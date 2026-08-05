"""Temporal overlaps, boundary precision, cross-entity gates, validation precedence,
and optimistic concurrency (PRD §2.5, §2.8, §3.3, §3.5, §3.6, §3.7)."""
from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    make_member_headers, create_delivery_job_payload, create_agreement_payload,
    create_waitlist_payload,
)
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId

VM = TEST_USERS["vault_manager_headers"]
CT = TEST_USERS["concierge_tech_headers"]


def _booking_base(api, unit_class="STANDARD", clock="2026-05-15T00:00:00Z"):
    fac = fx.create_facility(api, total_units=2)
    unit = fx.create_unit(api, fac["id"], unit_class=unit_class, monthly_rate_cents=30000)
    mem = fx.create_member(api)
    veh = fx.create_vehicle(api, mem["id"])
    fx.set_clock(api, clock)
    return fac, unit, mem, veh


def _book(api, mem, veh, unit, move_in_at, planned_move_out_at):
    uv = fx.unit_version(api, unit["id"])
    return api.create_agreement(
        create_agreement_payload(mem["id"], veh["id"], unit["id"], uv,
                                 move_in_at=move_in_at, planned_move_out_at=planned_move_out_at),
        VM)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / unit_occupancy_half_open_adjacency_allowed
# ---------------------------------------------------------------------------
def test_unit_bookings_touching_at_endpoint_both_allowed(api):
    """PRD §3.3: "Two windows that merely touch at an endpoint — one ending exactly
    when the next begins — do not overlap and are both allowed."

    Design: Difficulty/resource_temporal_overlap/unit_occupancy_half_open_adjacency_allowed
    """
    _, unit, mem, veh = _booking_base(api)
    agr1 = validate_success(_book(api, mem, veh, unit,
                                  "2026-06-01T00:00:00Z", "2026-09-01T00:00:00Z"), 201)
    agr2 = validate_success(_book(api, mem, veh, unit,
                                  "2026-09-01T00:00:00Z", "2026-12-01T00:00:00Z"), 201)
    assert agr1["status"] == "PENDING"
    assert agr2["status"] == "PENDING"


def test_unit_booking_interior_overlap_rejected(api):
    """PRD §3.3: "The proposed window `[move_in_at, planned_move_out_at)` is treated
    as a half-open interval and must not overlap the window of any non-terminal
    agreement already on that same unit; an overlap is rejected with `ERR_UNIT_OVERLAP`
    (409)."

    Design: Difficulty/resource_temporal_overlap/unit_occupancy_half_open_adjacency_allowed
    """
    _, unit, mem, veh = _booking_base(api)
    validate_success(_book(api, mem, veh, unit,
                           "2026-06-01T00:00:00Z", "2026-09-01T00:00:00Z"), 201)
    resp = _book(api, mem, veh, unit, "2026-08-01T00:00:00Z", "2026-10-01T00:00:00Z")
    validate_error(resp, ApiErrorId.ERR_UNIT_OVERLAP.value)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / transporter_buffered_overlap_conflict
# ---------------------------------------------------------------------------
def test_first_delivery_job_scheduled(api):
    """PRD §3.6: "The job's occupied interval on the transporter runs from `pickup_at`
    to `dropoff_at` as a closed interval, extended by `buffer_minutes` after
    `dropoff_at`. A new job starts in `status` `SCHEDULED` and reserves that window."

    Design: Difficulty/resource_temporal_overlap/transporter_buffered_overlap_conflict
    """
    ctx = fx.setup_scheduled_delivery(api, buffer_minutes=60,
                                      pickup_at="2026-06-10T10:00:00Z",
                                      dropoff_at="2026-06-10T14:00:00Z",
                                      declared_value_cents=1_000_000,
                                      coverage_amount_cents=1_000_000)
    assert ctx["delivery_job"]["status"] == "SCHEDULED"


