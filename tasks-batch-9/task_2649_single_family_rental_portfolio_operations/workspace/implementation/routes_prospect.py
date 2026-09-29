"""Prospect registration, identity verification and the self-showing calendar."""
import datetime

from flask import Blueprint

import calc
import cascades
import store
import views
from envelope import created, ok, paginate
from errors import fail
from validation import (F, authorize, body_json, must_find, parse_instant_value, validate)

bp = Blueprint("prospects", __name__)

PROSPECT_READ = ["LeasingAgent", "PortfolioAdmin", "RegionalDirector", "Prospect"]
PROSPECT_LIST = ["LeasingAgent", "PortfolioAdmin", "RegionalDirector"]
SLOT_READ = ["LeasingAgent", "PortfolioAdmin", "RegionalDirector", "Prospect"]

BLOCKING_SLOT_STATUSES = {"AVAILABLE", "BOOKED", "BLOCKED_BY_POSTURE"}

PROSPECT_FIELDS = [
    F("email", "string"),
    F("full_name", "string"),
    F("phone", "string"),
    F("market_id", "string"),
    F("declared_monthly_income_cents", "money", minimum=0),
    F("credit_tier", "string", enum=["A", "B", "C", "D"]),
    F("prior_eviction_count", "count", required=False, default=0),
]

VERIFY_FIELDS = [
    F("expected_prospect_version", "count"),
    F("document_type", "string", enum=["NONE", "DRIVERS_LICENSE", "PASSPORT", "STATE_ID"]),
    F("document_match_score_bps", "bps", minimum=0, maximum=10000),
    F("selfie_liveness_pass", "bool"),
    F("verified_monthly_income_cents", "money", minimum=0),
    F("device_reputation_bps", "bps", minimum=0, maximum=10000),
    F("ip_geo_distance_km", "count", minimum=0),
]


@bp.post("/prospects")
def create_prospect():
    data = validate(body_json(), PROSPECT_FIELDS)
    authorize(["Anonymous", "LeasingAgent"])
    market = must_find("markets", data["market_id"], "ERR_MARKET_NOT_FOUND")
    for existing in store.all_rows("prospects"):
        if existing["email"] == data["email"]:
            fail("ERR_DUPLICATE_PROSPECT_EMAIL")
    row = store.base_row()
    row.update({
        "email": data["email"],
        "full_name": data["full_name"],
        "phone": data["phone"],
        "market_id": market["id"],
        "declared_monthly_income_cents": data["declared_monthly_income_cents"],
        "verified_monthly_income_cents": 0,
        "credit_tier": data["credit_tier"],
        "prior_eviction_count": data["prior_eviction_count"],
        "document_type": "NONE",
        "document_match_score_bps": 0,
        "selfie_liveness_pass": False,
        "device_reputation_bps": 0,
        "ip_geo_distance_km": 0,
        "fraud_risk_score_bps": 0,
        "fraud_score_variant": "PRE_VERIFICATION",
        "identity_status": "UNVERIFIED",
        "verification_attempt_count": 0,
    })
    row["fraud_risk_score_bps"] = calc.fraud_score(row, market)
    store.insert("prospects", row)
    return created(views.public(row))


@bp.get("/prospects/<prospect_id>")
def read_prospect(prospect_id):
    authorize(PROSPECT_READ)
    row = must_find("prospects", prospect_id, "ERR_PROSPECT_NOT_FOUND")
    return ok(views.public(row))


@bp.get("/prospects")
def list_prospects():
    authorize(PROSPECT_LIST)
    rows = views.filtered("prospects", [
        ("market_id", "market_id", "string"),
        ("identity_status", "identity_status", "string"),
        ("credit_tier", "credit_tier", "string"),
    ])
    return paginate(rows, views.public)


@bp.post("/prospects/<prospect_id>/identity-verifications")
def verify_identity(prospect_id):
    data = validate(body_json(), VERIFY_FIELDS)
    authorize(["Anonymous", "Prospect"])
    prospect = must_find("prospects", prospect_id, "ERR_PROSPECT_NOT_FOUND")
    if int(data["expected_prospect_version"]) != int(prospect["version"]):
        fail("ERR_STALE_PROSPECT_VERSION")

    previous_status = prospect["identity_status"]
    for name in ("document_type", "document_match_score_bps", "selfie_liveness_pass",
                 "verified_monthly_income_cents", "device_reputation_bps",
                 "ip_geo_distance_km"):
        prospect[name] = data[name]
    prospect["verification_attempt_count"] = int(prospect["verification_attempt_count"]) + 1
    verified = calc.identity_verified(data["selfie_liveness_pass"],
                                      data["document_match_score_bps"])
    prospect["identity_status"] = "VERIFIED" if verified else "REJECTED"
    market = store.get("markets", prospect["market_id"])
    prospect["fraud_risk_score_bps"] = calc.fraud_score(prospect, market)
    prospect["fraud_score_variant"] = "POST_VERIFICATION"
    store.touch(prospect)

    if previous_status == "VERIFIED" and prospect["identity_status"] == "REJECTED":
        cascades.release_booked_slots_for_prospect(prospect["id"])
    return ok(views.public(prospect))


# ---------------------------------------------------------------------------
# The self-showing calendar
# ---------------------------------------------------------------------------


