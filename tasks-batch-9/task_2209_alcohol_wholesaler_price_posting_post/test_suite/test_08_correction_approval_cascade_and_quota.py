"""Approving corrections: the second one costs money, the third one is refused."""

from test_helpers import (
    api_client,
    approve_correction,
    assert_error_correction,
    assert_wholesaler,
    new_correction,
    new_tier,
    read_correction,
    read_exposure,
    read_item,
    read_schedule,
    read_tier,
    read_wholesaler,
    regulator_headers,
    setup_certified_schedule,
    validate_error,
    validate_paginated,
)

CASCADE_ITEM_SPECS = [
    {
        "size_ml": 750,
        "bottles_per_case": 12,
        "case_price_cents": 120_000,
        "unit_price_cents": 11_000,
    },
    {
        "size_ml": 375,
        "bottles_per_case": 24,
        "case_price_cents": 30_000,
        "unit_price_cents": 1_500,
    },
]


def _one_correction_approved_scene():
    """Two certified items, a tier on the first, and one approved correction on it."""
    scene = setup_certified_schedule(item_specs=CASCADE_ITEM_SPECS)
    item_a, _item_c = scene["items"]
    scene["tier"] = new_tier(
        item_a["id"], scene["agent_headers"], min_cases=5, discount_pct=0.10
    )
    first = new_correction(item_a["id"], 114_000, 10_500, scene["agent_headers"])
    scene["correction_one"] = approve_correction(first["id"])
    return scene


def _quota_exhausted_scene():
    """One certified item carrying three filed corrections, two of them approved."""
    scene = setup_certified_schedule()
    item = scene["items"][0]
    filings = [
        new_correction(item["id"], 114_000, 10_500, scene["agent_headers"]),
        new_correction(item["id"], 115_000, 10_600, scene["agent_headers"]),
        new_correction(item["id"], 116_000, 10_700, scene["agent_headers"]),
    ]
    scene["corrections"] = filings
    approve_correction(filings[0]["id"])
    approve_correction(filings[1]["id"])
    return scene


def test_first_approved_correction_costs_the_wholesaler_nothing():
    """The opening correction on a schedule moves prices and counters but no money.

    PRD §3.6: "When the schedule's resulting `correction_count` reaches 2, the program's
    `repeat_correction_penalty_cents` is added to the wholesaler's
    `correction_penalty_accrued_cents`, `penalty_exposure_cents` is recomputed and the
    wholesaler's `version` is advanced by 1 — the first correction on a schedule is free,
    the second costs the wholesaler money."

    Design: Difficulty/transitive_cascade/second_approved_correction_cascades_from_schedule_counter_into_the_wholesaler_penalty_ledger
    """
    scene = _one_correction_approved_scene()
    item_a = scene["items"][0]

    assert scene["correction_one"]["status"] == "APPROVED"
    assert read_schedule(scene["schedule"]["id"])["correction_count"] == 1

    stored = read_item(item_a["id"])
    assert stored["case_price_cents"] == 114_000
    assert stored["unit_price_cents"] == 10_500
    assert stored["correction_count"] == 1
    assert read_tier(scene["tier"]["id"])["discounted_case_price_cents"] == 102_600

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert_wholesaler(wholesaler)
    assert wholesaler["correction_penalty_accrued_cents"] == 0
    assert wholesaler["penalty_exposure_cents"] == 0
    assert wholesaler["version"] == 1


def test_second_approved_correction_cascades_into_the_wholesaler_penalty_ledger():
    """A correction on a second item lifts the schedule counter to two and charges the ledger.

    PRD §3.6: "Approval writes `corrected_case_price_cents` into the item's
    `case_price_cents` and `corrected_unit_price_cents` into the item's
    `unit_price_cents`, increments the item's `correction_count` by 1 and the owning
    schedule's `correction_count` by 1, recomputes `discounted_case_price_cents` on every
    `ACTIVE` quantity discount tier of the item, and advances the item's `version` by 1."

    Design: Difficulty/transitive_cascade/second_approved_correction_cascades_from_schedule_counter_into_the_wholesaler_penalty_ledger
    """
    scene = _one_correction_approved_scene()
    item_c = scene["items"][1]

    second = new_correction(item_c["id"], 28_500, 1_425, scene["agent_headers"])
    approved = approve_correction(second["id"])

    assert_error_correction(approved)
    assert approved["status"] == "APPROVED"

    stored_c = read_item(item_c["id"])
    assert stored_c["case_price_cents"] == 28_500
    assert stored_c["unit_price_cents"] == 1_425
    assert stored_c["correction_count"] == 1

    assert read_schedule(scene["schedule"]["id"])["correction_count"] == 2

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["correction_penalty_accrued_cents"] == 100_000
    assert wholesaler["late_filing_penalty_accrued_cents"] == 0
    assert wholesaler["assessed_penalty_cents"] == 0
    assert wholesaler["penalty_exposure_cents"] == 100_000
    assert wholesaler["version"] == 2

    exposure = read_exposure(scene["wholesaler"]["id"], variant="assessed_exposure")
    assert exposure["accrued_cents"] == 100_000
    assert exposure["provisional_cents"] == 0
    assert exposure["exposure_cents"] == 100_000


