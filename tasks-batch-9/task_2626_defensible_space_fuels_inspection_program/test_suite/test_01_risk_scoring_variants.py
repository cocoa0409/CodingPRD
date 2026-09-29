"""Parcel hazard scoring: the two scoring variants and the band ladder."""

from test_helpers import (
    BASIS_INTAKE,
    BASIS_VERIFIED,
    add_zone,
    assert_2dp,
    assert_risk,
    assert_zone_grade,
    complete_inspection,
    create_parcel,
    get_parcel,
    noticed_world,
    parcel_payload,
    set_clock,
)
from test_helpers.factories import finding_payload
from test_helpers.test_users import make_inspector_headers
from prd_bench_local_runner.testing import validate_success


HARDENING_SWEEP = (
    ("EAVE_VENTS", "COMPLIANT"),
    ("ROOF_ASSEMBLY", "COMPLIANT"),
    ("WINDOW_GLAZING", "COMPLIANT"),
    ("SIDING", "COMPLIANT"),
    ("GUTTER_DEBRIS", "COMPLIANT"),
    ("DECK_UNDERSIDE", "DEFICIENT"),
)


def _record_hardening_sweep(client, inspection_id, inspector_id):
    """Five compliant elements and one deficient one on the same inspection."""
    headers = make_inspector_headers(inspector_id)
    for item_code, status in HARDENING_SWEEP:
        validate_success(
            client.create_hardening_finding(
                inspection_id, finding_payload(item_code, status), headers=headers
            ),
            201,
        )


def _graded_inspection(client):
    """A noticed inspection carrying three deficient zones and six findings."""
    world = noticed_world(client, scheduled_start_utc="2026-08-20T15:00:00Z",
                          scheduled_end_utc="2026-08-20T17:00:00Z")
    inspection_id = world["inspection"]["id"]
    inspector_id = world["inspector"]["id"]
    world["z0"] = add_zone(client, inspection_id, inspector_id, "ZONE_0_EMBER", 5.0)
    world["z1"] = add_zone(client, inspection_id, inspector_id, "ZONE_1", 15.0)
    world["z2"] = add_zone(client, inspection_id, inspector_id, "ZONE_2", 118.0)
    _record_hardening_sweep(client, inspection_id, inspector_id)
    return world


class TestRiskScoreVariants:
    """The intake-provisional and post-inspection-verified variants disagree."""

    def test_intake_variant_uses_self_reported_vegetation_and_zero_credit(self, client):
        """A freshly registered parcel is scored from its owner's own answers.

        PRD: "The intake-provisional variant runs at parcel creation and on any
        attribute update that changes a scoring field while the parcel has not
        yet been verified in the field; it takes the vegetation subscore from
        the owner's self-reported vegetation_type - 15 points for
        IRRIGATED_LANDSCAPE, 40 for GRASS, 75 for BRUSH and 90 for
        MIXED_CONIFER - and it uses a hardening credit of exactly 0.00, because
        no structure-hardening findings exist yet."

        PRD: "These four subscores are combined into a weighted subtotal in
        which slope carries a weight of 0.30, vegetation carries 0.30,
        structure carries 0.25 and access carries 0.15."

        Design: Difficulty/dual_variant_calc/risk_score_intake_provisional_vs_post_inspection_verified
        """
        set_clock(client, "2026-08-01T00:00:00Z")
        parcel = create_parcel(client, parcel_payload(apn="APN-1001"))

        # slope 30 -> 60 * 0.30, BRUSH -> 75 * 0.30, CLASS_B -> 45 * 0.25,
        # GATED -> 25 * 0.15 gives a weighted subtotal of 55.50, and the HIGH
        # hazard multiplier of 1.15 lifts it to 63.825, rounded half up.
        assert_risk(parcel, 63.83, "HIGH", BASIS_INTAKE)

    def test_verified_variant_replaces_vegetation_and_subtracts_credit_first(
        self, client
    ):
        """Closing out the inspection rescores the parcel into a different band.

        PRD: "The post-inspection-verified variant runs whenever an inspection
        is closed out, whether the result was a pass or a failure; it replaces
        the self-reported vegetation subscore with the inspection's own
        measured_veg_points, and it computes a real hardening credit worth 4.00
        points for each structure-hardening element the inspector found
        compliant on that inspection, capped at 20.00 points however many
        elements were checked."

        PRD: "From the weighted subtotal the system first subtracts the
        structure-hardening credit, and only then multiplies the difference by
        the hazard-zone multiplier - 1.00 for a MODERATE zone, 1.15 for HIGH,
        and 1.30 for VERY_HIGH. Multiplying first and subtracting the credit
        afterwards produces a different number and is incorrect."

        Design: Difficulty/dual_variant_calc/risk_score_intake_provisional_vs_post_inspection_verified
        """
        world = _graded_inspection(client)
        assert world["parcel"]["risk_score_basis"] == BASIS_INTAKE

        # Each zone is graded and rounded on its own before the sum is taken.
        assert_zone_grade(world["z0"], 6.3, 1.3, 0.2063, "MINOR", 30.95)
        assert_zone_grade(world["z1"], 37.5, 22.5, 0.6000, "MAJOR", 60.00)
        assert_zone_grade(world["z2"], 125.0, 7.0, 0.0560, "MINOR", 3.36)

        completed = complete_inspection(
            client,
            world["inspection"]["id"],
            world["inspector"]["id"],
            "FAIL",
            "CERTIFIED_MAIL",
        )
        assert_2dp(completed["measured_veg_points"], 94.31)
        # Five compliant elements are worth 20.00, which is also the cap.
        assert_2dp(completed["hardening_credit_points"], 20.00)

        rescored = get_parcel(client, world["parcel"]["id"])
        # 18.00 + 0.30 * 94.31 + 11.25 + 3.75 = 61.293, less the 20.00 credit,
        # times 1.15 gives 47.487.
        assert_risk(rescored, 47.49, "MODERATE", BASIS_VERIFIED)
        assert rescored["risk_score"] != 63.83, "the intake value must be overwritten"
        assert (
            rescored["risk_score"] != 50.49
        ), "the credit is subtracted before the hazard multiplier, not after"


