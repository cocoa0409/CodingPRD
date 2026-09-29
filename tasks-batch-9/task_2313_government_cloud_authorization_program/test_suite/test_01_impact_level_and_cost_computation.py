"""Impact-level determination, matrix coverage and engagement pricing.

This file covers the computed figures that sit at the front of the authorization
workflow: the two impact-level variants and the baseline they bind (PRD 3.2), the
two-step rounding of customer-responsibility-matrix coverage (PRD 3.4), the
three-part engagement cost rollup (PRD 3.5), and the two residual-risk variants
that a package snapshot and a live authorization disagree about (PRD 3.6).
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    BOARD_1,
    BOARD_2,
    BOARD_HEADERS,
    CSP_LEAD_HEADERS,
)

# The HIGH baseline shape used opposite ``factories.MODERATE_FAMILIES``: four
# required AC controls and two required SC controls, six in total.
HIGH_FAMILIES = [f.build_family("AC", 4, 1), f.build_family("SC", 2, 2)]

# A baseline whose SC family requires nothing at all.
ZERO_SC_FAMILIES = [f.build_family("AC", 3, 1), f.build_family("SC", 0, 2)]

# One MODERATE information type, confirmed, beside one HIGH type left declared.
PII_CONFIRMED = {
    "category_code": "PII",
    "confidentiality_impact": "MODERATE",
    "integrity_impact": "MODERATE",
    "availability_impact": "LOW",
    "confirm": True,
}
FIN_DECLARED = {
    "category_code": "FIN",
    "confidentiality_impact": "HIGH",
    "integrity_impact": "LOW",
    "availability_impact": "LOW",
    "confirm": False,
}

SETUP_CLOCK = fx.SETUP_CLOCK  # 2026-02-01T00:00:00Z
REPORT_CLOCK = "2026-03-30T00:00:00Z"
SUBMISSION_CLOCK = "2026-06-01T00:00:00Z"

# The six-row control set of the split-rounding shape: AC counts 2 of 3 and SC
# counts 1 of 6, because PLANNED, ALTERNATIVE_IMPLEMENTATION and undocumented
# rows never count.
SPLIT_ROUNDING_CONTROLS = (
    {"control_id": "AC-2", "family_code": "AC", "implementation_status": "IMPLEMENTED",
     "crm_documented": True},
    {"control_id": "AC-3", "family_code": "AC",
     "implementation_status": "PARTIALLY_IMPLEMENTED", "crm_documented": True},
    {"control_id": "AC-6", "family_code": "AC", "implementation_status": "PLANNED",
     "crm_documented": False},
    {"control_id": "SC-7", "family_code": "SC", "implementation_status": "IMPLEMENTED",
     "crm_documented": True},
    {"control_id": "SC-8", "family_code": "SC", "implementation_status": "IMPLEMENTED",
     "crm_documented": False},
    {"control_id": "SC-12", "family_code": "SC",
     "implementation_status": "ALTERNATIVE_IMPLEMENTATION", "crm_documented": True},
)


def _assert_not_figure(actual, forbidden: float, label: str) -> None:
    """Assert a two-decimal figure is not the named wrong alternative."""
    assert abs(float(actual) - forbidden) > 0.005, (
        f"{label}: must not be {forbidden}, got {actual}"
    )


def _seed_two_baselines(client):
    """Reference data carrying both a HIGH and a MODERATE control baseline."""
    env = fx.seed_reference_data(
        client, clock=SETUP_CLOCK, impact_level="HIGH", families=HIGH_FAMILIES
    )
    env["high_baseline"] = env["baseline"]
    env["moderate_baseline"] = fx.create_baseline(
        client, impact_level="MODERATE", families=list(f.MODERATE_FAMILIES)
    )
    return env


def _determine_impact(client, env):
    """Run the impact determination as a program board reviewer."""
    return validate_success(
        client.determine_impact(env["offering_id"], {}, BOARD_HEADERS), 200
    )


def _split_rounding_coverage(client, families, controls):
    """A categorized offering against ``families`` with ``controls`` recorded."""
    env = fx.seed_reference_data(
        client, clock=SETUP_CLOCK, impact_level="MODERATE", families=families
    )
    env = fx.seed_categorized_offering(client, env)
    env = fx.seed_control_implementations(client, env, controls)
    return env


def _authorize_with_an_extended_moderate_finding(client):
    """Authorize an offering carrying one MODERATE finding with a 60-day extension.

    The finding is detected at 2026-02-01, so its severity base allowance puts
    its unextended deadline at 2026-05-02 and the approved operational-
    requirement extension moves its live deadline to 2026-07-01. Submission then
    happens at 2026-06-01, between the two.
    """
    env = fx.seed_reference_data(client, clock=SETUP_CLOCK)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_poam_item(
        client,
        env,
        severity="MODERATE",
        source="SELF_IDENTIFIED",
        control_id="AC-2",
        detected_at=SETUP_CLOCK,
    )
    env = fx.seed_deviation(
        client,
        env,
        env["poam_id"],
        kind="OPERATIONAL_REQUIREMENT",
        requested_extension_days=60,
        review_queue="BOARD",
        router=BOARD_1,
    )
    fx.decide_deviation(
        client, env, env["deviation_id"], decision="APPROVE", decider=BOARD_2
    )
    env = fx.seed_engagement(
        client, env, contracted_hours=200.00, labor_cost_usd=120000.00
    )
    env = fx.seed_report_delivered(client, env, findings=[], report_at=REPORT_CLOCK)
    env = fx.seed_package(client, env)
    fx.set_clock(client, SUBMISSION_CLOCK)
    env["clock_set_to"] = SUBMISSION_CLOCK
    return env


# ---------------------------------------------------------------------------
# The two impact-level variants and the baseline they bind
# ---------------------------------------------------------------------------


def test_preliminary_impact_outranks_final_when_a_high_category_stays_unconfirmed(client):
    """A declared-only HIGH information type lifts the preliminary level but not the final one.

    PRD: "An unconfirmed `HIGH` category therefore does not raise the final level, while a `HIGH` external dependency does."

    Design: Difficulty/dual_variant_calc/preliminary_impact_level_outranks_final_when_a_high_category_stays_unconfirmed
    """
    env = _seed_two_baselines(client)
    env = fx.seed_draft_offering(client, env)
    env = fx.declare_categories(client, env, [PII_CONFIRMED, FIN_DECLARED])

    offering = _determine_impact(client, env)

    assert offering["status"] == "CATEGORIZED"
    assert offering["preliminary_impact_level"] == "HIGH"
    assert offering["final_impact_level"] == "MODERATE"
    assert offering["final_impact_level"] != offering["preliminary_impact_level"]


def test_impact_determination_binds_the_moderate_baseline_while_the_high_category_waits(client):
    """The bound baseline follows the final level, so the HIGH baseline is passed over.

    PRD: "Candidates are the control baselines whose `impact_level` equals the determined final level and whose `retired` flag is false; if that candidate set is empty the request fails with `ERR_BASELINE_NOT_AVAILABLE`."

    Design: Difficulty/dual_variant_calc/preliminary_impact_level_outranks_final_when_a_high_category_stays_unconfirmed
    """
    env = _seed_two_baselines(client)
    env = fx.seed_draft_offering(client, env)
    env = fx.declare_categories(client, env, [PII_CONFIRMED, FIN_DECLARED])

    offering = _determine_impact(client, env)

    assert offering["baseline_id"] == env["moderate_baseline"]["id"]
    assert offering["baseline_id"] != env["high_baseline"]["id"]

    categories = get_success_data(
        client.list_data_categories(env["offering_id"], CSP_LEAD_HEADERS), 200
    )
    fin = [row for row in categories if row["category_code"] == "FIN"]
    assert len(fin) == 1, f"expected exactly one FIN category, got {categories}"
    assert fin[0]["status"] == "DECLARED"
    assert fin[0]["confirmed_by_user_id"] is None


def test_high_external_dependency_raises_the_final_impact_level_above_the_preliminary(client):
    """A HIGH external dependency lifts the final level while the preliminary level ignores it.

    PRD: "Otherwise take the highest of the three ratings for each confirmed category, take the greatest of those per-category highs as a water mark, and then compare that water mark's rank against the rank of the offering's `external_dependency_impact_level`: `final_impact_level` is the level whose rank is the greater of the two."

    Design: Difficulty/dual_variant_calc/final_impact_level_escalates_by_external_dependency_that_preliminary_ignores
    """
    env = _seed_two_baselines(client)
    env = fx.seed_draft_offering(client, env, external_dependency_impact_level="HIGH")
    env = fx.declare_categories(client, env, [PII_CONFIRMED])

    offering = _determine_impact(client, env)

    assert offering["status"] == "CATEGORIZED"
    assert offering["preliminary_impact_level"] == "MODERATE"
    assert offering["final_impact_level"] == "HIGH"
    assert offering["final_impact_level"] != offering["preliminary_impact_level"]


def test_escalated_determination_binds_the_six_control_high_baseline(client):
    """The escalated determination binds the HIGH baseline, whose families total six required controls.

    PRD: "On publication the server computes `total_required_controls` as the sum of the `required_control_count` values across all families."

    Design: Difficulty/dual_variant_calc/final_impact_level_escalates_by_external_dependency_that_preliminary_ignores
    """
    env = _seed_two_baselines(client)
    a.assert_integer(
        env["high_baseline"]["total_required_controls"], 6, "HIGH total_required_controls"
    )
    a.assert_integer(
        env["moderate_baseline"]["total_required_controls"],
        3,
        "MODERATE total_required_controls",
    )

    env = fx.seed_draft_offering(client, env, external_dependency_impact_level="HIGH")
    env = fx.declare_categories(client, env, [PII_CONFIRMED])

    offering = _determine_impact(client, env)

    assert offering["baseline_id"] == env["high_baseline"]["id"]
    assert offering["baseline_id"] != env["moderate_baseline"]["id"]


# ---------------------------------------------------------------------------
# The two residual-risk variants across one authorization
# ---------------------------------------------------------------------------


def test_approved_operational_requirement_extension_moves_the_finding_deadline(client):
    """An approved 60-day operational-requirement extension pushes the deadline to 2026-07-01.

    PRD: "Approving an `OPERATIONAL_REQUIREMENT` request in the board queue sets the request's `granted_extension_days` to the `requested_extension_days` figure, copies that figure onto the finding's own `granted_extension_days`, recomputes the finding's `deadline_at` from its anchor with the extension included, moves the finding's `risk_disposition` `DEVIATION_REQUESTED → EXTENSION_GRANTED`, and recomputes the authorization's `residual_risk_score`."

    Design: Difficulty/dual_variant_calc/residual_risk_at_submission_ignores_the_extension_that_the_monitoring_variant_honours
    """
    env = _authorize_with_an_extended_moderate_finding(client)

    finding = fx.read_poam_item(client, env["poam_id"])
    a.assert_integer(finding["granted_extension_days"], 60, "granted_extension_days")
    assert finding["risk_disposition"] == "EXTENSION_GRANTED"
    assert finding["remediation_status"] == "OPEN"
    a.assert_instant(finding["anchor_at"], SETUP_CLOCK, "anchor_at")
    a.assert_instant(
        finding["deadline_at"],
        a.expected_deadline(SETUP_CLOCK, "MODERATE", 60),
        "deadline_at",
    )
    a.assert_instant(finding["deadline_at"], "2026-07-01T00:00:00Z", "deadline_at")
    assert not a.instants_equal(finding["deadline_at"], "2026-05-02T00:00:00Z"), (
        "deadline_at must include the granted extension, not stop at the base allowance"
    )


def test_package_snapshot_scores_the_extended_finding_as_overdue_at_submission(client):
    """The submission snapshot measures the finding against its unextended deadline and scores 6.00.

    PRD: "The **submission** variant is frozen onto a package at submission time: its as-of instant is the package's `submitted_at`, and the deadline each finding is measured against is its anchor advanced by the severity base allowance *ignoring* `granted_extension_days` — a package snapshot uses assessment-time deadlines and does not benefit from later relief."

    Design: Difficulty/dual_variant_calc/residual_risk_at_submission_ignores_the_extension_that_the_monitoring_variant_honours
    """
    env = _authorize_with_an_extended_moderate_finding(client)

    package = validate_success(
        client.submit_package(env["package_id"], env["lead_headers"]), 200
    )

    a.assert_instant(package["submitted_at"], SUBMISSION_CLOCK, "submitted_at")
    unextended_deadline = a.expected_deadline(SETUP_CLOCK, "MODERATE")
    a.assert_instant(unextended_deadline, "2026-05-02T00:00:00Z", "unextended deadline")
    a.assert_money(
        package["residual_risk_score_at_submission"],
        a.expected_residual_risk(
            [
                {
                    "severity": "MODERATE",
                    "risk_disposition": "EXTENSION_GRANTED",
                    "deadline_at": unextended_deadline,
                }
            ],
            SUBMISSION_CLOCK,
        ),
        "residual_risk_score_at_submission",
    )
    a.assert_money(
        package["residual_risk_score_at_submission"],
        6.00,
        "residual_risk_score_at_submission",
    )
    _assert_not_figure(
        package["residual_risk_score_at_submission"],
        4.00,
        "residual_risk_score_at_submission",
    )
    a.assert_integer(package["open_findings_at_submission"], 1, "open_findings_at_submission")
    a.assert_money(package["crm_coverage_pct"], 100.00, "crm_coverage_pct")


def test_authorization_stores_the_monitoring_score_that_honours_the_extension(client):
    """The authorization scores the same finding at 4.00, because its live deadline has not passed.

    PRD: "The **monitoring** variant is the one stored on the authorization as `residual_risk_score`: its as-of instant is the logical clock and the deadline each finding is measured against is its live `deadline_at`, which *includes* `granted_extension_days`, so an approved operational-requirement extension pulls a finding back out of the overdue multiplier."

    Design: Difficulty/dual_variant_calc/residual_risk_at_submission_ignores_the_extension_that_the_monitoring_variant_honours
    """
    env = _authorize_with_an_extended_moderate_finding(client)
    env = fx.submit_package(client, env)
    env = fx.review_package(client, env, reviewer=BOARD_1)
    env = fx.decide_package(client, env, decision="AUTHORIZE")

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_money(
        authorization["residual_risk_score"],
        a.expected_residual_risk(
            [
                {
                    "severity": "MODERATE",
                    "risk_disposition": "EXTENSION_GRANTED",
                    "deadline_at": "2026-07-01T00:00:00Z",
                }
            ],
            SUBMISSION_CLOCK,
        ),
        "residual_risk_score",
    )
    a.assert_money(authorization["residual_risk_score"], 4.00, "residual_risk_score")
    _assert_not_figure(authorization["residual_risk_score"], 6.00, "residual_risk_score")
    assert authorization["poam_risk_tier"] == "LOW"
    a.assert_risk_tier_matches_score(authorization)

    package = fx.read_package(client, env["package_id"])
    delta = float(package["residual_risk_score_at_submission"]) - float(
        authorization["residual_risk_score"]
    )
    a.assert_money(delta, 2.00, "submission score less monitoring score")

    summary = fx.read_risk_summary(client, env["authorization_id"])
    a.assert_money(summary["residual_risk_score"], 4.00, "live residual_risk_score")
    a.assert_money(
        summary["stored_residual_risk_score"], 4.00, "stored_residual_risk_score"
    )
    a.assert_integer(summary["open_findings_count"], 1, "open_findings_count")


# ---------------------------------------------------------------------------
# Matrix coverage: two rounding steps in a pinned order
# ---------------------------------------------------------------------------


def test_crm_coverage_rounds_each_family_before_the_weighted_mean(client):
    """Rounding each family first and the weighted mean second yields 33.34, not the collapsed 33.33.

    PRD: "Collapsing the calculation into a single ratio of total documented controls to total required controls is a different and incorrect computation — for a baseline requiring 3 controls in family AC with 2 documented and 6 controls in family SC with 1 documented, the pinned order yields 33.34 while the collapsed ratio yields 33.33."

    Design: Difficulty/combinatorial_formula/crm_coverage_rounds_each_family_before_the_weighted_mean
    """
    env = _split_rounding_coverage(
        client, list(f.SPLIT_ROUNDING_FAMILIES), SPLIT_ROUNDING_CONTROLS
    )

    coverage = validate_success(
        client.get_crm_coverage(env["offering_id"], CSP_LEAD_HEADERS), 200
    )

    a.assert_money(coverage["overall_coverage_pct"], 33.34, "overall_coverage_pct")
    a.assert_money(
        coverage["overall_coverage_pct"],
        a.expected_overall_coverage([(2, 3), (1, 6)]),
        "overall_coverage_pct",
    )
    _assert_not_figure(coverage["overall_coverage_pct"], 33.33, "overall_coverage_pct")
    # AC rounds to 66.67 and SC to 16.67 before the weighted mean is taken.
    a.assert_integer(coverage["weight_total"], 9, "weight_total")


def test_crm_coverage_counting_set_excludes_planned_alternative_and_undocumented_rows(client):
    """Only documented IMPLEMENTED and PARTIALLY_IMPLEMENTED rows count, so six rows score 33.34.

    PRD: "For each remaining family, count the offering's control implementations whose `family_code` matches that family, whose `implementation_status` is either `IMPLEMENTED` or `PARTIALLY_IMPLEMENTED`, and whose `crm_documented` is true — implementations that are `PLANNED`, `ALTERNATIVE_IMPLEMENTATION` or `NOT_APPLICABLE` never count, and neither does an implementation whose matrix entry is undocumented."

    Design: Difficulty/combinatorial_formula/crm_coverage_rounds_each_family_before_the_weighted_mean
    """
    env = _split_rounding_coverage(
        client, list(f.SPLIT_ROUNDING_FAMILIES), SPLIT_ROUNDING_CONTROLS
    )

    coverage = validate_success(
        client.get_crm_coverage(env["offering_id"], CSP_LEAD_HEADERS), 200
    )

    a.assert_money(coverage["overall_coverage_pct"], 33.34, "overall_coverage_pct")
    # Counting all six rows would make AC 3 of 3 and SC 3 of 6, giving 66.67.
    _assert_not_figure(
        coverage["overall_coverage_pct"],
        a.expected_overall_coverage([(3, 3), (3, 6)]),
        "overall_coverage_pct",
    )
    _assert_not_figure(coverage["overall_coverage_pct"], 66.67, "overall_coverage_pct")
    assert len(coverage["family_breakdown"]) == 2, (
        f"expected one breakdown entry per weighted family, got {coverage['family_breakdown']}"
    )
    a.assert_instant(coverage["evaluated_at"], SETUP_CLOCK, "evaluated_at")


def test_crm_coverage_excludes_the_zero_requirement_family_from_the_mean(client):
    """A family requiring nothing is skipped, so a documented SC control cannot lift 66.67.

    PRD: "A family whose `required_control_count` is zero is skipped entirely: it contributes to neither the numerator nor the weight."

    Design: Difficulty/combinatorial_formula/crm_coverage_excludes_zero_requirement_family_from_numerator_and_weight
    """
    env = _split_rounding_coverage(
        client,
        ZERO_SC_FAMILIES,
        (("AC-2", "AC"), ("AC-3", "AC"), ("SC-7", "SC")),
    )

    coverage = validate_success(
        client.get_crm_coverage(env["offering_id"], CSP_LEAD_HEADERS), 200
    )

    a.assert_money(coverage["overall_coverage_pct"], 66.67, "overall_coverage_pct")
    a.assert_money(
        coverage["overall_coverage_pct"],
        a.expected_overall_coverage([(2, 3), (1, 0)]),
        "overall_coverage_pct",
    )
    # Treating the zero-requirement family as 100 percent at weight 1 gives 75.00.
    _assert_not_figure(coverage["overall_coverage_pct"], 75.00, "overall_coverage_pct")
    _assert_not_figure(coverage["overall_coverage_pct"], 100.00, "overall_coverage_pct")


def test_zero_requirement_family_adds_neither_baseline_total_nor_coverage_weight(client):
    """The SC family requiring nothing leaves the baseline total and the coverage weight at 3.

    PRD: "On publication the server computes `total_required_controls` as the sum of the `required_control_count` values across all families."

    Design: Difficulty/combinatorial_formula/crm_coverage_excludes_zero_requirement_family_from_numerator_and_weight
    """
    env = _split_rounding_coverage(
        client,
        ZERO_SC_FAMILIES,
        (("AC-2", "AC"), ("AC-3", "AC"), ("SC-7", "SC")),
    )
    a.assert_integer(
        env["baseline"]["total_required_controls"], 3, "total_required_controls"
    )

    coverage = validate_success(
        client.get_crm_coverage(env["offering_id"], CSP_LEAD_HEADERS), 200
    )

    a.assert_integer(coverage["weight_total"], 3, "weight_total")
    assert len(coverage["family_breakdown"]) == 1, (
        f"the zero-requirement family must not be weighted, got {coverage['family_breakdown']}"
    )


# ---------------------------------------------------------------------------
# Engagement pricing: three constants composing into one total
# ---------------------------------------------------------------------------


def test_engagement_surcharge_tier_keys_on_labor_cost_not_on_the_total(client):
    """A labor cost one cent below the tier ceiling draws 0.06 even though the total clears it.

    PRD: "First the program surcharge: the `surcharge_rate` is selected from a tier keyed on `labor_cost_usd` and never on the total — a labor cost below 250000.00 draws a rate of 0.06, a labor cost of at least 250000.00 but below 600000.00 draws 0.045, and a labor cost of 600000.00 or more draws 0.03."

    Design: Difficulty/combinatorial_formula/engagement_surcharge_tier_keys_on_labor_cost_not_on_total_cost
    """
    env = fx.seed_reference_data(client, clock=SETUP_CLOCK)
    env = fx.seed_path_selected_offering(client, env)

    engagement = validate_success(
        client.create_engagement(
            f.build_engagement_payload(
                env["offering_id"], contracted_hours=900.00, labor_cost_usd=249999.99
            ),
            env["lead_headers"],
        ),
        201,
    )

    a.assert_engagement_costs(engagement, 249999.99, 900.00, "MODERATE")
    a.assert_money(engagement["surcharge_rate"], 0.06, "surcharge_rate")
    a.assert_money(engagement["program_surcharge_usd"], 15000.00, "program_surcharge_usd")
    a.assert_money(engagement["total_cost_usd"], 264999.99, "total_cost_usd")
    # Re-deriving the tier from the total would charge 0.045 and give 261249.99.
    _assert_not_figure(engagement["total_cost_usd"], 261249.99, "total_cost_usd")
    _assert_not_figure(engagement["surcharge_rate"], 0.045, "surcharge_rate")


def test_engagement_within_the_hour_allowance_draws_no_overage(client):
    """Contracting exactly the MODERATE allowance of 900 hours leaves the overage at zero.

    PRD: "Subtract that allowance from `contracted_hours`; if the difference is negative treat it as zero; multiply the result by 120.00 US dollars per hour and round half up to two decimal places to obtain `hour_overage_usd`."

    Design: Difficulty/combinatorial_formula/engagement_surcharge_tier_keys_on_labor_cost_not_on_total_cost
    """
    env = fx.seed_reference_data(client, clock=SETUP_CLOCK)
    env = fx.seed_path_selected_offering(client, env)

    engagement = validate_success(
        client.create_engagement(
            f.build_engagement_payload(
                env["offering_id"], contracted_hours=900.00, labor_cost_usd=249999.99
            ),
            env["lead_headers"],
        ),
        201,
    )

    a.assert_money(engagement["hour_overage_usd"], 0.00, "hour_overage_usd")
    a.assert_money(engagement["allocated_hours"], 0.00, "allocated_hours")
    a.assert_money(engagement["unallocated_hours"], 900.00, "unallocated_hours")
    assert engagement["status"] == "DRAFT"
    a.assert_hour_conservation(engagement)


def test_engagement_at_the_tier_boundary_draws_the_mid_surcharge_rate(client):
    """A labor cost of exactly 250000.00 crosses into the 0.045 tier.

    PRD: "First the program surcharge: the `surcharge_rate` is selected from a tier keyed on `labor_cost_usd` and never on the total — a labor cost below 250000.00 draws a rate of 0.06, a labor cost of at least 250000.00 but below 600000.00 draws 0.045, and a labor cost of 600000.00 or more draws 0.03."

    Design: Difficulty/combinatorial_formula/engagement_overage_multiplies_hours_beyond_the_impact_level_allowance
    """
    env = fx.seed_reference_data(client, clock=SETUP_CLOCK)
    env = fx.seed_path_selected_offering(client, env)

    engagement = validate_success(
        client.create_engagement(
            f.build_engagement_payload(
                env["offering_id"], contracted_hours=1000.00, labor_cost_usd=250000.00
            ),
            env["lead_headers"],
        ),
        201,
    )

    a.assert_money(engagement["surcharge_rate"], 0.045, "surcharge_rate")
    a.assert_money(engagement["program_surcharge_usd"], 11250.00, "program_surcharge_usd")
    _assert_not_figure(engagement["surcharge_rate"], 0.06, "surcharge_rate")
    _assert_not_figure(engagement["program_surcharge_usd"], 15000.00, "program_surcharge_usd")


def test_engagement_hours_beyond_the_moderate_allowance_are_charged_at_the_overage_rate(client):
    """The MODERATE allowance of 900 hours leaves 100 chargeable hours, totalling 273250.00.

    PRD: "Second the hour overage: each impact level comes with an included hour allowance — 400 hours at `LOW`, 900 hours at `MODERATE` and 1600 hours at `HIGH`, read from the offering's `final_impact_level`."

    Design: Difficulty/combinatorial_formula/engagement_overage_multiplies_hours_beyond_the_impact_level_allowance
    """
    env = fx.seed_reference_data(client, clock=SETUP_CLOCK)
    env = fx.seed_path_selected_offering(client, env)
    assert env["offering"]["final_impact_level"] == "MODERATE"

    engagement = validate_success(
        client.create_engagement(
            f.build_engagement_payload(
                env["offering_id"], contracted_hours=1000.00, labor_cost_usd=250000.00
            ),
            env["lead_headers"],
        ),
        201,
    )

    a.assert_engagement_costs(engagement, 250000.00, 1000.00, "MODERATE")
    a.assert_money(engagement["hour_overage_usd"], 12000.00, "hour_overage_usd")
    a.assert_money(engagement["total_cost_usd"], 273250.00, "total_cost_usd")
    # The HIGH allowance of 1600 hours would zero the overage and give 261250.00.
    _assert_not_figure(engagement["total_cost_usd"], 261250.00, "total_cost_usd")
    a.assert_money(engagement["unallocated_hours"], 1000.00, "unallocated_hours")
    a.assert_hour_conservation(engagement)
