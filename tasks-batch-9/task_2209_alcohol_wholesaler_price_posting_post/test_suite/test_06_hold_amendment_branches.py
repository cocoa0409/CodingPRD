"""The three adjudication branches of a hold amendment and what each one writes."""

from test_helpers import (
    accept_amendment,
    assert_combination_sale,
    assert_hold_amendment,
    assert_quantity_discount_tier,
    new_amendment,
    new_combination,
    new_tier,
    read_amendment,
    read_combination,
    read_item,
    read_tier,
    read_wholesaler,
    reject_amendment,
    revoke_amendment,
    schedule_version,
    setup_two_wholesalers_certified,
)

REVOCATION_REASON = "The matched competitor posting was itself withdrawn."

INSTRUMENT_ITEM_SPECS = [
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


def _scene_with_tier():
    """Two certified wholesalers on one posting key; A's item carries a five-case tier."""
    scene = setup_two_wholesalers_certified()
    scene["tier"] = new_tier(
        scene["items_a"][0]["id"],
        scene["agent_a_headers"],
        min_cases=5,
        discount_pct=0.10,
    )
    return scene


def _scene_with_tier_and_combination():
    """A's schedule carries two items, a tier on the first and a combination over both."""
    scene = setup_two_wholesalers_certified(item_a_specs=INSTRUMENT_ITEM_SPECS)
    item_a, item_c = scene["items_a"]
    scene["tier"] = new_tier(
        item_a["id"], scene["agent_a_headers"], min_cases=5, discount_pct=0.10
    )
    scene["combination"] = new_combination(
        scene["schedule_a"]["id"],
        [item_a["id"], item_c["id"]],
        135_000,
        scene["agent_a_headers"],
    )
    return scene


def test_accept_branch_rewrites_the_item_and_recomputes_its_active_tier():
    """Acceptance captures the prior prices, writes the new ones and moves the tier with them.

    PRD §3.6: "Acceptance first captures the amending item's current prices into the
    amendment's `prior_case_price_cents` and `prior_unit_price_cents`, then writes
    `new_case_price_cents` into the item's `case_price_cents` and `new_unit_price_cents`
    into the item's `unit_price_cents`, then increments the item's `amendment_count` by 1,
    then recomputes `discounted_case_price_cents` on every `ACTIVE` quantity discount tier
    of that item, then recomputes `floor_price_cents` and `min_allowed_price_cents` on
    every `ACTIVE` combination sale that contains the item and moves to `VOID` any such
    combination whose `combined_case_price_cents` now falls strictly below its recomputed
    `min_allowed_price_cents`, and finally advances the item's `version` by 1."

    Design: Difficulty/non_linear_state_machine/hold_amendment_accept_and_reject_branches_write_disjoint_side_effect_sets
    """
    scene = _scene_with_tier()
    item_a = scene["items_a"][0]

    amendment = new_amendment(
        item_a["id"],
        scene["item_b"]["id"],
        115_000,
        10_500,
        schedule_version(scene["schedule_a"]["id"]),
        scene["agent_a_headers"],
    )
    accepted = accept_amendment(amendment["id"])

    assert_hold_amendment(accepted)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["prior_case_price_cents"] == 120_000
    assert accepted["prior_unit_price_cents"] == 11_000

    item = read_item(item_a["id"])
    assert item["case_price_cents"] == 115_000
    assert item["unit_price_cents"] == 10_500
    assert item["amendment_count"] == 1

    tier = read_tier(scene["tier"]["id"])
    assert_quantity_discount_tier(tier)
    assert tier["discounted_case_price_cents"] == 103_500
    assert tier["status"] == "ACTIVE"

    wholesaler = read_wholesaler(scene["wholesaler_a"]["id"])
    assert wholesaler["frivolous_amendment_count"] == 0
    assert wholesaler["amendment_penalty_accrued_cents"] == 0


def test_reject_branch_touches_only_the_filing_wholesalers_counter():
    """Rejection leaves every posted figure alone and moves the filer's frivolous count.

    PRD §3.6: "It records the supplied `rejection_reason` and leaves the amending item's
    prices, its `amendment_count`, its tiers and its combinations entirely unchanged."

    Design: Difficulty/non_linear_state_machine/hold_amendment_accept_and_reject_branches_write_disjoint_side_effect_sets
    """
    scene = _scene_with_tier()
    item_a = scene["items_a"][0]

    accepted = accept_amendment(
        new_amendment(
            item_a["id"],
            scene["item_b"]["id"],
            115_000,
            10_500,
            schedule_version(scene["schedule_a"]["id"]),
            scene["agent_a_headers"],
        )["id"]
    )
    assert accepted["status"] == "ACCEPTED"

    second = new_amendment(
        item_a["id"],
        scene["item_b"]["id"],
        112_000,
        10_200,
        schedule_version(scene["schedule_a"]["id"]),
        scene["agent_a_headers"],
    )
    rejected = reject_amendment(second["id"])

    assert_hold_amendment(rejected)
    assert rejected["status"] == "REJECTED"
    assert rejected.get("prior_case_price_cents") is None
    assert rejected.get("prior_unit_price_cents") is None

    item = read_item(item_a["id"])
    assert item["case_price_cents"] == 115_000
    assert item["unit_price_cents"] == 10_500
    assert item["amendment_count"] == 1

    wholesaler = read_wholesaler(scene["wholesaler_a"]["id"])
    assert wholesaler["frivolous_amendment_count"] == 1
    assert wholesaler["amendment_penalty_accrued_cents"] == 0
    assert wholesaler["penalty_exposure_cents"] == 0


def test_accepted_amendment_moves_every_derived_instrument_and_voids_the_combination():
    """A lower case price drags the tier price and the combination floor down with it.

    PRD §2.8: "A combination whose already-offered `combined_case_price_cents` no longer
    reaches its recomputed `min_allowed_price_cents` is moved to `VOID`; a combination
    previously `VOID` whose `combined_case_price_cents` again reaches the recomputed
    `min_allowed_price_cents` is returned to `ACTIVE`."

    Design: Difficulty/compensating_invariant/revoke_conserves_the_item_price_vector_and_every_derived_instrument_value
    """
    scene = _scene_with_tier_and_combination()
    item_a = scene["items_a"][0]

    amendment = new_amendment(
        item_a["id"],
        scene["item_b"]["id"],
        118_000,
        10_800,
        schedule_version(scene["schedule_a"]["id"]),
        scene["agent_a_headers"],
    )
    accept_amendment(amendment["id"])

    item = read_item(item_a["id"])
    assert item["case_price_cents"] == 118_000
    assert item["unit_price_cents"] == 10_800

    tier = read_tier(scene["tier"]["id"])
    assert tier["discounted_case_price_cents"] == 106_200

    combination = read_combination(scene["combination"]["id"])
    assert_combination_sale(combination)
    assert combination["floor_price_cents"] == 148_000
    assert combination["min_allowed_price_cents"] == 140_600
    assert combination["status"] == "VOID"


def test_revocation_restores_the_price_vector_and_resurrects_the_combination():
    """Revocation puts every derived figure back exactly, including a voided combination.

    PRD §3.6: "It restores the amending item's `case_price_cents` from
    `prior_case_price_cents` and its `unit_price_cents` from `prior_unit_price_cents`,
    decrements the item's `amendment_count` by 1, recomputes
    `discounted_case_price_cents` on every `ACTIVE` quantity discount tier of the item,
    and recomputes `floor_price_cents` and `min_allowed_price_cents` on **every**
    combination sale containing the item — not merely the `ACTIVE` ones — returning to
    `ACTIVE` any combination currently in `VOID` whose `combined_case_price_cents` is at
    or above the recomputed `min_allowed_price_cents`."

    Design: Difficulty/compensating_invariant/revoke_conserves_the_item_price_vector_and_every_derived_instrument_value
    """
    scene = _scene_with_tier_and_combination()
    item_a = scene["items_a"][0]

    amendment = new_amendment(
        item_a["id"],
        scene["item_b"]["id"],
        118_000,
        10_800,
        schedule_version(scene["schedule_a"]["id"]),
        scene["agent_a_headers"],
    )
    accept_amendment(amendment["id"])
    revoked = revoke_amendment(amendment["id"], REVOCATION_REASON)

    assert revoked["status"] == "REVOKED"

    item = read_item(item_a["id"])
    assert item["case_price_cents"] == 120_000
    assert item["unit_price_cents"] == 11_000
    assert item["amendment_count"] == 0

    tier = read_tier(scene["tier"]["id"])
    assert tier["discounted_case_price_cents"] == 108_000
    assert tier["status"] == "ACTIVE"

    combination = read_combination(scene["combination"]["id"])
    assert combination["floor_price_cents"] == 150_000
    assert combination["min_allowed_price_cents"] == 135_000
    assert combination["status"] == "ACTIVE"
    assert combination["combined_case_price_cents"] == 135_000


def test_revocation_keeps_its_own_record_and_the_untouched_member_item():
    """The revoked amendment still narrates what it restored, and the sibling item never moved.

    PRD §3.6: "Both `REJECTED` and `REVOKED` are terminal for an amendment; there is no
    path back to `PENDING`."

    Design: Difficulty/compensating_invariant/revoke_conserves_the_item_price_vector_and_every_derived_instrument_value
    """
    scene = _scene_with_tier_and_combination()
    item_a, item_c = scene["items_a"]

    amendment = new_amendment(
        item_a["id"],
        scene["item_b"]["id"],
        118_000,
        10_800,
        schedule_version(scene["schedule_a"]["id"]),
        scene["agent_a_headers"],
    )
    accept_amendment(amendment["id"])
    revoke_amendment(amendment["id"], REVOCATION_REASON)

    stored = read_amendment(amendment["id"])
    assert_hold_amendment(stored)
    assert stored["status"] == "REVOKED"
    assert stored["prior_case_price_cents"] == 120_000
    assert stored["prior_unit_price_cents"] == 11_000
    assert stored["revocation_reason"] == REVOCATION_REASON

    sibling = read_item(item_c["id"])
    assert sibling["case_price_cents"] == 30_000
    assert sibling["unit_price_cents"] == 1_500

    restored = read_item(item_a["id"])
    assert restored["certified_case_price_cents"] == 120_000
    assert restored["certified_unit_price_cents"] == 11_000
