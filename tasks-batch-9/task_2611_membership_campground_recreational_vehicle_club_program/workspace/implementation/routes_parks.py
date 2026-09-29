"""Parks, seasons, amenity inspections, maintenance windows, affiliate agreements."""

from flask import Blueprint, request

import auth
import calc
import clock
import engine
import guards
import response
import serializers
import store
import validators as v
from auth import CLUB_ADMIN, MEMBER, PARK_MANAGER, COMPLIANCE_OFFICER, TRANSIENT_GUEST
from errors import fail

bp = Blueprint("parks", __name__)


# ---------------------------------------------------------------------------
# parks
# ---------------------------------------------------------------------------
@bp.post("/parks")
def create_park():
    auth.authorize(CLUB_ADMIN)
    data = v.body()
    agreement = guards.maybe("affiliate_agreements", v.raw_id(data, "affiliate_agreement_id"))
    name = v.req_str(data, "name")
    park_class = v.req_enum(data, "park_class", calc.PARK_CLASSES)
    total_sites = v.req_int(data, "total_sites", minimum=1, maximum=500)
    allocation = v.req_int(data, "member_allocation_pct", minimum=0, maximum=100)
    season_open = v.req_date(data, "season_open_date")
    season_close = v.req_date(data, "season_close_date")
    if season_close <= season_open:
        fail("ERR_INVALID_REQUEST", "season_close_date must be after season_open_date")

    member_pool = (total_sites * allocation) // 100
    row = store.base_row()
    row.update({
        "name": name,
        "park_class": park_class,
        "affiliate_agreement_id": agreement["id"] if agreement is not None else None,
        "network_type": "AFFILIATE" if agreement is not None else "CLUB_OWNED",
        "total_sites": total_sites,
        "member_allocation_pct": allocation,
        "member_pool_sites": member_pool,
        "transient_pool_sites": total_sites - member_pool,
        "season_open_date": clock.fmt_date(season_open),
        "season_close_date": clock.fmt_date(season_close),
        "park_status": "SEASONAL_CLOSED",
        "amenity_compliance_status": "COMPLIANT",
        "rating_score": 0.00,
        "funded_capital_cents_ytd": 0,
        "last_inspection_at": None,
    })
    store.insert("parks", row)
    return response.created(serializers.park(row))


@bp.get("/parks/<park_id>")
def read_park(park_id):
    auth.authorize(CLUB_ADMIN, MEMBER, PARK_MANAGER, COMPLIANCE_OFFICER, TRANSIENT_GUEST)
    park = guards.fetch("parks", park_id)
    return response.ok(serializers.park(park))


