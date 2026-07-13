"""Scheduling and storage: berth half-open overlap, bay buffered overlap, berth guards."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    fixtures,
    create_slip_reservation_payload, create_repair_order_payload,
)

MANAGER = TEST_USERS["manager_headers"]
SERVICE = TEST_USERS["service_advisor_headers"]


# --- resource_temporal_overlap: berth half-open [start, end) --------------------
def test_berth_overlapping_reservation_rejected(api):
    """PRD §3.7: "the half-open interval from `start_date` up to but not including
    `end_date` must not overlap any other `RESERVED` reservation on the same berth, else
    `ERR_BERTH_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/berth_halfopen_date_overlap_rejected
    """
    berth = fixtures.create_berth(max_length_ft=40)
    unit_a = fixtures.create_unit(length_ft=30)
    unit_b = fixtures.create_unit(length_ft=30)
    fixtures.create_reservation(berth["id"], unit_a["id"],
                                start_date="2026-06-01T00:00:00Z",
                                end_date="2026-06-10T00:00:00Z", daily_rate_cents=5000)
    payload = create_slip_reservation_payload(
        berth["id"], unit_b["id"], start_date="2026-06-05T00:00:00Z",
        end_date="2026-06-15T00:00:00Z", daily_rate_cents=5000)
    validate_error(api.create_slip_reservation(payload, SERVICE),
                   ApiErrorId.ERR_BERTH_DOUBLE_BOOKED.value)


def test_berth_adjacent_reservation_allowed(api):
    """PRD §3.7: "the half-open interval from `start_date` up to but not including
    `end_date` must not overlap any other `RESERVED` reservation on the same berth, else
    `ERR_BERTH_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/berth_halfopen_date_overlap_rejected
    """
    berth = fixtures.create_berth(max_length_ft=40)
    unit_a = fixtures.create_unit(length_ft=30)
    unit_b = fixtures.create_unit(length_ft=30)
    fixtures.create_reservation(berth["id"], unit_a["id"],
                                start_date="2026-06-01T00:00:00Z",
                                end_date="2026-06-10T00:00:00Z", daily_rate_cents=5000)
    # New stay begins exactly when the prior stay's exclusive end_date falls: no overlap.
    payload = create_slip_reservation_payload(
        berth["id"], unit_b["id"], start_date="2026-06-10T00:00:00Z",
        end_date="2026-06-20T00:00:00Z", daily_rate_cents=5000)
    data = validate_success(api.create_slip_reservation(payload, SERVICE), expected_status=201)
    assert data["status"] == "RESERVED"


# --- resource_temporal_overlap: bay closed window + 30-minute buffer ------------
def test_bay_reservation_within_buffer_rejected(api):
    """PRD §3.5: "the new order conflicts with an existing one whenever `scheduled_start`
    is at or before the other order's `scheduled_end` plus 30 minutes and the other
    order's `scheduled_start` is at or before the new order's `scheduled_end` plus 30
    minutes." PRD §3.5: "a conflict is rejected with `ERR_BAY_SCHEDULE_CONFLICT` (HTTP
    409)."

    Design: Difficulty/resource_temporal_overlap/bay_buffered_timestamp_overlap_rejected
    """
    bay = fixtures.create_service_bay(bay_type="RIGGING")
    unit_a = fixtures.create_unit(length_ft=20)
    unit_b = fixtures.create_unit(length_ft=20)
    fixtures.create_repair_order(
        unit_a["id"], bay["id"], ro_type="DIAGNOSTIC", estimated_hours=2.0,
        scheduled_start="2026-06-02T09:00:00Z", scheduled_end="2026-06-02T11:00:00Z")
    payload = create_repair_order_payload(
        unit_b["id"], bay["id"], ro_type="DIAGNOSTIC", estimated_hours=0.75,
        scheduled_start="2026-06-02T11:15:00Z", scheduled_end="2026-06-02T12:00:00Z")
    validate_error(api.create_repair_order(payload, SERVICE),
                   ApiErrorId.ERR_BAY_SCHEDULE_CONFLICT.value)


def test_bay_reservation_outside_buffer_allowed(api):
    """PRD §3.5: "the new order conflicts with an existing one whenever `scheduled_start`
    is at or before the other order's `scheduled_end` plus 30 minutes and the other
    order's `scheduled_start` is at or before the new order's `scheduled_end` plus 30
    minutes."

    Design: Difficulty/resource_temporal_overlap/bay_buffered_timestamp_overlap_rejected
    """
    bay = fixtures.create_service_bay(bay_type="RIGGING")
    unit_a = fixtures.create_unit(length_ft=20)
    unit_b = fixtures.create_unit(length_ft=20)
    fixtures.create_repair_order(
        unit_a["id"], bay["id"], ro_type="DIAGNOSTIC", estimated_hours=2.0,
        scheduled_start="2026-06-02T09:00:00Z", scheduled_end="2026-06-02T11:00:00Z")
    # Starts at 12:00, later than the prior order's 11:00 end plus the 30-minute buffer.
    payload = create_repair_order_payload(
        unit_b["id"], bay["id"], ro_type="DIAGNOSTIC", estimated_hours=1.0,
        scheduled_start="2026-06-02T12:00:00Z", scheduled_end="2026-06-02T13:00:00Z")
    data = validate_success(api.create_repair_order(payload, SERVICE), expected_status=201)
    assert data["status"] == "OPEN"


# --- cross_entity_state_dependency: reservation requires berth OPEN --------------
def test_reservation_on_closed_berth_rejected(api):
    """PRD §3.7: "the target berth must be `OPEN`, else `ERR_BERTH_CLOSED` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/slip_reservation_requires_berth_open
    """
    berth = fixtures.create_closed_berth(max_length_ft=40)
    unit = fixtures.create_unit(length_ft=25)
    payload = create_slip_reservation_payload(
        berth["id"], unit["id"], start_date="2026-06-01T00:00:00Z",
        end_date="2026-06-05T00:00:00Z", daily_rate_cents=4000)
    validate_error(api.create_slip_reservation(payload, SERVICE),
                   ApiErrorId.ERR_BERTH_CLOSED.value)


def test_reservation_on_open_berth_succeeds(api):
    """PRD §3.7: "A berth begins `OPEN`". PRD §3.7: "A reservation begins `RESERVED` and
    reports two derived fields: `nights`, the whole number of days between `start_date`
    and `end_date`, and `total_cents`, that night count multiplied by `daily_rate_cents`."

    Design: Difficulty/cross_entity_state_dependency/slip_reservation_requires_berth_open
    """
    berth = fixtures.create_berth(max_length_ft=40)
    unit = fixtures.create_unit(length_ft=25)
    payload = create_slip_reservation_payload(
        berth["id"], unit["id"], start_date="2026-06-01T00:00:00Z",
        end_date="2026-06-05T00:00:00Z", daily_rate_cents=5000)
    data = validate_success(api.create_slip_reservation(payload, SERVICE), expected_status=201)
    assert data["status"] == "RESERVED"
    assert data["nights"] == 4, f"Expected 4 nights, got {data['nights']}"
    assert data["total_cents"] == 20000, f"Expected 20000, got {data['total_cents']}"


# --- priority_pair_validation_conflict: fit check pre-empts overlap check --------
def test_oversized_and_overlapping_reservation_returns_exceeds_berth(api):
    """PRD §3.7: "Four business guards apply to a reservation, evaluated in this order
    after existence and structural validation". PRD §3.7: "the unit must physically fit,
    with the unit's `length_ft` less than or equal to the berth's `max_length_ft`, else
    `ERR_UNIT_EXCEEDS_BERTH` (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/slip_constraint_beats_temporal
    """
    berth = fixtures.create_berth(max_length_ft=30)
    unit_a = fixtures.create_unit(length_ft=25)
    unit_big = fixtures.create_unit(length_ft=40)
    fixtures.create_reservation(berth["id"], unit_a["id"],
                                start_date="2026-06-01T00:00:00Z",
                                end_date="2026-06-10T00:00:00Z", daily_rate_cents=5000)
    payload = create_slip_reservation_payload(
        berth["id"], unit_big["id"], start_date="2026-06-05T00:00:00Z",
        end_date="2026-06-15T00:00:00Z", daily_rate_cents=5000)
    validate_error(api.create_slip_reservation(payload, SERVICE),
                   ApiErrorId.ERR_UNIT_EXCEEDS_BERTH.value)


def test_fitting_overlapping_reservation_returns_double_booked(api):
    """PRD §3.7: "the half-open interval from `start_date` up to but not including
    `end_date` must not overlap any other `RESERVED` reservation on the same berth, else
    `ERR_BERTH_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/slip_constraint_beats_temporal
    """
    berth = fixtures.create_berth(max_length_ft=30)
    unit_a = fixtures.create_unit(length_ft=25)
    unit_c = fixtures.create_unit(length_ft=25)
    fixtures.create_reservation(berth["id"], unit_a["id"],
                                start_date="2026-06-01T00:00:00Z",
                                end_date="2026-06-10T00:00:00Z", daily_rate_cents=5000)
    payload = create_slip_reservation_payload(
        berth["id"], unit_c["id"], start_date="2026-06-05T00:00:00Z",
        end_date="2026-06-15T00:00:00Z", daily_rate_cents=5000)
    validate_error(api.create_slip_reservation(payload, SERVICE),
                   ApiErrorId.ERR_BERTH_DOUBLE_BOOKED.value)


# --- Corner: reservation dates well-formed --------------------------------------
def test_reservation_end_not_after_start_rejected(api):
    """PRD §3.7: "the dates must be well-formed, with `end_date` strictly after
    `start_date`, else `ERR_RESERVATION_DATES_INVALID` (HTTP 422)".

    Design: Corner/validations/reservation_end_not_after_start_rejected
    """
    berth = fixtures.create_berth(max_length_ft=40)
    unit = fixtures.create_unit(length_ft=24)
    payload = create_slip_reservation_payload(
        berth["id"], unit["id"], start_date="2026-06-01T00:00:00Z",
        end_date="2026-06-01T00:00:00Z", daily_rate_cents=5000)
    validate_error(api.create_slip_reservation(payload, SERVICE),
                   ApiErrorId.ERR_RESERVATION_DATES_INVALID.value)
