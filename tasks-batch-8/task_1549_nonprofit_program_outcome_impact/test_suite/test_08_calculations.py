"""Calculation rules: attainment variants and bands, completeness, the
overall impact index, and the dual-variant dq score on the dashboard."""
import pytest

from test_helpers import (
    get_success_data,
    make_data_steward_headers,
    validate_success,
)
from test_helpers.fixtures import (
    create_certification,
    create_instrument,
    publish_instrument,
    record_and_validate,
    record_observation,
    set_clock,
    setup_active_cycle,
    setup_observation_world,
    setup_participant_with_consent,
    setup_program_with_approved_model,
)
from test_helpers.test_users import DIRECTOR, LEAD, PRIVACY, STEWARD


class TestAttainmentVariants:
    def test_provisional_and_final_variants_diverge(self, api):
        """PRD section 3.2: "`PROVISIONAL` admits `PENDING` and `VALIDATED`
        observations (it exists for mid-cycle monitoring), while `FINAL`
        admits only `VALIDATED` observations (it is the default, and the
        variant consumed by milestone evaluation and the impact index)."

        Design: Difficulty/dual_variant_calc/indicator_attainment_provisional_vs_final
        """
        world = setup_observation_world(program_name="Literacy", program_code="LIT")
        ind = world["indicators"]["I1"]
        obs1 = record_observation(
            world["participant"]["id"], ind["id"], world["instrument"]["id"],
            value=80)
        from test_helpers.fixtures import validate_observation
        validate_observation(obs1["id"])
        record_observation(
            world["participant"]["id"], ind["id"], world["instrument"]["id"],
            value=20, collected_at="2026-09-06T00:00:00Z")

        final_resp = api.get_indicator_attainment(
            ind["id"], STEWARD,
            params={"program_cycle_id": world["cycle"]["id"], "variant": "FINAL"})
        final_data = validate_success(final_resp)
        assert final_data["aggregated_value"] == pytest.approx(80.00, abs=0.01)
        assert final_data["attainment_pct"] == pytest.approx(80.00, abs=0.01)
        assert final_data["band"] == "YELLOW"
        assert final_data["observation_count"] == 1

        prov_resp = api.get_indicator_attainment(
            ind["id"], STEWARD,
            params={"program_cycle_id": world["cycle"]["id"], "variant": "PROVISIONAL"})
        prov_data = validate_success(prov_resp)
        assert prov_data["aggregated_value"] == pytest.approx(50.00, abs=0.01)
        assert prov_data["attainment_pct"] == pytest.approx(50.00, abs=0.01)
        assert prov_data["band"] == "RED"
        assert prov_data["observation_count"] == 2

    def test_default_variant_is_final(self, api):
        """PRD section 3.2: "an optional `variant` - `PROVISIONAL` or `FINAL`,
        defaulting to `FINAL`".

        Design: Difficulty/dual_variant_calc/indicator_attainment_provisional_vs_final
        """
        world = setup_observation_world(program_name="Literacy2", program_code="LI2")
        ind = world["indicators"]["I1"]
        obs1 = record_observation(
            world["participant"]["id"], ind["id"], world["instrument"]["id"],
            value=80)
        from test_helpers.fixtures import validate_observation
        validate_observation(obs1["id"])
        record_observation(
            world["participant"]["id"], ind["id"], world["instrument"]["id"],
            value=20, collected_at="2026-09-06T00:00:00Z")

        # No variant -> defaults to FINAL.
        default_resp = api.get_indicator_attainment(
            ind["id"], STEWARD,
            params={"program_cycle_id": world["cycle"]["id"]})
        default_data = validate_success(default_resp)
        assert default_data["aggregated_value"] == pytest.approx(80.00, abs=0.01)
        assert default_data["observation_count"] == 1


