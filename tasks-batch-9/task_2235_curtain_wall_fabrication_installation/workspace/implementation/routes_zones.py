"""Installation zones, embed surveys, crew days, hoist rigs and reservations."""

from datetime import timedelta

from flask import Blueprint

import calc
import domain
from common import created, get_or_404, listing, single
from errors import ApiError
from store import (
    apply,
    base_row,
    collection,
    db,
    fmt_dt,
    now,
    now_iso,
    parse_dt,
    sort_rows,
    touch,
)
from validate import (
    ANCHOR_TYPES,
    CREW_DAY_STATUSES,
    ELEVATIONS,
    F,
    FIELD_TEST_KINDS,
    FIELD_TEST_STATES,
    INSTALL_STATUSES,
    RESERVATION_STATUSES,
    RIG_KINDS,
    RIG_STATUSES,
    SURVEY_STATES,
    WEATHER_STATUSES,
    auth,
    body,
    check_window,
    q_enum,
    q_int,
    q_str,
    read_fields,
    require_user,
    user_id,
)

bp = Blueprint("zones", __name__)


# ==========================================================================
# InstallationZone
# ==========================================================================
ZONE_SPECS = (
    F("package_id", "string"),
    F("floor_number", "int", rng=lambda v: v >= 1),
    F("elevation_label", "enum", enum=ELEVATIONS),
    F("area_sqm", "num", rng=lambda v: v > 0),
    F("height_m", "num", rng=lambda v: v > 0),
    F("span_mm", "int", rng=lambda v: v >= 1),
    F("anchor_type", "enum", enum=ANCHOR_TYPES),
    F("designed_joint_mm", "num", rng=lambda v: v > 0),
    F("planned_panel_count", "int", rng=lambda v: v >= 1),
    F("budget_crew_hours", "num", rng=lambda v: v > 0),
)


@bp.post("/installation-zones")
def create_zone():
    auth("CWProjectManager")
    values = read_fields(body(), ZONE_SPECS)
    package = get_or_404(db.packages, values["package_id"], "ERR_PACKAGE_NOT_FOUND")
    row = base_row()
    row.update(
        {
            "package_id": package["id"],
            "floor_number": values["floor_number"],
            "elevation_label": values["elevation_label"],
            "area_sqm": values["area_sqm"],
            "height_m": values["height_m"],
            "span_mm": values["span_mm"],
            "anchor_type": values["anchor_type"],
            "designed_joint_mm": values["designed_joint_mm"],
            "planned_panel_count": values["planned_panel_count"],
            "budget_crew_hours": values["budget_crew_hours"],
            "install_status": "PLANNED",
            "weather_status": "NOT_TIGHT",
            "provisional_labor_cost_cents": None,
            "final_labor_cost_cents": None,
            "certified_line_cents": None,
            "weather_tight_at": None,
            "weather_tight_cycle_count": 0,
            "hang_completed_at": None,
            "certification_note": None,
        }
    )
    row.update(domain.zone_limit_fields(row, package))
    db.zones[row["id"]] = row
    return created(row, domain.ser_zone)


@bp.get("/installation-zones")
def list_zones():
    auth()
    floor = q_int("floor_number")
    rows = collection(
        db.zones,
        package_id=q_str("package_id"),
        install_status=q_enum("install_status", INSTALL_STATUSES),
        weather_status=q_enum("weather_status", WEATHER_STATUSES),
        floor_number=floor,
    )
    return listing(rows, domain.ser_zone)


