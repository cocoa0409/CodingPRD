"""Redemption lifecycle: quote, confirm, fulfill, cancel.

Covers the quoted-vs-final dual cost variant, per-line round-then-sum rounding,
the CONFIRMED fork to FULFILLED or CANCELLED, FIFO burn cascade, and the
redemption-shape / reward-availability / stock validations.
"""
from test_helpers import (
    TEST_USERS,
    get_success_data,
    validate_paginated,
    set_clock,
    setup_program,
    create_program,
    define_tiers,
    register_member,
    post_purchase,
    get_member,
    add_reward,
    quote_redemption,
    confirm_redemption,
    setup_confirmed_redemption,
    redemption_line,
    validate_error,
    ApiErrorId,
    STANDARD_ONLY,
    STANDARD_SILVER_GOLD,
    STANDARD_GOLD,
)

ADMIN = TEST_USERS["program_admin_headers"]


# ---------------------------------------------------------------------------
# Dual cost variant — quoted (SILVER, no discount) vs final (GOLD, discount)
# ---------------------------------------------------------------------------
def test_quoted_vs_final_cost_diverge_on_tier_crossing(api):
    """PRD 3.7: "Fulfillment recomputes the cost as a *final* variant, re-resolving the member's `current_tier_code` at fulfillment time and recomputing each line's discount from that tier; the result is `final_cost_points`. If the member crossed the `GOLD` rank boundary between quote and fulfillment, the discount toggles and `final_cost_points` will differ from `quoted_cost_points`."

    Reward point_cost 1000, tier_discount_pct 0.2. Quote at SILVER (no GOLD
    discount) gives quoted_cost_points 1000; after crossing to GOLD the final
    discount applies: round_half_up(1*1000*(1-0.2)) = 800.

    Design: Difficulty/dual_variant_calc/redemption_quoted_vs_final_cost_diverge_on_tier_crossing
    """
    base = setup_program(tiers=STANDARD_SILVER_GOLD, clock="2026-01-10T00:00:00Z")
    prog = base["program"]
    reward = add_reward(prog["id"], point_cost=1000, tier_discount_pct=0.2, stock=5)
    member = register_member(prog["id"])
    post_purchase(member["id"], 300000)   # qualifying 3000 => SILVER
    red = quote_redemption(member["id"], [redemption_line(reward["id"], 1)])
    assert red["quoted_cost_points"] == 1000, \
        f"Expected quoted 1000, got {red['quoted_cost_points']}"
    confirm_redemption(red["id"], member["id"])
    post_purchase(member["id"], 200000)   # qualifying window 5000 => GOLD

    fulfilled = get_success_data(api.fulfill_redemption(red["id"], ADMIN))
    assert fulfilled["final_cost_points"] == 800, \
        f"Expected final 800, got {fulfilled['final_cost_points']}"
    assert fulfilled["quoted_cost_points"] != fulfilled["final_cost_points"]


def test_fulfill_refunds_difference_when_final_below_quoted(api):
    """PRD 3.7: "When `final_cost_points` is less than `quoted_cost_points`, the platform refunds the difference by minting a refund lot (sourced as an `EARN_BONUS` lot) of `quoted_cost_points` minus `final_cost_points` and appending an `EARN_BONUS` `PointsTransaction`."

    The member is SILVER at quote and GOLD at fulfill, so the refund is
    quoted(1000) - final(800) = 200. Balances (base_earn_rate 1.0):
      - purchase 300000c at STANDARD (tier resolved before earn): 3000 earned;
        qualifying 3000 => SILVER. available 3000.
      - confirm burns quoted 1000 => available 2000.
      - purchase 200000c at SILVER (1.25 earn_multiplier, resolved before earn):
        floor(2000*1.0*1.25) = 2500 earned; qualifying window 5000 => GOLD.
        available 2000+2500 = 4500.
      - fulfill at GOLD: final 800, refund 200 => available 4700.

    Design: Difficulty/dual_variant_calc/redemption_quoted_vs_final_cost_diverge_on_tier_crossing
    """
    base = setup_program(tiers=STANDARD_SILVER_GOLD, clock="2026-01-10T00:00:00Z")
    prog = base["program"]
    reward = add_reward(prog["id"], point_cost=1000, tier_discount_pct=0.2, stock=5)
    member = register_member(prog["id"])
    post_purchase(member["id"], 300000)   # STANDARD->earn 3000; qualifying 3000 => SILVER
    red = quote_redemption(member["id"], [redemption_line(reward["id"], 1)])
    confirm_redemption(red["id"], member["id"])   # burns 1000 => available 2000
    post_purchase(member["id"], 200000)   # SILVER 1.25 mult -> earn 2500; window 5000 => GOLD
    get_success_data(api.fulfill_redemption(red["id"], ADMIN))   # refund 200

    member = get_member(member["id"])
    assert member["available_points"] == 4700, \
        f"Expected 4700 after 200-point refund, got {member['available_points']}"


