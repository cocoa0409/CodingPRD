"""Delivery attempts: creation, door-side identification, handover, refusal and
evidence capture."""
import re
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

from db import (
    CAPTURE_RETENTION_DAYS,
    COMPLIANCE_REFUSAL_REASONS,
    COURIER_ATTEMPT_DWELL_MINUTES,
    DISPATCHABLE_COMPLIANCE_STATES,
    OPEN_ATTEMPT_STATES,
    REFUSAL_SEVERITY_MAP,
    db,
    new_row,
    now,
    now_str,
    sort_key,
    touch,
)
from errors import ApiError
from middleware import (
    COMPLIANCE_OFFICER,
    COURIER,
    PARTNER_MANAGER,
    PLATFORM_ADMIN,
    auth,
    fetch,
    scope_check,
)
from response import created, listing, ok, pagination, public
from services.calc import (
    ZERO2,
    compute_exposure,
    effective_policies_for_attempt,
    permissibility_error,
    resolve_order_policies,
    window_error,
)
from services.parties import (
    open_case,
    recompute_courier_score,
    recount_compliant_handovers,
    recompute_refusal_strikes,
    refresh_partner,
)
from util import add_days, completed_years, dec, fmt_dt, local_date, parse_date, parse_dt, rhu
import validate as v

bp = Blueprint("attempts", __name__)

ATTEMPT_STATES = ("INITIATED", "ID_VERIFIED", "ID_REJECTED", "HANDED_OVER", "REFUSED", "ABORTED")
DOCUMENT_TYPES = ("DRIVERS_LICENSE", "PASSPORT", "STATE_ID", "MILITARY_ID", "TRIBAL_ID")
REFUSAL_REASONS = (
    "UNDERAGE_RECIPIENT",
    "INTOXICATED_RECIPIENT",
    "NO_ACCEPTABLE_ID",
    "ID_MISMATCH",
    "RECIPIENT_ABSENT",
    "COURIER_FAULT",
)
ALLOWED_REFUSALS_BY_STATE = {
    "INITIATED": ("NO_ACCEPTABLE_ID", "INTOXICATED_RECIPIENT", "RECIPIENT_ABSENT", "COURIER_FAULT"),
    "ID_REJECTED": ("UNDERAGE_RECIPIENT", "ID_MISMATCH", "NO_ACCEPTABLE_ID"),
    "ID_VERIFIED": ("INTOXICATED_RECIPIENT", "RECIPIENT_ABSENT", "COURIER_FAULT"),
}
CAPTURE_KINDS = ("SIGNATURE", "PHOTO_ID", "PHOTO_HANDOFF")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
DWELL = timedelta(minutes=COURIER_ATTEMPT_DWELL_MINUTES)


def _captures_of(attempt_id):
    rows = [c for c in db.captures.values() if c["delivery_attempt_id"] == attempt_id]
    rows.sort(key=sort_key)
    return rows