def test_second_delivery_within_buffer_conflicts(api):
    """PRD §3.6: "the closed interval `[pickup_at, dropoff_at]` plus the trailing
    `buffer_minutes` must not overlap any existing job's occupied window on that
    transporter, else `ERR_TRANSPORTER_CONFLICT` (409)."

    Design: Difficulty/resource_temporal_overlap/transporter_buffered_overlap_conflict
    """
    ctx = fx.setup_scheduled_delivery(api, buffer_minutes=60,
                                      pickup_at="2026-06-10T10:00:00Z",
                                      dropoff_at="2026-06-10T14:00:00Z",
                                      declared_value_cents=1_000_000,
                                      coverage_amount_cents=1_000_000)
    # 14:30 falls within the 60-min buffer after the 14:00 dropoff (buffer to 15:00)
    resp = api.create_delivery_job(
        create_delivery_job_payload(ctx["vehicle_id"], ctx["transporter_id"],
                                    event_name="Meet2",
                                    pickup_at="2026-06-10T14:30:00Z",
                                    dropoff_at="2026-06-10T16:00:00Z"), VM)
    validate_error(resp, ApiErrorId.ERR_TRANSPORTER_CONFLICT.value)


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / waitlist_join_only_at_zero_available_units
# ---------------------------------------------------------------------------
def test_waitlist_join_accepted_when_zero_available(api):
    """PRD §3.7: "A join is permitted only when the facility currently has zero
    `AVAILABLE` units of that class — if an available unit of the desired class already
    exists, the join is rejected with `ERR_UNITS_AVAILABLE` (409) because the member
    should simply take that unit."

    Design: Difficulty/boundary_precision_check/waitlist_join_only_at_zero_available_units
    """
    ctx = fx.setup_stored_agreement(api, unit_class="CLIMATE", monthly_rate_cents=40000,
                                    membership_tier="GOLD", total_units=1)
    fac = validate_success(api.get_facility(ctx["facility_id"], VM))
    assert fac["units_available"] == 0
    memB = fx.create_member(api, membership_tier="SILVER")
    entry = validate_success(api.create_waitlist(
        create_waitlist_payload(memB["id"], ctx["facility_id"], desired_unit_class="CLIMATE"),
        make_member_headers(memB["id"])), 201)
    assert entry["status"] == "WAITING"


def test_waitlist_join_rejected_when_unit_available(api):
    """PRD §3.7: "if an available unit of the desired class already exists, the join is
    rejected with `ERR_UNITS_AVAILABLE` (409) because the member should simply take
    that unit."

    Design: Difficulty/boundary_precision_check/waitlist_join_only_at_zero_available_units
    """
    fac = fx.create_facility(api, total_units=2)
    fx.create_unit(api, fac["id"], unit_class="CLIMATE", monthly_rate_cents=40000)
    memB = fx.create_member(api, membership_tier="SILVER")
    resp = api.create_waitlist(
        create_waitlist_payload(memB["id"], fac["id"], desired_unit_class="CLIMATE"),
        make_member_headers(memB["id"]))
    validate_error(resp, ApiErrorId.ERR_UNITS_AVAILABLE.value)


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / delivery_coverage_ge_declared_value_boundary
# ---------------------------------------------------------------------------
def test_delivery_coverage_equal_to_declared_value_allowed(api):
    """PRD §3.6: "the coverage on the vehicle's active certificate must be adequate:
    its `coverage_amount_cents` must be greater than or equal to the vehicle's
    `declared_value_cents`, else `ERR_COVERAGE_INSUFFICIENT` (409)."

    Design: Difficulty/boundary_precision_check/delivery_coverage_ge_declared_value_boundary
    """
    ctx = fx.setup_vehicle_with_active_coi(api, declared_value_cents=5_000_000,
                                           coverage_amount_cents=5_000_000)
    tr = fx.create_transporter(api, buffer_minutes=30)
    dj = validate_success(api.create_delivery_job(
        create_delivery_job_payload(ctx["vehicle_id"], tr["id"], event_name="Expo",
                                    pickup_at="2026-06-15T09:00:00Z",
                                    dropoff_at="2026-06-15T17:00:00Z"), VM), 201)
    assert dj["status"] == "SCHEDULED"


