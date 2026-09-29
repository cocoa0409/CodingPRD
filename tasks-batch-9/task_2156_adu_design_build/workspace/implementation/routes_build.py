"""Construction phases, inspection appointments, occupancy certificates."""
from datetime import date, timedelta

from flask import Blueprint, g, request

from common import (
    ALL_ROLES, DB, authorize, body_json, clock_date, fail, get_appointment, get_inspector,
    get_phase, get_project, listing, new_row, ok, parse_iso_dt, ser, touch, v_date, v_enum,
    v_int, v_str, v_datetime,
)
import calc
import services

bp = Blueprint("build", __name__)

PHASE_CODES = (
    "SITE_PREP", "FOUNDATION", "FRAMING", "ROUGH_MEP", "UTILITY_TIE_IN",
    "INSULATION_DRYWALL", "FINISHES",
)
DISRUPTION_CLASSES = ("NON_INVASIVE", "INVASIVE", "UTILITY_SHUTOFF")
INSPECTION_TYPES = ("FOUNDATION", "FRAMING", "ROUGH_MEP", "INSULATION", "FINAL")
CERT_REQUIREMENTS = {
    "FOUNDATION": ("STRUCTURAL",),
    "FRAMING": ("STRUCTURAL",),
    "ROUGH_MEP": ("ELECTRICAL", "PLUMBING"),
    "INSULATION": ("ENVELOPE",),
    "FINAL": ("FINAL",),
}


# ---------------------------------------------------------------------------
# Construction phases
# ---------------------------------------------------------------------------
@bp.post("/adu-projects/<pid>/construction-phases")
@authorize("ProjectManager")
def create_phase(pid):
    project = get_project(pid)
    body = body_json()

    raw_dep = body.get("depends_on_phase_id")
    if isinstance(raw_dep, str):
        get_phase(raw_dep)

    phase_code = v_enum(body, "phase_code", PHASE_CODES)
    disruption_class = v_enum(body, "disruption_class", DISRUPTION_CLASSES)
    sequence_index = v_int(body, "sequence_index", minimum=0)
    depends_on = v_str(body, "depends_on_phase_id", required=False, default=None)
    if depends_on is not None:
        get_phase(depends_on)

    row = new_row()
    row.update(
        adu_project_id=project["id"],
        depends_on_phase_id=depends_on,
        phase_code=phase_code,
        disruption_class=disruption_class,
        sequence_index=sequence_index,
        status="PLANNED",
        window_start_date=None,
        window_end_date=None,
        started_on_date=None,
        completed_on_date=None,
    )
    DB.phases[row["id"]] = row
    return ok(ser(row), 201)


@bp.get("/construction-phases")
@authorize(*ALL_ROLES)
def list_phases():
    rows = list(DB.phases.values())
    pid = request.args.get("adu_project_id")
    if pid:
        rows = [r for r in rows if r["adu_project_id"] == pid]
    dep = request.args.get("depends_on_phase_id")
    if dep:
        rows = [r for r in rows if r["depends_on_phase_id"] == dep]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows)


@bp.get("/construction-phases/<phid>")
@authorize(*ALL_ROLES)
def read_phase(phid):
    return ok(ser(get_phase(phid)))


@bp.post("/construction-phases/<phid>/schedule")
@authorize("ProjectManager")
def schedule_phase(phid):
    phase = get_phase(phid)
    body = body_json()
    window_start_date = v_date(body, "window_start_date")
    window_end_date = v_date(body, "window_end_date")
    start = date.fromisoformat(window_start_date)
    end = date.fromisoformat(window_end_date)
    if end < start:
        fail("ERR_VALIDATION", "window_end_date must not precede window_start_date.")

    if phase["status"] not in ("PLANNED", "BLOCKED"):
        fail("ERR_PHASE_STATE_INVALID", "Phase cannot be scheduled from %s." % phase["status"])

    project = DB.projects[phase["adu_project_id"]]
    if project["status"] not in ("PERMITTED", "UNDER_CONSTRUCTION"):
        fail("ERR_PROJECT_PHASE_INVALID", "Project cannot schedule phases from %s."
             % project["status"])

    prop = DB.properties[project["property_id"]]

    if (prop["occupied"] and phase["disruption_class"] == "UTILITY_SHUTOFF"
            and (end - start).days + 1 > calc.MAX_SHUTOFF_DAYS_OCCUPIED):
        fail("ERR_OCCUPIED_HABITABILITY_VIOLATION",
             "A utility shutoff on an occupied parcel may span at most one calendar day.")

    buffer_days = calc.HABITABILITY_BUFFER_DAYS if prop["occupied"] else 0
    for other in DB.phases.values():
        if other["id"] == phase["id"]:
            continue
        if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        other_project = DB.projects.get(other["adu_project_id"])
        if other_project is None or other_project["property_id"] != prop["id"]:
            continue
        if other["window_start_date"] is None or other["window_end_date"] is None:
            continue
        o_start = date.fromisoformat(other["window_start_date"])
        o_end = date.fromisoformat(other["window_end_date"])
        if (start <= o_end + timedelta(days=buffer_days)
                and o_start <= end + timedelta(days=buffer_days)):
            fail("ERR_PHASE_WINDOW_CONFLICT",
                 "The requested window collides with another booked window on this parcel.")

    phase["status"] = "SCHEDULED"
    phase["window_start_date"] = window_start_date
    phase["window_end_date"] = window_end_date
    touch(phase)
    return ok(ser(phase))


