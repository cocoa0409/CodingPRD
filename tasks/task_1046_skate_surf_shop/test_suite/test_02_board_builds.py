"""Board-build pricing, the revision cycle, and build-state guards.

Covers the dual provisional-vs-final price variants, the pinned per-line rounding
order, the ASSEMBLED->DRAFT revision loop and its reservation release, and the
invalid-transition / terminal-lockdown state checks.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, create_build_in_state, get_success_data,
)

SM = TEST_USERS["shop_manager_headers"]
ASSOC = TEST_USERS["associate_headers"]

# Five buildable products at these list prices, one line qty 1 each, PRO member.
FIVE_LINE_SPEC = [
    {"price": 6000, "qty": 1, "stock": 5, "category": "DECK"},
    {"price": 4000, "qty": 1, "stock": 5, "category": "TRUCK"},
    {"price": 3500, "qty": 1, "stock": 5, "category": "WHEELS"},
    {"price": 2000, "qty": 1, "stock": 5, "category": "BEARINGS"},
    {"price": 1000, "qty": 1, "stock": 5, "category": "GRIP"},
]


def test_build_provisional_total_raw_sum(api):
    """PRD §3.3: "the build's `provisional_total_cents` is computed as the plain sum
    over the component lines of the product's `unit_price_cents` times the line
    quantity — raw list price, with no discount and no setup fee."

    Design: Difficulty/dual_variant_calc/build_price_provisional_vs_final
    """
    build, member, products = create_build_in_state(
        api, target_state="COMPONENTS_RESERVED", lines_spec=FIVE_LINE_SPEC,
        member_tier="PRO")
    assert build["provisional_total_cents"] == 16500


def test_build_final_total_discounted_plus_setup_fee(api):
    """PRD §3.3: "for each line, take the product's `unit_price_cents`, multiply by
    one minus the member's tier discount rate (0 for `STANDARD`, 0.10 for `PRO`,
    0.20 for `TEAM`), round that discounted per-unit price half-up to a whole cent,
    then multiply the rounded per-unit price by the line quantity; sum those per-line
    totals across all lines and add a flat setup fee of 2500 cents."

    Design: Difficulty/dual_variant_calc/build_price_provisional_vs_final
    """
    build, member, products = create_build_in_state(
        api, target_state="SETUP_COMPLETE", lines_spec=FIVE_LINE_SPEC,
        member_tier="PRO")
    assert build["provisional_total_cents"] == 16500
    assert build["final_total_cents"] == 17350


def test_build_final_price_rounds_per_line_before_multiply(api):
    """PRD §3.3: "The rounding order is pinned — round the discounted unit price
    first, then multiply by quantity, then sum."

    Design: Difficulty/combinatorial_formula/build_final_price_round_per_line_then_sum
    """
    build, member, products = create_build_in_state(
        api, target_state="SETUP_COMPLETE",
        lines_spec=[{"price": 105, "qty": 3, "stock": 5, "category": "GRIP"}],
        member_tier="PRO")
    # round_half_up(105*0.9)=round_half_up(94.5)=95; 95*3=285; +2500 setup = 2785.
    assert build["final_total_cents"] == 2785


def test_build_final_price_persisted_rounded_value(api):
    """PRD §3.3: "Setting up (allowed only from `ASSEMBLED`) computes the build's
    `final_total_cents` and stamps `setup_at`."

    Design: Difficulty/combinatorial_formula/build_final_price_round_per_line_then_sum
    """
    build, member, products = create_build_in_state(
        api, target_state="SETUP_COMPLETE",
        lines_spec=[{"price": 105, "qty": 3, "stock": 5, "category": "GRIP"}],
        member_tier="PRO")
    persisted = get_success_data(api.get_board_build(build["id"], SM))
    assert persisted["status"] == "SETUP_COMPLETE"
    assert persisted["final_total_cents"] == 2785


def test_revise_returns_build_to_draft(api):
    """PRD §3.3: "Revising returns it to `DRAFT`: this is the compensating action for
    reserve, so each component product's `stock_reserved` is lowered back by the line
    quantity, and both `provisional_total_cents` and `assembled_at` are cleared to null."

    Design: Difficulty/non_linear_state_machine/board_build_revision_cycle
    """
    build, member, products = create_build_in_state(
        api, target_state="ASSEMBLED",
        lines_spec=[{"price": 3000, "qty": 1, "stock": 3}])
    resp = api.revise_board_build(build["id"], ASSOC)
    data = validate_success(resp, 200)
    assert data["status"] == "DRAFT"
    assert data["provisional_total_cents"] is None


def test_revise_releases_component_reservation(api):
    """PRD §3.3: "Revising returns it to `DRAFT`: this is the compensating action for
    reserve, so each component product's `stock_reserved` is lowered back by the line
    quantity, and both `provisional_total_cents` and `assembled_at` are cleared to null."

    Design: Difficulty/non_linear_state_machine/board_build_revision_cycle
    """
    build, member, products = create_build_in_state(
        api, target_state="ASSEMBLED",
        lines_spec=[{"price": 3000, "qty": 1, "stock": 3}])
    prod = products[0]
    before = get_success_data(api.get_product(prod["id"], SM))
    assert before["stock_reserved"] == 1
    api.revise_board_build(build["id"], ASSOC)
    after = get_success_data(api.get_product(prod["id"], SM))
    assert after["stock_reserved"] == 0


def test_assemble_draft_build_invalid_state(api):
    """PRD §3.3: "From `COMPONENTS_RESERVED`, assembling the board (allowed only from
    that state) stamps `assembled_at`."
    PRD §2.5: "the target resource is in a state from which the transition is allowed
    (`ERR_INVALID_STATE`, 409)".

    Design: Corner/state_machines/assemble_from_draft_returns_invalid_state
    """
    build, member, products = create_build_in_state(api, target_state="DRAFT")
    resp = api.assemble_board_build(build["id"], ASSOC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    unchanged = get_success_data(api.get_board_build(build["id"], SM))
    assert unchanged["status"] == "DRAFT"


def test_cancel_completed_build_invalid_state(api):
    """PRD §3.3: "`COMPLETED` and `CANCELLED` are terminal."
    PRD §2.5: "the target resource is in a state from which the transition is allowed
    (`ERR_INVALID_STATE`, 409)".

    Design: Corner/state_machines/cancel_completed_build_terminal_lockdown_returns_invalid_state
    """
    build, member, products = create_build_in_state(api, target_state="COMPLETED")
    resp = api.cancel_board_build(build["id"], ASSOC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    unchanged = get_success_data(api.get_board_build(build["id"], SM))
    assert unchanged["status"] == "COMPLETED"
