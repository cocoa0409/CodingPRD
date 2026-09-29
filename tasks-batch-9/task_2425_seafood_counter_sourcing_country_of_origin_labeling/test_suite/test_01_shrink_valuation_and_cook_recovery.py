"""Shrink valuation, cook-and-sell recovery and the counter shrink ledger."""
from test_helpers import fixtures, validate_success
from test_helpers.assertions import (
    assert_cents,
    assert_counter_shrink_ledger_identity,
    assert_shrink_event,
    assert_shrink_value_identity,
    assert_weight,
)
from test_helpers.factories import shrink_event_payload
from test_helpers.test_users import (
    OFFICER_LEDGER_USER_ID,
    make_compliance_officer_headers,
    make_seafood_manager_headers,
)


def _cased_cod_lot_of_thirty_kg(api):
    """Clock at 08:00, one counter, one dealer, and a 30.000 kg cod lot cased in slot 1."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    lot = fixtures.receive_lot(
        api,
        env["counter"]["id"],
        env["supplier"]["id"],
        env["cod"]["id"],
        received_weight_kg=30.000,
        unit_cost_cents_per_kg=1700,
        retail_price_cents_per_kg=2450,
        cooked_retail_price_cents_per_kg=2600,
        previously_frozen=False,
        fresh_claim=True,
    )
    env["lot"] = fixtures.case_lot(api, env["counter"]["id"], lot["id"], 1)
    return env


def test_01_shrink_event_values_each_line_before_summing(api):
    """PRD §3.9: "The provisional valuation is the sum of three line components, and
    **each component is rounded to whole cents before the three are added** — rounding
    once after summation is a different and incorrect answer."

    Design: Difficulty/combinatorial_formula/shrink_valuation_per_line_rounding_order
    """
    env = _cased_cod_lot_of_thirty_kg(api)
    counter_id = env["counter"]["id"]

    response = api.create_shrink_event(
        shrink_event_payload(
            env["lot"]["id"],
            reason="UNSOLD_FRESH",
            shrink_weight_kg=8.375,
            conversion_requested_kg=0.000,
        ),
        make_seafood_manager_headers(counter_id),
    )
    event = validate_success(response, expected_status=201)

    assert_shrink_event(event)
    assert_cents(event["provisional_value_cents"], 15285)
    assert event["provisional_value_cents"] != 15284, (
        "summing the three unrounded line components would yield 15284"
    )
    assert event["status"] == "VALUED"
    assert_cents(event["recovery_credit_cents"], 0)


def test_02_shrink_event_creation_leaves_the_lot_weight_untouched(api):
    """PRD §3.9: "Crucially, creating a shrink event does **not** decrement the lot's
    `remaining_weight_kg`; only posting does."

    Design: Difficulty/combinatorial_formula/shrink_valuation_per_line_rounding_order
    """
    env = _cased_cod_lot_of_thirty_kg(api)
    counter_id = env["counter"]["id"]
    lot_id = env["lot"]["id"]

    response = api.create_shrink_event(
        shrink_event_payload(
            lot_id,
            reason="UNSOLD_FRESH",
            shrink_weight_kg=8.375,
            conversion_requested_kg=0.000,
        ),
        make_seafood_manager_headers(counter_id),
    )
    validate_success(response, expected_status=201)

    lot = fixtures.read_lot(api, counter_id, lot_id)
    assert_weight(lot["remaining_weight_kg"], 30.000)


def test_03_conversion_approval_pins_the_allowance_and_the_approved_weight(api):
    """PRD §3.9: "The `allowance_kg` is the smaller of the event's `shrink_weight_kg` and
    60 percent of the lot's `received_weight_kg` — no more than three fifths of an entire
    received lot may ever be diverted into the cooked case."

    Design: Difficulty/combinatorial_formula/cook_conversion_recovery_four_input_interaction
    """
    env = _cased_cod_lot_of_thirty_kg(api)
    counter_id = env["counter"]["id"]
    event = fixtures.create_shrink_event(
        api,
        counter_id,
        env["lot"]["id"],
        reason="UNSOLD_FRESH",
        shrink_weight_kg=8.375,
        conversion_requested_kg=6.000,
    )

    response = api.approve_conversion(event["id"], {}, make_seafood_manager_headers(counter_id))
    approved = validate_success(response, expected_status=200)

    assert_weight(approved["allowance_kg"], 8.375)
    assert_weight(approved["approved_conversion_kg"], 6.000)
    assert approved["status"] == "CONVERSION_APPROVED"


def test_04_cook_yield_and_recovery_credit_combine_every_conversion_input(api):
    """PRD §3.9: "The gross recovery is then the `cook_yield_kg` multiplied by the lot's
    `cooked_retail_price_cents_per_kg`, rounded half up to whole cents, and the labour
    charge is the `approved_conversion_kg` multiplied by a cook-line labour rate of 90
    cents per kilogram, also rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/cook_conversion_recovery_four_input_interaction
    """
    env = _cased_cod_lot_of_thirty_kg(api)
    counter_id = env["counter"]["id"]
    event = fixtures.create_shrink_event(
        api,
        counter_id,
        env["lot"]["id"],
        reason="UNSOLD_FRESH",
        shrink_weight_kg=8.375,
        conversion_requested_kg=6.000,
    )
    fixtures.approve_conversion(api, counter_id, event["id"])

    response = api.convert_shrink_event(event["id"], {}, make_seafood_manager_headers(counter_id))
    converted = validate_success(response, expected_status=200)

    assert_weight(converted["cook_yield_kg"], 3.705)
    assert_cents(converted["recovery_credit_cents"], 9093)
    assert_cents(converted["final_value_cents"], 6192)
    assert converted["status"] == "CONVERTED"


def test_05_provisional_and_final_valuations_hold_different_integers(api):
    """PRD §3.9: "The final valuation is the same provisional figure minus the event's
    `recovery_credit_cents`, so that `provisional_value_cents` always equals
    `final_value_cents` plus `recovery_credit_cents` by construction."

    Design: Difficulty/dual_variant_calc/shrink_dual_variant_provisional_vs_final_diverge
    """
    env = _cased_cod_lot_of_thirty_kg(api)
    counter_id = env["counter"]["id"]
    event = fixtures.create_shrink_event(
        api,
        counter_id,
        env["lot"]["id"],
        reason="UNSOLD_FRESH",
        shrink_weight_kg=8.375,
        conversion_requested_kg=6.000,
    )
    fixtures.approve_conversion(api, counter_id, event["id"])

    response = api.convert_shrink_event(event["id"], {}, make_seafood_manager_headers(counter_id))
    converted = validate_success(response, expected_status=200)

    assert_cents(converted["provisional_value_cents"], 15285)
    assert_cents(converted["recovery_credit_cents"], 9093)
    assert_cents(converted["final_value_cents"], 6192)
    assert_shrink_value_identity(converted)
    assert converted["status"] == "CONVERTED"


def test_06_conversion_alone_moves_neither_the_counter_ledger_nor_the_lot_weight(api):
    """PRD §3.9: "Posting is what actually moves money and weight."

    Design: Difficulty/dual_variant_calc/shrink_dual_variant_provisional_vs_final_diverge
    """
    env = _cased_cod_lot_of_thirty_kg(api)
    counter_id = env["counter"]["id"]
    lot_id = env["lot"]["id"]
    event = fixtures.create_shrink_event(
        api,
        counter_id,
        lot_id,
        reason="UNSOLD_FRESH",
        shrink_weight_kg=8.375,
        conversion_requested_kg=6.000,
    )
    fixtures.approve_conversion(api, counter_id, event["id"])
    fixtures.convert_shrink_event(api, counter_id, event["id"])

    counter = fixtures.read_counter(api, counter_id)
    assert_cents(counter["shrink_gross_cents"], 0)
    assert_cents(counter["shrink_net_cents"], 0)
    assert_weight(fixtures.read_lot(api, counter_id, lot_id)["remaining_weight_kg"], 30.000)


def test_07_posting_a_converted_event_moves_all_three_ledger_totals(api):
    """PRD §3.9: "Either way, the lot's `remaining_weight_kg` decreases by the event's
    `shrink_weight_kg`, the counter's `shrink_gross_cents` increases by the event's
    `provisional_value_cents`, the counter's `shrink_net_cents` increases by its
    `final_value_cents`, the counter's `recovered_conversion_cents` increases by its
    `recovery_credit_cents` — which for the no-conversion path is an increase of 0 — and
    `posted_at` is stamped from the logical clock as the event reaches `POSTED`."

    Design: Difficulty/compensating_invariant/counter_shrink_ledger_zeroes_after_post_then_reverse
    """
    env = _cased_cod_lot_of_thirty_kg(api)
    counter_id = env["counter"]["id"]
    lot_id = env["lot"]["id"]
    event = fixtures.create_shrink_event(
        api,
        counter_id,
        lot_id,
        reason="UNSOLD_FRESH",
        shrink_weight_kg=8.375,
        conversion_requested_kg=6.000,
    )
    fixtures.approve_conversion(api, counter_id, event["id"])
    fixtures.convert_shrink_event(api, counter_id, event["id"])

    response = api.post_shrink_event(event["id"], {}, make_seafood_manager_headers(counter_id))
    validate_success(response, expected_status=200)

    counter = fixtures.read_counter(api, counter_id)
    assert_cents(counter["shrink_gross_cents"], 15285)
    assert_cents(counter["shrink_net_cents"], 6192)
    assert_cents(counter["recovered_conversion_cents"], 9093)
    assert_counter_shrink_ledger_identity(counter)
    assert_weight(fixtures.read_lot(api, counter_id, lot_id)["remaining_weight_kg"], 21.625)


def test_08_reversing_a_posted_event_returns_the_ledger_to_zero_without_drift(api):
    """PRD §2.11: "Because a shrink event's `recovery_credit_cents` always equals its
    `provisional_value_cents` minus its `final_value_cents` by construction, the identity
    that gross equals net plus recovered holds at all times, and survives both the forward
    posting of an event and its later reversal with zero drift."

    Design: Difficulty/compensating_invariant/counter_shrink_ledger_zeroes_after_post_then_reverse
    """
    env = _cased_cod_lot_of_thirty_kg(api)
    counter_id = env["counter"]["id"]
    lot_id = env["lot"]["id"]
    event = fixtures.create_shrink_event(
        api,
        counter_id,
        lot_id,
        reason="UNSOLD_FRESH",
        shrink_weight_kg=8.375,
        conversion_requested_kg=6.000,
    )
    fixtures.approve_conversion(api, counter_id, event["id"])
    fixtures.convert_shrink_event(api, counter_id, event["id"])
    fixtures.post_shrink_event(api, counter_id, event["id"])

    response = api.reverse_shrink_event(
        event["id"],
        {"reversal_note": "cook-and-sell batch was condemned at the hot case"},
        make_compliance_officer_headers(OFFICER_LEDGER_USER_ID),
    )
    reversed_event = validate_success(response, expected_status=200)

    assert reversed_event["status"] == "REVERSED"
    counter = fixtures.read_counter(api, counter_id)
    assert_cents(counter["shrink_gross_cents"], 0)
    assert_cents(counter["shrink_net_cents"], 0)
    assert_cents(counter["recovered_conversion_cents"], 0)
    assert_counter_shrink_ledger_identity(counter)
    assert_weight(fixtures.read_lot(api, counter_id, lot_id)["remaining_weight_kg"], 30.000)