# ---------------------------------------------------------------------------
# POST /delivery-attempts
# ---------------------------------------------------------------------------
@bp.post("/delivery-attempts")
def create_attempt():
    auth(COURIER)
    body = v.body()
    courier_id = body.get("courier_id")
    if isinstance(courier_id, str) and courier_id.strip() != "":
        scope_check(courier_id)
    order_id = body.get("order_id")
    if not isinstance(order_id, str) or order_id.strip() == "":
        raise ApiError("ERR_VALIDATION", "order_id is required")
    order = fetch("orders", order_id)
    if not isinstance(courier_id, str) or courier_id.strip() == "":
        raise ApiError("ERR_VALIDATION", "courier_id is required")
    courier = fetch("couriers", courier_id)
    started_at, started_raw = v.req_dt(body, "started_at")

    # tier 10 -- order state
    if order["fulfillment_state"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if order["compliance_state"] not in DISPATCHABLE_COMPLIANCE_STATES:
        raise ApiError("ERR_INVALID_ORDER_STATE")

    jurisdiction = db.jurisdictions.get(order["delivery_jurisdiction_id"])

    # tier 11 -- policy resolution repeats at started_at
    resolved, missing = resolve_order_policies(order, started_at)
    if missing is not None:
        raise ApiError("ERR_NO_EFFECTIVE_POLICY")

    # tier 12 -- jurisdiction permissibility
    permissibility = permissibility_error(jurisdiction, resolved)
    if permissibility is not None:
        raise ApiError(permissibility)

    # tier 13 -- partner and courier authority
    if courier["delivery_partner_id"] != order["delivery_partner_id"]:
        raise ApiError("ERR_COURIER_PARTNER_MISMATCH")
    if courier["certification_state"] != "CERTIFIED":
        raise ApiError("ERR_COURIER_NOT_CERTIFIED")
    partner = db.partners.get(order["delivery_partner_id"])
    if partner is not None and partner["posture"] == "SUSPENDED":
        raise ApiError("ERR_PARTNER_SUSPENDED")

    # tier 17 -- restricted hours at started_at
    hours = window_error(jurisdiction, resolved, started_at)
    if hours is not None:
        raise ApiError(hours)

    # tier 18 -- the courier's twenty-minute half-open dwell interval
    new_end = started_at + DWELL
    for other in db.attempts.values():
        if other["courier_id"] != courier_id:
            continue
        if other["state"] not in OPEN_ATTEMPT_STATES:
            continue
        other_start = parse_dt(other["started_at"])
        if other_start is None:
            continue
        other_end = other_start + DWELL
        if started_at < other_end and other_start < new_end:
            raise ApiError("ERR_COURIER_SLOT_CONFLICT")

    row = new_row(
        order_id=order_id,
        courier_id=courier_id,
        started_at=started_raw,
        state="INITIATED",
        document_type=None,
        document_expires_on=None,
        scan_performed=None,
        scanned_dob=None,
        recipient_name=None,
        recipient_age_years=None,
        id_check_compliant=False,
        refusal_reason=None,
        observed_indicators=[],
        abort_reason=None,
    )
    db.attempts[row["id"]] = row
    order["fulfillment_state"] = "OUT_FOR_DELIVERY"
    touch(order)
    return created(public(row))


@bp.get("/delivery-attempts/<attempt_id>")
def get_attempt(attempt_id):
    user_id, role = auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER, COURIER)
    attempt = fetch("attempts", attempt_id)
    if role == COURIER:
        scope_check(attempt["courier_id"])
    if role == PARTNER_MANAGER:
        order = db.orders.get(attempt["order_id"])
        if order is not None:
            scope_check(order["delivery_partner_id"])
    return ok(public(attempt))


@bp.get("/delivery-attempts")
def list_attempts():
    user_id, role = auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER, COURIER)
    order_filter = v.str_filter("order_id")
    courier_filter = v.str_filter("courier_id")
    state = v.enum_filter("state", ATTEMPT_STATES)
    limit, offset = pagination()
    if role == COURIER:
        if courier_filter is not None and courier_filter != user_id:
            raise ApiError("ERR_FORBIDDEN_RESOURCE_SCOPE")
        courier_filter = user_id
    rows = list(db.attempts.values())
    if role == PARTNER_MANAGER:
        owned = set(o["id"] for o in db.orders.values() if o["delivery_partner_id"] == user_id)
        rows = [r for r in rows if r["order_id"] in owned]
    if order_filter is not None:
        rows = [r for r in rows if r["order_id"] == order_filter]
    if courier_filter is not None:
        rows = [r for r in rows if r["courier_id"] == courier_filter]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    rows.sort(key=sort_key)
    return listing(rows, limit, offset)