@bp.get("/parks")
def list_parks():
    auth.authorize(CLUB_ADMIN, MEMBER, PARK_MANAGER, COMPLIANCE_OFFICER)
    rows = store.ordered(store.all_rows("parks"))
    for field in ("park_class", "park_status", "affiliate_agreement_id",
                  "amenity_compliance_status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    return response.paginate(rows, serializers.park)


@bp.post("/parks/<park_id>/season-openings")
def open_season(park_id):
    actor = auth.authorize(PARK_MANAGER, CLUB_ADMIN)
    auth.require_park_manager(actor, park_id)
    park = guards.fetch("parks", park_id)
    if park["park_status"] != "SEASONAL_CLOSED":
        fail("ERR_INVALID_PARK_STATE", "park is not SEASONAL_CLOSED")
    today = clock.today()
    earliest = clock.add_days(engine.as_date(park["season_open_date"]),
                              -calc.SEASON_OPEN_LEAD_DAYS)
    if today < earliest or today > engine.as_date(park["season_close_date"]):
        fail("ERR_INVALID_PARK_STATE", "outside the permitted season-opening window")
    for window in engine.windows_of_park(park_id):
        if window["status"] == "ACTIVE":
            fail("ERR_INVALID_PARK_STATE", "an active maintenance window blocks opening")
    park["park_status"] = "OPEN"
    store.touch(park)
    return response.ok(serializers.park(park))


@bp.post("/parks/<park_id>/season-closures")
def close_season(park_id):
    actor = auth.authorize(PARK_MANAGER, CLUB_ADMIN)
    auth.require_park_manager(actor, park_id)
    park = guards.fetch("parks", park_id)
    if park["park_status"] != "OPEN":
        fail("ERR_INVALID_PARK_STATE", "park is not OPEN")
    reservations = store.ordered(engine.reservations_at_park(park_id))
    for res in reservations:
        if res["status"] in ("CHECKED_IN", "EXTENSION_REVIEW"):
            fail("ERR_INVALID_PARK_STATE",
                 "a stay is on site; the season cannot be closed")

    today = clock.today()
    cancelled_confirmed = 0
    for res in reservations:
        if res["status"] == "CONFIRMED" and engine.as_date(res["arrival_date"]) >= today:
            engine.force_cancel(res, "SEASON_CLOSURE")
            cancelled_confirmed += 1
        elif res["status"] == "WAITLISTED":
            engine.force_cancel(res, "SEASON_CLOSURE")

    park["park_status"] = "SEASONAL_CLOSED"
    engine.add_forced_cancellations(park, cancelled_confirmed)
    engine.rederive_compliance(park)
    engine.recompute_project_scores(park)
    store.touch(park)
    return response.ok(serializers.park(park))


# ---------------------------------------------------------------------------
# amenity inspections
# ---------------------------------------------------------------------------
@bp.post("/parks/<park_id>/amenity-inspections")
def file_inspection(park_id):
    actor = auth.authorize(PARK_MANAGER, COMPLIANCE_OFFICER)
    auth.require_park_manager(actor, park_id)
    park = guards.fetch("parks", park_id)
    data = v.body()
    restroom = v.req_int(data, "restroom_score", minimum=1, maximum=5)
    hookup = v.req_int(data, "hookup_score", minimum=1, maximum=5)
    utility = v.req_int(data, "utility_score", minimum=1, maximum=5)
    road = v.req_int(data, "road_score", minimum=1, maximum=5)
    if park["park_status"] not in ("OPEN", "MAINTENANCE_HOLD"):
        fail("ERR_INVALID_PARK_STATE", "park must be OPEN or MAINTENANCE_HOLD")

    composite = calc.amenity_composite_score(restroom, hookup, utility, road)
    stamp = clock.now_iso()
    row = store.base_row(versioned=False)
    row.update({
        "park_id": park_id,
        "inspected_at": stamp,
        "inspector_user_id": actor.user_id,
        "restroom_score": restroom,
        "hookup_score": hookup,
        "utility_score": utility,
        "road_score": road,
        "composite_score": float(composite),
        "result": calc.amenity_result(composite),
    })
    store.insert("amenity_inspections", row)

    park["last_inspection_at"] = stamp
    engine.rederive_compliance(park)
    engine.recompute_project_scores(park)
    store.touch(park)
    return response.created(serializers.inspection(row))


@bp.get("/parks/<park_id>/amenity-inspections")
def list_inspections(park_id):
    auth.authorize(CLUB_ADMIN, COMPLIANCE_OFFICER, PARK_MANAGER)
    guards.fetch("parks", park_id)
    rows = engine.inspections_of_park(park_id)
    rows.sort(key=lambda r: (r.get("inspected_at") or "", r.get("_seq") or 0),
              reverse=True)
    return response.paginate(rows, serializers.inspection)


@bp.get("/parks/<park_id>/satisfaction-surveys")
def list_park_surveys(park_id):
    auth.authorize(CLUB_ADMIN, COMPLIANCE_OFFICER, PARK_MANAGER)
    guards.fetch("parks", park_id)
    rows = store.ordered(engine.surveys_of_park(park_id))
    return response.paginate(rows, serializers.survey)


@bp.get("/parks/<park_id>/maintenance-windows")
def list_park_windows(park_id):
    auth.authorize(CLUB_ADMIN, PARK_MANAGER, COMPLIANCE_OFFICER)
    guards.fetch("parks", park_id)
    rows = store.ordered(engine.windows_of_park(park_id))
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return response.paginate(rows, serializers.maintenance_window)


@bp.get("/parks/<park_id>/capital-projects")
def list_park_projects(park_id):
    auth.authorize(CLUB_ADMIN, PARK_MANAGER)
    guards.fetch("parks", park_id)
    rows = store.ordered(engine.projects_of_park(park_id))
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    fiscal_year = request.args.get("fiscal_year")
    if fiscal_year:
        try:
            wanted = int(fiscal_year)
        except Exception:
            wanted = None
        rows = [r for r in rows if r["fiscal_year"] == wanted]
    return response.paginate(rows, serializers.capital_project)


# ---------------------------------------------------------------------------
# maintenance windows
# ---------------------------------------------------------------------------
@bp.post("/maintenance-windows")
def create_window():
    actor = auth.authorize(PARK_MANAGER)
    data = v.body()
    raw_park = v.raw_id(data, "park_id")
    auth.require_park_manager(actor, raw_park if raw_park else None)
    guards.maybe("parks", raw_park)
    park_id = v.req_id(data, "park_id")
    guards.fetch("parks", park_id)
    start = v.req_date(data, "start_date")
    end = v.req_date(data, "end_date")
    work_type = v.req_enum(data, "work_type", ("ROUTINE", "CAPITAL", "EMERGENCY"))
    if end < start:
        fail("ERR_INVALID_REQUEST", "end_date must not precede start_date")

    row = store.base_row()
    row.update({
        "park_id": park_id,
        "start_date": clock.fmt_date(start),
        "end_date": clock.fmt_date(end),
        "work_type": work_type,
        "status": "SCHEDULED",
        "cancelled_reservation_count": 0,
    })
    store.insert("maintenance_windows", row)
    return response.created(serializers.maintenance_window(row))


@bp.post("/maintenance-windows/<window_id>/activation")
def activate_window(window_id):
    actor = auth.authorize(PARK_MANAGER)
    candidate = guards.find("maintenance_windows", window_id)
    if candidate is not None:
        auth.require_park_manager(actor, candidate["park_id"])
    window = guards.fetch("maintenance_windows", window_id)
    if window["status"] != "SCHEDULED":
        fail("ERR_INVALID_MAINTENANCE_STATE", "window is not SCHEDULED")
    park = guards.fetch("parks", window["park_id"])
    if park["park_status"] != "OPEN":
        fail("ERR_INVALID_PARK_STATE", "park is not OPEN")

    window["status"] = "ACTIVE"
    park["park_status"] = "MAINTENANCE_HOLD"
    cancelled = 0
    for res in store.ordered(engine.reservations_at_park(park["id"])):
        if res["status"] not in ("CONFIRMED", "WAITLISTED"):
            continue
        if not engine.window_intersects(window, res):
            continue
        engine.force_cancel(res, "MAINTENANCE")
        cancelled += 1
    window["cancelled_reservation_count"] = cancelled
    store.touch(window)

    engine.add_forced_cancellations(park, cancelled)
    engine.rederive_compliance(park)
    engine.recompute_project_scores(park)
    store.touch(park)
    return response.ok(serializers.maintenance_window(window))


@bp.post("/maintenance-windows/<window_id>/completion")
def complete_window(window_id):
    actor = auth.authorize(PARK_MANAGER)
    candidate = guards.find("maintenance_windows", window_id)
    if candidate is not None:
        auth.require_park_manager(actor, candidate["park_id"])
    window = guards.fetch("maintenance_windows", window_id)
    if window["status"] != "ACTIVE":
        fail("ERR_INVALID_MAINTENANCE_STATE", "window is not ACTIVE")
    park = guards.fetch("parks", window["park_id"])
    if park["park_status"] != "MAINTENANCE_HOLD":
        fail("ERR_INVALID_PARK_STATE", "park is not in MAINTENANCE_HOLD")

    window["status"] = "COMPLETED"
    store.touch(window)
    park["park_status"] = "OPEN"
    store.touch(park)
    engine.waitlist_sweep(park["id"], min_arrival_after=window["end_date"])
    return response.ok(serializers.maintenance_window(window))


# ---------------------------------------------------------------------------
# affiliate agreements
# ---------------------------------------------------------------------------
_AGREEMENT_TRANSITIONS = {
    "DRAFT": ("ACTIVE",),
    "ACTIVE": ("SUSPENDED", "EXPIRED"),
    "SUSPENDED": ("ACTIVE",),
    "EXPIRED": (),
}


@bp.post("/affiliate-agreements")
def create_agreement():
    auth.authorize(CLUB_ADMIN)
    data = v.body()
    partner_name = v.req_str(data, "partner_name")
    effective_from = v.req_date(data, "effective_from")
    effective_to = v.req_date(data, "effective_to")
    quota = v.req_int(data, "annual_member_night_quota", minimum=1)
    ratio = v.req_number(data, "reciprocity_ratio", minimum=0.5, maximum=3.0)
    min_tier_rank = v.req_int(data, "min_tier_rank", minimum=1, maximum=5)
    advance_cap = v.req_int(data, "advance_window_cap_days", minimum=1, maximum=365)
    per_stay_cap = v.req_int(data, "per_stay_night_cap", minimum=1, maximum=45)
    rate = v.req_int(data, "settlement_rate_cents_per_night", minimum=0)
    if effective_to < effective_from:
        fail("ERR_INVALID_REQUEST", "effective_to must not precede effective_from")

    row = store.base_row()
    row.update({
        "partner_name": partner_name,
        "status": "DRAFT",
        "effective_from": clock.fmt_date(effective_from),
        "effective_to": clock.fmt_date(effective_to),
        "annual_member_night_quota": quota,
        "reciprocity_ratio": ratio,
        "min_tier_rank": min_tier_rank,
        "advance_window_cap_days": advance_cap,
        "per_stay_night_cap": per_stay_cap,
        "settlement_rate_cents_per_night": rate,
        "nights_consumed_ytd": 0,
        "settlement_owed_cents": 0,
    })
    store.insert("affiliate_agreements", row)
    return response.created(serializers.agreement(row))


@bp.get("/affiliate-agreements/<agreement_id>")
def read_agreement(agreement_id):
    auth.authorize(CLUB_ADMIN, COMPLIANCE_OFFICER)
    row = guards.fetch("affiliate_agreements", agreement_id)
    return response.ok(serializers.agreement(row))


@bp.post("/affiliate-agreements/<agreement_id>/status-changes")
def change_agreement_status(agreement_id):
    auth.authorize(CLUB_ADMIN)
    agreement = guards.fetch("affiliate_agreements", agreement_id)
    data = v.body()
    new_status = v.req_enum(data, "new_status",
                            ("DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED"))
    if new_status not in _AGREEMENT_TRANSITIONS[agreement["status"]]:
        fail("ERR_INVALID_AGREEMENT_STATE",
             "%s -> %s is not a declared transition" % (agreement["status"], new_status))
    agreement["status"] = new_status
    store.touch(agreement)
    return response.ok(serializers.agreement(agreement))