class TestAttainmentFormula:
    def test_direction_clamp_zero_guard(self, api):
        """PRD section 3.2: "the zero-guard: if `target_value` equals
        `baseline_value`, attainment is exactly 100.00 when the direction
        condition holds - for `HIGHER_IS_BETTER`, the aggregated value is at
        least the target; for `LOWER_IS_BETTER`, it is at most the target -
        and exactly 0.00 otherwise. Third, when target and baseline differ:
        for `HIGHER_IS_BETTER`, the attainment percentage is one hundred times
        the amount by which the aggregated value exceeds the baseline, divided
        by the amount by which the target exceeds the baseline; for
        `LOWER_IS_BETTER`, it is one hundred times the amount by which the
        baseline exceeds the aggregated value, divided by the amount by which
        the baseline exceeds the target. Fourth, the result is clamped to a
        floor of 0 and a ceiling of 150."

        Design: Difficulty/combinatorial_formula/attainment_direction_clamp_zero_guard
        """
        world = setup_observation_world(
            program_name="Shelter", program_code="SHL",
            indicator_specs=[
                {"code": "L1", "level": "OUTCOME", "unit": "COUNT",
                 "direction": "LOWER_IS_BETTER", "baseline_value": 100,
                 "target_value": 20, "weight": 1.0,
                 "measurement_frequency": "PER_EVENT"},
                {"code": "L2", "level": "OUTCOME", "unit": "COUNT",
                 "direction": "LOWER_IS_BETTER", "baseline_value": 100,
                 "target_value": 20, "weight": 1.0,
                 "measurement_frequency": "PER_EVENT"},
                {"code": "G1", "level": "OUTPUT", "unit": "COUNT",
                 "direction": "HIGHER_IS_BETTER", "baseline_value": 50,
                 "target_value": 50, "weight": 1.0,
                 "measurement_frequency": "PER_EVENT"},
            ])
        indicators = world["indicators"]
        record_and_validate(world["participant"]["id"], indicators["L1"]["id"],
                            world["instrument"]["id"], value=40)
        record_and_validate(world["participant"]["id"], indicators["L2"]["id"],
                            world["instrument"]["id"], value=0)
        record_and_validate(world["participant"]["id"], indicators["G1"]["id"],
                            world["instrument"]["id"], value=50)

        l1 = validate_success(api.get_indicator_attainment(
            indicators["L1"]["id"], STEWARD,
            params={"program_cycle_id": world["cycle"]["id"], "variant": "FINAL"}))
        assert l1["attainment_pct"] == pytest.approx(75.00, abs=0.01)
        assert l1["band"] == "YELLOW"

        l2 = validate_success(api.get_indicator_attainment(
            indicators["L2"]["id"], STEWARD,
            params={"program_cycle_id": world["cycle"]["id"], "variant": "FINAL"}))
        assert l2["attainment_pct"] == pytest.approx(125.00, abs=0.01)
        assert l2["band"] == "GREEN"

        g1 = validate_success(api.get_indicator_attainment(
            indicators["G1"]["id"], STEWARD,
            params={"program_cycle_id": world["cycle"]["id"], "variant": "FINAL"}))
        assert g1["attainment_pct"] == pytest.approx(100.00, abs=0.01)
        assert g1["band"] == "GREEN"

    def test_zero_guard_miss_branch_yields_zero(self, api):
        """PRD section 3.2: "if `target_value` equals `baseline_value`,
        attainment is exactly 100.00 when the direction condition holds - for
        `HIGHER_IS_BETTER`, the aggregated value is at least the target; for
        `LOWER_IS_BETTER`, it is at most the target - and exactly 0.00
        otherwise."

        Design: Difficulty/combinatorial_formula/attainment_direction_clamp_zero_guard
        """
        world = setup_observation_world(
            program_name="Shelter2", program_code="SH2",
            indicator_specs=[{
                "code": "G1", "level": "OUTPUT", "unit": "COUNT",
                "direction": "HIGHER_IS_BETTER", "baseline_value": 50,
                "target_value": 50, "weight": 1.0,
                "measurement_frequency": "PER_EVENT",
            }])
        ind = world["indicators"]["G1"]
        # Aggregated value below target: direction condition fails -> 0.00.
        record_and_validate(world["participant"]["id"], ind["id"],
                            world["instrument"]["id"], value=40)
        data = validate_success(api.get_indicator_attainment(
            ind["id"], STEWARD,
            params={"program_cycle_id": world["cycle"]["id"], "variant": "FINAL"}))
        assert data["attainment_pct"] == pytest.approx(0.00, abs=0.01)
        assert data["band"] == "RED"


