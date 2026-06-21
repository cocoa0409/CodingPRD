"""Job routes: dispatch dimension + billing dimension (PRD §3.5, §3.6, §3.8)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import lookup
import serialize
import services.calc as calc
import util
from middleware import authenticate, require_role
from response import success

bp = Blueprint("jobs", __name__)

DISPATCH_STATUSES = {"UNSCHEDULED", "SCHEDULED", "EN_ROUTE", "ON_SITE",
                     "COMPLETED", "CLOSED", "CANCELLED"}
TRAVEL_BUFFER = timedelta(minutes=30)


def _job_window(j):
    """Return (start, end) tz-aware datetimes for a scheduled job, or (None, None)."""
    if not j.get("scheduled_start") or not j.get("scheduled_end"):
        return None, None
    return calc._parse_iso(j["scheduled_start"]), calc._parse_iso(j["scheduled_end"])


def _overlaps_half_open_buffered(s1, e1, s2, e2):
    """Half-open intervals with a 30-min travel buffer on each side of the
    existing booking; overlap when buffered intervals intersect (PRD §3.5)."""
    bs2 = s2 - TRAVEL_BUFFER
    be2 = e2 + TRAVEL_BUFFER
    # half-open intersection: max(start) < min(end)
    return max(s1, bs2) < min(e1, be2)


def _overlaps_closed(s1, e1, s2, e2):
    """Closed-interval overlap for equipment aggregate-capacity (PRD §3.5)."""
    return s1 <= e2 and s2 <= e1


@bp.route("/jobs/<id>", methods=["GET"])
def get_job(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Dispatcher", "Technician", "Customer"])
    j = lookup.job(id)
    return success(serialize.job(j))


@bp.route("/jobs", methods=["GET"])
def list_jobs():
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Dispatcher", "Technician"])
    limit, offset = util.parse_pagination()
    quote_id = request.args.get("quote_id")
    customer_id = request.args.get("customer_id")
    technician_id = request.args.get("technician_id")
    equipment_unit_id = request.args.get("equipment_unit_id")
    dispatch_status = request.args.get("dispatch_status")
    rows = []
    for j in db.jobs.values():
        if quote_id is not None and j["quote_id"] != quote_id:
            continue
        if customer_id is not None and j["customer_id"] != customer_id:
            continue
        if technician_id is not None and j["technician_id"] != technician_id:
            continue
        if equipment_unit_id is not None and j["equipment_unit_id"] != equipment_unit_id:
            continue
        if dispatch_status is not None and j["dispatch_status"] != dispatch_status:
            continue
        rows.append(j)
    page, pagination = util.paginate(rows, limit, offset)
    return success([serialize.job(j) for j in page], pagination=pagination)


# ----- Schedule -----
@bp.route("/jobs/<id>/schedule", methods=["POST"])
def schedule_job(id):
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    j = lookup.job(id)
    body = util.get_body()
    util.require_fields(body, ["technician_id", "scheduled_start", "scheduled_end"])
    technician_id = body.get("technician_id")
    if not isinstance(technician_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "technician_id must be a string")
    equipment_unit_id = body.get("equipment_unit_id")
    if equipment_unit_id is not None and not isinstance(equipment_unit_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "equipment_unit_id must be a string")
    is_emergency = util.optional_bool(body, "is_emergency", False)

    # Existence (PRD §2.7): body FKs
    tech = lookup.technician(technician_id)
    if equipment_unit_id is not None:
        lookup.equipment_unit(equipment_unit_id)

    # Body well-formedness: parse window
    start = util.parse_dt(body.get("scheduled_start"), "scheduled_start")
    end = util.parse_dt(body.get("scheduled_end"), "scheduled_end")

    # State: must be UNSCHEDULED
    if j["dispatch_status"] != "UNSCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Job must be UNSCHEDULED to schedule")

    quote = db.quotes[j["quote_id"]]

    # Business: technician eligibility (priority 9)
    if tech["status"] != "AVAILABLE":
        raise errors.err(errors.ERR_TECH_NOT_ELIGIBLE, "Technician not AVAILABLE")
    if quote["quote_type"] == "INSTALL" and not tech["certified_for_install"]:
        raise errors.err(errors.ERR_TECH_NOT_ELIGIBLE, "Technician not install-certified")

    # window validity (scheduled_start < scheduled_end, half-open)
    if not (start < end):
        raise errors.err(errors.ERR_INVALID_REQUEST, "scheduled_start must be before scheduled_end")

    # Business: technician schedule conflict (priority 10)
    for other in db.jobs.values():
        if other["id"] == j["id"]:
            continue
        if other["technician_id"] != technician_id:
            continue
        if other["dispatch_status"] == "CANCELLED":
            continue
        os, oe = _job_window(other)
        if os is None or oe is None:
            continue
        if _overlaps_half_open_buffered(start, end, os, oe):
            raise errors.err(errors.ERR_TECH_SCHEDULE_CONFLICT, "Technician schedule conflict")

    # Determine whether the door requires a lift
    requires_lift = False
    if quote["quote_type"] == "INSTALL" and quote["door_model_id"] is not None:
        door = db.door_models.get(quote["door_model_id"])
        if door is not None:
            requires_lift = door["requires_lift"]

    # Business: equipment availability (priority 11)
    if requires_lift:
        if equipment_unit_id is None:
            raise errors.err(errors.ERR_EQUIPMENT_UNAVAILABLE, "Lift required but no equipment supplied")
        unit = db.equipment_units[equipment_unit_id]
        overlapping = 0
        for other in db.jobs.values():
            if other["id"] == j["id"]:
                continue
            if other["equipment_unit_id"] != equipment_unit_id:
                continue
            if other["dispatch_status"] == "CANCELLED":
                continue
            os, oe = _job_window(other)
            if os is None or oe is None:
                continue
            if _overlaps_closed(start, end, os, oe):
                overlapping += 1
        if not (overlapping < unit["concurrent_capacity"]):
            raise errors.err(errors.ERR_EQUIPMENT_UNAVAILABLE, "Equipment unavailable")

    # Commit
    j["dispatch_status"] = "SCHEDULED"
    j["technician_id"] = technician_id
    j["scheduled_start"] = start.strftime("%Y-%m-%dT%H:%M:%S.") + f"{start.microsecond // 1000:03d}Z"
    j["scheduled_end"] = end.strftime("%Y-%m-%dT%H:%M:%S.") + f"{end.microsecond // 1000:03d}Z"
    j["is_emergency"] = is_emergency
    if requires_lift:
        j["equipment_unit_id"] = equipment_unit_id
    # increment technician booked_minutes by window length
    minutes = int(round((end - start).total_seconds() / 60))
    tech["booked_minutes"] += minutes
    db.touch(tech)
    db.touch(j)
    return success(serialize.job(j))


# ----- Depart / Arrive (on-site, assigned technician only) -----
def _assigned_tech_check(j, user_id):
    if j["technician_id"] != user_id:
        # Acting technician must be the assigned one (PRD §3.6).
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Not the assigned technician")


@bp.route("/jobs/<id>/depart", methods=["POST"])
def depart_job(id):
    user_id, role = authenticate()
    require_role(role, ["Technician"])
    j = lookup.job(id)
    if j["dispatch_status"] != "SCHEDULED":
        if j["technician_id"] != user_id:
            raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Not the assigned technician")
        raise errors.err(errors.ERR_INVALID_STATE, "Job must be SCHEDULED to depart")
    _assigned_tech_check(j, user_id)
    j["dispatch_status"] = "EN_ROUTE"
    db.touch(j)
    return success(serialize.job(j))


@bp.route("/jobs/<id>/arrive", methods=["POST"])
def arrive_job(id):
    user_id, role = authenticate()
    require_role(role, ["Technician"])
    j = lookup.job(id)
    if j["dispatch_status"] != "EN_ROUTE":
        if j["technician_id"] != user_id:
            raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Not the assigned technician")
        raise errors.err(errors.ERR_INVALID_STATE, "Job must be EN_ROUTE to arrive")
    _assigned_tech_check(j, user_id)
    j["dispatch_status"] = "ON_SITE"
    db.touch(j)
    return success(serialize.job(j))


@bp.route("/jobs/<id>/safety-check", methods=["POST"])
def safety_check(id):
    user_id, role = authenticate()
    require_role(role, ["Technician"])
    j = lookup.job(id)
    _assigned_tech_check(j, user_id)
    j["safety_inspection_passed"] = True
    db.touch(j)
    return success(serialize.job(j))


# ----- Complete -----
@bp.route("/jobs/<id>/complete", methods=["POST"])
def complete_job(id):
    user_id, role = authenticate()
    require_role(role, ["Technician"])
    j = lookup.job(id)
    if j["dispatch_status"] != "ON_SITE":
        if j["technician_id"] != user_id:
            raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Not the assigned technician")
        raise errors.err(errors.ERR_INVALID_STATE, "Job must be ON_SITE to complete")
    _assigned_tech_check(j, user_id)
    # business_safety (priority 7)
    if not j["safety_inspection_passed"]:
        raise errors.err(errors.ERR_SAFETY_NOT_PASSED, "Safety inspection not passed")
    # business_referential (priority 8): no reservation still HELD
    for r in db.part_reservations.values():
        if r["job_id"] == j["id"] and r["status"] == "HELD":
            raise errors.err(errors.ERR_PARTS_NOT_CONSUMED, "Parts not consumed")
    j["dispatch_status"] = "COMPLETED"
    j["completed_by_user_id"] = user_id
    final, surcharge = calc.job_final_total(j)
    j["final_total_cents"] = final
    j["emergency_surcharge_cents"] = surcharge
    # tech counters/rates derive live via serialize; bump tech version for visibility
    tech = db.technicians.get(j["technician_id"])
    if tech is not None:
        db.touch(tech)
    db.touch(j)
    return success(serialize.job(j))


# ----- Invoice / Pay / Close (billing dimension) -----
@bp.route("/jobs/<id>/invoice", methods=["POST"])
def invoice_job(id):
    user_id, role = authenticate()
    require_role(role, ["ServiceManager"])
    j = lookup.job(id)
    if j["billing_status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Billing must be PENDING to invoice")
    # cross-dimension guard: dispatch must be COMPLETED
    if j["dispatch_status"] != "COMPLETED":
        raise errors.err(errors.ERR_INVALID_STATE, "Job must be COMPLETED to invoice")
    # segregation of duties (priority 16)
    if user_id == j["completed_by_user_id"]:
        raise errors.err(errors.ERR_SEGREGATION_VIOLATION, "Invoicer must differ from completer")
    j["billing_status"] = "INVOICED"
    db.touch(j)
    return success(serialize.job(j))


@bp.route("/jobs/<id>/pay", methods=["POST"])
def pay_job(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    j = lookup.job(id)
    if j["billing_status"] != "INVOICED":
        raise errors.err(errors.ERR_INVALID_STATE, "Billing must be INVOICED to pay")
    j["billing_status"] = "PAID"
    db.touch(j)
    return success(serialize.job(j))


@bp.route("/jobs/<id>/close", methods=["POST"])
def close_job(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    j = lookup.job(id)
    if j["dispatch_status"] != "COMPLETED":
        raise errors.err(errors.ERR_INVALID_STATE, "Job must be COMPLETED to close")
    if j["billing_status"] != "PAID":
        raise errors.err(errors.ERR_INVALID_STATE, "Job must be PAID to close")
    j["dispatch_status"] = "CLOSED"
    # cascade: activate a PENDING WarrantyPlan for this job
    for w in db.warranty_plans.values():
        if w["job_id"] == j["id"] and w["status"] == "PENDING":
            w["status"] = "ACTIVE"
            db.touch(w)
            cust = db.customers.get(w["customer_id"])
            if cust is not None:
                db.touch(cust)  # active_warranty_count derives live
    db.touch(j)
    return success(serialize.job(j))


# ----- Cancel -----
@bp.route("/jobs/<id>/cancel", methods=["POST"])
def cancel_job(id):
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    j = lookup.job(id)
    if j["dispatch_status"] in ("ON_SITE", "COMPLETED", "CLOSED", "CANCELLED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Job cannot be cancelled from this state")
    # compensating effects
    for r in db.part_reservations.values():
        if r["job_id"] == j["id"] and r["status"] == "HELD":
            r["status"] = "RELEASED"
            db.touch(r)
            part = db.parts.get(r["part_id"])
            if part is not None:
                db.touch(part)  # reserved_qty/available_qty derive live
    if j["technician_id"] is not None:
        tech = db.technicians.get(j["technician_id"])
        ws, we = _job_window(j)
        if tech is not None and ws is not None and we is not None:
            minutes = int(round((we - ws).total_seconds() / 60))
            tech["booked_minutes"] -= minutes
            db.touch(tech)
    j["dispatch_status"] = "CANCELLED"
    db.touch(j)
    return success(serialize.job(j))