# ---------------------------------------------------------------------------
# POST /delivery-attempts/{id}/id-check
# ---------------------------------------------------------------------------
@bp.post("/delivery-attempts/<attempt_id>/id-check")
def id_check(attempt_id):
    auth(COURIER)
    attempt = fetch("attempts", attempt_id)
    scope_check(attempt["courier_id"])
    body = v.body()
    document_type = v.req_enum(body, "document_type", DOCUMENT_TYPES)
    document_expires_on = v.req_date(body, "document_expires_on")
    scan_performed = v.req_bool(body, "scan_performed")
    scanned_dob = v.req_date(body, "scanned_dob")
    recipient_name = v.req_str(body, "recipient_name")

    if attempt["state"] != "INITIATED":
        raise ApiError("ERR_INVALID_ATTEMPT_STATE")

    order = db.orders.get(attempt["order_id"])
    jurisdiction = db.jurisdictions.get(order["delivery_jurisdiction_id"])
    started_at = parse_dt(attempt["started_at"])

    # tier 11 -- policy resolution
    resolved, missing = resolve_order_policies(order, started_at)
    if missing is not None:
        raise ApiError("ERR_NO_EFFECTIVE_POLICY")
    policies = [p for _, p in resolved]

    # tier 13(d) -- one ACTIVE certification per restriction class on the order
    for rtype, _policy in resolved:
        held = any(c["courier_id"] == attempt["courier_id"]
                   and c["restriction_type"] == rtype
                   and c["state"] == "ACTIVE"
                   for c in db.certifications.values())
        if not held:
            raise ApiError("ERR_CERTIFICATION_MISSING_FOR_RESTRICTION")

    # tier 14 -- door-side identification, in the declared sub-order
    for policy in policies:
        if document_type not in policy["acceptable_document_types"]:
            raise ApiError("ERR_DOCUMENT_TYPE_NOT_ACCEPTABLE")
    if any(p["requires_scan"] for p in policies) and not scan_performed:
        raise ApiError("ERR_SCAN_REQUIRED")
    local_today = local_date(started_at, jurisdiction["utc_offset_minutes"])
    if document_expires_on < local_today:
        raise ApiError("ERR_DOCUMENT_EXPIRED")
    customer = db.customers.get(order["customer_id"])
    attested_dob = customer.get("attested_dob") if customer else None
    if attested_dob is None or scanned_dob.isoformat() != attested_dob:
        raise ApiError("ERR_RECIPIENT_IDENTITY_MISMATCH")

    recipient_age_years = completed_years(scanned_dob, started_at.date())
    min_age = max([p["min_age_years"] for p in policies]) if policies else 0

    attempt["document_type"] = document_type
    attempt["document_expires_on"] = document_expires_on.isoformat()
    attempt["scan_performed"] = scan_performed
    attempt["scanned_dob"] = scanned_dob.isoformat()
    attempt["recipient_name"] = recipient_name
    attempt["recipient_age_years"] = recipient_age_years
    if recipient_age_years >= min_age:
        attempt["state"] = "ID_VERIFIED"
        attempt["id_check_compliant"] = True
    else:
        attempt["state"] = "ID_REJECTED"
        attempt["id_check_compliant"] = False
    touch(attempt)
    return ok(public(attempt))


# ---------------------------------------------------------------------------
# POST /delivery-attempts/{id}/handover
# ---------------------------------------------------------------------------
@bp.post("/delivery-attempts/<attempt_id>/handover")
def handover(attempt_id):
    auth(COURIER)
    attempt = fetch("attempts", attempt_id)
    scope_check(attempt["courier_id"])
    body = v.body()
    recipient_name = v.req_str(body, "recipient_name")

    order = db.orders.get(attempt["order_id"])
    unrestricted = not order["restriction_types"]
    state = attempt["state"]
    if state == "ID_VERIFIED":
        verified_path = True
    elif state == "INITIATED" and unrestricted:
        verified_path = False
    else:
        raise ApiError("ERR_INVALID_ATTEMPT_STATE")

    started_at = parse_dt(attempt["started_at"])
    policies = effective_policies_for_attempt(order, started_at) if verified_path else []

    # tier 16 -- capture completeness
    kinds = set(c["kind"] for c in _captures_of(attempt_id))
    required = {"SIGNATURE", "PHOTO_HANDOFF"}
    if verified_path and any(p["requires_scan"] for p in policies):
        required.add("PHOTO_ID")
    if not required.issubset(kinds):
        raise ApiError("ERR_CAPTURE_INCOMPLETE")

    attempt["state"] = "HANDED_OVER"
    attempt["recipient_name"] = recipient_name
    touch(attempt)

    if order["fulfillment_state"] == "OUT_FOR_DELIVERY":
        order["fulfillment_state"] = "DELIVERED"
    order["delivered_at"] = attempt["started_at"]

    if verified_path:
        resolved, missing = resolve_order_policies(order, started_at)
        total, per_type, line_units = compute_exposure(order, resolved, use_snapshot=False)
        order["final_restricted_units"] = total
        for line_id, value in line_units.items():
            line = db.order_lines.get(line_id)
            if line is not None and line["line_restricted_units"] != value:
                line["line_restricted_units"] = value
                touch(line)
    else:
        order["final_restricted_units"] = ZERO2
    touch(order)

    if verified_path:
        courier = db.couriers.get(attempt["courier_id"])
        if courier is not None:
            recount_compliant_handovers(courier)
            recompute_courier_score(courier)
    return ok(public(attempt))