@bp.post("/construction-phases/<phid>/start")
@authorize("ProjectManager")
def start_phase(phid):
    phase = get_phase(phid)
    if phase["status"] != "SCHEDULED":
        fail("ERR_PHASE_STATE_INVALID", "Phase cannot start from %s." % phase["status"])

    project = DB.projects[phase["adu_project_id"]]
    latest = services.latest_submittal(project["id"])
    if latest is None or latest["status"] != "APPROVED":
        fail("ERR_PERMIT_NOT_APPROVED", "The project's newest permit submittal is not APPROVED.")

    dep_id = phase["depends_on_phase_id"]
    if dep_id is not None:
        dep = DB.phases.get(dep_id)
        if dep is None or dep["status"] != "COMPLETE":
            fail("ERR_PHASE_DEPENDENCY_INCOMPLETE", "Predecessor phase is not COMPLETE.")

    phase["status"] = "IN_PROGRESS"
    phase["started_on_date"] = clock_date()
    touch(phase)

    if project["status"] == "PERMITTED":
        project["status"] = "UNDER_CONSTRUCTION"
        touch(project)
    return ok(ser(phase))


@bp.post("/construction-phases/<phid>/complete")
@authorize("ProjectManager")
def complete_phase(phid):
    phase = get_phase(phid)
    if phase["status"] != "IN_PROGRESS":
        fail("ERR_PHASE_STATE_INVALID", "Phase cannot complete from %s." % phase["status"])

    for appt in services.phase_appointments(phase["id"]):
        if appt["status"] in ("SCHEDULED", "PARTIAL"):
            fail("ERR_OPEN_INSPECTIONS_REMAIN", "An inspection on this phase is still open.")

    phase["status"] = "COMPLETE"
    phase["completed_on_date"] = clock_date()
    touch(phase)
    return ok(ser(phase))


# ---------------------------------------------------------------------------
# Inspection appointments
# ---------------------------------------------------------------------------
@bp.post("/construction-phases/<phid>/inspection-appointments")
@authorize("ProjectManager")
def create_appointment(phid):
    phase = get_phase(phid)
    body = body_json()

    raw_inspector = body.get("inspector_id")
    if isinstance(raw_inspector, str):
        get_inspector(raw_inspector)

    inspector_id = v_str(body, "inspector_id")
    inspector = get_inspector(inspector_id)
    inspection_type = v_enum(body, "inspection_type", INSPECTION_TYPES)
    slot_date = v_date(body, "slot_date")
    raw_start, start_dt = v_datetime(body, "slot_start")
    raw_end, end_dt = v_datetime(body, "slot_end")

    if start_dt.date().isoformat() != slot_date:
        fail("ERR_VALIDATION", "slot_date must equal the UTC date part of slot_start.")
    if end_dt <= start_dt:
        fail("ERR_VALIDATION", "slot_end must be strictly later than slot_start.")

    required = CERT_REQUIREMENTS[inspection_type]
    for cert in required:
        if cert not in inspector["certifications"]:
            fail("ERR_INSPECTOR_NOT_CERTIFIED",
                 "Inspector is not certified for %s." % inspection_type)

    if inspector["status"] != "ACTIVE":
        fail("ERR_INSPECTOR_INACTIVE", "Inspector is not ACTIVE.")

    for other in DB.appointments.values():
        if other["inspector_id"] != inspector_id:
            continue
        if other["status"] not in ("SCHEDULED", "PARTIAL"):
            continue
        if start_dt < other["_slot_end_dt"] and other["_slot_start_dt"] < end_dt:
            fail("ERR_INSPECTOR_SLOT_CONFLICT",
                 "The requested slot overlaps an appointment the inspector already holds.")

    booked = [
        a for a in DB.appointments.values()
        if a["inspector_id"] == inspector_id
        and a["slot_date"] == slot_date
        and a["status"] in ("SCHEDULED", "PARTIAL")
    ]
    if len(booked) >= inspector["daily_capacity"]:
        fail("ERR_INSPECTOR_DAILY_CAPACITY_EXCEEDED",
             "The inspector is already at capacity on %s." % slot_date)

    row = new_row()
    row.update(
        adu_project_id=phase["adu_project_id"],
        construction_phase_id=phase["id"],
        inspector_id=inspector_id,
        inspection_type=inspection_type,
        slot_date=slot_date,
        slot_start=raw_start,
        slot_end=raw_end,
        status="SCHEDULED",
        result_notes=None,
        recorded_by_inspector_id=None,
    )
    row["_slot_start_dt"] = start_dt
    row["_slot_end_dt"] = end_dt
    DB.appointments[row["id"]] = row
    return ok(ser(row), 201)


