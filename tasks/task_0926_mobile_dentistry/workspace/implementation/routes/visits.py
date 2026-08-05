"""Site visit scheduling and the visit lifecycle."""

from flask import Blueprint

import calc
import cascades
import clock
import gates
import serializers
import store
import validation as v
from constants import VISIT_RESCHEDULE_MAX_COUNT, VISIT_RESCHEDULE_WINDOW_DAYS
from envelope import array_response, object_response
from errors import ApiError
from timefmt import timedelta

bp = Blueprint("visits", __name__)


def _assigned_staff(visit_or_ids):
    return [
        store.get("staff_members", visit_or_ids.get("lead_staff_id")),
        store.get("staff_members", visit_or_ids.get("onsite_dentist_staff_id")),
        store.get("staff_members", visit_or_ids.get("remote_dentist_staff_id")),
    ]


def _unit_gates(unit):
    """Rungs 15 and 16 in order: the lazy incubation sweep, the quarantine gate,
    then the calibration gate."""
    cascades.maybe_sweep_incubation_timeout(unit)
    if unit["status"] == "QUARANTINED":
        raise ApiError("ERR_UNIT_QUARANTINED")
    _due_on, calibration_status = calc.calibration_projection(unit)
    if calibration_status == "EXPIRED":
        raise ApiError("ERR_UNIT_CALIBRATION_EXPIRED")


# --------------------------------------------------------------------------
# POST /mobile-dentistry/site-visits
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/site-visits", methods=["POST"])
def create_site_visit():
    v.authenticate(["ProgramAdmin", "SiteCoordinator"])
    body = v.body()
    site = v.fk_row(body, "site_id", "sites")
    period = v.fk_row(body, "program_period_id", "program_periods")
    unit = v.fk_row(body, "portable_unit_id", "portable_units")
    lead = v.fk_row(body, "lead_staff_id", "staff_members")
    onsite = v.fk_row(body, "onsite_dentist_staff_id", "staff_members")
    remote = v.fk_row(body, "remote_dentist_staff_id", "staff_members")

    for field in ("site_id", "program_period_id", "portable_unit_id", "lead_staff_id"):
        v.need(body, field)
        if not isinstance(body.get(field), str):
            raise ApiError("ERR_VALIDATION", "Field '%s' must be a string." % field)
    for field in ("onsite_dentist_staff_id", "remote_dentist_staff_id"):
        if body.get(field) is not None and not isinstance(body.get(field), str):
            raise ApiError("ERR_VALIDATION", "Field '%s' must be a string." % field)
    start = v.req_instant(body, "scheduled_start_at")
    end = v.req_instant(body, "scheduled_end_at")
    chair_count = v.opt_int(body, "chair_count", minimum=1, default=1)
    if not start < end:
        raise ApiError("ERR_VALIDATION", "scheduled_start_at must be strictly before scheduled_end_at.")

    gates.period_gate(period["id"])
    gates.site_hold_gate(site, start, end)
    _unit_gates(unit)

    staff_rows = [lead, onsite, remote]
    gates.credential_gate(staff_rows)
    gates.license_state_gate(staff_rows, site)

    if calc.unit_collision(unit["id"], start, end):
        raise ApiError("ERR_UNIT_DOUBLE_BOOKED")
    staff_ids = [s["id"] for s in staff_rows if s is not None]
    if calc.staff_collision(staff_ids, start, end):
        raise ApiError("ERR_STAFF_DOUBLE_BOOKED")

    row = store.insert("site_visits", {
        "site_id": site["id"],
        "program_period_id": period["id"],
        "portable_unit_id": unit["id"],
        "lead_staff_id": lead["id"],
        "onsite_dentist_staff_id": onsite["id"] if onsite else None,
        "remote_dentist_staff_id": remote["id"] if remote else None,
        "scheduled_start_at": start,
        "scheduled_end_at": end,
        "chair_count": chair_count,
        "capacity_chair_minutes": calc.capacity_chair_minutes(chair_count, start, end),
        "status": "SCHEDULED",
        "reschedule_count": 0,
        "started_at": None,
        "completed_at": None,
        "cancelled_at": None,
    })
    v.mark_minted(row)
    gates.mark_period_reports_stale(period["id"])
    return object_response(serializers.site_visit(row), 201)


@bp.route("/mobile-dentistry/site-visits", methods=["GET"])
def list_site_visits():
    v.authenticate([
        "ProgramAdmin", "SiteCoordinator", "FieldDentist",
        "FieldHygienist", "DentalAssistant", "BillingSpecialist",
    ])
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all_rows("site_visits"), {
        "site_id": "site_id",
        "program_period_id": "program_period_id",
        "portable_unit_id": "portable_unit_id",
        "lead_staff_id": "lead_staff_id",
        "onsite_dentist_staff_id": "onsite_dentist_staff_id",
        "remote_dentist_staff_id": "remote_dentist_staff_id",
        "status": "status",
    })
    page, total = v.paginate(rows, limit, offset)
    return array_response(serializers.many(serializers.site_visit, page), limit, offset, total)


