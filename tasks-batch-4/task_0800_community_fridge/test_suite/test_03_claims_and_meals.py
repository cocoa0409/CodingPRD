"""Community claims, stock depletion, and provisional-vs-realized meal impact."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_fridge_and_steward, setup_stocked_batch, intake_batch,
    claim_portion, recall_batch, set_clock,
    make_member_headers, make_steward_headers,
    create_claim_payload,
)


def test_intake_provisional_meals_from_declared_mass(api):
    """PRD §3.5: "The batch's `provisional_meals` is computed immediately from the
    declared mass: it is `declared_quantity_kg` divided by 1.2 kilograms per meal,
    rounded half-up to a whole number of meals."

    Design: Difficulty/dual_variant_calc/batch_provisional_vs_realized_meals
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=10)
    batch = intake_batch(api, fridge["id"], steward["id"],
                         declared_quantity_kg=10.0, slot_footprint=2)
    assert batch["provisional_meals"] == 8


def test_realized_meals_frozen_from_claimed_mass_diverge_from_provisional(api):
    """PRD §3.6: "Freezing means `realized_quantity_kg` is set to the sum of
    `quantity_kg` over the batch's non-`VOIDED` claims, and `realized_meals` is set to
    that realized mass divided by 1.2 kilograms per meal, rounded half-up to a whole
    number of meals."

    Design: Difficulty/dual_variant_calc/batch_provisional_vs_realized_meals
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=10)
    batch = intake_batch(api, fridge["id"], steward["id"],
                         declared_quantity_kg=10.0, slot_footprint=2)
    claim_portion(api, batch["id"], 3.6)
    discarded = validate_success(
        api.discard_batch(batch["id"], make_steward_headers(steward["id"])), 200
    )
    assert discarded["realized_meals"] == 3
    assert discarded["provisional_meals"] == 8
    assert discarded["provisional_meals"] != discarded["realized_meals"]


def test_claim_decrements_available_quantity_and_keeps_stocked(api):
    """PRD §3.6: "A successful claim reduces the batch's `available_quantity_kg` by
    the claimed `quantity_kg`."

    Design: Corner/calculations/available_quantity_decrements_on_claim
    """
    fridge, steward, batch = setup_stocked_batch(api, capacity_slots=5,
                                                 declared_quantity_kg=5.0)
    claim_portion(api, batch["id"], 2.0)
    updated = validate_success(api.get_batch(batch["id"], make_steward_headers(steward["id"])), 200)
    assert updated["available_quantity_kg"] == 3.0
    assert updated["status"] == "STOCKED"


def test_full_claim_autocloses_batch_and_frees_slots(api):
    """PRD §3.6: "If that reduction drives `available_quantity_kg` to zero, the batch
    has been fully distributed: it transitions from `STOCKED` to the terminal
    `CLAIMED_OUT` status, which frees its slots (removing its `slot_footprint` from the
    fridge's `stock_slots_used`) and freezes its realized figures."

    Design: Corner/calculations/full_claim_autocloses_batch_and_frees_slots
    """
    fridge, steward, batch = setup_stocked_batch(api, capacity_slots=6,
                                                 declared_quantity_kg=5.0,
                                                 slot_footprint=2)
    claim_portion(api, batch["id"], 5.0)
    closed = validate_success(api.get_batch(batch["id"], make_steward_headers(steward["id"])), 200)
    assert closed["status"] == "CLAIMED_OUT"
    refreshed = validate_success(api.get_fridge(fridge["id"], make_steward_headers(steward["id"])), 200)
    assert refreshed["free_slots"] == 6


def test_overclaim_beyond_available_rejected_no_portions(api):
    """PRD §3.6: "a claim exceeding what is available, or against a batch with zero
    available, is rejected with `ERR_NO_PORTIONS`."

    Design: Corner/validations/overclaim_beyond_available_returns_no_portions
    """
    fridge, steward, batch = setup_stocked_batch(api, capacity_slots=5,
                                                 declared_quantity_kg=3.0)
    resp = api.create_claim(batch["id"], create_claim_payload(4.0), make_member_headers())
    validate_error(resp, ApiErrorId.ERR_NO_PORTIONS.value)


def test_claim_on_stocked_batch_past_use_by_rejected(api):
    """PRD §3.6: "The batch must also not be past its `use_by`: a claim on a batch
    whose `use_by` the logical clock has reached is rejected with `ERR_USE_BY_PASSED`."

    Design: Corner/validations/claim_past_use_by_on_stocked_returns_use_by_passed
    """
    fridge, steward, batch = setup_stocked_batch(
        api, capacity_slots=5, declared_quantity_kg=3.0, use_by="2026-03-05T00:00:00Z"
    )
    set_clock(api, "2026-03-06T00:00:00Z")
    resp = api.create_claim(batch["id"], create_claim_payload(1.0), make_member_headers())
    validate_error(resp, ApiErrorId.ERR_USE_BY_PASSED.value)


def test_claim_on_recalled_and_expired_batch_returns_batch_recalled(api):
    """PRD §3.6: "A claim is only valid against a batch in `STOCKED` status; a batch
    that is `RECALLED`, `HELD`, or in any terminal status cannot be claimed, and the
    attempt is rejected with `ERR_BATCH_RECALLED`."

    Design: Difficulty/priority_pair_validation_conflict/claim_recalled_state_beats_useby_safety
    """
    fridge, steward, batch = setup_stocked_batch(
        api, capacity_slots=10, declared_quantity_kg=4.0, use_by="2026-03-05T00:00:00Z"
    )
    recall_batch(api, batch["id"], steward["id"])
    set_clock(api, "2026-03-10T00:00:00Z")  # past use_by, but RECALLED is not swept
    resp = api.create_claim(batch["id"], create_claim_payload(1.0), make_member_headers())
    validate_error(resp, ApiErrorId.ERR_BATCH_RECALLED.value)


def test_recalled_state_error_preempts_use_by_safety_error(api):
    """PRD §3.6: "A claim is only valid against a batch in `STOCKED` status; a batch
    that is `RECALLED`, `HELD`, or in any terminal status cannot be claimed, and the
    attempt is rejected with `ERR_BATCH_RECALLED`. The batch must also not be past its
    `use_by`: a claim on a batch whose `use_by` the logical clock has reached is
    rejected with `ERR_USE_BY_PASSED`."

    Design: Difficulty/priority_pair_validation_conflict/claim_recalled_state_beats_useby_safety
    """
    fridge, steward, batch = setup_stocked_batch(
        api, capacity_slots=10, declared_quantity_kg=4.0, use_by="2026-03-05T00:00:00Z"
    )
    recall_batch(api, batch["id"], steward["id"])
    set_clock(api, "2026-03-10T00:00:00Z")
    resp = api.create_claim(batch["id"], create_claim_payload(1.0), make_member_headers())
    body = resp.json()
    assert body["data"]["error_id"] == ApiErrorId.ERR_BATCH_RECALLED.value
    assert body["data"]["error_id"] != ApiErrorId.ERR_USE_BY_PASSED.value
    assert resp.status_code == 409
