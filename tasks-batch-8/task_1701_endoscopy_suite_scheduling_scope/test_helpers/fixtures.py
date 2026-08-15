"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use the lenient get_success_data
validator so failures surface as clear "Setup step failed" errors.

Identity threading: Endoscopist calls are entity-backed by Provider and
AnesthesiaProvider calls are entity-backed by AnesthesiaProvider (PRD §2.1);
every ownership-gated call uses make_endoscopist_headers(provider["id"]) /
make_anesthesia_provider_headers(ap["id"]) — never the shared constants.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    completion_payload,
    create_assignment_payload,
    create_booking_payload,
    create_culture_payload,
    create_cycle_payload,
    create_egd_type_payload,
    create_patient_payload,
    create_procedure_type_payload,
    create_provider_payload,
    create_anesthesia_provider_payload,
    create_quality_report_payload,
    create_room_payload,
    create_scope_payload,
    create_specimen_payload,
    culture_result_payload,
    prep_assessment_payload,
)
from .test_users import (
    TEST_USERS,
    make_anesthesia_provider_headers,
    make_endoscopist_headers,
    make_nurse_headers,
    make_pathology_headers,
    make_technician_headers,
)

ADMIN = TEST_USERS["unit_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]
NURSE = TEST_USERS["nurse_headers"]
PATHO = TEST_USERS["pathology_headers"]
QO = TEST_USERS["quality_officer_headers"]


# ---------------------------------------------------------------------------
# Time helpers (the logical clock, PRD §2.4)
# ---------------------------------------------------------------------------

def parse_iso(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def fmt_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_minutes(iso: str, minutes: float) -> str:
    return fmt_iso(parse_iso(iso) + timedelta(minutes=minutes))


def add_seconds(iso: str, seconds: float) -> str:
    return fmt_iso(parse_iso(iso) + timedelta(seconds=seconds))


def add_hours(iso: str, hours: float) -> str:
    return fmt_iso(parse_iso(iso) + timedelta(hours=hours))


def advance_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (UnitAdmin-only capability).

    The logical clock only moves strictly forward (PRD §2.4), so a call whose
    target equals the current reading is a no-op instead of a rejected request;
    a call whose target falls behind it is a fixture-authoring bug and fails
    loudly through the server's ERR_CLOCK_REGRESSION response."""
    if parse_iso(to_iso8601) == _CLOCK_TRACK["now"]:
        return {"current_utc": to_iso8601}
    data = get_success_data(api_client.set_clock(to_iso8601, ADMIN))
    _CLOCK_TRACK["now"] = parse_iso(to_iso8601)
    return data


# Per-test logical-clock reading tracker. The harness restarts the server (and
# its clock) before every test, so test_suite/conftest.py resets this tracker
# before each test via the autouse fixture there.
_CLOCK_TRACK = {"now": parse_iso(DEFAULT_CLOCK_ISO)}


def reset_clock_tracker():
    _CLOCK_TRACK["now"] = parse_iso(DEFAULT_CLOCK_ISO)


# ---------------------------------------------------------------------------
# Tier 1: registry creation
# ---------------------------------------------------------------------------

def create_patient(mrn="MRN-1", full_name="Pat Test", date_of_birth="1990-05-05",
                   **extra):
    return get_success_data(api_client.create_patient(
        create_patient_payload(mrn=mrn, full_name=full_name,
                               date_of_birth=date_of_birth, **extra), SCHED))


def create_provider(full_name="Dr Test", specialty="GASTROENTEROLOGY"):
    return get_success_data(api_client.create_provider(
        create_provider_payload(full_name=full_name, specialty=specialty), ADMIN))


def create_colono_type(code="COLONO", base_duration_minutes=40, prep_protocol="SPLIT_DOSE",
                       colonoscopy_family=True, adr_relevant=True,
                       required_scope_type="COLONOSCOPE"):
    return get_success_data(api_client.create_procedure_type(
        create_procedure_type_payload(
            code=code, base_duration_minutes=base_duration_minutes,
            prep_protocol=prep_protocol, colonoscopy_family=colonoscopy_family,
            adr_relevant=adr_relevant, required_scope_type=required_scope_type),
        ADMIN))


def create_egd_type(code="EGD", prep_protocol="CLEAR_LIQUIDS"):
    return get_success_data(api_client.create_procedure_type(
        create_egd_type_payload(code=code, prep_protocol=prep_protocol), ADMIN))


def create_room(name="R-STD", room_class="STANDARD", supports_anesthesia=True):
    return get_success_data(api_client.create_room(
        create_room_payload(name=name, room_class=room_class,
                            supports_anesthesia=supports_anesthesia), ADMIN))


def create_anesthesia_provider(full_name="Ann Esthesia"):
    return get_success_data(api_client.create_anesthesia_provider(
        create_anesthesia_provider_payload(full_name=full_name), ADMIN))


def create_scope(serial_number="SC-1", scope_type="COLONOSCOPE"):
    return get_success_data(api_client.create_scope(
        create_scope_payload(serial_number=serial_number, scope_type=scope_type), ADMIN))


def make_registry(mrn="MRN-1", patient_dob="1990-05-05", serial="SC-1",
                  scope_type="COLONOSCOPE", room_class="STANDARD",
                  room_name="R-STD", with_scope=True):
    """Patient + provider + COLONO type + room (+ scope). Returns a dict."""
    out = {
        "patient": create_patient(mrn=mrn, date_of_birth=patient_dob),
        "provider": create_provider(),
        "ptype": create_colono_type(),
        "room": create_room(name=room_name, room_class=room_class),
    }
    if with_scope:
        out["scope"] = create_scope(serial_number=serial, scope_type=scope_type)
    return out


# ---------------------------------------------------------------------------
# Tier 1: bookings and readers
# ---------------------------------------------------------------------------

def create_booking(patient_id, provider_id, procedure_type_id, room_id,
                   scheduled_start="2026-08-03T09:00:00Z", indication="SCREENING",
                   anesthesia_type="NONE", notes=None):
    payload = create_booking_payload(
        patient_id, provider_id, procedure_type_id, room_id,
        scheduled_start=scheduled_start, indication=indication,
        anesthesia_type=anesthesia_type)
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.create_booking(payload, SCHED))


def get_booking(booking_id):
    return get_success_data(api_client.get_booking(booking_id, ADMIN))


def get_scope(scope_id):
    return get_success_data(api_client.get_scope(scope_id, ADMIN))


def get_anesthesia_provider(ap_id):
    return get_success_data(api_client.get_anesthesia_provider(ap_id, ADMIN))


def get_assignment(assignment_id):
    return get_success_data(api_client.get_anesthesia_assignment(assignment_id, ADMIN))


def get_cycle(cycle_id):
    return get_success_data(api_client.get_reprocessing_cycle(cycle_id, ADMIN))


def get_case(case_id):
    return get_success_data(api_client.get_quarantine_case(case_id, NURSE))


def get_usage(usage_id):
    return get_success_data(api_client.get_scope_usage(usage_id, ADMIN))


def first_usage_for_booking(booking_id):
    data, _ = validate_paginated(api_client.list_scope_usages(
        ADMIN, params={"booking_id": booking_id}))
    assert len(data) >= 1, f"expected a usage for booking {booking_id}"
    return data[0]


def first_case_for_scope(scope_id):
    data, _ = validate_paginated(api_client.list_quarantine_cases(
        NURSE, params={"scope_id": scope_id}))
    assert len(data) >= 1, f"expected a quarantine case for scope {scope_id}"
    return data[0]


# ---------------------------------------------------------------------------
# Tier 2: booking day-of-procedure drivers
# ---------------------------------------------------------------------------

def confirm_prep(booking_id):
    return get_success_data(api_client.confirm_prep(booking_id, SCHED))


def check_in(booking_id):
    return get_success_data(api_client.check_in_booking(booking_id, SCHED))


def start_procedure(booking_id, provider_id, scope_id=None):
    payload = {"scope_id": scope_id} if scope_id else {}
    return get_success_data(api_client.start_booking(
        booking_id, payload, make_endoscopist_headers(provider_id)))


def assess_prep(booking_id, provider_id, left=2, right=2, transverse=2):
    return get_success_data(api_client.record_prep_assessment(
        booking_id, prep_assessment_payload(left, right, transverse),
        make_endoscopist_headers(provider_id)))


def complete_procedure(booking_id, provider_id, cecum_intubated=True,
                       withdrawal_time_seconds=400, adenomas_detected=0):
    return get_success_data(api_client.complete_booking(
        booking_id,
        completion_payload(cecum_intubated, withdrawal_time_seconds, adenomas_detected),
        make_endoscopist_headers(provider_id)))


def abort_procedure(booking_id, provider_id, reason="prep inadequate"):
    return get_success_data(api_client.abort_booking(
        booking_id, {"reason": reason}, make_endoscopist_headers(provider_id)))


def cancel_booking(booking_id, reason="patient request"):
    return get_success_data(api_client.cancel_booking(booking_id, {"reason": reason}, SCHED))


def create_checked_in_booking(patient_id, provider_id, procedure_type_id, room_id,
                              scope_id, scheduled_start, clock_iso=None,
                              indication="SCREENING", anesthesia_type="NONE"):
    """Create + confirm + (clock) + check-in. Leaves clock at check-in time."""
    booking = create_booking(patient_id, provider_id, procedure_type_id, room_id,
                             scheduled_start=scheduled_start, indication=indication,
                             anesthesia_type=anesthesia_type)
    confirm_prep(booking["id"])
    advance_clock(clock_iso or scheduled_start)
    check_in(booking["id"])
    return booking


def create_in_progress_booking(patient_id, provider_id, procedure_type_id, room_id,
                               scope_id, scheduled_start="2026-08-03T09:00:00Z",
                               clock_iso=None, indication="SCREENING",
                               anesthesia_type="NONE", auto_scope=False):
    """Drive a booking to IN_PROGRESS. Returns the started booking."""
    booking = create_checked_in_booking(
        patient_id, provider_id, procedure_type_id, room_id, scope_id,
        scheduled_start, clock_iso=clock_iso, indication=indication,
        anesthesia_type=anesthesia_type)
    return start_procedure(booking["id"], provider_id,
                           None if auto_scope else scope_id)


def run_procedure_to_complete(booking_id, provider_id, scope_id, start_iso, end_iso,
                              bbps=(2, 2, 2), cecum_intubated=True,
                              withdrawal_time_seconds=400, adenomas_detected=0):
    """check-in at start_iso -> start -> assess -> complete at end_iso."""
    advance_clock(start_iso)
    check_in(booking_id)
    start_procedure(booking_id, provider_id, scope_id)
    assess_prep(booking_id, provider_id, *bbps)
    advance_clock(end_iso)
    return complete_procedure(booking_id, provider_id, cecum_intubated,
                              withdrawal_time_seconds, adenomas_detected)


# ---------------------------------------------------------------------------
# Tier 2: anesthesia assignments
# ---------------------------------------------------------------------------

def create_assignment(booking_id, anesthesia_provider_id):
    return get_success_data(api_client.create_anesthesia_assignment(
        create_assignment_payload(booking_id, anesthesia_provider_id), SCHED))


def confirm_assignment(assignment_id, anesthesia_provider_id):
    return get_success_data(api_client.confirm_anesthesia_assignment(
        assignment_id, make_anesthesia_provider_headers(anesthesia_provider_id)))


# ---------------------------------------------------------------------------
# Tier 2/3: reprocessing cycles
# ---------------------------------------------------------------------------

def send_to_reprocessing(scope_id):
    return get_success_data(api_client.send_scope_to_reprocessing(
        scope_id, make_technician_headers("tech-1")))


def create_cycle(scope_id, technician_id="tech-1", booking_id=None):
    payload = create_cycle_payload(scope_id)
    if booking_id is not None:
        payload["booking_id"] = booking_id
    return get_success_data(api_client.create_reprocessing_cycle(
        payload, make_technician_headers(technician_id)))


def advance_step(cycle_id, to_step, technician_id="tech-1", **fields):
    payload = {"to_step": to_step}
    payload.update(fields)
    return get_success_data(api_client.advance_cycle_step(
        cycle_id, payload, make_technician_headers(technician_id)))


def run_complete_cycle(scope_id, start_iso, technician_id="tech-1", booking_id=None,
                       lot="LOT-1", ppm=350, send_first=False, clean_gap_minutes=6):
    """Drive a cycle INITIATED -> COMPLETE with step minimums satisfied.

    Cadence (all within PRD §3.6 minimums): preclean at start; clean at
    start+clean_gap (default 6 min >= 5; pass >= 20 for extended-soak cycles);
    disinfect 10 min after clean (>= 600 s); dry 10 min after disinfect;
    complete immediately. Returns the COMPLETE cycle."""
    advance_clock(start_iso)
    if send_first:
        send_to_reprocessing(scope_id)
    cycle = create_cycle(scope_id, technician_id=technician_id, booking_id=booking_id)
    cid = cycle["id"]
    advance_step(cid, "PRECLEANED", technician_id)
    clean_at = add_minutes(start_iso, clean_gap_minutes)
    advance_clock(clean_at)
    advance_step(cid, "CLEANED", technician_id)
    disinfect_at = add_minutes(clean_at, 10)
    advance_clock(disinfect_at)
    advance_step(cid, "DISINFECTED", technician_id,
                 hld_solution_lot=lot, hld_concentration_ppm=ppm)
    dry_at = add_minutes(disinfect_at, 10)
    advance_clock(dry_at)
    advance_step(cid, "DRIED", technician_id)
    return advance_step(cid, "COMPLETE", technician_id)


def create_reprocessed_scope(serial_number="SC-R1", scope_type="COLONOSCOPE",
                             start_iso="2026-08-01T08:00:00Z", technician_id="tech-1",
                             lot="LOT-1", ppm=350):
    """Fresh scope -> manual send -> full cycle -> AVAILABLE with a 72h expiry.
    Returns (scope, cycle)."""
    scope = create_scope(serial_number=serial_number, scope_type=scope_type)
    cycle = run_complete_cycle(scope["id"], start_iso, technician_id=technician_id,
                               lot=lot, ppm=ppm, send_first=True)
    return get_scope(scope["id"]), cycle


def create_culture(scope_id, cycle_id, nurse_id="nurse-1"):
    return get_success_data(api_client.create_culture_test(
        create_culture_payload(scope_id, cycle_id), make_nurse_headers(nurse_id)))


def result_culture(culture_id, result="NEGATIVE", organism=None, cfu_count=None,
                   nurse_id="nurse-1"):
    payload = culture_result_payload(result)
    if organism is not None:
        payload["organism"] = organism
    if cfu_count is not None:
        payload["cfu_count"] = cfu_count
    return get_success_data(api_client.result_culture_test(
        culture_id, payload, make_nurse_headers(nurse_id)))


# ---------------------------------------------------------------------------
# Tier 3: quarantine chains
# ---------------------------------------------------------------------------

def create_quarantined_scope(serial_number="SQ-1", technician_id="tech-1",
                             day="2026-08-20", organism="E_COLI", cfu_count=25):
    """Scope with a COMPLETE cycle whose culture comes back POSITIVE.
    Returns (scope, cycle, culture, case); scope is QUARANTINED, case OPEN.
    Clock ends at {day}T09:00:00Z."""
    scope = create_scope(serial_number=serial_number)
    cycle = run_complete_cycle(scope["id"], f"{day}T08:00:00Z",
                               technician_id=technician_id, lot="LOT-Q0", ppm=350,
                               send_first=True)
    advance_clock(f"{day}T09:00:00Z")
    culture = create_culture(scope["id"], cycle["id"])
    result_culture(culture["id"], "POSITIVE", organism=organism, cfu_count=cfu_count)
    case = first_case_for_scope(scope["id"])
    return get_scope(scope["id"]), cycle, culture, case


def run_reculture_cycle(scope_id, technician_id="tech-7", start_iso="2026-08-20T09:30:00Z",
                        lot="LOT-Q1", ppm=400):
    """Reculture cycle on a QUARANTINED scope: case OPEN -> RECULTURING and the
    scope stays QUARANTINED at COMPLETE. Returns the COMPLETE cycle. Uses a
    21-minute manual-clean gap so the step minimum is met whether or not the
    scope's preclean deadline makes this an extended-soak cycle (PRD §3.6)."""
    return run_complete_cycle(scope_id, start_iso, technician_id=technician_id,
                              lot=lot, ppm=ppm, clean_gap_minutes=21)


def create_release_ready_scope(serial_number="SQ-R", reculture_technician="tech-7",
                               day="2026-08-20"):
    """Quarantined scope + COMPLETE reculture cycle + NEGATIVE reculture culture.
    Returns (scope, cycle_q0, cycle_q1, case). Clock ends at {day}T10:15:00Z."""
    scope, cycle_q0, _culture0, case = create_quarantined_scope(
        serial_number=serial_number, day=day)
    cycle_q1 = run_reculture_cycle(scope["id"], technician_id=reculture_technician,
                                   start_iso=f"{day}T09:30:00Z")
    advance_clock(f"{day}T10:15:00Z")
    culture1 = create_culture(scope["id"], cycle_q1["id"])
    result_culture(culture1["id"], "NEGATIVE")
    return get_scope(scope["id"]), cycle_q0, cycle_q1, get_case(case["id"])


# ---------------------------------------------------------------------------
# Tier 2: specimens
# ---------------------------------------------------------------------------

def collect_specimen(booking_id, provider_id, specimen_type="POLYP", container_count=1):
    return get_success_data(api_client.create_specimen(
        create_specimen_payload(booking_id, specimen_type=specimen_type,
                                container_count=container_count),
        make_endoscopist_headers(provider_id)))


def label_specimen(specimen_id, user_id="lab-1", as_endoscopist_provider_id=None):
    headers = (make_endoscopist_headers(as_endoscopist_provider_id)
               if as_endoscopist_provider_id else make_pathology_headers(user_id))
    return get_success_data(api_client.label_specimen(specimen_id, headers))


def handoff_specimen(specimen_id, courier_id="courier-1", user_id="lab-1"):
    return get_success_data(api_client.handoff_specimen(
        specimen_id, {"courier_id": courier_id}, make_pathology_headers(user_id)))


def setup_in_progress_with_specimen(mrn="MRN-SP", scheduled_start="2026-08-03T09:00:00Z"):
    """Booking IN_PROGRESS with a scope + one COLLECTED specimen. Returns dict."""
    reg = make_registry(mrn=mrn, serial="SC-SP")
    booking = create_in_progress_booking(
        reg["patient"]["id"], reg["provider"]["id"], reg["ptype"]["id"],
        reg["room"]["id"], reg["scope"]["id"], scheduled_start=scheduled_start)
    return {"booking": booking, **reg}


# ---------------------------------------------------------------------------
# Tier 4: threshold / accumulation composite scenarios
# ---------------------------------------------------------------------------

def setup_two_assignment_ledger():
    """Ba COLONO/MAC 2026-08-06T09:00 in RA (50 min) + Bb EGD/MAC 11:00 in RB
    (35 min), assignments Aa/Ab on AP1 -> scheduled_minutes == 85."""
    patient = create_patient(mrn="MRN-LED", date_of_birth="1990-05-05")
    provider = create_provider("Dr Ledger")
    t_col = create_colono_type()
    t_egd = create_egd_type()
    ra = create_room(name="RA")
    rb = create_room(name="RB")
    ap1 = create_anesthesia_provider()
    ba = create_booking(patient["id"], provider["id"], t_col["id"], ra["id"],
                        scheduled_start="2026-08-06T09:00:00Z", anesthesia_type="MAC")
    bb = create_booking(patient["id"], provider["id"], t_egd["id"], rb["id"],
                        scheduled_start="2026-08-06T11:00:00Z", indication="DIAGNOSTIC",
                        anesthesia_type="MAC")
    aa = create_assignment(ba["id"], ap1["id"])
    ab = create_assignment(bb["id"], ap1["id"])
    return {"patient": patient, "provider": provider, "t_col": t_col, "t_egd": t_egd,
            "ra": ra, "rb": rb, "ap1": ap1, "ba": ba, "bb": bb, "aa": aa, "ab": ab}


def setup_quality_metrics_scenario():
    """Seven-booking quality-metric day (2026-08-03) for one provider.

    B1 SCREENING mid-age adequate, cecum, withdrawal 540, adenomas 2 (COMPLETED)
    B2 SCREENING senior adequate (3,3,3), cecum, withdrawal 480, adenomas 0
    B3 SCREENING young INADEQUATE (2,2,1), completed, cecum, 500, adenomas 1
    B4 DIAGNOSTIC young adequate, completed, cecum, 420, adenomas 1
    B5 SCREENING young INADEQUATE (3,3,0), aborted
    B6 SCREENING young adequate, completed, cecum NOT intubated, 300, adenomas 0
    B7 SCREENING mid-age adequate, specimen taken, completed, cecum, 600, adenomas 0
    """
    p_mid = create_patient(mrn="M2001", full_name="Pat Mid", date_of_birth="1976-03-10")
    p_sr = create_patient(mrn="M2002", full_name="Pat Senior", date_of_birth="1966-05-20")
    p_yng = create_patient(mrn="M2003", full_name="Pat Young", date_of_birth="1990-05-05")
    drq = create_provider("Dr Quality")
    t_col = create_colono_type()
    room = create_room(name="RQ")
    scopes = [create_scope(serial_number=f"QSC-{i}") for i in range(1, 8)]
    starts = ["08:00", "08:55", "09:50", "10:45", "11:40", "12:35", "13:30"]
    patients = [p_mid, p_sr, p_yng, p_yng, p_yng, p_yng, p_mid]
    indications = ["SCREENING", "SCREENING", "SCREENING", "DIAGNOSTIC", "SCREENING",
                   "SCREENING", "SCREENING"]
    bookings = []
    for pat, start, ind in zip(patients, starts, indications):
        b = create_booking(pat["id"], drq["id"], t_col["id"], room["id"],
                           scheduled_start=f"2026-08-03T{start}:00Z", indication=ind)
        confirm_prep(b["id"])
        bookings.append(b)

    def run(b, scope, start, end, bbps, cecum, withdrawal, adenomas, specimen=False,
            abort=False):
        advance_clock(f"2026-08-03T{start}:00Z")
        check_in(b["id"])
        start_procedure(b["id"], drq["id"], scope["id"])
        if specimen:
            collect_specimen(b["id"], drq["id"], specimen_type="POLYP")
        assess_prep(b["id"], drq["id"], *bbps)
        if abort:
            abort_procedure(b["id"], drq["id"], reason="inadequate prep")
        else:
            advance_clock(f"2026-08-03T{end}:00Z")
            complete_procedure(b["id"], drq["id"], cecum, withdrawal, adenomas)

    run(bookings[0], scopes[0], "08:00", "08:40", (2, 2, 2), True, 540, 2)
    run(bookings[1], scopes[1], "08:55", "09:35", (3, 3, 3), True, 480, 0)
    run(bookings[2], scopes[2], "09:50", "10:30", (2, 2, 1), True, 500, 1)
    run(bookings[3], scopes[3], "10:45", "11:25", (2, 2, 2), True, 420, 1)
    run(bookings[4], scopes[4], "11:40", None, (3, 3, 0), None, None, None, abort=True)
    run(bookings[5], scopes[5], "12:35", "13:15", (2, 2, 2), False, 300, 0)
    run(bookings[6], scopes[6], "13:30", "14:10", (2, 2, 2), True, 600, 0, specimen=True)
    return {"provider": drq, "bookings": bookings, "room": room, "scopes": scopes}


def create_quality_report(provider_id, period_start, period_end, metric_variant="STRICT"):
    return get_success_data(api_client.create_quality_report(
        create_quality_report_payload(provider_id, period_start, period_end,
                                      metric_variant), QO))


def setup_utilization_scenario():
    """Two STANDARD rooms on 2026-08-05: R-U1 holds COLONO/MAC blocks
    65+65+70=200 min; R-U2 holds 65 (COLONO/MAC) + 50 (EGD/MAC) = 115 min."""
    p_yng = create_patient(mrn="M3101", full_name="Pat Young", date_of_birth="1990-05-05")
    p_old = create_patient(mrn="M3102", full_name="Pat Old", date_of_birth="1961-08-02")
    dr1 = create_provider("Dr One")
    t_col = create_colono_type()
    t_egd = create_egd_type()
    ru1 = create_room(name="R-U1")
    ru2 = create_room(name="R-U2")
    for pat, ptype, room, start in [
        (p_yng, t_col, ru1, "08:00"), (p_yng, t_col, ru1, "09:05"),
        (p_old, t_col, ru1, "10:10"),
        (p_yng, t_col, ru2, "08:00"),
        (p_yng, t_egd, ru2, "09:05"),
    ]:
        create_booking(pat["id"], dr1["id"], ptype["id"], room["id"],
                       scheduled_start=f"2026-08-05T{start}:00Z",
                       indication="SCREENING" if ptype is t_col else "DIAGNOSTIC",
                       anesthesia_type="MAC")
    return {"provider": dr1, "ru1": ru1, "ru2": ru2}


def setup_exposure_scenario():
    """Scope SX usage history for the exposure-window cascade.

    cycle0 dried 2026-08-09T07:31 (expiry 08-12T07:31); culture C0 NEGATIVE
    sampled 08-09T08:00. Usages: U_EDGE ends exactly 08-09T08:00 (== C0 sample),
    U1 ends 08-10T09:00, U2 ends 08-12T09:00, U3 ends 08-14T10:00. Cycle chain
    cya/cyb/cyc keeps the scope storage-current throughout; cyc is the cycle the
    triggering POSITIVE culture will reference.
    """
    pe = create_patient(mrn="M4001", full_name="Pat Expo", date_of_birth="1990-05-05")
    drx = create_provider("Dr Expo")
    t_col = create_colono_type()
    room = create_room(name="R-EXP")
    sx = create_scope(serial_number="SX-1")
    slots = [("2026-08-09T08:30:00Z", "SCREENING"), ("2026-08-10T08:30:00Z", "SCREENING"),
             ("2026-08-12T08:00:00Z", "SURVEILLANCE"), ("2026-08-14T09:00:00Z", "DIAGNOSTIC")]
    bookings = []
    for start, ind in slots:
        b = create_booking(pe["id"], drx["id"], t_col["id"], room["id"],
                           scheduled_start=start, indication=ind)
        confirm_prep(b["id"])
        bookings.append(b)
    b_edge, b1, b2, b3 = bookings

    # cycle0 + NEGATIVE culture C0 sampled 2026-08-09T08:00
    cy0 = run_complete_cycle(sx["id"], "2026-08-09T07:00:00Z", lot="LOT-0",
                             send_first=True)
    advance_clock("2026-08-09T08:00:00Z")
    c0 = create_culture(sx["id"], cy0["id"])
    result_culture(c0["id"], "NEGATIVE")

    # U_EDGE runs entirely at 08:00 (actual_end == C0.sampled_at)
    run_procedure_to_complete(b_edge["id"], drx["id"], sx["id"],
                              "2026-08-09T08:00:00Z", "2026-08-09T08:00:00Z")
    u_edge = first_usage_for_booking(b_edge["id"])
    cya = run_complete_cycle(sx["id"], "2026-08-09T08:30:00Z", lot="LOT-A",
                             booking_id=b_edge["id"])

    # U1 completes 2026-08-10T09:00
    run_procedure_to_complete(b1["id"], drx["id"], sx["id"],
                              "2026-08-10T08:30:00Z", "2026-08-10T09:00:00Z",
                              withdrawal_time_seconds=410)
    u1 = first_usage_for_booking(b1["id"])
    cyb = run_complete_cycle(sx["id"], "2026-08-10T09:30:00Z", lot="LOT-B",
                             booking_id=b1["id"])

    # U2 completes 2026-08-12T09:00
    run_procedure_to_complete(b2["id"], drx["id"], sx["id"],
                              "2026-08-12T08:00:00Z", "2026-08-12T09:00:00Z",
                              withdrawal_time_seconds=420, adenomas_detected=1)
    u2 = first_usage_for_booking(b2["id"])
    cyc = run_complete_cycle(sx["id"], "2026-08-12T09:30:00Z", lot="LOT-C",
                             booking_id=b2["id"])

    # U3 completes exactly 2026-08-14T10:00 (the trigger sample time)
    run_procedure_to_complete(b3["id"], drx["id"], sx["id"],
                              "2026-08-14T09:00:00Z", "2026-08-14T10:00:00Z",
                              withdrawal_time_seconds=430)
    u3 = first_usage_for_booking(b3["id"])
    return {"scope": get_scope(sx["id"]), "provider": drx, "patient": pe,
            "cy0": cy0, "cya": cya, "cyb": cyb, "cyc": cyc, "c0": c0,
            "b_edge": b_edge, "b1": b1, "b2": b2, "b3": b3,
            "u_edge": u_edge, "u1": u1, "u2": u2, "u3": u3}


def setup_two_negative_cultures_scenario():
    """Scope SW with TWO NEGATIVE cultures (N1 08-08T07:30, N2 08-09T08:00) and
    two usages: U_MID ends 08-08T12:00 (after N1, before N2), U_IN ends
    08-09T10:00. cycle cyc (COMPLETE) is the trigger culture's reference."""
    p1 = create_patient(mrn="MRN-EW", full_name="Pat Ew", date_of_birth="1990-05-05")
    dr1 = create_provider("Dr Ew")
    t_col = create_colono_type()
    room = create_room(name="R-EW")
    sw = create_scope(serial_number="SC-EW")
    b_mid = create_booking(p1["id"], dr1["id"], t_col["id"], room["id"],
                           scheduled_start="2026-08-08T08:00:00Z")
    b_in = create_booking(p1["id"], dr1["id"], t_col["id"], room["id"],
                          scheduled_start="2026-08-09T09:00:00Z")
    confirm_prep(b_mid["id"])
    confirm_prep(b_in["id"])
    cya = run_complete_cycle(sw["id"], "2026-08-08T06:30:00Z", lot="LOT-A",
                             send_first=True)
    advance_clock("2026-08-08T07:30:00Z")
    n1 = create_culture(sw["id"], cya["id"])
    result_culture(n1["id"], "NEGATIVE")
    run_procedure_to_complete(b_mid["id"], dr1["id"], sw["id"],
                              "2026-08-08T08:00:00Z", "2026-08-08T12:00:00Z")
    u_mid = first_usage_for_booking(b_mid["id"])
    cyb = run_complete_cycle(sw["id"], "2026-08-08T12:30:00Z", lot="LOT-B",
                             booking_id=b_mid["id"])
    advance_clock("2026-08-09T08:00:00Z")
    n2 = create_culture(sw["id"], cyb["id"])
    result_culture(n2["id"], "NEGATIVE")
    run_procedure_to_complete(b_in["id"], dr1["id"], sw["id"],
                              "2026-08-09T09:00:00Z", "2026-08-09T10:00:00Z",
                              adenomas_detected=1)
    u_in = first_usage_for_booking(b_in["id"])
    cyc = run_complete_cycle(sw["id"], "2026-08-09T10:30:00Z", lot="LOT-C",
                             booking_id=b_in["id"])
    return {"scope": get_scope(sw["id"]), "provider": dr1,
            "cya": cya, "cyb": cyb, "cyc": cyc, "n1": n1, "n2": n2,
            "b_mid": b_mid, "b_in": b_in, "u_mid": u_mid, "u_in": u_in}


def setup_capacity_room_scenario():
    """R-CAP with six COLONO/MAC bookings for a 65-year-old on 2026-08-04:
    blocks of 70 min at 08:00/09:10/10:20/11:30/12:40/13:50 -> 420 committed."""
    p_old = create_patient(mrn="M8201", full_name="Pat Old", date_of_birth="1961-08-02")
    dr1 = create_provider("Dr Cap")
    t_col = create_colono_type()
    room = create_room(name="R-CAP")
    for start in ("08:00", "09:10", "10:20", "11:30", "12:40", "13:50"):
        create_booking(p_old["id"], dr1["id"], t_col["id"], room["id"],
                       scheduled_start=f"2026-08-04T{start}:00Z", anesthesia_type="MAC")
    return {"patient": p_old, "provider": dr1, "ptype": t_col, "room": room}
