"""Qualitative factor framework: windows, documentation chain, overlay math (PRD §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_model_run_totals,
    assert_qualitative_factor,
    create_approved_factor,
    create_draft_run,
    create_factor,
    create_factor_payload,
    create_segment,
    execute_run,
    get_allowance_summary,
    prime_loan_spec,
    setup_run_environment,
    validate_error,
    validate_success,
)

DOC_TEXT = (
    "Energy-sector concentration elevated relative to risk appetite; "
    "committee approved overlay per memo Q1-2026."
)


class TestFactorWindowOverlap:
    def test_adjacent_factor_windows_accepted(self, api, credit_analyst_headers):
        """PRD §3.5: "One structural rule keeps overlays auditable: within the same pairing of segment and factor code, the closed windows of factors that are not `RETIRED` may never overlap. Because the windows are closed, adjacency means one factor's last covered quarter immediately precedes the other's first covered quarter — that arrangement is allowed — but any true intersection is rejected with `ERR_FACTOR_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/factor_closed_interval_adjacency
        """
        segment = create_segment()
        first = create_factor(segment["id"], factor_code="CONCENTRATION_RISK",
                              adjustment_bps=25, effective_from_period="2026-Q1",
                              effective_to_period="2026-Q2")
        # Closed window: first covers Q1 and Q2; Q3 immediately follows Q2 -> adjacent, allowed.
        res = api.create_qualitative_factor(
            create_factor_payload(segment["id"], factor_code="CONCENTRATION_RISK",
                                  adjustment_bps=30, effective_from_period="2026-Q3",
                                  effective_to_period="2026-Q4"),
            credit_analyst_headers,
        )
        data = validate_success(res, 201)
        assert_qualitative_factor(data)
        assert data["id"] != first["id"]

    def test_overlapping_factor_windows_rejected(self, api, credit_analyst_headers):
        """PRD §3.5: "One structural rule keeps overlays auditable: within the same pairing of segment and factor code, the closed windows of factors that are not `RETIRED` may never overlap. Because the windows are closed, adjacency means one factor's last covered quarter immediately precedes the other's first covered quarter — that arrangement is allowed — but any true intersection is rejected with `ERR_FACTOR_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/factor_closed_interval_adjacency
        """
        segment = create_segment()
        create_factor(segment["id"], factor_code="CONCENTRATION_RISK",
                      adjustment_bps=25, effective_from_period="2026-Q1",
                      effective_to_period="2026-Q2")
        # [2026-Q2, 2026-Q3] shares quarter Q2 with the existing [Q1, Q2] window.
        res = api.create_qualitative_factor(
            create_factor_payload(segment["id"], factor_code="CONCENTRATION_RISK",
                                  adjustment_bps=10, effective_from_period="2026-Q2",
                                  effective_to_period="2026-Q3"),
            credit_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_FACTOR_WINDOW_OVERLAP, 409)


class TestFactorDocumentationChain:
    def test_factor_approve_from_draft_rejected(self, api, chief_credit_officer_headers):
        """PRD §3.5: "A `ChiefCreditOfficer` then approves it, moving it `DOCUMENTED` → `APPROVED`, and only `APPROVED` factors ever enter a run's overlay."
        PRD §2.9: "State-transition legality: the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Any transition attempted from a state other than its declared source state fails here."

        Design: Corner/state_machines/factor_approve_from_draft_rejected
        """
        segment = create_segment()
        factor = create_factor(segment["id"], factor_code="CONCENTRATION_RISK",
                               adjustment_bps=25, effective_from_period="2026-Q1",
                               effective_to_period="2026-Q2")
        res = api.approve_qualitative_factor(factor["id"], chief_credit_officer_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        assert validate_success(
            api.get_qualitative_factor(factor["id"], chief_credit_officer_headers), 200
        )["status"] == "DRAFT"

    def test_factor_approve_forbidden_for_analyst(self, api, credit_analyst_headers):
        """PRD §2.1: "A request whose role is valid but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §3.5: "A `CreditAnalyst` moves a `DRAFT` factor to `DOCUMENTED` by attaching the supporting narrative: the supplied `documentation_text` must have a trimmed length of at least fifty characters, and a thinner rationale is rejected with `ERR_FACTOR_DOCUMENTATION_INSUFFICIENT` (HTTP 422); the accepted text is stored on the factor."

        Design: Corner/validations/factor_approve_forbidden_for_analyst
        """
        segment = create_segment()
        factor = create_factor(segment["id"], factor_code="POLICY_CHANGE",
                               adjustment_bps=15, effective_from_period="2026-Q1",
                               effective_to_period="2026-Q2")
        documented = validate_success(api.document_qualitative_factor(
            factor["id"],
            {"documentation_text": (
                "Underwriting policy tightened in March 2026; overlay reflects "
                "reduced risk appetite per committee minutes."
            )},
            credit_analyst_headers,
        ), 200)
        assert documented["status"] == "DOCUMENTED"

        res = api.approve_qualitative_factor(factor["id"], credit_analyst_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
        assert validate_success(
            api.get_qualitative_factor(factor["id"], credit_analyst_headers), 200
        )["status"] == "DOCUMENTED"


class TestQualitativeOverlay:
    def test_qualitative_window_filtering(self, api):
        """PRD §3.6: "The overlay in basis points is the sum of `adjustment_bps` over the segment's factors that are `APPROVED` and whose closed effective window covers the run's `as_of_period` — the from-quarter's index is at most the run's index, and the run's index is at most the to-quarter's index. The segment's qualitative adjustment in cents is its collective exposure multiplied by the overlay basis points and divided by ten thousand, rounded half-up to a whole cent."

        Design: Corner/calculations/qualitative_window_filtering
        """
        env = setup_run_environment(loan_specs=[prime_loan_spec(10_000_000)])
        # APPROVED factor whose closed window covers only 2026-Q1.
        create_approved_factor(
            env.segments[0]["id"], factor_code="ECONOMIC_UNCERTAINTY",
            adjustment_bps=25, effective_from_period="2026-Q1",
            effective_to_period="2026-Q1", documentation_text=DOC_TEXT,
        )

        execute_run(env.run["id"])  # as_of_period 2026-Q1
        summary_q1 = get_allowance_summary(env.run["id"])
        # round_half_up(10000000 * 25 / 10000) = 25000
        assert summary_q1["qualitative_adjustment_cents"] == 25_000
        assert summary_q1["quantitative_reserve_cents"] == 50_000
        assert summary_q1["total_allowance_cents"] == 75_000
        assert_model_run_totals(summary_q1)

        run_q2 = create_draft_run(
            env.model["id"],
            [{"scenario_id": env.scenarios[0]["id"], "weight_bps": 10_000}],
            as_of_period="2026-Q2",
        )
        execute_run(run_q2["id"])
        summary_q2 = get_allowance_summary(run_q2["id"])
        # The closed window [2026-Q1, 2026-Q1] does not cover 2026-Q2.
        assert summary_q2["qualitative_adjustment_cents"] == 0
        assert summary_q2["total_allowance_cents"] == 50_000

    def test_segment_allowance_floor_at_zero(self, api):
        """PRD §3.6: "A floor then protects the segment: when the quantitative reserve plus the qualitative adjustment would be negative, the adjustment is set to the exact negative of the quantitative reserve, so the segment's allowance lands at zero and never below. The segment's allowance is its quantitative reserve plus its qualitative adjustment."

        Design: Corner/calculations/segment_allowance_floor_at_zero
        """
        env = setup_run_environment(
            segment_specs=[{"name": "NearPrime Cards", "risk_rating_band": "NEAR_PRIME"}],
            loan_specs=[{"amortized_cost_cents": 100_000, "risk_rating": "PASS"}],
        )
        create_approved_factor(
            env.segments[0]["id"], factor_code="COLLATERAL_VALUATION",
            adjustment_bps=-2_000, effective_from_period="2026-Q1",
            effective_to_period="2026-Q4",
            documentation_text=(
                "Updated collateral index indicates systematic overvaluation; "
                "negative overlay supported by reappraisal study 2026-04."
            ),
        )
        execute_run(env.run["id"])
        summary = get_allowance_summary(env.run["id"])
        row = summary["segments_breakdown"][0]
        # rate 150 bps on 100000 -> quantitative 1500; raw qual = -20000 -> clamped
        # to the exact negative of the quantitative reserve.
        assert row["quantitative_reserve_cents"] == 1_500
        assert row["qualitative_adjustment_cents"] == -1_500
        assert row["segment_allowance_cents"] == 0
        assert_model_run_totals(summary)
