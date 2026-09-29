"""Authentication events, chargebacks and policy exceptions (PRD 3.5 / 3.7 / 3.8)."""

from datetime import timedelta

from flask import Blueprint, g

import calc
import services as svc
import validators as v
from db import db, touch
from errors import ApiError
from middleware import roles
from response import created, ok, serialize
from routes._common import paged

bp = Blueprint("risk", __name__, url_prefix="/fraud")

AUTH_READERS = ("RiskAnalyst", "ReviewLead", "CheckoutService", "PlatformAdmin")
CHARGEBACK_READERS = ("PlatformAdmin", "RiskAnalyst", "ReviewLead", "PolicyEngineer")
EXCEPTION_READERS = ("RiskAnalyst", "ReviewLead", "PlatformAdmin", "CheckoutService")


# ============================================================== AuthEvent
def _device_first_seen(customer_id, device_id):
    for event in db.auth_events.values():
        if (
            event["customer_id"] == customer_id
            and event["device_profile_id"] == device_id
        ):
            return False
    for assessment in db.assessments.values():
        if (
            assessment["customer_id"] == customer_id
            and assessment["device_profile_id"] == device_id
        ):
            return False
    return True


@bp.route("/auth-events", methods=["POST"])
@roles("CheckoutService")
def create_auth_event():
    payload = v.body()
    customer = v.required_fk(
        payload, "customer_id", db.customers, "ERR_CUSTOMER_NOT_FOUND"
    )
    device = v.required_fk(
        payload, "device_profile_id", db.devices, "ERR_DEVICE_NOT_FOUND"
    )
    if customer is None or device is None:
        v.bad()
    event_type = v.as_enum(payload, "event_type", calc.AUTH_EVENT_TYPES)
    ip_country = v.as_country(payload, "ip_country")
    prior_password_change_hours = v.as_decimal(
        payload, "prior_password_change_hours", required=False, default=None
    )

    now = db.now()
    # Scored against the customer and device as they stand BEFORE this event lands.
    first_seen = _device_first_seen(customer["id"], device["id"])
    ato_score = calc.ato_score_evaluation(
        event_type, ip_country, customer, device, first_seen
    )
    outcome = calc.ato_outcome(ato_score)

    if outcome == "STEP_UP_REQUIRED":
        challenge_state = "ISSUED"
        challenge_method = "OTP_SMS"
        challenge_expires_at = now + timedelta(seconds=calc.CHALLENGE_TTL_SECONDS)
    else:
        challenge_state = "NONE"
        challenge_method = None
        challenge_expires_at = None

    row = svc.new_row(
        customer_id=customer["id"],
        device_profile_id=device["id"],
        event_type=event_type,
        ip_country=ip_country,
        prior_password_change_hours=prior_password_change_hours,
        ato_score=ato_score,
        outcome=outcome,
        challenge_state=challenge_state,
        challenge_method=challenge_method,
        challenge_attempts=0,
        challenge_expires_at=challenge_expires_at,
        device_first_seen_for_customer=first_seen,
    )
    db.auth_events[row["id"]] = row

    if outcome == "STEP_UP_REQUIRED":
        if (
            customer["account_status"] != "CLOSED"
            and customer["ato_posture"] == "CLEAR"
        ):
            customer["ato_posture"] = "WATCH"
            svc.recompute_good_standing(customer)
            touch(customer)
    elif outcome == "BLOCKED":
        if (
            customer["account_status"] != "CLOSED"
            and customer["ato_posture"] != "CONTAINED"
        ):
            svc.contain_customer(customer)

    # Authentication events feed the distinct-customer signal.
    svc.recompute_device(device)
    return created(serialize(row))


@bp.route("/auth-events", methods=["GET"])
@roles(*AUTH_READERS)
def list_auth_events():
    return paged(
        list(db.auth_events.values()),
        [
            ("customer_id", v.query_str("customer_id")),
            ("device_profile_id", v.query_str("device_profile_id")),
            ("event_type", v.query_enum("event_type", calc.AUTH_EVENT_TYPES)),
            ("outcome", v.query_enum("outcome", calc.AUTH_OUTCOMES)),
            ("challenge_state", v.query_enum("challenge_state", calc.CHALLENGE_STATES)),
        ],
    )


