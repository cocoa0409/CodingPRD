"""Gap analyses and the residual gap score."""
from test_helpers import (
    ApiErrorId,
    accept_assessment,
    create_approved_mapping,
    create_assessment,
    create_business_owner,
    create_control,
    create_mapping,
    create_obligation,
    create_triaged_change,
    confirm_gap,
    get_gap,
    list_gaps_for_assessment,
    make_officer_headers,
    setup_accepted_assessment,
    setup_confirmed_gap,
    start_assessment,
    submit_assessment,
    validate_error,
    validate_success,
    OFFICER_A,
    OFFICER_B,
    api_client,
)


class TestEffectivenessBoundary:
    def test_ninety_vs_ninety_one_day_review(self, api, officer_a_headers, officer_b_headers):
        """PRD §3.3: "`effectiveness_factor`, which measures review staleness
        against the current logical clock — 1.0 when the last review was at most
        90 days ago, 0.8 when it was between 91 and 180 days ago, and 0.5 when it
        was more than 180 days ago or never happened, the latter being the default
        before any review."
        PRD §3.5: "Against that requirement the system maintains `covered_points`:
        the sum over the obligation's `APPROVED` mappings of each mapping's
        `coverage_weight` multiplied by its control's `effectiveness_factor` as
        evaluated at the current logical clock."

        Design: Corner/calculations/calc_effectiveness_boundary_90_vs_91_days
        """
        pipe = setup_accepted_assessment(citation="CB-1", criticality="CRITICAL")
        obl = pipe["obligation"]
        gap = pipe["gaps"][0]
        # Default clock 2026-08-01: 2026-05-03 is exactly 90 days before; 2026-05-02 is 91.
        ctl90 = validate_success(
            api.create_control(
                {
                    "control_code": "CTL-CB-90",
                    "title": "Reviewed exactly 90d ago",
                    "owner_department": "COMP",
                    "review_frequency_days": 90,
                    "last_reviewed_at": "2026-05-03T00:00:00Z",
                },
                officer_a_headers,
            ),
            201,
        )
        ctl91 = validate_success(
            api.create_control(
                {
                    "control_code": "CTL-CB-91",
                    "title": "Reviewed 91d ago",
                    "owner_department": "COMP",
                    "review_frequency_days": 90,
                    "last_reviewed_at": "2026-05-02T00:00:00Z",
                },
                officer_a_headers,
            ),
            201,
        )
        assert ctl90["effectiveness_factor"] == 1.0, "90 days is inclusive of the fresh tier"
        assert ctl91["effectiveness_factor"] == 0.8, "91 days falls in the 91-180 band"

        create_approved_mapping(obl["id"], ctl90["id"], coverage_weight=4)
        create_approved_mapping(obl["id"], ctl91["id"], coverage_weight=5)
        gap = get_gap(gap["id"])
        assert gap["covered_points"] == 8.0, "4 x 1.0 + 5 x 0.8 = 8.0"
        assert gap["residual_gap_points"] == 24.0, "32 - 8.0 = 24.0"


class TestCoverageInputSet:
    def test_proposed_mapping_contributes_nothing(self, api, officer_a_headers, officer_b_headers):
        """PRD §3.5: "Mappings in `PROPOSED`, `REJECTED`, or `RETIRED` contribute
        nothing."
        PRD §3.3: "Both approval and retirement immediately recompute
        `covered_points` and `residual_gap_points` on every gap analysis of the
        mapped obligation that is still in `OPEN` or `IN_REVIEW`."

        Design: Corner/calculations/calc_proposed_mapping_excluded_from_coverage
        """
        pipe = setup_accepted_assessment(citation="CB-2", criticality="CRITICAL")
        gap = pipe["gaps"][0]
        assert gap["covered_points"] == 0.0
        ctl = create_control(control_code="CTL-CB-2")
        mapping = create_mapping(pipe["obligation"]["id"], ctl["id"], coverage_weight=4)
        mid = get_gap(gap["id"])
        assert mid["covered_points"] == 0.0, "PROPOSED mapping is outside the input set"

        approve = api.approve_mapping(mapping["id"], officer_b_headers)
        assert approve.status_code == 200, f"Setup failed: {approve.text}"
        after = get_gap(gap["id"])
        assert after["covered_points"] == 2.0, "4 x 0.5 (never reviewed) = 2.0"
        assert after["residual_gap_points"] == 30.0, "32 - 2.0 = 30.0"