# ---------------------------------------------------------------------------
# POST /delivery-attempts/{id}/refuse
# ---------------------------------------------------------------------------
@bp.post("/delivery-attempts/<attempt_id>/refuse")
def refuse(attempt_id):
    auth(COURIER)
    attempt = fetch("attempts", attempt_id)
    scope_check(attempt["courier_id"])
    body = v.body()
    refusal_reason = v.req_enum(body, "refusal_reason", REFUSAL_REASONS)
    observed_indicators = v.opt_str_list(body, "observed_indicators", default=[])

    state = attempt["state"]
    if state not in ALLOWED_REFUSALS_BY_STATE:
        raise ApiError("ERR_INVALID_ATTEMPT_STATE")
    if refusal_reason not in ALLOWED_REFUSALS_BY_STATE[state]:
        raise ApiError("ERR_REFUSAL_REASON_NOT_ALLOWED")

    order = db.orders.get(attempt["order_id"])

    # link 1 -- the attempt and its order
    attempt["state"] = "REFUSED"
    attempt["refusal_reason"] = refusal_reason
    attempt["observed_indicators"] = list(observed_indicators)
    touch(attempt)
    if order["fulfillment_state"] == "OUT_FOR_DELIVERY":
        order["fulfillment_state"] = "RETURN_IN_TRANSIT"
        touch(order)

    # link 2 -- a violation case, only for compliance-relevant reasons
    partner = db.partners.get(order["delivery_partner_id"])
    if refusal_reason in COMPLIANCE_REFUSAL_REASONS:
        open_case(
            partner_id=order["delivery_partner_id"],
            severity=REFUSAL_SEVERITY_MAP[refusal_reason],
            summary="Auto-opened from delivery refusal (%s)" % refusal_reason,
            origin="AUTO_REFUSAL",
            delivery_attempt_id=attempt["id"],
        )
        # links 3 and 4 -- partner counters, posture, and the order-hold cascade
        if partner is not None:
            refresh_partner(partner)

    # independently -- purchaser refusal strikes
    customer = db.customers.get(order["customer_id"])
    if customer is not None:
        recompute_refusal_strikes(customer, attempt)
    return ok(public(attempt))


# ---------------------------------------------------------------------------
# Evidence captures
# ---------------------------------------------------------------------------
@bp.post("/delivery-attempts/<attempt_id>/captures")
def create_capture(attempt_id):
    auth(COURIER)
    attempt = fetch("attempts", attempt_id)
    scope_check(attempt["courier_id"])
    body = v.body()
    kind = v.req_enum(body, "kind", CAPTURE_KINDS)
    content_hash = v.req_str(body, "content_hash")
    if not HASH_RE.match(content_hash):
        raise ApiError("ERR_VALIDATION", "content_hash must be 64 lowercase hexadecimal characters")
    captured_at, captured_raw = v.req_dt(body, "captured_at")

    for existing in db.captures.values():
        if existing["content_hash"] == content_hash:
            raise ApiError("ERR_DUPLICATE_CODE", "content_hash is already in use")
    for existing in _captures_of(attempt_id):
        if existing["kind"] == kind:
            raise ApiError("ERR_DUPLICATE_CAPTURE_KIND")

    row = new_row(
        with_common=False,
        delivery_attempt_id=attempt_id,
        kind=kind,
        content_hash=content_hash,
        captured_at=captured_raw,
        retention_until=fmt_dt(add_days(captured_at, CAPTURE_RETENTION_DAYS)),
    )
    db.captures[row["id"]] = row
    return created(public(row))


@bp.get("/delivery-attempts/<attempt_id>/captures")
def list_captures(attempt_id):
    user_id, role = auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER, COURIER)
    attempt = fetch("attempts", attempt_id)
    if role == COURIER:
        scope_check(attempt["courier_id"])
    if role == PARTNER_MANAGER:
        order = db.orders.get(attempt["order_id"])
        if order is not None:
            scope_check(order["delivery_partner_id"])
    kind = v.enum_filter("kind", CAPTURE_KINDS)
    limit, offset = pagination()
    rows = _captures_of(attempt_id)
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    return listing(rows, limit, offset)