def test_delivery_coverage_below_declared_value_rejected(api):
    """PRD §3.6: "its `coverage_amount_cents` must be greater than or equal to the
    vehicle's `declared_value_cents`, else `ERR_COVERAGE_INSUFFICIENT` (409)."

    Design: Difficulty/boundary_precision_check/delivery_coverage_ge_declared_value_boundary
    """
    ctx = fx.setup_vehicle_with_active_coi(api, declared_value_cents=5_000_000,
                                           coverage_amount_cents=4_999_999)
    tr = fx.create_transporter(api, buffer_minutes=30)
    resp = api.create_delivery_job(
        create_delivery_job_payload(ctx["vehicle_id"], tr["id"], event_name="Expo",
                                    pickup_at="2026-06-15T09:00:00Z",
                                    dropoff_at="2026-06-15T17:00:00Z"), VM)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_INSUFFICIENT.value)


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / delivery_create_requires_vehicle_insurance_active
# ---------------------------------------------------------------------------
def test_delivery_create_blocked_when_insurance_not_active(api):
    """PRD §3.6: "the vehicle's `insurance_status` must be `ACTIVE`, else
    `ERR_INSURANCE_LAPSED` (409)."

    Design: Difficulty/cross_entity_state_dependency/delivery_create_requires_vehicle_insurance_active
    """
    mem = fx.create_member(api, membership_tier="GOLD")
    veh = fx.create_vehicle(api, mem["id"], declared_value_cents=5_000_000)
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    tr = fx.create_transporter(api, buffer_minutes=30)
    resp = api.create_delivery_job(
        create_delivery_job_payload(veh["id"], tr["id"], event_name="Show1",
                                    pickup_at="2026-06-10T09:00:00Z",
                                    dropoff_at="2026-06-10T12:00:00Z"), VM)
    validate_error(resp, ApiErrorId.ERR_INSURANCE_LAPSED.value)


def test_delivery_create_succeeds_once_insurance_active(api):
    """PRD §3.2: "attaching it recomputes the vehicle's `insurance_status`, which
    becomes `ACTIVE` if the certificate's window covers the current logical clock".
    PRD §3.6: "the vehicle's `insurance_status` must be `ACTIVE`, else
    `ERR_INSURANCE_LAPSED` (409)."

    Design: Difficulty/cross_entity_state_dependency/delivery_create_requires_vehicle_insurance_active
    """
    mem = fx.create_member(api, membership_tier="GOLD")
    veh = fx.create_vehicle(api, mem["id"], declared_value_cents=5_000_000)
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    tr = fx.create_transporter(api, buffer_minutes=30)
    fx.create_coi(api, veh["id"], coverage_amount_cents=5_000_000)
    v = validate_success(api.get_vehicle(veh["id"], VM))
    assert v["insurance_status"] == "ACTIVE"
    dj = validate_success(api.create_delivery_job(
        create_delivery_job_payload(veh["id"], tr["id"], event_name="Show2",
                                    pickup_at="2026-06-12T09:00:00Z",
                                    dropoff_at="2026-06-12T12:00:00Z"), VM), 201)
    assert dj["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / service_start_requires_agreement_in_storage
# ---------------------------------------------------------------------------
def test_service_start_blocked_while_agreement_checked_out(api):
    """PRD §3.5: "Starting requires that the parent agreement's `status` is
    `IN_STORAGE` — work cannot begin while the vehicle is `CHECKED_OUT`, and a
    violation is a cross-entity failure with `ERR_CROSS_ENTITY_STATE`".

    Design: Difficulty/cross_entity_state_dependency/service_start_requires_agreement_in_storage
    """
    ctx = fx.setup_approved_service_order(api)
    validate_success(api.check_out(ctx["agreement_id"], CT))
    resp = api.start_service_order(ctx["service_order_id"], CT)
    validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE.value)


