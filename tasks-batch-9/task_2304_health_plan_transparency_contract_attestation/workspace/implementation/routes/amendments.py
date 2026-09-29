"""ContractAmendment endpoints — the data-rights dimension (PRD 3.5)."""

from flask import Blueprint

import calc
import clock
import db
import guards
import response

bp = Blueprint("amendments", __name__)

AMENDMENT_TYPES = ("DATA_RIGHTS", "GAG_CLAUSE_REMOVAL", "COOPERATION_SLA")
OPEN_STATUSES = ("PROPOSED", "COUNTERED")


@bp.route("/compliance/contract-amendments", methods=["POST"])
def create_amendment():
    guards.authorize("PlanSponsorAdmin")
    body = guards.read_body()
    contract_id = guards.field(body, "contract_id", "string")
    amendment_type = guards.field(body, "amendment_type", "enum", enum=AMENDMENT_TYPES)
    proposed_terms = guards.field(body, "proposed_terms_summary", "string")
    data_rights_granted = guards.field(body, "data_rights_granted", "boolean")
    expires_at = guards.field(body, "expires_at", "datetime")
    expected_version = guards.field(body, "expected_contract_version", "integer")
    contract = guards.fetch("contract", contract_id)
    # Ladder step 8 — optimistic concurrency on the contract.
    guards.occ(expected_version, contract, "ERR_STALE_CONTRACT_VERSION")
    plan_year = db.plan_year_of_contract(contract)
    guards.not_frozen(plan_year)
    # Ladder step 19 — expires_at must be strictly in the future.
    guards.require(
        clock.parse_datetime(expires_at) > clock.now(),
        "ERR_INVALID_INTERVAL",
        "expires_at must be strictly after the logical clock.",
    )

    record = db.common_fields()
    record.update({
        "contract_id": contract_id,
        "amendment_type": amendment_type,
        "proposed_terms_summary": proposed_terms,
        "data_rights_granted": data_rights_granted,
        "expires_at": expires_at,
        "status": "PROPOSED",
        "round": 1,
        "counter_terms_summary": None,
        "executed_at": None,
        "executed_terms_note": None,
        "withdrawal_reason": None,
    })

    # Supersede the prior open amendment of the same contract and type.
    for prior in db.amendments_of_contract(contract_id):
        if prior["amendment_type"] == amendment_type and prior["status"] in OPEN_STATUSES:
            prior["status"] = "WITHDRAWN"
            prior["withdrawal_reason"] = "SUPERSEDED_BY_NEWER_AMENDMENT"
            db.bump(prior)

    db.amendments[record["id"]] = record

    if amendment_type == "DATA_RIGHTS" and contract["data_rights_status"] == "NOT_SECURED":
        with db.txn(contract):
            contract["data_rights_status"] = "PENDING_AMENDMENT"

    return response.created_response(response.public(record))


@bp.route("/compliance/contract-amendments/<row_id>", methods=["GET"])
def get_amendment(row_id):
    role = guards.authorize(
        "PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor", "VendorContact"
    )[1]
    amendment = guards.fetch("amendment", row_id)
    guards.vendor_identity(role, guards.caller_id())
    return response.object_response(response.public(amendment))


@bp.route("/compliance/contract-amendments", methods=["GET"])
def list_amendments():
    role = guards.authorize(
        "PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor", "VendorContact"
    )[1]
    limit, offset = guards.pagination()
    guards.filter_fk("contract", "contract_id")
    guards.vendor_identity(role, guards.caller_id())
    rows = guards.apply_filters(db.ordered(db.amendments), [
        ("contract_id", "contract_id", None),
        ("amendment_type", "amendment_type", None),
        ("status", "status", None),
    ])
    page, total = guards.paginate(rows, limit, offset)
    return response.array_response(
        [response.public(r) for r in page], limit, offset, total
    )


