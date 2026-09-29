"""Core exchange: provisional versus assayed credit, the dispute cycle and the release."""
import pytest

from test_helpers import (
    validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    setup_inspected_core_return, setup_submitted_core_return, setup_delivered_order,
    setup_dispatched_shipment, setup_account_in_credit_hold,
    create_core_return, inspect_core_return, dispute_core_return, credit_core_return,
    read_core_return, read_account, read_order, read_order_line,
)

REP = TEST_USERS["sales_rep_headers"]
OPERATOR = TEST_USERS["warehouse_operator_headers"]


def _inspected_return_of_ten_flooded_cores():
    return setup_inspected_core_return(
        quantity=10, core_expected_count=10, declared_core_count=10,
        accepted_core_count=10, lot_overrides={"quantity_on_hand": 60},
        account_overrides={"name": "Delta Fleet", "storm_priority_rank": 5},
    )


def test_assayed_final_credit_diverges_from_the_flat_provisional_figure():
    """PRD §3.6: "And the **provisional** credit is booked:
    `provisional_credit_cents` is simply the declared core count multiplied by
    the model's `core_deposit_cents`. This provisional figure values every
    declared core at the flat deposit, ignores lead assay and lateness entirely,
    is written once and is never overwritten."
    PRD §3.6: "Concretely, the deposit valuation is the accepted core count
    multiplied by the model's `core_deposit_cents`; the gross credit is
    whichever is larger, that deposit valuation or the `scrap_value_cents` from
    the last inspection; the penalty is 25 percent of the gross, rounded half up
    to whole cents, when `late_return` is true and zero otherwise; and
    `final_credit_cents` is the gross less the penalty."

    Design: Difficulty/dual_variant_calc/core_credit_provisional_vs_assayed_final_diverge
    """
    env = _inspected_return_of_ten_flooded_cores()
    assert env["core_return"]["provisional_credit_cents"] == 22000

    credited = credit_core_return(env["core_return"]["id"])

    assert credited["lead_recovered_kg"] == pytest.approx(120.625, abs=0.0005)
    assert credited["scrap_value_cents"] == 23643
    assert credited["final_credit_cents"] == 23643, \
        f"The scrap valuation beats the deposit valuation, got {credited['final_credit_cents']}"
    assert credited["final_credit_cents"] != credited["provisional_credit_cents"], \
        "The two variants must differ on these inputs"


def test_crediting_a_return_releases_the_deposit_and_banks_the_lead():
    """PRD §3.6: "**Hop two** applies it: the account's
    `core_deposit_balance_cents` is reduced by `final_credit_cents`, floored at
    0 so the liability never goes negative, and the account's
    `lifetime_lead_recovered_kg` increases by the return's `lead_recovered_kg`."
    PRD §3.6: "Issuing the credit is a sales representative's or an
    administrator's action on a return standing in `INSPECTED`, and it drives a
    four-hop cascade."

    Design: Difficulty/dual_variant_calc/core_credit_provisional_vs_assayed_final_diverge
    """
    env = _inspected_return_of_ten_flooded_cores()
    credited = credit_core_return(env["core_return"]["id"])
    assert credited["status"] == "CREDITED"

    account = read_account(env["account"]["id"])
    assert account["core_deposit_balance_cents"] == 0, \
        f"The liability is floored at 0, got {account['core_deposit_balance_cents']}"
    assert account["lifetime_lead_recovered_kg"] == pytest.approx(120.625, abs=0.0005)


# --------------------------------------------------------------------------
# The inspect / dispute cycle
# --------------------------------------------------------------------------

def _return_disputed_after_a_partial_first_round():
    env = setup_submitted_core_return(
        quantity=10, core_expected_count=10, declared_core_count=10,
        lot_overrides={"quantity_on_hand": 60},
        account_overrides={"name": "Delta Fleet", "storm_priority_rank": 5},
    )
    env["round_one"] = inspect_core_return(env["core_return"]["id"], 8)
    env["disputed"] = dispute_core_return(
        env["core_return"]["id"],
        "Eight of ten cores were graded as case-cracked; buyer contests grading.",
    )
    return env


