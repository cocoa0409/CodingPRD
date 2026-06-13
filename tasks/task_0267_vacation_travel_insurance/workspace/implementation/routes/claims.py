"""Claim endpoints (PRD §3.4, §3.6)."""
from flask import Blueprint, request, g

import errors
import response
from db import db
from middleware import require_roles
from services import common, serialize, claim_ops
from services.store_helpers import (
    make_record, touch, get_policy, get_insured, get_named_storm, get_claim,
)

bp = Blueprint("claims", __name__)

PERILS = {"CANCELLATION", "MEDICAL", "DELAY", "BAGGAGE"}
CANCELLATION_REASONS = {"COVERED_REASON", "CFAR", "NAMED_STORM"}
EXPENSE_CATEGORIES = {"PREPAID_TRIP", "MEDICAL_BILL", "BAGGAGE_ITEM", "DELAY_EXPENSE"}
DOC_TYPES = {"RECEIPT", "MEDICAL_REPORT", "CARRIER_DELAY_LETTER", "POLICE_REPORT", "OTHER"}


def _ensure_policy_owner(policy):
    if g.user_role == "Traveler" and policy["owner_traveler_id"] != g.user_id:
        raise errors.not_resource_owner("Traveler does not own this policy.")


def _ensure_claim_owner(claim):
    policy = db.policies[claim["policy_id"]]
    if g.user_role == "Traveler" and policy["owner_traveler_id"] != g.user_id:
        raise errors.not_resource_owner("Traveler does not own this claim.")


# --------------------------------------------------------------------------
# File a claim
# --------------------------------------------------------------------------
@bp.route("/claims", methods=["POST"])
@require_roles("Traveler")
def create_claim():
    body = common.get_json_body()

    policy_id = common.require_str(body, "policy_id")
    insured_traveler_id = common.require_str(body, "insured_traveler_id")
    peril = common.require_enum(body, "peril", PERILS)
    incident_at = common.require_datetime(body, "incident_at")
    named_storm_id = common.opt_str(body, "named_storm_id", default=None)
    cancellation_reason = common.opt_enum(body, "cancellation_reason", CANCELLATION_REASONS, default=None)
    delay_hours = common.opt_int(body, "delay_hours", default=0, minimum=0)
    involves_preexisting = common.opt_bool(body, "involves_preexisting", default=False)

    # Existence (priority 3), left-to-right: policy, insured, named storm.
    policy = get_policy(policy_id)
    insured = get_insured(insured_traveler_id)
    if named_storm_id is not None:
        get_named_storm(named_storm_id)

    # Ownership (priority 4)
    _ensure_policy_owner(policy)

    # Insured must belong to the policy (nested-resource referential integrity).
    if insured["policy_id"] != policy_id:
        raise errors.not_found("Insured traveler does not belong to the policy.")

    # Business: policy must be ACTIVE (priority 8)
    if policy["coverage_status"] != "ACTIVE":
        raise errors.conflict(errors.ERR_POLICY_NOT_ACTIVE, "Policy is not ACTIVE.")

    rec = make_record()
    rec.update({
        "policy_id": policy_id,
        "insured_traveler_id": insured_traveler_id,
        "named_storm_id": named_storm_id,
        "peril": peril,
        "cancellation_reason": cancellation_reason,
        "incident_at": body["incident_at"],
        "_incident_at_dt": incident_at,
        "delay_hours": delay_hours,
        "involves_preexisting": involves_preexisting,
        "provisional_amount_cents": 0,
        "approved_amount_cents": 0,
        "denial_reason": None,
        "status": "SUBMITTED",
    })

    plan = db.plans[policy["plan_id"]]

    # Filing deadline (priority 9): one-sided lateness gate at submission.
    if not claim_ops.filing_window_open(rec, plan):
        raise errors.conflict(errors.ERR_FILING_WINDOW_CLOSED, "Filing window has closed.")

    # Delay-event de-duplication (priority 15) — before persisting.
    if peril == "DELAY":
        claim_ops.enforce_delay_event_overlap(policy_id, incident_at, delay_hours)

    db.claims[rec["id"]] = rec
    claim_ops.refresh_provisional(rec)
    return response.success_object(serialize.claim_out(rec), status=201)


@bp.route("/claims/<claim_id>", methods=["GET"])
@require_roles("Any")
def get_claim_route(claim_id):
    rec = get_claim(claim_id)
    return response.success_object(serialize.claim_out(rec), status=200)


