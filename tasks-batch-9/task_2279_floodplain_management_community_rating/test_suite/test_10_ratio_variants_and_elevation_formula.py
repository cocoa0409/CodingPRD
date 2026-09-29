"""Dual-variant ratio / class arithmetic and the multi-factor formulas.

Every scenario is built from scratch through PRD-declared endpoints only.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    add_property,
    analyze_area,
    complete_outreach,
    delineate_area,
    designate_area,
    draft_standard,
    issue_violation,
    launch_outreach,
    make_administrator_headers,
    open_case,
    open_cycle,
    read_area,
    read_community,
    read_compliance_summary,
    read_standard,
    read_structure,
    record_delivery,
    record_visit,
    register_community,
    resolve_violation,
    setup_ledger,
    setup_parcel,
    setup_structure,
    start_permit,
    submit_cycle,
    submit_standard,
    validate_success,
    verify_standard,
)

ADMIN_FPA_01 = make_administrator_headers("fpa-01")
COORDINATOR = TEST_USERS["coordinator_headers"]
ADMINISTRATOR = TEST_USERS["administrator_headers"]

COMMUNITY_1_5_FT = {"freeboard_ft": 1.5, "cumulative_period_years": 10}
PANEL_AE_12 = {"flood_zone": "AE", "base_flood_elevation_ft": 12.0}


# --------------------------------------------------------------------------
# Private composites
# --------------------------------------------------------------------------

def _setup_two_record_ledger_with_case(method):
    """A 200000.00 structure carrying 60000.00 of 2019 work and 45000.00 of 2026
    work, plus an administrator-opened case using `method`."""
    scenario = setup_ledger(
        [
            {"record_type": "IMPROVEMENT", "event_date": "2019-03-01T00:00:00Z",
             "cost_usd": 60_000.00},
            {"record_type": "IMPROVEMENT", "event_date": "2026-03-01T00:00:00Z",
             "cost_usd": 45_000.00},
        ],
        community_overrides=COMMUNITY_1_5_FT,
        panel_overrides=PANEL_AE_12,
        structure_overrides={
            "structure_use": "RESIDENTIAL",
            "construction_year": 1998,
            "market_value_usd": 200_000.00,
            "highest_adjacent_grade_ft": 10.0,
        },
    )
    scenario["case"] = open_case(
        scenario["structure"]["id"], method=method, headers=ADMIN_FPA_01
    )
    return scenario


def _setup_freeboard_claim_and_visited_cycle():
    """A community claiming 700 points against a 1.5 ft freeboard ordinance, with
    the 2026 cycle already SUBMITTED, the claim VERIFIED and the visit recorded."""
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)
    standard = draft_standard(
        community["id"],
        activity_code="A430_FREEBOARD",
        documentation_cycle_year=2026,
        claimed_points=700,
    )
    submit_standard(standard["id"])
    cycle = open_cycle(
        community["id"],
        cycle_year=2026,
        cycle_start_date="2026-01-01T00:00:00Z",
        cycle_end_date="2026-12-31T00:00:00Z",
        due_at="2026-09-30T00:00:00Z",
    )
    cycle = submit_cycle(cycle["id"])
    standard = verify_standard(standard["id"])
    record_visit(cycle["id"], visit_note="Field verification of freeboard ordinance")
    return {"community": community, "standard": standard, "cycle": cycle}


def _setup_draft_permit(structure_use, market_value_usd, parcel_id):
    """A DRAFT NEW_CONSTRUCTION permit asking for dry-floodproofing credit on an
    AE parcel whose community requires 1.5 ft of freeboard."""
    scenario = setup_structure(
        community_overrides=COMMUNITY_1_5_FT,
        panel_overrides=PANEL_AE_12,
        property_overrides={"parcel_id": parcel_id},
        structure_overrides={
            "structure_use": structure_use,
            "construction_year": 2001,
            "market_value_usd": market_value_usd,
            "highest_adjacent_grade_ft": 10.0,
        },
    )
    scenario["permit"] = start_permit(
        scenario["property"]["id"],
        scenario["structure"]["id"],
        scenario["owner_headers"],
        project_type="NEW_CONSTRUCTION",
        declared_project_cost_usd=250_000.00,
        proposed_lowest_floor_elevation_ft=20.0,
        floodproofing_requested=True,
    )
    return scenario


def _setup_two_closed_outreach_efforts():
    """Two DESIGNATED areas whose 2026 outreach efforts closed at 80.00 and
    100.00 percent coverage, plus a SUBMITTED A330_OUTREACH claim."""
    scenario = setup_parcel(
        community_overrides=COMMUNITY_1_5_FT,
        panel_overrides=PANEL_AE_12,
        property_overrides={
            "parcel_id": "P-0011",
            "mapped_area_code": "RLA-1",
            "owner_name": "C Owner",
            "owner_email": "c@example.com",
        },
    )
    community_id = scenario["community"]["id"]
    scenario["property_2"] = add_property(
        community_id,
        scenario["panel"]["id"],
        parcel_id="P-0012",
        mapped_area_code="RLA-2",
        owner_name="D Owner",
        owner_email="d@example.com",
    )

    area_1 = delineate_area(
        community_id, area_code="RLA-1", boundary_description="Lower Buffalo Bayou bend"
    )
    area_2 = delineate_area(
        community_id, area_code="RLA-2", boundary_description="Brays Bayou headwaters"
    )
    for area in (area_1, area_2):
        analyze_area(area["id"])
        designate_area(area["id"])

    cycle = open_cycle(
        community_id,
        cycle_year=2026,
        cycle_start_date="2026-01-01T00:00:00Z",
        cycle_end_date="2026-12-31T00:00:00Z",
        due_at="2026-09-30T00:00:00Z",
    )

    launch_outreach(area_1["id"], cycle["id"], 20)
    record_delivery(area_1["id"], 16)
    scenario["area_1"] = complete_outreach(area_1["id"])

    launch_outreach(area_2["id"], cycle["id"], 2)
    record_delivery(area_2["id"], 2)
    scenario["area_2"] = complete_outreach(area_2["id"])

    standard = draft_standard(
        community_id,
        activity_code="A330_OUTREACH",
        documentation_cycle_year=2026,
        claimed_points=50,
    )
    scenario["standard"] = submit_standard(standard["id"])
    scenario["cycle"] = cycle
    return scenario


def _setup_verified_a510_credit_and_one_major_violation():
    """A community holding a VERIFIED A510 enforcement claim (earned by a
    REMEDIATED violation) plus one OPEN MAJOR violation worth 6 points."""
    scenario = setup_parcel(
        community_overrides=COMMUNITY_1_5_FT,
        panel_overrides=PANEL_AE_12,
        property_overrides={
            "parcel_id": "P-0021",
            "owner_name": "E Owner",
            "owner_email": "e@example.com",
        },
    )
    property_id = scenario["property"]["id"]
    scenario["violation_0"] = issue_violation(
        property_id, violation_type="UNPERMITTED_FILL", severity="MINOR"
    )
    resolve_violation(
        scenario["violation_0"]["id"],
        "REMEDIATED",
        resolution_note="Fill removed and site restored",
    )

    standard = draft_standard(
        scenario["community"]["id"],
        activity_code="A510_HIGHER_STD_ENFORCEMENT",
        documentation_cycle_year=2026,
        claimed_points=60,
    )
    submit_standard(standard["id"])
    scenario["standard"] = verify_standard(standard["id"])

    scenario["violation_1"] = issue_violation(
        property_id, violation_type="NO_PERMIT", severity="MAJOR"
    )
    return scenario


# ==========================================================================
# The two substantial-improvement ratio methods
# ==========================================================================

class TestSubstantialRatioVariants:

    def test_single_event_variant_scores_the_anchor_alone(self, api):
        """PRD §3.7: "When `method` is `SINGLE_EVENT`, `computed_ratio_pct` takes the
        structure's `single_event_improvement_pct`: the classic per-permit test applied
        to the anchor event alone, ignoring earlier work inside the look-back window, so
        a ledger with several moderate jobs can come out `NOT_SUBSTANTIAL`."
        "`threshold_pct` is set to 50.00 and the `outcome` is `SUBSTANTIAL` when
        `computed_ratio_pct` is at least `threshold_pct` and `NOT_SUBSTANTIAL`
        otherwise."

        Design: Difficulty/dual_variant_calc/si_ratio_single_event_variant_yields_not_substantial
        """
        scenario = _setup_two_record_ledger_with_case("SINGLE_EVENT")

        case = validate_success(
            api.determine_case(scenario["case"]["id"], ADMIN_FPA_01), 200
        )

        assert case["method"] == "SINGLE_EVENT"
        assert float(case["computed_ratio_pct"]) == pytest.approx(22.50, abs=0.01)
        assert float(case["threshold_pct"]) == pytest.approx(50.00, abs=0.01)
        assert case["outcome"] == "NOT_SUBSTANTIAL"
        assert case["status"] == "DETERMINED"

    def test_single_event_not_substantial_leaves_the_structure_at_none(self, api):
        """PRD §3.7: "A `SUBSTANTIAL` outcome sets the structure's `substantial_status`
        to the case's `determination_type`; a `NOT_SUBSTANTIAL` outcome sets it to
        `NONE`."
        PRD §3.7: "Its `determination_type` is derived from the anchor record's
        `record_type`: an `IMPROVEMENT` anchor yields `SUBSTANTIAL_IMPROVEMENT` and a
        `DAMAGE` anchor yields `SUBSTANTIAL_DAMAGE`, and when the anchor is null the type
        is `SUBSTANTIAL_IMPROVEMENT`."
        PRD §3.6: "`cumulative_improvement_pct` is that windowed sum divided by the
        denominator, multiplied by 100, rounded half-up to two decimals;
        `single_event_improvement_pct` is the anchor's own `cost_usd` divided by the same
        denominator, multiplied by 100, rounded half-up to two decimals."

        Design: Difficulty/dual_variant_calc/si_ratio_single_event_variant_yields_not_substantial
        """
        scenario = _setup_two_record_ledger_with_case("SINGLE_EVENT")
        anchor_record = scenario["records"][1]

        case = validate_success(
            api.determine_case(scenario["case"]["id"], ADMIN_FPA_01), 200
        )

        assert case["anchor_record_id"] == anchor_record["id"]
        assert case["determination_type"] == "SUBSTANTIAL_IMPROVEMENT"

        structure = read_structure(scenario["structure"]["id"])
        assert float(structure["single_event_improvement_pct"]) == pytest.approx(
            22.50, abs=0.01
        )
        assert float(structure["cumulative_improvement_pct"]) == pytest.approx(
            52.50, abs=0.01
        )
        assert structure["substantial_status"] == "NONE"

    def test_cumulative_variant_sums_the_whole_look_back_window(self, api):
        """PRD §3.7: "When `method` is `CUMULATIVE`, `computed_ratio_pct` takes the
        structure's `cumulative_improvement_pct`: the adopted higher standard, whose
        numerator sums every counted record inside the closed window from the anchor's
        `event_date` minus the community's `cumulative_period_years` through the anchor's
        `event_date`, so the very same ledger can come out `SUBSTANTIAL`."
        "`threshold_pct` is set to 50.00 and the `outcome` is `SUBSTANTIAL` when
        `computed_ratio_pct` is at least `threshold_pct` and `NOT_SUBSTANTIAL`
        otherwise."

        Design: Difficulty/dual_variant_calc/si_ratio_cumulative_variant_yields_substantial
        """
        scenario = _setup_two_record_ledger_with_case("CUMULATIVE")

        case = validate_success(
            api.determine_case(scenario["case"]["id"], ADMIN_FPA_01), 200
        )

        assert case["method"] == "CUMULATIVE"
        assert float(case["computed_ratio_pct"]) == pytest.approx(52.50, abs=0.01)
        assert case["outcome"] == "SUBSTANTIAL"
        assert case["determination_type"] == "SUBSTANTIAL_IMPROVEMENT"

    def test_cumulative_substantial_outcome_stamps_structure_and_determiner(self, api):
        """PRD §3.7: "A `SUBSTANTIAL` outcome sets the structure's `substantial_status`
        to the case's `determination_type`; a `NOT_SUBSTANTIAL` outcome sets it to
        `NONE`."
        PRD §3.7: "Determination stamps `determined_by_user_id` with the acting
        administrator's identifier, `determined_at` with the current logical clock, and
        `appeal_deadline_at` with 30 days after `determined_at`."
        PRD §3.6: "`cumulative_counted_cost_usd` is the exact sum of `cost_usd` over the
        candidates inside that window."

        Design: Difficulty/dual_variant_calc/si_ratio_cumulative_variant_yields_substantial
        """
        scenario = _setup_two_record_ledger_with_case("CUMULATIVE")

        case = validate_success(
            api.determine_case(scenario["case"]["id"], ADMIN_FPA_01), 200
        )

        assert case["determined_by_user_id"] == "fpa-01"

        structure = read_structure(scenario["structure"]["id"])
        assert structure["substantial_status"] == "SUBSTANTIAL_IMPROVEMENT"
        assert float(structure["cumulative_counted_cost_usd"]) == pytest.approx(
            105_000.00, abs=0.01
        )
        assert float(structure["cumulative_improvement_pct"]) == pytest.approx(
            52.50, abs=0.01
        )
        assert float(structure["single_event_improvement_pct"]) == pytest.approx(
            22.50, abs=0.01
        )


# ==========================================================================
# The claimed and verified variants of the class formula
# ==========================================================================

class TestClaimedVersusVerifiedClass:

    def test_claimed_variant_freezes_an_unbounded_provisional_class(self, api):
        """PRD §3.9: "The **claimed variant**, written to `provisional_class` at
        submission and never to the community, feeds the formula with
        `crs_credit_points_claimed`, which sums `claimed_points` and is therefore
        unbounded by any activity ceiling — so the provisional class can be better than
        any class the community can actually be certified at."
        PRD §3.9: "Submission moves the cycle to `SUBMITTED`, stamps `submitted_at`,
        freezes `total_claimed_points` from the community's `crs_credit_points_claimed`
        and `prior_class` from its `crs_class`, computes `provisional_class`, and
        recomputes `verification_visit_required`."
        PRD §3.9: "The class formula subtracts, from 10, the number of whole 500-point
        blocks the points total contains, truncating any partial block downward; the
        result is then raised to 1 if it came out lower, since 1 is the best attainable
        class; and if the community's `compliance_posture` is anything other than
        `GOOD_STANDING`, the class is instead forced to 10 outright — no credit accrues
        to a community on probation or under suspension."

        Design: Difficulty/dual_variant_calc/crs_class_claimed_provisional_diverges_from_verified_final
        """
        scenario = _setup_freeboard_claim_and_visited_cycle()

        cycle = validate_success(api.certify_crs_cycle(scenario["cycle"]["id"], COORDINATOR), 200)

        assert cycle["prior_class"] == 10
        assert cycle["total_claimed_points"] == 700
        assert cycle["provisional_class"] == 9

        community = read_community(scenario["community"]["id"])
        assert community["crs_credit_points_claimed"] == 700

    def test_verified_variant_scores_the_trimmed_points_and_sets_the_class(self, api):
        """PRD §3.9: "`total_verified_points` is frozen from that recomputed figure,
        `resulting_class` is computed by the **verified variant** of the same class
        formula — fed with `crs_credit_points_verified`, which sums `verified_points`,
        each already capped at its activity ceiling, and which reflects the sweep — the
        community's `crs_class` is set to `resulting_class`, and the cycle moves to the
        terminal `CERTIFIED`."
        PRD §3.9: "For `A430_FREEBOARD` the ceiling is 100 points for each foot of
        adopted `freeboard_ft`, counting no more than 5.0 feet, with the product
        truncated downward to a whole number of points — so 2.5 feet of freeboard yields
        250 and 5.4 feet still yields 500."
        PRD §3.9: "Otherwise `verified_points` becomes the smaller of `claimed_points`
        and `max_points_allowed`, `documentation_status` becomes `VERIFIED`,
        `verified_at` is stamped, `doc_expires_at` is set to 5 calendar years after
        `verified_at`, and the community's `crs_credit_points_verified` is recomputed as
        the sum of `verified_points` over submissions whose `documentation_status` is
        `VERIFIED`."

        Design: Difficulty/dual_variant_calc/crs_class_claimed_provisional_diverges_from_verified_final
        """
        scenario = _setup_freeboard_claim_and_visited_cycle()

        cycle = validate_success(api.certify_crs_cycle(scenario["cycle"]["id"], COORDINATOR), 200)

        assert cycle["total_verified_points"] == 150
        assert cycle["resulting_class"] == 10
        assert cycle["status"] == "CERTIFIED"

        standard = read_standard(scenario["standard"]["id"])
        assert standard["max_points_allowed"] == 150
        assert standard["verified_points"] == 150

        community = read_community(scenario["community"]["id"])
        assert community["crs_credit_points_verified"] == 150
        assert community["crs_class"] == 10


# ==========================================================================
# The required lowest floor elevation
# ==========================================================================

class TestRequiredElevationFormula:

    def test_non_residential_floodproofing_credit_subtracts_one_foot(self, api):
        """PRD §3.4: "**The floodproofing credit** subtracts one foot, but only when
        `floodproofing_requested` is true *and* the structure's `structure_use` is
        `NON_RESIDENTIAL`; requesting dry-floodproofing on a `RESIDENTIAL` or `ACCESSORY`
        structure is recorded faithfully on the permit and grants nothing."
        PRD §3.4: "The base, the freeboard, and the bump are added together and the
        credit is subtracted, and that single sum is rounded half-up to one decimal
        place."
        PRD §3.4: "**The freeboard** is the larger of the permit's `freeboard_applied_ft`
        and the zone's own regulatory floor, which is 1.0 foot for zones `A`, `AE`, and
        `AO` and 2.0 feet for zone `VE`."

        Design: Difficulty/combinatorial_formula/required_elevation_non_residential_floodproofing_credit_applies
        """
        scenario = _setup_draft_permit("NON_RESIDENTIAL", 800_000.00, "P-0002")

        permit = validate_success(
            api.submit_permit(scenario["permit"]["id"], scenario["owner_headers"]), 200
        )

        assert float(permit["required_lowest_floor_elevation_ft"]) == pytest.approx(
            12.5, abs=0.01
        )
        assert float(permit["freeboard_applied_ft"]) == pytest.approx(1.5, abs=0.01)

    def test_first_submission_snapshots_zone_bfe_and_freeboard(self, api):
        """PRD §3.4: "On a first submission out of `DRAFT`, the server snapshots
        `determined_zone` and `determined_bfe_ft` from the effective panel and
        `freeboard_applied_ft` from the community's current `freeboard_ft`, then computes
        `required_lowest_floor_elevation_ft`."
        PRD §3.4: "**The base** depends on the frozen zone: for `A`, `AE`, and `VE` the
        base is `determined_bfe_ft` directly; for `AO`, where `determined_bfe_ft` holds a
        depth rather than an elevation, the base is the structure's
        `highest_adjacent_grade_ft` plus `determined_bfe_ft`."
        PRD §3.4: "A draft permit has `revision_round` 0, every determination snapshot
        null, and `version` 1."
        PRD §3.4: "The permit's `status` moves through `DRAFT`, `UNDER_REVIEW`,
        `REVISION_REQUIRED`, `APPROVED`, `ISSUED`, and one of the three terminal values
        `CLOSED_COMPLIANT`, `DENIED`, or `REVOKED`."

        Design: Difficulty/combinatorial_formula/required_elevation_non_residential_floodproofing_credit_applies
        """
        scenario = _setup_draft_permit("NON_RESIDENTIAL", 800_000.00, "P-0002")

        permit = validate_success(
            api.submit_permit(scenario["permit"]["id"], scenario["owner_headers"]), 200
        )

        assert permit["status"] == "UNDER_REVIEW"
        assert permit["determined_zone"] == "AE"
        assert float(permit["determined_bfe_ft"]) == pytest.approx(12.0, abs=0.01)
        assert float(permit["freeboard_applied_ft"]) == pytest.approx(1.5, abs=0.01)
        assert permit["revision_round"] == 0

    def test_residential_floodproofing_request_grants_no_credit(self, api):
        """PRD §3.4: "**The floodproofing credit** subtracts one foot, but only when
        `floodproofing_requested` is true *and* the structure's `structure_use` is
        `NON_RESIDENTIAL`; requesting dry-floodproofing on a `RESIDENTIAL` or `ACCESSORY`
        structure is recorded faithfully on the permit and grants nothing."
        PRD §3.4: "**The substantial-improvement bump** adds a further 0.5 feet whenever
        the structure's `substantial_status` is anything other than `NONE`, and adds
        nothing when it is `NONE`."

        Design: Difficulty/combinatorial_formula/required_elevation_residential_floodproofing_request_grants_no_credit
        """
        scenario = _setup_draft_permit("RESIDENTIAL", 300_000.00, "P-0003")

        permit = validate_success(
            api.submit_permit(scenario["permit"]["id"], scenario["owner_headers"]), 200
        )

        assert float(permit["required_lowest_floor_elevation_ft"]) == pytest.approx(
            13.5, abs=0.01
        )

    def test_residential_request_is_recorded_faithfully_on_the_permit(self, api):
        """PRD §3.4: "**The floodproofing credit** subtracts one foot, but only when
        `floodproofing_requested` is true *and* the structure's `structure_use` is
        `NON_RESIDENTIAL`; requesting dry-floodproofing on a `RESIDENTIAL` or `ACCESSORY`
        structure is recorded faithfully on the permit and grants nothing."
        PRD §3.4: "Only `freeboard_applied_ft` is ever read here — a later change to the
        community's `freeboard_ft` never reaches a permit that has already been
        submitted."

        Design: Difficulty/combinatorial_formula/required_elevation_residential_floodproofing_request_grants_no_credit
        """
        scenario = _setup_draft_permit("RESIDENTIAL", 300_000.00, "P-0003")

        permit = validate_success(
            api.submit_permit(scenario["permit"]["id"], scenario["owner_headers"]), 200
        )

        assert permit["floodproofing_requested"] is True
        assert float(permit["freeboard_applied_ft"]) == pytest.approx(1.5, abs=0.01)
        assert permit["status"] == "UNDER_REVIEW"


# ==========================================================================
# The outreach score: mean of already-rounded coverages
# ==========================================================================

class TestOutreachScoreAggregation:

    def test_outreach_ceiling_is_the_mean_of_rounded_coverages(self, api):
        """PRD §3.9: "The score is 0.00 when that set is empty, and otherwise it is the
        arithmetic mean of the members' **already-rounded** `coverage_pct` values,
        rounded half-up to two decimal places a second time."
        PRD §3.9: "Pooling the raw numerators and denominators — summing every
        `delivered_count` and dividing by the sum of every `target_property_count` — is
        forbidden and yields a different, wrong score."
        PRD §3.9: "The outreach credit tier then reads off that score: a score of at
        least 90.00 earns 50 points, a score of at least 75.00 but below 90.00 earns 25
        points, and a lower score earns 0."
        PRD §3.9: "For `A330_OUTREACH` the ceiling is the outreach credit tier described
        above, evaluated for the submission's own `documentation_cycle_year`."

        Design: Difficulty/combinatorial_formula/outreach_score_is_mean_of_rounded_area_coverages_not_pooled_ratio
        """
        scenario = _setup_two_closed_outreach_efforts()

        standard = validate_success(
            api.verify_higher_standard(
                scenario["standard"]["id"], {"decision": "VERIFY"}, COORDINATOR
            ),
            200,
        )

        assert standard["max_points_allowed"] == 50
        assert standard["verified_points"] == 50
        assert standard["documentation_status"] == "VERIFIED"

        community = read_community(scenario["community"]["id"])
        assert community["crs_credit_points_verified"] == 50

    def test_each_area_coverage_is_rounded_before_the_tier_is_read(self, api):
        """PRD §3.9: "`coverage_pct` is then recomputed as 0.00 when
        `target_property_count` is 0, and otherwise as `delivered_count` divided by
        `target_property_count`, multiplied by 100, rounded half-up to two decimal
        places."
        PRD §3.9: "Closing the effort is also admitted only from `IN_PROGRESS`, and the
        coverage tier decides the branch: a `coverage_pct` of at least 75.00 moves
        `outreach_status` to `COMPLETED`, and a `coverage_pct` below 75.00 moves it to
        `INSUFFICIENT`."

        Design: Difficulty/combinatorial_formula/outreach_score_is_mean_of_rounded_area_coverages_not_pooled_ratio
        """
        scenario = _setup_two_closed_outreach_efforts()

        validate_success(
            api.verify_higher_standard(
                scenario["standard"]["id"], {"decision": "VERIFY"}, COORDINATOR
            ),
            200,
        )

        area_1 = read_area(scenario["area_1"]["id"])
        assert float(area_1["coverage_pct"]) == pytest.approx(80.00, abs=0.01)
        assert area_1["outreach_status"] == "COMPLETED"

        area_2 = read_area(scenario["area_2"]["id"])
        assert float(area_2["coverage_pct"]) == pytest.approx(100.00, abs=0.01)
        assert area_2["outreach_status"] == "COMPLETED"


# ==========================================================================
# Sanction risk: the probation credit is read off the provisional tier
# ==========================================================================

class TestSanctionProbationCredit:

    def test_probation_credit_nets_twelve_raw_points_down_to_eight(self, api):
        """PRD §3.8: "**Step one** produces the raw score: the severity weights of every
        violation belonging to any property of the community whose `status` is `OPEN`,
        `ORDER_ISSUED`, or `ESCALATED` — 2 points for `MINOR`, 6 for `MAJOR`, 12 for
        `CRITICAL` — plus 5 points for each `DEFAULTED` remediation order whose violation
        is still `ESCALATED` and whose violation belongs to a property of the community."
        PRD §3.8: "**Step three** grants a credit of 4 points, and grants it only when
        that provisional tier is exactly `ON_PROBATION` *and* the community holds a
        higher-standards submission for the enforcement activity
        `A510_HIGHER_STD_ENFORCEMENT` whose `documentation_status` is `VERIFIED`; in every
        other case the credit is 0."
        PRD §3.8: "**Step four** sets `sanction_risk_points` to the raw score minus the
        credit, floored at 0, and sets `compliance_posture` to the tier of that final
        value — the provisional tier of step two is discarded and is never the answer."
        PRD §3.8: "The tier rule is inclusive on the worse side: a score of 25 points or
        more is `SUSPENDED`, a score of 10 points or more is `ON_PROBATION`, and anything
        lower is `GOOD_STANDING`."
        PRD §3.1: "A computed compliance summary is available to the
        `StateNfipCoordinator` and the `FloodplainAdministrator` and reports the
        community's enforcement and rating posture in one payload: `community_id`, the
        current `sanction_risk_points` and `compliance_posture`, the
        `counted_violation_count` of violations currently inside the counted set, the
        `defaulted_order_count` of defaulted orders currently carrying a penalty, the
        `a510_credit_applied` value actually subtracted by the probation credit rule, and
        the rating figures `crs_class`, `crs_credit_points_claimed`,
        `crs_credit_points_verified`, `freeboard_ft`, and `cumulative_period_years`."

        Design: Difficulty/combinatorial_formula/sanction_probation_credit_applied_once_from_provisional_tier
        """
        scenario = _setup_verified_a510_credit_and_one_major_violation()

        validate_success(
            api.create_violation(
                {
                    "property_id": scenario["property"]["id"],
                    "violation_type": "UNPERMITTED_FILL",
                    "severity": "MAJOR",
                },
                ADMINISTRATOR,
            ),
            201,
        )

        community = read_community(scenario["community"]["id"])
        assert community["sanction_risk_points"] == 8
        assert community["compliance_posture"] == "GOOD_STANDING"

        summary = read_compliance_summary(scenario["community"]["id"])
        assert summary["a510_credit_applied"] == 4

    def test_credit_leaves_the_per_violation_weights_untouched(self, api):
        """PRD §3.8: "A new violation opens with `status` `OPEN`, `opened_at` stamped
        from the logical clock, `sanction_points_contributed` set to its severity weight,
        and `version` 1."
        PRD §3.8: "`REMEDIATED` moves the violation to the terminal `REMEDIATED`, stamps
        `resolved_at`, drops `sanction_points_contributed` to 0, moves every remediation
        order of that violation whose `status` is `ISSUED` or `EXTENDED` to `SATISFIED`
        in ascending `created_at` order, recomputes the community's
        `sanction_risk_points` and `compliance_posture`, and — when the `violation_type`
        was `ELEVATION_DEFICIENT`, a `structure_id` was named, and that structure carries
        no other violation in `OPEN`, `ORDER_ISSUED`, or `ESCALATED` — restores the
        structure's `compliance_status` to `COMPLIANT` if its `lowest_floor_elevation_ft`
        is not null and to `PENDING_CERTIFICATE` if it is null."
        PRD §3.9: "For `A510_HIGHER_STD_ENFORCEMENT` the ceiling is 60 points when at
        least one violation belonging to any property of the community has reached
        `REMEDIATED`, and 0 otherwise."

        Design: Difficulty/combinatorial_formula/sanction_probation_credit_applied_once_from_provisional_tier
        """
        scenario = _setup_verified_a510_credit_and_one_major_violation()

        violation_2 = validate_success(
            api.create_violation(
                {
                    "property_id": scenario["property"]["id"],
                    "violation_type": "UNPERMITTED_FILL",
                    "severity": "MAJOR",
                },
                ADMINISTRATOR,
            ),
            201,
        )

        assert violation_2["sanction_points_contributed"] == 6

        violation_0 = validate_success(
            api.get_violation(scenario["violation_0"]["id"], ADMINISTRATOR), 200
        )
        assert violation_0["sanction_points_contributed"] == 0

        violation_1 = validate_success(
            api.get_violation(scenario["violation_1"]["id"], ADMINISTRATOR), 200
        )
        assert violation_1["sanction_points_contributed"] == 6

        standard = read_standard(scenario["standard"]["id"])
        assert standard["documentation_status"] == "VERIFIED"
        assert standard["verified_points"] == 60
