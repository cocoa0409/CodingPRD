"""Foundation analysis: provisional vs final bearing variants, the inclusive
settlement threshold, n60 input-set filtering, and staleness refresh."""
import pytest

from test_helpers import (
    SEN,
    api_client,
    assert_foundation_analysis,
    clear_boring,
    create_analysis,
    drill_boring,
    file_clearance,
    get_success_data,
    mobilize_assignment,
    run_order_to_accepted,
    schedule_rig,
    setup_accepted_uc_order,
    setup_verified_analysis,
    transition_analysis,
    validate_success,
)


# ---------------------------------------------------------------------------
# Provisional vs final bearing variants (difficulty instance, two tests)
# ---------------------------------------------------------------------------

class TestBearingCapacityProvisionalVsFinal:
    """Identical subsurface data (n60_average 12, qu 4000, fs 3.0) yields
    4800 psf provisional but 6000 psf final."""

    def test_provisional_at_creation_final_after_verification(self, api):
        """PRD section 3.5: "At creation the server computes
        `bearing_capacity_provisional_psf` from SPT data alone: four hundred
        psf per unit of `n60_average`, capped at 8,000 psf and rounded half-up
        to two decimal places." and "On verification the server takes
        `qu_psf` from the project's latest accepted unconfined-compression
        result, halves it for the undrained shear strength, multiplies by
        nine for the ultimate bearing capacity, and divides by `fs_required`;
        the quotient is floored at 1,500 psf and capped at 12,000 psf" and
        "The provisional and final variants deliberately diverge for the same
        ground: with `n60_average` of 12, `qu_psf` of 4,000, and
        `fs_required` of 3.0, the provisional value is 4,800 psf while the
        final value is 6,000 psf."

        Design: Difficulty/dual_variant_calc/bearing_capacity_provisional_vs_final
        """
        ctx = setup_accepted_uc_order(qu_psf=4000)
        analysis = create_analysis(ctx["project"]["id"], fs_required=3.0,
                                   footing_width_ft=6, applied_bearing_psf=3000)
        assert_foundation_analysis(analysis)
        assert analysis["status"] == "PRELIMINARY"
        assert analysis["bearing_capacity_provisional_psf"] == pytest.approx(4800)
        assert analysis["bearing_capacity_final_psf"] is None

        verified = transition_analysis(analysis["id"], "VERIFIED")
        assert verified["status"] == "VERIFIED"
        assert verified["bearing_capacity_final_psf"] == pytest.approx(6000)
        assert verified["bearing_capacity_final_psf"] != pytest.approx(
            verified["bearing_capacity_provisional_psf"]), (
            "The two variants must diverge for identical subsurface data"
        )

    def test_variants_coexist_with_settlement_and_deep_flag(self, api):
        """PRD section 3.5: "The provisional and final variants deliberately
        diverge for the same ground: with `n60_average` of 12, `qu_psf` of
        4,000, and `fs_required` of 3.0, the provisional value is 4,800 psf
        while the final value is 6,000 psf." and "`settlement_est_in` is the
        product of `applied_bearing_psf` and `footing_width_ft` divided by the
        product of 1,200 and `n60_average`, rounded half-up to three decimal
        places, and `deep_foundation_required` is true exactly when the
        estimate reaches 1.0 inch — the threshold is inclusive, so an
        estimate of precisely 1.000 requires a deep foundation."

        Design: Difficulty/dual_variant_calc/bearing_capacity_provisional_vs_final
        """
        ctx = setup_verified_analysis(applied_bearing_psf=3000,
                                      footing_width_ft=6, fs_required=3.0)
        analysis = get_success_data(
            api.get_foundation_analysis(ctx["analysis"]["id"], SEN))
        # Both variants coexist on the same analysis row after VERIFIED.
        assert analysis["bearing_capacity_provisional_psf"] == pytest.approx(4800)
        assert analysis["bearing_capacity_final_psf"] == pytest.approx(6000)
        # 3000 * 6 / (1200 * 12) = 1.25 >= 1.0 -> deep foundation.
        assert analysis["settlement_est_in"] == pytest.approx(1.25, abs=0.001)
        assert analysis["deep_foundation_required"] is True


# ---------------------------------------------------------------------------
# Inclusive settlement threshold (difficulty instance, two tests)
# ---------------------------------------------------------------------------