class TestAttainmentInputSet:
    def test_attainment_excludes_flagged_and_excluded(self, api):
        """PRD section 3.2: "`FLAGGED` and `EXCLUDED` observations are never
        included in either variant."

        Design: Corner/calculations/attainment_excludes_flagged_and_excluded
        """
        world = setup_observation_world(program_name="Filter", program_code="FLT")
        ind = world["indicators"]["I1"]
        obs_a = record_observation(
            world["participant"]["id"], ind["id"], world["instrument"]["id"],
            value=80)
        from test_helpers.fixtures import validate_observation
        validate_observation(obs_a["id"])

        obs_b = record_observation(
            world["participant"]["id"], ind["id"], world["instrument"]["id"],
            value=20)
        get_success_data(api.flag_observation(
            obs_b["id"], {"reason": "suspect"},
            make_data_steward_headers("steward-1")))

        obs_c = record_observation(
            world["participant"]["id"], ind["id"], world["instrument"]["id"],
            value=1000)
        get_success_data(api.exclude_observation(
            obs_c["id"], {"reason": "out of range"},
            make_data_steward_headers("steward-1")))

        prov = validate_success(api.get_indicator_attainment(
            ind["id"], STEWARD,
            params={"program_cycle_id": world["cycle"]["id"], "variant": "PROVISIONAL"}))
        assert prov["aggregated_value"] == pytest.approx(80.00, abs=0.01)
        assert prov["observation_count"] == 1


class TestAttainmentBands:
    def test_band_boundaries(self, api):
        """PRD section 3.2: "Every surfaced attainment percentage carries an
        **attainment band**: `GREEN` when the percentage is 90.00 or higher,
        `YELLOW` when it is 70.00 or higher but below 90.00, and `RED` below
        70.00. Boundaries are inclusive at the lower edge - exactly 90.00 is
        `GREEN`, exactly 70.00 is `YELLOW`."

        Design: Corner/calculations/attainment_band_boundaries
        """
        world = setup_observation_world(
            program_name="Bands", program_code="BND",
            indicator_specs=[
                {"code": "G", "measurement_frequency": "PER_EVENT"},
                {"code": "Y", "measurement_frequency": "PER_EVENT"},
            ])
        record_and_validate(world["participant"]["id"],
                            world["indicators"]["G"]["id"],
                            world["instrument"]["id"], value=90)
        record_and_validate(world["participant"]["id"],
                            world["indicators"]["Y"]["id"],
                            world["instrument"]["id"], value=89.99)

        g = validate_success(api.get_indicator_attainment(
            world["indicators"]["G"]["id"], STEWARD,
            params={"program_cycle_id": world["cycle"]["id"], "variant": "FINAL"}))
        assert g["attainment_pct"] == pytest.approx(90.00, abs=0.01)
        assert g["band"] == "GREEN"

        y = validate_success(api.get_indicator_attainment(
            world["indicators"]["Y"]["id"], STEWARD,
            params={"program_cycle_id": world["cycle"]["id"], "variant": "FINAL"}))
        assert y["attainment_pct"] == pytest.approx(89.99, abs=0.01)
        assert y["band"] == "YELLOW"


class TestCompleteness:
    def test_completeness_excludes_withdrawn_participants(self, api):
        """PRD section 3.4: "The eligible participants are those in `ACTIVE`,
        `COMPLETED`, or `EXITED` status; the active indicators are those of
        the cycle's pinned logic model in `ACTIVE` status. If either set is
        empty, `data_completeness_pct` is null. Otherwise, for each eligible
        participant, count the distinct active indicators for which that
        participant has at least one observation in `PENDING` or `VALIDATED`
        review status; the completeness percentage is one hundred times the
        sum of these per-participant counts, divided by the product of the
        eligible-participant count and the active-indicator count, rounded
        half-up to two decimal places."

        Design: Corner/calculations/completeness_excludes_withdrawn_participants
        """
        world = setup_observation_world(
            program_name="Complete", program_code="CPL",
            indicator_specs=[{
                "code": "I1", "measurement_frequency": "END_OF_CYCLE",
            }])
        # Add a second consented participant with no observations.
        pc2 = setup_participant_with_consent(world["cycle"]["id"],
                                             external_ref="P-002")
        record_and_validate(world["participant"]["id"],
                            world["indicators"]["I1"]["id"],
                            world["instrument"]["id"], value=70)

        dash_before = validate_success(
            api.get_dashboard(world["cycle"]["id"], STEWARD))
        assert dash_before["data_completeness_pct"] == pytest.approx(50.00, abs=0.01)

        get_success_data(api.revoke_consent(pc2["consent"]["id"], PRIVACY))

        dash_after = validate_success(
            api.get_dashboard(world["cycle"]["id"], STEWARD))
        assert dash_after["data_completeness_pct"] == pytest.approx(100.00, abs=0.01)


