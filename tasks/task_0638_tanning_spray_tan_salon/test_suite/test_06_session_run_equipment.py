"""Session run lifecycle, the UV-complete equipment cascade, maintenance/service,
slot conflicts, cross-entity state gating, and the cyclic reservation loop.

Covers queue-B equipment/state-machine corner instances plus the transitive_cascade,
boundary_precision_check (service threshold), cross_entity_state_dependency,
resource_temporal_overlap, and non_linear_state_machine (session cycle) difficulty
instances.
"""
from test_helpers import (
    ApiErrorId,
    validate_success,
    validate_error,
    TEST_USERS,
    make_member_headers,
    create_session_payload,
    create_equipment_payload,
    create_spray_room_payload,
    assert_maintenance_log,
)
from test_helpers import fixtures as fx

FRONT_DESK = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_system_headers"]
SALON_MANAGER = TEST_USERS["salon_manager_headers"]


# ---------------------------------------------------------------------------
# Equipment / SprayRoom creation defaults (corner entities)
# ---------------------------------------------------------------------------
def test_equipment_default_turnaround_applied(api):
    """PRD §3.8: "Each `Equipment` unit is created by a `SalonManager` with a
    `name`, a `kind` (`BED` or `BOOTH`), a `max_exposure_seconds` ceiling of at
    least 1, and an optional `turnaround_seconds` (default 600). A new unit starts
    `AVAILABLE` with `sessions_since_service` at 0."

    Design: Corner/entities/equipment_default_turnaround_applied
    """
    resp = api.create_equipment(
        create_equipment_payload(name="Default bed", kind="BOOTH", max_exposure_seconds=480),
        SALON_MANAGER,
    )
    data = validate_success(resp, expected_status=201)
    assert data["turnaround_seconds"] == 600
    assert data["status"] == "AVAILABLE"


