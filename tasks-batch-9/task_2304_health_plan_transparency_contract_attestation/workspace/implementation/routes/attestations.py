"""Attestation endpoints (PRD 3.8)."""

from flask import Blueprint

import calc
import clock
import db
import domain
import guards
import response

bp = Blueprint("attestations", __name__)

READ_ROLES = ("PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor")


@bp.route("/compliance/attestations", methods=["POST"])
def create_attestation():
    user_id, _role = guards.authorize("ComplianceOfficer")
    body = guards.read_body()
    plan_year_id = guards.field(body, "plan_year_id", "string")
    attestation_type = guards.field(
        body, "attestation_type", "enum", enum=("GAG_CLAUSE_CEE",)
    )
    doc_count = guards.field(body, "contract_terms_doc_count", "integer")
    expected_version = guards.field(body, "expected_plan_year_version", "integer")
    guards.require(
        doc_count >= 0,
        "ERR_INVALID_REQUEST",
        "contract_terms_doc_count must be at least 0.",
    )
    plan_year = guards.fetch("plan_year", plan_year_id)
    # Ladder step 8 — optimistic concurrency on the plan year.
    guards.occ(expected_version, plan_year, "ERR_STALE_PLAN_YEAR_VERSION")
    guards.not_frozen(plan_year)

    record = db.common_fields()
    record.update({
        "plan_year_id": plan_year_id,
        "attestation_type": attestation_type,
        "contract_terms_doc_count": doc_count,
        "status": "DRAFT",
        "prepared_by_user_id": user_id,
        "submitted_by_user_id": None,
        "submitted_at": None,
        "signature_statement": None,
        "rejection_reason": None,
        "revision_round": 0,
        "void_reason": None,
    })
    # A new draft supersedes any earlier draft of the same plan year.
    for prior in db.attestations_of_plan_year(plan_year_id):
        if prior["status"] == "DRAFT":
            prior["status"] = "VOIDED"
            prior["void_reason"] = "SUPERSEDED_BY_NEWER_DRAFT"
            db.bump(prior)
    db.attestations[record["id"]] = record
    with db.txn(plan_year):
        domain.refresh_attestation_status(plan_year)
    return response.created_response(response.public(record))


@bp.route("/compliance/attestations/<row_id>", methods=["GET"])
def get_attestation(row_id):
    guards.authorize(*READ_ROLES)
    return response.object_response(
        response.public(guards.fetch("attestation", row_id))
    )


@bp.route("/compliance/attestations", methods=["GET"])
def list_attestations():
    guards.authorize(*READ_ROLES)
    limit, offset = guards.pagination()
    guards.filter_fk("plan_year", "plan_year_id")
    rows = guards.apply_filters(db.ordered(db.attestations), [
        ("plan_year_id", "plan_year_id", None),
        ("status", "status", None),
    ])
    page, total = guards.paginate(rows, limit, offset)
    return response.array_response(
        [response.public(r) for r in page], limit, offset, total
    )


@bp.route("/compliance/attestations/<row_id>/submit", methods=["POST"])
def submit_attestation(row_id):
    user_id, _role = guards.authorize("ComplianceOfficer")
    attestation = guards.fetch("attestation", row_id)
    body = guards.read_body()
    signature = guards.field(body, "signature_statement", "string")
    plan_year = db.plan_year_of_attestation(attestation)
    guards.not_frozen(plan_year)
    guards.state_is(attestation["status"], "DRAFT")
    guards.require(
        plan_year is not None and plan_year["lifecycle_status"] == "ACTIVE",
        "ERR_INVALID_STATE_TRANSITION",
        "The plan year must be ACTIVE to submit an attestation.",
    )
    # Ladder step 11 — the posture gate outranks segregation of duties.
    guards.require(
        plan_year["compliance_posture"] in ("COMPLIANT", "AT_RISK"),
        "ERR_POSTURE_BLOCKS_ATTESTATION",
        "A %s plan year may not have its attestation submitted."
        % plan_year["compliance_posture"],
    )
    # Ladder step 12 — segregation of duties.
    guards.require(
        user_id != attestation["prepared_by_user_id"],
        "ERR_SEGREGATION_OF_DUTIES",
        "The submitter must differ from the preparer.",
    )
    # Ladder step 13 — every material contract gag-COMPLIANT.
    guards.require(
        all(
            contract["gag_review_status"] == "COMPLIANT"
            for contract in db.contracts_of_plan_year(plan_year["id"])
            if contract["contract_type"] in calc.MATERIAL_CONTRACT_TYPES
        ),
        "ERR_GAG_CLAUSES_OUTSTANDING",
        "A material contract is not yet gag-clause COMPLIANT.",
    )
    # Ladder step 14 — evidence attached.
    guards.require(
        attestation["contract_terms_doc_count"] >= 1,
        "ERR_CONTRACT_TERMS_DOC_REQUIRED",
        "contract_terms_doc_count must be at least 1 to submit.",
    )
    with db.txn(attestation):
        attestation["status"] = "SUBMITTED"
        attestation["submitted_by_user_id"] = user_id
        attestation["submitted_at"] = clock.now_iso()
        attestation["signature_statement"] = signature
    with db.txn(plan_year):
        domain.refresh_attestation_status(plan_year)
    return response.object_response(response.public(attestation))


