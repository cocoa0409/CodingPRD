"""Feedback collection, aggregation, suggestion engine (PRD §3.5)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_shipment_feedback,
    drive_order_to_delivered,
    emit_next_order,
    list_recipe_adjustments,
    make_customer_headers,
    setup_delivered_order,
    setup_subscription_with_order,
    submit_feedback,
    submit_feedback_payload,
    validate_error,
    validate_success,
)
from test_helpers import api_client


# ---------------------------------------------------------------------------
# Feedback payload validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("field", [
    "palatability", "stool_quality", "coat_condition",
])
@pytest.mark.parametrize("value", [0, 6, 10, -1])
def test_feedback_rating_out_of_range_rejected(api, field, value):
    """PRD §3.5: 'integer ratings palatability, stool_quality, and
    coat_condition each in the range 1 to 5 inclusive ... Feedback
    whose rating fields fall outside [1, 5] or whose
    weight_change_grams is not an integer is rejected with
    ERR_INVALID_FEEDBACK_PAYLOAD.'
    """
    bundle = setup_delivered_order()
    customer = bundle["customer"]
    pet = bundle["pet"]
    order = bundle["order"]
    payload = submit_feedback_payload(pet["id"])
    payload[field] = value
    res = api.submit_feedback(
        order["id"], payload,
        make_customer_headers(customer["id"]),
    )
    validate_error(
        res, ApiErrorId.ERR_INVALID_FEEDBACK_PAYLOAD.value,
    )


def test_feedback_weight_change_grams_not_integer_rejected(api):
    """PRD §3.5: 'weight_change_grams is not an integer is rejected
    with ERR_INVALID_FEEDBACK_PAYLOAD.'
    """
    bundle = setup_delivered_order()
    customer = bundle["customer"]
    pet = bundle["pet"]
    order = bundle["order"]
    payload = submit_feedback_payload(pet["id"])
    payload["weight_change_grams"] = "not-an-int"
    res = api.submit_feedback(
        order["id"], payload,
        make_customer_headers(customer["id"]),
    )
    validate_error(
        res, ApiErrorId.ERR_INVALID_FEEDBACK_PAYLOAD.value,
    )


def test_feedback_adverse_flag_computed_from_low_palatability(api):
    """PRD §3.5: 'adverse_flag is true when palatability is at most 2
    or stool_quality is at most 2; otherwise it is false.'
    """
    bundle = setup_delivered_order()
    customer = bundle["customer"]
    pet = bundle["pet"]
    order = bundle["order"]
    fb = submit_feedback(
        customer, order, pet,
        palatability=1, stool_quality=5, coat_condition=5,
        weight_change_grams=0,
    )
    assert_shipment_feedback(fb)
    assert fb["adverse_flag"] is True


def test_feedback_adverse_flag_false_when_above_threshold(api):
    """PRD §3.5: 'adverse_flag is true when palatability is at most 2
    or stool_quality is at most 2; otherwise it is false.'"""
    bundle = setup_delivered_order()
    customer = bundle["customer"]
    pet = bundle["pet"]
    order = bundle["order"]
    fb = submit_feedback(
        customer, order, pet,
        palatability=3, stool_quality=3, coat_condition=5,
        weight_change_grams=0,
    )
    assert fb["adverse_flag"] is False


def test_feedback_applies_weight_change_to_pet_weight_kg(api):
    """PRD §3.5: 'On success, the pet's weight_kg is updated by adding
    weight_change_grams divided by 1000 (so a +500 g entry raises the
    weight by 0.5 kg, and a -200 g entry lowers it by 0.2 kg).'
    """
    from test_helpers import reload_pet

    bundle = setup_delivered_order(
        pet_overrides={"weight_kg": 16.0},
    )
    customer = bundle["customer"]
    pet = bundle["pet"]
    order = bundle["order"]
    submit_feedback(
        customer, order, pet,
        weight_change_grams=500,
    )
    after = reload_pet(customer, pet["id"])
    assert abs(after["weight_kg"] - 16.5) < 1e-6, (
        f"PRD §3.5: pet weight_kg should be 16.5 after +500g feedback; "
        f"got {after['weight_kg']}"
    )


