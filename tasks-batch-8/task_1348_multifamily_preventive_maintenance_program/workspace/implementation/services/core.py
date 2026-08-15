"""Entity lookups, property-chain resolution, serializers, and cost math."""
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from calendar import monthrange

import errors as E
from errors import ApiError
from db import store, now

OPEN_WO_STATES = ("OPEN", "IN_REVIEW", "APPROVED", "IN_PROGRESS")


# ---------------------------------------------------------------------------
# Existence lookups (pipeline stage 3)
# ---------------------------------------------------------------------------

def _get(table, _id, error_id, label):
    rec = getattr(store, table).get(_id) if isinstance(_id, str) else None
    if rec is None:
        raise ApiError(error_id, 404, "%s not found: %s" % (label, _id))
    return rec


def get_property(pid):
    return _get("properties", pid, E.ERR_PROPERTY_NOT_FOUND, "property")


def get_building(bid):
    return _get("buildings", bid, E.ERR_BUILDING_NOT_FOUND, "building")


def get_unit(uid):
    return _get("units", uid, E.ERR_UNIT_NOT_FOUND, "unit")


def get_asset(aid):
    return _get("assets", aid, E.ERR_ASSET_NOT_FOUND, "asset")


def get_template(tid):
    return _get("templates", tid, E.ERR_TEMPLATE_NOT_FOUND, "template")


def get_plan(pid):
    return _get("plans", pid, E.ERR_PLAN_NOT_FOUND, "plan")


def get_batch(bid):
    return _get("batches", bid, E.ERR_BATCH_NOT_FOUND, "batch")


def get_visit(vid):
    return _get("visits", vid, E.ERR_VISIT_NOT_FOUND, "visit")


def get_deficiency(did):
    return _get("deficiencies", did, E.ERR_DEFICIENCY_NOT_FOUND, "deficiency")


def get_work_order(wid):
    return _get("work_orders", wid, E.ERR_WORK_ORDER_NOT_FOUND, "work order")


# ---------------------------------------------------------------------------
# Property chain resolution + archival gate (pipeline stage 4)
# ---------------------------------------------------------------------------

def property_of_building(b):
    return store.properties.get(b["property_id"])


def property_of_unit(u):
    b = store.buildings.get(u["building_id"])
    return property_of_building(b) if b else None


def property_of_asset(a):
    u = store.units.get(a["unit_id"])
    return property_of_unit(u) if u else None


def property_of_visit(v):
    b = store.batches.get(v["batch_id"])
    return store.properties.get(b["property_id"]) if b else None


def property_of_deficiency(d):
    v = store.visits.get(d["visit_id"])
    return property_of_visit(v) if v else None


def property_of_work_order(wo):
    return store.properties.get(wo["property_id"])


def require_active_property(prop):
    if prop is not None and prop["status"] == "ARCHIVED":
        raise ApiError(E.ERR_PROPERTY_ARCHIVED, 409,
                       "Property %s is ARCHIVED; mutations are rejected" % prop["id"])


# ---------------------------------------------------------------------------
# Money math (PRD §2.7): round half-up per event, then sum
# ---------------------------------------------------------------------------

def round_half_up_cents(minutes, rate_cents_per_hour):
    val = (Decimal(minutes * rate_cents_per_hour) / Decimal(60)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(val)


def estimated_visit_cost(template, prop):
    return round_half_up_cents(template["estimated_labor_minutes"],
                               prop["default_labor_rate_cents_per_hour"])


def actual_visit_cost(actual_minutes, prop):
    return round_half_up_cents(actual_minutes,
                               prop["default_labor_rate_cents_per_hour"])


# ---------------------------------------------------------------------------
# Calendar helpers
# ---------------------------------------------------------------------------

def add_months_date(d, months):
    total = (d.year * 12 + (d.month - 1)) + months
    y, m0 = divmod(total, 12)
    m = m0 + 1
    day = min(d.day, monthrange(y, m)[1])
    return date(y, m, day)


def add_years_dt(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # Feb 29 -> Feb 28
        return dt.replace(year=dt.year + years, day=28)


def age_months(installed_date, clock):
    """Whole calendar months between installed_on and the logical clock date."""
    months = (clock.year - installed_date.year) * 12 + (clock.month - installed_date.month)
    if clock.day < installed_date.day:
        months -= 1
    return months


def warranty_active(installed_date, warranty_months, clock):
    return age_months(installed_date, clock) < warranty_months