def _adjudication_guards(user_id, attestation):
    plan_year = db.plan_year_of_attestation(attestation)
    guards.not_frozen(plan_year)
    guards.state_is(attestation["status"], "SUBMITTED")
    # Ladder step 12 — the auditor differs from preparer and submitter.
    guards.require(
        user_id != attestation["prepared_by_user_id"]
        and user_id != attestation["submitted_by_user_id"],
        "ERR_SEGREGATION_OF_DUTIES",
        "The adjudicating auditor must differ from the preparer and the submitter.",
    )
    return plan_year


@bp.route("/compliance/attestations/<row_id>/accept", methods=["POST"])
def accept_attestation(row_id):
    user_id, _role = guards.authorize("ExternalAuditor")
    attestation = guards.fetch("attestation", row_id)
    body = guards.read_body()
    guards.field(body, "acceptance_note", "string", required=False)
    plan_year = _adjudication_guards(user_id, attestation)
    with db.txn(attestation):
        attestation["status"] = "ACCEPTED"
    # Acceptance posts NO ledger entry; it only closes the deficiency.
    with db.txn(plan_year):
        domain.refresh_attestation_status(plan_year)
        domain.recompute_posture(plan_year)
    return response.object_response(response.public(attestation))


@bp.route("/compliance/attestations/<row_id>/reject", methods=["POST"])
def reject_attestation(row_id):
    user_id, _role = guards.authorize("ExternalAuditor")
    attestation = guards.fetch("attestation", row_id)
    body = guards.read_body()
    reason = guards.field(body, "rejection_reason", "string")
    plan_year = _adjudication_guards(user_id, attestation)
    with db.txn(attestation):
        attestation["status"] = "REJECTED"
        attestation["rejection_reason"] = reason
    with db.txn(plan_year):
        domain.refresh_attestation_status(plan_year)
        domain.post_accrual(
            plan_year,
            "ATTESTATION_LATE",
            clock.today_iso(),
            "Attestation %s was rejected by the external auditor." % attestation["id"],
            user_id,
        )
        domain.recompute_exposure(plan_year)
        domain.recompute_posture(plan_year)
    return response.object_response(response.public(attestation))


@bp.route("/compliance/attestations/<row_id>/revise", methods=["POST"])
def revise_attestation(row_id):
    user_id, _role = guards.authorize("ComplianceOfficer")
    attestation = guards.fetch("attestation", row_id)
    body = guards.read_body()
    doc_count = guards.field(body, "contract_terms_doc_count", "integer")
    plan_year = db.plan_year_of_attestation(attestation)
    guards.not_frozen(plan_year)
    guards.state_is(attestation["status"], "REJECTED")
    # Ladder step 14 — evidence attached.
    guards.require(
        doc_count >= 1,
        "ERR_CONTRACT_TERMS_DOC_REQUIRED",
        "contract_terms_doc_count must be at least 1.",
    )
    with db.txn(attestation):
        attestation["status"] = "DRAFT"
        attestation["contract_terms_doc_count"] = doc_count
        attestation["revision_round"] = attestation["revision_round"] + 1
        attestation["rejection_reason"] = None
        attestation["submitted_by_user_id"] = None
        attestation["submitted_at"] = None
        attestation["prepared_by_user_id"] = user_id
    with db.txn(plan_year):
        domain.refresh_attestation_status(plan_year)
    return response.object_response(response.public(attestation))