def test_dispute_cycle_returns_the_row_to_inspected_with_a_higher_round():
    """PRD §3.6: "A successful dispute moves the return `INSPECTED → DISPUTED`,
    and the next inspection carries it back to `INSPECTED` — or to `REJECTED` if
    nothing is accepted that round — incrementing the round counter again.
    `INSPECTED → DISPUTED → INSPECTED` is a genuine cycle, bounded only by that
    round ceiling."
    PRD §3.6: "Inspection is admissible from `SUBMITTED` and from `DISPUTED`
    alike, which is what makes the cycle work, and the accepted count may not
    exceed the declared count — a larger value is a malformed request refused
    with `ERR_INVALID_REQUEST`."

    Design: Difficulty/non_linear_state_machine/core_return_dispute_cycle_reenters_inspected
    """
    env = _return_disputed_after_a_partial_first_round()
    assert env["disputed"]["status"] == "DISPUTED"

    round_two = inspect_core_return(env["core_return"]["id"], 10)
    assert round_two["status"] == "INSPECTED"
    assert round_two["inspection_round"] == 2, \
        f"Every inspection increments the round, got {round_two['inspection_round']}"


def test_re_inspection_overwrites_the_previous_rounds_assay():
    """PRD §3.6: "A re-inspection after a dispute overwrites
    `accepted_core_count`, `lead_recovered_kg` and `scrap_value_cents` with the
    new round's values; only the latest round survives."
    PRD §3.6: "An accepted count of at least 1 moves the return to `INSPECTED`
    and runs the lead assay: `lead_recovered_kg` is the accepted count
    multiplied by the model's `lead_content_kg` multiplied by a recovery yield
    of 0.965 — the smelter returns 96.5 percent of the lead in the case —
    rounded half up to three decimals; and `scrap_value_cents` is that
    already-rounded lead mass multiplied by 196 cents per kilogram, rounded half
    up to whole cents."

    Design: Difficulty/non_linear_state_machine/core_return_dispute_cycle_reenters_inspected
    """
    env = _return_disputed_after_a_partial_first_round()
    assert env["round_one"]["lead_recovered_kg"] == pytest.approx(96.500, abs=0.0005)

    inspect_core_return(env["core_return"]["id"], 10)

    stored = read_core_return(env["core_return"]["id"])
    assert stored["accepted_core_count"] == 10
    assert stored["lead_recovered_kg"] == pytest.approx(120.625, abs=0.0005)
    assert stored["scrap_value_cents"] == 23643


# --------------------------------------------------------------------------
# The credit cascade mirrors the delivery cascade
# --------------------------------------------------------------------------

def _credited_return_against_the_held_account():
    env = setup_account_in_credit_hold()
    env["core_return"] = create_core_return(
        env["account"]["id"], env["order_b"]["id"], env["model"]["id"], 12
    )
    env["core_return"] = inspect_core_return(env["core_return"]["id"], 12)
    return env


def test_core_credit_takes_the_larger_deposit_valuation_and_clears_the_balance():
    """PRD §3.6: "The `late_return` flag is true when the calendar date on which
    the return was created is strictly after the earliest non-null `core_due_by`
    among the source order's lines for this model — so a return arriving on the
    due date itself is not late, and lateness is possible without the window
    being closed, because the window allows 30 further days of grace."
    PRD §3.6: "the gross credit is whichever is larger, that deposit valuation
    or the `scrap_value_cents` from the last inspection"

    Design: Difficulty/transitive_cascade/core_credit_cascade_releases_hold_and_reclears_sibling
    """
    env = _credited_return_against_the_held_account()
    assert env["core_return"]["late_return"] is False

    credited = credit_core_return(env["core_return"]["id"])
    assert credited["lead_recovered_kg"] == pytest.approx(231.600, abs=0.0005)
    assert credited["scrap_value_cents"] == 45394
    assert credited["final_credit_cents"] == 600000, \
        f"The deposit valuation wins here, got {credited['final_credit_cents']}"
    assert credited["status"] == "CREDITED"

    account = read_account(env["account"]["id"])
    assert account["core_deposit_balance_cents"] == 0
    assert account["lifetime_lead_recovered_kg"] == pytest.approx(231.600, abs=0.0005)


