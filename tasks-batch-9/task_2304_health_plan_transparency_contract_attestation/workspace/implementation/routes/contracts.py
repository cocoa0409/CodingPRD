"""ServiceProviderContract endpoints — the gag-clause dimension (PRD 3.1, 3.4)."""

from flask import Blueprint

import calc
import clock
import db
import domain
import guards
import response

bp = Blueprint("contracts", __name__)

CONTRACT_TYPES = ("TPA", "PBM", "BROKER", "CONSULTANT", "NETWORK_VENDOR")


@bp.route("/compliance/contracts", methods=["POST"])
def create_contract():
    guards.authorize("PlanSponsorAdmin")
    body = guards.read_body()
    plan_year_id = guards.field(body, "plan_year_id", "string")
    vendor_id = guards.field(body, "vendor_id", "string")
    contract_type = guards.field(body, "contract_type", "enum", enum=CONTRACT_TYPES)
    term_start = guards.field(body, "term_start", "date")
    term_end = guards.field(body, "term_end", "date")
    annual_fee_cents = guards.field(body, "annual_fee_cents", "integer")
    guards.require(
        annual_fee_cents >= 0,
        "ERR_INVALID_REQUEST",
        "annual_fee_cents must be at least 0.",
    )
    plan_year = guards.fetch("plan_year", plan_year_id)
    guards.fetch("vendor", vendor_id)
    guards.not_frozen(plan_year)
    # Ladder step 19 — the contract term is half-open and must be non-degenerate.
    guards.require(
        clock.parse_date(term_end) > clock.parse_date(term_start),
        "ERR_INVALID_INTERVAL",
        "term_end must be strictly after term_start.",
    )
    record = db.common_fields()
    record.update({
        "plan_year_id": plan_year_id,
        "vendor_id": vendor_id,
        "contract_type": contract_type,
        "term_start": term_start,
        "term_end": term_end,
        "annual_fee_cents": annual_fee_cents,
        "gag_review_status": "NOT_REVIEWED",
        "data_rights_status": "NOT_SECURED",
        "clause_inventory_count": 0,
        "prohibited_clause_count": 0,
        "remediation_round": 0,
        "gag_non_compliant_since": None,
        "compensation_disclosure_required": contract_type in ("BROKER", "CONSULTANT"),
    })
    db.contracts[record["id"]] = record
    return response.created_response(response.public(record))


@bp.route("/compliance/contracts/<row_id>", methods=["GET"])
def get_contract(row_id):
    role = guards.authorize(
        "PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor", "VendorContact"
    )[1]
    contract = guards.fetch("contract", row_id)
    guards.vendor_identity(role, guards.caller_id())
    return response.object_response(response.public(contract))


@bp.route("/compliance/contracts", methods=["GET"])
def list_contracts():
    guards.authorize("PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor")
    limit, offset = guards.pagination()
    guards.filter_fk("plan_year", "plan_year_id")
    guards.filter_fk("vendor", "vendor_id")
    rows = guards.apply_filters(db.ordered(db.contracts), [
        ("plan_year_id", "plan_year_id", None),
        ("vendor_id", "vendor_id", None),
        ("contract_type", "contract_type", None),
        ("gag_review_status", "gag_review_status", None),
        ("data_rights_status", "data_rights_status", None),
    ])
    page, total = guards.paginate(rows, limit, offset)
    return response.array_response(
        [response.public(r) for r in page], limit, offset, total
    )


@bp.route("/compliance/contracts/<row_id>/gag-review", methods=["POST"])
def gag_review(row_id):
    guards.authorize("ComplianceOfficer")
    contract = guards.fetch("contract", row_id)
    body = guards.read_body()
    inventory = guards.field(body, "clause_inventory_count", "integer")
    prohibited = guards.field(body, "prohibited_clause_count", "integer")
    guards.field(body, "review_note", "string", required=False)
    plan_year = db.plan_year_of_contract(contract)
    guards.not_frozen(plan_year)
    guards.state_is(contract["gag_review_status"], "NOT_REVIEWED")
    # Ladder step 43 — clause counts internally consistent.
    guards.require(
        inventory >= 0 and prohibited >= 0 and prohibited <= inventory,
        "ERR_CLAUSE_COUNT_INCONSISTENT",
        "prohibited_clause_count must be between 0 and clause_inventory_count.",
    )
    with db.txn(contract):
        contract["gag_review_status"] = "IN_REVIEW"
        contract["clause_inventory_count"] = inventory
        contract["prohibited_clause_count"] = prohibited
    return response.object_response(response.public(contract))