class TestRiskClassBoundary:
    """The band ladder is inclusive at its lower edge and both clamps bite."""

    def test_score_of_exactly_55_00_bands_as_high(self, client):
        """55.00 is HIGH, and one tenth of a slope point below it is MODERATE.

        PRD: "risk_class bands the resulting score, with every boundary
        inclusive at its lower edge: a score of 75.00 or above is EXTREME, a
        score of 55.00 or above but below 75.00 is HIGH, a score of 35.00 or
        above but below 55.00 is MODERATE, and anything below 35.00 is LOW. A
        score of exactly 55.00 is therefore HIGH, never MODERATE."

        Design: Difficulty/boundary_precision_check/risk_class_high_at_exact_55_00_score
        """
        set_clock(client, "2026-08-01T00:00:00Z")
        edge = create_parcel(
            client,
            parcel_payload(
                apn="APN-7005",
                roof_class="NONE",
                vegetation_type="GRASS",
                slope_pct=20,
                hazard_zone="MODERATE",
                access_constraint="DOG_ON_SITE",
            ),
        )
        # 0.30*40 + 0.30*40 + 0.25*100 + 0.15*40 = 55.00 at a 1.00 multiplier.
        assert_risk(edge, 55.00, "HIGH", BASIS_INTAKE)

        below = create_parcel(
            client,
            parcel_payload(
                apn="APN-7001",
                roof_class="NONE",
                vegetation_type="GRASS",
                slope_pct=19.9,
                hazard_zone="MODERATE",
                access_constraint="DOG_ON_SITE",
            ),
        )
        assert_risk(below, 54.94, "MODERATE", BASIS_INTAKE)

    def test_slope_subscore_saturates_at_its_own_cap(self, client):
        """Slope 70 scores no higher than slope 50 once the cap is applied.

        PRD: "The slope subscore is the parcel's slope_pct multiplied by two,
        capped at 100 - so a 60 percent slope scores the full 100 while a 30
        percent slope scores 60."

        Design: Difficulty/boundary_precision_check/risk_class_high_at_exact_55_00_score
        """
        set_clock(client, "2026-08-01T00:00:00Z")
        steep = create_parcel(
            client, parcel_payload(apn="APN-7002", slope_pct=50, hazard_zone="MODERATE")
        )
        steeper = create_parcel(
            client, parcel_payload(apn="APN-7003", slope_pct=70, hazard_zone="MODERATE")
        )

        assert_2dp(steep["risk_score"], 67.50)
        assert_2dp(steeper["risk_score"], 67.50)
        assert steeper["risk_score"] == steep["risk_score"]
        assert (
            steeper["risk_score"] != 79.50
        ), "an uncapped slope subscore would contribute 0.30 * 140 instead of 30.00"

    def test_score_is_clamped_to_100_before_rounding(self, client):
        """An overflowing product is clamped to 100.00 and bands as EXTREME.

        PRD: "The product is then clamped so that it can never exceed 100.00,
        and the clamped value is rounded half up to two decimal places to give
        risk_score. Clamping happens before rounding, not after."

        Design: Difficulty/boundary_precision_check/risk_class_high_at_exact_55_00_score
        """
        set_clock(client, "2026-08-01T00:00:00Z")
        overflow = create_parcel(
            client,
            parcel_payload(
                apn="APN-7004",
                roof_class="NONE",
                vegetation_type="MIXED_CONIFER",
                slope_pct=50,
                hazard_zone="VERY_HIGH",
                access_constraint="LOCKED_GATE",
            ),
        )
        # The raw product is 91.00 * 1.30 = 118.30.
        assert_risk(overflow, 100.00, "EXTREME", BASIS_INTAKE)
