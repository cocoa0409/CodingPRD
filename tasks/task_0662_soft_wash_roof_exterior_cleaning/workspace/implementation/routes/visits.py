from datetime import timedelta

from flask import Blueprint, request

from db import db, common_create_fields, append_only_fields, touch
from errors import ApiError
from middleware import get_identity, require_role
from response import success, list_response
from services import serialize
from services import calc
from services.common import (
    get_body, require_fields, as_int, as_enum, parse_iso, parse_date,
    get_property, get_quote, get_visit,
    get_pagination, paginate, sorted_by_creation,
)
from services.domain import (
    recompute_outstanding_balance, release_visit_assignments,
    backing_quote_for_visit,
)

bp = Blueprint("visits", __name__)

PHASE_VALUES = {"BEFORE", "AFTER"}


def _owning_customer(visit):
    prop = db.properties.get(visit["property_id"])
    if prop is None:
        return None
    return db.customers.get(prop["customer_id"])


# --------------------------------------------------------------------------
@bp.post("/visits")
def create_visit():
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    body = get_body()
    require_fields(body, ["property_id", "quote_id", "scheduled_date"])
    prop = get_property(body["property_id"])
    quote = get_quote(body["quote_id"])
    scheduled_date = parse_date(body["scheduled_date"], "scheduled_date")
    duration = 120
    if "duration_minutes" in body and body["duration_minutes"] is not None:
        duration = as_int(body["duration_minutes"], "duration_minutes", minimum=1)

    # SUSPENDED customer blocks new visit creation (§3.1).
    customer = db.customers.get(prop["customer_id"])
    if customer is not None and customer["status"] == "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "Customer is SUSPENDED")

    # Backing quote must be ACCEPTED (§3.5).
    if quote["status"] != "ACCEPTED":
        raise ApiError("ERR_QUOTE_NOT_ACCEPTED", "Backing quote is not ACCEPTED")

    v = common_create_fields()
    v.update({
        "property_id": prop["id"],
        "quote_id": quote["id"],
        "plan_id": None,
        "route_id": prop["route_id"],
        "scheduled_date": body["scheduled_date"],
        "duration_minutes": duration,
        "provisional_cost_cents": None,
        "final_cost_cents": None,
        "reclean_of_visit_id": None,
        "billing_status": "UNBILLED",
        "status": "REQUESTED",
    })
    db.visits[v["id"]] = v
    return success(serialize.visit_view(v), 201)


@bp.get("/visits")
def list_visits():
    user_id, role = get_identity()
    require_role(role, {"Dispatcher", "Customer", "FieldTech"})
    property_id = request.args.get("property_id")
    quote_id = request.args.get("quote_id")
    plan_id = request.args.get("plan_id")
    route_id = request.args.get("route_id")
    reclean_of = request.args.get("reclean_of_visit_id")
    status = request.args.get("status")
    limit, offset = get_pagination()

    items = []
    for v in db.visits.values():
        if property_id is not None and v["property_id"] != property_id:
            continue
        if quote_id is not None and v["quote_id"] != quote_id:
            continue
        if plan_id is not None and v["plan_id"] != plan_id:
            continue
        if route_id is not None and v["route_id"] != route_id:
            continue
        if reclean_of is not None and v["reclean_of_visit_id"] != reclean_of:
            continue
        if status is not None and v["status"] != status:
            continue
        if role == "Customer":
            cust = _owning_customer(v)
            if cust is None or cust["id"] != user_id:
                continue
        if role == "FieldTech":
            # A FieldTech sees visits they are assigned to.
            tech_visit_ids = {a["visit_id"] for a in db.crew_assignments.values()
                              if a["technician_id"] == user_id}
            if v["id"] not in tech_visit_ids:
                continue
        items.append(v)
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize.visit_view(v) for v in page], limit, offset, total)


@bp.get("/visits/<vid>")
def get_one_visit(vid):
    user_id, role = get_identity()
    require_role(role, {"Dispatcher", "Customer", "FieldTech"})
    v = get_visit(vid)
    if role == "Customer":
        cust = _owning_customer(v)
        if cust is None or cust["id"] != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning customer")
    if role == "FieldTech":
        assigned = any(a["visit_id"] == vid and a["technician_id"] == user_id
                       for a in db.crew_assignments.values())
        if not assigned:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "FieldTech not assigned to this visit")
    return success(serialize.visit_view(v), 200)