@bp.route("/mobile-dentistry/site-visits/<visit_id>", methods=["GET"])
def read_site_visit(visit_id):
    v.authenticate([
        "ProgramAdmin", "SiteCoordinator", "FieldDentist",
        "FieldHygienist", "DentalAssistant", "BillingSpecialist",
    ])
    row = v.path_row("site_visits", visit_id)
    return object_response(serializers.site_visit(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/site-visits/{id}/reschedule
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/site-visits/<visit_id>/reschedule", methods=["POST"])
def reschedule_site_visit(visit_id):
    v.authenticate(["ProgramAdmin", "SiteCoordinator"])
    row = v.path_row("site_visits", visit_id)
    body = v.body()
    start = v.req_instant(body, "scheduled_start_at")
    end = v.req_instant(body, "scheduled_end_at")
    if not start < end:
        raise ApiError("ERR_VALIDATION", "scheduled_start_at must be strictly before scheduled_end_at.")

    gates.period_gate(row["program_period_id"])
    site = store.get("sites", row["site_id"])
    gates.site_hold_gate(site, start, end)

    if row["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    if row["reschedule_count"] >= VISIT_RESCHEDULE_MAX_COUNT:
        raise ApiError("ERR_INVALID_STATE")
    delta = start - row["scheduled_start_at"]
    if abs(delta) > timedelta(days=VISIT_RESCHEDULE_WINDOW_DAYS):
        raise ApiError("ERR_INVALID_STATE")

    if calc.unit_collision(row["portable_unit_id"], start, end, exclude_visit_id=row["id"]):
        raise ApiError("ERR_UNIT_DOUBLE_BOOKED")
    staff_ids = [
        row.get("lead_staff_id"),
        row.get("onsite_dentist_staff_id"),
        row.get("remote_dentist_staff_id"),
    ]
    if calc.staff_collision(staff_ids, start, end, exclude_visit_id=row["id"]):
        raise ApiError("ERR_STAFF_DOUBLE_BOOKED")

    row["scheduled_start_at"] = start
    row["scheduled_end_at"] = end
    row["capacity_chair_minutes"] = calc.capacity_chair_minutes(row["chair_count"], start, end)
    row["reschedule_count"] += 1
    v.touch(row)
    gates.mark_period_reports_stale(row["program_period_id"])
    return object_response(serializers.site_visit(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/site-visits/{id}/start
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/site-visits/<visit_id>/start", methods=["POST"])
def start_site_visit(visit_id):
    v.authenticate(["FieldDentist", "FieldHygienist", "DentalAssistant"])
    row = v.path_row("site_visits", visit_id)

    gates.period_gate(row["program_period_id"])
    site = store.get("sites", row["site_id"])
    gates.site_hold_gate(site, row["scheduled_start_at"], row["scheduled_end_at"])

    unit = store.get("portable_units", row["portable_unit_id"])
    if row["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    # A unit already IN_SERVICE has no declared AVAILABLE -> IN_SERVICE leg; a
    # QUARANTINED unit is answered one rung lower, by the quarantine gate.
    if unit["status"] == "IN_SERVICE":
        raise ApiError("ERR_INVALID_STATE")

    _unit_gates(unit)

    # Rung 17 clause (a) -- no load on this unit may still be incubating.
    for load in store.all_rows("sterilization_loads"):
        if load["portable_unit_id"] != unit["id"]:
            continue
        if load["spore_result"] == "PENDING" and clock.now() < load["incubation_ends_at"]:
            raise ApiError("ERR_SPORE_RESULT_PENDING")

    staff_rows = _assigned_staff(row)
    gates.credential_gate(staff_rows)
    gates.license_state_gate(staff_rows, site)

    row["status"] = "IN_PROGRESS"
    row["started_at"] = clock.now()
    v.touch(row)
    unit["status"] = "IN_SERVICE"
    v.touch(unit)
    gates.mark_period_reports_stale(row["program_period_id"])
    return object_response(serializers.site_visit(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/site-visits/{id}/complete
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/site-visits/<visit_id>/complete", methods=["POST"])
def complete_site_visit(visit_id):
    v.authenticate(["FieldDentist", "FieldHygienist", "DentalAssistant"])
    row = v.path_row("site_visits", visit_id)

    gates.period_gate(row["program_period_id"])

    if row["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")
    encounters = calc.visit_encounters(row["id"])
    for encounter in encounters:
        for procedure in calc.encounter_procedures(encounter["id"]):
            if procedure["status"] == "PLANNED":
                raise ApiError("ERR_INVALID_STATE")

    row["status"] = "COMPLETED"
    row["completed_at"] = clock.now()
    v.touch(row)

    # The IN_SERVICE -> AVAILABLE leg is declared only out of IN_SERVICE; a unit
    # quarantined mid-visit stays quarantined.
    unit = store.get("portable_units", row["portable_unit_id"])
    if unit is not None and unit["status"] == "IN_SERVICE":
        unit["status"] = "AVAILABLE"
        v.touch(unit)

    for encounter in encounters:
        if encounter["clinical_status"] in ("EXAMINED", "TREATED"):
            encounter["clinical_status"] = "CLOSED"
            v.touch(encounter)
        elif encounter["clinical_status"] == "REGISTERED":
            encounter["clinical_status"] = "NO_SHOW"
            v.touch(encounter)

    gates.mark_period_reports_stale(row["program_period_id"])
    return object_response(serializers.site_visit(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/site-visits/{id}/cancel
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/site-visits/<visit_id>/cancel", methods=["POST"])
def cancel_site_visit(visit_id):
    v.authenticate(["ProgramAdmin", "SiteCoordinator"])
    row = v.path_row("site_visits", visit_id)
    body = v.body()
    v.opt_string(body, "cancel_reason")

    gates.period_gate(row["program_period_id"])

    if row["status"] not in ("SCHEDULED", "HOLD_BLOCKED"):
        raise ApiError("ERR_INVALID_STATE")

    from_scheduled = row["status"] == "SCHEDULED"
    row["status"] = "CANCELLED"
    row["cancelled_at"] = clock.now()
    v.touch(row)

    if from_scheduled:
        for encounter in calc.visit_encounters(row["id"]):
            if encounter["clinical_status"] == "REGISTERED":
                encounter["clinical_status"] = "NO_SHOW"
                v.touch(encounter)

    gates.mark_period_reports_stale(row["program_period_id"])
    return object_response(serializers.site_visit(row), 200)