# ---------------------------------------------------------------------------
# Aggregation window — empty-set fallback
# ---------------------------------------------------------------------------
def test_no_suggestion_emitted_when_below_min_threshold(api):
    """PRD §3.5: 'The aggregation collects up to the most recent 3
    feedback rows for the same pet (the aggregation window), ordered
    by created_at ascending. If fewer than 2 rows are available, no
    suggestion is emitted and the engine stops.'
    """
    bundle = setup_delivered_order()
    customer = bundle["customer"]
    pet = bundle["pet"]
    order = bundle["order"]
    submit_feedback(
        customer, order, pet,
        palatability=5, stool_quality=5, coat_condition=5,
        weight_change_grams=1000,  # would trigger if MIN allowed
    )
    adjs = list_recipe_adjustments(customer, pet)
    assert adjs == [], (
        "PRD §3.5: a single feedback row must not produce any "
        f"RecipeAdjustment; got {adjs!r}"
    )


# ---------------------------------------------------------------------------
# Suggestion engine — priority-ordered branches
# ---------------------------------------------------------------------------
def test_suggestion_vet_escalate_when_adverse_count_ge_2(api):
    """PRD §3.5 branch 1: 'If adverse_count is at least 2, emit a
    RecipeAdjustment whose suggestion_type is VET_ESCALATE, whose
    status is auto-escalated immediately to VET_PENDING, and whose
    rationale is appended with the token adverse_stool_or_palatability.
    The pet's status is moved to VET_HOLD.'
    """
    from test_helpers import reload_pet

    bundle = setup_delivered_order()
    customer = bundle["customer"]
    pet = bundle["pet"]
    order = bundle["order"]
    # Two adverse feedbacks: palatability == 1 each (adverse_count=2).
    submit_feedback(
        customer, order, pet,
        palatability=1, stool_quality=5, coat_condition=5,
        weight_change_grams=0,
    )
    submit_feedback(
        customer, order, pet,
        palatability=1, stool_quality=5, coat_condition=5,
        weight_change_grams=0,
    )
    adjs = list_recipe_adjustments(customer, pet)
    vet_adjs = [
        a for a in adjs
        if a.get("suggestion_type") == "VET_ESCALATE"
    ]
    assert vet_adjs, (
        f"PRD §3.5 branch 1: expected a VET_ESCALATE adjustment after "
        f"2 adverse feedbacks; got {adjs!r}"
    )
    assert vet_adjs[0]["status"] == "VET_PENDING"
    # Pet must be on VET_HOLD.
    pet_after = reload_pet(customer, pet["id"])
    assert pet_after["status"] == "VET_HOLD"


def test_suggestion_decrease_portion_on_weight_gain(api):
    """PRD §3.5 branch 3: 'if total_weight_change_grams is strictly
    greater than 500 grams, emit a RecipeAdjustment whose
    suggestion_type is DECREASE_PORTION and whose portion_delta_pct
    is -10.'
    """
    bundle = setup_delivered_order()
    customer = bundle["customer"]
    pet = bundle["pet"]
    order = bundle["order"]
    # Two feedbacks each contributing +600g → total +1200g > 500.
    submit_feedback(
        customer, order, pet,
        palatability=5, stool_quality=5, coat_condition=5,
        weight_change_grams=600,
    )
    submit_feedback(
        customer, order, pet,
        palatability=5, stool_quality=5, coat_condition=5,
        weight_change_grams=600,
    )
    adjs = list_recipe_adjustments(customer, pet)
    suggested = [
        a for a in adjs
        if a.get("suggestion_type") == "DECREASE_PORTION"
    ]
    assert suggested, (
        f"PRD §3.5 branch 3: expected DECREASE_PORTION after >500g "
        f"weight gain; got {adjs!r}"
    )
    assert suggested[0]["portion_delta_pct"] == -10
    assert suggested[0]["status"] == "SUGGESTED"


def test_suggestion_increase_portion_on_weight_loss(api):
    """PRD §3.5 branch 4: 'if total_weight_change_grams is strictly
    less than -500 grams, emit a RecipeAdjustment whose
    suggestion_type is INCREASE_PORTION and whose portion_delta_pct
    is +10.'
    """
    bundle = setup_delivered_order(
        pet_overrides={"weight_kg": 30.0},
    )
    customer = bundle["customer"]
    pet = bundle["pet"]
    order = bundle["order"]
    submit_feedback(
        customer, order, pet,
        palatability=5, stool_quality=5, coat_condition=5,
        weight_change_grams=-600,
    )
    submit_feedback(
        customer, order, pet,
        palatability=5, stool_quality=5, coat_condition=5,
        weight_change_grams=-600,
    )
    adjs = list_recipe_adjustments(customer, pet)
    inc = [
        a for a in adjs
        if a.get("suggestion_type") == "INCREASE_PORTION"
    ]
    assert inc, (
        f"PRD §3.5 branch 4: expected INCREASE_PORTION after <-500g "
        f"total weight change; got {adjs!r}"
    )
    assert inc[0]["portion_delta_pct"] == 10