def test_second_approval_leaves_the_other_items_derived_values_alone():
    """The cascade follows the corrected item only; the sibling's tier is not re-derived.

    PRD §2.8: "Concretely: whenever a `PriceScheduleItem`'s `case_price_cents` changes,
    every `ACTIVE` `QuantityDiscountTier` of that item has its
    `discounted_case_price_cents` recomputed, and every affected `CombinationSale` has its
    `floor_price_cents` and `min_allowed_price_cents` recomputed."

    Design: Difficulty/transitive_cascade/second_approved_correction_cascades_from_schedule_counter_into_the_wholesaler_penalty_ledger
    """
    scene = _one_correction_approved_scene()
    item_a, item_c = scene["items"]

    second = new_correction(item_c["id"], 28_500, 1_425, scene["agent_headers"])
    approve_correction(second["id"])

    stored_a = read_item(item_a["id"])
    assert stored_a["case_price_cents"] == 114_000
    assert stored_a["unit_price_cents"] == 10_500
    assert stored_a["correction_count"] == 1
    assert read_tier(scene["tier"]["id"])["discounted_case_price_cents"] == 102_600


def test_reapproving_an_approved_correction_answers_with_the_state_rule():
    """State admissibility is reached before the exhausted quota is ever consulted.

    PRD §2.10: "State admissibility outranks every business rule below it — an amendment
    filed against an item that has already gone `EFFECTIVE` is reported as
    `ERR_INVALID_STATE` even though its post-and-hold window has also closed, because
    priority 8 is reached before priority 12."

    Design: Difficulty/priority_pair_validation_conflict/already_approved_correction_state_outranks_the_exhausted_schedule_correction_quota
    """
    scene = _quota_exhausted_scene()
    second = scene["corrections"][1]

    response = api_client.approve_error_correction(second["id"], regulator_headers())

    validate_error(response, "ERR_INVALID_STATE", 409)

    stored = read_correction(second["id"])
    assert stored["status"] == "APPROVED"
    assert stored["prior_case_price_cents"] == 120_000


def test_approving_a_third_correction_answers_with_the_quota_rule():
    """A correction that is still submitted clears priority 8 and is stopped by the quota.

    PRD §3.6: "It requires the correction to be in `SUBMITTED` (otherwise
    `ERR_INVALID_STATE`) and requires the item's schedule to have strictly fewer approved
    corrections than the program's `max_corrections_per_schedule`; at or above that number
    the approval is refused with `ERR_CORRECTION_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/already_approved_correction_state_outranks_the_exhausted_schedule_correction_quota
    """
    scene = _quota_exhausted_scene()
    third = scene["corrections"][2]

    response = api_client.approve_error_correction(third["id"], regulator_headers())

    validate_error(response, "ERR_CORRECTION_LIMIT_EXCEEDED", 409)

    stored = read_correction(third["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["prior_case_price_cents"] == 120_000

    assert read_schedule(scene["schedule"]["id"])["correction_count"] == 2

    item = read_item(scene["items"][0]["id"])
    assert item["correction_count"] == 2
    assert item["case_price_cents"] == 115_000
    assert item["unit_price_cents"] == 10_600

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["correction_penalty_accrued_cents"] == 100_000

    listing = api_client.list_error_corrections(
        regulator_headers(), params={"item_id": item["id"], "status": "APPROVED"}
    )
    _data, meta = validate_paginated(listing)
    assert meta["total_count"] == 2
