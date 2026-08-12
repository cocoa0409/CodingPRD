"""VendorMobilization endpoints (§3.5): predecessor chain, half-open overlap,
market crew-day capacity, readiness and the automatic advance to PUNCH."""
from datetime import timedelta

from flask import Blueprint

import clock
from db import store
from errors import ApiError
from middleware import ALL_ROLES, authed
from response import ok
from routes import list_response, require_state
from services.budget import recompute_readiness
from services.forecast import recompute_commitment_for_site
from util import bump, new_entity, parse_date, serialize
from validate import body_fk, get_or_404, json_body, req_date, req_enum, req_str

bp = Blueprint("mobilizations", __name__)

TERMINAL = ("COMPLETE", "CANCELLED")
VENDOR_TYPES = ("FIXTURE", "IT", "SIGNAGE")
PREDECESSOR = {"FIXTURE": None, "IT": "FIXTURE", "SIGNAGE": "IT"}
BLOCKING_STATUSES = ("PLANNED", "SCHEDULED", "ON_SITE")


@bp.route("/rollout/vendor-mobilizations", methods=["POST"], strict_slashes=False)
@authed(["SiteSuperintendent"])
def create_mobilization():
    body = json_body()
    site = body_fk(body, "site_id", store.sites)
    vendor_type = req_enum(body, "vendor_type", VENDOR_TYPES)
    vendor_name = req_str(body, "vendor_name")
    planned_start = req_date(body, "planned_start_on")
    planned_end = req_date(body, "planned_end_on")
    if site is None:
        from errors import invalid_request
        invalid_request("field 'site_id' is required")
    mob = new_entity(store)
    mob.update({
        "site_id": site["id"],
        "vendor_type": vendor_type,
        "vendor_name": vendor_name,
        "planned_start_on": planned_start.isoformat(),
        "planned_end_on": planned_end.isoformat(),
        "actual_start_on": None,
        "actual_end_on": None,
        "status": "PLANNED",
    })
    store.mobilizations[mob["id"]] = mob
    return ok(serialize(mob), status=201)


