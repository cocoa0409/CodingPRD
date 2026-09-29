"""Boundary precision: the exact inclusive edges, and the value one step outside.

Each boundary is pinned from both sides so that an implementation using a strict
comparison, or one rounding the wrong way, cannot pass.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_calendar_years_after,
    draft_standard,
    file_certificate,
    improvement_record_payload,
    open_cycle,
    record_visit,
    register_community,
    setup_issued_permit,
    setup_ledger,
    setup_structure,
    submit_cycle,
    submit_standard,
    validate_error,
    validate_paginated,
    validate_success,
    verify_standard,
)

ADMIN = TEST_USERS["administrator_headers"]
COORD = TEST_USERS["coordinator_headers"]


# ==========================================================================
# Scenario builders
# ==========================================================================

def _ledger_anchored_in_march_2026() -> dict:
    """A structure worth 200000.00 in a community with a 10-year cumulative period,
    holding 30000.00 dated exactly on the window's lower bound and a 45000.00
    anchor dated 2026-03-01."""
    return setup_ledger(
        [
            {
                "record_type": "IMPROVEMENT",
                "event_date": "2016-03-01T00:00:00Z",
                "cost_usd": 30_000.00,
            },
            {
                "record_type": "IMPROVEMENT",
                "event_date": "2026-03-01T00:00:00Z",
                "cost_usd": 45_000.00,
            },
        ],
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={
            "structure_use": "RESIDENTIAL",
            "pre_firm": True,
            "construction_year": 1955,
            "market_value_usd": 200_000.00,
            "highest_adjacent_grade_ft": 10.0,
        },
    )


def _accessory_structure_worth_two_thousand() -> dict:
    """An ACCESSORY structure worth 2000.00 with an empty ledger, so that a
    five-hundred-dollar job is exactly one quarter of its value."""
    return setup_structure(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={
            "structure_use": "ACCESSORY",
            "pre_firm": True,
            "construction_year": 1970,
            "market_value_usd": 2_000.00,
            "highest_adjacent_grade_ft": 10.0,
        },
    )


def _cycle_ready_to_certify(claimed_points: int) -> dict:
    """A community with 5.0 feet of adopted freeboard whose single A430_FREEBOARD
    package claims `claimed_points`, verified, with a SUBMITTED 2026 cycle taken to
    the point where certification is admissible."""
    community = register_community(freeboard_ft=5.0, cumulative_period_years=10)
    standard = draft_standard(
        community["id"],
        activity_code="A430_FREEBOARD",
        documentation_cycle_year=2026,
        claimed_points=claimed_points,
    )
    standard = submit_standard(standard["id"])
    cycle = open_cycle(
        community["id"],
        cycle_year=2026,
        cycle_start_date="2026-01-01T00:00:00Z",
        cycle_end_date="2026-12-31T00:00:00Z",
        due_at="2026-09-30T00:00:00Z",
    )
    cycle = submit_cycle(cycle["id"])
    standard = verify_standard(standard["id"])
    if cycle["verification_visit_required"]:
        cycle = record_visit(cycle["id"], visit_note="State verification visit complete")
    return {"community": community, "standard": standard, "cycle": cycle}


def _ngvd29_certificate(measured_lowest_floor_ft: float) -> dict:
    """An ISSUED permit requiring 13.5 ft, with a FINISHED_CONSTRUCTION certificate
    surveyed in NGVD29 filed against it."""
    scenario = setup_issued_permit(
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 200_000.00,
            "proposed_lowest_floor_elevation_ft": 13.5,
        },
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={
            "structure_use": "RESIDENTIAL",
            "pre_firm": False,
            "construction_year": 2025,
            "market_value_usd": 310_000.00,
            "highest_adjacent_grade_ft": 10.0,
        },
    )
    scenario["certificate"] = file_certificate(
        scenario["permit"]["id"],
        scenario["structure"]["id"],
        scenario["owner_headers"],
        certificate_type="FINISHED_CONSTRUCTION",
        datum="NGVD29",
        measured_lowest_floor_ft=measured_lowest_floor_ft,
        measured_bfe_ft=12.85,
        surveyor_license_no="TX-RPLS-9002",
    )
    return scenario


# ==========================================================================
# The cumulative window's lower bound
# ==========================================================================

class TestCumulativeWindowLowerBound:

    def test_the_window_reported_by_the_summary_starts_on_the_inclusive_day(self, api):
        """PRD §3.6: "The **cumulative window** is closed on both ends: it starts at the
        anchor's `event_date` minus the community's `cumulative_period_years` counted in
        whole calendar years (with 29 February clamped to 28 February) and ends at the
        anchor's `event_date` itself, so a record dated exactly on either endpoint is
        inside the window."  And the anchor it hangs from: "Otherwise the **anchor** is
        chosen as the candidate with the latest `event_date`, breaking ties by the latest
        `created_at` — `created_at` is the only sanctioned tiebreaker and `id` is never
        used for ordering — and its identifier is written to the structure's
        `anchor_record_id`."  §3.3: "A computed improvement summary is available for any
        structure and reports `structure_id`, the current `anchor_record_id`, the
        `window_start_date` and `window_end_date` of the closed anchored cumulative
        window — both null when no counted record exists — the `counted_record_count` of
        counted, non-reversed records lying inside that window, and the three aggregates
        `cumulative_counted_cost_usd`, `cumulative_improvement_pct`, and
        `single_event_improvement_pct`."

        Design: Difficulty/boundary_precision_check/cumulative_window_lower_bound_is_inclusive_to_the_day
        """
        scenario = _ledger_anchored_in_march_2026()
        structure_id = scenario["structure"]["id"]
        anchor = scenario["records"][1]

        validate_success(
            api.append_improvement_record(
                improvement_record_payload(
                    structure_id,
                    record_type="IMPROVEMENT",
                    event_date="2016-02-28T00:00:00Z",
                    cost_usd=30_000.00,
                ),
                ADMIN,
            ),
            201,
        )

        summary = validate_success(api.get_improvement_summary(structure_id, ADMIN))
        assert summary["structure_id"] == structure_id
        assert summary["anchor_record_id"] == anchor["id"]
        assert summary["window_start_date"].startswith("2016-03-01")
        assert summary["window_end_date"].startswith("2026-03-01")
        assert summary["counted_record_count"] == 2

    def test_a_record_one_day_before_the_bound_is_counted_but_outside_the_window(self, api):
        """PRD §3.6: "`cumulative_counted_cost_usd` is the exact sum of `cost_usd` over
        the candidates inside that window."  And: "`cumulative_improvement_pct` is that
        windowed sum divided by the denominator, multiplied by 100, rounded half-up to
        two decimals; `single_event_improvement_pct` is the anchor's own `cost_usd`
        divided by the same denominator, multiplied by 100, rounded half-up to two
        decimals."  The row's own flag is independent of the window: "Whether a row
        counts toward cumulative tracking is recorded on the row itself as
        `counted_in_cumulative`, and the rule is a conjunction of three conditions: the
        `record_type` must be `IMPROVEMENT` or `DAMAGE`, `is_code_compliance_only` must
        be false, and `cost_usd` must be at least 500.00."  And the case rule that stays
        silent below the threshold: "When the freshly computed
        `cumulative_improvement_pct` reaches 50 percent or more and no
        `DeterminationCase` of that structure is currently `OPEN`, `DETERMINED`, or
        `APPEALED`, the server opens a case with `method` `CUMULATIVE` on its own
        initiative."

        Design: Difficulty/boundary_precision_check/cumulative_window_lower_bound_is_inclusive_to_the_day
        """
        scenario = _ledger_anchored_in_march_2026()
        structure_id = scenario["structure"]["id"]

        outside = validate_success(
            api.append_improvement_record(
                improvement_record_payload(
                    structure_id,
                    record_type="IMPROVEMENT",
                    event_date="2016-02-28T00:00:00Z",
                    cost_usd=30_000.00,
                ),
                ADMIN,
            ),
            201,
        )
        assert outside["counted_in_cumulative"] is True

        structure = validate_success(api.get_structure(structure_id, ADMIN))
        assert structure["anchor_record_id"] == scenario["records"][1]["id"]
        assert float(structure["cumulative_counted_cost_usd"]) == pytest.approx(
            75_000.00, abs=0.01
        )
        assert float(structure["cumulative_improvement_pct"]) == pytest.approx(37.50, abs=0.01)
        assert float(structure["single_event_improvement_pct"]) == pytest.approx(22.50, abs=0.01)
        assert structure["substantial_status"] == "NONE"

        _cases, meta = validate_paginated(
            api.list_determination_cases(ADMIN, {"structure_id": structure_id})
        )
        assert meta["total_count"] == 0


# ==========================================================================
# The counted-cost threshold
# ==========================================================================

class TestCountedCostThreshold:

    def test_a_job_of_exactly_five_hundred_dollars_counts(self, api):
        """PRD §3.6: "Whether a row counts toward cumulative tracking is recorded on the
        row itself as `counted_in_cumulative`, and the rule is a conjunction of three
        conditions: the `record_type` must be `IMPROVEMENT` or `DAMAGE`,
        `is_code_compliance_only` must be false, and `cost_usd` must be at least
        500.00."  And the aggregates it then feeds: "The candidate set is every record of
        the structure whose `counted_in_cumulative` is true and whose `reversed` is
        false."  And: "The shared denominator for both ratios is the anchor's
        `market_value_at_event_usd`."

        Design: Difficulty/boundary_precision_check/counted_cost_threshold_includes_exactly_five_hundred_excludes_499_99
        """
        scenario = _accessory_structure_worth_two_thousand()
        structure_id = scenario["structure"]["id"]

        record = validate_success(
            api.append_improvement_record(
                improvement_record_payload(
                    structure_id,
                    record_type="IMPROVEMENT",
                    event_date="2026-05-01T00:00:00Z",
                    cost_usd=500.00,
                ),
                ADMIN,
            ),
            201,
        )
        assert record["counted_in_cumulative"] is True
        assert float(record["market_value_at_event_usd"]) == pytest.approx(2_000.00, abs=0.01)

        structure = validate_success(api.get_structure(structure_id, ADMIN))
        assert structure["anchor_record_id"] == record["id"]
        assert float(structure["cumulative_counted_cost_usd"]) == pytest.approx(500.00, abs=0.01)
        assert float(structure["cumulative_improvement_pct"]) == pytest.approx(25.00, abs=0.01)
        assert float(structure["single_event_improvement_pct"]) == pytest.approx(25.00, abs=0.01)

    def test_a_job_one_cent_below_the_threshold_is_excluded_from_the_aggregates(self, api):
        """PRD §3.6: "Reversals, code-compliance-only work, and small jobs below five
        hundred dollars are therefore excluded from the aggregates by construction."  The
        conjunction that excludes it: "Whether a row counts toward cumulative tracking is
        recorded on the row itself as `counted_in_cumulative`, and the rule is a
        conjunction of three conditions: the `record_type` must be `IMPROVEMENT` or
        `DAMAGE`, `is_code_compliance_only` must be false, and `cost_usd` must be at
        least 500.00."  And the anchor, which only candidates may claim: "Otherwise the
        **anchor** is chosen as the candidate with the latest `event_date`, breaking ties
        by the latest `created_at` — `created_at` is the only sanctioned tiebreaker and
        `id` is never used for ordering — and its identifier is written to the
        structure's `anchor_record_id`."

        Design: Difficulty/boundary_precision_check/counted_cost_threshold_includes_exactly_five_hundred_excludes_499_99
        """
        scenario = setup_ledger(
            [
                {
                    "record_type": "IMPROVEMENT",
                    "event_date": "2026-05-01T00:00:00Z",
                    "cost_usd": 500.00,
                }
            ],
            community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
            structure_overrides={
                "structure_use": "ACCESSORY",
                "pre_firm": True,
                "construction_year": 1970,
                "market_value_usd": 2_000.00,
                "highest_adjacent_grade_ft": 10.0,
            },
        )
        structure_id = scenario["structure"]["id"]
        counted_record = scenario["records"][0]

        uncounted = validate_success(
            api.append_improvement_record(
                improvement_record_payload(
                    structure_id,
                    record_type="IMPROVEMENT",
                    event_date="2026-06-01T00:00:00Z",
                    cost_usd=499.99,
                ),
                ADMIN,
            ),
            201,
        )
        assert uncounted["counted_in_cumulative"] is False

        structure = validate_success(api.get_structure(structure_id, ADMIN))
        assert structure["anchor_record_id"] == counted_record["id"]
        assert float(structure["cumulative_counted_cost_usd"]) == pytest.approx(500.00, abs=0.01)
        assert float(structure["cumulative_improvement_pct"]) == pytest.approx(25.00, abs=0.01)
        assert float(structure["single_event_improvement_pct"]) == pytest.approx(25.00, abs=0.01)


# ==========================================================================
# The CRS class block boundary
# ==========================================================================

class TestCrsClassBlockBoundary:

    def test_five_feet_of_freeboard_caps_the_claim_at_five_hundred_points(self, api):
        """PRD §3.9: "For `A430_FREEBOARD` the ceiling is 100 points for each foot of
        adopted `freeboard_ft`, counting no more than 5.0 feet, with the product
        truncated downward to a whole number of points — so 2.5 feet of freeboard yields
        250 and 5.4 feet still yields 500."  And: "Otherwise `verified_points` becomes
        the smaller of `claimed_points` and `max_points_allowed`, `documentation_status`
        becomes `VERIFIED`, `verified_at` is stamped, `doc_expires_at` is set to 5
        calendar years after `verified_at`, and the community's
        `crs_credit_points_verified` is recomputed as the sum of `verified_points` over
        submissions whose `documentation_status` is `VERIFIED`."  §3.10: "Submission moves
        the cycle to `SUBMITTED`, stamps `submitted_at`, freezes `total_claimed_points`
        from the community's `crs_credit_points_claimed` and `prior_class` from its
        `crs_class`, computes `provisional_class`, and recomputes
        `verification_visit_required`."  And: "The class formula subtracts, from 10, the
        number of whole 500-point blocks the points total contains, truncating any
        partial block downward; the result is then raised to 1 if it came out lower, since
        1 is the best attainable class; and if the community's `compliance_posture` is
        anything other than `GOOD_STANDING`, the class is instead forced to 10 outright —
        no credit accrues to a community on probation or under suspension."  And the
        boundary: "The boundary is inclusive on the block: exactly 500 points is class
        9."

        Design: Difficulty/boundary_precision_check/crs_class_boundary_exactly_five_hundred_points_yields_class_nine
        """
        scenario = _cycle_ready_to_certify(claimed_points=500)

        standard = validate_success(api.get_higher_standard(scenario["standard"]["id"], COORD))
        assert standard["documentation_status"] == "VERIFIED"
        assert standard["max_points_allowed"] == 500
        assert standard["verified_points"] == 500

        community = validate_success(api.get_community(scenario["community"]["id"], COORD))
        assert community["crs_credit_points_verified"] == 500

        cycle = validate_success(api.get_crs_cycle(scenario["cycle"]["id"], COORD))
        assert cycle["total_claimed_points"] == 500
        assert cycle["prior_class"] == 10
        assert cycle["provisional_class"] == 9

    def test_certifying_on_exactly_five_hundred_verified_points_sets_class_nine(self, api):
        """PRD §3.10: "The class formula subtracts, from 10, the number of whole
        500-point blocks the points total contains, truncating any partial block
        downward; the result is then raised to 1 if it came out lower, since 1 is the
        best attainable class; and if the community's `compliance_posture` is anything
        other than `GOOD_STANDING`, the class is instead forced to 10 outright — no
        credit accrues to a community on probation or under suspension."  And: "The
        boundary is inclusive on the block: exactly 500 points is class 9."  And:
        "`total_verified_points` is frozen from that recomputed figure, `resulting_class`
        is computed by the **verified variant** of the same class formula — fed with
        `crs_credit_points_verified`, which sums `verified_points`, each already capped
        at its activity ceiling, and which reflects the sweep — the community's
        `crs_class` is set to `resulting_class`, and the cycle moves to the terminal
        `CERTIFIED`."

        Design: Difficulty/boundary_precision_check/crs_class_boundary_exactly_five_hundred_points_yields_class_nine
        """
        scenario = _cycle_ready_to_certify(claimed_points=500)

        cycle = validate_success(api.certify_crs_cycle(scenario["cycle"]["id"], COORD))
        assert cycle["status"] == "CERTIFIED"
        assert cycle["total_verified_points"] == 500
        assert cycle["resulting_class"] == 9

        community = validate_success(api.get_community(scenario["community"]["id"], COORD))
        assert community["crs_class"] == 9

    def test_one_point_short_of_the_block_stays_at_class_ten(self, api):
        """PRD §3.10: "The class formula subtracts, from 10, the number of whole
        500-point blocks the points total contains, truncating any partial block
        downward; the result is then raised to 1 if it came out lower, since 1 is the
        best attainable class; and if the community's `compliance_posture` is anything
        other than `GOOD_STANDING`, the class is instead forced to 10 outright — no
        credit accrues to a community on probation or under suspension."  And: "The
        boundary is inclusive on the block: exactly 500 points is class 9."  And:
        "`total_verified_points` is frozen from that recomputed figure, `resulting_class`
        is computed by the **verified variant** of the same class formula — fed with
        `crs_credit_points_verified`, which sums `verified_points`, each already capped
        at its activity ceiling, and which reflects the sweep — the community's
        `crs_class` is set to `resulting_class`, and the cycle moves to the terminal
        `CERTIFIED`."

        Design: Difficulty/boundary_precision_check/crs_class_boundary_exactly_five_hundred_points_yields_class_nine
        """
        scenario = _cycle_ready_to_certify(claimed_points=499)

        standard = validate_success(api.get_higher_standard(scenario["standard"]["id"], COORD))
        assert standard["verified_points"] == 499

        cycle = validate_success(api.certify_crs_cycle(scenario["cycle"]["id"], COORD))
        assert cycle["status"] == "CERTIFIED"
        assert cycle["total_verified_points"] == 499
        assert cycle["resulting_class"] == 10

        community = validate_success(api.get_community(scenario["community"]["id"], COORD))
        assert community["crs_class"] == 10


# ==========================================================================
# Datum conversion at exactly zero margin
# ==========================================================================

class TestDatumConversionAtZeroMargin:

    def test_ngvd29_survey_normalizing_onto_the_requirement_is_accepted(self, api):
        """PRD §3.5: "The datum offset is added to `measured_lowest_floor_ft` first —
        the offset is 0.0 feet for `NAVD88` and negative 0.85 feet for `NGVD29` — and
        that sum is rounded half-up to one decimal place to yield
        `normalized_lowest_floor_ft`."  And: "The permit's current
        `required_lowest_floor_elevation_ft` is then subtracted from that already-rounded
        normalized value, and the difference is rounded half-up to one decimal place
        again to yield `freeboard_margin_ft`."  And: "Acceptance additionally requires
        that the certificate's `structure_id` still equals its permit's `structure_id`
        and that `freeboard_margin_ft` be at least 0.0 feet; a negative margin is
        rejected with `ERR_ELEVATION_BELOW_REQUIRED`."  §2.6 confirms the inclusive
        edge: "All threshold comparisons in this domain are inclusive on the passing side
        unless stated otherwise: a ratio that lands exactly on 50 percent is substantial,
        a coverage figure that lands exactly on 75 percent earns partial credit, and a
        freeboard margin of exactly 0.0 feet is acceptable."  And: "An accepted
        certificate moves to `ACCEPTED`, stamps `accepted_at` with the current logical
        clock, and sets `retention_review_due_at` to 5 calendar years after
        `accepted_at`, which is the date the record-retention audit for CRS Activity 310
        becomes due."

        Design: Difficulty/boundary_precision_check/datum_conversion_accepts_certificate_at_exactly_zero_margin
        """
        scenario = _ngvd29_certificate(14.35)
        certificate_id = scenario["certificate"]["id"]
        assert float(scenario["certificate"]["normalized_lowest_floor_ft"]) == pytest.approx(
            13.5, abs=0.01
        )
        assert float(scenario["certificate"]["freeboard_margin_ft"]) == pytest.approx(
            0.0, abs=0.01
        )

        certificate = validate_success(
            api.review_certificate(certificate_id, {"decision": "ACCEPT"}, ADMIN)
        )
        assert certificate["status"] == "ACCEPTED"
        assert float(certificate["normalized_lowest_floor_ft"]) == pytest.approx(13.5, abs=0.01)
        assert float(certificate["freeboard_margin_ft"]) == pytest.approx(0.0, abs=0.01)
        assert_calendar_years_after(
            certificate["retention_review_due_at"], certificate["accepted_at"], 5,
            "retention_review_due_at",
        )

    def test_acceptance_at_zero_margin_makes_the_structure_compliant(self, api):
        """PRD §3.5: "And when the accepted certificate's `certificate_type` is
        `FINISHED_CONSTRUCTION`, the structure's `lowest_floor_elevation_ft` is set to
        the certificate's `normalized_lowest_floor_ft` and the structure's
        `compliance_status` becomes `COMPLIANT` — unless the structure carries a
        violation whose `status` is `OPEN`, `ORDER_ISSUED`, or `ESCALATED`, in which case
        the elevation is recorded but the compliance status is left where enforcement put
        it."  The requirement the survey had to reach follows §3.4: "The base, the
        freeboard, and the bump are added together and the credit is subtracted, and that
        single sum is rounded half-up to one decimal place."

        Design: Difficulty/boundary_precision_check/datum_conversion_accepts_certificate_at_exactly_zero_margin
        """
        scenario = _ngvd29_certificate(14.35)

        validate_success(
            api.review_certificate(
                scenario["certificate"]["id"], {"decision": "ACCEPT"}, ADMIN
            )
        )

        permit = validate_success(api.get_permit(scenario["permit"]["id"], ADMIN))
        assert float(permit["required_lowest_floor_elevation_ft"]) == pytest.approx(
            13.5, abs=0.01
        )
        structure = validate_success(api.get_structure(scenario["structure"]["id"], ADMIN))
        assert float(structure["lowest_floor_elevation_ft"]) == pytest.approx(13.5, abs=0.01)
        assert structure["compliance_status"] == "COMPLIANT"

    def test_a_tenth_of_a_foot_below_the_requirement_is_refused(self, api):
        """PRD §3.5: "Acceptance additionally requires that the certificate's
        `structure_id` still equals its permit's `structure_id` and that
        `freeboard_margin_ft` be at least 0.0 feet; a negative margin is rejected with
        `ERR_ELEVATION_BELOW_REQUIRED`."  The normalization that produces that margin:
        "The datum offset is added to `measured_lowest_floor_ft` first — the offset is
        0.0 feet for `NAVD88` and negative 0.85 feet for `NGVD29` — and that sum is
        rounded half-up to one decimal place to yield `normalized_lowest_floor_ft`."
        And: "The permit's current `required_lowest_floor_elevation_ft` is then
        subtracted from that already-rounded normalized value, and the difference is
        rounded half-up to one decimal place again to yield `freeboard_margin_ft`."

        Design: Difficulty/boundary_precision_check/datum_conversion_accepts_certificate_at_exactly_zero_margin
        """
        scenario = _ngvd29_certificate(14.29)
        certificate_id = scenario["certificate"]["id"]
        assert float(scenario["certificate"]["normalized_lowest_floor_ft"]) == pytest.approx(
            13.4, abs=0.01
        )
        assert float(scenario["certificate"]["freeboard_margin_ft"]) == pytest.approx(
            -0.1, abs=0.01
        )

        validate_error(
            api.review_certificate(certificate_id, {"decision": "ACCEPT"}, ADMIN),
            ApiErrorId.ERR_ELEVATION_BELOW_REQUIRED,
        )

        certificate = validate_success(api.get_certificate(certificate_id, ADMIN))
        assert certificate["status"] == "SUBMITTED"
        structure = validate_success(api.get_structure(scenario["structure"]["id"], ADMIN))
        assert structure["lowest_floor_elevation_ft"] is None
