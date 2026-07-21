"""Logical clock, subscription plans, stores and artist accounts — PRD §2.5, §3.1."""

from flask import Blueprint, request

from db import db, format_iso, set_clock, common_fields, touch
from errors import ApiError
from middleware import auth, require_ownership
from response import created, ok, ok_list, paginate, read_pagination
from services import core
import validation as v

bp = Blueprint("catalogue", __name__)


# ---- logical clock --------------------------------------------------------

@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    auth("PlatformAdmin")
    data = v.body()
    target = v.req_datetime(data, "to_iso8601")
    set_clock(target)
    return ok({"current_utc": format_iso(target)})


# ---- subscription plans ---------------------------------------------------

@bp.post("/api/subscription-plans")
def create_plan():
    auth("PlatformAdmin")
    data = v.body()
    code = v.req_string(data, "code", min_len=2, max_len=32)
    name = v.req_string(data, "name")
    annual_fee_cents = v.req_int(data, "annual_fee_cents", minimum=0)
    included_release_slots = v.req_int(data, "included_release_slots", minimum=1)
    commission_bps = v.req_int(data, "commission_bps", minimum=0, maximum=10000)
    allows_content_id, has_acid = v.opt_bool(data, "allows_content_id")
    status, has_status = v.opt_enum(data, "status", {"ACTIVE", "RETIRED"})

    if any(p["code"] == code for p in db.subscription_plans.values()):
        raise ApiError("ERR_DUPLICATE_IDENTIFIER", "Plan code already in use.")

    row = common_fields()
    row.update({
        "code": code,
        "name": name,
        "annual_fee_cents": annual_fee_cents,
        "included_release_slots": included_release_slots,
        "commission_bps": commission_bps,
        "allows_content_id": allows_content_id if has_acid else False,
        "status": status if has_status else "ACTIVE",
    })
    db.subscription_plans[row["id"]] = row
    return created(row)


@bp.get("/api/subscription-plans/<plan_id>")
def read_plan(plan_id):
    auth("PlatformAdmin", "Artist", "FinanceOps", "DistributionOps")
    return ok(core.find_plan(plan_id))


@bp.get("/api/subscription-plans")
def list_plans():
    auth("PlatformAdmin", "Artist", "FinanceOps", "DistributionOps")
    limit, offset = read_pagination(request.args)
    rows = list(db.subscription_plans.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


# ---- stores ---------------------------------------------------------------

@bp.post("/api/stores")
def create_store():
    auth("PlatformAdmin")
    data = v.body()
    code = v.req_string(data, "code")
    name = v.req_string(data, "name")
    delivery_lead_days = v.req_int(data, "delivery_lead_days", minimum=0)
    supports_pre_save, has_sps = v.opt_bool(data, "supports_pre_save")
    requires_isrc, has_ri = v.opt_bool(data, "requires_isrc")
    requires_explicit_flag, has_ref = v.opt_bool(data, "requires_explicit_flag")
    surcharge_bps, has_sur = v.opt_int(data, "surcharge_bps", minimum=0, maximum=2000)
    max_concurrent, has_mcd = v.opt_int(data, "max_concurrent_deliveries", minimum=1)
    status, has_status = v.opt_enum(data, "status", {"ACTIVE", "PAUSED"})

    if any(s["code"] == code for s in db.stores.values()):
        raise ApiError("ERR_DUPLICATE_IDENTIFIER", "Store code already in use.")

    row = common_fields()
    row.update({
        "code": code,
        "name": name,
        "supports_pre_save": supports_pre_save if has_sps else False,
        "requires_isrc": requires_isrc if has_ri else True,
        "requires_explicit_flag": requires_explicit_flag if has_ref else True,
        "delivery_lead_days": delivery_lead_days,
        "surcharge_bps": surcharge_bps if has_sur else 0,
        "max_concurrent_deliveries": max_concurrent if has_mcd else 2,
        "status": status if has_status else "ACTIVE",
    })
    db.stores[row["id"]] = row
    return created(row)


@bp.get("/api/stores/<store_id>")
def read_store(store_id):
    auth("PlatformAdmin", "DistributionOps", "FinanceOps", "Artist")
    return ok(core.find_store(store_id))


@bp.get("/api/stores")
def list_stores():
    auth("PlatformAdmin", "DistributionOps", "FinanceOps", "Artist")
    limit, offset = read_pagination(request.args)
    rows = list(db.stores.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


# ---- artists --------------------------------------------------------------

@bp.post("/api/artists")
def create_artist():
    auth("PlatformAdmin")
    data = v.body()
    display_name = v.req_string(data, "display_name")
    legal_name = v.req_string(data, "legal_name")
    country_code = v.check_country(v.req_string(data, "country_code"))
    email = v.req_string(data, "email")

    if any(a["email"] == email for a in db.artists.values()):
        raise ApiError("ERR_DUPLICATE_IDENTIFIER", "Artist email already in use.")

    row = common_fields()
    row.update({
        "display_name": display_name,
        "legal_name": legal_name,
        "country_code": country_code,
        "email": email,
        "status": "ACTIVE",
        "lifetime_gross_cents": 0,
        "live_track_count": 0,
    })
    db.artists[row["id"]] = row
    return created(row)


@bp.get("/api/artists/<artist_id>")
def read_artist(artist_id):
    user_id, role = auth("PlatformAdmin", "Artist", "FinanceOps", "DistributionOps")
    if role == "Artist":
        require_ownership(user_id == artist_id)
    return ok(core.find_artist(artist_id))


@bp.get("/api/artists")
def list_artists():
    auth("PlatformAdmin", "FinanceOps", "DistributionOps")
    limit, offset = read_pagination(request.args)
    rows = list(db.artists.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.patch("/api/artists/<artist_id>")
def update_artist(artist_id):
    auth("PlatformAdmin")
    data = v.body()
    display_name, has_dn = v.opt_string(data, "display_name", nullable=False)
    legal_name, has_ln = v.opt_string(data, "legal_name", nullable=False)
    country_code, has_cc = v.opt_string(data, "country_code", nullable=False)
    if has_cc:
        v.check_country(country_code)
    status, has_status = v.opt_enum(data, "status", {"ACTIVE", "SUSPENDED", "CLOSED"})

    artist = core.find_artist(artist_id)
    if has_dn:
        artist["display_name"] = display_name
    if has_ln:
        artist["legal_name"] = legal_name
    if has_cc:
        artist["country_code"] = country_code
    if has_status:
        artist["status"] = status
    touch(artist)
    return ok(artist)