# ---------------------------------------------------------------------------
# Per-line round-then-sum — MODE (b)
# ---------------------------------------------------------------------------
def test_redemption_line_round_then_sum(api):
    """PRD 2.7: "The rounding is applied **per line** — each line's real-valued cost is rounded half up to a whole number of points — and only then are the rounded line totals summed."

    Two GOLD lines, each point_cost 101 with tier_discount_pct 0.5:
    round_half_up(1*101*0.5) = round_half_up(50.5) = 51 per line, summed = 102.

    Design: Difficulty/combinatorial_formula/redemption_line_round_then_sum_mode_b
    """
    base = setup_program(tiers=STANDARD_GOLD, clock="2026-01-10T00:00:00Z")
    prog = base["program"]
    r1 = add_reward(prog["id"], name="R1", point_cost=101, tier_discount_pct=0.5, stock=9)
    r2 = add_reward(prog["id"], name="R2", point_cost=101, tier_discount_pct=0.5, stock=9)
    member = register_member(prog["id"])
    post_purchase(member["id"], 500000)   # GOLD
    red = quote_redemption(member["id"],
                           [redemption_line(r1["id"], 1), redemption_line(r2["id"], 1)])
    assert red["quoted_cost_points"] == 102, \
        f"Expected quoted 102 (51+51), got {red['quoted_cost_points']}"


def test_redemption_line_cost_points_per_line(api):
    """PRD 3.7: "The line's cost is then the line `quantity` multiplied by the reward's `point_cost` multiplied by one minus the applicable discount, with the result rounded half up to a whole number of points."

    Each GOLD line of point_cost 101 at discount 0.5 has line_cost_points == 51.

    Design: Difficulty/combinatorial_formula/redemption_line_round_then_sum_mode_b
    """
    base = setup_program(tiers=STANDARD_GOLD, clock="2026-01-10T00:00:00Z")
    prog = base["program"]
    r1 = add_reward(prog["id"], name="R1", point_cost=101, tier_discount_pct=0.5, stock=9)
    r2 = add_reward(prog["id"], name="R2", point_cost=101, tier_discount_pct=0.5, stock=9)
    member = register_member(prog["id"])
    post_purchase(member["id"], 500000)
    red = quote_redemption(member["id"],
                           [redemption_line(r1["id"], 1), redemption_line(r2["id"], 1)])
    lines, _ = validate_paginated(api.list_redemption_lines(red["id"], ADMIN))
    by_reward = {ln["reward_id"]: ln for ln in lines}
    assert by_reward[r1["id"]]["line_cost_points"] == 51, \
        f"Expected R1 line 51, got {by_reward[r1['id']]['line_cost_points']}"
    assert by_reward[r2["id"]]["line_cost_points"] == 51, \
        f"Expected R2 line 51, got {by_reward[r2['id']]['line_cost_points']}"


# ---------------------------------------------------------------------------
# Fork-join: CONFIRMED -> CANCELLED (compensating mint refunds)
# ---------------------------------------------------------------------------
def test_confirmed_cancel_compensates_and_restores_balance(api):
    """PRD 3.7: "Cancelling from `CONFIRMED` is a compensating action: because the confirm already burned `quoted_cost_points`, cancellation mints a single compensating `EARN_BONUS` `PointsLot` of `quoted_cost_points` back to the member and appends a compensating `EARN_BONUS` `PointsTransaction` (with a positive `points_delta` and `ref_redemption_id` set to this redemption), recomputes the member's balances to restore point conservation, and moves the redemption to `CANCELLED`."

    Member with 1000 points confirms a 600-point redemption (available drops to
    400) then cancels; the compensating mint restores available_points to 1000.

    Design: Difficulty/non_linear_state_machine/redemption_fork_join_confirmed_branches_to_fulfilled_or_cancelled
    """
    s = setup_confirmed_redemption(reward_point_cost=600, purchase_cents=100000)
    member, red = s["member"], s["redemption"]
    assert red["status"] == "CONFIRMED"
    cancelled = get_success_data(api.cancel_redemption(red["id"], ADMIN))
    assert cancelled["status"] == "CANCELLED", \
        f"Expected CANCELLED, got {cancelled['status']}"
    member = get_member(member["id"])
    assert member["available_points"] == 1000, \
        f"Expected 1000 restored, got {member['available_points']}"


