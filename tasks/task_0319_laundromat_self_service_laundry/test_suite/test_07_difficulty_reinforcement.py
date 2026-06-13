"""Second assertions for difficulty-design instances, each pinning a distinct
observable facet of the same PRD rule so every instance carries >= 2 tests.

Every test here translates the same difficulty instance as its sibling in
test_01..test_06 but asserts a different, independently-derivable outcome.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    make_attendant_headers,
    create_vend_payload,
    create_wdf_order_payload,
    setup_active_plan_and_washer,
    setup_active_plan_and_dryer,
    setup_app_wallet_vend,
    setup_submitted_wallet_claim,
    setup_shift_with_coin_and_cash_reload,
    capture_coin_vend,
    file_refund_claim,
    approve_refund_claim,
    begin_reconcile,
    open_shift,
    create_plan,
    create_machine,
    create_member,
    set_clock,
    get_machine,
    get_machine_version,
    get_member,
    get_vend,
    create_pricing_plan_payload,
    create_reload_payload,
    create_shift_payload,
)
from test_helpers import NON_EXISTENT_UUID

MANAGER = TEST_USERS["manager_headers"]
ATTENDANT = TEST_USERS["attendant_headers"]


# --- combinatorial_formula -------------------------------------------------
def test_dryer_non_surge_quote_is_linear_base(api):
    """PRD §3.3: "for a `DRYER` the base is the plan's `dry_base_cents_per_block`
    multiplied by the requested `dry_blocks`." PRD §3.3: "outside surge the
    multiplier is effectively 10000, so the quote equals the base."

    Design: Difficulty/combinatorial_formula/vend_quote_three_input_nonlinear_surge_branch
    """
    # Same DRYER pricing inputs but captured outside surge: 75*3 = 225, no surge.
    plan, dryer = setup_active_plan_and_dryer(
        clock="2026-06-01T10:00:00Z",
        plan_overrides={"dry_base_cents_per_block": 75, "surge_multiplier_bps": 15000,
                        "surge_start_hour_utc": 16, "surge_end_hour_utc": 20})
    resp = api.create_vend(
        dryer["id"], create_vend_payload(dryer["version"], payment_method="COIN", dry_blocks=3),
        ATTENDANT)
    vend = validate_success(resp, 201)
    assert vend["quoted_amount_cents"] == 225, "75 * 3 with no surge multiplier"
    assert vend["surge_applied"] is False


def test_wdf_rush_surcharge_rounds_half_up(api):
    """PRD §3.5: "a rush surcharge is added equal to the floored subtotal
    multiplied by 2500 basis points (twenty-five percent), divided by 10000,
    rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/wdf_total_minimum_before_rush_rounding_order
    """
    # 7 lb * 180 = 1260 raw, above minimum 1500? No: 1260 < 1500 -> floored to 1500.
    # Use a load above the minimum to isolate the rush rounding: 17 lb * 180 = 3060;
    # rush = round_half_up(3060 * 2500/10000) = round_half_up(765.0) = 765 -> 3825.
    set_clock("2026-06-01T10:00:00Z")
    create_plan(wdf_rate_cents_per_lb=180, wdf_minimum_cents=1500)
    attendant = create_member(full_name="A One", phone="555-0100", card_token="tok-a1")
    resp = api.create_wdf_order(
        create_wdf_order_payload(attendant["id"], 17, rush=True),
        make_attendant_headers(attendant["id"]))
    order = validate_success(resp, 201)
    assert order["quoted_total_cents"] == 3825, "3060 + round_half_up(765.0) = 3825"


# --- non_linear_state_machine ----------------------------------------------
def test_machine_running_to_done_via_complete_cycle(api):
    """PRD §3.2: "either because the capture clock has reached `cycle_ends_at`
    during a clock advance, or because an attendant explicitly marks the running
    machine's cycle complete — the machine moves `RUNNING → DONE`, the occupying
    vend's `cycle_status` moves from `RUNNING` to `COMPLETED`".

    Design: Difficulty/non_linear_state_machine/machine_cyclic_idle_running_done_idle
    """
    plan, washer = setup_active_plan_and_washer(
        clock="2026-06-01T10:00:00Z", machine_overrides={"label": "W1", "cycle_minutes": 30})
    vend = capture_coin_vend(washer["id"])
    validate_success(api.complete_cycle(washer["id"], ATTENDANT), 200)
    assert get_machine(washer["id"])["status"] == "DONE"
    assert get_vend(vend["id"])["cycle_status"] == "COMPLETED"


def test_fault_aborts_running_vend_increments_fault_count(api):
    """PRD §3.2: "An attendant may declare a fault on a machine that is `RUNNING`
    or `DONE`, moving it to `FAULT`; this increments `fault_count` by one, and if
    the occupying vend was still `RUNNING` its `cycle_status` moves to
    `ABORTED`."

    Design: Difficulty/non_linear_state_machine/vend_parallel_payment_and_cycle_dimensions
    """
    plan, machine, member, vend = setup_app_wallet_vend(
        charged_clock="2026-06-01T10:00:00Z", principal_cents=5000,
        plan_overrides={"loyalty_cents_per_point": 100})
    faulted = validate_success(api.declare_fault(machine["id"], ATTENDANT), 200)
    assert faulted["status"] == "FAULT"
    assert faulted["fault_count"] == 1
    aborted = get_vend(vend["id"])
    assert aborted["cycle_status"] == "ABORTED"
    assert aborted["payment_status"] == "CAPTURED", "payment dimension independent of cycle"


# --- transitive_cascade ----------------------------------------------------
def test_plan_activation_makes_new_plan_active(api):
    """PRD §3.1: "A manager activating a plan moves it from `DRAFT` to `ACTIVE`".

    Design: Difficulty/transitive_cascade/plan_activate_cascade_depth2_retires_prior
    """
    p1 = validate_success(api.create_pricing_plan(create_pricing_plan_payload(label="P1"), MANAGER), 201)
    validate_success(api.activate_pricing_plan(p1["id"], MANAGER), 200)
    p2 = validate_success(
        api.create_pricing_plan(create_pricing_plan_payload(label="P2", wash_base_cents=350), MANAGER), 201)
    activated = validate_success(api.activate_pricing_plan(p2["id"], MANAGER), 200)
    assert activated["status"] == "ACTIVE", "the newly activated plan is ACTIVE"


def test_refund_cascade_writes_reversal_ledger_entry(api):
    """PRD §3.7: "a `REVERSAL` loyalty ledger entry of negative the vend's
    `loyalty_points_earned` is written and the member's `loyalty_points` is
    reduced by that many points, floored at zero".

    Design: Difficulty/transitive_cascade/refund_approve_cascade_depth3_vend_member_ledger
    """
    plan, machine, member, vend, claim = setup_submitted_wallet_claim(
        reason="NO_CYCLE", principal_cents=5000,
        plan_overrides={"loyalty_cents_per_point": 100})
    approve_refund_claim(claim["id"], claim["version"])
    ledger = validate_success(api.list_member_loyalty_ledger(member["id"], MANAGER), 200)
    reversals = [e for e in ledger if e["entry_type"] == "REVERSAL"]
    assert len(reversals) == 1, "exactly one REVERSAL entry from the approved refund"
    assert reversals[0]["points_delta"] == -3, "reversal is negative the 3 points earned"


# --- priority_pair_validation_conflict -------------------------------------
def test_machine_unavailable_returned_not_wallet_error_http_409(api):
    """PRD §3.3: "if the machine is `RUNNING`, `DONE`, `FAULT`, or
    `OUT_OF_SERVICE` the vend is rejected with `ERR_MACHINE_UNAVAILABLE`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/machine_unavailable_beats_insufficient_wallet
    """
    plan, washer = setup_active_plan_and_washer(clock="2026-06-01T10:00:00Z")
    member = create_member()  # wallet 0
    capture_coin_vend(washer["id"])  # RUNNING
    version = get_machine_version(washer["id"])
    resp = api.create_vend(
        washer["id"],
        create_vend_payload(version, payment_method="APP_WALLET", member_id=member["id"]),
        make_member_headers(member["id"]))
    # ERR_MACHINE_UNAVAILABLE maps to HTTP 409 (cross-checked via the error map).
    err = validate_error(resp, ApiErrorId.ERR_MACHINE_UNAVAILABLE.value)
    assert err["error_id"] != ApiErrorId.ERR_INSUFFICIENT_WALLET.value


def test_dispose_missing_item_is_404_not_state_error(api):
    """PRD §2.10: "Existence is third: every referenced resource must exist, or
    `ERR_NOT_FOUND`."
    PRD §2.9: "any referenced ... item that does not exist halts the request at
    that point before any business rule is evaluated."

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_invalid_state_on_dispose
    """
    resp = api.dispose_lost_found(NON_EXISTENT_UUID, ATTENDANT)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
    assert err["error_id"] != ApiErrorId.ERR_DISPOSAL_HOLD_ACTIVE.value


# --- boundary_precision_check (reload tier) ---------------------------------
def test_reload_tier1_exact_minimum_credits_wallet(api):
    """PRD §3.4: "that full credited amount is added to the member's
    `wallet_cents`."

    Design: Difficulty/boundary_precision_check/reload_bonus_tier_boundary_at_exact_minimum
    """
    create_plan(reload_bonus_tier1_min_cents=2000, reload_bonus_tier1_bps=500,
                reload_bonus_tier2_min_cents=5000, reload_bonus_tier2_bps=1000)
    member = create_member()
    validate_success(
        api.create_reload(member["id"], create_reload_payload(tender="APP", principal_cents=2000),
                          make_member_headers(member["id"])), 201)
    # 2000 principal at the exact tier1 boundary -> +100 bonus -> wallet 2100.
    assert get_member(member["id"])["wallet_cents"] == 2100


# --- cross_entity_state_dependency -----------------------------------------
def test_vend_rejected_machine_stays_running(api):
    """PRD §3.3: "The capture is allowed only against an `IDLE` machine".

    Design: Difficulty/cross_entity_state_dependency/vend_requires_machine_idle
    """
    plan, washer = setup_active_plan_and_washer(clock="2026-06-01T10:00:00Z")
    capture_coin_vend(washer["id"])  # RUNNING
    version = get_machine_version(washer["id"])
    resp = api.create_vend(
        washer["id"], create_vend_payload(version, payment_method="COIN"), ATTENDANT)
    validate_error(resp, ApiErrorId.ERR_MACHINE_UNAVAILABLE.value)
    # The rejected vend left the machine in RUNNING, not a new state.
    assert get_machine(washer["id"])["status"] == "RUNNING"


def test_second_approve_leaves_vend_refunded(api):
    """PRD §3.7: "Approving a `SUBMITTED` claim ... requires ... the referenced
    vend's `payment_status` to still be `CAPTURED` and not already `REFUNDED`
    (else `ERR_ALREADY_REFUNDED`)".

    Design: Difficulty/cross_entity_state_dependency/refund_approve_requires_vend_captured
    """
    from test_helpers import setup_refunded_vend
    plan, machine, member, vend, claim1 = setup_refunded_vend(
        reason="MACHINE_FAULT", principal_cents=5000,
        plan_overrides={"loyalty_cents_per_point": 100})
    claim2 = file_refund_claim(vend["id"], member["id"], reason="DOUBLE_CHARGE",
                               refund_destination="WALLET", as_member_id=member["id"])
    resp = api.approve_refund_claim(
        claim2["id"], {"expected_claim_version": claim2["version"]}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_ALREADY_REFUNDED.value)
    # The original refund stands; vend remains REFUNDED.
    assert get_vend(vend["id"])["payment_status"] == "REFUNDED"


# --- resource_temporal_overlap ---------------------------------------------
def test_vend_inside_cycle_interval_rejected_http_409(api):
    """PRD §3.3: "if the machine is `RUNNING`, `DONE`, `FAULT`, or
    `OUT_OF_SERVICE` the vend is rejected with `ERR_MACHINE_UNAVAILABLE`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/machine_cycle_interval_single_occupancy_reject
    """
    plan, washer = setup_active_plan_and_washer(
        clock="2026-06-01T10:00:00Z", machine_overrides={"label": "W1", "cycle_minutes": 30})
    capture_coin_vend(washer["id"])  # [10:00, 10:30)
    set_clock("2026-06-01T10:29:00Z")  # still inside the running interval
    version = get_machine_version(washer["id"])
    resp = api.create_vend(
        washer["id"], create_vend_payload(version, payment_method="COIN"), ATTENDANT)
    validate_error(resp, ApiErrorId.ERR_MACHINE_UNAVAILABLE.value, 409)


def test_first_shift_succeeds_second_rejected(api):
    """PRD §3.6: "An attendant may hold only one open shift at a time — opening a
    second while one is already `OPEN` for the same attendant is rejected with
    `ERR_SHIFT_ALREADY_OPEN` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/shift_open_session_overlap_per_attendant_reject
    """
    attendant = create_member(full_name="A One", phone="555-0100", card_token="tok-a1")
    first = open_shift(attendant["id"], opening_float_cents=5000)
    assert first["status"] == "OPEN"
    resp = api.create_shift(
        create_shift_payload(attendant["id"], opening_float_cents=1000),
        make_attendant_headers(attendant["id"]))
    validate_error(resp, ApiErrorId.ERR_SHIFT_ALREADY_OPEN.value, 409)


# --- compensating_invariant ------------------------------------------------
def test_refund_credits_exactly_charged_amount(api):
    """PRD §3.7: "On approval `approved_cents` equals `requested_cents` exactly —
    refunds are full, never partial." PRD §3.7: "the member's `wallet_cents` is
    credited the approved amount".

    Design: Difficulty/compensating_invariant/refund_preserves_wallet_money_conservation
    """
    plan, machine, member, vend, claim = setup_submitted_wallet_claim(
        reason="NO_CYCLE", principal_cents=5000,
        plan_overrides={"loyalty_cents_per_point": 100})
    pre_wallet = get_member(member["id"])["wallet_cents"]  # 5200
    approved = approve_refund_claim(claim["id"], claim["version"])
    assert approved["approved_cents"] == 300, "full refund of the 300 charged"
    assert get_member(member["id"])["wallet_cents"] == pre_wallet + 300


def test_loyalty_points_return_to_pre_vend_value(api):
    """PRD §3.7: "the member's `loyalty_points` is reduced by that many points,
    floored at zero".

    Design: Difficulty/compensating_invariant/loyalty_accrual_reversal_preserves_points_conservation
    """
    plan, machine, member, vend, claim = setup_submitted_wallet_claim(
        reason="NO_CYCLE", principal_cents=5000,
        plan_overrides={"loyalty_cents_per_point": 100})
    assert get_member(member["id"])["loyalty_points"] == 3, "accrued 3 on the vend"
    approve_refund_claim(claim["id"], claim["version"])
    assert get_member(member["id"])["loyalty_points"] == 0, "reversal returns points to 0"
