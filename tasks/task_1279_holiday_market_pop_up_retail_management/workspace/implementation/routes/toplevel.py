"""Top-level cross-market collection endpoints, top-level single-resource
GETs, and the logical clock endpoint."""
from flask import Blueprint

import clock
import db
from middleware import auth, require_roles
from response import success
from services import cascades
from services.core import (
    arg,
    arg_bool,
    as_dt,
    body,
    get_child,
    list_response,
    required,
    serialize,
)
from dates import fmt_dt

bp = Blueprint("toplevel", __name__)


def _category_of(app):
    vendor = db.STORES["vendors"].get(app["vendor_id"])
    return vendor["category"] if vendor else None


def _cross_list(store, roles, extra_filters=None, sync=False):
    user = auth()
    require_roles(user, roles)
    if sync:
        cascades.sync_programming()
    records = list(db.STORES[store].values())
    for name, value in (extra_filters or []):
        if value is None:
            continue
        if name == "category" and store == "applications":
            records = [r for r in records if _category_of(r) == value]
        elif name == "triggers_alert":
            records = [r for r in records if r["triggers_alert"] == value]
        else:
            records = [r for r in records if r.get(name) == value]
    return list_response(records)


def _top_get(store, roles, rec_id):
    user = auth()
    require_roles(user, roles)
    if store == "programming":
        cascades.sync_programming()
    return success(serialize(get_child(store, rec_id)))


# ------------------------------------------------------------- applications
APP_READ = ("MarketOperator", "VendorRole", "JuryMember", "JuryChair")
APP_LIST = ("MarketOperator", "JuryMember", "JuryChair")


@bp.get("/markets/applications")
def cross_applications():
    return _cross_list(
        "applications",
        APP_LIST,
        [
            ("market_id", arg("market_id")),
            ("vendor_id", arg("vendor_id")),
            ("status", arg("status")),
            ("category", arg("category")),
        ],
    )


@bp.get("/markets/applications/<applicationId>")
def top_application(applicationId):
    return _top_get("applications", APP_READ, applicationId)


# ------------------------------------------------------------- booths
BOOTH_READ = ("MarketOperator", "VendorRole", "JuryChair", "UtilityCrew")


@bp.get("/markets/booths")
def cross_booths():
    return _cross_list(
        "booths",
        BOOTH_READ,
        [
            ("market_id", arg("market_id")),
            ("status", arg("status")),
            ("booth_type", arg("booth_type")),
            ("zone", arg("zone")),
        ],
    )


@bp.get("/markets/booths/<boothId>")
def top_booth(boothId):
    return _top_get("booths", BOOTH_READ, boothId)


# ------------------------------------------------------------- assignments
ASSIGN_READ = ("MarketOperator", "VendorRole", "FinanceOfficer")
ASSIGN_LIST = ("MarketOperator", "FinanceOfficer")


@bp.get("/markets/assignments")
def cross_assignments():
    return _cross_list(
        "assignments",
        ASSIGN_LIST,
        [
            ("market_id", arg("market_id")),
            ("booth_id", arg("booth_id")),
            ("application_id", arg("application_id")),
            ("status", arg("status")),
        ],
    )


@bp.get("/markets/assignments/<assignmentId>")
def top_assignment(assignmentId):
    return _top_get("assignments", ASSIGN_READ, assignmentId)


# ------------------------------------------------------------- permits
PERMIT_READ = ("MarketOperator", "VendorRole", "UtilityCrew")
PERMIT_LIST = ("MarketOperator", "UtilityCrew")


@bp.get("/markets/permits")
def cross_permits():
    return _cross_list(
        "permits",
        PERMIT_LIST,
        [
            ("market_id", arg("market_id")),
            ("assignment_id", arg("assignment_id")),
            ("status", arg("status")),
            ("permit_type", arg("permit_type")),
        ],
    )


@bp.get("/markets/permits/<permitId>")
def top_permit(permitId):
    return _top_get("permits", PERMIT_READ, permitId)


# ------------------------------------------------------------- hookups
HOOKUP_ROLES = ("MarketOperator", "UtilityCrew")


@bp.get("/markets/hookups")
def cross_hookups():
    return _cross_list(
        "hookups",
        HOOKUP_ROLES,
        [
            ("market_id", arg("market_id")),
            ("booth_id", arg("booth_id")),
            ("status", arg("status")),
            ("hookup_type", arg("hookup_type")),
        ],
    )


