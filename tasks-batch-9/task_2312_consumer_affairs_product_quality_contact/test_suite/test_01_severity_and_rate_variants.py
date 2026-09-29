"""Provisional and adjudicated readings of the same underlying facts.

Severity is published twice — once from the intake descriptors alone and once
after a supervisor adjudicates — and a lot's complaint rate is likewise readable
under two variants that count different numerators.
"""

from test_helpers import (
    add_complaint,
    add_contact,
    assert_lot_buckets,
    assert_severity,
    assert_two_decimal_value,
    seed_base_world,
    triage,
    validate_success,
)

# ---------------------------------------------------------------------------
# Divergence between the two severity readings on one complaint
# ---------------------------------------------------------------------------
BADLY_TRANSCRIBED_CODE = "a1b 2026 0710"


def _seed_illness_complaint(api):
    """One ILLNESS complaint with two symptoms on the regulated lot."""
    world = seed_base_world(api, actor_keys=("ag1", "sup1"))
    add_contact(api, world, "ct1")
    add_complaint(
        api,
        world,
        "cp1",
        complaint_type="ILLNESS",
        reported_batch_code=BADLY_TRANSCRIBED_CODE,
        symptom_codes=["NAUSEA", "CRAMPS"],
    )
    return world


class TestSeverityBandDivergence:
    def test_provisional_reading_comes_from_the_intake_descriptors_alone(self, api):
        """Registration scores 50 for ILLNESS plus 3.5 for each of two symptoms.

        PRD: "That additive total, rounded half up to 2 decimal places, is the
        `provisional_severity_score`. Its `provisional_severity_band` is `S1`
        when the score is at least 90, otherwise `S2` when it is at least 60,
        otherwise `S3` when it is at least 30, and otherwise `S4`."

        Design: Difficulty/dual_variant_calc/severity_provisional_vs_adjudicated_band_divergence
        """
        world = _seed_illness_complaint(api)
        complaint = world["complaints"]["cp1"]

        assert_severity(complaint, provisional_score=57.00, provisional_band="S3")
        assert complaint["effective_severity_band"] == "S3"
        assert complaint["adjudicated_severity_score"] is None
        assert complaint["product_identification_status"] == "RESOLVED"
        assert complaint["lot_id"] == world["lot"]["id"]

    def test_adjudication_publishes_a_second_reading_and_leaves_the_first_alone(self, api):
        """The regulated multiplier lifts 57.00 to 61.28 and flips S3 to S2.

        PRD: "That first result is then multiplied by 1.075 when the resolved
        lot's product has `is_regulated_food` true, and rounded half up to 2
        decimal places again; when the product is not a regulated food, the
        first result carries forward unchanged."

        Design: Difficulty/dual_variant_calc/severity_provisional_vs_adjudicated_band_divergence
        """
        world = _seed_illness_complaint(api)

        triaged = triage(api, world, world["complaints"]["cp1"]["id"])

        assert_severity(
            triaged,
            provisional_score=57.00,
            provisional_band="S3",
            adjudicated_score=61.28,
            adjudicated_band="S2",
            effective_band="S2",
        )
        assert triaged["handling_status"] == "TRIAGED"
        assert triaged["triaged_by_ref"] == world.actor("sup1").id

    def test_effective_band_follows_the_adjudicated_reading_once_one_exists(self, api):
        """Before triage the effective band reads provisional, after it reads adjudicated.

        PRD: "Once an adjudicated score exists, `effective_severity_band`
        switches to `adjudicated_severity_band` and stays there; before
        adjudication it reads `provisional_severity_band`."

        Design: Difficulty/dual_variant_calc/severity_provisional_vs_adjudicated_band_divergence
        """
        world = _seed_illness_complaint(api)
        before = world["complaints"]["cp1"]
        assert before["effective_severity_band"] == before["provisional_severity_band"]

        triaged = triage(api, world, before["id"])

        assert triaged["effective_severity_band"] == triaged["adjudicated_severity_band"]
        assert_two_decimal_value(triaged["provisional_severity_score"], 57.00)


