"""Two money computations whose evaluation order decides the answer.

A proposal estimate rounds each cost line before summing and takes contingency
on the subtotal plus overhead, while a pool's supplemental tier is selected from
the gross pre-fee draw even though the fee is charged on the supplemented total.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_estimate_breakdown,
    assert_funding_pool,
    assert_pool_availability_identity,
)
from test_helpers.test_users import TEST_USERS


def _proposal_with_first_line(api):
    """A draft proposal carrying one 12.5 hour coating line."""
    register = fixtures.setup_register(api)
    conservator = fixtures.create_conservator(api)
    assessment = fixtures.setup_assessment_finalized(
        api, register["artwork"]["id"], assessed_on="2026-07-15"
    )
    proposal = fixtures.create_proposal_with_lines(
        api,
        register["artwork"]["id"],
        conservator["id"],
        assessment["id"],
        lines=[
            {
                "labor_hours": 12.5,
                "complexity_class": "COATING",
                "materials_cents": 82_500,
                "description": "recoat and wax",
            }
        ],
    )
    return proposal


def test_each_cost_line_rounds_its_own_half_cent_of_labour(api):
    """PRD §3.4: "The line's own labour cost is `labor_hours` multiplied by the
    engaged conservator's `hourly_rate_cents` as it stands at the moment the line is
    added, multiplied again by a complexity factor of 1.00 for `STABILIZATION`, 1.15
    for `SURFACE`, 1.25 for `COATING`, 1.40 for `STRUCTURAL` and 1.10 for
    `GRAFFITI`, with that product rounded half up to a whole cent and stored on the
    line as `labor_cents`."
    PRD §3.4: "The line's `line_total_cents` is its `labor_cents` plus its
    `materials_cents`."

    Design: Difficulty/combinatorial_formula/estimate_rounds_each_line_then_sums_mode_b
    """
    proposal = _proposal_with_first_line(api)
    proposal = validate_success(
        api.add_proposal_line_item(
            proposal["id"],
            {
                "labor_hours": 12.5,
                "complexity_class": "SURFACE",
                "materials_cents": 15_000,
                "description": "surface cleaning",
            },
            TEST_USERS["chief_conservator_headers"],
        )
    )

    # 12.5 hours at 14500 cents is 181250 cents of raw labour on both lines.
    # Coating: 181250 x 1.25 = 226562.5 -> 226563.  Surface: 181250 x 1.15 =
    # 208437.5 -> 208438.  Each half cent rounds up on its own line.
    assert len(proposal["line_items"]) == 2
    assert proposal["line_items"][0]["labor_cents"] == 226_563
    assert proposal["line_items"][0]["line_total_cents"] == 309_063
    assert proposal["line_items"][1]["labor_cents"] == 208_438
    assert proposal["line_items"][1]["line_total_cents"] == 223_438


def test_subtotal_sums_the_already_rounded_lines(api):
    """PRD §3.4: "`subtotal_cents` is the sum of the per-line `line_total_cents`
    values, each already rounded — rounding per line and then summing is normative,
    and it differs by a cent from summing raw products and rounding once whenever a
    line's labour lands on a half cent."

    Design: Difficulty/combinatorial_formula/estimate_rounds_each_line_then_sums_mode_b
    """
    proposal = _proposal_with_first_line(api)
    assert proposal["subtotal_cents"] == 309_063

    proposal = validate_success(
        api.add_proposal_line_item(
            proposal["id"],
            {
                "labor_hours": 12.5,
                "complexity_class": "SURFACE",
                "materials_cents": 15_000,
            },
            TEST_USERS["chief_conservator_headers"],
        )
    )
    # 309063 + 223438 = 532501; summing the raw products first would give 532500.
    assert proposal["subtotal_cents"] == 532_501


def test_contingency_is_taken_on_the_subtotal_plus_overhead(api):
    """PRD §3.4: "`overhead_cents` is 11.5 percent of `subtotal_cents`, rounded half
    up to a whole cent."
    PRD §3.4: "`contingency_cents` is 7.5 percent of the sum of `subtotal_cents` and
    `overhead_cents`, rounded half up to a whole cent — contingency is computed after
    overhead and therefore includes it, and computing contingency from the bare
    subtotal is wrong."
    PRD §3.4: "`mobilization_cents` is a flat 45,000 cents (450 dollars) whenever at
    least one line exists and zero when the collection is empty."

    Design: Difficulty/combinatorial_formula/estimate_rounds_each_line_then_sums_mode_b
    """
    proposal = _proposal_with_first_line(api)
    proposal = validate_success(
        api.add_proposal_line_item(
            proposal["id"],
            {
                "labor_hours": 12.5,
                "complexity_class": "SURFACE",
                "materials_cents": 15_000,
            },
            TEST_USERS["chief_conservator_headers"],
        )
    )
    # Overhead 11.5% of 532501 = 61237.615 -> 61238.  Contingency 7.5% of
    # (532501 + 61238 = 593739) = 44530.425 -> 44530.  Taking 7.5% of the bare
    # subtotal would give 39938 instead.
    assert proposal["overhead_cents"] == 61_238
    assert proposal["contingency_cents"] == 44_530
    assert proposal["mobilization_cents"] == 45_000
    assert proposal["estimate_total_cents"] == 683_269
    assert_estimate_breakdown(proposal)


def test_endowment_tier_is_selected_from_the_gross_pre_fee_draw(api):
    """PRD §3.10: "That gross figure then selects a supplemental tier: no supplement
    at all when the gross draw is below 5,000,000 cents (50,000 dollars); a
    supplement of 75 basis points when the gross draw is at least 5,000,000 cents but
    below 20,000,000 cents (200,000 dollars); and a supplement of 125 basis points
    when the gross draw is 20,000,000 cents or more."
    PRD §3.10: "Tier selection is pinned to the **gross, pre-fee** draw."

    Design: Difficulty/combinatorial_formula/pool_supplemental_tier_keyed_on_gross_draw_mode_c
    """
    pool = fixtures.create_pool(
        api, pool_code="END-BIG", principal_cents=400_000_000, draw_rate_bps=450
    )
    # Gross draw 400000000 x 450 / 10000 = 18000000, which sits in the 75 bps tier,
    # so the supplement is 3000000 and the pre-fee amount is 21000000.  The fee of
    # 2.25 percent is 472500, leaving 20527500 authorized.  Keying the tier on the
    # post-fee figure would cross the 20000000 floor and authorize 22482500.
    assert pool["admin_fee_cents"] == 472_500
    assert pool["draw_authorized_cents"] == 20_527_500
    assert_funding_pool(pool)


def test_a_gross_draw_below_the_first_floor_earns_no_supplement(api):
    """PRD §3.10: "For an `ENDOWMENT` pool the gross draw is the `principal_cents`
    multiplied by the `draw_rate_bps` and divided by 10,000, rounded half up to a
    whole cent."
    PRD §3.10: "The administrative fee is then 2.25 percent of that pre-fee
    authorised amount, rounded half up to a whole cent, and recorded as
    `admin_fee_cents`."
    PRD §3.10: "`draw_authorized_cents` is the pre-fee authorised amount less
    `admin_fee_cents`."

    Design: Difficulty/combinatorial_formula/pool_supplemental_tier_keyed_on_gross_draw_mode_c
    """
    pool = fixtures.create_pool(
        api, pool_code="END-SMALL", principal_cents=80_000_000, draw_rate_bps=450
    )
    # Gross draw 3600000 is below 5000000, so no supplement applies: the fee is
    # 2.25 percent of 3600000 = 81000 and 3519000 is authorized.
    assert pool["admin_fee_cents"] == 81_000
    assert pool["draw_authorized_cents"] == 3_519_000


def test_a_new_pool_is_available_up_to_its_authorized_draw(api):
    """PRD §3.10: "A pool's `available_cents` is then its `draw_authorized_cents`,
    plus its `recovery_credits_cents` — the running total of insurance settlements
    credited back to it, which begins at zero — less the total `amount_cents` of the
    pool's allocations sitting in `RESERVED`, `COMMITTED` or `DISBURSED`."

    Design: Difficulty/combinatorial_formula/pool_supplemental_tier_keyed_on_gross_draw_mode_c
    """
    big = fixtures.create_pool(
        api, pool_code="END-BIG", principal_cents=400_000_000, draw_rate_bps=450
    )
    small = fixtures.create_pool(
        api, pool_code="END-SMALL", principal_cents=80_000_000, draw_rate_bps=450
    )
    assert big["recovery_credits_cents"] == 0
    assert big["available_cents"] == 20_527_500
    assert small["recovery_credits_cents"] == 0
    assert small["available_cents"] == 3_519_000
    # No allocation has been reserved against either pool yet.
    assert_pool_availability_identity(big, 0)
    assert_pool_availability_identity(small, 0)