class TestImpactIndex:
    def test_impact_index_per_term_rounding(self, api):
        """PRD section 3.8: "for each eligible indicator, take its
        FINAL-variant attainment percentage, multiply it by the indicator's
        `weight`, and round that product half-up to two decimal places
        *before* summing - per-term rounding is pinned, since summing exact
        products and rounding once would produce a different number. The index
        is the sum of those rounded products divided by the sum of the
        eligible indicators' weights (renormalized over the eligible set
        only), with the quotient rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/impact_index_per_term_rounding
        """
        world = setup_observation_world(
            program_name="Jobs", program_code="JOB",
            indicator_specs=[
                {"code": "W1", "level": "IMPACT", "weight": 0.01},
                {"code": "W2", "level": "IMPACT", "weight": 0.01},
                {"code": "W3", "level": "IMPACT", "weight": 0.98},
            ])
        record_and_validate(world["participant"]["id"],
                            world["indicators"]["W1"]["id"],
                            world["instrument"]["id"], value=12.5)
        record_and_validate(world["participant"]["id"],
                            world["indicators"]["W2"]["id"],
                            world["instrument"]["id"], value=12.5)
        record_and_validate(world["participant"]["id"],
                            world["indicators"]["W3"]["id"],
                            world["instrument"]["id"], value=50)

        dash = validate_success(
            api.get_dashboard(world["cycle"]["id"], LEAD))
        # Per-term rounding: round(12.50*0.01)=0.13 twice plus
        # round(50.00*0.98)=49.00 -> 49.26 over weight_sum 1.00.
        assert dash["overall_impact_index"] == pytest.approx(49.26, abs=0.001), (
            "per-term rounding must produce 49.26, not the sum-then-round 49.25"
        )

    def test_impact_index_renormalized_over_eligible_only(self, api):
        """PRD section 3.8: "The eligible indicators are those of the cycle's
        pinned logic model in `ACTIVE` status that have at least one
        `VALIDATED` observation in the cycle. ... The index is the sum of
        those rounded products divided by the sum of the eligible indicators'
        weights (renormalized over the eligible set only)".

        Design: Difficulty/combinatorial_formula/impact_index_per_term_rounding
        """
        world = setup_observation_world(
            program_name="Jobs2", program_code="JB2",
            indicator_specs=[
                {"code": "A", "weight": 1.0},
                {"code": "B", "weight": 5.0},
            ])
        # Only indicator A gets a VALIDATED observation; B stays ineligible.
        record_and_validate(world["participant"]["id"],
                            world["indicators"]["A"]["id"],
                            world["instrument"]["id"], value=40)

        dash = validate_success(
            api.get_dashboard(world["cycle"]["id"], LEAD))
        # Only A is eligible: index = round(40.00 * 1.0) / 1.0 = 40.00.
        assert dash["overall_impact_index"] == pytest.approx(40.00, abs=0.01)