def test_confirmed_fulfill_reaches_terminal_and_decrements_stock(api):
    """PRD 3.7: "Fulfillment then decrements each line's reward `stock` by the line `quantity`, recomputes the member's balances, and moves the redemption to the terminal `FULFILLED` status."

    A CONFIRMED redemption fulfilled by an admin reaches FULFILLED and the reward's
    stock drops by the line quantity (5 -> 4 for quantity 1).

    Design: Difficulty/non_linear_state_machine/redemption_fork_join_confirmed_branches_to_fulfilled_or_cancelled
    """
    s = setup_confirmed_redemption(reward_point_cost=600, reward_stock=5, purchase_cents=100000)
    red, reward = s["redemption"], s["reward"]
    fulfilled = get_success_data(api.fulfill_redemption(red["id"], ADMIN))
    assert fulfilled["status"] == "FULFILLED", f"Expected FULFILLED, got {fulfilled['status']}"
    rewards, _ = validate_paginated(api.list_rewards(s["program"]["id"], ADMIN))
    found = [r for r in rewards if r["id"] == reward["id"]]
    assert found and found[0]["stock"] == 4, \
        f"Expected stock 4 after fulfillment, got {found[0]['stock'] if found else 'missing'}"


# ---------------------------------------------------------------------------
# Transitive cascade depth-2: FIFO burn exhausts oldest lot
# ---------------------------------------------------------------------------
def test_confirm_fifo_burn_exhausts_oldest_lot(api):
    """PRD 3.7: "On confirmation the platform burns `quoted_cost_points` from the member's lots in first-in-first-out order — oldest `created_at` first, breaking ties between identical timestamps by lot id ascending — decrementing each consumed lot's `remaining_points` and moving a lot to `EXHAUSTED` the moment its `remaining_points` reaches 0."

    Lot A=600 (older) and lot B=300 (newer); a 700-point burn exhausts A
    completely and draws 100 from B, leaving available_points == 200.

    Design: Difficulty/transitive_cascade/confirm_fifo_burn_exhausts_first_lot_recomputes_balance_depth2
    """
    base = setup_program(clock="2026-01-10T00:00:00Z")
    prog = base["program"]
    reward = add_reward(prog["id"], point_cost=700, tier_discount_pct=0.0, stock=5)
    member = register_member(prog["id"])
    post_purchase(member["id"], 60000)   # lot A = 600, created 2026-01-10
    set_clock("2026-01-12T00:00:00Z")
    post_purchase(member["id"], 30000)   # lot B = 300, created 2026-01-12
    red = quote_redemption(member["id"], [redemption_line(reward["id"], 1)])
    confirmed = confirm_redemption(red["id"], member["id"])
    assert confirmed["status"] == "CONFIRMED"

    member = get_member(member["id"])
    assert member["available_points"] == 200, \
        f"Expected 200 after burning 700, got {member['available_points']}"


def test_confirm_burn_marks_oldest_lot_exhausted(api):
    """PRD 3.7: "moving a lot to `EXHAUSTED` the moment its `remaining_points` reaches 0."

    After a 700-point FIFO burn, the oldest 600-point lot is EXHAUSTED with
    remaining_points 0.

    Design: Difficulty/transitive_cascade/confirm_fifo_burn_exhausts_first_lot_recomputes_balance_depth2
    """
    from test_helpers import validate_paginated
    base = setup_program(clock="2026-01-10T00:00:00Z")
    prog = base["program"]
    reward = add_reward(prog["id"], point_cost=700, tier_discount_pct=0.0, stock=5)
    member = register_member(prog["id"])
    post_purchase(member["id"], 60000)
    set_clock("2026-01-12T00:00:00Z")
    post_purchase(member["id"], 30000)
    red = quote_redemption(member["id"], [redemption_line(reward["id"], 1)])
    confirm_redemption(red["id"], member["id"])

    lots, _ = validate_paginated(api.list_member_lots(member["id"], ADMIN))
    exhausted = [lot for lot in lots if lot["original_points"] == 600]
    assert exhausted, "expected the 600-point lot to be present"
    assert exhausted[0]["status"] == "EXHAUSTED", \
        f"Expected EXHAUSTED, got {exhausted[0]['status']}"
    assert exhausted[0]["remaining_points"] == 0, \
        f"Expected remaining 0, got {exhausted[0]['remaining_points']}"


# ---------------------------------------------------------------------------
# Empty redemption rejected (boundary)
# ---------------------------------------------------------------------------
def test_empty_redemption_rejected(api):
    """PRD 3.7: "A redemption submitted with no lines is rejected with `ERR_EMPTY_REDEMPTION` (HTTP 422), and a line whose `quantity` is below 1 is rejected with `ERR_INVALID_QUANTITY` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/empty_redemption_zero_lines_rejected
    """
    base = setup_program()
    member = register_member(base["program"]["id"])
    resp = api.create_redemption({"member_id": member["id"], "lines": []}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_EMPTY_REDEMPTION.value)


