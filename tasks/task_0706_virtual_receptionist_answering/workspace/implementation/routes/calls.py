"""Call lifecycle routes (PRD §3.4-3.7, §3.10) — handling and billing axes."""
from flask import Blueprint, request

import errors
import serializers
from db import db
from response import success_object, success_array
from middleware import (get_auth, require_role, ROLE_ADMIN, ROLE_OWNER,
                        ROLE_RECEPTIONIST)
from common import (get_body, make_record, paginate, public, touch,
                    as_str, as_int, as_enum)
from services.lookups import (find_or_404, require_account_owner,
                              require_call_receptionist)
from services import routing
from services import billing

bp = Blueprint("calls", __name__)

LANGUAGES = {"EN", "ES"}
ESCALATION_REASONS = {"LONG_RUNNING", "CALLER_REQUEST", "LANGUAGE"}


# --- Intake (PRD §3.4) ------------------------------------------------------
@bp.route("/va/calls", methods=["POST"])
def create_call():
    _, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_RECEPTIONIST})
    body = get_body()

    account_id = as_str(body, "account_id", required=True)
    account = find_or_404(db.accounts, account_id)
    caller_id = as_str(body, "caller_id", default="")
    requested_language = as_enum(body, "requested_language", LANGUAGES, default="EN")

    # Resolve the account's single PUBLISHED script (PRD §3.4).
    script = routing.published_script(account_id)
    if script is None:
        raise errors.err(errors.ERR_NO_PUBLISHED_SCRIPT, "Account has no PUBLISHED CallScript")

    received_minute = db.clock.minute_of_day()
    is_after_hours = (received_minute < script["business_open_minute"]
                      or received_minute >= script["business_close_minute"])

    # Provisional spam screening (PRD §3.4).
    rule = routing.active_spam_rule(account_id)
    if rule is not None:
        spam_score = routing.spam_score_provisional(caller_id, rule)
        blocked = routing.area_code(caller_id) in rule["blocked_area_codes"]
        screened = blocked or spam_score >= rule["spam_score_threshold"]
    else:
        spam_score = 0
        screened = False

    rec = make_record({
        "account_id": account_id,
        "script_id": script["id"],
        "caller_id": caller_id,
        "requested_language": requested_language,
        "received_minute": received_minute,
        "is_after_hours": is_after_hours,
        "spam_score": spam_score,
        "answered_by_receptionist_id": None,
        "handling_status": "RINGING",
        "billing_status": "UNBILLED",
        "start_second": 0,
        "end_second": 0,
        "duration_seconds": 0,
        "billed_units": 0,
        "charge_cents": 0,
        "_period_id": account["current_period_id"],
        "_reached_in_progress": False,
    })

    if screened:
        rec["handling_status"] = "SCREENED_OUT"
        # Terminal; billing stays UNBILLED; open_call_count not incremented.
    elif is_after_hours and script["after_hours_action"] == "OVERFLOW":
        rec["handling_status"] = "OVERFLOW"
        _inc_open_call_count(account)
    else:
        rec["handling_status"] = "RINGING"
        _inc_open_call_count(account)

    db.calls[rec["id"]] = rec
    return success_object(serializers.call(public(rec)), 201)


def _inc_open_call_count(account):
    account["open_call_count"] += 1
    touch(account)


def _dec_open_call_count(account):
    account["open_call_count"] = max(0, account["open_call_count"] - 1)
    touch(account)


@bp.route("/va/calls/<call_id>", methods=["GET"])
def get_call(call_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER, ROLE_RECEPTIONIST})
    rec = find_or_404(db.calls, call_id)
    if role == ROLE_OWNER:
        require_account_owner(rec["account_id"], user_id, role)
    return success_object(serializers.call(public(rec)), 200)


@bp.route("/va/calls", methods=["GET"])
def list_calls():
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER, ROLE_RECEPTIONIST})
    records = list(db.calls.values())
    account_id = request.args.get("account_id")
    script_id = request.args.get("script_id")
    answered_by = request.args.get("answered_by_receptionist_id")
    handling_status = request.args.get("handling_status")
    billing_status = request.args.get("billing_status")
    if account_id is not None:
        records = [r for r in records if r["account_id"] == account_id]
    if script_id is not None:
        records = [r for r in records if r["script_id"] == script_id]
    if answered_by is not None:
        records = [r for r in records if r["answered_by_receptionist_id"] == answered_by]
    if handling_status is not None:
        records = [r for r in records if r["handling_status"] == handling_status]
    if billing_status is not None:
        records = [r for r in records if r["billing_status"] == billing_status]
    if role == ROLE_OWNER:
        records = [r for r in records if r["account_id"] == user_id]
    page, meta = paginate(records)
    return success_array([serializers.call(public(r)) for r in page], meta, 200)