def test_spray_room_default_ventilation_applied(api):
    """PRD §3.10: "Spray rooms are configured by a `SalonManager`, who creates a
    `SprayRoom` with a `name` and an optional `ventilation_buffer_seconds` (default
    300); a new room starts `AVAILABLE`."

    Design: Corner/entities/spray_room_default_ventilation_applied
    """
    resp = api.create_spray_room(create_spray_room_payload(name="Default room"), SALON_MANAGER)
    data = validate_success(resp, expected_status=201)
    assert data["ventilation_buffer_seconds"] == 300
    assert data["status"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# Invalid session transitions / preconditions (corner state_machines)
# ---------------------------------------------------------------------------
def test_complete_reserved_session_rejected(api):
    """PRD §3.7: "A `FrontDeskStaff` operator then completes an in-progress session,
    advancing it from `IN_PROGRESS` to `COMPLETED`; this requires the session to
    currently be `IN_PROGRESS` (otherwise `ERR_SESSION_NOT_IN_PROGRESS`)."

    Design: Corner/state_machines/complete_session_from_reserved_invalid_state
    """
    plan, member, equipment = fx.setup_active_member_with_equipment(
        plan_overrides={"weekly_uv_session_cap": 0}, clock="2026-06-01T10:00:00Z",
    )
    session = fx.reserve_uv_session(member["id"], equipment["id"], "2026-06-01T10:00:00Z", 120)
    resp = api.complete_session(session["id"], FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_IN_PROGRESS.value, expected_status=409)
    eq_after = validate_success(api.get_equipment(equipment["id"], SALON_MANAGER))
    assert eq_after["sessions_since_service"] == 0, "no cascade should fire on a failed complete"


def test_no_show_before_start_at_rejected(api):
    """PRD §3.7: "a `FrontDeskStaff` operator marks a reserved past-due session as a
    no-show, moving it from `RESERVED` to the terminal `NO_SHOW` state; this requires
    the session to be `RESERVED` (otherwise `ERR_SESSION_NOT_RESERVED`) and requires
    that the logical clock has reached or passed the session's `start_at` (otherwise
    `ERR_TOO_EARLY_FOR_NO_SHOW`)."

    Design: Corner/state_machines/no_show_too_early_returns_error
    """
    plan, member, equipment = fx.setup_active_member_with_equipment(
        plan_overrides={"weekly_uv_session_cap": 0}, clock="2026-06-01T09:00:00Z",
    )
    session = fx.reserve_uv_session(member["id"], equipment["id"], "2026-06-01T12:00:00Z", 120)
    resp = api.no_show_session(session["id"], FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_TOO_EARLY_FOR_NO_SHOW.value, expected_status=409)


def test_service_available_equipment_rejected(api):
    """PRD §3.8: "servicing requires the unit to currently be `MAINTENANCE`
    (otherwise `ERR_EQUIPMENT_NOT_IN_MAINTENANCE`)."

    Design: Corner/state_machines/service_equipment_not_in_maintenance_returns_error
    """
    equipment = fx.create_equipment(name="NotMaint bed", max_exposure_seconds=600)
    resp = api.service_equipment(equipment["id"], {"reason": "MANUAL"}, SALON_MANAGER)
    validate_error(resp, ApiErrorId.ERR_EQUIPMENT_NOT_IN_MAINTENANCE.value, expected_status=409)


def test_retire_in_use_equipment_blocked(api):
    """PRD §3.8: "A `SalonManager` may also retire a unit, moving it to the terminal
    `RETIRED` state from either `AVAILABLE` or `MAINTENANCE`; retiring is blocked
    while the unit is `IN_USE`, in which case it is rejected with
    `ERR_EQUIPMENT_IN_USE`, and a retired unit is permanently unbookable."

    Design: Corner/state_machines/retire_equipment_in_use_blocked
    """
    plan, member, equipment = fx.setup_active_member_with_equipment(
        plan_overrides={"weekly_uv_session_cap": 0}, clock="2026-06-01T10:00:00Z",
    )
    fx.start_uv_session(member["id"], equipment["id"], "2026-06-01T10:00:00Z", 120)  # IN_USE
    resp = api.retire_equipment(equipment["id"], SALON_MANAGER)
    validate_error(resp, ApiErrorId.ERR_EQUIPMENT_IN_USE.value, expected_status=409)


# ---------------------------------------------------------------------------
# UV-complete cascade + service threshold boundary (difficulty)
# ---------------------------------------------------------------------------
def test_first_uv_completion_keeps_equipment_available(api):
    """PRD §3.8: "The service threshold is 2: when `sessions_since_service` reaches 2
    or more after the completing session — that is, on the second completed UV
    session since the last service — the equipment is driven to `MAINTENANCE` and
    becomes unbookable until serviced; otherwise it returns to `AVAILABLE`."

    Design: Difficulty/boundary_precision_check/service_threshold_count_boundary
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    equipment = fx.create_equipment(name="Boundary bed", max_exposure_seconds=600, turnaround_seconds=600)
    fx.set_clock("2026-06-01T10:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Boundary Member", skin_type="IV")
    fx.complete_uv_session(member["id"], equipment["id"], "2026-06-01T10:00:00Z", 120)
    eq_after = validate_success(api.get_equipment(equipment["id"], SALON_MANAGER))
    assert eq_after["sessions_since_service"] == 1
    assert eq_after["status"] == "AVAILABLE", (
        f"after 1st completion equipment must stay AVAILABLE, got {eq_after['status']}"
    )


def test_second_uv_completion_trips_maintenance(api):
    """PRD §3.8: "On each UV session completion, the equipment's
    `sessions_since_service` is incremented by one (only completed UV sessions
    count). The service threshold is 2: when `sessions_since_service` reaches 2 or
    more after the completing session — that is, on the second completed UV session
    since the last service — the equipment is driven to `MAINTENANCE`."

    Design: Difficulty/boundary_precision_check/service_threshold_count_boundary
    """
    plan, member, equipment = fx.setup_equipment_in_maintenance()
    eq_after = validate_success(api.get_equipment(equipment["id"], SALON_MANAGER))
    assert eq_after["sessions_since_service"] == 2
    assert eq_after["status"] == "MAINTENANCE"


def test_uv_complete_cascade_counter_and_member_count_and_maintenance(api):
    """PRD §3.7: "Completion of a UV session is a cascade: the equipment returns to
    `AVAILABLE`, the equipment's `sessions_since_service` increases by one, and the
    member's `completed_uv_session_count` increases by one. If, after that increment,
    the equipment's `sessions_since_service` reaches the service threshold, the
    equipment is instead driven to `MAINTENANCE` — this maintenance set overrides the
    `AVAILABLE` set that would otherwise apply, so the unit ends in `MAINTENANCE`,
    not `AVAILABLE`."

    Design: Difficulty/transitive_cascade/uv_complete_bumps_counter_trips_maintenance
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    equipment = fx.create_equipment(name="Service bed", max_exposure_seconds=600, turnaround_seconds=600)
    fx.set_clock("2026-06-01T10:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Service Member", skin_type="IV")
    mid = member["id"]
    fx.complete_uv_session(mid, equipment["id"], "2026-06-01T10:00:00Z", 120)  # counter -> 1
    fx.set_clock("2026-06-02T10:00:00Z")
    # Second completion trips the cascade through to MAINTENANCE.
    session_b = fx.reserve_uv_session(mid, equipment["id"], "2026-06-02T10:00:00Z", 120)
    validate_success(api.start_session(session_b["id"], FRONT_DESK))
    complete_resp = api.complete_session(session_b["id"], FRONT_DESK)
    completed = validate_success(complete_resp)
    assert completed["status"] == "COMPLETED"
    eq_after = validate_success(api.get_equipment(equipment["id"], SALON_MANAGER))
    assert eq_after["sessions_since_service"] == 2
    assert eq_after["status"] == "MAINTENANCE"
    member_after = validate_success(api.get_member(mid, FRONT_DESK))
    assert member_after["completed_uv_session_count"] == 2


def test_uv_complete_increments_member_completed_count(api):
    """PRD §3.7: "Completion of a UV session is a cascade: the equipment returns to
    `AVAILABLE`, the equipment's `sessions_since_service` increases by one, and the
    member's `completed_uv_session_count` increases by one."

    Design: Difficulty/transitive_cascade/uv_complete_bumps_counter_trips_maintenance
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    equipment = fx.create_equipment(name="Cascade bed", max_exposure_seconds=600, turnaround_seconds=600)
    fx.set_clock("2026-06-01T10:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Cascade Member", skin_type="IV")
    mid = member["id"]
    completed = fx.complete_uv_session(mid, equipment["id"], "2026-06-01T10:00:00Z", 120)
    assert completed["status"] == "COMPLETED"
    eq_after = validate_success(api.get_equipment(equipment["id"], SALON_MANAGER))
    assert eq_after["sessions_since_service"] == 1
    member_after = validate_success(api.get_member(mid, FRONT_DESK))
    assert member_after["completed_uv_session_count"] == 1


def test_service_resets_counter_and_creates_maintenance_log(api):
    """PRD §3.8: "servicing requires the unit to currently be `MAINTENANCE` ...
    supplies a `reason` (`SCHEDULED_THRESHOLD` or `MANUAL`), creates a
    `MaintenanceLog` capturing the serviced `equipment_id`, the `reason`, and the
    `sessions_at_service` value of `sessions_since_service` taken before reset, and
    then resets `sessions_since_service` to 0."

    Design: Corner/state_machines/equipment_service_resets_counter_and_logs
    """
    plan, member, equipment = fx.setup_equipment_in_maintenance()
    resp = api.service_equipment(equipment["id"], {"reason": "SCHEDULED_THRESHOLD"}, SALON_MANAGER)
    data = validate_success(resp)
    assert data["status"] == "AVAILABLE"
    assert data["sessions_since_service"] == 0
    from test_helpers import validate_paginated
    logs_resp = api.list_maintenance_logs(equipment["id"], SALON_MANAGER)
    log_list, log_meta = validate_paginated(logs_resp)
    assert log_meta["total_count"] >= 1
    assert_maintenance_log(log_list[-1])
    assert log_list[-1]["sessions_at_service"] == 2


# ---------------------------------------------------------------------------
# Cross-entity state gating (difficulty)
# ---------------------------------------------------------------------------
def test_reserve_uv_requires_member_active(api):
    """PRD §3.4: "First comes member booking eligibility: the booking member must be
    `ACTIVE` and must not have `billing_status` of `SUSPENDED`; a suspended or
    non-active member cannot book and is rejected with `ERR_MEMBER_NOT_BOOKABLE`."

    Design: Difficulty/cross_entity_state_dependency/session_reserve_requires_member_active
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    equipment = fx.create_equipment(name="Dep bed", max_exposure_seconds=600, turnaround_seconds=600)
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Frozen Member", skin_type="IV")
    frozen = fx.freeze_member(member["id"], member["version"])
    assert frozen["status"] == "FROZEN"
    payload = create_session_payload(
        member_id=member["id"], kind="UV", booking_mode="WALK_IN",
        equipment_id=equipment["id"], start_at="2026-06-01T10:00:00Z", requested_seconds=120,
    )
    resp = api.create_session(payload, FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_BOOKABLE.value, expected_status=409)


def test_reserve_uv_requires_member_active_pending_member(api):
    """PRD §3.4: "First comes member booking eligibility: the booking member must be
    `ACTIVE` and must not have `billing_status` of `SUSPENDED`; a suspended or
    non-active member cannot book and is rejected with `ERR_MEMBER_NOT_BOOKABLE`."

    Design: Difficulty/cross_entity_state_dependency/session_reserve_requires_member_active
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    equipment = fx.create_equipment(name="Pending dep bed", max_exposure_seconds=600, turnaround_seconds=600)
    fx.set_clock("2026-06-01T00:00:00Z")
    # Registered but never activated -> status PENDING (not ACTIVE).
    pending = fx.register_member(plan["id"], full_name="Pending Member", skin_type="IV")
    payload = create_session_payload(
        member_id=pending["id"], kind="UV", booking_mode="WALK_IN",
        equipment_id=equipment["id"], start_at="2026-06-01T10:00:00Z", requested_seconds=120,
    )
    resp = api.create_session(payload, FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_BOOKABLE.value, expected_status=409)


def test_start_session_requires_equipment_available_in_use(api):
    """PRD §3.7: "for a UV session the booked equipment must be `AVAILABLE`
    (otherwise `ERR_EQUIPMENT_UNAVAILABLE`)."

    Design: Difficulty/cross_entity_state_dependency/session_start_requires_equipment_available
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    equipment = fx.create_equipment(name="InUse dep bed", max_exposure_seconds=600, turnaround_seconds=600)
    fx.set_clock("2026-06-01T09:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="InUse Dep Member", skin_type="IV")
    mid = member["id"]
    # Reserve two non-conflicting slots on the same unit.
    s_first = fx.reserve_uv_session(mid, equipment["id"], "2026-06-01T10:00:00Z", 120)
    s_second = fx.reserve_uv_session(mid, equipment["id"], "2026-06-02T10:00:00Z", 120)
    # Start the first -> equipment becomes IN_USE.
    validate_success(api.start_session(s_first["id"], FRONT_DESK))
    eq_after = validate_success(api.get_equipment(equipment["id"], SALON_MANAGER))
    assert eq_after["status"] == "IN_USE"
    # Starting the second while equipment IN_USE must fail.
    resp = api.start_session(s_second["id"], FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_EQUIPMENT_UNAVAILABLE.value, expected_status=409)


def test_start_session_requires_equipment_available(api):
    """PRD §3.7: "Starting requires the session to currently be `RESERVED` (otherwise
    `ERR_SESSION_NOT_RESERVED`); for a UV session the booked equipment must be
    `AVAILABLE` (otherwise `ERR_EQUIPMENT_UNAVAILABLE`)."

    Design: Difficulty/cross_entity_state_dependency/session_start_requires_equipment_available
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    equipment = fx.create_equipment(name="Maint bed", max_exposure_seconds=600, turnaround_seconds=600)
    fx.set_clock("2026-06-01T10:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Maint Member", skin_type="IV")
    mid = member["id"]
    fx.complete_uv_session(mid, equipment["id"], "2026-06-01T10:00:00Z", 120)  # counter -> 1
    fx.set_clock("2026-06-02T10:00:00Z")
    # Reserve s3 (later slot) while equipment still AVAILABLE.
    s3 = fx.reserve_uv_session(mid, equipment["id"], "2026-06-02T11:00:00Z", 120)
    # Drive equipment into MAINTENANCE via the second completion (different slot).
    fx.complete_uv_session(mid, equipment["id"], "2026-06-02T10:00:00Z", 120)
    eq_after = validate_success(api.get_equipment(equipment["id"], SALON_MANAGER))
    assert eq_after["status"] == "MAINTENANCE"
    # Now starting s3 must fail because the unit is in MAINTENANCE.
    resp = api.start_session(s3["id"], FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_EQUIPMENT_UNAVAILABLE.value, expected_status=409)


# ---------------------------------------------------------------------------
# Cyclic reservation loop + derived count reconciliation
# ---------------------------------------------------------------------------
def test_cancelled_reservation_frees_slot_for_reuse(api):
    """PRD §2.6: "`Session` status (`RESERVED`, `IN_PROGRESS`, `COMPLETED`,
    `CANCELLED`, `NO_SHOW`) is deliberately cyclic at the reservation stage:
    cancelling or no-showing a `RESERVED` session frees its slot so a brand-new
    `RESERVED` session may reuse the same interval."

    Design: Difficulty/non_linear_state_machine/session_cyclic_reserve_cancel_reserve_slot_reuse
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    equipment = fx.create_equipment(name="Cycle bed", max_exposure_seconds=600, turnaround_seconds=600)
    fx.set_clock("2026-06-15T09:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Cycle Member", skin_type="IV")
    mid = member["id"]
    s1 = fx.reserve_uv_session(mid, equipment["id"], "2026-06-15T10:00:00Z", 120)
    cancel_resp = api.cancel_session(s1["id"], make_member_headers(mid))
    cancelled = validate_success(cancel_resp)
    assert cancelled["status"] == "CANCELLED"
    # A fresh reservation at the identical interval now succeeds.
    payload = create_session_payload(
        member_id=mid, kind="UV", booking_mode="RESERVATION",
        equipment_id=equipment["id"], start_at="2026-06-15T10:00:00Z", requested_seconds=120,
    )
    resp = api.create_session(payload, make_member_headers(mid))
    s2 = validate_success(resp, expected_status=201)
    assert s2["status"] == "RESERVED"


def test_no_show_frees_slot_does_not_increment_count(api):
    """PRD §3.7: "A no-show frees the reserved interval but, unlike completion, does
    not increment the member's `completed_uv_session_count`."

    Design: Difficulty/non_linear_state_machine/session_cyclic_reserve_cancel_reserve_slot_reuse
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    equipment = fx.create_equipment(name="NoShow cycle bed", max_exposure_seconds=600, turnaround_seconds=600)
    fx.set_clock("2026-06-15T09:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="NoShow Member", skin_type="IV")
    mid = member["id"]
    s1 = fx.reserve_uv_session(mid, equipment["id"], "2026-06-15T10:00:00Z", 120)
    fx.set_clock("2026-06-15T10:30:00Z")  # past start_at so no-show is allowed
    ns_resp = api.no_show_session(s1["id"], FRONT_DESK)
    assert validate_success(ns_resp)["status"] == "NO_SHOW"
    member_after = validate_success(api.get_member(mid, FRONT_DESK))
    assert member_after["completed_uv_session_count"] == 0
    # Slot freed: a new reservation at the same interval succeeds.
    payload = create_session_payload(
        member_id=mid, kind="UV", booking_mode="RESERVATION",
        equipment_id=equipment["id"], start_at="2026-06-15T10:00:00Z", requested_seconds=120,
    )
    s2 = validate_success(api.create_session(payload, make_member_headers(mid)), expected_status=201)
    assert s2["status"] == "RESERVED"


def test_cancelled_reservation_leaves_completed_count_zero(api):
    """PRD §3.1: "`completed_uv_session_count` is the number of this member's
    sessions with `kind` of `UV` and `status` of `COMPLETED`."

    Design: Corner/cross_cutting_complexity_layers/derived_completed_uv_count_reconciled_on_complete
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    equipment = fx.create_equipment(name="Derived bed", max_exposure_seconds=600)
    fx.set_clock("2026-06-01T10:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Derived Member", skin_type="IV")
    mid = member["id"]
    s = fx.reserve_uv_session(mid, equipment["id"], "2026-06-01T10:00:00Z", 120)
    cancel_resp = api.cancel_session(s["id"], make_member_headers(mid))
    assert validate_success(cancel_resp)["status"] == "CANCELLED"
    member_after = validate_success(api.get_member(mid, FRONT_DESK))
    assert member_after["completed_uv_session_count"] == 0


# ---------------------------------------------------------------------------
# Temporal overlap (difficulty)
# ---------------------------------------------------------------------------
def test_equipment_turnaround_buffer_overlap_rejected(api):
    """PRD §3.6: "The requested half-open interval `[start_at, end_at)`, extended by
    the equipment's `turnaround_seconds` buffer appended after `end_at`, must not
    overlap any existing `RESERVED` or `IN_PROGRESS` session on the same equipment.
    ... a true overlap is rejected with `ERR_EQUIPMENT_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/equipment_turnaround_buffer_adjacency
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    equipment = fx.create_equipment(name="Overlap bed", max_exposure_seconds=600, turnaround_seconds=600)
    fx.set_clock("2026-06-15T09:00:00Z")
    m1 = fx.create_active_member(plan["id"], full_name="M1", skin_type="IV")
    m2 = fx.create_active_member(plan["id"], full_name="M2", skin_type="IV")
    # M1 reserves 10:00:00..10:02:00, unit busy until 10:12:00 (10:02 + 600s).
    fx.reserve_uv_session(m1["id"], equipment["id"], "2026-06-15T10:00:00Z", 120)
    # M2 starts 10:11:00 -> one minute inside the buffer -> overlap.
    payload = create_session_payload(
        member_id=m2["id"], kind="UV", booking_mode="RESERVATION",
        equipment_id=equipment["id"], start_at="2026-06-15T10:11:00Z", requested_seconds=120,
    )
    resp = api.create_session(payload, make_member_headers(m2["id"]))
    validate_error(resp, ApiErrorId.ERR_EQUIPMENT_SLOT_CONFLICT.value, expected_status=409)


def test_equipment_booking_at_exact_buffer_end_admitted(api):
    """PRD §3.6: "Because intervals are half-open, a new booking whose `start_at` is
    exactly at the boundary where a prior session's buffer ends is allowed; a true
    overlap is rejected with `ERR_EQUIPMENT_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/equipment_turnaround_buffer_adjacency
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    equipment = fx.create_equipment(name="Adjacent bed", max_exposure_seconds=600, turnaround_seconds=600)
    fx.set_clock("2026-06-15T09:00:00Z")
    m1 = fx.create_active_member(plan["id"], full_name="A1", skin_type="IV")
    m3 = fx.create_active_member(plan["id"], full_name="A3", skin_type="IV")
    fx.reserve_uv_session(m1["id"], equipment["id"], "2026-06-15T10:00:00Z", 120)
    # M3 starts exactly at 10:12:00 (buffer end) -> admitted.
    payload = create_session_payload(
        member_id=m3["id"], kind="UV", booking_mode="RESERVATION",
        equipment_id=equipment["id"], start_at="2026-06-15T10:12:00Z", requested_seconds=120,
    )
    s3 = validate_success(api.create_session(payload, make_member_headers(m3["id"])), expected_status=201)
    assert s3["status"] == "RESERVED"


def test_spray_room_ventilation_buffer_overlap_rejected(api):
    """PRD §3.6: "Spray bookings undergo the analogous check against the spray room's
    `ventilation_buffer_seconds`, the buffer applied after a spray session's end
    before the room is bookable again, defaulting to 300 seconds (five minutes): the
    requested interval plus that ventilation buffer must not overlap any `RESERVED`
    or `IN_PROGRESS` session on the same room, with adjacency at the exact buffer
    boundary allowed and a real overlap rejected with `ERR_ROOM_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/spray_room_ventilation_buffer_adjacency
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000,
                          weekly_uv_session_cap=0, includes_spray=True)
    room = fx.create_spray_room(name="Room A", ventilation_buffer_seconds=300)
    fx.set_clock("2026-06-15T10:00:00Z")
    m1 = fx.create_active_member(plan["id"], full_name="SM1", skin_type="IV")
    m2 = fx.create_active_member(plan["id"], full_name="SM2", skin_type="IV")
    # M1 reserves 11:00:00..11:05:00, room busy until 11:10:00 (11:05 + 300s).
    fx.reserve_spray_session(m1["id"], room["id"], "2026-06-15T11:00:00Z", 300)
    # M2 at 11:09:00 -> one minute inside the vent buffer -> overlap.
    payload = create_session_payload(
        member_id=m2["id"], kind="SPRAY", booking_mode="RESERVATION",
        spray_room_id=room["id"], start_at="2026-06-15T11:09:00Z", requested_seconds=300,
    )
    payload.pop("equipment_id", None)
    resp = api.create_session(payload, make_member_headers(m2["id"]))
    validate_error(resp, ApiErrorId.ERR_ROOM_SLOT_CONFLICT.value, expected_status=409)


def test_spray_room_booking_at_exact_buffer_end_admitted(api):
    """PRD §3.6: "with adjacency at the exact buffer boundary allowed and a real
    overlap rejected with `ERR_ROOM_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/spray_room_ventilation_buffer_adjacency
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000,
                          weekly_uv_session_cap=0, includes_spray=True)
    room = fx.create_spray_room(name="Room B", ventilation_buffer_seconds=300)
    fx.set_clock("2026-06-15T10:00:00Z")
    m1 = fx.create_active_member(plan["id"], full_name="SB1", skin_type="IV")
    m2 = fx.create_active_member(plan["id"], full_name="SB2", skin_type="IV")
    fx.reserve_spray_session(m1["id"], room["id"], "2026-06-15T11:00:00Z", 300)
    # M2 at exactly 11:10:00 (buffer end) -> admitted.
    payload = create_session_payload(
        member_id=m2["id"], kind="SPRAY", booking_mode="RESERVATION",
        spray_room_id=room["id"], start_at="2026-06-15T11:10:00Z", requested_seconds=300,
    )
    payload.pop("equipment_id", None)
    s2 = validate_success(api.create_session(payload, make_member_headers(m2["id"])), expected_status=201)
    assert s2["status"] == "RESERVED"
