"""
Load rating: one equation, two answers, and the divergence that posts a bridge.

PRD §3.4: "Load rating answers two questions with one equation: how much load may
cross this structure occasionally, and how much may cross it indefinitely. Both
answers are always computed and both are stored on the same rating record,
because it is their *divergence* that decides whether the structure must be
posted and at what weight."
"""

from decimal import Decimal

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import fixtures as fx


def test_operating_and_inventory_variants_diverge_on_one_rating(
    client, roster, bridge, accepted
):
    """
    Both variants are computed from the same numerator and stored on the same
    record, and they disagree because only the live-load factor differs.

    PRD §3.4: "Both variants share a numerator and differ in exactly one term."
    PRD §3.4: "The **operating** variant uses a live-load factor of 1.35 and
    represents the maximum live load the structure may carry for occasional
    passage; it always yields the higher of the two rating factors".
    PRD §3.4: "The **inventory** variant uses a live-load factor of 1.75 and
    represents the load level the structure can carry for an indefinite period;
    it always yields the lower of the two rating factors".
    PRD §3.4: "With a capacity of 2000, a structural dead load of 600, a
    wearing-surface dead load of 150, a live load of 500, a dynamic allowance of
    1.33, a resistance factor of 0.90, a system factor of 1.00 and a condition
    factor of 0.85, the numerator is 1530 minus 750 minus 225, which is 555."

    Design: Difficulty/dual_variant_calc/load_rating_operating_vs_inventory_diverge
    """
    rating = fx.create_rating(
        client, bridge["id"], roster, accepted["inspection"]["id"]
    )

    assert rating["condition_factor_phi_c"] == c.PHI_C_SEVERE, (
        "the baseline girder carries severe quantity, so the condition factor is "
        f"0.85, got {rating['condition_factor_phi_c']}"
    )
    assert rating["rating_factor_operating"] == 0.618
    assert rating["rating_factor_inventory"] == 0.477
    assert rating["rating_factor_operating"] != rating["rating_factor_inventory"], (
        "the two variants must not collapse onto a single stored value"
    )
    a.assert_operating_exceeds_inventory(rating)
    a.assert_three_decimals(rating["rating_factor_operating"], "rating_factor_operating")
    a.assert_three_decimals(rating["rating_factor_inventory"], "rating_factor_inventory")


def test_each_variant_is_scaled_to_tons_from_its_own_rounded_factor(
    client, roster, bridge, accepted
):
    """
    The tonnage of each variant follows from that variant's already-rounded
    factor, not from the unrounded quotient.

    PRD §3.4: "Each rating factor is then converted to tons by multiplying the
    *already-rounded three-decimal factor* by the rating vehicle's gross weight
    of 36.0 tons and rounding half up to one decimal place, giving
    `operating_rating_tons` and `inventory_rating_tons`."
    PRD §3.4: "0.477 times 36.0 is 17.172, rounded to 17.2 tons" and "22.248,
    rounded to 22.2 tons".

    Design: Difficulty/dual_variant_calc/load_rating_operating_vs_inventory_diverge
    """
    rating = fx.create_rating(
        client, bridge["id"], roster, accepted["inspection"]["id"]
    )

    assert rating["operating_rating_tons"] == 22.2
    assert rating["inventory_rating_tons"] == 17.2
    a.assert_rating_tonnage_pair(rating)
    a.assert_one_decimal(rating["operating_rating_tons"], "operating_rating_tons")
    a.assert_one_decimal(rating["inventory_rating_tons"], "inventory_rating_tons")


def test_posting_follows_the_operating_variant_but_the_limit_follows_inventory(
    client, roster, bridge, accepted
):
    """
    Posting is decided by the operating factor, while the weight actually posted
    comes from the inventory tonnage floored to a half ton.

    PRD §3.4: "`posting_required` is true exactly when `rating_factor_operating`
    is strictly less than 1.000".
    PRD §3.4: "When posting is required, `posted_limit_tons` is
    `inventory_rating_tons` quantised *downward* to the nearest half ton: double
    the inventory tonnage, discard the fractional part, and halve the result."
    PRD §3.4: "the posted limit is 17.2 doubled to 34.4, floored to 34, halved to
    17.0 tons."

    Design: Difficulty/dual_variant_calc/load_rating_operating_vs_inventory_diverge
    """
    rating = fx.create_rating(
        client, bridge["id"], roster, accepted["inspection"]["id"]
    )

    assert rating["posting_required"] is True
    assert rating["posted_limit_tons"] == 17.0
    a.assert_half_ton_step(rating["posted_limit_tons"])
    assert Decimal(str(rating["posted_limit_tons"])) == a.expected_posted_limit(
        rating["inventory_rating_tons"]
    )


def test_a_draft_rating_computes_everything_yet_governs_nothing(
    client, roster, bridge, accepted
):
    """
    A rating starts life `DRAFT` with all derived values present, but a `DRAFT`
    row is excluded from governing-rating selection, so the structure is still
    unrated.

    PRD §3.4: "A newly created rating is `DRAFT`, with every derived value
    computed immediately from the submitted inputs, and creating it increments the
    structure's `version` by one."
    PRD §3.4: "it considers only that structure's ratings whose `rating_status`
    is `APPROVED`, excluding `DRAFT`, `SEALED`, `REJECTED` and `SUPERSEDED` rows
    entirely. If none qualify, `governing_load_rating_id` is null and the
    structure has no posted limit and no rating tonnages."

    Design: Difficulty/dual_variant_calc/load_rating_operating_vs_inventory_diverge
    """
    before = fx.read_bridge(client, bridge["id"])
    rating = fx.create_rating(
        client, bridge["id"], roster, accepted["inspection"]["id"]
    )

    assert rating["rating_status"] == "DRAFT"
    a.assert_common_fields(rating, "load rating")

    after = fx.read_bridge(client, bridge["id"])
    a.assert_version_advanced_by(
        after["version"], before["version"], 1, "bridge"
    )
    assert after["governing_load_rating_id"] is None, (
        "a DRAFT rating must not become the governing rating"
    )
    assert after["posting_required"] is False
    assert after["posted_limit_tons"] is None
    assert after["operating_rating_tons"] is None
    assert after["inventory_rating_tons"] is None
