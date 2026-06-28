"""Account endpoints: CRUD + work_status/contact_status transitions."""
from flask import Blueprint, request

from clock import clock, parse_iso8601, format_iso8601, add_days
from db import db, stamp_create, touch
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_VALIDATION_ALREADY_SENT, ERR_CEASE_COMMUNICATION, ERR_VALIDATION_HOLD,
)
from middleware import require_roles
from response import object_response, array_response
from serializers import serialize_account
from pagination import paginate
from validation import get_body, require_str, require_int, optional_enum, invalid, optional_int
from services.transitions import recall_cascade, TERMINAL_WORK

bp = Blueprint("accounts", __name__)

SOL_ANCHORS = {"CHARGE_OFF", "LAST_PAYMENT"}


def _get_account_or_404(aid):
    a = db.accounts.get(aid)
    if a is None:
        raise ApiError(*ERR_NOT_FOUND, message="Account not found")
    return a


def _has_active_validation_hold(account):
    """True iff an OPEN/INVESTIGATING/REOPENED VALIDATION dispute with
    within_validation_window=true exists on the account."""
    for d in db.disputes.values():
        if d["account_id"] != account["id"]:
            continue
        if d["dispute_type"] != "VALIDATION":
            continue
        if d["status"] in ("OPEN", "INVESTIGATING", "REOPENED") and d["within_validation_window"]:
            return True
    return False


@bp.route("/accounts", methods=["POST"])
@require_roles("Creditor")
def create_account():
    body = get_body()
    creditor_id = require_str(body, "creditor_id")
    consumer_id = require_str(body, "consumer_id")
    # Existence checks (left-to-right) before body well-formedness of the rest.
    if creditor_id not in db.creditors:
        raise ApiError(*ERR_NOT_FOUND, message="Creditor not found")
    if consumer_id not in db.consumers:
        raise ApiError(*ERR_NOT_FOUND, message="Consumer not found")
    principal = require_int(body, "original_principal_cents")
    if principal <= 0:
        invalid("original_principal_cents must be greater than zero")
    charge_off_raw = require_str(body, "charge_off_date")
    if parse_iso8601(charge_off_raw) is None:
        invalid("charge_off_date must be a valid ISO 8601 timestamp")
    sol_years = require_int(body, "sol_years")
    if sol_years <= 0:
        invalid("sol_years must be greater than zero")
    sol_anchor = optional_enum(body, "sol_anchor_basis", SOL_ANCHORS, default="CHARGE_OFF")

    now = format_iso8601(clock.now)
    a = stamp_create({
        "creditor_id": creditor_id,
        "consumer_id": consumer_id,
        "original_principal_cents": principal,
        "balance_cents": principal,
        "amount_collected_cents": 0,
        "amount_settled_forgiven_cents": 0,
        "charge_off_date": format_iso8601(parse_iso8601(charge_off_raw)),
        "last_payment_date": None,
        "sol_years": sol_years,
        "sol_anchor_basis": sol_anchor,
        "placement_date": now,
        "validation_notice_sent_at": None,
        "work_status": "PLACED",
        "contact_status": "PRE_VALIDATION",
        "last_conversation_at": None,
        "commission_earned_cents": 0,
    })
    db.accounts[a["id"]] = a
    return object_response(serialize_account(a), status=201)


@bp.route("/accounts/<aid>", methods=["GET"])
@require_roles("Creditor", "Collector", "ComplianceOfficer", "BureauOperator", "System")
def get_account(aid):
    a = _get_account_or_404(aid)
    return object_response(serialize_account(a), status=200)


@bp.route("/accounts", methods=["GET"])
@require_roles("Creditor", "Collector", "ComplianceOfficer", "BureauOperator", "System")
def list_accounts():
    items = list(db.accounts.values())
    creditor_id = request.args.get("creditor_id")
    consumer_id = request.args.get("consumer_id")
    work_status = request.args.get("work_status")
    contact_status = request.args.get("contact_status")
    if creditor_id:
        items = [a for a in items if a["creditor_id"] == creditor_id]
    if consumer_id:
        items = [a for a in items if a["consumer_id"] == consumer_id]
    if work_status:
        items = [a for a in items if a["work_status"] == work_status]
    if contact_status:
        items = [a for a in items if a["contact_status"] == contact_status]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_account(a) for a in page], limit, offset, total)


