"""Expansion options & land banking (PRD §3.6)."""
from flask import Blueprint

from db import store, new_entity, public, touch
from errors import (
    ApiError, ERR_FORBIDDEN, ERR_INVALID_TIME_RANGE, ERR_INVALID_STATE,
    ERR_SITE_NOT_LISTED, ERR_COMPLIANCE_NOT_CLEARED, ERR_INSUFFICIENT_SF,
    ERR_OPTION_WINDOW_NOT_OPEN, ERR_OPTION_WINDOW_EXPIRED,
)
from middleware import (
    authenticate, body, require_fields, get_fk, get_path, ALL_ROLES,
)
from response import success_object
from routes import list_response
from services import cascades
from timeutil import parse_iso

bp = Blueprint("options", __name__)


def _option_owner_uid(option):
    loi = store.lois[option["loi_id"]]
    return store.requirements[loi["requirement_id"]]["tenant_rep_id"]


@bp.post("/api/expansion-options")
def create_option():
    authenticate(["LeasingManager"])
    b = body()
    # Priority 4 (existence), input-list order: loi_id then land_site_id.
    loi = get_fk(b, "loi_id", store.lois)
    land = get_fk(b, "land_site_id", store.sites)
    require_fields(b, [
        ("loi_id", "string", True),
        ("land_site_id", "string", True),
        ("option_sf", "int", True),
        ("window_open_date", "datetime", True),
        ("window_close_date", "datetime", True),
    ])
    if loi is None:
        loi = store.lois[b["loi_id"]]
    if land is None:
        land = store.sites[b["land_site_id"]]
    if b["option_sf"] <= 0:
        from errors import ERR_INVALID_REQUEST
        raise ApiError(ERR_INVALID_REQUEST, "option_sf must be positive", 400)
    # Priority 7: close strictly after open.
    if parse_iso(b["window_close_date"]) <= parse_iso(b["window_open_date"]):
        raise ApiError(ERR_INVALID_TIME_RANGE,
                       "window_close_date must be strictly after window_open_date", 422)
    # Priority 8: the linked LOI must be ACCEPTED or EXECUTED.
    if loi["status"] not in ("ACCEPTED", "EXECUTED"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot grant an option on an LOI in status {loi['status']}", 409)
    # Priority 10: the land parcel must be a LISTED LAND_BANK site.
    if land["parcel_type"] != "LAND_BANK" or land["status"] != "LISTED":
        raise ApiError(ERR_SITE_NOT_LISTED,
                       "The land parcel must be a LISTED LAND_BANK site", 409)
    if land["available_sf"] < b["option_sf"]:
        raise ApiError(ERR_INSUFFICIENT_SF,
                       "land site available_sf is less than option_sf", 422)
    ent = new_entity({
        "loi_id": loi["id"],
        "land_site_id": land["id"],
        "option_sf": b["option_sf"],
        "window_open_date": b["window_open_date"],
        "window_close_date": b["window_close_date"],
        "status": "GRANTED",
    })
    store.options[ent["id"]] = ent
    return success_object(public(ent), 201)


@bp.get("/api/expansion-options")
def list_options():
    authenticate(ALL_ROLES)
    return list_response(store.options.values(), [
        ("loi_id", lambda e: e["loi_id"]),
        ("land_site_id", lambda e: e["land_site_id"]),
        ("status", lambda e: e["status"]),
    ])


@bp.get("/api/expansion-options/<oid>")
def get_option(oid):
    authenticate(ALL_ROLES)
    return success_object(public(get_path(store.options, oid, "expansion option")))


@bp.post("/api/expansion-options/<oid>/exercise")
def exercise_option(oid):
    uid, _ = authenticate(["TenantRep"])
    opt = get_path(store.options, oid, "expansion option")
    # Priority 3: the acting representative must own the linked LOI's requirement.
    if _option_owner_uid(opt) != uid:
        raise ApiError(ERR_FORBIDDEN,
                       "X-User-ID does not own the linked LOI's requirement", 403)
    loi = store.lois[opt["loi_id"]]
    land = store.sites[opt["land_site_id"]]
    # Precedence per PRD §3.6: state -> site listed -> zoning gate ->
    # available SF -> window not open -> window expired.
    if opt["status"] != "GRANTED":
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot exercise an option in status {opt['status']}", 409)
    if land["status"] != "LISTED":
        raise ApiError(ERR_SITE_NOT_LISTED,
                       f"Land parcel is in status {land['status']}", 409)
    zoning_cleared = any(
        r["site_id"] == land["id"] and r["requirement_id"] == loi["requirement_id"]
        and r["review_type"] == "ZONING_USE" and r["status"] == "CLEARED"
        for r in store.reviews.values())
    if not zoning_cleared:
        raise ApiError(ERR_COMPLIANCE_NOT_CLEARED,
                       "No CLEARED ZONING_USE review for the land parcel and requirement", 409)
    if land["available_sf"] < opt["option_sf"]:
        raise ApiError(ERR_INSUFFICIENT_SF,
                       "land site available_sf is less than option_sf", 422)
    if store.clock < parse_iso(opt["window_open_date"]):
        raise ApiError(ERR_OPTION_WINDOW_NOT_OPEN,
                       "The option window has not opened on the logical clock", 409)
    if store.clock > parse_iso(opt["window_close_date"]):
        # Inclusive close: a late attempt flips the option to EXPIRED and fails.
        opt["status"] = "EXPIRED"
        touch(opt)
        raise ApiError(ERR_OPTION_WINDOW_EXPIRED,
                       "The option window closed before the logical clock", 409)
    opt["status"] = "EXERCISED"
    touch(opt)
    cascades.site_reserve(land, opt["option_sf"])
    return success_object(public(opt))


@bp.post("/api/expansion-options/<oid>/release")
def release_option(oid):
    uid, _ = authenticate(["TenantRep"])
    opt = get_path(store.options, oid, "expansion option")
    if _option_owner_uid(opt) != uid:
        raise ApiError(ERR_FORBIDDEN,
                       "X-User-ID does not own the linked LOI's requirement", 403)
    if opt["status"] != "GRANTED":
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot release an option in status {opt['status']}", 409)
    opt["status"] = "RELEASED"
    touch(opt)
    return success_object(public(opt))