@bp.route("/rollout/vendor-mobilizations", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def list_mobilizations():
    return list_response(store.mobilizations, [
        ("site_id", "site_id", "str"),
        ("vendor_type", "vendor_type", "str"),
        ("status", "status", "str"),
    ])


@bp.route("/rollout/vendor-mobilizations/<mobilizationId>", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def get_mobilization(mobilizationId):
    return ok(serialize(get_or_404(store.mobilizations, mobilizationId, "mobilization")))


@bp.route("/rollout/vendor-mobilizations/<mobilizationId>/schedule", methods=["POST"], strict_slashes=False)
@authed(["SiteSuperintendent"])
def schedule_mobilization(mobilizationId):
    mob = get_or_404(store.mobilizations, mobilizationId, "mobilization")
    require_state(mob, ("PLANNED",), TERMINAL)
    site = store.sites.get(mob["site_id"])

    # Step 5 — site must be in its build window.
    if site is None or site["status"] not in ("IN_BUILD", "PUNCH"):
        raise ApiError("ERR_SITE_NOT_IN_BUILD", 409,
                       "site is not in IN_BUILD or PUNCH")

    # Step 8 — predecessor chain: IT needs COMPLETE FIXTURE, SIGNAGE needs
    # COMPLETE IT, FIXTURE needs none.
    pred = PREDECESSOR[mob["vendor_type"]]
    if pred is not None:
        satisfied = any(
            m["site_id"] == site["id"] and m["vendor_type"] == pred
            and m["status"] == "COMPLETE"
            for m in store.mobilizations.values()
        )
        if not satisfied:
            raise ApiError("ERR_VENDOR_PREDECESSOR_INCOMPLETE", 409,
                           "%s requires a COMPLETE %s mobilization"
                           % (mob["vendor_type"], pred))

    # Step 9 — window feasibility, then half-open overlap.
    start = parse_date(mob["planned_start_on"])
    end = parse_date(mob["planned_end_on"])
    today = clock.today()
    if start >= end or end <= today:
        raise ApiError("ERR_SCHEDULE_INFEASIBLE", 422,
                       "window start >= end or window fully past")
    for other in store.mobilizations.values():
        if other["id"] == mob["id"] or other["site_id"] != site["id"]:
            continue
        if other["status"] not in BLOCKING_STATUSES:
            continue
        o_start = parse_date(other["planned_start_on"])
        o_end = parse_date(other["planned_end_on"])
        if start < o_end and o_start < end:  # half-open intersection
            raise ApiError("ERR_VENDOR_WINDOW_OVERLAP", 409,
                           "window overlaps another non-terminal mobilization")

    # Step 10 — market crew-day capacity: every day may land exactly at
    # capacity but never above it.
    market = store.markets.get(site["market_id"])
    if market is not None:
        cap = market["max_concurrent_vendor_crews"]
        market_site_ids = {s["id"] for s in store.sites.values()
                           if s["market_id"] == market["id"]}
        occupants = [
            m for m in store.mobilizations.values()
            if m["id"] != mob["id"]
            and m["site_id"] in market_site_ids
            and m["status"] in ("SCHEDULED", "ON_SITE")
        ]
        day = start
        while day < end:
            concurrent = sum(
                1 for m in occupants
                if parse_date(m["planned_start_on"]) <= day < parse_date(m["planned_end_on"])
            )
            if concurrent + 1 > cap:
                raise ApiError("ERR_MARKET_CAPACITY_FULL", 409,
                               "market crew-day capacity exceeded on %s" % day)
            day += timedelta(days=1)

    mob["status"] = "SCHEDULED"
    bump(mob)
    return ok(serialize(mob))


@bp.route("/rollout/vendor-mobilizations/<mobilizationId>/arrive", methods=["POST"], strict_slashes=False)
@authed(["SiteSuperintendent"])
def arrive_mobilization(mobilizationId):
    mob = get_or_404(store.mobilizations, mobilizationId, "mobilization")
    require_state(mob, ("SCHEDULED",), TERMINAL)
    today = clock.today()
    if today < parse_date(mob["planned_start_on"]):
        raise ApiError("ERR_SCHEDULE_INFEASIBLE", 422,
                       "arrival before planned_start_on")
    mob["status"] = "ON_SITE"
    mob["actual_start_on"] = today.isoformat()
    bump(mob)
    return ok(serialize(mob))


@bp.route("/rollout/vendor-mobilizations/<mobilizationId>/complete", methods=["POST"], strict_slashes=False)
@authed(["SiteSuperintendent"])
def complete_mobilization(mobilizationId):
    mob = get_or_404(store.mobilizations, mobilizationId, "mobilization")
    require_state(mob, ("ON_SITE",), TERMINAL)
    today = clock.today()
    mob["status"] = "COMPLETE"
    mob["actual_end_on"] = today.isoformat()
    bump(mob)

    site = store.sites.get(mob["site_id"])
    if site is not None:
        recompute_readiness(site)
        mobs = [m for m in store.mobilizations.values() if m["site_id"] == site["id"]]
        done = {m["vendor_type"] for m in mobs if m["status"] == "COMPLETE"}
        if all(t in done for t in VENDOR_TYPES) and site["status"] == "IN_BUILD":
            site["status"] = "PUNCH"  # automatic advance (§3.5)
            site["readiness_posture"] = "SIGNAGE_HUNG"
            bump(site)
        recompute_commitment_for_site(site)  # vendor completion trigger
    return ok(serialize(mob))


@bp.route("/rollout/vendor-mobilizations/<mobilizationId>/cancel", methods=["POST"], strict_slashes=False)
@authed(["SiteSuperintendent"])
def cancel_mobilization(mobilizationId):
    mob = get_or_404(store.mobilizations, mobilizationId, "mobilization")
    require_state(mob, ("PLANNED", "SCHEDULED"), TERMINAL)
    mob["status"] = "CANCELLED"  # crew-day usage released (derived from status)
    bump(mob)
    return ok(serialize(mob))
