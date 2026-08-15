"""Extension requests: create and decide (computed grants, hard stop)."""

from datetime import timedelta

from db import store, now, today
from errors import ApiError
from helpers import (
    get_body, check_allowed_fields, req_string, req_enum, opt_string, req_int,
    get_extension_or_404, get_holdback_or_404, work_order_of,
    new_entity, touch, ser_extension,
)
from middleware import authenticate, authorize
from response import success

from . import bp

REASONS = {"WEATHER_EXTERIOR", "SUPPLY_DELAY", "OTHER"}
DECISIONS = {"GRANTED", "DENIED"}

MAX_TOTAL_EXTENSION_DAYS = 45
WEATHER_PER_REQUEST_CAP_DAYS = 21
NON_WEATHER_PER_REQUEST_CAP_DAYS = 7


@bp.post("/escrow/extension-requests")
def create_extension():
    uid, role = authenticate()
    authorize(role, ["Buyer", "Seller"])
    data = get_body()
    raw_hid = data.get("holdback_id")
    if isinstance(raw_hid, str) and raw_hid not in store.holdbacks:
        raise ApiError("ERR_NOT_FOUND", "Holdback not found: %s" % raw_hid)
    check_allowed_fields(data, {"holdback_id", "reason", "requested_days", "evidence_ref"})
    hid = req_string(data, "holdback_id")
    hb = get_holdback_or_404(hid)
    reason = req_enum(data, "reason", REASONS)
    requested_days = req_int(data, "requested_days", lo=1, hi=45)
    evidence_ref = req_string(data, "evidence_ref")

    # Rung 8: extensions require an ACTIVE holdback.
    if hb["status"] != "ACTIVE":
        raise ApiError("ERR_HOLDBACK_NOT_ACTIVE", "Extensions require an ACTIVE holdback")
    # Rung 10: one PENDING extension at a time.
    for e in store.extensions.values():
        if e["holdback_id"] == hid and e["status"] == "PENDING":
            raise ApiError("ERR_EXTENSION_ALREADY_PENDING", "Another extension is already PENDING")
    # Rung 11: WEATHER_EXTERIOR requires an exterior scope.
    if reason == "WEATHER_EXTERIOR" and not hb["exterior_work_flag"]:
        raise ApiError("ERR_EXTENSION_NOT_WEATHER_ELIGIBLE", "Scope is not exterior work")
    # Rung 14: request on/before the effective deadline date is allowed.
    if not (today() <= hb["effective_deadline_date"]):
        raise ApiError("ERR_EXTENSION_WINDOW_CLOSED", "The effective deadline has passed")

    e = new_entity()
    e.update({
        "holdback_id": hid,
        "requester_user_id": uid,
        "reason": reason,
        "requested_days": requested_days,
        "evidence_ref": evidence_ref,
        "status": "PENDING",
        "granted_days": None,
        "decided_at": None,
    })
    store.extensions[e["id"]] = e
    return success(ser_extension(e), response_type="object", status=201)


@bp.post("/escrow/extension-requests/<eid>/decide")
def decide_extension(eid):
    _uid, role = authenticate()
    authorize(role, ["EscrowOfficer"])
    e = get_extension_or_404(eid)
    data = get_body()
    check_allowed_fields(data, {"decision", "decision_note"})
    decision = req_enum(data, "decision", DECISIONS)
    opt_string(data, "decision_note")  # accepted alongside the decision

    hb = get_holdback_or_404(e["holdback_id"])
    # Rung 7: only a PENDING request can be decided.
    if e["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Extension request is not PENDING")
    # Rung 8: holdback must still be ACTIVE for grant or deny.
    if hb["status"] != "ACTIVE":
        raise ApiError("ERR_HOLDBACK_NOT_ACTIVE", "Extension decision requires an ACTIVE holdback")

    if decision == "GRANTED":
        # Computed grant: smallest of requested, per-request cap, remaining
        # lifetime allowance, and hard-stop headroom.
        per_request_cap = (
            WEATHER_PER_REQUEST_CAP_DAYS
            if e["reason"] == "WEATHER_EXTERIOR"
            else NON_WEATHER_PER_REQUEST_CAP_DAYS
        )
        total_cap_remaining = MAX_TOTAL_EXTENSION_DAYS - hb["granted_extension_days"]
        hard_stop_remaining = (hb["hard_stop_date"] - hb["effective_deadline_date"]).days
        granted = min(e["requested_days"], per_request_cap, total_cap_remaining, hard_stop_remaining)
        # Rung 14: a grant must yield at least one full day.
        if granted < 1:
            raise ApiError("ERR_EXTENSION_EXCEEDS_HARD_STOP", "Grant would yield zero days")
        e["status"] = "GRANTED"
        e["granted_days"] = granted
        e["decided_at"] = now()
        touch(e)
        hb["granted_extension_days"] += granted
        hb["effective_deadline_date"] = hb["work_deadline_date"] + timedelta(
            days=hb["granted_extension_days"]
        )
        wo = work_order_of(hb["id"])
        if wo is not None and wo["completion_deadline_date"] != hb["effective_deadline_date"]:
            wo["completion_deadline_date"] = hb["effective_deadline_date"]
            touch(wo)
        touch(hb)
    else:
        e["status"] = "DENIED"
        e["decided_at"] = now()
        touch(e)

    return success(ser_extension(e), response_type="object", status=200)
