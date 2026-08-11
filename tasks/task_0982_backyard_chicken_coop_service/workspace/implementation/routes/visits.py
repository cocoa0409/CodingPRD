"""ServiceVisit endpoints (PRD §3.5)."""
from flask import Blueprint, request

from db import new_id, now, serialize, stamp_new, store, touch
from errors import fail
from middleware import (
    ALL_ROLES,
    authenticate,
    body,
    require_owner,
    require_role,
    require_tech,
)
from response import list_response, ok
from services.cascade import cancel_visit_cascade, release_reservation
from services.pricing import (
    resolve_coverage,
    technician_schedule_conflict,
    visit_final_price,
    visit_provisional_price,
)
from util import is_int, parse_dt, req_dt, req_enum, req_str

bp = Blueprint("visits", __name__)

VISIT_TYPES = {"COOP_CLEANING", "FLOCK_HEALTH_CHECK", "PREDATOR_PROOFING", "SETUP_INSTALL"}
CUSTOMER_OR_ADMIN = {"Customer", "PlatformAdmin"}
GRADE_UP = {"NONE": "B", "B": "A", "A": "A"}


def get_visit(vid):
    v = store.visits.get(vid)
    if v is None:
        fail("ERR_VISIT_NOT_FOUND", f"Service visit {vid} does not exist")
    return v


@bp.route("/coopcare/service-visits", methods=["POST"])
def create_visit():
    uid, role = authenticate()
    require_role(role, CUSTOMER_OR_ADMIN)
    data = body()
    household_id = data.get("household_id")
    coop_site_id = data.get("coop_site_id")
    require_owner(uid, role, household_id if isinstance(household_id, str) else None)
    if not isinstance(household_id, str) or not household_id.strip():
        fail("ERR_INVALID_REQUEST", "household_id is required")
    if not isinstance(coop_site_id, str) or not coop_site_id.strip():
        fail("ERR_INVALID_REQUEST", "coop_site_id is required")
    h = store.households.get(household_id)
    if h is None:
        fail("ERR_HOUSEHOLD_NOT_FOUND", f"Household {household_id} does not exist")
    c = store.coops.get(coop_site_id)
    if c is None or c["household_id"] != household_id:
        # A coop outside the referenced household does not exist in this scope.
        fail("ERR_COOP_SITE_NOT_FOUND", f"Coop site {coop_site_id} does not exist for this household")
    visit_type = req_enum(data, "visit_type", VISIT_TYPES)
    scheduled_start = req_dt(data, "scheduled_start")
    scheduled_end = req_dt(data, "scheduled_end")
    if scheduled_end <= scheduled_start:
        fail("ERR_INVALID_TIME_RANGE", "scheduled_end must be strictly after scheduled_start")
    if h["status"] != "ACTIVE":
        fail("ERR_ACCOUNT_SUSPENDED", "visit booking requires household status ACTIVE")
    if visit_type == "SETUP_INSTALL":
        if c["status"] != "PLANNED":
            fail("ERR_COOP_ALREADY_INSTALLED", "SETUP_INSTALL requires a PLANNED coop")
    else:
        if c["status"] != "INSTALLED":
            fail("ERR_COOP_NOT_INSTALLED", "this visit type requires an INSTALLED coop")
    if scheduled_start < now():
        fail("ERR_SCHEDULE_IN_PAST", "scheduled_start is before the current logical clock time")
    coverage, sub = resolve_coverage(household_id, visit_type, scheduled_start)
    provisional = visit_provisional_price(h, c, visit_type, scheduled_start)
    rec = stamp_new({
        "id": new_id(),
        "household_id": household_id,
        "coop_site_id": coop_site_id,
        "subscription_id": sub["id"] if sub else None,
        "visit_type": visit_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "coverage": coverage,
        "provisional_price_cents": provisional,
        "final_price_cents": None,
        "assigned_technician_id": None,
        "reschedule_count": 0,
        "status": "REQUESTED",
        "billed_invoice_id": None,
        "completed_at": None,
    })
    store.visits[rec["id"]] = rec
    if sub is not None:
        # Reservation: the used counter is incremented immediately.
        if visit_type == "COOP_CLEANING":
            sub["used_cleanings"] += 1
        elif visit_type == "FLOCK_HEALTH_CHECK":
            sub["used_health_checks"] += 1
        touch(sub)
    return ok(serialize(rec), 201)


