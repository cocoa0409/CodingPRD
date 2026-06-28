"""Booking guards: window overlap (clinician buffer vs vehicle zero-buffer),
service-area coverage, vet requirement, euthanasia gates, OCC stale-version, and
stop sequencing.

Queue A — resource_temporal_overlap, cross_entity_state_dependency,
priority_pair_validation_conflict (state-beats-safety). Queue B — validation
corner claims (vet required, euthanasia forbidden), OCC, and sequence ordering.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    make_clinician_headers,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_service_area,
    create_tech,
    create_vet,
    create_van,
    create_patient,
    create_appointment,
    create_route_day,
    book_stop,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# resource_temporal_overlap / clinician_route_buffered_touching_conflict
# ===========================================================================

def test_clinician_buffer_makes_touching_windows_conflict(api):
    """PRD §3.3: "two windows that merely touch end-to-start, with a zero-minute
    gap, therefore do conflict because the buffer is positive. This conflict is
    reported as `ERR_STOP_WINDOW_CONFLICT`."

    On the same RouteDay, a 09:00-10:00 stop and a touching 10:00-11:00 stop
    conflict.

    Design: Difficulty/resource_temporal_overlap/clinician_route_buffered_touching_conflict
    """
    create_service_area(travel_surcharge_cents=0)
    tech = create_tech("Tech Two")
    van = create_van(controlled_stock_ml=0, vaccine_stock_count=5, plate="VAN-14")
    pat1 = create_patient(owner_name="Owner L1", species="DOG", weight_kg=10)
    pat2 = create_patient(owner_name="Owner L2", species="DOG", weight_kg=10)
    appt1 = create_appointment(pat1["id"], visit_type="EXAM",
                               requested_start="2026-02-15T09:00:00Z",
                               requested_end="2026-02-15T10:00:00Z")
    appt2 = create_appointment(pat2["id"], visit_type="EXAM",
                               requested_start="2026-02-15T10:00:00Z",
                               requested_end="2026-02-15T11:00:00Z")
    rd = create_route_day(tech["id"], van["id"], service_date="2026-02-15T00:00:00Z")
    book_stop(rd["id"], appt1["id"], rd["version"],
              window_start="2026-02-15T09:00:00Z", window_end="2026-02-15T10:00:00Z")
    rd_now = validate_success(api.get_route_day(rd["id"], DISPATCHER))
    resp = api.create_stop(
        rd["id"],
        {"appointment_id": appt2["id"],
         "window_start": "2026-02-15T10:00:00Z", "window_end": "2026-02-15T11:00:00Z",
         "expected_route_day_version": rd_now["version"]},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_STOP_WINDOW_CONFLICT.value)


# ===========================================================================
# resource_temporal_overlap / vehicle_zerobuffer_overlap_across_routes
# ===========================================================================

def test_vehicle_double_booked_overlap_across_routes(api):
    """PRD §3.3: "The second is a vehicle double-booking check across any other
    route day that shares the same `rolling_clinic_id` on the same `service_date`,
    applied with a zero buffer: the proposed stop conflicts with such a stop when
    the proposed start falls earlier than the other's end and the other's start
    falls earlier than the proposed end."
    PRD §3.3: "This conflict is reported as `ERR_VEHICLE_DOUBLE_BOOKED`."

    Same van on two RouteDays same date; route-1 has 09:00-10:00, route-2 attempts
    09:30-10:30 (genuine overlap) -> ERR_VEHICLE_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/vehicle_zerobuffer_overlap_across_routes
    """
    create_service_area(travel_surcharge_cents=0)
    techA = create_tech("Tech A")
    techB = create_tech("Tech B")
    van = create_van(controlled_stock_ml=0, vaccine_stock_count=5, plate="VAN-15")
    pat1 = create_patient(owner_name="Owner M1", species="DOG", weight_kg=10)
    pat2 = create_patient(owner_name="Owner M2", species="DOG", weight_kg=10)
    appt1 = create_appointment(pat1["id"], visit_type="EXAM",
                               requested_start="2026-02-16T09:00:00Z",
                               requested_end="2026-02-16T10:00:00Z")
    appt2 = create_appointment(pat2["id"], visit_type="EXAM",
                               requested_start="2026-02-16T09:30:00Z",
                               requested_end="2026-02-16T10:30:00Z")
    rd1 = create_route_day(techA["id"], van["id"], service_date="2026-02-16T00:00:00Z")
    book_stop(rd1["id"], appt1["id"], rd1["version"],
              window_start="2026-02-16T09:00:00Z", window_end="2026-02-16T10:00:00Z")
    rd2 = create_route_day(techB["id"], van["id"], service_date="2026-02-16T00:00:00Z")
    resp = api.create_stop(
        rd2["id"],
        {"appointment_id": appt2["id"],
         "window_start": "2026-02-16T09:30:00Z", "window_end": "2026-02-16T10:30:00Z",
         "expected_route_day_version": rd2["version"]},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_VEHICLE_DOUBLE_BOOKED.value)


# ===========================================================================
# cross_entity_state_dependency / stop_booking_requires_active_service_area
# ===========================================================================

def test_booking_rejected_when_service_area_suspended(api):
    """PRD §3.3: "The appointment's resolved service area — found from the patient's
    `home_zip` — must be `ACTIVE`, or the booking is refused with
    `ERR_AREA_NOT_COVERED`."

    Booking a stop for a patient whose ZIP resolves to a SUSPENDED area ->
    ERR_AREA_NOT_COVERED.

    Design: Difficulty/cross_entity_state_dependency/stop_booking_requires_active_service_area
    """
    area = create_service_area(zip_code="11201", travel_surcharge_cents=0)
    validate_success(api.suspend_service_area(area["id"], DISPATCHER))
    tech = create_tech("Tech Tory")
    van = create_van(controlled_stock_ml=0, vaccine_stock_count=5, plate="VAN-13")
    pat = create_patient(owner_name="Owner J", species="DOG", weight_kg=22, home_zip="11201")
    appt = create_appointment(pat["id"], visit_type="EXAM",
                              requested_start="2026-02-13T09:00:00Z",
                              requested_end="2026-02-13T10:00:00Z")
    rd = create_route_day(tech["id"], van["id"], service_date="2026-02-13T00:00:00Z")
    resp = api.create_stop(
        rd["id"],
        {"appointment_id": appt["id"],
         "window_start": "2026-02-13T09:00:00Z", "window_end": "2026-02-13T10:00:00Z",
         "expected_route_day_version": rd["version"]},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_AREA_NOT_COVERED.value)


# ===========================================================================
# cross_entity_state_dependency / estimate_approve_requires_appointment_visit_phase
# ===========================================================================

def test_estimate_approve_requires_appointment_in_visit_phase(api):
    """PRD §3.4: "approval is only allowed while the linked appointment is in
    `SCHEDULED` or `IN_VISIT`, and otherwise fails with
    `ERR_APPT_NOT_IN_VISIT_PHASE`."

    Approving a DRAFT estimate whose appointment is still REQUESTED (unbooked) ->
    ERR_APPT_NOT_IN_VISIT_PHASE.

    Design: Difficulty/cross_entity_state_dependency/estimate_approve_requires_appointment_visit_phase
    """
    create_service_area(zip_code="11201", travel_surcharge_cents=0)
    pat = create_patient(owner_name="Owner K", species="CAT", weight_kg=4, home_zip="11201")
    tech = create_tech("Tech Tj")
    appt = create_appointment(pat["id"], visit_type="EXAM",
                              requested_start="2026-02-14T09:00:00Z",
                              requested_end="2026-02-14T10:00:00Z")
    clin = make_clinician_headers(tech["id"])
    est = validate_success(
        api.create_estimate(
            {"appointment_id": appt["id"],
             "line_items": [{"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1}]},
            clin,
        ),
        expected_status=201,
    )
    resp = api.approve_estimate(est["id"], clin)
    validate_error(resp, ApiErrorId.ERR_APPT_NOT_IN_VISIT_PHASE.value)


# ===========================================================================
# priority_pair_validation_conflict / state_beats_safety_on_euthanasia_booking
# ===========================================================================

def test_state_check_precedes_euthanasia_permission_on_rebooking(api):
    """PRD §2.6: "Only after these three gates does the server consider domain rules
    — state legality, route posture, area coverage, safety, scheduling, stock,
    fiscal, concurrency, and finally body well-formedness."
    PRD §3.3: "This single operation drives the appointment from `REQUESTED` to
    `SCHEDULED` and is gated by a layered set of preconditions."

    An already-SCHEDULED euthanasia appointment re-booked into a second route fails
    the state check (ERR_INVALID_STATE) before the euthanasia-permission check,
    because state legality outranks the safety gate.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_euthanasia_booking
    """
    create_service_area(zip_code="11201", name="Allowed", travel_surcharge_cents=0,
                        euthanasia_allowed=True)
    # second area exists but is irrelevant to the booked patient's ZIP
    create_service_area(zip_code="11215", name="Forbidden", travel_surcharge_cents=0,
                        euthanasia_allowed=False)
    vet = create_vet(full_name="Dr Vet C", dea_number="CV1112223")
    van = create_van(controlled_stock_ml=50, vaccine_stock_count=0, plate="VAN-9")
    pat = create_patient(owner_name="Owner G", species="DOG", weight_kg=25, home_zip="11201")
    appt = create_appointment(pat["id"], visit_type="EUTHANASIA",
                              requested_start="2026-02-08T09:00:00Z",
                              requested_end="2026-02-08T10:00:00Z")
    rd1 = create_route_day(vet["id"], van["id"], service_date="2026-02-08T00:00:00Z")
    book_stop(rd1["id"], appt["id"], rd1["version"],
              window_start="2026-02-08T09:00:00Z", window_end="2026-02-08T10:00:00Z")
    rd2 = create_route_day(vet["id"], van["id"], service_date="2026-02-09T00:00:00Z")
    resp = api.create_stop(
        rd2["id"],
        {"appointment_id": appt["id"],
         "window_start": "2026-02-09T09:00:00Z", "window_end": "2026-02-09T10:00:00Z",
         "expected_route_day_version": rd2["version"]},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner / validations / vet_required_for_euthanasia_booking
# ===========================================================================

def test_euthanasia_booking_requires_vet_lead(api):
    """PRD §3.3: "additionally the route day's clinician must have a
    `clinician_role` of `VET`, or the booking is refused with `ERR_VET_REQUIRED`."

    Booking a EUTHANASIA appointment onto a TECH-led route -> ERR_VET_REQUIRED.

    Design: Corner/validations/vet_required_for_euthanasia_booking
    """
    create_service_area(zip_code="11201", travel_surcharge_cents=0, euthanasia_allowed=True)
    tech = create_tech("Tech Ti")
    van = create_van(controlled_stock_ml=50, vaccine_stock_count=0, plate="VAN-29")
    pat = create_patient(owner_name="Owner L3", species="DOG", weight_kg=25, home_zip="11201")
    appt = create_appointment(pat["id"], visit_type="EUTHANASIA",
                              requested_start="2026-03-16T09:00:00Z",
                              requested_end="2026-03-16T10:00:00Z")
    rd = create_route_day(tech["id"], van["id"], service_date="2026-03-16T00:00:00Z")
    resp = api.create_stop(
        rd["id"],
        {"appointment_id": appt["id"],
         "window_start": "2026-03-16T09:00:00Z", "window_end": "2026-03-16T10:00:00Z",
         "expected_route_day_version": rd["version"]},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_VET_REQUIRED.value)


# ===========================================================================
# Corner / validations / euthanasia_forbidden_area_blocks_booking
# ===========================================================================

def test_euthanasia_forbidden_area_blocks_booking(api):
    """PRD §3.3: "If the visit is an `EUTHANASIA`, that service area's
    `euthanasia_allowed` must be true, or the booking is refused with
    `ERR_EUTHANASIA_NOT_PERMITTED`."

    Booking a EUTHANASIA appointment in an area with euthanasia_allowed==false
    (VET-led route) -> ERR_EUTHANASIA_NOT_PERMITTED.

    Design: Corner/validations/euthanasia_forbidden_area_blocks_booking
    """
    create_service_area(zip_code="11215", name="No-Euth", travel_surcharge_cents=0,
                        euthanasia_allowed=False)
    vet = create_vet(full_name="Dr Vet L", dea_number="LV0001112")
    van = create_van(controlled_stock_ml=50, vaccine_stock_count=0, plate="VAN-32")
    pat = create_patient(owner_name="Owner O3", species="DOG", weight_kg=22, home_zip="11215")
    appt = create_appointment(pat["id"], visit_type="EUTHANASIA",
                              requested_start="2026-03-19T09:00:00Z",
                              requested_end="2026-03-19T10:00:00Z")
    rd = create_route_day(vet["id"], van["id"], service_date="2026-03-19T00:00:00Z")
    resp = api.create_stop(
        rd["id"],
        {"appointment_id": appt["id"],
         "window_start": "2026-03-19T09:00:00Z", "window_end": "2026-03-19T10:00:00Z",
         "expected_route_day_version": rd["version"]},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_EUTHANASIA_NOT_PERMITTED.value)


# ===========================================================================
# Corner / cross_cutting / occ_stale_route_day_version_on_stop_create
# ===========================================================================

def test_stale_route_day_version_rejected(api):
    """PRD §2.9: "If that value does not equal the route day's current `version`,
    the booking is rejected with `ERR_STALE_ROUTE_DAY_VERSION` and HTTP 412."
    PRD §2.9: "each successful booking legitimately advances the route day's
    `version` and re-sequences the route; a second booking still carrying the older
    version is working from an out-of-date picture of the route's stop set and
    capacity, and is refused rather than allowed to overwrite a state it never saw."

    After one successful stop create bumps version 1->2, a second create still
    carrying expected_route_day_version=1 -> ERR_STALE_ROUTE_DAY_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_route_day_version_on_stop_create
    """
    create_service_area(travel_surcharge_cents=0)
    tech = create_tech("Tech To")
    van = create_van(controlled_stock_ml=0, vaccine_stock_count=5, plate="VAN-37")
    pat1 = create_patient(owner_name="Owner V3", species="DOG", weight_kg=10)
    pat2 = create_patient(owner_name="Owner V4", species="DOG", weight_kg=10)
    appt1 = create_appointment(pat1["id"], visit_type="EXAM",
                               requested_start="2026-03-26T09:00:00Z",
                               requested_end="2026-03-26T10:00:00Z")
    appt2 = create_appointment(pat2["id"], visit_type="EXAM",
                               requested_start="2026-03-26T13:00:00Z",
                               requested_end="2026-03-26T14:00:00Z")
    rd = create_route_day(tech["id"], van["id"], service_date="2026-03-26T00:00:00Z")
    stale_version = rd["version"]
    book_stop(rd["id"], appt1["id"], stale_version,
              window_start="2026-03-26T09:00:00Z", window_end="2026-03-26T10:00:00Z")
    # second create still carries the now-stale version
    resp = api.create_stop(
        rd["id"],
        {"appointment_id": appt2["id"],
         "window_start": "2026-03-26T13:00:00Z", "window_end": "2026-03-26T14:00:00Z",
         "expected_route_day_version": stale_version},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ROUTE_DAY_VERSION.value)


# ===========================================================================
# Corner / cross_cutting / occ_correct_version_succeeds_and_bumps
# ===========================================================================

def test_correct_route_day_version_succeeds_and_bumps_version(api):
    """PRD §3.3: "A successful booking creates the route stop in `PLANNED` status,
    advances the appointment to `SCHEDULED`, recomputes the route day's
    `stop_count`, recomputes the `sequence` of every stop on the route, and
    increments the route day's `version` by 1."

    With one stop booked (version now 2), a second booking carrying version 2
    succeeds and bumps version to 3, with stop_count 2.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
    """
    create_service_area(travel_surcharge_cents=0)
    tech = create_tech("Tech Tp")
    van = create_van(controlled_stock_ml=0, vaccine_stock_count=5, plate="VAN-38")
    pat1 = create_patient(owner_name="Owner W3", species="DOG", weight_kg=10)
    pat2 = create_patient(owner_name="Owner W4", species="DOG", weight_kg=10)
    appt1 = create_appointment(pat1["id"], visit_type="EXAM",
                               requested_start="2026-03-27T09:00:00Z",
                               requested_end="2026-03-27T10:00:00Z")
    appt2 = create_appointment(pat2["id"], visit_type="EXAM",
                               requested_start="2026-03-27T13:00:00Z",
                               requested_end="2026-03-27T14:00:00Z")
    rd = create_route_day(tech["id"], van["id"], service_date="2026-03-27T00:00:00Z")
    book_stop(rd["id"], appt1["id"], rd["version"],
              window_start="2026-03-27T09:00:00Z", window_end="2026-03-27T10:00:00Z")
    rd2 = validate_success(api.get_route_day(rd["id"], DISPATCHER))
    validate_success(
        api.create_stop(
            rd["id"],
            {"appointment_id": appt2["id"],
             "window_start": "2026-03-27T13:00:00Z", "window_end": "2026-03-27T14:00:00Z",
             "expected_route_day_version": rd2["version"]},
            DISPATCHER,
        ),
        expected_status=201,
    )
    rd3 = validate_success(api.get_route_day(rd["id"], DISPATCHER))
    assert rd3["version"] == 3, f"version should reach 3 after two bookings, got {rd3['version']}"
    assert rd3["stop_count"] == 2


# ===========================================================================
# Corner / calculations / assign_stop_sequence_orders_by_window_start
# ===========================================================================

def test_stop_sequence_orders_by_window_start(api):
    """PRD §3.3: "The `sequence` is a one-based ordinal assigned across all
    non-`SKIPPED` stops on the route, ordered by `window_start` ascending and, where
    two windows start at the same instant, by `created_at` ascending — never by
    `id`."

    Book an 11:00 stop then a 09:00 stop: the 09:00 stop gets sequence 1, the 11:00
    stop gets 2.

    Design: Corner/calculations/assign_stop_sequence_orders_by_window_start
    """
    create_service_area(travel_surcharge_cents=0)
    tech = create_tech("Tech Th")
    van = create_van(controlled_stock_ml=0, vaccine_stock_count=5, plate="VAN-27")
    pat1 = create_patient(owner_name="Owner J1", species="DOG", weight_kg=10)
    pat2 = create_patient(owner_name="Owner J2", species="DOG", weight_kg=10)
    appt1 = create_appointment(pat1["id"], visit_type="EXAM",
                               requested_start="2026-03-14T11:00:00Z",
                               requested_end="2026-03-14T12:00:00Z")
    appt2 = create_appointment(pat2["id"], visit_type="EXAM",
                               requested_start="2026-03-14T09:00:00Z",
                               requested_end="2026-03-14T10:00:00Z")
    rd = create_route_day(tech["id"], van["id"], service_date="2026-03-14T00:00:00Z")
    stop1 = book_stop(rd["id"], appt1["id"], rd["version"],
                      window_start="2026-03-14T11:00:00Z", window_end="2026-03-14T12:00:00Z")
    rd2 = validate_success(api.get_route_day(rd["id"], DISPATCHER))
    stop2 = book_stop(rd["id"], appt2["id"], rd2["version"],
                      window_start="2026-03-14T09:00:00Z", window_end="2026-03-14T10:00:00Z")
    s2 = validate_success(api.get_route_stop(stop2["id"], DISPATCHER))
    s1 = validate_success(api.get_route_stop(stop1["id"], DISPATCHER))
    assert s2["sequence"] == 1, f"09:00 stop should be sequence 1, got {s2['sequence']}"
    assert s1["sequence"] == 2, f"11:00 stop should be sequence 2, got {s1['sequence']}"