# ---------------------------------------------------------------------------
# Divergence between the two rate numerators on one lot
# ---------------------------------------------------------------------------
def _seed_three_complaints_one_triaged(api):
    """Three complaints on the same lot, exactly one of them adjudicated."""
    world = seed_base_world(api, actor_keys=("ag1", "sup1"))
    add_contact(api, world, "ct1")
    add_complaint(
        api,
        world,
        "cp1",
        complaint_type="ILLNESS",
        symptom_codes=["NAUSEA", "CRAMPS"],
    )
    add_complaint(api, world, "cp2", complaint_type="QUALITY")
    add_complaint(api, world, "cp3", complaint_type="PACKAGING")
    world["complaints"]["cp1"] = triage(api, world, world["complaints"]["cp1"]["id"])
    return world


class TestComplaintRateVariantDivergence:
    def test_provisional_variant_counts_every_non_duplicate_linked_complaint(self, api):
        """All three complaints count, triaged or not, over 200,000 units.

        PRD: "The `provisional` variant — the default, used when `variant` is
        omitted or set to `provisional` — counts every complaint linked to the
        lot whose `handling_status` is not `DUPLICATE`, triaged or not."

        Design: Difficulty/dual_variant_calc/lot_rate_provisional_vs_adjudicated_numerator_divergence
        """
        world = _seed_three_complaints_one_triaged(api)
        supervisor = world.headers("sup1")

        read = validate_success(
            api.get_lot_complaint_rate(
                world["lot"]["id"], supervisor, {"variant": "provisional"}
            )
        )

        assert read["production_lot_id"] == world["lot"]["id"]
        assert read["variant"] == "provisional"
        assert read["numerator"] == 3
        assert read["units_produced"] == 200000
        assert_two_decimal_value(read["rate_ppm"], 15.00)
        assert read["rate_undefined"] is False

    def test_adjudicated_variant_counts_only_the_adjudicated_complaint(self, api):
        """The same lot reads 5.00 ppm under the adjudicated numerator.

        PRD: "The `adjudicated` variant counts only those non-duplicate linked
        complaints that carry an `adjudicated_severity_score`."

        Design: Difficulty/dual_variant_calc/lot_rate_provisional_vs_adjudicated_numerator_divergence
        """
        world = _seed_three_complaints_one_triaged(api)
        supervisor = world.headers("sup1")

        provisional = validate_success(
            api.get_lot_complaint_rate(
                world["lot"]["id"], supervisor, {"variant": "provisional"}
            )
        )
        adjudicated = validate_success(
            api.get_lot_complaint_rate(
                world["lot"]["id"], supervisor, {"variant": "adjudicated"}
            )
        )

        assert adjudicated["variant"] == "adjudicated"
        assert adjudicated["numerator"] == 1
        assert_two_decimal_value(adjudicated["rate_ppm"], 5.00)
        assert adjudicated["rate_undefined"] is False
        assert_two_decimal_value(
            provisional["rate_ppm"] - adjudicated["rate_ppm"], 10.00
        )

    def test_lot_buckets_explain_the_two_numerators(self, api):
        """One triage moved a single unit between the lot's two live buckets.

        PRD: "The linked lot's counters shift one unit from
        `provisional_complaint_count` into `adjudicated_complaint_count`,
        leaving `linked_complaint_count` unchanged."

        Design: Difficulty/dual_variant_calc/lot_rate_provisional_vs_adjudicated_numerator_divergence
        """
        world = _seed_three_complaints_one_triaged(api)

        lot = validate_success(
            api.get_production_lot(world["lot"]["id"], world.headers("sup1"))
        )

        assert_lot_buckets(lot, linked=3, provisional=2, adjudicated=1, duplicate=0)