@bp.route("/auth-events/<eid>", methods=["GET"])
@roles(*AUTH_READERS)
def read_auth_event(eid):
    return ok(serialize(v.lookup(db.auth_events, eid, "ERR_AUTH_EVENT_NOT_FOUND")))


@bp.route("/auth-events/<eid>/challenge", methods=["POST"])
@roles("CheckoutService")
def auth_event_challenge(eid):
    event = v.lookup(db.auth_events, eid, "ERR_AUTH_EVENT_NOT_FOUND")
    payload = v.body()
    action = v.as_enum(payload, "action", calc.CHALLENGE_ACTIONS)
    method = v.as_enum(
        payload, "challenge_method", calc.CHALLENGE_METHODS, required=False, default=None
    )

    now = db.now()
    state = event["challenge_state"]
    expires_at = event.get("challenge_expires_at")

    # PRD 3.7: 48 -> 49 -> 50 -> 82
    if action in ("PASS", "FAIL", "EXPIRE"):
        if state != "ISSUED":
            raise ApiError("ERR_CHALLENGE_STATE_INVALID")
    else:  # REISSUE
        if state != "FAILED":
            raise ApiError("ERR_CHALLENGE_STATE_INVALID")
    if action in ("PASS", "FAIL", "REISSUE"):
        if expires_at is not None and now >= expires_at:
            raise ApiError("ERR_CHALLENGE_EXPIRED")
    if action == "EXPIRE":
        if expires_at is not None and now < expires_at:
            raise ApiError("ERR_CHALLENGE_NOT_EXPIRED")
    if action == "REISSUE" and event["challenge_attempts"] >= calc.MAX_CHALLENGE_ATTEMPTS:
        raise ApiError("ERR_CHALLENGE_ATTEMPTS_EXHAUSTED")

    customer = db.customers[event["customer_id"]]

    if action == "PASS":
        event["challenge_state"] = "PASSED"
        customer["failed_login_count"] = 0
        if customer["ato_posture"] == "WATCH":
            customer["ato_posture"] = "CLEAR"
        svc.recompute_good_standing(customer)
        touch(customer)
    elif action == "FAIL":
        event["challenge_state"] = "FAILED"
        event["challenge_attempts"] += 1
        customer["failed_login_count"] += 1
        if event["challenge_attempts"] >= calc.MAX_CHALLENGE_ATTEMPTS:
            # first link of the containment chain
            svc.contain_customer(customer)
        else:
            svc.recompute_good_standing(customer)
            touch(customer)
    elif action == "REISSUE":
        event["challenge_state"] = "ISSUED"
        event["challenge_method"] = method or "OTP_SMS"
        event["challenge_expires_at"] = now + timedelta(
            seconds=calc.CHALLENGE_TTL_SECONDS
        )
    else:  # EXPIRE
        event["challenge_state"] = "EXPIRED"

    touch(event)
    return ok(serialize(event))


# ======================================================= ChargebackRecord
@bp.route("/chargebacks", methods=["POST"])
@roles("PlatformAdmin")
def create_chargeback():
    payload = v.body()
    assessment = v.required_fk(
        payload, "assessment_id", db.assessments, "ERR_ASSESSMENT_NOT_FOUND"
    )
    if assessment is None:
        v.bad()
    reason_code = v.as_enum(payload, "reason_code", calc.CHARGEBACK_REASON_CODES)
    amount_cents = v.as_int(payload, "amount_cents", minimum=1)
    liability_shift = v.as_bool(payload, "liability_shift")
    received_at = v.as_datetime(payload, "received_at")
    evidence_note = v.as_str(payload, "evidence_note", required=False, default=None)

    # PRD 3.8: 69 -> 72 -> 88
    if assessment["state"] != "DECIDED_APPROVE":
        raise ApiError("ERR_CHARGEBACK_ASSESSMENT_NOT_APPROVED")
    if assessment["decided_at"] is not None and received_at < assessment["decided_at"]:
        raise ApiError("ERR_CHARGEBACK_BEFORE_DECISION")
    if amount_cents > assessment["amount_cents"]:
        raise ApiError("ERR_CHARGEBACK_AMOUNT_EXCEEDS_ORDER")

    row = svc.new_row(
        assessment_id=assessment["id"],
        reason_code=reason_code,
        amount_cents=amount_cents,
        liability_shift=liability_shift,
        received_at=received_at,
        state="RECEIVED",
        evidence_note=evidence_note,
        resolved_at=None,
        guarantee_state="NOT_APPLICABLE",
        guarantee_denial_reason=None,
        guarantee_eligible_cents=0,
        guarantee_fee_cents=0,
        guarantee_reimbursed_cents=0,
    )
    db.chargebacks[row["id"]] = row
    return created(serialize(row))


