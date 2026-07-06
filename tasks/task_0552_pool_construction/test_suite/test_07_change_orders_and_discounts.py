"""Change orders: apply preconditions, volume-discount tiering, and apply/reverse conservation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, assert_ledger_conservation,
    setup_proposed_change_order, setup_change_order_tiered, setup_change_order_applied,
)


def test_apply_unapproved_change_order_rejected(api, builder_headers):
    """PRD §3.6: "The builder then applies an approved change, moving APPROVED to APPLIED; applying
    a change whose status is not APPROVED is rejected with ERR_CHANGE_ORDER_NOT_APPROVED."

    Design: Corner/state_machines/change_order_apply_before_approved_rejected
    """
    project, co = setup_proposed_change_order()  # PROPOSED, never approved
    res = api.transition_change_order(co["id"], {"action": "APPLY"}, builder_headers)
    validate_error(res, ApiErrorId.ERR_CHANGE_ORDER_NOT_APPROVED)


def test_discount_tier_read_from_cumulative_applied_base(api, builder_headers):
    """PRD §3.6: "first, compute the cumulative pre-discount base as the sum of price_delta_cents
    over the project's already-APPLIED change orders whose price_delta_cents is greater than zero,
    excluding this change order itself. Second, read the discount tier from that cumulative base
    before adding this change: if the cumulative base is below 500,000 cents the discount is 0%; if
    it is at least 500,000 cents but below 1,500,000 cents the discount is 3%; if it is 1,500,000
    cents or more the discount is 5%. Third, set the applied delta: when this change's
    price_delta_cents is greater than zero, applied_delta_cents is price_delta_cents multiplied by
    one minus the discount rate, rounded half-up to whole cents".

    Design: Difficulty/combinatorial_formula/change_order_discount_evaluation_order_mode_c
    """
    project, co1, co2 = setup_change_order_tiered()  # co1 (+600000) APPLIED, co2 (+400000) APPROVED
    validate_success(api.transition_change_order(co2["id"], {"action": "APPLY"}, builder_headers), 200)
    # co1 applied when the cumulative base was 0 -> tier 0% -> full 600000.
    co1_after = validate_success(api.get_change_order(co1["id"], builder_headers), 200)
    assert co1_after["applied_delta_cents"] == 600000
    # co2 reads cumulative base 600000 -> tier 3% -> round(400000 * 0.97) = 388000.
    co2_after = validate_success(api.get_change_order(co2["id"], builder_headers), 200)
    assert co2_after["applied_delta_cents"] == 388000


def test_applied_deltas_roll_up_into_contract_amount(api, builder_headers):
    """PRD §3.6: "Fourth, the project's contract_amount_cents increases by applied_delta_cents".
    PRD §3.6: "Across all applied change orders, the project's contract_amount_cents always equals
    the original signed contract_price_cents plus the sum of applied_delta_cents over every change
    currently in APPLIED status."

    Design: Difficulty/combinatorial_formula/change_order_discount_evaluation_order_mode_c
    """
    project, co1, co2 = setup_change_order_tiered()
    validate_success(api.transition_change_order(co2["id"], {"action": "APPLY"}, builder_headers), 200)
    # base 1000000 + 600000 (co1) + 388000 (co2 after 3% discount) = 1988000.
    project_after = validate_success(api.get_pool_project(project["id"], builder_headers), 200)
    assert project_after["contract_amount_cents"] == 1988000


def test_reverse_conserves_contract_dollars(api, builder_headers):
    """PRD §3.6: "Reversing an applied change undoes exactly what was posted. The project's
    contract_amount_cents decreases by the same applied_delta_cents that was posted at apply time".
    PRD §2.8: "at all times amount_remaining_cents equals contract_amount_cents minus
    amount_disbursed_cents minus retainage_held_cents".

    Design: Difficulty/compensating_invariant/change_order_apply_reverse_conserves_contract_dollars
    """
    project, co = setup_change_order_applied()  # contract 1000000, +600000 applied
    reversed_co = validate_success(api.transition_change_order(co["id"], {"action": "REVERSE"},
                                                              builder_headers), 200)
    assert reversed_co["status"] == "REVERSED"
    project_after = validate_success(api.get_pool_project(project["id"], builder_headers), 200)
    assert project_after["contract_amount_cents"] == 1000000
    assert project_after["amount_remaining_cents"] == 1000000
    assert_ledger_conservation(project_after)


def test_reverse_decreases_contract_by_exact_applied_delta(api, builder_headers):
    """PRD §3.6: "Reversing an applied change undoes exactly what was posted. The project's
    contract_amount_cents decreases by the same applied_delta_cents that was posted at apply time".

    Design: Difficulty/compensating_invariant/change_order_apply_reverse_conserves_contract_dollars
    """
    project, co = setup_change_order_applied()
    assert co["applied_delta_cents"] == 600000
    before = validate_success(api.get_pool_project(project["id"], builder_headers), 200)
    assert before["contract_amount_cents"] == 1600000
    validate_success(api.transition_change_order(co["id"], {"action": "REVERSE"}, builder_headers), 200)
    after = validate_success(api.get_pool_project(project["id"], builder_headers), 200)
    assert after["contract_amount_cents"] == 1000000