# --- Answer / route (PRD §3.5) ---------------------------------------------
@bp.route("/va/calls/<call_id>/answer", methods=["POST"])
def answer_call(call_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_RECEPTIONIST})
    call = find_or_404(db.calls, call_id)
    account = db.accounts[call["account_id"]]

    # State (priority 6): transition must be defined from RINGING or OVERFLOW.
    if call["handling_status"] not in ("RINGING", "OVERFLOW"):
        raise errors.err(errors.ERR_INVALID_STATE, "Call is not RINGING or OVERFLOW")

    # Account suspended (priority 7).
    if account["status"] == "SUSPENDED":
        raise errors.err(errors.ERR_ACCOUNT_SUSPENDED, "Account is suspended")

    # After-hours blocked (priority 8): an after-hours call whose script does
    # not make it routable cannot be answered.
    script = db.call_scripts.get(call["script_id"])
    if call["is_after_hours"] and call["handling_status"] == "RINGING":
        # A RINGING after-hours call only exists when after_hours_action was
        # VOICEMAIL (OVERFLOW would have routed it to OVERFLOW at intake).
        raise errors.err(errors.ERR_AFTER_HOURS_BLOCKED, "After-hours call is not routable")

    # Run the answer-routing selector.
    selected = routing.select_receptionist(call["requested_language"], senior=False)
    if selected is None:
        # Empty candidate set. If someone speaks the language but none have
        # capacity/availability => ERR_NO_LANGUAGE_MATCH only when a language
        # mismatch is the cause; otherwise the business-hours fallback is a
        # non-error OVERFLOW.
        if not routing.any_receptionist_speaks_language(call["requested_language"]):
            raise errors.err(errors.ERR_NO_LANGUAGE_MATCH,
                             "No receptionist speaks the requested language")
        # Business-hours empty-pool fallback => OVERFLOW (no error). For an
        # already-OVERFLOW call this is a no-op state-wise; it stays OVERFLOW.
        if call["handling_status"] == "RINGING":
            call["handling_status"] = "OVERFLOW"
            touch(call)
        return success_object(serializers.call(public(call)), 200)

    call["answered_by_receptionist_id"] = selected["id"]
    call["handling_status"] = "ANSWERED"
    touch(call)
    return success_object(serializers.call(public(call)), 200)


# --- Start (PRD §3.6) -------------------------------------------------------
@bp.route("/va/calls/<call_id>/start", methods=["POST"])
def start_call(call_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_RECEPTIONIST})
    call = find_or_404(db.calls, call_id)
    require_call_receptionist(call, user_id, role)

    if call["handling_status"] != "ANSWERED":
        raise errors.err(errors.ERR_INVALID_STATE, "Call is not ANSWERED")
    if not call["answered_by_receptionist_id"]:
        raise errors.err(errors.ERR_INVALID_STATE, "Call has no answering receptionist")

    call["start_second"] = db.clock.epoch_seconds()
    call["handling_status"] = "IN_PROGRESS"
    call["_reached_in_progress"] = True
    touch(call)

    receptionist = db.receptionists[call["answered_by_receptionist_id"]]
    receptionist["active_call_count"] += 1
    if receptionist["active_call_count"] >= receptionist["max_concurrent_calls"]:
        receptionist["status"] = "BUSY"
    touch(receptionist)

    account = db.accounts[call["account_id"]]
    account["lifetime_calls_answered"] += 1
    touch(account)

    return success_object(serializers.call(public(call)), 200)


# --- Wrap (PRD §3.6) --------------------------------------------------------
@bp.route("/va/calls/<call_id>/wrap", methods=["POST"])
def wrap_call(call_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_RECEPTIONIST})
    call = find_or_404(db.calls, call_id)
    require_call_receptionist(call, user_id, role)

    if call["handling_status"] != "IN_PROGRESS":
        raise errors.err(errors.ERR_INVALID_STATE, "Call is not IN_PROGRESS")

    call["end_second"] = db.clock.epoch_seconds()
    call["duration_seconds"] = max(0, call["end_second"] - call["start_second"])
    call["handling_status"] = "WRAP_UP"

    # Finalize spam score (PRD §3.6).
    rule = routing.active_spam_rule(call["account_id"])
    if rule is not None:
        call["spam_score"] = routing.spam_score_final(
            call["caller_id"], rule, call["_reached_in_progress"])
    else:
        call["spam_score"] = max(0, call["spam_score"] - 30) if call["_reached_in_progress"] else call["spam_score"]
    touch(call)

    receptionist = db.receptionists.get(call["answered_by_receptionist_id"])
    if receptionist is not None:
        receptionist["active_call_count"] = max(0, receptionist["active_call_count"] - 1)
        if receptionist["status"] == "BUSY":
            receptionist["status"] = "AVAILABLE"
        touch(receptionist)

    return success_object(serializers.call(public(call)), 200)