@bp.route("/chargebacks", methods=["GET"])
@roles(*CHARGEBACK_READERS)
def list_chargebacks():
    return paged(
        list(db.chargebacks.values()),
        [
            ("assessment_id", v.query_str("assessment_id")),
            ("reason_code", v.query_enum("reason_code", calc.CHARGEBACK_REASON_CODES)),
            ("state", v.query_enum("state", calc.CHARGEBACK_STATES)),
            ("guarantee_state", v.query_enum("guarantee_state", calc.GUARANTEE_STATES)),
        ],
    )


@bp.route("/chargebacks/<bid>", methods=["GET"])
@roles(*CHARGEBACK_READERS)
def read_chargeback(bid):
    return ok(serialize(v.lookup(db.chargebacks, bid, "ERR_CHARGEBACK_NOT_FOUND")))


@bp.route("/chargebacks/<bid>/transition", methods=["POST"])
@roles("PlatformAdmin")
def chargeback_transition(bid):
    chargeback = v.lookup(db.chargebacks, bid, "ERR_CHARGEBACK_NOT_FOUND")
    payload = v.body()
    action = v.as_enum(payload, "action", calc.CHARGEBACK_ACTIONS)
    evidence_note = v.as_str(payload, "evidence_note", required=False, default=None)
    state = chargeback["state"]

    # priority 44
    if action == "REPRESENT" and state != "RECEIVED":
        raise ApiError("ERR_CHARGEBACK_TRANSITION_INVALID")
    if action == "WIN" and state != "REPRESENTED":
        raise ApiError("ERR_CHARGEBACK_TRANSITION_INVALID")
    if action == "LOSE" and state not in ("RECEIVED", "REPRESENTED"):
        raise ApiError("ERR_CHARGEBACK_TRANSITION_INVALID")

    if evidence_note is not None:
        chargeback["evidence_note"] = evidence_note

    if action == "REPRESENT":
        chargeback["state"] = "REPRESENTED"
        touch(chargeback)
    elif action == "WIN":
        svc.chargeback_win(chargeback)
    else:
        svc.chargeback_lose(chargeback)
    return ok(serialize(chargeback))


# ========================================================= PolicyException
@bp.route("/policy-exceptions", methods=["POST"])
@roles("RiskAnalyst")
def create_policy_exception():
    payload = v.body()
    customer = v.required_fk(
        payload, "customer_id", db.customers, "ERR_CUSTOMER_NOT_FOUND"
    )
    if customer is None:
        v.bad()
    whitelisted = v.required_fk(
        payload, "whitelisted_address_id", db.addresses, "ERR_ADDRESS_NOT_FOUND"
    )
    scope = v.as_enum(payload, "scope", calc.EXCEPTION_SCOPES)
    max_amount_cents = v.as_int(payload, "max_amount_cents", minimum=1)
    effective_from = v.as_datetime(payload, "effective_from")
    expires_at = v.as_datetime(payload, "expires_at")
    justification = v.as_str(payload, "justification")

    # PRD 3.5: 41 -> 66/67 -> 70 -> 79 -> 86 -> 87
    if customer["account_status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_ACCOUNT_LOCKED")
    if scope == "ADDRESS_WHITELIST" and whitelisted is None:
        raise ApiError("ERR_EXCEPTION_SCOPE_ADDRESS_REQUIRED")
    if scope == "AUTO_APPROVE_UNDER_AMOUNT" and whitelisted is not None:
        raise ApiError("ERR_EXCEPTION_ADDRESS_NOT_ALLOWED")
    if expires_at <= effective_from:
        raise ApiError("ERR_INVALID_WINDOW")
    for other in db.policy_exceptions.values():
        if other["customer_id"] != customer["id"] or other["scope"] != scope:
            continue
        if other["state"] not in ("REQUESTED", "APPROVED"):
            continue
        clear = (
            expires_at <= other["effective_from"]
            or other["expires_at"] <= effective_from
        )
        if not clear:
            raise ApiError("ERR_EXCEPTION_WINDOW_OVERLAP")
    if max_amount_cents > calc.TIER_EXCEPTION_CAP_CENTS[customer["tier"]]:
        raise ApiError("ERR_EXCEPTION_AMOUNT_EXCEEDS_TIER_CAP")
    if scope == "AUTO_APPROVE_UNDER_AMOUNT" and customer["tier"] == "STANDARD":
        raise ApiError("ERR_EXCEPTION_TIER_NOT_ELIGIBLE")

    row = svc.new_row(
        customer_id=customer["id"],
        requested_by_analyst_id=g.user_id,
        approved_by_analyst_id=None,
        whitelisted_address_id=whitelisted["id"] if whitelisted is not None else None,
        scope=scope,
        max_amount_cents=max_amount_cents,
        effective_from=effective_from,
        expires_at=expires_at,
        justification=justification,
        state="REQUESTED",
        consumed_count=0,
        decided_at=None,
        decision_note=None,
    )
    db.policy_exceptions[row["id"]] = row
    return created(serialize(row))