# --------------------------------------------------------------------------
@bp.post("/visits/<vid>/schedule")
def schedule_visit(vid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    v = get_visit(vid)
    body = get_body()
    require_fields(body, ["expected_visit_version"])
    expected = as_int(body["expected_visit_version"], "expected_visit_version", minimum=0)

    # State (priority 6) before OCC / business (later).
    if v["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED visit can be scheduled")
    # OCC on Visit.version.
    if expected != v["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_visit_version is stale")

    # Weather gate: a CLEAR window on the route covering scheduled_date.
    sched_day = parse_date(v["scheduled_date"], "scheduled_date")
    if not _has_clear_window(v["route_id"], sched_day):
        raise ApiError("ERR_NO_CLEAR_WEATHER", "No CLEAR weather window covers the scheduled date")

    # Provisional cost from the backing quote's frozen total_cents.
    quote = backing_quote_for_visit(v)
    provisional = quote["total_cents"] if quote and quote["total_cents"] is not None else 0

    # Credit gate.
    cust = _owning_customer(v)
    if cust is not None:
        if cust["outstanding_balance_cents"] + provisional > cust["credit_limit_cents"]:
            raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", "Credit limit would be exceeded")

    v["status"] = "SCHEDULED"
    v["provisional_cost_cents"] = provisional
    touch(v)  # increments Visit.version by 1
    return success(serialize.visit_view(v), 200)


def _has_clear_window(route_id, day):
    """A CLEAR window on route whose closed interval covers the calendar day.

    The scheduled_date is a UTC calendar day; the window's closed interval
    [start,end] must intersect that day (00:00:00 .. 23:59:59.999999 UTC).
    """
    day_start = day
    day_end = day + timedelta(days=1) - timedelta(microseconds=1)
    for w in db.weather_windows.values():
        if w["route_id"] != route_id or w["condition"] != "CLEAR":
            continue
        w_start = parse_iso(w["window_start_utc"], "window_start_utc")
        w_end = parse_iso(w["window_end_utc"], "window_end_utc")
        # closed-interval intersection with the day span
        if w_start <= day_end and day_start <= w_end:
            return True
    return False


@bp.post("/visits/<vid>/unschedule")
def unschedule_visit(vid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    v = get_visit(vid)
    if v["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED visit can be unscheduled")
    release_visit_assignments(v)
    v["status"] = "REQUESTED"
    v["provisional_cost_cents"] = None
    touch(v)
    return success(serialize.visit_view(v), 200)


@bp.post("/visits/<vid>/start")
def start_visit(vid):
    user_id, role = get_identity()
    require_role(role, {"FieldTech"})
    v = get_visit(vid)
    # Ownership (priority 4): FieldTech must be assigned to this visit.
    assigned = any(a["visit_id"] == vid and a["technician_id"] == user_id
                   for a in db.crew_assignments.values())
    if not assigned:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "FieldTech not assigned to this visit")
    if v["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED visit can be started")
    confirmed = any(a["visit_id"] == vid and a["status"] == "CONFIRMED"
                    for a in db.crew_assignments.values())
    if not confirmed:
        raise ApiError("ERR_NO_CONFIRMED_CREW", "No CONFIRMED crew assignment")
    has_before = any(p["visit_id"] == vid and p["phase"] == "BEFORE"
                     for p in db.photo_sets.values())
    if not has_before:
        raise ApiError("ERR_BEFORE_PHOTO_MISSING", "No BEFORE photo set")
    v["status"] = "IN_PROGRESS"
    touch(v)
    return success(serialize.visit_view(v), 200)


@bp.post("/visits/<vid>/complete")
def complete_visit(vid):
    user_id, role = get_identity()
    require_role(role, {"FieldTech"})
    v = get_visit(vid)
    assigned = any(a["visit_id"] == vid and a["technician_id"] == user_id
                   for a in db.crew_assignments.values())
    if not assigned:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "FieldTech not assigned to this visit")
    body = get_body()
    require_fields(body, ["re_measured_roof_sqft", "re_measured_siding_sqft", "re_measured_concrete_sqft"])
    roof = as_int(body["re_measured_roof_sqft"], "re_measured_roof_sqft", minimum=0)
    siding = as_int(body["re_measured_siding_sqft"], "re_measured_siding_sqft", minimum=0)
    concrete = as_int(body["re_measured_concrete_sqft"], "re_measured_concrete_sqft", minimum=0)

    if v["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_PROGRESS visit can be completed")
    has_after = any(p["visit_id"] == vid and p["phase"] == "AFTER"
                    for p in db.photo_sets.values())
    if not has_after:
        raise ApiError("ERR_AFTER_PHOTO_MISSING", "No AFTER photo set")

    # Final cost.
    if v["reclean_of_visit_id"] is not None:
        final_cost = 0
    else:
        final_cost = _compute_final_cost(v, {"ROOF": roof, "SIDING": siding, "CONCRETE": concrete})
    v["final_cost_cents"] = final_cost
    v["status"] = "COMPLETED"

    # Plan: advance next_due_utc by cadence_days; visits_generated_count unchanged.
    if v["plan_id"] is not None:
        plan = db.recurring_plans.get(v["plan_id"])
        if plan is not None:
            plan["next_due_utc"] = _advance_iso(plan["next_due_utc"], plan["cadence_days"])
            touch(plan)

    touch(v)

    # Auto-issue invoice (§3.8).
    _auto_issue_invoice(v)

    return success(serialize.visit_view(v), 200)