@bp.route("/claims", methods=["GET"])
@require_roles("Any")
def list_claims():
    items = list(db.claims.values())
    for field in ("policy_id", "insured_traveler_id", "named_storm_id", "peril", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [c for c in items if c.get(field) == val]
    items = common.sort_by_created(items)
    page, limit, offset, total = common.paginate(items)
    return response.success_array([serialize.claim_out(c) for c in page], limit, offset, total)


# --------------------------------------------------------------------------
# Expenses
# --------------------------------------------------------------------------
@bp.route("/claims/<claim_id>/expenses", methods=["POST"])
@require_roles("Traveler")
def add_expense(claim_id):
    claim = get_claim(claim_id)
    _ensure_claim_owner(claim)

    body = common.get_json_body()
    category = common.require_enum(body, "category", EXPENSE_CATEGORIES)
    description = common.require_str(body, "description")
    documented_amount_cents = common.require_int(body, "documented_amount_cents", minimum=0)
    prepaid_nonrefundable_cents = common.opt_int(body, "prepaid_nonrefundable_cents", default=0, minimum=0)
    supplier_refund_received_cents = common.opt_int(body, "supplier_refund_received_cents", default=0, minimum=0)
    item_value_cents = common.opt_int(body, "item_value_cents", default=0, minimum=0)

    # State: expenses may be added while SUBMITTED or INFO_REQUESTED.
    if claim["status"] not in ("SUBMITTED", "INFO_REQUESTED"):
        raise errors.invalid_state("Claim does not accept new expense lines in its current state.")

    rec = make_record()
    rec.update({
        "claim_id": claim_id,
        "category": category,
        "description": description,
        "documented_amount_cents": documented_amount_cents,
        "prepaid_nonrefundable_cents": prepaid_nonrefundable_cents,
        "supplier_refund_received_cents": supplier_refund_received_cents,
        "item_value_cents": item_value_cents,
    })
    db.claim_expenses[rec["id"]] = rec

    # Recompute provisional and bump claim version.
    claim_ops.refresh_provisional(claim)
    touch(claim)

    return response.success_object(serialize.claim_expense_out(rec), status=201)


@bp.route("/claims/<claim_id>/expenses", methods=["GET"])
@require_roles("Any")
def list_expenses(claim_id):
    get_claim(claim_id)
    items = [e for e in db.claim_expenses.values() if e["claim_id"] == claim_id]
    items = common.sort_by_created(items)
    page, limit, offset, total = common.paginate(items)
    return response.success_array([serialize.claim_expense_out(e) for e in page], limit, offset, total)


# --------------------------------------------------------------------------
# Documents (append-only)
# --------------------------------------------------------------------------
@bp.route("/claims/<claim_id>/documents", methods=["POST"])
@require_roles("Traveler")
def add_document(claim_id):
    claim = get_claim(claim_id)
    _ensure_claim_owner(claim)

    body = common.get_json_body()
    doc_type = common.require_enum(body, "doc_type", DOC_TYPES)
    file_ref = common.require_str(body, "file_ref")

    # State: documents may be added while SUBMITTED or INFO_REQUESTED.
    if claim["status"] not in ("SUBMITTED", "INFO_REQUESTED"):
        raise errors.invalid_state("Claim does not accept new documents in its current state.")

    rec = make_record(with_version=False)
    # ClaimDocument is append-only: id + created_at only (no updated_at/version).
    del rec["updated_at"]
    rec.update({
        "claim_id": claim_id,
        "doc_type": doc_type,
        "file_ref": file_ref,
        "uploaded_by_traveler_id": g.user_id,
    })
    db.claim_documents[rec["id"]] = rec
    return response.success_object(serialize.claim_document_out(rec), status=201)


@bp.route("/claims/<claim_id>/documents", methods=["GET"])
@require_roles("Any")
def list_documents(claim_id):
    get_claim(claim_id)
    items = [d for d in db.claim_documents.values() if d["claim_id"] == claim_id]
    items = common.sort_by_created(items)
    page, limit, offset, total = common.paginate(items)
    return response.success_array([serialize.claim_document_out(d) for d in page], limit, offset, total)


# --------------------------------------------------------------------------
# Adjudication transitions
# --------------------------------------------------------------------------
@bp.route("/claims/<claim_id>/start-review", methods=["POST"])
@require_roles("ClaimsAdjuster")
def start_review(claim_id):
    claim = get_claim(claim_id)
    if claim["status"] != "SUBMITTED":
        raise errors.invalid_state("Claim is not SUBMITTED.")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return response.success_object(serialize.claim_out(claim), status=200)


@bp.route("/claims/<claim_id>/request-info", methods=["POST"])
@require_roles("ClaimsAdjuster")
def request_info(claim_id):
    claim = get_claim(claim_id)
    if claim["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Claim is not UNDER_REVIEW.")
    claim["status"] = "INFO_REQUESTED"
    touch(claim)
    return response.success_object(serialize.claim_out(claim), status=200)


@bp.route("/claims/<claim_id>/resubmit", methods=["POST"])
@require_roles("Traveler")
def resubmit(claim_id):
    claim = get_claim(claim_id)
    _ensure_claim_owner(claim)
    if claim["status"] != "INFO_REQUESTED":
        raise errors.invalid_state("Claim is not INFO_REQUESTED.")
    from services.store_helpers import documents_for_claim
    if len(documents_for_claim(claim_id)) == 0:
        raise errors.conflict(errors.ERR_DOCUMENTATION_MISSING, "No supporting document on the claim.")
    claim["status"] = "UNDER_REVIEW"
    claim_ops.refresh_provisional(claim)
    touch(claim)
    return response.success_object(serialize.claim_out(claim), status=200)


@bp.route("/claims/<claim_id>/approve", methods=["POST"])
@require_roles("ClaimsAdjuster")
def approve(claim_id):
    claim = get_claim(claim_id)
    claim_ops.approve_claim(claim)
    return response.success_object(serialize.claim_out(claim), status=200)


@bp.route("/claims/<claim_id>/deny", methods=["POST"])
@require_roles("ClaimsAdjuster")
def deny(claim_id):
    claim = get_claim(claim_id)
    body = common.get_json_body()
    denial_reason = common.require_str(body, "denial_reason")
    if claim["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Claim is not UNDER_REVIEW.")
    claim["denial_reason"] = denial_reason
    claim["status"] = "DENIED"
    touch(claim)
    return response.success_object(serialize.claim_out(claim), status=200)
