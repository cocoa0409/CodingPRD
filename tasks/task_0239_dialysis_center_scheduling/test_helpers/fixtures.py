"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors rather than confusing assertion failures. Every
helper builds its preconditions from scratch — the server starts each test with
an empty database.

Patient OCC threading: booking a session or reserving a standing slot increments
the patient's version by 1 (PRD §2.7). Helpers that perform multiple such writes
re-read the patient version between writes via _patient_version().
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_clinic_payload,
    create_shift_payload,
    create_machine_payload,
    create_station_payload,
    create_patient_payload,
    create_order_payload,
    create_session_payload,
    create_standing_slot_payload,
    create_transport_trip_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["clinic_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]
NEPH = TEST_USERS["nephrologist_headers"]
BILL = TEST_USERS["billing_clerk_headers"]

DEFAULT_CLOCK = "2026-06-01T07:00:00Z"


# ─── Low-level helpers ────────────────────────────────────────────────────
def set_clock(to_iso8601: str = DEFAULT_CLOCK):
    """Set the clinic clock (admin-only test-driving capability)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def _patient_version(patient_id: str) -> int:
    """Re-read the patient's current version for OCC-guarded writes."""
    data = get_success_data(api_client.get_patient(patient_id, SCHED))
    return data["version"]


# ─── Tier 1/2: Inventory + clinic scaffolding ─────────────────────────────
def create_clinic(name="Test Clinic", dialyzer_reuse_limit=None, set_clock_to=DEFAULT_CLOCK):
    """Create an OPEN clinic (optionally with a reuse limit) and set the clock."""
    payload = create_clinic_payload(name=name)
    if dialyzer_reuse_limit is not None:
        payload["dialyzer_reuse_limit"] = dialyzer_reuse_limit
    clinic = get_success_data(api_client.create_clinic(payload, ADMIN))
    if set_clock_to is not None:
        set_clock(set_clock_to)
    return clinic


def create_machine(clinic_id, asset_tag="M1", supports_hdf=False, model="Test Model"):
    return get_success_data(api_client.create_machine(
        create_machine_payload(clinic_id, asset_tag=asset_tag,
                               supports_hdf=supports_hdf, model=model), ADMIN))


def create_station(clinic_id, machine_id, chair_label="C1", isolation_capable=False):
    return get_success_data(api_client.create_station(
        create_station_payload(clinic_id, machine_id, chair_label=chair_label,
                               isolation_capable=isolation_capable), ADMIN))


def create_shift(clinic_id, code="MON_AM", day_pattern="MWF",
                 start_minute=360, end_minute=600, turnover_buffer_minutes=None):
    payload = create_shift_payload(clinic_id, code=code, day_pattern=day_pattern,
                                   start_minute=start_minute, end_minute=end_minute)
    if turnover_buffer_minutes is not None:
        payload["turnover_buffer_minutes"] = turnover_buffer_minutes
    return get_success_data(api_client.create_shift(payload, ADMIN))


def create_patient(clinic_id, mrn="P1", full_name="Test Patient", **overrides):
    return get_success_data(api_client.create_patient(
        create_patient_payload(clinic_id, mrn=mrn, full_name=full_name, **overrides), SCHED))


def create_active_order(patient_id, modality="HEMODIALYSIS",
                        effective_from_date="2026-06-01", **overrides):
    """Create a DRAFT order and activate it. Returns the ACTIVE order."""
    order = get_success_data(api_client.create_order(
        create_order_payload(patient_id, modality=modality,
                             effective_from_date=effective_from_date, **overrides), NEPH))
    return get_success_data(api_client.activate_order(order["id"], NEPH))


def setup_clinic_inventory(clinic_name="Test Clinic", dialyzer_reuse_limit=None,
                           supports_hdf=False, isolation_capable=False,
                           set_clock_to=DEFAULT_CLOCK,
                           day_pattern="MWF", start_minute=360, end_minute=600,
                           turnover_buffer_minutes=None):
    """Active OPEN clinic + one machine + one station + one shift.

    Returns dict: {clinic, machine, station, shift}.
    """
    clinic = create_clinic(name=clinic_name, dialyzer_reuse_limit=dialyzer_reuse_limit,
                           set_clock_to=set_clock_to)
    machine = create_machine(clinic["id"], supports_hdf=supports_hdf)
    station = create_station(clinic["id"], machine["id"], isolation_capable=isolation_capable)
    shift = create_shift(clinic["id"], day_pattern=day_pattern, start_minute=start_minute,
                         end_minute=end_minute, turnover_buffer_minutes=turnover_buffer_minutes)
    return {"clinic": clinic, "machine": machine, "station": station, "shift": shift}


def setup_patient_with_order(clinic_id, modality="HEMODIALYSIS",
                             effective_from_date="2026-06-01",
                             mrn="P1", full_name="Test Patient",
                             order_overrides=None, **patient_overrides):
    """A patient plus one ACTIVE order. Returns (patient, order)."""
    patient = create_patient(clinic_id, mrn=mrn, full_name=full_name, **patient_overrides)
    order = create_active_order(patient["id"], modality=modality,
                                effective_from_date=effective_from_date,
                                **(order_overrides or {}))
    return patient, order


def setup_bookable_scenario(modality="HEMODIALYSIS", dialyzer_reuse_limit=None,
                            supports_hdf=False, isolation_capable=False,
                            payer_class=None, coinsurance_pct=0.0,
                            patient_kind=None, requires_isolation=None,
                            order_overrides=None, set_clock_to=DEFAULT_CLOCK,
                            day_pattern="MWF", start_minute=360, end_minute=600):
    """Full bookable state: OPEN clinic + machine + station + shift + patient + ACTIVE order.

    Returns dict: {clinic, machine, station, shift, patient, order}.
    The patient's version is fresh (no OCC-guarded writes yet).
    """
    inv = setup_clinic_inventory(dialyzer_reuse_limit=dialyzer_reuse_limit,
                                 supports_hdf=supports_hdf,
                                 isolation_capable=isolation_capable,
                                 set_clock_to=set_clock_to,
                                 day_pattern=day_pattern, start_minute=start_minute,
                                 end_minute=end_minute)
    p_overrides = {"coinsurance_pct": coinsurance_pct}
    if payer_class is not None:
        p_overrides["payer_class"] = payer_class
    if patient_kind is not None:
        p_overrides["patient_kind"] = patient_kind
    if requires_isolation is not None:
        p_overrides["requires_isolation"] = requires_isolation
    patient, order = setup_patient_with_order(
        inv["clinic"]["id"], modality=modality,
        order_overrides=order_overrides, **p_overrides)
    return {**inv, "patient": patient, "order": order}


# ─── Tier 3: Session lifecycle shortcuts ──────────────────────────────────
def book_session(scenario, service_date="2026-06-01", station_id=None, shift_id=None,
                 standing_slot_id=None):
    """Book one session against the scenario's patient/order using the live version.

    Returns the BOOKED session. Reads the patient version immediately before the
    booking so the OCC guard passes regardless of prior writes.
    """
    patient = scenario["patient"]
    order = scenario["order"]
    pv = _patient_version(patient["id"])
    payload = create_session_payload(
        patient["id"], order["id"],
        station_id or scenario["station"]["id"],
        shift_id or scenario["shift"]["id"],
        service_date, pv)
    if standing_slot_id is not None:
        payload["standing_slot_id"] = standing_slot_id
    return get_success_data(api_client.create_session(payload, SCHED))


def book_and_check_in(scenario, service_date="2026-06-01"):
    """Book a session and move it to CHECKED_IN. Returns the session."""
    session = book_session(scenario, service_date=service_date)
    return get_success_data(api_client.check_in_session(session["id"], SCHED))


def book_and_complete(scenario, service_date="2026-06-01"):
    """Book → check-in → complete. Returns the COMPLETED session."""
    session = book_session(scenario, service_date=service_date)
    api_client.check_in_session(session["id"], SCHED)
    return get_success_data(api_client.complete_session(session["id"], SCHED))


def book_complete_bill(scenario, service_date="2026-06-01"):
    """Book → check-in → complete → bill. Returns the BILLED session."""
    session = book_and_complete(scenario, service_date=service_date)
    return get_success_data(api_client.bill_session(session["id"], BILL))


def book_and_mark_missed(scenario, service_date="2026-06-01"):
    """Book a session and mark it MISSED. Returns the MISSED session."""
    session = book_session(scenario, service_date=service_date)
    return get_success_data(api_client.mark_missed_session(session["id"], SCHED))


# ─── Tier 4: Threshold / accumulation targeting ───────────────────────────
def setup_reuse_count_at(target_count, dialyzer_reuse_limit):
    """Drive a machine's dialyzer_reuse_count to `target_count` by completing
    that many HEMODIALYSIS sessions, then leave a fresh session CHECKED_IN.

    Returns dict with {clinic, machine, station, patient, order, pending_session}
    where pending_session is a CHECKED_IN session ready to complete. Each prior
    completed session uses a distinct non-overlapping shift on the same date so
    no station-cell or turnover collision occurs.
    """
    assert target_count >= 0
    clinic = create_clinic(name="ReuseClinic", dialyzer_reuse_limit=dialyzer_reuse_limit)
    machine = create_machine(clinic["id"])
    station = create_station(clinic["id"], machine["id"])
    patient = create_patient(clinic["id"], mrn="RP", full_name="Reuse Patient",
                             coinsurance_pct=0.0)
    order = create_active_order(patient["id"])
    scenario = {"clinic": clinic, "machine": machine, "station": station,
                "patient": patient, "order": order}

    # Non-overlapping back-to-back shifts (turnover buffer 0) so all sessions
    # sit on the same station/date without colliding.
    minute = 360
    for i in range(target_count):
        shift = create_shift(clinic["id"], code=f"S{i}", day_pattern="MWF",
                             start_minute=minute, end_minute=minute + 120,
                             turnover_buffer_minutes=0)
        minute += 120
        sess = book_session({**scenario, "shift": shift, "station": station},
                            service_date="2026-06-01", shift_id=shift["id"])
        api_client.check_in_session(sess["id"], SCHED)
        get_success_data(api_client.complete_session(sess["id"], SCHED))

    pending_shift = create_shift(clinic["id"], code="PEND", day_pattern="MWF",
                                 start_minute=minute, end_minute=minute + 120,
                                 turnover_buffer_minutes=0)
    pending = book_session({**scenario, "shift": pending_shift, "station": station},
                           service_date="2026-06-01", shift_id=pending_shift["id"])
    pending = get_success_data(api_client.check_in_session(pending["id"], SCHED))
    return {**scenario, "shift": pending_shift, "pending_session": pending}


def setup_patient_with_n_missed(n, clock="2026-06-12T07:00:00Z",
                                service_dates=None):
    """Create a patient and mark `n` sessions MISSED on distinct in-window dates.

    Returns dict {clinic, machine, station, shift, patient, order, missed: [...]}.
    service_dates defaults to a sequence of MWF dates inside the 30-day window.
    """
    if service_dates is None:
        service_dates = ["2026-06-01", "2026-06-03", "2026-06-05",
                         "2026-06-08", "2026-06-10"][:n]
    assert len(service_dates) >= n
    scenario = setup_bookable_scenario(set_clock_to=clock)
    missed = []
    for d in service_dates[:n]:
        sess = book_session(scenario, service_date=d)
        missed.append(get_success_data(api_client.mark_missed_session(sess["id"], SCHED)))
    return {**scenario, "missed": missed}


# ─── Tier: Cascade / transport scenarios ──────────────────────────────────
def book_with_confirmed_transport(scenario, service_date="2026-06-01", miles=8,
                                   direction="INBOUND", **trip_overrides):
    """Book a session and create + confirm a transport trip on it.

    Returns (session, trip) where the trip is CONFIRMED (fare posted to ledger).
    """
    session = book_session(scenario, service_date=service_date)
    trip = get_success_data(api_client.create_transport_trip(
        create_transport_trip_payload(session["id"], direction=direction,
                                       miles=miles, **trip_overrides), SCHED))
    trip = get_success_data(api_client.confirm_transport_trip(trip["id"], SCHED))
    return session, trip


def reserve_standing_slot(scenario, station_id=None, shift_id=None):
    """Reserve a standing slot for the scenario's patient using the live version.

    Returns the RESERVED standing slot.
    """
    patient = scenario["patient"]
    pv = _patient_version(patient["id"])
    return get_success_data(api_client.create_standing_slot(
        create_standing_slot_payload(
            patient["id"],
            shift_id or scenario["shift"]["id"],
            station_id or scenario["station"]["id"], pv), SCHED))
