"""Composite setup helpers for the Vehicle Safety & Emissions Inspection API.

Every test starts against an empty database (the harness restarts the server
before each test), so each fixture builds its preconditions from scratch using
only PRD-declared endpoints. Fixtures use get_success_data() internally so a
broken setup surfaces as a clear "Setup step failed" error.

Naming uses PRD domain language. All callers pass the session ApiClient.
"""
from prd_bench_local_runner.testing import get_success_data

from .factories import (
    create_station_payload,
    create_vehicle_class_profile_payload,
    create_lane_payload,
    create_appointment_payload,
    create_inspection_record_payload,
    create_checklist_result_payload,
    create_emissions_test_payload,
    create_repair_order_payload,
    create_waiver_request_payload,
    create_certificate_payload,
    create_state_report_batch_payload,
    attach_line_payload,
    clock_payload,
)
from .test_users import TEST_USERS

SM = TEST_USERS["station_manager_headers"]
INSP = TEST_USERS["inspector_headers"]
RECEP = TEST_USERS["receptionist_headers"]
AUDITOR = TEST_USERS["state_auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + bootstrap config
# ---------------------------------------------------------------------------
def set_clock(api, iso: str):
    """Set the server logical clock (StationManager-only)."""
    return get_success_data(api.set_clock(clock_payload(iso), SM))


def create_station(api, **overrides):
    """Create a Station. Returns the station dict."""
    return get_success_data(api.create_station(create_station_payload(**overrides), SM))


def create_profile(api, station_id, **overrides):
    """Create a VehicleClassProfile under a station. Returns the profile dict."""
    return get_success_data(
        api.create_vehicle_class_profile(
            create_vehicle_class_profile_payload(station_id, **overrides), SM
        )
    )


def create_lane(api, station_id, **overrides):
    """Create a Lane under a station. Returns the lane dict."""
    return get_success_data(api.create_lane(create_lane_payload(station_id, **overrides), SM))


def setup_station_with_passenger_obd(api, clock_iso="2026-06-10T09:00:00Z",
                                     buffer_minutes=0, repair_cost_limit_cents=60000,
                                     base_fee_cents=2500, checklist_item_count=2,
                                     reinspection_window_days=30):
    """Station + PASSENGER profile (obd_required=True) + one OBD lane, clock set.

    Returns (station, profile, lane).
    """
    station = create_station(api, repair_cost_limit_cents=repair_cost_limit_cents)
    profile = create_profile(
        api, station["id"], vehicle_class="PASSENGER", base_fee_cents=base_fee_cents,
        obd_required=True, checklist_item_count=checklist_item_count,
        reinspection_window_days=reinspection_window_days,
    )
    lane = create_lane(api, station["id"], lane_number=1, supports_obd=True,
                       turnaround_buffer_minutes=buffer_minutes)
    if clock_iso is not None:
        set_clock(api, clock_iso)
    return station, profile, lane


def setup_station_with_motorcycle_no_obd(api, clock_iso="2026-06-10T09:00:00Z",
                                         base_fee_cents=1500, checklist_item_count=1,
                                         reinspection_window_days=30):
    """Station + MOTORCYCLE profile (obd_required=False) + one non-OBD lane.

    Returns (station, profile, lane).
    """
    station = create_station(api)
    profile = create_profile(
        api, station["id"], vehicle_class="MOTORCYCLE", base_fee_cents=base_fee_cents,
        obd_required=False, checklist_item_count=checklist_item_count,
        reinspection_window_days=reinspection_window_days,
    )
    lane = create_lane(api, station["id"], lane_number=1, supports_obd=False,
                       turnaround_buffer_minutes=0)
    if clock_iso is not None:
        set_clock(api, clock_iso)
    return station, profile, lane


# ---------------------------------------------------------------------------
# Tier 1: appointment lifecycle
# ---------------------------------------------------------------------------
def book_appointment(api, lane_id, **overrides):
    """Book an appointment on a lane. Returns the appointment dict."""
    return get_success_data(api.create_appointment(create_appointment_payload(lane_id, **overrides), RECEP))


def book_and_check_in(api, lane_id, **overrides):
    """Book then check-in an appointment. Returns the CHECKED_IN appointment dict."""
    appt = book_appointment(api, lane_id, **overrides)
    return get_success_data(api.check_in_appointment(appt["id"], RECEP))


# ---------------------------------------------------------------------------
# Tier 2: opening + conducting an inspection
# ---------------------------------------------------------------------------
def open_record(api, appointment_id, **overrides):
    """Open an InspectionRecord by consuming a CHECKED_IN appointment.

    Returns the IN_PROGRESS record dict.
    """
    return get_success_data(
        api.create_inspection_record(
            create_inspection_record_payload(appointment_id, **overrides), INSP
        )
    )


def add_checklist(api, record_id, item_code="BRAKES", outcome="PASS", **overrides):
    return get_success_data(
        api.create_checklist_result(
            create_checklist_result_payload(record_id, item_code=item_code,
                                            outcome=outcome, **overrides), INSP
        )
    )


def add_emissions(api, record_id, **overrides):
    return get_success_data(
        api.create_emissions_test(create_emissions_test_payload(record_id, **overrides), INSP)
    )


def setup_in_progress_passenger_record(api, clock_iso="2026-06-10T09:00:00Z",
                                       checklist_item_count=2, **station_overrides):
    """Full path to a PASSENGER+OBD IN_PROGRESS record (no checklist/emissions yet).

    Returns (station, profile, lane, appointment, record).
    """
    station, profile, lane = setup_station_with_passenger_obd(
        api, clock_iso=clock_iso, checklist_item_count=checklist_item_count, **station_overrides
    )
    appt = book_and_check_in(api, lane["id"])
    record = open_record(api, appt["id"])
    return station, profile, lane, appt, record


def decide_record(api, record_id):
    """Run the pass/fail decision. Returns the decided record dict."""
    return get_success_data(api.decide_inspection_record(record_id, INSP))


def setup_decided_passenger_record(api, safety_pass=True, emissions_pass=True,
                                   clock_iso="2026-06-10T09:00:00Z",
                                   **station_overrides):
    """Walk a PASSENGER+OBD record to a frozen PASSED/FAILED decision.

    - safety_pass: when False, one checklist item is FAIL (safety_result FAIL).
    - emissions_pass: when False, the emissions test has mil_on=True (FAIL).

    Returns (station, profile, lane, appointment, decided_record).
    """
    station, profile, lane, appt, record = setup_in_progress_passenger_record(
        api, clock_iso=clock_iso, **station_overrides
    )
    add_checklist(api, record["id"], item_code="BRAKES",
                  outcome="PASS" if safety_pass else "FAIL",
                  severity="MAJOR")
    add_checklist(api, record["id"], item_code="LIGHTS", outcome="PASS")
    add_emissions(api, record["id"], mil_on=not emissions_pass,
                  dtc_count=0 if emissions_pass else 3)
    decided = decide_record(api, record["id"])
    return station, profile, lane, appt, decided


def setup_passed_passenger_record(api, clock_iso="2026-06-10T09:00:00Z", **station_overrides):
    """A PASSENGER+OBD record frozen to PASSED.

    Returns (station, profile, lane, appointment, passed_record).
    """
    return setup_decided_passenger_record(
        api, safety_pass=True, emissions_pass=True, clock_iso=clock_iso, **station_overrides
    )


def setup_failed_emissions_record(api, clock_iso="2026-06-10T09:00:00Z",
                                  repair_cost_limit_cents=60000, **station_overrides):
    """A PASSENGER+OBD record FAILED on emissions (mil_on=True), safety passing.

    Returns (station, profile, lane, appointment, failed_record).
    """
    return setup_decided_passenger_record(
        api, safety_pass=True, emissions_pass=False, clock_iso=clock_iso,
        repair_cost_limit_cents=repair_cost_limit_cents, **station_overrides
    )


def setup_safety_failed_record(api, clock_iso="2026-06-10T09:00:00Z", **station_overrides):
    """A PASSENGER+OBD record FAILED on safety (one checklist FAIL), emissions PASS.

    Returns (station, profile, lane, appointment, failed_record).
    """
    return setup_decided_passenger_record(
        api, safety_pass=False, emissions_pass=True, clock_iso=clock_iso, **station_overrides
    )


# ---------------------------------------------------------------------------
# Tier 3: repair orders / waivers
# ---------------------------------------------------------------------------
def submit_repair_order(api, record_id, **overrides):
    return get_success_data(
        api.create_repair_order(create_repair_order_payload(record_id, **overrides), RECEP)
    )


def submit_and_verify_repair(api, record_id, documented_cost_cents=0,
                             estimated_cost_cents=0, emissions_related=True, shop_name="Test Auto"):
    """Submit a repair order then verify it. Returns the VERIFIED order dict."""
    ro = submit_repair_order(api, record_id, shop_name=shop_name,
                             documented_cost_cents=documented_cost_cents,
                             estimated_cost_cents=estimated_cost_cents,
                             emissions_related=emissions_related)
    return get_success_data(api.verify_repair_order(ro["id"], SM))


def request_waiver(api, record_id, cost_basis="DOCUMENTED_ONLY"):
    return get_success_data(
        api.create_waiver_request(create_waiver_request_payload(record_id, cost_basis=cost_basis), RECEP)
    )


# ---------------------------------------------------------------------------
# Tier 4: certificates
# ---------------------------------------------------------------------------
def issue_certificate(api, record_id, expected_record_version):
    """Issue a certificate for a PASSED record. Returns the certificate dict."""
    return get_success_data(
        api.create_certificate(
            create_certificate_payload(record_id, expected_record_version), SM
        )
    )


def setup_passed_record_with_certificate(api, clock_iso="2026-06-10T09:00:00Z", **station_overrides):
    """A PASSED PASSENGER+OBD record with an ACTIVE Certificate already issued.

    Returns (station, profile, lane, appointment, passed_record, certificate).
    """
    station, profile, lane, appt, passed = setup_passed_passenger_record(
        api, clock_iso=clock_iso, **station_overrides
    )
    cert = issue_certificate(api, passed["id"], passed["version"])
    return station, profile, lane, appt, passed, cert


# ---------------------------------------------------------------------------
# Tier 5: state report batches + lines
# ---------------------------------------------------------------------------
def open_batch(api, station_id, period_label="2026-06"):
    return get_success_data(
        api.create_state_report_batch(create_state_report_batch_payload(station_id, period_label=period_label), SM)
    )


def attach_line(api, batch_id, record_id):
    """Attach a terminal record to an OPEN batch as a line. Returns the line dict."""
    return get_success_data(api.attach_state_report_line(batch_id, attach_line_payload(record_id), SM))


def setup_open_batch_with_line(api, clock_iso="2026-06-10T09:00:00Z",
                               record_safety_pass=False, record_emissions_pass=True,
                               **station_overrides):
    """A station with one terminal record attached as a line to an OPEN batch.

    By default the record is safety-FAILED (terminal, fee 3700). Returns
    (station, record, batch, line).
    """
    station, profile, lane, appt, record = setup_decided_passenger_record(
        api, safety_pass=record_safety_pass, emissions_pass=record_emissions_pass,
        clock_iso=clock_iso, **station_overrides
    )
    batch = open_batch(api, station["id"])
    line = attach_line(api, batch["id"], record["id"])
    fresh_batch = get_success_data(api.get_state_report_batch(batch["id"], SM))
    return station, record, fresh_batch, line


def setup_submitted_batch(api, clock_iso="2026-06-10T09:00:00Z", **station_overrides):
    """A batch driven OPEN -> SUBMITTED with one attached line.

    Returns (station, record, batch_after_submit).
    """
    station, record, batch, line = setup_open_batch_with_line(
        api, clock_iso=clock_iso, **station_overrides
    )
    submitted = get_success_data(
        api.submit_state_report_batch(batch["id"], {"expected_batch_version": batch["version"]}, SM)
    )
    return station, record, submitted


def setup_rejected_batch(api, clock_iso="2026-06-10T09:00:00Z", **station_overrides):
    """A batch driven OPEN -> SUBMITTED -> REJECTED.

    Returns (station, record, batch_after_reject).
    """
    station, record, submitted = setup_submitted_batch(api, clock_iso=clock_iso, **station_overrides)
    rejected = get_success_data(
        api.decide_state_report_batch(submitted["id"], {"decision": "REJECT"}, AUDITOR)
    )
    return station, record, rejected


def setup_accepted_batch(api, clock_iso="2026-06-10T09:00:00Z", **station_overrides):
    """A batch driven OPEN -> SUBMITTED -> ACCEPTED (terminal).

    Returns (station, record, batch_after_accept).
    """
    station, record, submitted = setup_submitted_batch(api, clock_iso=clock_iso, **station_overrides)
    accepted = get_success_data(
        api.decide_state_report_batch(submitted["id"], {"decision": "ACCEPT"}, AUDITOR)
    )
    return station, record, accepted


# ---------------------------------------------------------------------------
# Tier 6: reinspection chains
# ---------------------------------------------------------------------------
def reinspect(api, source_record_id, reinspection_appointment_id):
    """Open a fresh reinspection record from a FAILED/PASSED record.

    Returns the new IN_PROGRESS record dict.
    """
    return get_success_data(
        api.reinspect_inspection_record(
            source_record_id, {"reinspection_appointment_id": reinspection_appointment_id}, INSP
        )
    )


def add_reinspection_appointment(api, lane_id, scheduled_start, scheduled_end, vin=None):
    """Book + check-in an appointment for a reinspection visit. Returns it CHECKED_IN."""
    overrides = {"scheduled_start": scheduled_start, "scheduled_end": scheduled_end}
    if vin is not None:
        overrides["vehicle_vin"] = vin
    return book_and_check_in(api, lane_id, **overrides)


def setup_failed_then_reinspected_chain_at_index(api, target_index,
                                                 clock_iso="2026-06-10T08:00:00Z"):
    """Build a reinspection chain whose current FAILED record sits at target_index.

    All records in the chain FAIL on safety; each reinspection consumes a fresh
    CHECKED_IN appointment booked on the hour. Returns the list of record dicts
    (index 0 = chain head, ... index target_index = current FAILED record).
    """
    station, profile, lane = setup_station_with_passenger_obd(api, clock_iso=clock_iso)
    records = []

    # chain head (index 0)
    appt0 = book_and_check_in(api, lane["id"],
                              scheduled_start="2026-06-10T09:00:00Z",
                              scheduled_end="2026-06-10T09:30:00Z")
    head = open_record(api, appt0["id"])
    add_checklist(api, head["id"], item_code="BRAKES", outcome="FAIL", severity="MAJOR")
    add_checklist(api, head["id"], item_code="LIGHTS", outcome="PASS")
    add_emissions(api, head["id"], mil_on=False, dtc_count=0)
    head = decide_record(api, head["id"])
    records.append(head)

    hours = ["10", "11", "12", "13"]
    current_id = head["id"]
    for i in range(1, target_index + 1):
        appt = add_reinspection_appointment(
            api, lane["id"],
            scheduled_start=f"2026-06-10T{hours[i - 1]}:00:00Z",
            scheduled_end=f"2026-06-10T{hours[i - 1]}:30:00Z",
        )
        new_rec = reinspect(api, current_id, appt["id"])
        add_checklist(api, new_rec["id"], item_code="BRAKES", outcome="FAIL", severity="MAJOR")
        add_checklist(api, new_rec["id"], item_code="LIGHTS", outcome="PASS")
        add_emissions(api, new_rec["id"], mil_on=False, dtc_count=0)
        new_rec = decide_record(api, new_rec["id"])
        records.append(new_rec)
        current_id = new_rec["id"]

    return station, profile, lane, records