@bp.get("/installation-zones/<zone_id>")
def read_zone(zone_id):
    auth()
    row = get_or_404(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    return single(row, domain.ser_zone)


@bp.post("/installation-zones/<zone_id>/set-anchors")
def set_anchors(zone_id):
    auth("FieldSuperintendent")
    zone = get_or_404(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    if zone["install_status"] != "PLANNED":
        raise ApiError("ERR_ZONE_SEQUENCE_VIOLATION")
    poured = [
        survey
        for survey in db.surveys.values()
        if survey["zone_id"] == zone["id"] and survey["state"] == "POURED"
    ]
    if not poured:
        raise ApiError("ERR_EMBED_SURVEY_NOT_ACCEPTED")
    package = domain.zone_package(zone)
    if package is not None and package["engineering_posture"] == "FROZEN":
        raise ApiError("ERR_ENGINEERING_POSTURE_FROZEN")

    apply(zone, {"install_status": "ANCHORS_SET"})
    if package is not None and package["state"] == "IN_FABRICATION":
        domain.sync_package(package, {"state": "IN_INSTALLATION"})
    return single(zone, domain.ser_zone)


@bp.post("/installation-zones/<zone_id>/hang-panels")
def hang_panels(zone_id):
    auth("FieldSuperintendent")
    zone = get_or_404(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    values = read_fields(body(), (F("hoist_reservation_id", "string"),))
    reservation = get_or_404(
        db.reservations, values["hoist_reservation_id"], "ERR_HOIST_NOT_FOUND"
    )
    if zone["install_status"] != "ANCHORS_SET":
        raise ApiError("ERR_ZONE_SEQUENCE_VIOLATION")
    package = domain.zone_package(zone)
    if package is not None and package["engineering_posture"] == "FROZEN":
        raise ApiError("ERR_ENGINEERING_POSTURE_FROZEN")
    if not domain.all_lots_shipped_for_zone(zone["id"]):
        raise ApiError("ERR_PANEL_LOTS_NOT_SHIPPED")

    window_start = parse_dt(reservation["window_start"])
    window_end = parse_dt(reservation["window_end"])
    instant = now()
    if (
        reservation["status"] != "RESERVED"
        or reservation["zone_id"] != zone["id"]
        or window_start is None
        or window_end is None
        or instant < window_start
        or instant >= window_end
    ):
        raise ApiError("ERR_HOIST_WINDOW_INVALID")

    provisional = None
    if package is not None:
        provisional = calc.provisional_labor_cost_cents(
            package["system_type"],
            zone["planned_panel_count"],
            package["planned_field_crew_size"],
            package["base_labor_rate_cents_per_hour"],
        )
    apply(
        zone,
        {
            "install_status": "PANELS_HUNG",
            "hang_completed_at": now_iso(),
            "provisional_labor_cost_cents": provisional,
        },
    )
    apply(reservation, {"status": "CONSUMED"})
    return single(zone, domain.ser_zone)


@bp.post("/installation-zones/<zone_id>/certify-weather-tight")
def certify_weather_tight(zone_id):
    auth("CWProjectManager")
    zone = get_or_404(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    values = read_fields(body(), (F("certification_note", "string", required=False),))

    if zone["weather_status"] not in ("NOT_TIGHT", "REMEDIATION"):
        raise ApiError("ERR_INVALID_STATE")
    if zone["install_status"] != "PANELS_HUNG":
        raise ApiError("ERR_ZONE_SEQUENCE_VIOLATION")
    package = domain.zone_package(zone)
    if package is not None and package["engineering_posture"] == "FROZEN":
        raise ApiError("ERR_ENGINEERING_POSTURE_FROZEN")

    tests = [t for t in db.field_tests.values() if t["zone_id"] == zone["id"]]
    passed_kinds = {t["test_kind"] for t in tests if t["state"] == "PASSED"}
    if not {"WATER_AAMA_501_2", "AIR_INFILTRATION"}.issubset(passed_kinds):
        raise ApiError("ERR_NO_FIELD_TEST_EVIDENCE")
    for test in tests:
        if test["state"] != "FAILED":
            continue
        linked = [
            item
            for item in db.defects.values()
            if item.get("field_test_id") == test["id"]
        ]
        for item in linked:
            if item["status"] not in ("CLOSED", "WAIVED"):
                raise ApiError("ERR_NO_FIELD_TEST_EVIDENCE")

    if domain.open_critical_defects(zone["package_id"], zone_id=zone["id"]):
        raise ApiError("ERR_OPEN_CRITICAL_DEFECT")

    allowance = zone["thermal_movement_allowance_mm"]
    if allowance is None or calc.D(allowance) > calc.D(zone["designed_joint_mm"]):
        raise ApiError("ERR_THERMAL_MOVEMENT_EXCEEDED")

    line = 0
    if package is not None:
        line = calc.certified_line_cents(
            zone["area_sqm"], package["unit_rate_cents_per_sqm"]
        )
        current = domain.earned_value_view(package)["certified_subtotal_cents"]
        if current + line > int(package["contract_value_cents"]):
            raise ApiError("ERR_BILLING_EXCEEDS_CONTRACT")

    updates = {
        "weather_status": "WEATHER_TIGHT",
        "weather_tight_at": now_iso(),
        "weather_tight_cycle_count": int(zone["weather_tight_cycle_count"]) + 1,
        "final_labor_cost_cents": domain.zone_final_labor_cents(zone),
        "certified_line_cents": line,
    }
    if values["certification_note"] is not None:
        updates["certification_note"] = values["certification_note"]
    apply(zone, updates)

    if package is not None:
        extra = None
        siblings = [z for z in db.zones.values() if z["package_id"] == package["id"]]
        if (
            siblings
            and all(z["weather_status"] == "WEATHER_TIGHT" for z in siblings)
            and package["state"] == "IN_INSTALLATION"
        ):
            extra = {"state": "WEATHER_TIGHT_ACHIEVED"}
        domain.sync_package(package, extra)
    return single(zone, domain.ser_zone)


@bp.post("/installation-zones/<zone_id>/retune-joint")
def retune_joint(zone_id):
    auth("CWDetailer")
    zone = get_or_404(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    values = read_fields(
        body(), (F("designed_joint_mm", "num", rng=lambda v: v > 0),)
    )
    package = domain.zone_package(zone)
    updates = {"designed_joint_mm": values["designed_joint_mm"]}
    if package is not None:
        updates.update(domain.zone_limit_fields(zone, package))
    apply(zone, updates)
    return single(zone, domain.ser_zone)


@bp.get("/installation-zones/<zone_id>/crew-day-logs")
def zone_crew_day_logs(zone_id):
    auth()
    zone = get_or_404(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    rows = collection(
        db.crew_days,
        zone_id=zone["id"],
        status=q_enum("status", CREW_DAY_STATUSES),
    )
    rows.sort(key=lambda log: (log["work_date"], log["created_at"], log["_seq"]))
    return listing(rows, domain.ser_crew_day, paginated=False)


@bp.get("/installation-zones/<zone_id>/field-tests")
def zone_field_tests(zone_id):
    auth()
    zone = get_or_404(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    rows = collection(
        db.field_tests,
        zone_id=zone["id"],
        test_kind=q_enum("test_kind", FIELD_TEST_KINDS),
        state=q_enum("state", FIELD_TEST_STATES),
    )
    return listing(rows, domain.ser_field_test, paginated=False)


# ==========================================================================
# AnchorEmbedSurvey
# ==========================================================================
SURVEY_SPECS = (
    F("embed_layout_ref", "string"),
    F("planned_anchor_count", "int", rng=lambda v: v >= 1),
    F("tolerance_mm", "num", required=False, default=25.0, rng=lambda v: v > 0),
)


@bp.post("/installation-zones/<zone_id>/embed-surveys")
def create_survey(zone_id):
    auth("StructuralContractor")
    zone = get_or_404(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    values = read_fields(body(), SURVEY_SPECS)
    row = base_row()
    row.update(
        {
            "zone_id": zone["id"],
            "embed_layout_ref": values["embed_layout_ref"],
            "planned_anchor_count": values["planned_anchor_count"],
            "tolerance_mm": values["tolerance_mm"],
            "state": "PENDING_SURVEY",
            "surveyed_anchor_count": None,
            "max_deviation_mm": None,
            "survey_attempt_count": 0,
            "surveyed_by_user_id": None,
            "poured_at": None,
        }
    )
    db.surveys[row["id"]] = row
    return created(row, domain.ser_survey)


@bp.get("/embed-surveys")
def list_surveys():
    auth()
    rows = collection(
        db.surveys,
        zone_id=q_str("zone_id"),
        state=q_enum("state", SURVEY_STATES),
    )
    return listing(rows, domain.ser_survey)


@bp.get("/embed-surveys/<survey_id>")
def read_survey(survey_id):
    auth()
    row = get_or_404(db.surveys, survey_id, "ERR_SURVEY_NOT_FOUND")
    return single(row, domain.ser_survey)


@bp.post("/embed-surveys/<survey_id>/survey")
def record_survey(survey_id):
    auth("StructuralContractor")
    acting = user_id()
    values = read_fields(
        body(),
        (
            F("surveyed_anchor_count", "int", rng=lambda v: v >= 0),
            F("max_deviation_mm", "num", rng=lambda v: v >= 0),
        ),
    )
    survey = get_or_404(db.surveys, survey_id, "ERR_SURVEY_NOT_FOUND")
    if survey["state"] == "POURED":
        raise ApiError("ERR_TERMINAL_STATE")
    if survey["state"] not in ("PENDING_SURVEY", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE")

    accepted = int(values["surveyed_anchor_count"]) == int(
        survey["planned_anchor_count"]
    ) and calc.D(values["max_deviation_mm"]) < calc.D(survey["tolerance_mm"])
    apply(
        survey,
        {
            "surveyed_anchor_count": values["surveyed_anchor_count"],
            "max_deviation_mm": values["max_deviation_mm"],
            "surveyed_by_user_id": acting,
            "survey_attempt_count": int(survey["survey_attempt_count"]) + 1,
            "state": "ACCEPTED" if accepted else "REJECTED",
        },
    )
    return single(survey, domain.ser_survey)


@bp.post("/embed-surveys/<survey_id>/confirm-pour")
def confirm_pour(survey_id):
    auth("StructuralContractor")
    values = read_fields(body(), (F("poured_at", "datetime"),))
    survey = get_or_404(db.surveys, survey_id, "ERR_SURVEY_NOT_FOUND")
    if survey["state"] == "POURED":
        raise ApiError("ERR_TERMINAL_STATE")
    if survey["state"] in ("PENDING_SURVEY", "REJECTED"):
        raise ApiError("ERR_POUR_BEFORE_ACCEPTANCE")
    if survey["state"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE")
    apply(survey, {"state": "POURED", "poured_at": fmt_dt(values["poured_at"])})
    return single(survey, domain.ser_survey)


# ==========================================================================
# CrewDayLog
# ==========================================================================
CREW_DAY_SPECS = (
    F("work_date", "date"),
    F("crew_size", "int", rng=lambda v: v >= 1),
    F("shift_hours", "num", rng=lambda v: 0 < v <= 16),
    F("panels_installed", "int", rng=lambda v: v >= 0),
)


@bp.post("/installation-zones/<zone_id>/crew-days")
def post_crew_day(zone_id):
    auth("FieldSuperintendent")
    require_user()
    zone = get_or_404(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    values = read_fields(body(), CREW_DAY_SPECS)

    for log in db.crew_days.values():
        if (
            log["zone_id"] == zone["id"]
            and log["status"] == "POSTED"
            and log["work_date"] == values["work_date"]
        ):
            raise ApiError("ERR_CREW_DAY_DUPLICATE")

    package = domain.zone_package(zone)
    base_rate = package["base_labor_rate_cents_per_hour"] if package else 0
    straight, overtime = calc.crew_day_hours(
        values["crew_size"], values["shift_hours"]
    )
    row = base_row()
    row.update(
        {
            "zone_id": zone["id"],
            "work_date": values["work_date"],
            "crew_size": values["crew_size"],
            "shift_hours": values["shift_hours"],
            "panels_installed": values["panels_installed"],
            "status": "POSTED",
            "day_index": None,
            "straight_person_hours": straight,
            "overtime_person_hours": overtime,
            "day_cost_cents": calc.crew_day_cost_cents(
                values["crew_size"],
                values["shift_hours"],
                base_rate,
                zone["height_m"],
            ),
            "void_reason": None,
        }
    )
    db.crew_days[row["id"]] = row
    domain.reindex_crew_days(zone["id"])
    return created(row, domain.ser_crew_day)


@bp.get("/crew-day-logs")
def list_crew_days():
    auth()
    rows = collection(
        db.crew_days,
        zone_id=q_str("zone_id"),
        status=q_enum("status", CREW_DAY_STATUSES),
        work_date=q_str("work_date"),
    )
    return listing(rows, domain.ser_crew_day)


@bp.get("/crew-day-logs/<log_id>")
def read_crew_day(log_id):
    auth()
    row = get_or_404(db.crew_days, log_id, "ERR_RESOURCE_NOT_FOUND")
    return single(row, domain.ser_crew_day)


@bp.post("/installation-zones/<zone_id>/crew-days/<crew_day_id>/void")
def void_crew_day(zone_id, crew_day_id):
    auth("FieldSuperintendent")
    zone = get_or_404(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    log = db.crew_days.get(crew_day_id)
    if log is None or log["zone_id"] != zone["id"]:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    values = read_fields(body(), (F("void_reason", "string"),))
    if log["status"] == "VOIDED":
        raise ApiError("ERR_TERMINAL_STATE")

    apply(
        log,
        {
            "status": "VOIDED",
            "void_reason": values["void_reason"],
            "day_index": None,
        },
    )
    domain.reindex_crew_days(zone["id"])
    zone_updates = {}
    if zone["weather_status"] == "WEATHER_TIGHT":
        zone_updates["final_labor_cost_cents"] = domain.zone_final_labor_cents(zone)
    if not apply(zone, zone_updates):
        touch(zone)
    return single(log, domain.ser_crew_day)


# ==========================================================================
# HoistRig
# ==========================================================================
RIG_SPECS = (
    F("package_id", "string"),
    F("rig_code", "string"),
    F("rig_kind", "enum", enum=RIG_KINDS),
    F("capacity_panels_per_shift", "int", rng=lambda v: v >= 1),
    F(
        "changeover_buffer_minutes",
        "int",
        required=False,
        default=45,
        rng=lambda v: v >= 0,
    ),
)


@bp.post("/hoist-rigs")
def create_rig():
    auth("FieldSuperintendent")
    values = read_fields(body(), RIG_SPECS)
    package = get_or_404(db.packages, values["package_id"], "ERR_PACKAGE_NOT_FOUND")
    row = base_row()
    row.update(
        {
            "package_id": package["id"],
            "rig_code": values["rig_code"],
            "rig_kind": values["rig_kind"],
            "capacity_panels_per_shift": values["capacity_panels_per_shift"],
            "changeover_buffer_minutes": values["changeover_buffer_minutes"],
            "status": "ACTIVE",
        }
    )
    db.rigs[row["id"]] = row
    return created(row, domain.ser_rig)


@bp.get("/hoist-rigs")
def list_rigs():
    auth()
    rows = collection(
        db.rigs,
        package_id=q_str("package_id"),
        status=q_enum("status", RIG_STATUSES),
    )
    return listing(rows, domain.ser_rig)


@bp.get("/hoist-rigs/<rig_id>")
def read_rig(rig_id):
    auth()
    row = get_or_404(db.rigs, rig_id, "ERR_HOIST_NOT_FOUND")
    return single(row, domain.ser_rig)


@bp.get("/hoist-rigs/<rig_id>/reservations")
def rig_reservations(rig_id):
    auth()
    rig = get_or_404(db.rigs, rig_id, "ERR_HOIST_NOT_FOUND")
    rows = collection(
        db.reservations,
        rig_id=rig["id"],
        status=q_enum("status", RESERVATION_STATUSES),
    )
    return listing(rows, domain.ser_reservation, paginated=False)


# ==========================================================================
# HoistReservation
# ==========================================================================
RESERVATION_SPECS = (
    F("rig_id", "string"),
    F("zone_id", "string"),
    F("window_start", "datetime"),
    F("window_end", "datetime"),
    F("planned_panel_count", "int", rng=lambda v: v >= 1),
)


@bp.post("/hoist-reservations")
def create_reservation():
    auth("FieldSuperintendent")
    values = read_fields(body(), RESERVATION_SPECS)
    window_start = values["window_start"]
    window_end = values["window_end"]
    check_window(window_start, window_end)

    zone = get_or_404(db.zones, values["zone_id"], "ERR_ZONE_NOT_FOUND")
    rig = get_or_404(db.rigs, values["rig_id"], "ERR_HOIST_NOT_FOUND")

    for other in sort_rows(list(db.reservations.values())):
        if other["rig_id"] != rig["id"]:
            continue
        if other["status"] not in ("RESERVED", "CONSUMED"):
            continue
        blocked_from = parse_dt(other["blocked_from"])
        blocked_until = parse_dt(other["blocked_until"])
        if blocked_from is None or blocked_until is None:
            continue
        if window_start < blocked_until and window_end > blocked_from:
            raise ApiError("ERR_HOIST_WINDOW_CONFLICT")

    buffer_minutes = int(rig["changeover_buffer_minutes"] or 0)
    buffer = timedelta(minutes=buffer_minutes)
    row = base_row()
    row.update(
        {
            "rig_id": rig["id"],
            "zone_id": zone["id"],
            "window_start": fmt_dt(window_start),
            "window_end": fmt_dt(window_end),
            "planned_panel_count": values["planned_panel_count"],
            "status": "RESERVED",
            "blocked_from": fmt_dt(window_start - buffer),
            "blocked_until": fmt_dt(window_end + buffer),
            "cancelled_reason": None,
        }
    )
    db.reservations[row["id"]] = row
    return created(row, domain.ser_reservation)


@bp.get("/hoist-reservations")
def list_reservations():
    auth()
    rows = collection(
        db.reservations,
        rig_id=q_str("rig_id"),
        zone_id=q_str("zone_id"),
        status=q_enum("status", RESERVATION_STATUSES),
    )
    return listing(rows, domain.ser_reservation)


@bp.get("/hoist-reservations/<reservation_id>")
def read_reservation(reservation_id):
    auth()
    row = get_or_404(db.reservations, reservation_id, "ERR_HOIST_NOT_FOUND")
    return single(row, domain.ser_reservation)


@bp.post("/hoist-reservations/<reservation_id>/cancel")
def cancel_reservation(reservation_id):
    auth("FieldSuperintendent")
    values = read_fields(body(), (F("cancelled_reason", "string"),))
    reservation = get_or_404(
        db.reservations, reservation_id, "ERR_HOIST_NOT_FOUND"
    )
    if reservation["status"] in ("CANCELLED", "CONSUMED"):
        raise ApiError("ERR_TERMINAL_STATE")
    apply(
        reservation,
        {"status": "CANCELLED", "cancelled_reason": values["cancelled_reason"]},
    )
    return single(reservation, domain.ser_reservation)