@bp.get("/inspection-appointments")
@authorize(*ALL_ROLES)
def list_appointments():
    rows = list(DB.appointments.values())
    for key in ("adu_project_id", "construction_phase_id", "inspector_id",
                "recorded_by_inspector_id", "slot_date", "status"):
        val = request.args.get(key)
        if val:
            rows = [r for r in rows if r[key] == val]
    return listing(rows)


@bp.get("/inspection-appointments/<aid>")
@authorize(*ALL_ROLES)
def read_appointment(aid):
    return ok(ser(get_appointment(aid)))


@bp.post("/inspection-appointments/<aid>/result")
@authorize("BuildingInspector")
def record_result(aid):
    appt = get_appointment(aid)
    if g.user_id != appt["inspector_id"]:
        fail("ERR_NOT_ASSIGNED_INSPECTOR", "This appointment is booked to another inspector.")

    body = body_json()
    outcome = v_enum(body, "outcome", ("PASS", "FAIL", "PARTIAL"))
    result_notes = v_str(body, "result_notes", required=False, default=None, allow_empty=True)

    if appt["status"] not in ("SCHEDULED", "PARTIAL"):
        fail("ERR_APPOINTMENT_STATE_INVALID", "Appointment is already %s." % appt["status"])

    if appt["inspection_type"] == "FINAL":
        for other in DB.appointments.values():
            if other["id"] == appt["id"]:
                continue
            if other["adu_project_id"] != appt["adu_project_id"]:
                continue
            if other["recorded_by_inspector_id"] == g.user_id:
                fail("ERR_SEGREGATION_OF_DUTIES",
                     "This inspector already recorded a result on this project.")

    appt["status"] = {"PASS": "PASSED", "FAIL": "FAILED", "PARTIAL": "PARTIAL"}[outcome]
    appt["recorded_by_inspector_id"] = g.user_id
    appt["result_notes"] = result_notes
    touch(appt)
    return ok(ser(appt))


@bp.post("/inspection-appointments/<aid>/cancel")
@authorize("ProjectManager")
def cancel_appointment(aid):
    appt = get_appointment(aid)
    if appt["status"] not in ("SCHEDULED", "PARTIAL"):
        fail("ERR_APPOINTMENT_STATE_INVALID", "Appointment is already %s." % appt["status"])
    appt["status"] = "CANCELLED"
    touch(appt)
    return ok(ser(appt))


# ---------------------------------------------------------------------------
# Occupancy certificate
# ---------------------------------------------------------------------------
@bp.post("/adu-projects/<pid>/occupancy-certificate")
@authorize("PlanChecker")
def issue_certificate(pid):
    project = get_project(pid)
    if project["status"] != "UNDER_CONSTRUCTION":
        fail("ERR_PROJECT_PHASE_INVALID", "Project is not UNDER_CONSTRUCTION.")

    for cert in DB.certificates.values():
        if cert["adu_project_id"] == project["id"]:
            fail("ERR_CERTIFICATE_ALREADY_ISSUED", "Project already holds a certificate.")

    for uc in services.project_utilities(project["id"]):
        if uc["status"] != "ENERGIZED":
            fail("ERR_UTILITY_NOT_ENERGIZED", "A utility connection is not ENERGIZED.")

    for phase in services.project_phases(project["id"]):
        if phase["status"] != "COMPLETE":
            fail("ERR_PHASES_INCOMPLETE", "A construction phase is not COMPLETE.")

    finals = [
        a for a in services.project_appointments(project["id"])
        if a["inspection_type"] == "FINAL" and a["status"] == "PASSED"
    ]
    if not finals:
        fail("ERR_FINAL_INSPECTION_MISSING", "No PASSED FINAL inspection on this project.")
    finals.sort(key=lambda a: (a["_slot_end_dt"], -a["_seq"]), reverse=True)
    qualifying = finals[0]

    prop = DB.properties[project["property_id"]]
    jur = DB.jurisdictions[prop["jurisdiction_id"]]

    issued_count = 0
    for cert in DB.certificates.values():
        other_project = DB.projects.get(cert["adu_project_id"])
        if other_project is None:
            continue
        other_prop = DB.properties.get(other_project["property_id"])
        if other_prop is not None and other_prop["jurisdiction_id"] == jur["id"]:
            issued_count += 1

    row = new_row(common=False)
    row.update(
        adu_project_id=project["id"],
        certificate_number="%s-%d" % (jur["code"], issued_count + 1),
        issued_on_date=clock_date(),
        final_inspection_passed_at=qualifying["slot_end"],
    )
    row.update(calc.rental_readiness_check(project, prop, jur))
    DB.certificates[row["id"]] = row

    project["status"] = "FINALED"
    touch(project)
    return ok(ser(row), 201)


@bp.get("/adu-projects/<pid>/occupancy-certificates")
@authorize(*ALL_ROLES)
def list_certificates(pid):
    get_project(pid)
    rows = [c for c in DB.certificates.values() if c["adu_project_id"] == pid]
    return listing(rows)
