"""Validation precedence, boundary precision, cross-entity dependency, temporal
overlap, and compensating invariants (queue A: Difficulty).
"""
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_error, get_success_data,
    ApiErrorId, fixtures,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["center_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
MIDWIFE = TEST_USERS["midwife_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ===========================================================================
# priority_pair_validation_conflict / ppvc_state_before_risk_on_record_birth
# ===========================================================================
def test_record_birth_on_planning_episode_returns_invalid_state(api):
    """PRD §2.6: "State-validity for a requested transition is checked sixth, producing
    ERR_INVALID_STATE (HTTP 409). The domain-specific business and safety rules described
    throughout Section 3 are evaluated after these foundational layers"
    PRD §3.2: "Recording a birth at the center advances clinical_status from ACTIVE to
    BORN."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_before_risk_on_record_birth
    """
    # Episode kept in PLANNING; risk_tier driven to TRANSFER_REQUIRED via a TRANSFER visit.
    ctx = fixtures.setup_episode_with_completed_visit(risk_flag="TRANSFER", blood_pressure_systolic=130)
    ep_id = ctx["episode"]["id"]
    assert ctx["episode"]["risk_tier"] == "TRANSFER_REQUIRED"

    resp = api.record_birth(ep_id, MIDWIFE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    ep = validate_success(api.get_episode(ep_id, MIDWIFE))
    assert ep["clinical_status"] == "PLANNING", "episode unchanged"


def test_state_precondition_wins_over_risk_gate(api):
    """PRD §2.6: "the same failing request always yields the same error" ... "State-validity
    for a requested transition is checked sixth, producing ERR_INVALID_STATE (HTTP 409).
    The domain-specific business and safety rules described throughout Section 3 are
    evaluated after these foundational layers, each with its own dedicated error code."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_before_risk_on_record_birth
    """
    ctx = fixtures.setup_episode_with_completed_visit(risk_flag="TRANSFER", blood_pressure_systolic=130)
    ep_id = ctx["episode"]["id"]

    resp = api.record_birth(ep_id, MIDWIFE)
    # State check (priority 6) outranks the risk-safety gate (priority 8).
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# priority_pair_validation_conflict / ppvc_state_before_fiscal_on_plan_create
# ===========================================================================
def test_plan_create_on_written_off_episode_returns_invalid_state(api):
    """PRD §3.10: "The plan create is the financial-axis transition into PLAN_ACTIVE, and
    it is allowed only from UNBILLED."
    PRD §2.6: "State-validity for a requested transition is checked sixth, producing
    ERR_INVALID_STATE (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_before_fiscal_on_plan_create
    """
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    validate_success(api.write_off_episode(ep_id, BILLING))
    ep = validate_success(api.get_episode(ep_id, BILLING))
    assert ep["financial_status"] == "WRITTEN_OFF"
    assert ep["balance_due_cents"] == 0

    resp = api.create_payment_plan(
        f.create_payment_plan_payload(ep_id, 2, ep["version"]), BILLING
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_financial_state_precondition_wins_over_no_balance(api):
    """PRD §3.10: "The plan create is the financial-axis transition into PLAN_ACTIVE, and
    it is allowed only from UNBILLED."
    PRD §2.6: "The domain-specific business and safety rules described throughout Section 3
    are evaluated after these foundational layers"

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_before_fiscal_on_plan_create
    """
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    validate_success(api.write_off_episode(ep_id, BILLING))
    ep = validate_success(api.get_episode(ep_id, BILLING))

    resp = api.create_payment_plan(
        f.create_payment_plan_payload(ep_id, 2, ep["version"]), BILLING
    )
    # WRITTEN_OFF is not UNBILLED -> state error wins over the NO_BALANCE fiscal check.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# boundary_precision_check / bpc_bp_transfer_threshold_160
# ===========================================================================
def test_bp_159_yields_elevated_not_transfer(api):
    """PRD §3.7: "otherwise if the highest systolic reading is at least 140, the tier is
    ELEVATED" ... "a systolic reading of exactly 160 already requires transfer, and a
    reading of exactly 140 already raises the tier to elevated."

    Design: Difficulty/boundary_precision_check/bpc_bp_transfer_threshold_160
    """
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    v1 = fixtures.schedule_visit(ep_id, scheduled_at="2026-04-01T10:00:00Z")
    fixtures.complete_visit(v1["id"], risk_flag="NONE", blood_pressure_systolic=159)

    ep = validate_success(api.get_episode(ep_id, MIDWIFE))
    assert ep["risk_tier"] == "ELEVATED", f"bp 159 (< 160) -> ELEVATED, got {ep['risk_tier']}"


def test_bp_160_inclusive_yields_transfer_required(api):
    """PRD §3.7: "otherwise if the highest systolic reading is at least 160, the tier is
    TRANSFER_REQUIRED" ... "a systolic reading of exactly 160 already requires transfer"

    Design: Difficulty/boundary_precision_check/bpc_bp_transfer_threshold_160
    """
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    v1 = fixtures.schedule_visit(ep_id, scheduled_at="2026-04-01T10:00:00Z")
    v2 = fixtures.schedule_visit(ep_id, scheduled_at="2026-04-15T10:00:00Z")
    fixtures.complete_visit(v1["id"], risk_flag="NONE", blood_pressure_systolic=159)
    fixtures.complete_visit(v2["id"], risk_flag="NONE", blood_pressure_systolic=160)

    ep = validate_success(api.get_episode(ep_id, MIDWIFE))
    assert ep["risk_tier"] == "TRANSFER_REQUIRED", \
        f"bp 160 (== threshold, inclusive) -> TRANSFER_REQUIRED, got {ep['risk_tier']}"


# ===========================================================================
# boundary_precision_check / bpc_kit_zero_stock_boundary
# ===========================================================================
def test_last_kit_unit_reserved_drives_available_to_zero(api):
    """PRD §2.10: "A kit's available quantity is its on_hand_count minus its
    reserved_count, and that available quantity must never drop below zero"
    PRD §3.1: "It reserves one unit of the package's birth kit: the kit's reserved_count
    increases by one and the episode's kit_issued flag becomes true."

    Design: Difficulty/boundary_precision_check/bpc_kit_zero_stock_boundary
    """
    kit = fixtures.create_kit(on_hand_count=1)
    package = fixtures.create_package(kit["sku"])
    c1 = fixtures.create_client()
    fixtures.open_episode(package["code"], client_id=c1["id"])

    kit_after = validate_success(api.get_supply_kit(kit["sku"], ADMIN))
    assert kit_after["reserved_count"] == 1, f"reserved_count == 1, got {kit_after['reserved_count']}"
    assert kit_after["on_hand_count"] - kit_after["reserved_count"] == 0, "available == 0"


def test_episode_open_rejected_when_kit_out_of_stock(api):
    """PRD §3.1: "If no unit is available — that is, if reserving would drive the kit's
    on_hand_count minus reserved_count below zero — the open is refused with
    ERR_KIT_OUT_OF_STOCK (HTTP 409)."

    Design: Difficulty/boundary_precision_check/bpc_kit_zero_stock_boundary
    """
    kit = fixtures.create_kit(on_hand_count=1)
    package = fixtures.create_package(kit["sku"])
    c1 = fixtures.create_client()
    c2 = fixtures.create_client(full_name="Bea B", date_of_birth="1992-05-09", parity=1)
    fixtures.open_episode(package["code"], client_id=c1["id"])

    resp = api.create_episode(
        f.create_episode_payload(c2["id"], package_code=package["code"], edd="2026-09-01"), INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_KIT_OUT_OF_STOCK.value)


# ===========================================================================
# cross_entity_state_dependency / cesd_booking_checkin_requires_episode_active
# ===========================================================================
def test_checkin_rejected_while_episode_planning(api):
    """PRD §3.5: "The CenterAdmin then checks in, moving status from CONFIRMED to IN_USE;
    check-in requires that the episode's clinical_status be ACTIVE and that the logical
    clock have reached or passed the booking's starts_at."

    Design: Difficulty/cross_entity_state_dependency/cesd_booking_checkin_requires_episode_active
    """
    ctx = fixtures.setup_episode()  # episode stays PLANNING
    ep_id = ctx["episode"]["id"]
    room = fixtures.create_room(turnover_minutes=0)
    booking = fixtures.create_booking(ep_id, room["id"], room["version"])
    validate_success(api.confirm_booking(booking["id"], ADMIN))
    validate_success(api.set_clock("2026-01-02T01:00:00Z", ADMIN))

    resp = api.check_in_booking(booking["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    bk = validate_success(api.get_booking(booking["id"], ADMIN))
    assert bk["status"] == "CONFIRMED", "booking unchanged"


def test_checkin_succeeds_once_episode_active(api):
    """PRD §3.5: "The CenterAdmin then checks in, moving status from CONFIRMED to IN_USE;
    check-in requires that the episode's clinical_status be ACTIVE and that the logical
    clock have reached or passed the booking's starts_at."

    Design: Difficulty/cross_entity_state_dependency/cesd_booking_checkin_requires_episode_active
    """
    ctx = fixtures.setup_active_episode()  # episode ACTIVE
    ep_id = ctx["episode"]["id"]
    room = fixtures.create_room(turnover_minutes=0)
    booking = fixtures.create_booking(ep_id, room["id"], room["version"])
    validate_success(api.confirm_booking(booking["id"], ADMIN))
    validate_success(api.set_clock("2026-01-02T01:00:00Z", ADMIN))

    checked_in = validate_success(api.check_in_booking(booking["id"], ADMIN))
    assert checked_in["status"] == "IN_USE", \
        f"check-in succeeds while episode ACTIVE, got {checked_in['status']}"


def test_oncall_release_rejected_while_episode_active(api):
    """PRD §3.4: "A primary assignment is released when coverage is no longer needed,
    moving from either ASSIGNED or ON_DUTY to RELEASED; release requires that the
    assignment be PRIMARY and that the episode's clinical_status be one of BORN,
    COMPLETED, or TRANSFERRED"

    Design: Difficulty/cross_entity_state_dependency/cesd_oncall_release_requires_episode_terminal_clinical
    """
    ctx = fixtures.setup_primary_assignment(max_active_episodes=2)
    asg_id = ctx["assignment"]["id"]

    resp = api.release_assignment(asg_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    asg = validate_success(api.get_on_call_assignment(asg_id, ADMIN))
    assert asg["status"] == "ASSIGNED", "assignment unchanged"


def test_oncall_release_succeeds_after_episode_transferred(api):
    """PRD §3.4: "release requires that the assignment be PRIMARY and that the episode's
    clinical_status be one of BORN, COMPLETED, or TRANSFERRED, and it decrements the
    provider's active_assignment_count by one."

    Design: Difficulty/cross_entity_state_dependency/cesd_oncall_release_requires_episode_terminal_clinical
    """
    ctx = fixtures.setup_primary_assignment(max_active_episodes=2)
    ep_id = ctx["episode"]["id"]
    asg_id = ctx["assignment"]["id"]
    # Transfer moves episode to TRANSFERRED and stands the primary down; create a fresh
    # primary that we can then release once the episode is terminal-clinical.
    # Instead, reach a terminal clinical state without standing this assignment down:
    # drive the episode to BORN via an IN_USE booking.
    room = fixtures.create_room(turnover_minutes=0)
    booking = fixtures.create_booking(ep_id, room["id"], room["version"])
    validate_success(api.confirm_booking(booking["id"], ADMIN))
    validate_success(api.set_clock("2026-01-02T01:00:00Z", ADMIN))
    validate_success(api.check_in_booking(booking["id"], ADMIN))
    validate_success(api.record_birth(ep_id, MIDWIFE))  # episode -> BORN

    released = validate_success(api.release_assignment(asg_id, ADMIN))
    assert released["status"] == "RELEASED", \
        f"release succeeds once episode in {{BORN, COMPLETED, TRANSFERRED}}, got {released['status']}"


# ===========================================================================
# resource_temporal_overlap / rto_room_halfopen_turnover_buffer
# ===========================================================================
def test_booking_inside_turnover_buffer_rejected(api):
    """PRD §3.9: "When turnover_minutes is greater than 0, the next booking must start at
    or after the previous booking's ends_at plus that many minutes of turnover; starting
    any earlier is a collision. A violation is refused with ERR_ROOM_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/rto_room_halfopen_turnover_buffer
    """
    kit, package = fixtures.create_catalog()
    c1 = fixtures.create_client()
    c2 = fixtures.create_client(full_name="Bea B", date_of_birth="1992-05-09", parity=1)
    e1 = fixtures.open_episode(package["code"], client_id=c1["id"])
    e2 = fixtures.open_episode(package["code"], client_id=c2["id"], edd="2026-09-01")
    room = fixtures.create_room(turnover_minutes=30)

    fixtures.create_booking(e1["id"], room["id"], room["version"],
                            starts_at="2026-01-02T00:00:00Z", ends_at="2026-01-02T06:00:00Z")
    room_v1 = validate_success(api.get_room(room["id"], ADMIN))["version"]

    # Second booking starts exactly at the first booking's ends_at -> inside 30-min buffer.
    resp = api.create_booking(
        f.create_booking_payload(e2["id"], room["id"], room_v1,
                                 starts_at="2026-01-02T06:00:00Z", ends_at="2026-01-02T08:00:00Z"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED.value)


def test_booking_at_or_after_turnover_succeeds(api):
    """PRD §3.9: "When turnover_minutes is greater than 0, the next booking must start at
    or after the previous booking's ends_at plus that many minutes of turnover"

    Design: Difficulty/resource_temporal_overlap/rto_room_halfopen_turnover_buffer
    """
    kit, package = fixtures.create_catalog()
    c1 = fixtures.create_client()
    c2 = fixtures.create_client(full_name="Bea B", date_of_birth="1992-05-09", parity=1)
    e1 = fixtures.open_episode(package["code"], client_id=c1["id"])
    e2 = fixtures.open_episode(package["code"], client_id=c2["id"], edd="2026-09-01")
    room = fixtures.create_room(turnover_minutes=30)

    fixtures.create_booking(e1["id"], room["id"], room["version"],
                            starts_at="2026-01-02T00:00:00Z", ends_at="2026-01-02T06:00:00Z")
    room_v1 = validate_success(api.get_room(room["id"], ADMIN))["version"]

    # Start at ends_at + 30 min -> exactly at the buffer boundary -> allowed.
    booking2 = validate_success(api.create_booking(
        f.create_booking_payload(e2["id"], room["id"], room_v1,
                                 starts_at="2026-01-02T06:30:00Z", ends_at="2026-01-02T08:00:00Z"),
        ADMIN,
    ), expected_status=201)
    assert booking2["status"] == "HELD"


# ===========================================================================
# resource_temporal_overlap / rto_provider_window_closed_touching_collides
# ===========================================================================
def test_provider_window_touching_endpoint_collides(api):
    """PRD §3.9: "Because the interval is closed, touching endpoints count as a collision:
    if one window's coverage_end exactly equals another window's coverage_start, that is a
    conflict. There is no buffer between coverage windows. A violation is refused with
    ERR_PROVIDER_WINDOW_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/rto_provider_window_closed_touching_collides
    """
    kit, package = fixtures.create_catalog()
    c1 = fixtures.create_client()
    c2 = fixtures.create_client(full_name="Bea B", date_of_birth="1992-05-09", parity=1)
    e1 = fixtures.open_episode(package["code"], client_id=c1["id"])
    e2 = fixtures.open_episode(package["code"], client_id=c2["id"], edd="2026-09-01")
    pri = fixtures.create_provider(max_active_episodes=3)

    fixtures.assign_primary(e1["id"], pri["id"],
                            coverage_start="2026-07-01T00:00:00Z", coverage_end="2026-07-10T10:00:00Z")

    resp = api.create_on_call_assignment(
        f.create_on_call_assignment_payload(
            e2["id"], pri["id"],
            coverage_start="2026-07-10T10:00:00Z", coverage_end="2026-07-20T00:00:00Z"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_PROVIDER_WINDOW_OVERLAP.value)


def test_provider_non_touching_window_succeeds(api):
    """PRD §3.4: "And the new coverage window must not overlap any of that provider's
    existing primary windows ... with a conflict refused as ERR_PROVIDER_WINDOW_OVERLAP"
    PRD §3.9: "Because the interval is closed, touching endpoints count as a collision"

    Design: Difficulty/resource_temporal_overlap/rto_provider_window_closed_touching_collides
    """
    kit, package = fixtures.create_catalog()
    c1 = fixtures.create_client()
    c2 = fixtures.create_client(full_name="Bea B", date_of_birth="1992-05-09", parity=1)
    e1 = fixtures.open_episode(package["code"], client_id=c1["id"])
    e2 = fixtures.open_episode(package["code"], client_id=c2["id"], edd="2026-09-01")
    pri = fixtures.create_provider(max_active_episodes=3)

    fixtures.assign_primary(e1["id"], pri["id"],
                            coverage_start="2026-07-01T00:00:00Z", coverage_end="2026-07-10T10:00:00Z")

    # Start strictly after the prior window's end -> no collision.
    asg2 = validate_success(api.create_on_call_assignment(
        f.create_on_call_assignment_payload(
            e2["id"], pri["id"],
            coverage_start="2026-07-10T10:00:01Z", coverage_end="2026-07-20T00:00:00Z"),
        ADMIN,
    ), expected_status=201)
    assert asg2["coverage_role"] == "PRIMARY"


# ===========================================================================
# compensating_invariant / ci_kit_total_conserved_on_transfer
# ===========================================================================
def test_kit_reserved_before_transfer(api):
    """PRD §3.1: "It reserves one unit of the package's birth kit: the kit's reserved_count
    increases by one and the episode's kit_issued flag becomes true."

    Design: Difficulty/compensating_invariant/ci_kit_total_conserved_on_transfer
    """
    kit = fixtures.create_kit(on_hand_count=1)
    package = fixtures.create_package(kit["sku"])
    client = fixtures.create_client()
    episode = fixtures.open_episode(package["code"], client_id=client["id"])
    validate_success(api.activate_episode(episode["id"], MIDWIFE))

    kit_state = validate_success(api.get_supply_kit(kit["sku"], ADMIN))
    assert kit_state["reserved_count"] == 1 and kit_state["consumed_count"] == 0
    assert kit_state["on_hand_count"] == 1


def test_kit_total_conserved_reserve_to_consumed_on_transfer(api):
    """PRD §3.8: "The kit reserved for this episode is treated as consumed and is
    non-recoverable once transfer occurs: the kit's reserved_count decreases by one and
    its consumed_count increases by one."

    Design: Difficulty/compensating_invariant/ci_kit_total_conserved_on_transfer
    """
    kit = fixtures.create_kit(on_hand_count=1)
    package = fixtures.create_package(kit["sku"])
    client = fixtures.create_client()
    episode = fixtures.open_episode(package["code"], client_id=client["id"])
    validate_success(api.activate_episode(episode["id"], MIDWIFE))

    validate_success(api.transfer_episode(episode["id"], MIDWIFE))

    kit_state = validate_success(api.get_supply_kit(kit["sku"], ADMIN))
    assert kit_state["reserved_count"] == 0, f"reserved 1 -> 0, got {kit_state['reserved_count']}"
    assert kit_state["consumed_count"] == 1, f"consumed 0 -> 1, got {kit_state['consumed_count']}"
    assert kit_state["on_hand_count"] == 1, "on_hand unchanged"
    assert kit_state["reserved_count"] + kit_state["consumed_count"] == 1


# ===========================================================================
# compensating_invariant / ci_provider_coverage_conserved_on_promote
# ===========================================================================
def test_provider_loads_before_transfer(api):
    """PRD §3.4: "the provider's active_assignment_count increments by one." (primary
    assignment create) ... "A BACKUP row still sitting in ASSIGNED does not count toward
    primary load."

    Design: Difficulty/compensating_invariant/ci_provider_coverage_conserved_on_promote
    """
    ctx = fixtures.setup_primary_with_backup(max_active_episodes=2)
    pri = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    bak = validate_success(api.get_provider(ctx["backup_provider"]["id"], ADMIN))
    assert pri["active_assignment_count"] == 1
    assert bak["active_assignment_count"] == 0


def test_provider_coverage_conserved_on_transfer_promote(api):
    """PRD §3.8: "Standing a primary down decrements that primary provider's
    active_assignment_count by one. If that primary names a backup through its
    backup_assignment_id, the referenced backup assignment — a BACKUP row in ASSIGNED — is
    promoted to PROMOTED, and the promotion increments the backup provider's
    active_assignment_count by one."

    Design: Difficulty/compensating_invariant/ci_provider_coverage_conserved_on_promote
    """
    ctx = fixtures.setup_primary_with_backup(max_active_episodes=2)
    ep_id = ctx["episode"]["id"]
    pri_id = ctx["provider"]["id"]
    bak_id = ctx["backup_provider"]["id"]

    validate_success(api.transfer_episode(ep_id, MIDWIFE))

    pri = validate_success(api.get_provider(pri_id, ADMIN))
    bak = validate_success(api.get_provider(bak_id, ADMIN))
    assert pri["active_assignment_count"] == 0, f"PRI 1 -> 0, got {pri['active_assignment_count']}"
    assert bak["active_assignment_count"] == 1, f"BAK 0 -> 1, got {bak['active_assignment_count']}"
    assert pri["active_assignment_count"] + bak["active_assignment_count"] == 1, \
        "total active primary coverage conserved at 1"