def test_core_credit_releases_the_hold_and_reclears_the_sibling_order():
    """PRD §3.6: "**Hop three** reacts to the reduced liability: if the account's
    core-deposit balance now stands below 500000 cents and the account's
    `status` is `CREDIT_HOLD`, the account returns to `ACTIVE`."
    PRD §3.6: "**Hop four** reacts to that release: every order belonging to
    that account whose `credit_status` is `HELD` moves back to `CLEARED`, and
    allocation becomes possible again for those orders."

    Design: Difficulty/transitive_cascade/core_credit_cascade_releases_hold_and_reclears_sibling
    """
    env = _credited_return_against_the_held_account()
    assert read_account(env["account"]["id"])["status"] == "CREDIT_HOLD"
    assert read_order(env["order_a"]["id"])["credit_status"] == "HELD"

    credit_core_return(env["core_return"]["id"])

    assert read_account(env["account"]["id"])["status"] == "ACTIVE"
    order_a = read_order(env["order_a"]["id"])
    assert order_a["credit_status"] == "CLEARED"
    assert order_a["fulfillment_status"] == "SUBMITTED", \
        "The release never touches the fulfilment dimension"


# --------------------------------------------------------------------------
# Cores may only come back from a delivered order
# --------------------------------------------------------------------------

def _shipped_but_undelivered_order():
    return setup_dispatched_shipment(
        quantity=10, core_expected_count=10,
        lot_overrides={"quantity_on_hand": 60},
        account_overrides={"name": "Delta Fleet", "storm_priority_rank": 5},
    )


def test_core_return_against_a_shipped_order_is_refused(api):
    """PRD §3.6: "The source order's `fulfillment_status` must be `DELIVERED`,
    since cores cannot come back from goods that never went out, and anything
    else is refused with `ERR_ORDER_NOT_DELIVERED` (HTTP 422)."
    PRD §3.5: "A successful tender writes `dispatched_at` from the clock, moves
    the shipment `CERTIFIED → DISPATCHED`, and drives the order's
    `fulfillment_status` from `ALLOCATED` to `SHIPPED`."

    Design: Difficulty/cross_entity_state_dependency/core_return_creation_requires_source_order_delivered
    """
    env = _shipped_but_undelivered_order()
    assert read_order(env["order"]["id"])["fulfillment_status"] == "SHIPPED"

    resp = api.create_core_return({
        "account_id": env["account"]["id"],
        "order_id": env["order"]["id"],
        "battery_model_id": env["model"]["id"],
        "declared_core_count": 1,
    }, REP)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DELIVERED.value)


def test_undelivered_order_carries_no_core_window_and_no_return_row(api):
    """PRD §3.5: "every line is stamped with a `core_due_by` equal to the
    calendar date of the delivery instant plus 45 days, the window inside which
    promised cores must come back"
    PRD §3.5: "**Hop three** books the core liability: the account's
    `core_deposit_balance_cents` increases by the sum over the order's lines of
    `core_expected_count` multiplied by that line's model `core_deposit_cents`."

    Design: Difficulty/cross_entity_state_dependency/core_return_creation_requires_source_order_delivered
    """
    env = _shipped_but_undelivered_order()
    api.create_core_return({
        "account_id": env["account"]["id"],
        "order_id": env["order"]["id"],
        "battery_model_id": env["model"]["id"],
        "declared_core_count": 1,
    }, REP)

    assert read_order_line(env["line"]["id"])["core_due_by"] is None
    returns, _meta = validate_paginated(
        api.list_core_returns(REP, params={"order_id": env["order"]["id"]})
    )
    assert returns == [], "A refused declaration leaves no core return behind"
    assert read_account(env["account"]["id"])["core_deposit_balance_cents"] == 0


def _submitted_return_of_four_agm_cores():
    return setup_submitted_core_return(
        quantity=4, core_expected_count=4, declared_core_count=4,
        model_preset="IB-AGM-95",
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
        order_overrides={"requested_ship_date": "2026-08-05"},
    )