def _minutes_between(later, earlier):
    return int((later - earlier).total_seconds() // 60)


@bp.post("/showing-slots")
def create_slot():
    data = validate(body_json(), [
        F("home_id", "string"),
        F("starts_at", "datetime"),
        F("ends_at", "datetime"),
        F("access_mode", "string", enum=["SMART_LOCK", "LOCKBOX", "AGENT_ESCORT"]),
    ])
    starts = parse_instant_value(data["starts_at"])
    ends = parse_instant_value(data["ends_at"])
    if starts >= ends:
        fail("ERR_INVALID_REQUEST", "Field 'ends_at' must be after 'starts_at'.")
    authorize(["LeasingAgent"])
    home = must_find("homes", data["home_id"], "ERR_HOME_NOT_FOUND")
    market = cascades.market_of(home)

    if _minutes_between(ends, starts) < int(market["min_showing_duration_minutes"]):
        fail("ERR_SLOT_DURATION_INVALID")
    if starts < store.clock_now():
        fail("ERR_SLOT_IN_PAST")
    buffer_minutes = int(market["showing_buffer_minutes"])
    for other in cascades.home_slots(home["id"]):
        if other["status"] not in BLOCKING_SLOT_STATUSES:
            continue
        o_start = parse_instant_value(other["starts_at"])
        o_end = parse_instant_value(other["ends_at"])
        if starts < o_end and o_start < ends:
            fail("ERR_SHOWING_SLOT_OVERLAP")
        gap = (_minutes_between(starts, o_end) if starts >= o_end
               else _minutes_between(o_start, ends))
        if gap < buffer_minutes:
            fail("ERR_SHOWING_SLOT_OVERLAP")

    row = store.base_row()
    row.update({
        "home_id": home["id"],
        "prospect_id": "",
        "starts_at": data["starts_at"],
        "ends_at": data["ends_at"],
        "access_mode": data["access_mode"],
        "status": "AVAILABLE",
        "cancel_reason": "",
    })
    store.insert("showing_slots", row)
    return created(views.public(row))


@bp.get("/showing-slots/<slot_id>")
def read_slot(slot_id):
    authorize(SLOT_READ)
    row = must_find("showing_slots", slot_id, "ERR_SHOWING_SLOT_NOT_FOUND")
    return ok(views.public(row))


@bp.get("/showing-slots")
def list_slots():
    authorize(SLOT_READ)
    rows = views.filtered("showing_slots", [
        ("home_id", "home_id", "string"),
        ("prospect_id", "prospect_id", "string"),
        ("status", "status", "string"),
        ("access_mode", "access_mode", "string"),
    ])
    return paginate(rows, views.public)


@bp.post("/showing-slots/<slot_id>/book")
def book_slot(slot_id):
    data = validate(body_json(), [F("prospect_id", "string")])
    role, user_id = authorize(["Prospect"])
    prospect = must_find("prospects", data["prospect_id"], "ERR_PROSPECT_NOT_FOUND")
    slot = must_find("showing_slots", slot_id, "ERR_SHOWING_SLOT_NOT_FOUND")
    home = store.get("homes", slot["home_id"])
    market = cascades.market_of(home)
    if prospect["market_id"] != home["market_id"]:
        fail("ERR_MARKET_MISMATCH")
    if slot["status"] != "AVAILABLE":
        fail("ERR_SHOWING_SLOT_NOT_AVAILABLE")
    if user_id != prospect["id"]:
        fail("ERR_NOT_SLOT_OWNER")
    if prospect["identity_status"] != "VERIFIED":
        fail("ERR_PROSPECT_IDENTITY_UNVERIFIED")
    if int(prospect["fraud_risk_score_bps"]) > int(market["fraud_block_threshold_bps"]):
        fail("ERR_PROSPECT_FRAUD_BLOCKED")
    if calc.leasing_posture(home) == "FROZEN":
        fail("ERR_HOME_SHOWINGS_BLOCKED")

    slot["status"] = "BOOKED"
    slot["prospect_id"] = prospect["id"]
    store.touch(slot)
    home["booked_showing_count"] = int(home["booked_showing_count"]) + 1
    store.touch(home)
    return ok(views.public(slot))


@bp.post("/showing-slots/<slot_id>/cancel")
def cancel_slot(slot_id):
    data = validate(body_json(), [F("reason", "string")])
    role, user_id = authorize(["Prospect", "LeasingAgent"])
    slot = must_find("showing_slots", slot_id, "ERR_SHOWING_SLOT_NOT_FOUND")
    if slot["status"] not in ("BOOKED", "AVAILABLE"):
        fail("ERR_INVALID_STATE")
    if role == "Prospect" and user_id != slot["prospect_id"]:
        fail("ERR_NOT_SLOT_OWNER")

    if slot["status"] == "BOOKED":
        slot["status"] = "AVAILABLE"
        slot["prospect_id"] = ""
        slot["cancel_reason"] = data["reason"]
        store.touch(slot)
        home = store.get("homes", slot["home_id"])
        if home is not None:
            home["booked_showing_count"] = max(0, int(home["booked_showing_count"]) - 1)
            store.touch(home)
        return ok(views.public(slot))

    slot["status"] = "CANCELLED"
    slot["cancel_reason"] = data["reason"]
    store.touch(slot)
    return ok(views.public(slot))