class TestDqVariants:
    def test_dq_score_standard_vs_strict(self, api):
        """PRD section 3.7: "This **STANDARD** variant drives audits, the
        reporting gate, and report snapshots. A **STRICT** variant, surfaced
        on the cycle dashboard as `dq_score_strict`, differs only in V:
        observations flagged `is_late` are dropped from both the numerator
        and the denominator of the validation-coverage component, while C
        and K are computed exactly as in the standard variant."
        PRD section 3.6: "`is_late`: true exactly when `recorded_at` falls
        after the owning cycle's `cycle_end`".

        Design: Difficulty/dual_variant_calc/dq_score_standard_vs_strict
        """
        world = setup_observation_world(program_name="Health", program_code="HLT")
        ind = world["indicators"]["I1"]

        set_clock("2026-09-01T00:00:00Z")
        obs_a = record_observation(
            world["participant"]["id"], ind["id"], world["instrument"]["id"],
            value=100, collected_at="2026-09-01T00:00:00Z")
        from test_helpers.fixtures import validate_observation
        validate_observation(obs_a["id"])

        # Late observation: recorded after cycle_end 2026-09-30T23:59:59Z.
        set_clock("2026-10-05T00:00:00Z")
        obs_b = record_observation(
            world["participant"]["id"], ind["id"], world["instrument"]["id"],
            value=50, collected_at="2026-10-05T00:00:00Z")

        dash = validate_success(
            api.get_dashboard(world["cycle"]["id"], STEWARD))
        # STANDARD: C=100.00, V=50.00 (1 validated of 2 total), K=100.00, F=0
        # -> 0.5*100 + 0.3*50 + 0.2*100 = 85.00.
        assert dash["dq_score_standard"] == pytest.approx(85.00, abs=0.01)
        # STRICT: obs_b dropped from V numerator and denominator ->
        # V=100.00 -> 0.5*100 + 0.3*100 + 0.2*100 = 100.00.
        assert dash["dq_score_strict"] == pytest.approx(100.00, abs=0.01)

        obs_b_after = get_success_data(api.get_observation(obs_b["id"], STEWARD))
        assert obs_b_after["is_late"] is True

    def test_dq_score_variants_agree_without_late_observations(self, api):
        """PRD section 3.7: "A **STRICT** variant, surfaced on the cycle
        dashboard as `dq_score_strict`, differs only in V: observations
        flagged `is_late` are dropped from both the numerator and the
        denominator of the validation-coverage component, while C and K are
        computed exactly as in the standard variant."
        PRD section 3.6: "`is_late`: true exactly when `recorded_at` falls
        after the owning cycle's `cycle_end`".

        Design: Difficulty/dual_variant_calc/dq_score_standard_vs_strict
        """
        # With no late observations the two variants coincide -- V is
        # identical because nothing is dropped from the STRICT input set.
        world = setup_observation_world(program_name="Health2", program_code="HL2")
        ind = world["indicators"]["I1"]
        record_and_validate(world["participant"]["id"], ind["id"],
                            world["instrument"]["id"], value=80)

        dash = validate_success(
            api.get_dashboard(world["cycle"]["id"], STEWARD))
        assert dash["dq_score_standard"] == pytest.approx(100.00, abs=0.01)
        assert dash["dq_score_strict"] == pytest.approx(100.00, abs=0.01)

    def test_dashboard_null_state_on_fresh_cycle(self, api):
        """PRD section 3.4: "If either set is empty, `data_completeness_pct`
        is null."
        PRD section 3.8: "If no indicator is eligible, or the eligible
        indicators' `weight` values sum to zero, the index is null."
        PRD section 3.7: "**C** is the cycle's `data_completeness_pct`, or
        0.00 when it is null; **V** is one hundred times
        `validated_observation_count` divided by `total_observation_count`,
        rounded half-up to two decimals, or 0.00 when the total is zero; **K**
        is one hundred times the number of the cycle's participants whose
        `consent_status` is `CURRENT`, divided by the number of its
        participants not in `WITHDRAWN`, rounded half-up to two decimals, or
        0.00 when there are none."

        Design: Corner/endpoints/dashboard_null_state_on_fresh_cycle
        """
        base = setup_program_with_approved_model(program_name="Dash",
                                                 program_code="DSH")
        cycle = setup_active_cycle(base["program"])

        dash = validate_success(api.get_dashboard(cycle["id"], LEAD))
        assert dash["overall_impact_index"] is None
        assert dash["data_completeness_pct"] is None
        assert dash["dq_score_standard"] == pytest.approx(0.00, abs=0.001)
        assert dash["dq_score_strict"] == pytest.approx(0.00, abs=0.001)
