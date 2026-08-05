"""Clock, zones, property owners, parcels and officers (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import aggregates
import auth
import calc
import envelope
import lclock
import lookups
import serialize
import store
import valid
from errors import ApiError

bp = Blueprint("registry", __name__)
P = "/vector-control"

PROPERTY_TYPES = (
    "RESIDENTIAL_SINGLE",
    "RESIDENTIAL_MULTI",
    "COMMERCIAL_FOOD",
    "COMMERCIAL_OTHER",
    "VACANT_LOT",
)
NOTICE_PREFERENCES = ("FIRST_CLASS_MAIL", "CERTIFIED_MAIL", "PERSONAL_SERVICE")
RANKS = ("FIELD_INSPECTOR", "SUPERVISOR")


# --- logical clock ------------------------------------------------------


@bp.post(P + "/_clock/set_current_utc")
def set_clock():
    auth.guard("ProgramAdmin")
    data = valid.body()
    target = valid.req_dt(data, "to_iso8601")
    previous = lclock.set_now(target)
    return envelope.obj(
        {
            "current_utc": lclock.render(lclock.now()),
            "previous_utc": lclock.render(previous),
        }
    )


# --- zones --------------------------------------------------------------


@bp.post(P + "/zones")
def create_zone():
    auth.guard("ProgramAdmin")
    data = valid.body()
    name = valid.req_str(data, "name", min_len=1, max_len=120)
    code = valid.req_str(data, "code", min_len=2, max_len=16)
    density = valid.req_int(data, "population_density_per_sqkm", minimum=0)
    if any(z["code"] == code for z in store.zones.values()):
        raise ApiError("ERR_DUPLICATE_CODE", "Zone code '%s' is already taken." % code)
    zone = store.stamp_new(
        {
            "name": name,
            "code": code,
            "population_density_per_sqkm": density,
            "posture": "NORMAL",
            "rodent_index": Decimal("0.00"),
            "open_complaint_count": 0,
            "chronic_property_count": 0,
            "active_station_count": 0,
            "last_index_recomputed_at": None,
        }
    )
    store.zones[zone["id"]] = zone
    return envelope.obj(serialize.zone(zone), 201)


@bp.get(P + "/zones/<zone_id>")
def read_zone(zone_id):
    auth.guard("ProgramAdmin", "Supervisor", "Inspector", "IntakeClerk", "FinanceOfficer")
    zone = lookups.zone(zone_id)
    return envelope.obj(serialize.zone(zone))


@bp.get(P + "/zones/<zone_id>/surveillance-summary")
def zone_surveillance_summary(zone_id):
    auth.guard("ProgramAdmin", "Supervisor", "Inspector")
    zone = lookups.zone(zone_id)
    result = aggregates.zone_index(zone)
    return envelope.obj(
        {
            "zone_id": zone["id"],
            "rodent_index": calc.num(result["rodent_index"]),
            "posture": result["posture"],
            "bait_component": calc.num(result["bait_component"]),
            "sign_component": calc.num(result["sign_component"]),
            "complaint_component": calc.num(result["complaint_component"]),
            "in_window_reading_count": result["in_window_reading_count"],
            "eligible_station_count": result["eligible_station_count"],
            "open_complaint_count": result["open_complaint_count"],
            "window_start": lclock.render(result["window_start"]),
            "window_end": lclock.render(result["window_end"]),
        }
    )


# --- property owners ----------------------------------------------------


@bp.post(P + "/property-owners")
def create_owner():
    auth.guard("ProgramAdmin")
    data = valid.body()
    full_name = valid.req_str(data, "full_name", min_len=1, max_len=120)
    email = valid.req_str(data, "email", min_len=1)
    mailing_address = valid.req_str(data, "mailing_address", min_len=1)
    preference = valid.opt_enum(data, "notice_preference", NOTICE_PREFERENCES, "CERTIFIED_MAIL")
    hardship = valid.opt_bool(data, "hardship_certified", False)
    owner = store.stamp_new(
        {
            "full_name": full_name,
            "email": email,
            "mailing_address": mailing_address,
            "notice_preference": preference,
            "hardship_certified": hardship,
            "outstanding_balance_cents": 0,
            "lifetime_paid_cents": 0,
        }
    )
    store.owners[owner["id"]] = owner
    return envelope.obj(serialize.owner(owner), 201)


@bp.get(P + "/property-owners/<owner_id>")
def read_owner(owner_id):
    caller = auth.guard("ProgramAdmin", "Supervisor", "FinanceOfficer", "PropertyOwner")
    owner = lookups.owner(owner_id)
    auth.require_owner(caller, owner["id"])
    return envelope.obj(serialize.owner(owner))


# --- parcels ------------------------------------------------------------


@bp.post(P + "/properties")
def create_property():
    auth.guard("ProgramAdmin")
    data = valid.body()
    zone_id = data.get("zone_id")
    owner_id = data.get("owner_id")
    if isinstance(zone_id, str) and zone_id:
        lookups.zone(zone_id)
    if isinstance(owner_id, str) and owner_id:
        lookups.owner(owner_id)
    zone_id = valid.req_id(data, "zone_id")
    owner_id = valid.req_id(data, "owner_id")
    address_line = valid.req_str(data, "address_line", min_len=1)
    parcel_number = valid.req_str(data, "parcel_number", min_len=1)
    property_type = valid.req_enum(data, "property_type", PROPERTY_TYPES)
    unit_count = valid.opt_int(data, "unit_count", 1, minimum=1)
    if any(p["parcel_number"] == parcel_number for p in store.properties.values()):
        raise ApiError("ERR_DUPLICATE_CODE", "parcel_number '%s' is already taken." % parcel_number)
    prop = store.stamp_new(
        {
            "zone_id": zone_id,
            "owner_id": owner_id,
            "address_line": address_line,
            "parcel_number": parcel_number,
            "property_type": property_type,
            "unit_count": unit_count,
            "provisional_chronic_score": Decimal("0.00"),
            "chronic_score": Decimal("0.00"),
            "chronic_flag": False,
            "open_order_count": 0,
            "lien_encumbered": False,
            "last_inspection_at": None,
        }
    )
    store.properties[prop["id"]] = prop
    return envelope.obj(serialize.prop(prop), 201)


@bp.get(P + "/properties/<property_id>")
def read_property(property_id):
    caller = auth.guard(
        "ProgramAdmin", "Supervisor", "Inspector", "IntakeClerk", "FinanceOfficer", "PropertyOwner"
    )
    prop = lookups.prop(property_id)
    auth.require_owner(caller, prop["owner_id"])
    return envelope.obj(serialize.prop(prop))


@bp.get(P + "/properties")
def list_properties():
    auth.guard("ProgramAdmin", "Supervisor", "Inspector", "IntakeClerk", "FinanceOfficer")
    limit, offset = valid.pagination()
    zone_id = valid.query_str("zone_id")
    owner_id = valid.query_str("owner_id")
    chronic_flag = valid.query_bool("chronic_flag")

    def keep(p):
        if zone_id is not None and p["zone_id"] != zone_id:
            return False
        if owner_id is not None and p["owner_id"] != owner_id:
            return False
        if chronic_flag is not None and p["chronic_flag"] != chronic_flag:
            return False
        return True

    rows = store.ordered(store.properties, keep)
    return lookups.page(rows, limit, offset, serialize.prop)


# --- officers -----------------------------------------------------------


@bp.post(P + "/officers")
def create_officer():
    auth.guard("ProgramAdmin")
    data = valid.body()
    full_name = valid.req_str(data, "full_name", min_len=1)
    badge_number = valid.req_str(data, "badge_number", min_len=1)
    rank = valid.req_enum(data, "rank", RANKS)
    certification_expires_at = valid.req_dt(data, "certification_expires_at")
    if any(o["badge_number"] == badge_number for o in store.officers.values()):
        raise ApiError("ERR_DUPLICATE_CODE", "badge_number '%s' is already taken." % badge_number)
    officer = store.stamp_new(
        {
            "full_name": full_name,
            "badge_number": badge_number,
            "rank": rank,
            "certification_expires_at": certification_expires_at,
            "active_assignment_count": 0,
        }
    )
    store.officers[officer["id"]] = officer
    return envelope.obj(serialize.officer(officer), 201)