def _compute_final_cost(visit, remeasured):
    quote = backing_quote_for_visit(visit)
    prop = db.properties.get(visit["property_id"])
    stories = prop["stories"]
    items = [li for li in db.quote_line_items.values()
             if quote is not None and li["quote_id"] == quote["id"]]
    items = sorted_by_creation(items)
    subtotal = 0
    for li in items:
        actual_sqft = remeasured.get(li["surface_type"], 0)
        subtotal += calc.line_total_cents(actual_sqft, li["surface_type"], li["service_type"], stories)
    final = subtotal + calc.travel_surcharge_cents(subtotal)
    return final


def _advance_iso(iso_str, days):
    dt = parse_iso(iso_str, "next_due_utc")
    dt = dt + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _auto_issue_invoice(visit):
    prop = db.properties.get(visit["property_id"])
    customer = db.customers.get(prop["customer_id"])
    # Loyalty count from plan tenure.
    n = 0
    if visit["plan_id"] is not None:
        plan = db.recurring_plans.get(visit["plan_id"])
        if plan is not None:
            n = plan["visits_generated_count"]
    final_cost = visit["final_cost_cents"]
    discount = calc.loyalty_discount_cents(final_cost, n)
    amount_due = max(0, final_cost - discount)

    inv = common_create_fields()
    inv.update({
        "visit_id": visit["id"],
        "customer_id": customer["id"],
        "amount_due_cents": amount_due,
        "loyalty_discount_cents": discount,
        "status": "ISSUED",
    })
    db.invoices[inv["id"]] = inv

    visit["billing_status"] = "BILLED"
    touch(visit)
    recompute_outstanding_balance(customer)
    return inv


@bp.post("/visits/<vid>/cancel")
def cancel_visit(vid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    v = get_visit(vid)
    if v["status"] not in ("REQUESTED", "SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED/SCHEDULED visit can be cancelled")
    release_visit_assignments(v)
    v["status"] = "CANCELLED"
    touch(v)
    return success(serialize.visit_view(v), 200)


# --------------------------------------------------------------------------
@bp.post("/visits/<vid>/photos")
def upload_photo(vid):
    user_id, role = get_identity()
    require_role(role, {"FieldTech"})
    v = get_visit(vid)
    assigned = any(a["visit_id"] == vid and a["technician_id"] == user_id
                   for a in db.crew_assignments.values())
    if not assigned:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "FieldTech not assigned to this visit")
    body = get_body()
    require_fields(body, ["phase", "photo_url"])
    phase = as_enum(body["phase"], "phase", PHASE_VALUES)
    photo_url = body["photo_url"]
    if not isinstance(photo_url, str) or photo_url == "":
        raise ApiError("ERR_INVALID_REQUEST", "photo_url must be a non-empty string")
    p = append_only_fields()
    p.update({"visit_id": v["id"], "phase": phase, "photo_url": photo_url})
    db.photo_sets[p["id"]] = p
    return success(serialize.photo_set_view(p), 201)


@bp.get("/visits/<vid>/photos")
def list_photos(vid):
    user_id, role = get_identity()
    require_role(role, {"Dispatcher", "Customer", "FieldTech"})
    v = get_visit(vid)
    if role == "Customer":
        cust = _owning_customer(v)
        if cust is None or cust["id"] != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning customer")
    if role == "FieldTech":
        assigned = any(a["visit_id"] == vid and a["technician_id"] == user_id
                       for a in db.crew_assignments.values())
        if not assigned:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "FieldTech not assigned to this visit")
    phase = request.args.get("phase")
    limit, offset = get_pagination()
    items = [p for p in db.photo_sets.values()
             if p["visit_id"] == vid and (phase is None or p["phase"] == phase)]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize.photo_set_view(p) for p in page], limit, offset, total)
