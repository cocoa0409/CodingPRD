"""Design-center selections: cutoff windows, confirm/unconfirm cycling, change
fees, and the options_total aggregation (PRD §2.10, §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_option_selection,
    complete_milestones_in_order,
    confirm_selection,
    create_community,
    create_option_item,
    create_selection,
    get_selection,
    make_buyer_headers,
    setup_draft_agreement,
    setup_signed_agreement,
    unconfirm_selection,
    validate_error,
    validate_paginated,
    validate_success,
)

AGENT = TEST_USERS["sales_agent_headers"]
DIRECTOR = TEST_USERS["sales_director_headers"]


def _get_agreement(agreement_id):
    return validate_success(api_client.get_agreement(agreement_id, AGENT), 200)


def test_option_selection_read_paths_and_not_found():
    """PRD §2.10: "The first unresolvable identifier produces its dedicated 404:
    `ERR_COMMUNITY_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_OPTION_ITEM_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_SELECTION_NOT_FOUND`,
    `ERR_MILESTONE_NOT_FOUND`, or `ERR_INCENTIVE_NOT_FOUND`."
    PRD §3.5: "Selection listings may be filtered by `agreement_id`,
    `option_item_id`, or `status`."

    Design: Corner/errors/option_selection_read_paths_and_not_found
    """
    bundle = setup_draft_agreement()

    resp = api_client.get_option_selection(NON_EXISTENT_UUID, AGENT)
    validate_error(resp, ApiErrorId.ERR_SELECTION_NOT_FOUND, 404)

    data, meta = validate_paginated(
        api_client.list_option_selections(
            AGENT, params={"agreement_id": bundle["agreement"]["id"]}
        )
    )
    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_options_total_tracks_select_and_cancel():
    """PRD §3.5: "The agreement's `options_total_cents` — the sum of
    `line_total_cents` over its selections in `SELECTED`, `CONFIRMED`, or
    `INSTALLED` status — absorbs the new line, and the agreement's `version`
    increments alongside the selection's creation."
    PRD §3.5: "Cancelling a merely-`SELECTED` line is free regardless of
    stage."
    PRD §3.5: "Either way the line leaves the options total —
    `options_total_cents` is recomputed without it — and both selection and
    agreement increment their `version`."

    Design: Corner/calculations/options_total_tracks_select_and_cancel
    """
    bundle = setup_signed_agreement(with_quartz=True, with_ev=True)
    agreement_id = bundle["agreement"]["id"]
    buyer_id = bundle["buyer"]["id"]

    create_selection(agreement_id, bundle["quartz"]["id"], buyer_id)
    ev = create_selection(
        agreement_id, bundle["ev"]["id"], buyer_id, quantity=2
    )
    assert_option_selection(ev)
    assert ev["unit_price_cents"] == 150_000, "unit price snapshotted at selection"
    assert ev["line_total_cents"] == 300_000, "line total = unit price * quantity"
    assert ev["status"] == "SELECTED"
    assert ev["change_fee_cents"] == 0

    agreement = _get_agreement(agreement_id)
    assert agreement["options_total_cents"] == 1_100_000, (
        "800,000 + 300,000; SELECTED lines count toward the total"
    )

    cancelled = validate_success(
        api_client.cancel_selection(ev["id"], make_buyer_headers(buyer_id)), 200
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "BUYER_REQUEST"
    assert cancelled["change_fee_cents"] == 0, "cancelling SELECTED is always free"

    agreement = _get_agreement(agreement_id)
    assert agreement["options_total_cents"] == 800_000
    assert agreement["change_fees_total_cents"] == 0


def test_confirm_unconfirm_confirm_cycle_no_fee():
    """PRD §3.5: "While still inside the free window, a confirmation can be
    undone: re-opening a `CONFIRMED` line returns it to `SELECTED` and clears
    `confirmed_at_stage`."
    PRD §3.5: "Confirmation stamps `confirmed_at_stage` with the agreement's
    current stage and never charges a fee — a stale `SELECTED` line cannot
    survive into a past-cutoff stage, because the milestone sweep of §3.6
    cancels it first, so no confirm can ever occur past cutoff."

    Design: Difficulty/non_linear_state_machine/option_selection_confirm_unconfirm_cycle
    """
    bundle = setup_signed_agreement(with_ev=True)
    buyer_id = bundle["buyer"]["id"]
    selection = create_selection(
        bundle["agreement"]["id"], bundle["ev"]["id"], buyer_id
    )

    confirmed = confirm_selection(selection["id"], buyer_id)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["confirmed_at_stage"] == "PRE_CONSTRUCTION"

    reopened = unconfirm_selection(selection["id"], buyer_id)
    assert reopened["status"] == "SELECTED"
    assert reopened["confirmed_at_stage"] is None

    reconfirmed = confirm_selection(selection["id"], buyer_id)
    assert reconfirmed["status"] == "CONFIRMED", (
        "SELECTED -> CONFIRMED -> SELECTED -> CONFIRMED loop completes"
    )
    assert reconfirmed["confirmed_at_stage"] == "PRE_CONSTRUCTION"
    assert reconfirmed["change_fee_cents"] == 0, (
        "all transitions inside the free window: no fee accrues"
    )

    agreement = _get_agreement(bundle["agreement"]["id"])
    assert agreement["options_total_cents"] == 150_000, (
        "options total is constant across the confirm/unconfirm cycle"
    )
    assert agreement["change_fees_total_cents"] == 0


def test_unconfirm_clears_confirmed_stage_and_keeps_totals():
    """PRD §3.5: "While still inside the free window, a confirmation can be
    undone: re-opening a `CONFIRMED` line returns it to `SELECTED` and clears
    `confirmed_at_stage`."
    PRD §3.5: "The agreement's `options_total_cents` — the sum of
    `line_total_cents` over its selections in `SELECTED`, `CONFIRMED`, or
    `INSTALLED` status — absorbs the new line, and the agreement's `version`
    increments alongside the selection's creation."

    Design: Difficulty/non_linear_state_machine/option_selection_confirm_unconfirm_cycle
    """
    bundle = setup_signed_agreement(with_ev=True)
    buyer_id = bundle["buyer"]["id"]
    selection = create_selection(
        bundle["agreement"]["id"], bundle["ev"]["id"], buyer_id
    )

    confirm_selection(selection["id"], buyer_id)
    reopened = unconfirm_selection(selection["id"], buyer_id)
    assert reopened["status"] == "SELECTED"
    assert reopened["confirmed_at_stage"] is None, "unconfirm clears the stamp"
    assert reopened["change_fee_cents"] == 0

    agreement = _get_agreement(bundle["agreement"]["id"])
    assert agreement["options_total_cents"] == 150_000, (
        "SELECTED and CONFIRMED both count, so the loop never moves the total"
    )
    assert agreement["change_fees_total_cents"] == 0


def test_unconfirm_free_at_exact_cutoff_equality():
    """PRD §3.5: "The same cutoff comparison guards the re-open — once the
    agreement's `current_stage` ordinal has moved strictly past the item's
    `cutoff_stage` ordinal, unconfirming is rejected with
    `ERR_OPTION_CUTOFF_PASSED`; at exact stage equality the window is still
    open."

    Design: Difficulty/boundary_precision_check/option_unconfirm_free_at_cutoff_equality
    """
    bundle = setup_signed_agreement(with_quartz=True)
    buyer_id = bundle["buyer"]["id"]
    agreement_id = bundle["agreement"]["id"]
    selection = create_selection(agreement_id, bundle["quartz"]["id"], buyer_id)
    confirm_selection(selection["id"], buyer_id)

    # One completion: current_stage FOUNDATION == cutoff FOUNDATION (equality).
    complete_milestones_in_order(agreement_id, 1)
    reopened = unconfirm_selection(selection["id"], buyer_id)
    assert reopened["status"] == "SELECTED", (
        "at exact stage equality the free window is still open"
    )
    assert reopened["change_fee_cents"] == 0

    confirm_selection(selection["id"], buyer_id)
    # Second completion: current_stage FRAMING, strictly past cutoff FOUNDATION.
    complete_milestones_in_order(agreement_id, 1)
    agreement = _get_agreement(agreement_id)
    assert agreement["current_stage"] == "FRAMING"

    resp = api_client.unconfirm_selection(
        selection["id"], make_buyer_headers(buyer_id)
    )
    validate_error(resp, ApiErrorId.ERR_OPTION_CUTOFF_PASSED)
    after = get_selection(selection["id"])
    assert after["status"] == "CONFIRMED", "rejected unconfirm leaves the line alone"
    assert after["change_fee_cents"] == 0


def test_unconfirm_past_cutoff_rejected_and_selection_unchanged():
    """PRD §3.5: "The same cutoff comparison guards the re-open — once the
    agreement's `current_stage` ordinal has moved strictly past the item's
    `cutoff_stage` ordinal, unconfirming is rejected with
    `ERR_OPTION_CUTOFF_PASSED`; at exact stage equality the window is still
    open."

    Design: Difficulty/boundary_precision_check/option_unconfirm_free_at_cutoff_equality
    """
    bundle = setup_signed_agreement(with_quartz=True)
    buyer_id = bundle["buyer"]["id"]
    agreement_id = bundle["agreement"]["id"]
    selection = create_selection(agreement_id, bundle["quartz"]["id"], buyer_id)
    confirm_selection(selection["id"], buyer_id)  # confirmed at PRE_CONSTRUCTION

    complete_milestones_in_order(agreement_id, 2)  # -> current_stage FRAMING
    resp = api_client.unconfirm_selection(
        selection["id"], make_buyer_headers(buyer_id)
    )
    validate_error(resp, ApiErrorId.ERR_OPTION_CUTOFF_PASSED)

    after = get_selection(selection["id"])
    assert after["status"] == "CONFIRMED"
    assert after["confirmed_at_stage"] == "PRE_CONSTRUCTION"
    agreement = _get_agreement(agreement_id)
    assert agreement["change_fees_total_cents"] == 0
    assert agreement["options_total_cents"] == 800_000


def test_selection_create_past_cutoff_reports_temporal_over_referential():
    """PRD §2.10: "Every request is evaluated against an ordered cascade of
    checks; the first failing tier determines the error response, and later
    tiers are not evaluated."
    PRD §2.10 (tier 8, Time and stage windows): "reservation holds, option
    cutoff windows, and price-phase window overlap: `ERR_LOT_HOLD_ACTIVE`,
    `ERR_OPTION_CUTOFF_PASSED`, or `ERR_PHASE_WINDOW_OVERLAP`."
    PRD §2.10 (tier 10, In-community cross-references): "referenced plans,
    elevations, and option items must belong to the same community as the deal,
    else `ERR_PLAN_NOT_IN_COMMUNITY`, `ERR_ELEVATION_NOT_AVAILABLE`, or
    `ERR_OPTION_NOT_IN_COMMUNITY`."

    Design: Difficulty/priority_pair_validation_conflict/selection_create_temporal_beats_referential
    """
    bundle = setup_signed_agreement()
    agreement_id = bundle["agreement"]["id"]
    buyer_id = bundle["buyer"]["id"]
    complete_milestones_in_order(agreement_id, 2)  # -> current_stage FRAMING

    other = create_community(name="Aspen Grove")
    foreign = create_option_item(
        other["id"], option_name="Guest Suite", category="STRUCTURAL",
        price_cents=5_000_000, cutoff_stage="PRE_CONSTRUCTION",
        install_stage="FRAMING",
    )
    # FRAMING is strictly past cutoff PRE_CONSTRUCTION (temporal fails) AND the
    # item belongs to another community (referential fails): tier 8 wins.
    resp = api_client.create_option_selection(
        {"agreement_id": agreement_id, "option_item_id": foreign["id"],
         "quantity": 1},
        make_buyer_headers(buyer_id),
    )
    validate_error(resp, ApiErrorId.ERR_OPTION_CUTOFF_PASSED)


def test_selection_create_foreign_item_inside_cutoff_reports_referential():
    """PRD §3.5: "The option item must belong to the same community as the
    agreement (else `ERR_OPTION_NOT_IN_COMMUNITY`, HTTP 422), and the
    agreement's `current_stage` must not have moved past the item's
    `cutoff_stage` — selection is free while the current stage's ordinal is at
    or below the cutoff stage's ordinal, and once the ordinal ordering places
    `current_stage` strictly beyond `cutoff_stage` the create is rejected with
    `ERR_OPTION_CUTOFF_PASSED`."

    Design: Difficulty/priority_pair_validation_conflict/selection_create_temporal_beats_referential
    """
    bundle = setup_signed_agreement()
    agreement_id = bundle["agreement"]["id"]
    buyer_id = bundle["buyer"]["id"]
    complete_milestones_in_order(agreement_id, 2)  # -> current_stage FRAMING

    other = create_community(name="Aspen Grove")
    foreign = create_option_item(
        other["id"], option_name="Guest Suite", category="STRUCTURAL",
        price_cents=5_000_000, cutoff_stage="DRYWALL", install_stage="FINAL_WALKTHROUGH",
    )
    # FRAMING is not past DRYWALL, so the temporal tier passes and the
    # in-community cross-reference tier reports the violation.
    resp = api_client.create_option_selection(
        {"agreement_id": agreement_id, "option_item_id": foreign["id"],
         "quantity": 1},
        make_buyer_headers(buyer_id),
    )
    validate_error(resp, ApiErrorId.ERR_OPTION_NOT_IN_COMMUNITY, 422)


def test_selection_installed_cancel_rejected():
    """PRD §3.5: "Cancelling a selection is always possible from `SELECTED` or
    `CONFIRMED` — any other state, including `INSTALLED`, is rejected with
    `ERR_SELECTION_INVALID_STATE` — and always records `cancel_reason`
    `BUYER_REQUEST`."
    PRD §3.6: "Second, every selection in `CONFIRMED` whose option's
    `install_stage` ordinal now lies strictly behind the new stage becomes
    `INSTALLED`."

    Design: Corner/state_machines/selection_installed_cancel_rejected
    """
    bundle = setup_signed_agreement(with_ev=True)
    buyer_id = bundle["buyer"]["id"]
    agreement_id = bundle["agreement"]["id"]
    selection = create_selection(agreement_id, bundle["ev"]["id"], buyer_id)
    confirm_selection(selection["id"], buyer_id)

    complete_milestones_in_order(agreement_id, 5)  # -> current_stage COMPLETE
    installed = get_selection(selection["id"])
    assert installed["status"] == "INSTALLED", (
        "COMPLETE lies strictly behind install_stage FINAL_WALKTHROUGH"
    )

    resp = api_client.cancel_selection(
        selection["id"], make_buyer_headers(buyer_id)
    )
    validate_error(resp, ApiErrorId.ERR_SELECTION_INVALID_STATE)

    agreement = _get_agreement(agreement_id)
    assert agreement["options_total_cents"] == 150_000, (
        "INSTALLED lines still count toward the options total"
    )


def test_confirmed_cancel_past_cutoff_accrues_change_fee():
    """PRD §3.5: "Cancelling a `CONFIRMED` line is free inside the cutoff window
    but incurs a change fee once the agreement's `current_stage` ordinal is
    strictly past the item's `cutoff_stage` ordinal: the fee is ten percent of
    the line's `line_total_cents`, rounded half up to whole cents, recorded in
    the selection's `change_fee_cents` and added to the agreement's
    `change_fees_total_cents`."

    Design: Corner/calculations/confirmed_cancel_past_cutoff_accrues_change_fee
    """
    bundle = setup_signed_agreement(with_ev=True)
    buyer_id = bundle["buyer"]["id"]
    agreement_id = bundle["agreement"]["id"]
    selection = create_selection(
        agreement_id, bundle["ev"]["id"], buyer_id, quantity=2
    )
    confirm_selection(selection["id"], buyer_id)

    # current_stage FINAL_WALKTHROUGH: strictly past cutoff DRYWALL, but not
    # strictly past install_stage FINAL_WALKTHROUGH, so the line stays CONFIRMED.
    complete_milestones_in_order(agreement_id, 4)
    before = get_selection(selection["id"])
    assert before["status"] == "CONFIRMED"

    cancelled = validate_success(
        api_client.cancel_selection(selection["id"], make_buyer_headers(buyer_id)),
        200,
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "BUYER_REQUEST"
    # round_half_up(300,000 * 0.10) = 30,000
    assert cancelled["change_fee_cents"] == 30_000

    agreement = _get_agreement(agreement_id)
    assert agreement["change_fees_total_cents"] == 30_000
    assert agreement["options_total_cents"] == 0, (
        "the cancelled line leaves the options total"
    )