@bp.route("/accounts/<aid>/send-validation-notice", methods=["POST"])
@require_roles("Collector")
def send_validation_notice(aid):
    a = _get_account_or_404(aid)
    # PRD §3.3: "permitted only while the account has not already had a notice
    # sent — that is, while validation_notice_sent_at is null; a repeat attempt is
    # rejected with ERR_VALIDATION_ALREADY_SENT." This repeat-notice guard is the
    # precondition that defines the transition, so it precedes the generic state
    # check (an account whose notice was sent has work_status VALIDATION_SENT).
    if a.get("validation_notice_sent_at") is not None:
        raise ApiError(*ERR_VALIDATION_ALREADY_SENT, message="Validation notice already sent")
    # state: must be PLACED for this transition.
    if a["work_status"] != "PLACED":
        raise ApiError(*ERR_INVALID_STATE, message="Account is not in PLACED state")
    now = clock.now
    a["validation_notice_sent_at"] = format_iso8601(now)
    a["work_status"] = "VALIDATION_SENT"
    a["contact_status"] = "CONTACTABLE"
    touch(a)
    return object_response(serialize_account(a), status=200)


@bp.route("/accounts/<aid>/begin-work", methods=["POST"])
@require_roles("Collector")
def begin_work(aid):
    a = _get_account_or_404(aid)
    # state: defined only from VALIDATION_SENT.
    if a["work_status"] != "VALIDATION_SENT":
        raise ApiError(*ERR_INVALID_STATE, message="Account is not in VALIDATION_SENT state")
    # guardrails (priority order): cease first, then validation hold.
    if a["contact_status"] == "CEASED":
        raise ApiError(*ERR_CEASE_COMMUNICATION, message="Account communication ceased")
    if _has_active_validation_hold(a):
        raise ApiError(*ERR_VALIDATION_HOLD, message="In-window validation dispute holds collection")
    a["work_status"] = "WORKING"
    touch(a)
    return object_response(serialize_account(a), status=200)


@bp.route("/accounts/<aid>/cease-communication", methods=["POST"])
@require_roles("ComplianceOfficer")
def cease_communication(aid):
    a = _get_account_or_404(aid)
    # Defined from PRE_VALIDATION, CONTACTABLE, VALIDATION_HELD. CEASED is terminal.
    if a["contact_status"] == "CEASED":
        raise ApiError(*ERR_INVALID_STATE, message="Account communication already ceased")
    a["contact_status"] = "CEASED"
    touch(a)
    return object_response(serialize_account(a), status=200)


@bp.route("/accounts/<aid>/recall", methods=["POST"])
@require_roles("Creditor")
def recall(aid):
    a = _get_account_or_404(aid)
    body = get_body()
    expected = require_int(body, "expected_account_version")
    # OCC check (412) before state per scaffold precondition order.
    if expected != a["version"]:
        raise ApiError(*ERR_STALE_VERSION, message="expected_account_version does not match")
    if a["work_status"] in ("CLOSED_PAID", "CLOSED_UNCOLLECTIBLE", "RECALLED"):
        raise ApiError(*ERR_INVALID_STATE, message="Account cannot be recalled from its current state")
    a["work_status"] = "RECALLED"
    touch(a)  # increments version by 1
    recall_cascade(a)
    return object_response(serialize_account(a), status=200)


@bp.route("/accounts/<aid>/close-uncollectible", methods=["POST"])
@require_roles("Creditor")
def close_uncollectible(aid):
    a = _get_account_or_404(aid)
    if a["work_status"] in ("CLOSED_PAID", "CLOSED_UNCOLLECTIBLE"):
        raise ApiError(*ERR_INVALID_STATE, message="Account already closed")
    a["work_status"] = "CLOSED_UNCOLLECTIBLE"
    from services.accounts import recompute_commission
    recompute_commission(a)
    touch(a)
    return object_response(serialize_account(a), status=200)