@bp.route("/compliance/contract-amendments/<row_id>/counter", methods=["POST"])
def counter_amendment(row_id):
    user_id, role = guards.authorize("VendorContact")
    amendment = guards.fetch("amendment", row_id)
    body = guards.read_body()
    counter_terms = guards.field(body, "counter_terms_summary", "string")
    contract = db.contracts.get(amendment["contract_id"])
    # Ladder step 7 — vendor scope.
    guards.vendor_scope(role, user_id, contract["vendor_id"] if contract else None)
    plan_year = db.plan_year_of_amendment(amendment)
    guards.not_frozen(plan_year)
    guards.state_is(amendment["status"], "PROPOSED")
    # Ladder step 25 — the amendment must not have expired.
    guards.require(
        clock.now() <= clock.parse_datetime(amendment["expires_at"]),
        "ERR_AMENDMENT_EXPIRED",
        "The amendment expired at %s." % amendment["expires_at"],
    )
    # Ladder step 40 — vendor identity resolves.
    guards.vendor_identity(role, user_id)
    with db.txn(amendment):
        amendment["status"] = "COUNTERED"
        amendment["counter_terms_summary"] = counter_terms
    return response.object_response(response.public(amendment))


@bp.route("/compliance/contract-amendments/<row_id>/revise-proposal", methods=["POST"])
def revise_proposal(row_id):
    guards.authorize("PlanSponsorAdmin")
    amendment = guards.fetch("amendment", row_id)
    body = guards.read_body()
    proposed_terms = guards.field(body, "proposed_terms_summary", "string")
    data_rights_granted = guards.field(body, "data_rights_granted", "boolean")
    plan_year = db.plan_year_of_amendment(amendment)
    guards.not_frozen(plan_year)
    guards.state_is(amendment["status"], "COUNTERED")
    # Ladder step 25 — expiry outranks the round cap.
    guards.require(
        clock.now() <= clock.parse_datetime(amendment["expires_at"]),
        "ERR_AMENDMENT_EXPIRED",
        "The amendment expired at %s." % amendment["expires_at"],
    )
    # Ladder step 27 — negotiation rounds remaining.
    guards.require(
        amendment["round"] < calc.MAX_NEGOTIATION_ROUNDS,
        "ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
        "The amendment has used all three negotiation rounds.",
    )
    with db.txn(amendment):
        amendment["status"] = "PROPOSED"
        amendment["proposed_terms_summary"] = proposed_terms
        amendment["data_rights_granted"] = data_rights_granted
        amendment["round"] = amendment["round"] + 1
    return response.object_response(response.public(amendment))


@bp.route("/compliance/contract-amendments/<row_id>/execute", methods=["POST"])
def execute_amendment(row_id):
    guards.authorize("PlanSponsorAdmin")
    amendment = guards.fetch("amendment", row_id)
    body = guards.read_body()
    note = guards.field(body, "executed_terms_note", "string", required=False)
    contract = db.contracts.get(amendment["contract_id"])
    plan_year = db.plan_year_of_amendment(amendment)
    guards.not_frozen(plan_year)
    guards.state_is(amendment["status"], "PROPOSED")
    # Ladder step 25 — the amendment must not have expired.
    guards.require(
        clock.now() <= clock.parse_datetime(amendment["expires_at"]),
        "ERR_AMENDMENT_EXPIRED",
        "The amendment expired at %s." % amendment["expires_at"],
    )
    # Ladder step 26 — a DATA_RIGHTS amendment must actually grant them.
    if amendment["amendment_type"] == "DATA_RIGHTS":
        guards.require(
            amendment["data_rights_granted"] is True,
            "ERR_DATA_RIGHTS_NOT_GRANTED",
            "data_rights_granted must be true to execute a DATA_RIGHTS amendment.",
        )
    with db.txn(amendment):
        amendment["status"] = "EXECUTED"
        amendment["executed_at"] = clock.now_iso()
        amendment["executed_terms_note"] = note
    if contract is not None:
        if amendment["amendment_type"] == "DATA_RIGHTS":
            with db.txn(contract):
                contract["data_rights_status"] = "SECURED"
        elif amendment["amendment_type"] == "GAG_CLAUSE_REMOVAL":
            with db.txn(contract):
                contract["prohibited_clause_count"] = 0
    return response.object_response(response.public(amendment))