@bp.route("/coopcare/service-visits", methods=["GET"])
def list_visits():
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    filters = []
    for key in ("household_id", "coop_site_id", "subscription_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters.append((key, v))
    return list_response(store.visits.values(), filters)


@bp.route("/coopcare/service-visits/<vid>", methods=["GET"])
def read_visit(vid):
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    return ok(serialize(get_visit(vid)), 200)


@bp.route("/coopcare/service-visits/<vid>/assign", methods=["POST"])
def assign(vid):
    uid, role = authenticate()
    require_role(role, {"Dispatcher"})
    v = get_visit(vid)
    data = body()
    technician_id = req_str(data, "technician_id")
    new_start = v["scheduled_start"]
    new_end = v["scheduled_end"]
    if data.get("scheduled_start") is not None:
        new_start = parse_dt(data.get("scheduled_start"))
        if new_start is None:
            fail("ERR_INVALID_REQUEST", "scheduled_start must be an ISO 8601 datetime")
    if data.get("scheduled_end") is not None:
        new_end = parse_dt(data.get("scheduled_end"))
        if new_end is None:
            fail("ERR_INVALID_REQUEST", "scheduled_end must be an ISO 8601 datetime")
    if new_end <= new_start:
        fail("ERR_INVALID_TIME_RANGE", "scheduled_end must be strictly after scheduled_start")
    if v["status"] not in ("REQUESTED", "RESCHEDULE_REQUESTED"):
        fail("ERR_VISIT_NOT_ASSIGNABLE", "assign requires status REQUESTED or RESCHEDULE_REQUESTED")
    if technician_schedule_conflict(technician_id, new_start, new_end, exclude_visit_id=v["id"]):
        fail("ERR_TECH_SCHEDULE_CONFLICT", "buffered window collides with another visit of this technician")
    v["assigned_technician_id"] = technician_id
    v["scheduled_start"] = new_start
    v["scheduled_end"] = new_end
    v["status"] = "SCHEDULED"
    touch(v)
    return ok(serialize(v), 200)


@bp.route("/coopcare/service-visits/<vid>/request-reschedule", methods=["POST"])
def request_reschedule(vid):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    v = get_visit(vid)
    require_owner(uid, role, v["household_id"])
    if v["status"] != "SCHEDULED":
        fail("ERR_VISIT_NOT_SCHEDULED", "request-reschedule requires status SCHEDULED")
    if v["reschedule_count"] >= 2:
        fail("ERR_RESCHEDULE_LIMIT_REACHED", "this visit has already been rescheduled twice")
    v["reschedule_count"] += 1
    v["status"] = "RESCHEDULE_REQUESTED"
    touch(v)
    return ok(serialize(v), 200)


@bp.route("/coopcare/service-visits/<vid>/check-in", methods=["POST"])
def check_in(vid):
    uid, role = authenticate()
    require_role(role, {"ServiceTech"})
    v = get_visit(vid)
    require_tech(uid, v["assigned_technician_id"])
    if v["status"] != "SCHEDULED":
        fail("ERR_VISIT_NOT_SCHEDULED", "check-in requires status SCHEDULED")
    h = store.households[v["household_id"]]
    if h["status"] != "ACTIVE":
        fail("ERR_ACCOUNT_SUSPENDED", "check-in requires household status ACTIVE")
    v["status"] = "ON_SITE"
    touch(v)
    return ok(serialize(v), 200)


@bp.route("/coopcare/service-visits/<vid>/complete", methods=["POST"])
def complete(vid):
    uid, role = authenticate()
    require_role(role, {"ServiceTech"})
    v = get_visit(vid)
    require_tech(uid, v["assigned_technician_id"])
    data = body()
    observed = data.get("observed_flock_size")
    if not is_int(observed) or observed < 0:
        fail("ERR_INVALID_REQUEST", "observed_flock_size is required and must be an integer >= 0")
    duration = data.get("actual_duration_minutes")
    if not is_int(duration):
        fail("ERR_INVALID_REQUEST", "actual_duration_minutes is required and must be an integer")
    if duration <= 0:
        fail("ERR_INVALID_TIME_RANGE", "actual_duration_minutes must be positive")
    if v["status"] != "ON_SITE":
        fail("ERR_VISIT_NOT_ON_SITE", "complete requires status ON_SITE")
    h = store.households[v["household_id"]]
    v["completed_at"] = now()
    v["final_price_cents"] = visit_final_price(h, v, observed, duration)
    v["status"] = "COMPLETED"
    touch(v)
    # Coop lifecycle transitions driven by the completed visit.
    c = store.coops[v["coop_site_id"]]
    if v["visit_type"] == "SETUP_INSTALL":
        if c["status"] == "PLANNED":
            c["status"] = "INSTALLED"
            touch(c)
    elif v["visit_type"] == "PREDATOR_PROOFING":
        c["predator_grade"] = GRADE_UP[c["predator_grade"]]
        touch(c)
    # Linked PLACED orders are fulfilled by the completing visit.
    for o in store.orders.values():
        if o["fulfillment_visit_id"] == v["id"] and o["status"] == "PLACED":
            o["status"] = "FULFILLED"
            touch(o)
    return ok(serialize(v), 200)


@bp.route("/coopcare/service-visits/<vid>/mark-no-show", methods=["POST"])
def mark_no_show(vid):
    uid, role = authenticate()
    require_role(role, {"ServiceTech"})
    v = get_visit(vid)
    require_tech(uid, v["assigned_technician_id"])
    if v["status"] != "SCHEDULED":
        fail("ERR_VISIT_NOT_SCHEDULED", "mark-no-show requires status SCHEDULED")
    v["status"] = "NO_SHOW"
    touch(v)
    release_reservation(v)  # covered reservation released; no charge attaches
    return ok(serialize(v), 200)


@bp.route("/coopcare/service-visits/<vid>/cancel", methods=["POST"])
def cancel_visit(vid):
    uid, role = authenticate()
    require_role(role, {"Customer", "Dispatcher"})
    v = get_visit(vid)
    require_owner(uid, role, v["household_id"])
    if v["status"] not in ("REQUESTED", "SCHEDULED", "RESCHEDULE_REQUESTED"):
        fail("ERR_VISIT_NOT_CANCELLABLE", "cancel requires status REQUESTED, SCHEDULED or RESCHEDULE_REQUESTED")
    cancel_visit_cascade(v)
    return ok(serialize(v), 200)