@bp.get("/markets/hookups/<hookupId>")
def top_hookup(hookupId):
    return _top_get("hookups", HOOKUP_ROLES, hookupId)


# ------------------------------------------------------------- pos devices
POS_READ = ("MarketOperator", "VendorRole", "FinanceOfficer")
POS_LIST = ("MarketOperator", "FinanceOfficer")


@bp.get("/markets/pos_devices")
def cross_pos_devices():
    return _cross_list(
        "pos_devices",
        POS_LIST,
        [
            ("market_id", arg("market_id")),
            ("assignment_id", arg("assignment_id")),
            ("status", arg("status")),
        ],
    )


@bp.get("/markets/pos_devices/<posDeviceId>")
def top_pos_device(posDeviceId):
    return _top_get("pos_devices", POS_READ, posDeviceId)


# ------------------------------------------------------------- settlements
SETTLE_READ = ("MarketOperator", "VendorRole", "FinanceOfficer")
SETTLE_LIST = ("MarketOperator", "FinanceOfficer")


@bp.get("/markets/settlements")
def cross_settlements():
    return _cross_list(
        "settlements",
        SETTLE_LIST,
        [
            ("market_id", arg("market_id")),
            ("assignment_id", arg("assignment_id")),
            ("status", arg("status")),
            ("business_date", arg("business_date")),
        ],
    )


@bp.get("/markets/settlements/<settlementId>")
def top_settlement(settlementId):
    return _top_get("settlements", SETTLE_READ, settlementId)


# ------------------------------------------------------------- programming
PROG_ROLES = ("MarketOperator", "VendorRole")


@bp.get("/markets/programming")
def cross_programming():
    return _cross_list(
        "programming",
        PROG_ROLES,
        [
            ("market_id", arg("market_id")),
            ("vendor_id", arg("vendor_id")),
            ("status", arg("status")),
            ("slot_kind", arg("slot_kind")),
        ],
        sync=True,
    )


@bp.get("/markets/programming/<slotId>")
def top_programming(slotId):
    return _top_get("programming", PROG_ROLES, slotId)


# ------------------------------------------------------------- load slots
LOAD_ROLES = ("MarketOperator", "VendorRole")


@bp.get("/markets/load_slots")
def cross_load_slots():
    return _cross_list(
        "load_slots",
        LOAD_ROLES,
        [
            ("market_id", arg("market_id")),
            ("assignment_id", arg("assignment_id")),
            ("status", arg("status")),
            ("direction", arg("direction")),
        ],
    )


@bp.get("/markets/load_slots/<loadSlotId>")
def top_load_slot(loadSlotId):
    return _top_get("load_slots", LOAD_ROLES, loadSlotId)


# ------------------------------------------------------------- weather events
WEATHER_READ = ("MarketOperator", "VendorRole", "UtilityCrew")
WEATHER_LIST = ("MarketOperator", "UtilityCrew")


@bp.get("/markets/weather_events")
def cross_weather_events():
    return _cross_list(
        "weather_events",
        WEATHER_LIST,
        [
            ("market_id", arg("market_id")),
            ("triggers_alert", arg_bool("triggers_alert")),
            ("source", arg("source")),
        ],
    )


@bp.get("/markets/weather_events/<weatherEventId>")
def top_weather_event(weatherEventId):
    return _top_get("weather_events", WEATHER_READ, weatherEventId)


# ------------------------------------------------------------- renewal offers
RENEWAL_ROLES = ("MarketOperator", "VendorRole")


@bp.get("/markets/renewal_offers")
def cross_renewal_offers():
    return _cross_list(
        "renewal_offers",
        RENEWAL_ROLES,
        [
            ("market_id", arg("market_id")),
            ("vendor_id", arg("vendor_id")),
            ("status", arg("status")),
            ("prior_assignment_id", arg("prior_assignment_id")),
            ("offered_booth_id", arg("offered_booth_id")),
        ],
    )


@bp.get("/markets/renewal_offers/<offerId>")
def top_renewal_offer(offerId):
    return _top_get("renewal_offers", RENEWAL_ROLES, offerId)


# ------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_current_utc():
    user = auth()
    require_roles(user, ("MarketOperator",))
    data = body()
    target = as_dt(required(data, "to_iso8601"), "to_iso8601")
    clock.set_current(target)
    return success({"current_utc": fmt_dt(clock.now())})