class TestCompensatingCoverage:
    def test_approve_moves_coverage(self, api):
        """PRD §3.5: "Against that requirement the system maintains
        `covered_points`: the sum over the obligation's `APPROVED` mappings of
        each mapping's `coverage_weight` multiplied by its control's
        `effectiveness_factor` as evaluated at the current logical clock."

        Design: Difficulty/compensating_invariant/ci_mapping_approve_retire_conserves_coverage
        """
        pipe = setup_accepted_assessment(citation="CI-A", criticality="CRITICAL")
        gap = pipe["gaps"][0]
        assert gap["covered_points"] == 0.0
        assert gap["residual_gap_points"] == 32.0, "Full CRITICAL requirement exposed"

        ctl = create_control(control_code="CTL-CIA")
        create_approved_mapping(pipe["obligation"]["id"], ctl["id"], coverage_weight=4)
        after = get_gap(gap["id"])
        assert after["covered_points"] == 2.0, "4 x 0.5 = 2.0"
        assert after["residual_gap_points"] == 30.0, "32 - 2.0 = 30.0"

    def test_retire_restores_coverage_exactly(self, api, officer_a_headers):
        """PRD §3.3: "An approved mapping can later be retired (`APPROVED` →
        `RETIRED`), which drops its coverage from that moment."
        PRD §3.5: "Mappings in `PROPOSED`, `REJECTED`, or `RETIRED` contribute
        nothing."

        Design: Difficulty/compensating_invariant/ci_mapping_approve_retire_conserves_coverage
        """
        pipe = setup_accepted_assessment(citation="CI-A2", criticality="CRITICAL")
        gap = pipe["gaps"][0]
        ctl = create_control(control_code="CTL-CIA2")
        mapping = create_approved_mapping(pipe["obligation"]["id"], ctl["id"], coverage_weight=4)
        mid = get_gap(gap["id"])
        assert mid["covered_points"] == 2.0

        resp = api.retire_mapping(mapping["id"], officer_a_headers)
        retired = validate_success(resp, 200)
        assert retired["status"] == "RETIRED"
        after = get_gap(gap["id"])
        assert after["covered_points"] == 0.0, "Approve/retire pair leaves coverage unchanged"
        assert after["residual_gap_points"] == 32.0


class TestGapFreeze:
    def test_confirm_freezes_residual(self, api, officer_a_headers, officer_b_headers):
        """PRD §3.5: "confirming it (`IN_REVIEW` → `CONFIRMED`, the terminal state)
        recomputes coverage and residual one final time and then freezes both
        numbers permanently".
        PRD §3.5: "It is computed at gap creation and recomputed whenever a
        mapping of the obligation is approved or retired, whenever a mapped
        control records a review, and whenever the logical clock advances — but
        only while the gap analysis stands in `OPEN` or `IN_REVIEW`."

        Design: Corner/state_machines/sm_gap_confirm_freezes_residual
        """
        pipe = setup_confirmed_gap(citation="SM-11", criticality="CRITICAL")
        gap = pipe["gap"]
        assert gap["residual_gap_points"] == 32.0, "Frozen at confirm with zero coverage"
        ctl = create_control(control_code="CTL-SM-11")
        create_approved_mapping(pipe["obligation"]["id"], ctl["id"], coverage_weight=10)
        after = get_gap(gap["id"])
        assert after["residual_gap_points"] == 32.0, "CONFIRMED gap is untouched by new coverage"
        assert after["covered_points"] == 0.0


class TestRecordReviewReconciliation:
    def test_record_review_reconciles_open_gap(self, api, officer_a_headers):
        """PRD §3.3: "Recording a review stamps `last_reviewed_at` to the current
        clock, recomputes `next_review_due` and `effectiveness_factor`, and
        increments the control's `version` by one. Because coverage moves when
        effectiveness moves, the same call also recomputes `covered_points` and
        `residual_gap_points` on every gap analysis in `OPEN` or `IN_REVIEW` whose
        obligation has an `APPROVED` mapping to the reviewed control."

        Design: Corner/cross_cutting_layers/layer_record_review_reconciles_open_gap
        """
        owner = create_business_owner()
        change = create_triaged_change(citation="DR-1", severity_hint="CRITICAL")
        obl = create_obligation(change["id"], obligation_code="OBL-DR-1", criticality="CRITICAL")
        ctl = create_control(control_code="CTL-DR-1", title="Never reviewed")
        create_approved_mapping(obl["id"], ctl["id"], coverage_weight=4)

        assessment = create_assessment(change, owner["id"])
        start_assessment(assessment["id"], owner["id"])
        submit_assessment(assessment["id"], owner["id"], likelihood_score=3, severity_score=3)
        accept_assessment(assessment["id"])
        gap = list_gaps_for_assessment(assessment["id"])[0]
        assert gap["covered_points"] == 2.0, "Gap creation reflects approved mapping: 4 x 0.5"
        assert gap["residual_gap_points"] == 30.0

        reviewed = validate_success(api.record_control_review(ctl["id"], officer_a_headers), 200)
        assert reviewed["effectiveness_factor"] == 1.0, "Reviewed at the current clock"
        after = get_gap(gap["id"])
        assert after["covered_points"] == 4.0, "4 x 1.0 after review"
        assert after["residual_gap_points"] == 28.0, "32 - 4.0 = 28.0"