@bp.route("/compliance/contracts/<row_id>/request-remediation", methods=["POST"])
def request_remediation(row_id):
    guards.authorize("ComplianceOfficer")
    contract = guards.fetch("contract", row_id)
    body = guards.read_body()
    guards.field(body, "remediation_request_note", "string", required=False)
    plan_year = db.plan_year_of_contract(contract)
    guards.not_frozen(plan_year)
    guards.state_is(contract["gag_review_status"], "IN_REVIEW")
    guards.require(
        contract["prohibited_clause_count"] >= 1,
        "ERR_INVALID_STATE_TRANSITION",
        "Remediation is only requestable while prohibited clauses remain.",
    )
    # Ladder step 28 — remediation rounds remaining.
    guards.require(
        contract["remediation_round"] < calc.MAX_REMEDIATION_ROUNDS,
        "ERR_REMEDIATION_ROUNDS_EXHAUSTED",
        "The contract has used both remediation rounds.",
    )
    with db.txn(contract):
        contract["gag_review_status"] = "REMEDIATION_REQUESTED"
    return response.object_response(response.public(contract))


@bp.route("/compliance/contracts/<row_id>/submit-remediation", methods=["POST"])
def submit_remediation(row_id):
    user_id, role = guards.authorize("VendorContact")
    contract = guards.fetch("contract", row_id)
    body = guards.read_body()
    prohibited = guards.field(body, "prohibited_clause_count", "integer")
    guards.field(body, "remediation_note", "string", required=False)
    # Ladder step 7 — vendor scope.
    guards.vendor_scope(role, user_id, contract["vendor_id"])
    plan_year = db.plan_year_of_contract(contract)
    guards.not_frozen(plan_year)
    guards.state_is(contract["gag_review_status"], "REMEDIATION_REQUESTED")
    # Ladder step 40 — vendor identity resolves.
    guards.vendor_identity(role, user_id)
    # Ladder step 43 — clause counts internally consistent.
    guards.require(
        prohibited >= 0 and prohibited <= contract["clause_inventory_count"],
        "ERR_CLAUSE_COUNT_INCONSISTENT",
        "prohibited_clause_count must be between 0 and clause_inventory_count.",
    )
    with db.txn(contract):
        contract["gag_review_status"] = "IN_REVIEW"
        contract["prohibited_clause_count"] = prohibited
        contract["remediation_round"] = contract["remediation_round"] + 1
    return response.object_response(response.public(contract))


@bp.route("/compliance/contracts/<row_id>/clear-gag", methods=["POST"])
def clear_gag(row_id):
    guards.authorize("ComplianceOfficer")
    contract = guards.fetch("contract", row_id)
    body = guards.read_body()
    guards.field(body, "clearance_note", "string", required=False)
    plan_year = db.plan_year_of_contract(contract)
    guards.not_frozen(plan_year)
    guards.state_is(contract["gag_review_status"], "IN_REVIEW")
    # Ladder step 29 — clearance requires a clean contract.
    guards.require(
        contract["prohibited_clause_count"] == 0,
        "ERR_PROHIBITED_CLAUSES_PRESENT",
        "Prohibited clauses remain outstanding.",
    )
    with db.txn(contract):
        contract["gag_review_status"] = "COMPLIANT"
        contract["gag_non_compliant_since"] = None
    with db.txn(plan_year):
        domain.recompute_posture(plan_year)
    return response.object_response(response.public(contract))


@bp.route("/compliance/contracts/<row_id>/escalate-gag", methods=["POST"])
def escalate_gag(row_id):
    user_id, _role = guards.authorize("ComplianceOfficer")
    contract = guards.fetch("contract", row_id)
    body = guards.read_body()
    guards.field(body, "escalation_note", "string", required=False)
    plan_year = db.plan_year_of_contract(contract)
    guards.not_frozen(plan_year)
    guards.state_is(
        contract["gag_review_status"], "IN_REVIEW", "REMEDIATION_REQUESTED"
    )
    # Ladder step 29 — escalation requires at least one prohibited clause.
    guards.require(
        contract["prohibited_clause_count"] >= 1,
        "ERR_PROHIBITED_CLAUSES_PRESENT",
        "Escalation requires at least one prohibited clause.",
    )
    onset = clock.today_iso()
    # CASCADE-A links 1-5.
    with db.txn(contract):
        contract["gag_review_status"] = "NON_COMPLIANT"
        contract["gag_non_compliant_since"] = onset
    with db.txn(plan_year):
        domain.post_accrual(
            plan_year,
            "GAG_CLAUSE",
            onset,
            "Gag-clause review escalated to NON_COMPLIANT for contract %s."
            % contract["id"],
            user_id,
        )
        domain.recompute_exposure(plan_year)
        domain.recompute_posture(plan_year)
    return response.object_response(response.public(contract))