# --- Complete + bill (PRD §3.6, §3.7, §3.9) ---------------------------------
@bp.route("/va/calls/<call_id>/complete", methods=["POST"])
def complete_call(call_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_RECEPTIONIST})
    call = find_or_404(db.calls, call_id)
    require_call_receptionist(call, user_id, role)

    if call["handling_status"] != "WRAP_UP":
        raise errors.err(errors.ERR_INVALID_STATE, "Call is not WRAP_UP")
    if call["billing_status"] != "UNBILLED":
        raise errors.err(errors.ERR_INVALID_STATE, "Call is not UNBILLED")

    period = db.billing_periods[call["_period_id"]]
    billed_units, charge_cents = billing.call_charge(call, period)
    call["billed_units"] = billed_units
    call["charge_cents"] = charge_cents
    call["billing_status"] = "BILLED"
    call["handling_status"] = "COMPLETED"
    touch(call)

    # Recompute the period under the final variant (now this call counts).
    billing.recompute_period_final(period)

    account = db.accounts[call["account_id"]]
    _dec_open_call_count(account)

    # Evaluate the billing cascade on account posture (PRD §3.9).
    billing.apply_posture_cascade(account)

    return success_object(serializers.call(public(call)), 200)


# --- Abandon (PRD §3.5) -----------------------------------------------------
@bp.route("/va/calls/<call_id>/abandon", methods=["POST"])
def abandon_call(call_id):
    _, role = get_auth()
    require_role(role, {ROLE_RECEPTIONIST, ROLE_ADMIN})
    call = find_or_404(db.calls, call_id)

    if call["handling_status"] != "RINGING":
        raise errors.err(errors.ERR_INVALID_STATE, "Call is not RINGING")
    call["handling_status"] = "ABANDONED"
    touch(call)
    account = db.accounts[call["account_id"]]
    _dec_open_call_count(account)
    return success_object(serializers.call(public(call)), 200)


# --- Dispute (PRD §3.10) ----------------------------------------------------
@bp.route("/va/calls/<call_id>/dispute", methods=["POST"])
def dispute_call(call_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_OWNER})
    call = find_or_404(db.calls, call_id)
    require_account_owner(call["account_id"], user_id, role)

    if call["billing_status"] != "BILLED":
        raise errors.err(errors.ERR_INVALID_STATE, "Call is not BILLED")
    period = db.billing_periods[call["_period_id"]]
    if period["status"] != "OPEN":
        raise errors.err(errors.ERR_PERIOD_NOT_OPEN, "Billing period is not OPEN")

    call["billing_status"] = "DISPUTED"
    touch(call)
    return success_object(serializers.call(public(call)), 200)


# --- Adjust (PRD §3.10) -----------------------------------------------------
@bp.route("/va/calls/<call_id>/adjust", methods=["POST"])
def adjust_call(call_id):
    _, role = get_auth()
    require_role(role, {ROLE_ADMIN})
    call = find_or_404(db.calls, call_id)
    body = get_body()

    # OCC check (priority 5) before state check (priority 6).
    expected_call_version = as_int(body, "expected_call_version", required=True)
    if expected_call_version != call["version"]:
        raise errors.err(errors.ERR_STALE_CALL_VERSION, "expected_call_version is stale")

    if call["billing_status"] != "DISPUTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Call is not DISPUTED")

    adjusted_units = as_int(body, "adjusted_units", required=True, minimum=0)

    period = db.billing_periods[call["_period_id"]]
    plan = db.service_plans[period["plan_id"]]

    call["billed_units"] = adjusted_units
    # charge_cents recomputed at the adjusted unit count: the marginal overage
    # contribution of these units to the period's tiered charge, evaluated on
    # the period's consumed_units excluding this call (PRD §3.7 marginal rule).
    consumed_excl = 0
    for c in db.calls.values():
        if c["_period_id"] == period["id"] and c["billing_status"] in ("BILLED", "ADJUSTED") and c["id"] != call["id"]:
            consumed_excl += c["billed_units"]
    _u0, _a0, _b0, prev_overage = billing.tiered_overage_charge(
        consumed_excl, period["included_units"], plan)
    _u1, _a1, _b1, new_overage = billing.tiered_overage_charge(
        consumed_excl + adjusted_units, period["included_units"], plan)
    call["charge_cents"] = max(0, new_overage - prev_overage)
    call["billing_status"] = "ADJUSTED"
    touch(call)

    # Compensate the period ledger under the final variant (PRD §3.10).
    billing.recompute_period_final(period)

    account = db.accounts[call["account_id"]]
    billing.apply_posture_cascade(account)

    return success_object(serializers.call(public(call)), 200)


# --- Escalate (PRD §3.6) ----------------------------------------------------
@bp.route("/va/calls/<call_id>/escalate", methods=["POST"])
def escalate_call(call_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_RECEPTIONIST})
    call = find_or_404(db.calls, call_id)
    require_call_receptionist(call, user_id, role)
    body = get_body()
    reason = as_enum(body, "reason", ESCALATION_REASONS, required=True)

    if call["handling_status"] != "IN_PROGRESS":
        raise errors.err(errors.ERR_INVALID_STATE, "Call is not IN_PROGRESS")

    senior = routing.select_receptionist(call["requested_language"], senior=True)
    rec = make_record({
        "call_id": call["id"],
        "reason": reason,
        "escalated_to_receptionist_id": senior["id"] if senior else None,
        "status": "ASSIGNED" if senior else "QUEUED",
    })
    db.escalations[rec["id"]] = rec
    return success_object(serializers.escalation(public(rec)), 201)