def test_single_line_redemption_accepted(api):
    """PRD 3.7: "A `Member` or `ProgramAdmin` opens a redemption by quoting it against a program that is `ACTIVE`, supplying the burning `member_id` and a set of `lines`, each line naming a `reward_id` and a `quantity` of at least 1."

    The one-line boundary just above the empty-redemption floor is accepted: a
    redemption with exactly one valid line quotes successfully in QUOTED status.

    Design: Difficulty/boundary_precision_check/empty_redemption_zero_lines_rejected
    """
    base = setup_program()
    prog = base["program"]
    reward = add_reward(prog["id"], point_cost=100, stock=5)
    member = register_member(prog["id"])
    post_purchase(member["id"], 100000)
    resp = api.create_redemption(
        {"member_id": member["id"], "lines": [redemption_line(reward["id"], 1)]}, ADMIN)
    red = get_success_data(resp)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"
    assert red["status"] == "QUOTED", f"Expected QUOTED, got {red['status']}"


def test_redemption_line_zero_quantity_rejected(api):
    """PRD 3.7: "a line whose `quantity` is below 1 is rejected with `ERR_INVALID_QUANTITY` (HTTP 422)."

    Design: Corner/errors/redemption_line_zero_quantity_returns_422
    """
    base = setup_program()
    prog = base["program"]
    reward = add_reward(prog["id"], point_cost=100, stock=5)
    member = register_member(prog["id"])
    resp = api.create_redemption(
        {"member_id": member["id"], "lines": [{"reward_id": reward["id"], "quantity": 0}]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_QUANTITY.value)


def test_redemption_discontinued_reward_rejected(api):
    """PRD 3.7: "a line pointing at a `DISCONTINUED` reward or one outside the member's program is rejected with `ERR_REWARD_UNAVAILABLE` (HTTP 409)."

    Design: Corner/validations/reward_discontinued_in_redemption_returns_409
    """
    # Reward must be discontinued BEFORE activation, mirroring the design recipe.
    prog = create_program()
    define_tiers(prog["id"], STANDARD_ONLY)
    reward = add_reward(prog["id"], point_cost=600, stock=5)
    get_success_data(api.discontinue_reward(reward["id"], ADMIN))
    get_success_data(api.activate_program(prog["id"], ADMIN))
    member = register_member(prog["id"])
    post_purchase(member["id"], 100000)
    resp = api.create_redemption(
        {"member_id": member["id"], "lines": [redemption_line(reward["id"], 1)]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_REWARD_UNAVAILABLE.value)


def test_fulfill_insufficient_stock_rejected(api):
    """PRD 3.7: "It requires that every line's reward still be `ACTIVE` and that every line's reward have `stock` at least the line `quantity`; insufficient stock at fulfillment is rejected with `ERR_INSUFFICIENT_STOCK` (HTTP 409)."

    Reward stock 1, line quantity 2: the redemption quotes and confirms, but
    fulfillment fails the stock check.

    Design: Corner/validations/fulfill_insufficient_stock_returns_409
    """
    base = setup_program()
    prog = base["program"]
    reward = add_reward(prog["id"], point_cost=100, stock=1)
    member = register_member(prog["id"])
    post_purchase(member["id"], 100000)
    red = quote_redemption(member["id"], [redemption_line(reward["id"], 2)])
    confirm_redemption(red["id"], member["id"])
    resp = api.fulfill_redemption(red["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)


def test_cancel_fulfilled_redemption_invalid_state(api):
    """PRD 3.7: "Both cancellation paths require the redemption to be in a
    cancellable state and otherwise yield the invalid-state rejection of Section
    2.8."
    PRD 2.8: "When a state-transition endpoint is invoked against a target that is not in a state from which that transition is legal — a redemption, referral, partner transfer, promotion, points lot, or transfer blackout in the wrong state — the request is rejected with `ERR_INVALID_STATE` (HTTP 409), except where a more specific code is named for that transition (for example program activation, below)."

    Design: Corner/state_machines/cancel_already_fulfilled_redemption_returns_invalid_state
    """
    s = setup_confirmed_redemption(reward_point_cost=600, reward_stock=5, purchase_cents=60000)
    red = s["redemption"]
    get_success_data(api.fulfill_redemption(red["id"], ADMIN))   # -> FULFILLED (terminal)
    resp = api.cancel_redemption(red["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
