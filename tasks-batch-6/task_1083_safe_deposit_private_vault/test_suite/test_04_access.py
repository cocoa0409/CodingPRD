"""Appointments, room capacity, dual-control events, and access-gate priority
(Difficulty queue A) plus access-grant corner cases (Corner queue B).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    assert_access_event,
)
from test_helpers import factories as F
from test_helpers import fixtures as X

ADMIN = TEST_USERS["vault_admin_headers"]
OFFICER = TEST_USERS["vault_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / box_appointment_overlap_half_open
# ---------------------------------------------------------------------------
def test_overlapping_appointment_on_same_box_rejected(api):
    """PRD §3.7: "the window must not overlap another `BOOKED` or `CHECKED_IN`
    appointment on the same box (half-open comparison), else
    `ERR_APPOINTMENT_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/box_appointment_overlap_half_open
    """
    ctx = X.setup_active_rental_with_booked_appointment(api)  # [10:00,11:00)
    resp = api.create_appointment(
        F.create_appointment_payload(ctx["box"]["id"], ctx["rental"]["id"],
                                     "2026-05-02T10:30:00Z", "2026-05-02T11:30:00Z"), OFFICER)
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_OVERLAP.value, 409)


def test_adjacent_appointment_on_same_box_accepted(api):
    """PRD §3.7: "the window's `scheduled_start` and `scheduled_end` (a half-open
    interval that includes the start and excludes the end)". PRD §3.7: "the
    window must not overlap another `BOOKED` or `CHECKED_IN` appointment on the
    same box (half-open comparison), else `ERR_APPOINTMENT_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/box_appointment_overlap_half_open
    """
    ctx = X.setup_active_rental_with_booked_appointment(api)  # [10:00,11:00)
    data = validate_success(api.create_appointment(
        F.create_appointment_payload(ctx["box"]["id"], ctx["rental"]["id"],
                                     "2026-05-02T11:00:00Z", "2026-05-02T12:00:00Z"), OFFICER), 201)
    assert data["status"] == "BOOKED"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / branch_room_capacity_buffered
# ---------------------------------------------------------------------------
def test_room_capacity_exceeded_via_cleanup_buffer(api):
    """PRD §3.7: "The room-capacity test is a buffered aggregate: for the
    candidate window, count the existing appointments at the same branch in
    `BOOKED` or `CHECKED_IN` whose window, widened by a 30-minute cleanup buffer
    on each side, intersects the candidate window; if that count plus one would
    exceed the branch's `viewing_room_capacity`, booking is refused."

    Design: Difficulty/resource_temporal_overlap/branch_room_capacity_buffered
    """
    ctx = X.setup_two_active_rentals(api, capacity=1)
    X.book_appointment(api, ctx["box1"]["id"], ctx["rental1"]["id"],
                       "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")
    # box1 buffered → [09:30,11:30) intersects [11:15,12:00) → capacity 1 exceeded
    resp = api.create_appointment(
        F.create_appointment_payload(ctx["box2"]["id"], ctx["rental2"]["id"],
                                     "2026-05-02T11:15:00Z", "2026-05-02T12:00:00Z"), OFFICER)
    validate_error(resp, ApiErrorId.ERR_ROOM_CAPACITY_EXCEEDED.value, 409)


def test_room_capacity_ok_when_outside_buffer(api):
    """PRD §3.7: "count the existing appointments at the same branch in `BOOKED`
    or `CHECKED_IN` whose window, widened by a 30-minute cleanup buffer on each
    side, intersects the candidate window; if that count plus one would exceed
    the branch's `viewing_room_capacity`, booking is refused."

    Design: Difficulty/resource_temporal_overlap/branch_room_capacity_buffered
    """
    ctx = X.setup_two_active_rentals(api, capacity=1)
    X.book_appointment(api, ctx["box1"]["id"], ctx["rental1"]["id"],
                       "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")
    # box1 buffered → [09:30,11:30); candidate [11:45,12:30) does not intersect → allowed
    data = validate_success(api.create_appointment(
        F.create_appointment_payload(ctx["box2"]["id"], ctx["rental2"]["id"],
                                     "2026-05-02T11:45:00Z", "2026-05-02T12:30:00Z"), OFFICER), 201)
    assert data["status"] == "BOOKED"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / dual_control_witness_count_boundary
# ---------------------------------------------------------------------------
def test_access_event_with_single_witness_rejected(api):
    """PRD §3.7: "Dual control requires the officer to differ from the accessor
    and the witness count to be at least the required two witnesses; a
    `witness_count` of exactly 2 passes while a count of 1 fails, and any
    violation yields `ERR_DUAL_CONTROL_REQUIRED`."

    Design: Difficulty/boundary_precision_check/dual_control_witness_count_boundary
    """
    ctx = X.setup_checked_in_appointment(api)
    resp = api.create_access_event(
        F.create_access_event_payload(ctx["appointment"]["id"], ctx["box"]["id"],
                                      ctx["rental"]["id"], primary_accessor_ref="P1",
                                      dual_control_officer_ref="O1", witness_count=1), OFFICER)
    validate_error(resp, ApiErrorId.ERR_DUAL_CONTROL_REQUIRED.value, 409)


def test_access_event_with_two_witnesses_accepted(api):
    """PRD §3.7: "a `witness_count` of exactly 2 passes while a count of 1 fails,
    and any violation yields `ERR_DUAL_CONTROL_REQUIRED`."

    Design: Difficulty/boundary_precision_check/dual_control_witness_count_boundary
    """
    ctx = X.setup_checked_in_appointment(api)
    data = validate_success(api.create_access_event(
        F.create_access_event_payload(ctx["appointment"]["id"], ctx["box"]["id"],
                                      ctx["rental"]["id"], primary_accessor_ref="P1",
                                      dual_control_officer_ref="O1", witness_count=2), OFFICER), 201)
    assert_access_event(data)
    assert data["witness_count"] == 2


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / checkin_compliance_hold_beats_state
# ---------------------------------------------------------------------------
def test_checkin_compliance_hold_preempts_state_error(api):
    """PRD §2.6: "a compliance hold (priority 5) surfaces before a state error
    (priority 6), so a frozen renter attempting to check in sees the hold, not a
    state complaint."

    Design: Difficulty/priority_pair_validation_conflict/checkin_compliance_hold_beats_state
    """
    ctx = X.setup_active_rental_with_booked_appointment(api)
    X.set_clock(api, "2026-07-10T00:00:00Z")
    validate_success(api.run_billing_cycle(ADMIN), 200)   # rental → DELINQUENT (state fail)
    validate_success(api.create_compliance_case(
        F.create_compliance_case_payload(ctx["renter"]["id"], case_type="SANCTIONS",
                                         severity="HOLD"), COMPLIANCE), 201)
    resp = api.check_in_appointment(ctx["appointment"]["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_COMPLIANCE_HOLD.value, 409)
    appt = validate_success(api.get_appointment(ctx["appointment"]["id"], ADMIN), 200)
    assert appt["status"] == "BOOKED"


def test_checkin_blocked_by_compliance_hold_alone(api):
    """PRD §3.7: "Checking in an appointment (by `VaultOfficer`) has two gates
    evaluated safety-first: the renter must have no open `HOLD` compliance case,
    else `ERR_COMPLIANCE_HOLD`".

    Design: Difficulty/priority_pair_validation_conflict/checkin_compliance_hold_beats_state
    """
    ctx = X.setup_active_rental_with_booked_appointment(api)   # rental stays ACTIVE
    validate_success(api.create_compliance_case(
        F.create_compliance_case_payload(ctx["renter"]["id"], case_type="SAR",
                                         severity="HOLD"), COMPLIANCE), 201)
    resp = api.check_in_appointment(ctx["appointment"]["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_COMPLIANCE_HOLD.value, 409)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / booking_temporal_beats_referential
# ---------------------------------------------------------------------------
def test_booking_temporal_error_preempts_grant_mismatch(api):
    """PRD §3.7: "Booking enforces, in order: the window must be well-formed and
    future — `scheduled_end` strictly after `scheduled_start`, and
    `scheduled_start` at or after the clock's current instant — else
    `ERR_APPOINTMENT_IN_PAST`; the window must not overlap another `BOOKED` or
    `CHECKED_IN` appointment on the same box (half-open comparison), else
    `ERR_APPOINTMENT_OVERLAP`; the branch's viewing rooms must not be
    oversubscribed, else `ERR_ROOM_CAPACITY_EXCEEDED`; and if a `grant_id` is
    given, that grant must belong to the same rental, else
    `ERR_GRANT_RENTAL_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/booking_temporal_beats_referential
    """
    ctx = X.setup_two_active_rentals(api, capacity=4)
    grant_b = validate_success(api.create_access_grant(
        F.create_access_grant_payload(ctx["rental2"]["id"], "CO_RENTER", "Other Person"),
        ADMIN), 201)
    # Past window on rental1's box AND grant belonging to rental2 → temporal wins
    resp = api.create_appointment(
        F.create_appointment_payload(ctx["box1"]["id"], ctx["rental1"]["id"],
                                     "2026-04-15T10:00:00Z", "2026-04-15T11:00:00Z",
                                     grant_id=grant_b["id"]), OFFICER)
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_IN_PAST.value, 409)


def test_booking_past_window_rejected(api):
    """PRD §3.7: "the window must be well-formed and future — `scheduled_end`
    strictly after `scheduled_start`, and `scheduled_start` at or after the
    clock's current instant — else `ERR_APPOINTMENT_IN_PAST`".

    Design: Difficulty/priority_pair_validation_conflict/booking_temporal_beats_referential
    """
    ctx = X.setup_active_rental(api)
    resp = api.create_appointment(
        F.create_appointment_payload(ctx["box"]["id"], ctx["rental"]["id"],
                                     "2026-04-15T10:00:00Z", "2026-04-15T11:00:00Z"), OFFICER)
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_IN_PAST.value, 409)


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / checkin_requires_rental_accessible
# ---------------------------------------------------------------------------
def test_checkin_blocked_when_rental_delinquent(api):
    """PRD §3.7: "and the rental must be `ACTIVE` or `PAST_DUE`, else
    `ERR_RENTAL_NOT_ACCESSIBLE`."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_rental_accessible
    """
    ctx = X.setup_active_rental_with_booked_appointment(api)
    X.set_clock(api, "2026-07-10T00:00:00Z")
    validate_success(api.run_billing_cycle(ADMIN), 200)   # rental → DELINQUENT, no hold
    resp = api.check_in_appointment(ctx["appointment"]["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_RENTAL_NOT_ACCESSIBLE.value, 409)
    appt = validate_success(api.get_appointment(ctx["appointment"]["id"], ADMIN), 200)
    assert appt["status"] == "BOOKED"


def test_checkin_succeeds_on_active_rental(api):
    """PRD §3.7: "Checking in an appointment (by `VaultOfficer`) has two gates
    evaluated safety-first: the renter must have no open `HOLD` compliance case,
    else `ERR_COMPLIANCE_HOLD`; and the rental must be `ACTIVE` or `PAST_DUE`,
    else `ERR_RENTAL_NOT_ACCESSIBLE`."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_rental_accessible
    """
    ctx = X.setup_active_rental_with_booked_appointment(api)
    data = validate_success(api.check_in_appointment(ctx["appointment"]["id"], OFFICER), 200)
    assert data["status"] == "CHECKED_IN"


# ---------------------------------------------------------------------------
# Corner: state_machines / grant_suspend_resume_cycle
# ---------------------------------------------------------------------------
def test_grant_suspend_then_resume_returns_active(api):
    """PRD §3.7: "An active grant may be suspended (to `SUSPENDED`) and later
    resumed (back to `ACTIVE`) by `VaultAdmin` or `ComplianceOfficer`, forming a
    suspend/resume cycle."

    Design: Corner/state_machines/grant_suspend_resume_cycle
    """
    ctx = X.setup_active_rental(api)
    grant = validate_success(api.create_access_grant(
        F.create_access_grant_payload(ctx["rental"]["id"], "CO_RENTER", "Deputy"), ADMIN), 201)
    validate_success(api.activate_grant(grant["id"], {}, COMPLIANCE), 200)
    validate_success(api.suspend_grant(grant["id"], ADMIN), 200)
    data = validate_success(api.resume_grant(grant["id"], ADMIN), 200)
    assert data["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner: validations / beneficiary_activation_requires_death_certificate
# ---------------------------------------------------------------------------
def test_beneficiary_activation_without_certificate_rejected(api):
    """PRD §3.7: "For a `BENEFICIARY` grant, a `death_certificate_ref` must be
    supplied at activation, else `ERR_DEATH_CERTIFICATE_REQUIRED`; on success
    that reference is stored on `death_certificate_ref` and the underlying
    renter's `is_deceased` flag is set true."

    Design: Corner/validations/beneficiary_activation_requires_death_certificate
    """
    ctx = X.setup_active_rental(api)
    grant = validate_success(api.create_access_grant(
        F.create_access_grant_payload(ctx["rental"]["id"], "BENEFICIARY", "Heir Apparent",
                                      grantee_gov_id_ref="H-1"), ADMIN), 201)
    resp = api.activate_grant(grant["id"], {}, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_DEATH_CERTIFICATE_REQUIRED.value, 409)
    data = validate_success(api.get_access_grant(grant["id"], ADMIN), 200)
    assert data["status"] == "PENDING"