def test_service_start_succeeds_after_check_in(api):
    """PRD §3.3: "**checking in** advances `CHECKED_OUT → IN_STORAGE`."
    PRD §3.5: "A concierge technician **starts** work, advancing an order from
    `APPROVED` to `IN_PROGRESS`."

    Design: Difficulty/cross_entity_state_dependency/service_start_requires_agreement_in_storage
    """
    ctx = fx.setup_approved_service_order(api)
    validate_success(api.check_out(ctx["agreement_id"], CT))
    validate_success(api.check_in(ctx["agreement_id"], CT))
    started = validate_success(api.start_service_order(ctx["service_order_id"], CT))
    assert started["status"] == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / service_start_state_beats_referential
# ---------------------------------------------------------------------------
def _completed_order_checked_out(api):
    ctx = fx.setup_in_progress_service_order(api)
    validate_success(api.complete_service_order(ctx["service_order_id"],
                                                {"actual_labor_hours": 1.0}, CT))
    validate_success(api.check_out(ctx["agreement_id"], CT))
    return ctx


def test_start_completed_order_returns_invalid_state_not_cross_entity(api):
    """PRD §2.8: "Requests are validated in a fixed priority order, and the first
    failing check determines the error returned."
    PRD §2.8: "6. State validity — the target resource is in a legal state for the
    requested transition, else `ERR_INVALID_STATE` (409). 7. Cross-entity state — a
    required state on a related entity holds, else `ERR_CROSS_ENTITY_STATE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/service_start_state_beats_referential
    """
    ctx = _completed_order_checked_out(api)
    resp = api.start_service_order(ctx["service_order_id"], CT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_start_completed_order_leaves_states_unchanged(api):
    """PRD §2.8: "the first failing check determines the error returned ... 6. State
    validity — the target resource is in a legal state for the requested transition,
    else `ERR_INVALID_STATE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/service_start_state_beats_referential
    """
    ctx = _completed_order_checked_out(api)
    api.start_service_order(ctx["service_order_id"], CT)
    so = validate_success(api.get_service_order(ctx["service_order_id"], CT))
    assert so["status"] == "COMPLETED"
    agr = validate_success(api.get_agreement(ctx["agreement_id"], VM))
    assert agr["status"] == "CHECKED_OUT"


# ---------------------------------------------------------------------------
# Corner: cross_cutting / occ_stale_unit_version_returns_412
# ---------------------------------------------------------------------------
def test_stale_unit_version_rejected_on_second_booking(api):
    """PRD §2.5: "If that value does not equal the unit's current `version` — for
    example because another agreement has since recorded its own non-overlapping
    booking window on the same unit and thereby advanced the unit's `version` — the
    create is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_unit_version_returns_412
    """
    _, unit, mem, veh = _booking_base(api)
    uv1 = fx.unit_version(api, unit["id"])
    agr1 = validate_success(api.create_agreement(
        create_agreement_payload(mem["id"], veh["id"], unit["id"], uv1,
                                 move_in_at="2026-06-01T00:00:00Z",
                                 planned_move_out_at="2026-09-01T00:00:00Z"), VM), 201)
    # unit.version has advanced to 2; reusing the stale uv1 must be rejected
    resp = api.create_agreement(
        create_agreement_payload(mem["id"], veh["id"], unit["id"], uv1,
                                 move_in_at="2026-09-01T00:00:00Z",
                                 planned_move_out_at="2026-12-01T00:00:00Z"), VM)
    validate_error(resp, ApiErrorId.ERR_STALE_UNIT_VERSION.value)
    assert validate_success(api.get_agreement(agr1["id"], VM))["status"] == "PENDING"
