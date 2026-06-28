"""RefundRequest endpoints (PRD §3.11)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_auth, require_roles
from models import base_record, serialize, touch
from response import object_response, array_response
from services.calculations import refund_amount
from services.case_service import first_run_steps
from services.listing import paginate
from services.refund_service import settle_cascade
from services.store import get_refund, get_case, fk_case
from validation import get_body, require_str, require_int, require_enum, parse_pagination

bp = Blueprint("refunds", __name__)

REASONS = {"ELIGIBILITY_DECLINE", "PATIENT_CANCEL", "GOODWILL"}
APPROVE_SETTLE_CASE_STATUSES = {"DECLINED", "PLAN_APPROVED", "ACTIVE"}


@bp.route("/refunds", methods=["POST"])
def open_refund():
    _, role = get_auth()
    require_roles(role, {"Patient", "BillingAdmin"})
    body = get_body()
    case_id = require_str(body, "case_id")
    reason = require_enum(body, "reason", REASONS)
    expected_case_version = require_int(body, "expected_case_version")
    # FK existence
    case = fk_case(case_id)
    # OCC check (priority 6)
    if expected_case_version != case["version"]:
        raise err("ERR_STALE_CASE_VERSION",
                  "expected_case_version does not match the case's current version.")

    rec = base_record(common_fields=True)
    rec.update({
        "case_id": case_id,
        "reason": reason,
        "status": "OPEN",
        "computed_refund_cents": 0,
        "restocking_fee_cents": 0,
    })
    db.refunds[rec["id"]] = rec
    # opening a refund increments the case's version by one
    touch(case)
    return object_response(serialize(rec), status=201)


@bp.route("/refunds/<rid>", methods=["GET"])
def fetch_refund(rid):
    _, role = get_auth()
    require_roles(role, {"Patient", "BillingAdmin"})
    rec = get_refund(rid)
    return object_response(serialize(rec), status=200)


@bp.route("/refunds", methods=["GET"])
def list_refunds():
    _, role = get_auth()
    require_roles(role, {"Patient", "BillingAdmin"})
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    records = list(db.refunds.values())
    if case_id is not None:
        records = [r for r in records if r["case_id"] == case_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/refunds/<rid>/approve", methods=["POST"])
def approve_refund(rid):
    _, role = get_auth()
    require_roles(role, {"BillingAdmin"})
    refund = get_refund(rid)
    case = get_case(refund["case_id"])
    if refund["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Refund must be OPEN to approve.")
    if case["status"] not in APPROVE_SETTLE_CASE_STATUSES:
        raise err("ERR_INVALID_STATE",
                  "Case must be DECLINED, PLAN_APPROVED, or ACTIVE to approve a refund.")

    # refund_amount over first-run steps only
    first_run = first_run_steps(case["id"])
    shipped_first_run = sum(1 for s in first_run if s["status"] == "SHIPPED")
    total_first_run_non_void = sum(1 for s in first_run if s["status"] != "VOID")
    # guaranteed >= 1 post-approval; guard divide-by-zero defensively
    if total_first_run_non_void == 0:
        total_first_run_non_void = 1
    computed, restocking = refund_amount(
        refund["reason"], case["amount_collected_cents"],
        case["total_contracted_cents"], shipped_first_run, total_first_run_non_void,
    )
    refund["computed_refund_cents"] = computed
    refund["restocking_fee_cents"] = restocking
    refund["status"] = "APPROVED"
    touch(refund)
    return object_response(serialize(refund), status=200)


@bp.route("/refunds/<rid>/reject", methods=["POST"])
def reject_refund(rid):
    _, role = get_auth()
    require_roles(role, {"BillingAdmin"})
    refund = get_refund(rid)
    if refund["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Refund must be OPEN to reject.")
    refund["status"] = "REJECTED"
    touch(refund)
    return object_response(serialize(refund), status=200)


@bp.route("/refunds/<rid>/settle", methods=["POST"])
def settle_refund(rid):
    _, role = get_auth()
    require_roles(role, {"BillingAdmin"})
    refund = get_refund(rid)
    case = get_case(refund["case_id"])
    if refund["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Refund must be APPROVED to settle.")
    if case["status"] not in APPROVE_SETTLE_CASE_STATUSES:
        raise err("ERR_INVALID_STATE",
                  "Case must be DECLINED, PLAN_APPROVED, or ACTIVE to settle a refund.")
    refund["status"] = "SETTLED"
    touch(refund)
    # drive case -> REFUNDED with full cascade
    case["refund_issued_cents"] = refund["computed_refund_cents"]
    settle_cascade(case)
    return object_response(serialize(refund), status=200)