def test_disputing_before_any_inspection_is_refused(api):
    """PRD §3.6: "A dispute is admissible only from `INSPECTED` and only while
    `inspection_round` is still below 3; once three rounds have been completed
    the return is settled as inspected and a further dispute is refused with
    `ERR_DISPUTE_ROUNDS_EXHAUSTED` (HTTP 409)."
    PRD §3.6: "The return opens with `status` at `SUBMITTED` and
    `inspection_round` at 0."

    Design: Corner/state_machines/dispute_before_first_inspection_returns_invalid_state
    """
    env = _submitted_return_of_four_agm_cores()
    assert env["core_return"]["provisional_credit_cents"] == 10000

    resp = api.dispute_core_return(env["core_return"]["id"], {
        "dispute_reason": "Premature dispute before any grading took place."
    }, REP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    stored = read_core_return(env["core_return"]["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["inspection_round"] == 0


def test_inspection_accepting_no_cores_rejects_the_whole_return():
    """PRD §3.6: "An accepted count of exactly 0 moves the return to `REJECTED`
    instead, and zeroes the assay outright: `lead_recovered_kg` becomes 0.0,
    `scrap_value_cents` becomes 0 and `final_credit_cents` becomes 0, with no
    movement whatsoever on the account ledger."
    PRD §3.6: "Every inspection increments `inspection_round` by 1. The count
    then forks the outcome."

    Design: Corner/state_machines/inspect_with_zero_accepted_cores_rejects_the_return
    """
    env = _submitted_return_of_four_agm_cores()
    inspected = inspect_core_return(env["core_return"]["id"], 0)

    assert inspected["status"] == "REJECTED"
    assert inspected["lead_recovered_kg"] == pytest.approx(0.0, abs=0.0005)
    assert inspected["scrap_value_cents"] == 0
    assert inspected["final_credit_cents"] == 0
    assert inspected["inspection_round"] == 1

    account = read_account(env["account"]["id"])
    assert account["core_deposit_balance_cents"] == 10000, \
        "A rejected return moves nothing on the ledger"
    assert account["lifetime_lead_recovered_kg"] == pytest.approx(0.0, abs=0.0005)


def test_fourth_dispute_after_three_rounds_is_refused(api):
    """PRD §3.6: "A dispute is admissible only from `INSPECTED` and only while
    `inspection_round` is still below 3; once three rounds have been completed
    the return is settled as inspected and a further dispute is refused with
    `ERR_DISPUTE_ROUNDS_EXHAUSTED` (HTTP 409)."
    PRD §3.6: "`INSPECTED → DISPUTED → INSPECTED` is a genuine cycle, bounded
    only by that round ceiling."

    Design: Corner/state_machines/dispute_after_third_inspection_round_returns_rounds_exhausted
    """
    env = _submitted_return_of_four_agm_cores()
    cr_id = env["core_return"]["id"]
    inspect_core_return(cr_id, 3)
    dispute_core_return(cr_id, "First grading contested.")
    inspect_core_return(cr_id, 3)
    dispute_core_return(cr_id, "Second grading contested.")
    third = inspect_core_return(cr_id, 3)
    assert third["inspection_round"] == 3

    resp = api.dispute_core_return(cr_id, {"dispute_reason": "Third grading contested."}, REP)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_ROUNDS_EXHAUSTED.value)

    stored = read_core_return(cr_id)
    assert stored["status"] == "INSPECTED"
    assert stored["inspection_round"] == 3
    assert stored["accepted_core_count"] == 3


def test_a_late_return_pays_the_gross_credit_less_a_quarter_penalty():
    """PRD §3.6: "The `late_return` flag is true when the calendar date on which
    the return was created is strictly after the earliest non-null `core_due_by`
    among the source order's lines for this model — so a return arriving on the
    due date itself is not late, and lateness is possible without the window
    being closed, because the window allows 30 further days of grace."
    PRD §3.6: "the penalty is 25 percent of the gross, rounded half up to whole
    cents, when `late_return` is true and zero otherwise; and
    `final_credit_cents` is the gross less the penalty"

    Design: Corner/calculations/late_core_return_applies_the_quarter_penalty
    """
    from test_helpers import set_clock, create_core_return, read_order_line
    env = setup_delivered_order(
        quantity=10, core_expected_count=10, lot_overrides={"quantity_on_hand": 60},
        account_overrides={"name": "Delta Fleet", "storm_priority_rank": 5},
        order_overrides={"requested_ship_date": "2026-08-05"},
    )
    line = read_order_line(env["line"]["id"])
    assert str(line["core_due_by"]).startswith("2026-09-19")

    set_clock("2026-09-25T00:00:00Z")
    core_return = create_core_return(env["account"]["id"], env["order"]["id"],
                                     env["model"]["id"], 10)
    assert core_return["late_return"] is True
    assert core_return["provisional_credit_cents"] == 22000

    inspected = inspect_core_return(core_return["id"], 10)
    assert inspected["scrap_value_cents"] == 23643

    credited = credit_core_return(core_return["id"])
    assert credited["final_credit_cents"] == 17732, \
        f"23643 gross less a 5911 cent penalty, got {credited['final_credit_cents']}"
    assert credited["status"] == "CREDITED"
    assert read_account(env["account"]["id"])["core_deposit_balance_cents"] == 4268


def test_declaring_more_cores_than_promised_is_refused(api):
    """PRD §3.6: "And the declared count must not outrun the promise: it may be
    no greater than the sum of `core_expected_count` across the source order's
    lines for this model, minus the declared counts already committed by that
    order's other returns for the same model standing in `SUBMITTED`,
    `INSPECTED`, `DISPUTED` or `CREDITED`; over-claiming is refused with
    `ERR_CORE_COUNT_EXCEEDS_PROMISE` (HTTP 422)."

    Design: Corner/validations/core_return_declaring_more_than_the_promise_is_refused
    """
    from test_helpers import read_order_line
    env = setup_delivered_order(
        quantity=4, core_expected_count=2, model_preset="IB-AGM-95",
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
        order_overrides={"requested_ship_date": "2026-08-05"},
    )
    line = read_order_line(env["line"]["id"])
    assert line["core_expected_count"] == 2
    assert str(line["core_due_by"]).startswith("2026-09-19")

    resp = api.create_core_return({
        "account_id": env["account"]["id"], "order_id": env["order"]["id"],
        "battery_model_id": env["model"]["id"], "declared_core_count": 3,
    }, REP)
    validate_error(resp, ApiErrorId.ERR_CORE_COUNT_EXCEEDS_PROMISE.value)

    returns, _meta = validate_paginated(api.list_core_returns(
        REP, params={"order_id": env["order"]["id"], "limit": 10, "offset": 0}))
    assert returns == []
    assert read_account(env["account"]["id"])["core_deposit_balance_cents"] == 5000


def test_a_return_opened_past_the_grace_window_is_refused(api):
    """PRD §3.6: "The return must arrive inside the grace period: the current
    logical-clock date must be no later than the earliest `core_due_by` among
    the source order's lines for this model, plus 30 grace days; a later arrival
    is refused with `ERR_CORE_RETURN_WINDOW_CLOSED` (HTTP 422)."
    PRD §3.6: "This check is skipped entirely when no matching line carries a
    `core_due_by` at all."

    Design: Corner/validations/core_return_opened_past_the_grace_window_is_refused
    """
    from test_helpers import set_clock, read_order_line
    env = setup_delivered_order(
        quantity=10, core_expected_count=10, lot_overrides={"quantity_on_hand": 60},
        account_overrides={"name": "Delta Fleet", "storm_priority_rank": 5},
        order_overrides={"requested_ship_date": "2026-08-05"},
    )
    assert str(read_order_line(env["line"]["id"])["core_due_by"]).startswith("2026-09-19")

    set_clock("2026-10-20T00:00:00Z")
    resp = api.create_core_return({
        "account_id": env["account"]["id"], "order_id": env["order"]["id"],
        "battery_model_id": env["model"]["id"], "declared_core_count": 10,
    }, REP)
    validate_error(resp, ApiErrorId.ERR_CORE_RETURN_WINDOW_CLOSED.value)

    returns, _meta = validate_paginated(api.list_core_returns(
        REP, params={"order_id": env["order"]["id"], "limit": 10, "offset": 0}))
    assert returns == []
    assert read_account(env["account"]["id"])["core_deposit_balance_cents"] == 22000
