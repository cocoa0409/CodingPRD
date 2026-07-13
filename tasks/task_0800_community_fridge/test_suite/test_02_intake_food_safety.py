"""Donation intake food-safety gating: temperature, allergens, posture, capacity."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_fridge_and_steward, setup_restricted_fridge, setup_quarantined_fridge,
    intake_batch, get_fridge_version, record_temperature,
    make_steward_headers, create_batch_payload,
)


def _attempt_intake(api, fridge_id, steward_id, **overrides):
    """Attempt an intake with the fridge's current version; returns raw response."""
    version = get_fridge_version(api, fridge_id)
    payload = create_batch_payload(steward_id, version, **overrides)
    return api.create_batch(fridge_id, payload, make_steward_headers(steward_id))


def test_cold_chain_intake_at_exactly_max_temp_is_accepted(api):
    """PRD §3.5: "if `storage_type` is `COLD_CHAIN` and `intake_temp_c` is strictly
    above 5.0 degrees Celsius, the intake is rejected with `ERR_TEMP_UNSAFE`; a
    reading of exactly 5.0 degrees is accepted."

    Design: Difficulty/boundary_precision_check/cold_chain_temp_upper_bound_strict
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=10)
    batch = intake_batch(
        api, fridge["id"], steward["id"],
        food_category="DAIRY", storage_type="COLD_CHAIN",
        declared_quantity_kg=2.0, intake_temp_c=5.0, allergens=["DAIRY"],
    )
    assert batch["status"] == "STOCKED"


def test_cold_chain_intake_just_above_max_temp_is_rejected(api):
    """PRD §3.5: "if `storage_type` is `COLD_CHAIN` and `intake_temp_c` is strictly
    above 5.0 degrees Celsius, the intake is rejected with `ERR_TEMP_UNSAFE`; a
    reading of exactly 5.0 degrees is accepted."

    Design: Difficulty/boundary_precision_check/cold_chain_temp_upper_bound_strict
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=10)
    resp = _attempt_intake(
        api, fridge["id"], steward["id"],
        food_category="DAIRY", storage_type="COLD_CHAIN",
        declared_quantity_kg=2.0, intake_temp_c=5.1, allergens=["DAIRY"],
    )
    validate_error(resp, ApiErrorId.ERR_TEMP_UNSAFE.value)


def test_intake_into_restricted_fridge_rejected_not_operational(api):
    """PRD §3.5: "the fridge's `safety_posture` must be `OPERATIONAL`; a `RESTRICTED`
    or `QUARANTINED` fridge cannot accept new food and the intake is rejected with
    `ERR_FRIDGE_NOT_OPERATIONAL`."

    Design: Difficulty/cross_entity_state_dependency/intake_requires_fridge_operational
    """
    fridge, steward = setup_restricted_fridge(api, capacity_slots=10)
    resp = _attempt_intake(api, fridge["id"], steward["id"], declared_quantity_kg=3.0)
    validate_error(resp, ApiErrorId.ERR_FRIDGE_NOT_OPERATIONAL.value)


def test_intake_into_quarantined_fridge_rejected_not_operational(api):
    """PRD §3.5: "the fridge's `safety_posture` must be `OPERATIONAL`; a `RESTRICTED`
    or `QUARANTINED` fridge cannot accept new food and the intake is rejected with
    `ERR_FRIDGE_NOT_OPERATIONAL`."

    Design: Difficulty/cross_entity_state_dependency/intake_requires_fridge_operational
    """
    fridge, steward, _recalled, _held, _need = setup_quarantined_fridge(
        api, capacity_slots=10
    )
    resp = _attempt_intake(api, fridge["id"], steward["id"], declared_quantity_kg=3.0)
    validate_error(resp, ApiErrorId.ERR_FRIDGE_NOT_OPERATIONAL.value)


def test_intake_not_operational_preempts_capacity_error(api):
    """PRD §3.5: "the fridge's `safety_posture` must be `OPERATIONAL`; a `RESTRICTED`
    or `QUARANTINED` fridge cannot accept new food and the intake is rejected with
    `ERR_FRIDGE_NOT_OPERATIONAL`."

    Design: Difficulty/priority_pair_validation_conflict/intake_notoperational_safety_beats_capacity
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=2)
    # Fill the fridge (free_slots -> 0) while still OPERATIONAL.
    intake_batch(api, fridge["id"], steward["id"],
                 declared_quantity_kg=4.0, slot_footprint=2)
    # Force RESTRICTED via a hot reading.
    record_temperature(api, fridge["id"], 10.0, steward_id=steward["id"])
    # A footprint-2 intake violates BOTH capacity and the safety gate.
    resp = _attempt_intake(api, fridge["id"], steward["id"],
                           declared_quantity_kg=4.0, slot_footprint=2)
    validate_error(resp, ApiErrorId.ERR_FRIDGE_NOT_OPERATIONAL.value)


def test_intake_not_operational_wins_over_capacity_specifically(api):
    """PRD §3.5: "Next, the fridge's `safety_posture` must be `OPERATIONAL` ... the
    intake is rejected with `ERR_FRIDGE_NOT_OPERATIONAL`. ... Finally, capacity is
    checked: the batch's `slot_footprint` must fit within the fridge's current
    `free_slots`, or the intake is rejected with `ERR_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/intake_notoperational_safety_beats_capacity
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=2)
    intake_batch(api, fridge["id"], steward["id"],
                 declared_quantity_kg=4.0, slot_footprint=2)
    record_temperature(api, fridge["id"], 10.0, steward_id=steward["id"])
    resp = _attempt_intake(api, fridge["id"], steward["id"],
                           declared_quantity_kg=4.0, slot_footprint=2)
    body = resp.json()
    assert body["data"]["error_id"] == ApiErrorId.ERR_FRIDGE_NOT_OPERATIONAL.value
    assert body["data"]["error_id"] != ApiErrorId.ERR_CAPACITY_EXCEEDED.value
    assert resp.status_code == 409


def test_bakery_intake_without_allergens_rejected(api):
    """PRD §3.5: "When the `food_category` is `BAKERY`, `DAIRY`, or `PREPARED`, the
    `allergens` list must be non-empty, or the intake is rejected with
    `ERR_ALLERGEN_LABEL_REQUIRED`."

    Design: Corner/validations/bakery_intake_without_allergens_returns_label_required
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=5)
    resp = _attempt_intake(
        api, fridge["id"], steward["id"],
        food_category="BAKERY", storage_type="AMBIENT", declared_quantity_kg=2.0,
    )
    validate_error(resp, ApiErrorId.ERR_ALLERGEN_LABEL_REQUIRED.value)


def test_intake_exceeding_free_slots_rejected_capacity(api):
    """PRD §3.5: "Finally, capacity is checked: the batch's `slot_footprint` must fit
    within the fridge's current `free_slots`, or the intake is rejected with
    `ERR_CAPACITY_EXCEEDED`."

    Design: Corner/validations/intake_footprint_exceeds_free_slots_returns_capacity_exceeded
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=2)
    # Fully occupy the fridge (free_slots -> 0), fridge stays OPERATIONAL.
    intake_batch(api, fridge["id"], steward["id"],
                 declared_quantity_kg=4.0, slot_footprint=2)
    resp = _attempt_intake(api, fridge["id"], steward["id"],
                           declared_quantity_kg=1.0, slot_footprint=1)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)