@bp.route("/policy-exceptions", methods=["GET"])
@roles(*EXCEPTION_READERS)
def list_policy_exceptions():
    return paged(
        list(db.policy_exceptions.values()),
        [
            ("customer_id", v.query_str("customer_id")),
            ("requested_by_analyst_id", v.query_str("requested_by_analyst_id")),
            ("approved_by_analyst_id", v.query_str("approved_by_analyst_id")),
            ("whitelisted_address_id", v.query_str("whitelisted_address_id")),
            ("scope", v.query_enum("scope", calc.EXCEPTION_SCOPES)),
            ("state", v.query_enum("state", calc.EXCEPTION_STATES)),
        ],
    )


@bp.route("/policy-exceptions/<xid>", methods=["GET"])
@roles(*EXCEPTION_READERS)
def read_policy_exception(xid):
    return ok(
        serialize(v.lookup(db.policy_exceptions, xid, "ERR_EXCEPTION_NOT_FOUND"))
    )


@bp.route("/policy-exceptions/<xid>/decision", methods=["POST"])
@roles("ReviewLead")
def decide_policy_exception(xid):
    exception = v.lookup(db.policy_exceptions, xid, "ERR_EXCEPTION_NOT_FOUND")
    payload = v.body()
    action = v.as_enum(payload, "action", calc.EXCEPTION_ACTIONS)
    expected_customer_version = v.as_int(payload, "expected_customer_version")
    decision_note = v.as_str(payload, "decision_note", required=False, default=None)

    customer = db.customers[exception["customer_id"]]
    state = exception["state"]

    # PRD 3.5: 41 (APPROVE only) -> 47 -> 53 -> 57
    if action == "APPROVE" and customer["account_status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_ACCOUNT_LOCKED")
    if action in ("APPROVE", "REJECT") and state != "REQUESTED":
        raise ApiError("ERR_EXCEPTION_STATE_INVALID")
    if action == "REVOKE" and state != "APPROVED":
        raise ApiError("ERR_EXCEPTION_STATE_INVALID")
    if expected_customer_version != customer["version"]:
        raise ApiError("ERR_STALE_CUSTOMER_VERSION")
    if action in ("APPROVE", "REJECT"):
        if g.user_id == exception["requested_by_analyst_id"]:
            raise ApiError("ERR_DECISION_SEGREGATION_VIOLATION")

    now = db.now()
    if action == "APPROVE":
        exception["state"] = "APPROVED"
        exception["approved_by_analyst_id"] = g.user_id
    elif action == "REJECT":
        exception["state"] = "REJECTED"
    else:
        exception["state"] = "REVOKED"
    exception["decided_at"] = now
    if decision_note is not None:
        exception["decision_note"] = decision_note
    touch(exception)
    touch(customer)
    return ok(serialize(exception))
