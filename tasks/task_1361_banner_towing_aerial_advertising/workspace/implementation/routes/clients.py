"""Clients and Campaigns (PRD 3.2)."""
from flask import Blueprint, request

from db import DB
from errors import ApiError
from middleware import auth, client_owner_guard
from response import ok, ok_list
from services import (
    cancel_slot_by_client,
    flight_subtotal,
    get_campaign,
    get_client,
    maybe_complete_campaign,
    new_record,
    pub,
    recompute_campaign,
    sorted_created,
    touch,
)
from util import (
    as_bool,
    as_month,
    as_str,
    as_version,
    body,
    pagination_args,
    required,
)

bp = Blueprint("clients", __name__, url_prefix="/btaa")

CLIENT_READ = ["PlatformAdmin", "FinanceOfficer", "ComplianceOfficer", "Client"]
CAMPAIGN_READ = [
    "PlatformAdmin",
    "FinanceOfficer",
    "ComplianceOfficer",
    "Dispatcher",
    "Client",
]


def _list(recs, filters):
    items = sorted_created(recs)
    for key, val in filters.items():
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([pub(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
@bp.post("/clients")
def create_client():
    auth(["PlatformAdmin"])
    data = body()
    legal_name = as_str(required(data, "legal_name"), "legal_name")
    billing_email = as_str(required(data, "billing_email"), "billing_email")
    rec = new_record()
    rec.update(
        {
            "legal_name": legal_name,
            "billing_email": billing_email,
            "credit_hold": False,
            "outstanding_balance_cents": 0,
        }
    )
    DB["clients"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.get("/clients/<cid>")
def get_one_client(cid):
    user_id, role = auth(CLIENT_READ)
    c = get_client(cid)
    client_owner_guard(role, user_id, c["id"])
    return ok(pub(c))


@bp.post("/clients/<cid>/set_credit_hold")
def set_credit_hold(cid):
    auth(["FinanceOfficer"])
    c = get_client(cid)
    data = body()
    hold = as_bool(required(data, "credit_hold"), "credit_hold")
    c["credit_hold"] = hold
    touch(c)
    return ok(pub(c))


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------
@bp.post("/clients/<cid>/campaigns")
def create_campaign(cid):
    user_id, role = auth(["Client", "PlatformAdmin"])
    c = get_client(cid)
    # Credit hold blocks new work (PRD 3.2): ERR_CLIENT_CREDIT_HOLD (402).
    if c["credit_hold"]:
        raise ApiError(
            "ERR_CLIENT_CREDIT_HOLD", 402, "Client is under a credit hold"
        )
    # RBAC: clients may create campaigns for themselves only.
    client_owner_guard(role, user_id, c["id"])
    data = body()
    name = as_str(required(data, "name"), "name")
    rec = new_record()
    rec.update(
        {
            "client_id": c["id"],
            "name": name,
            "status": "DRAFT",
            "booked_flight_count": 0,
            "flown_flight_count": 0,
            "cancelled_weather_count": 0,
            "unapplied_make_good_cents": 0,
        }
    )
    DB["campaigns"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.get("/clients/<cid>/campaigns")
def list_campaigns(cid):
    user_id, role = auth(CAMPAIGN_READ)
    c = get_client(cid)
    client_owner_guard(role, user_id, c["id"])
    recs = [x for x in DB["campaigns"].values() if x["client_id"] == c["id"]]
    return _list(recs, {"status": request.args.get("status")})


@bp.get("/campaigns/<cid>")
def get_one_campaign(cid):
    user_id, role = auth(CAMPAIGN_READ + ["Pilot", "GroundCrewLead"])
    camp = get_campaign(cid)
    client_owner_guard(role, user_id, camp["client_id"])
    return ok(pub(camp))


@bp.post("/campaigns/<cid>/book")
def book_campaign(cid):
    user_id, role = auth(["Client"])
    camp = get_campaign(cid)
    data = body()
    expected = as_version(
        required(data, "expected_campaign_version"), "expected_campaign_version"
    )
    if camp["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Campaign is not in a state permitting book"
        )
    # Booking requires at least one child slot already in BOOKED (PRD 3.2).
    has_booked = any(
        s["campaign_id"] == camp["id"] and s["status"] == "BOOKED"
        for s in DB["flight_slots"].values()
    )
    if not has_booked:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Campaign has no FlightSlot in BOOKED status",
        )
    client = get_client(camp["client_id"])
    if client["credit_hold"]:
        raise ApiError(
            "ERR_CLIENT_CREDIT_HOLD", 402, "Client is under a credit hold"
        )
    # Ownership (PRD 2.1): a client may book only its own campaign.
    client_owner_guard(role, user_id, camp["client_id"])
    # OCC runs last of all, after every business rule has passed (PRD 2.7/2.10).
    if expected != camp["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412, "expected_campaign_version is stale"
        )
    camp["status"] = "BOOKED"
    touch(camp)
    return ok(pub(camp))


@bp.post("/campaigns/<cid>/cancel")
def cancel_campaign(cid):
    user_id, role = auth(["Client"])
    camp = get_campaign(cid)
    st = camp["status"]
    if st not in ("DRAFT", "BOOKED", "IN_FLIGHT"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Campaign is not in a state permitting cancel",
        )
    slots = [s for s in DB["flight_slots"].values() if s["campaign_id"] == camp["id"]]
    # Escalating strictness (PRD 3.2): from DRAFT no BOOKED/SCHEDULED/
    # WEATHER_HOLD may exist; from BOOKED/IN_FLIGHT only SCHEDULED/WEATHER_HOLD
    # block cancellation.
    if st == "DRAFT":
        blocked = ("BOOKED", "SCHEDULED", "WEATHER_HOLD")
        cascade_from = ("DRAFT",)
    else:
        blocked = ("SCHEDULED", "WEATHER_HOLD")
        cascade_from = ("DRAFT", "BOOKED")
    if any(s["status"] in blocked for s in slots):
        raise ApiError(
            "ERR_CAMPAIGN_HAS_OPEN_SLOTS",
            409,
            "Campaign has open flight slots",
        )
    # Only the campaign-owning client may cancel (PRD 3.2).
    client_owner_guard(role, user_id, camp["client_id"])
    for s in slots:
        if s["status"] in cascade_from:
            cancel_slot_by_client(s)
    camp["status"] = "CANCELLED"
    touch(camp)
    recompute_campaign(camp)
    return ok(pub(camp))


@bp.get("/campaigns/<cid>/billing_preview")
def billing_preview(cid):
    user_id, role = auth(["PlatformAdmin", "FinanceOfficer", "Client"])
    camp = get_campaign(cid)
    client_owner_guard(role, user_id, camp["client_id"])
    period = request.args.get("period_yyyy_mm")
    if period is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Missing required parameter: period_yyyy_mm"
        )
    period = as_month(period, "period_yyyy_mm")
    # Provisional variant (PRD 3.8): un-flown BOOKED/SCHEDULED slots count at
    # planned hours; never includes penalties or credit applications.
    subtotal = flight_subtotal(camp["id"], period, provisional=True)
    return ok(
        {
            "flight_subtotal_cents": subtotal,
            "cancellation_penalty_cents": 0,
            "make_good_applied_cents": 0,
            "total_cents": subtotal,
        }
    )
