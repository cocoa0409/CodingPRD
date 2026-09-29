"""
Permit filing: gross weight is rounded per axle before the axles are summed.

PRD §3.7: "`gross_weight_tons` is computed by rounding *each* axle load half up
to one decimal place first, and only then summing those rounded values and
rounding the total half up to one decimal place. The order is load-bearing."
"""

from test_helpers import assertions as a
from test_helpers import fixtures as fx


def test_five_axles_round_individually_before_they_are_summed(
    client, roster, bridge
):
    """
    Four axles of 8.25 tons round up individually to 8.3 each, so the filed gross
    weight is 39.6 tons and not the 39.4 tons a sum-then-round order would give.

    PRD §3.7: "Five axles of 8.25, 8.25, 8.25, 8.25 and 6.4 tons round
    individually to 8.3, 8.3, 8.3, 8.3 and 6.4, which sum to 39.6 tons. Summing
    first would give 39.4 tons and a materially different rating factor for every
    structure on the route, so implementations must round per axle before
    summing."
    PRD §3.7: "Two fields are derived from the axle array at filing:
    `axle_count`, the number of entries, and `gross_weight_tons`."

    Design: Difficulty/combinatorial_formula/permit_gross_weight_per_axle_rounding_order
    """
    permit = fx.receive_permit(
        client,
        "OW-2026-0001",
        [bridge["id"]],
        axle_loads_tons=[8.25, 8.25, 8.25, 8.25, 6.4],
    )

    assert permit["axle_count"] == 5
    assert permit["gross_weight_tons"] == 39.6, (
        "rounding per axle first gives 39.6 tons"
    )
    assert permit["gross_weight_tons"] != 39.4, (
        "39.4 tons is the sum-then-round answer and is not what the filing derives"
    )
    a.assert_one_decimal(permit["gross_weight_tons"], "gross_weight_tons")


def test_the_rounding_order_shows_itself_on_a_two_axle_load(client, roster, bridge):
    """
    The same order applies to the smallest legal axle array: two axles of 8.25
    tons each round to 8.3 and total 16.6 tons, where summing first would total
    16.5.

    PRD §3.7: "an `axle_loads_tons` array of per-axle loads in tons, which must
    contain at least two entries each strictly positive".
    PRD §3.7: "`gross_weight_tons` is computed by rounding *each* axle load half
    up to one decimal place first, and only then summing those rounded values and
    rounding the total half up to one decimal place."

    Design: Difficulty/combinatorial_formula/permit_gross_weight_per_axle_rounding_order
    """
    permit = fx.receive_permit(
        client, "OW-2026-0003", [bridge["id"]], axle_loads_tons=[8.25, 8.25]
    )

    assert permit["axle_count"] == 2
    assert permit["gross_weight_tons"] == 16.6
    assert permit["gross_weight_tons"] != 16.5


def test_a_freshly_received_application_carries_no_analysis_yet(
    client, roster, bridge
):
    """
    Filing derives the weight only. The route verdict, the governing minimum and
    the analysis rows all wait for the separate analysis run.

    PRD §3.7: "A newly received application is `RECEIVED`, carries a
    `recommended_decision` of `PENDING` and a null `governing_analysis_min_rf`,
    and has no analysis rows at all."

    Design: Difficulty/combinatorial_formula/permit_gross_weight_per_axle_rounding_order
    """
    permit = fx.receive_permit(
        client,
        "OW-2026-0004",
        [bridge["id"]],
        axle_loads_tons=[8.25, 8.25, 8.25, 8.25, 6.4],
    )

    assert permit["status"] == "RECEIVED"
    assert permit["recommended_decision"] == "PENDING"
    assert permit["governing_analysis_min_rf"] is None
    assert permit["decided_at"] is None
    assert permit["revoked_at"] is None
    a.assert_common_fields(permit, "permit application")

    assert fx.analyses_for_permit(client, permit["id"]) == [], (
        "no analysis rows exist before the analysis run"
    )