class TestSettlementThresholdInclusive:
    """settlement_est_in exactly 1.000 requires a deep foundation; just under
    the threshold does not."""

    def test_settlement_exactly_one_inch_requires_deep_foundation(self, api):
        """PRD section 3.5: "`settlement_est_in` is the product of
        `applied_bearing_psf` and `footing_width_ft` divided by the product of
        1,200 and `n60_average`, rounded half-up to three decimal places, and
        `deep_foundation_required` is true exactly when the estimate reaches
        1.0 inch — the threshold is inclusive, so an estimate of precisely
        1.000 requires a deep foundation."

        Design: Difficulty/boundary_precision_check/settlement_threshold_inclusive
        """
        ctx = setup_verified_analysis(applied_bearing_psf=2400,
                                      footing_width_ft=6, fs_required=3.0)
        analysis = ctx["analysis"]
        # 2400 * 6 / (1200 * 12) = 1.000 exactly.
        assert analysis["settlement_est_in"] == pytest.approx(1.0, abs=0.001)
        assert analysis["deep_foundation_required"] is True, (
            "The inclusive >= 1.0 threshold triggers at exactly 1.000"
        )

    def test_settlement_just_below_one_inch_does_not(self, api):
        """PRD section 3.5: "`settlement_est_in` is the product of
        `applied_bearing_psf` and `footing_width_ft` divided by the product of
        1,200 and `n60_average`, rounded half-up to three decimal places, and
        `deep_foundation_required` is true exactly when the estimate reaches
        1.0 inch — the threshold is inclusive, so an estimate of precisely
        1.000 requires a deep foundation."

        Design: Difficulty/boundary_precision_check/settlement_threshold_inclusive
        """
        ctx = setup_verified_analysis(applied_bearing_psf=2390,
                                      footing_width_ft=6, fs_required=3.0)
        analysis = ctx["analysis"]
        # 2390 * 6 / (1200 * 12) = 0.995833... -> 0.996, below the threshold.
        assert analysis["settlement_est_in"] == pytest.approx(0.996, abs=0.001)
        assert analysis["deep_foundation_required"] is False


# ---------------------------------------------------------------------------
# n60 input-set filtering (corner)
# ---------------------------------------------------------------------------

def test_n60_average_excludes_non_drilled_borings(api):
    """PRD section 3.5: "Here `n60_average` is the mean of `avg_n60` over the
    active plan's borings standing in `DRILLED`, `LOGGED`, `CLOSED`, or
    `REFUSED`, recomputed whenever a boring reaches `DRILLED` and itself
    rounded half-up to two decimal places" and "At creation the server
    computes `bearing_capacity_provisional_psf` from SPT data alone: four
    hundred psf per unit of `n60_average`, capped at 8,000 psf and rounded
    half-up to two decimal places."

    Design: Corner/calculations/n60_average_excludes_non_drilled_borings
    """
    from test_helpers import setup_fieldwork_project
    ctx = setup_fieldwork_project(boring_count=2)
    # Drill only B-1; B-2 stays PLANNED (its ticket keeps it field-legal).
    mobilize_assignment(ctx["assignment"]["id"], ctx["subcontractor"]["id"])
    clear_boring(ctx["boring"]["id"])
    drill_boring(ctx["boring"]["id"], ctx["subcontractor"]["id"], avg_n60=12)

    analysis = create_analysis(ctx["project"]["id"])
    # Mean over the DRILLED-only input set is 12 -> 400 * 12 = 4800; the
    # PLANNED boring must not dilute the mean.
    assert analysis["bearing_capacity_provisional_psf"] == pytest.approx(4800)


# ---------------------------------------------------------------------------
# Staleness and the refresh self-loop (corner)
# ---------------------------------------------------------------------------

def test_analysis_refresh_restores_current_after_new_drill(api):
    """PRD section 3.5: "Two events flip a `VERIFIED` analysis's `data_status`
    to `STALE`: any laboratory order of the project being rejected, and any
    boring of the project reaching `DRILLED` while the analysis stands
    verified. A stale analysis cures through a self-loop refresh (`VERIFIED`
    → `VERIFIED`) performed by a `SeniorEngineer`, permitted only while
    `data_status` is `STALE` (`ERR_INVALID_STATE` otherwise); the refresh
    recomputes `bearing_capacity_final_psf` and `settlement_est_in` from
    current inputs and restores `data_status` to `CURRENT`."

    Design: Corner/complexity_layers/analysis_refresh_restores_current_after_new_drill
    """
    ctx = setup_verified_analysis(boring_count=2)
    assert ctx["analysis"]["data_status"] == "CURRENT"
    boring2 = ctx["borings"][1]
    sub_id = ctx["subcontractor"]["id"]

    # Schedule and mobilize a second, exactly adjacent window on B-2.
    assignment2 = schedule_rig(boring2["id"], sub_id,
                               "2026-08-03T16:00:00Z", "2026-08-04T08:00:00Z")
    mobilize_assignment(assignment2["id"], sub_id)
    clear_boring(boring2["id"])
    drill_boring(boring2["id"], sub_id, avg_n60=12)

    stale = get_success_data(
        api.get_foundation_analysis(ctx["analysis"]["id"], SEN))
    assert stale["data_status"] == "STALE", (
        "A boring reaching DRILLED while the analysis is VERIFIED flips it STALE"
    )

    refreshed = transition_analysis(ctx["analysis"]["id"], "VERIFIED")
    assert refreshed["status"] == "VERIFIED"
    assert refreshed["data_status"] == "CURRENT"
    # n60 mean over both DRILLED borings is still 12 -> final still 6000.
    assert refreshed["bearing_capacity_final_psf"] == pytest.approx(6000)
