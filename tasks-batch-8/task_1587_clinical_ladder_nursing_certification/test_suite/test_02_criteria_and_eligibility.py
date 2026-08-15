"""Ladder criterion publication rules and application eligibility gates.

Covers PRD §3.1 (window overlap, half-open adjacency, differential
monotonicity) and §3.4 (one-rung rule, active-criterion gate).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_criterion,
    create_draft_application,
    create_ladder_criterion_payload,
    create_nurse,
    make_nurse_headers,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


def _post_criterion(api, **overrides):
    return api.create_ladder_criterion(
        create_ladder_criterion_payload(**overrides), ADMIN
    )


class TestCriterionWindowOverlap:
    def test_adjacent_criterion_window_accepted(self, api):
        """PRD §3.1: "Two criterion sets for the same `target_level` may not
        have overlapping validity windows — geometric overlap of the half-open
        intervals — and mere adjacency, where one set's `effective_until`
        equals the other's `effective_from`, is not overlap..."

        Design: Difficulty/resource_temporal_overlap/criterion_window_half_open_adjacency
        """
        set_clock("2026-08-01T00:00:00Z")
        first = _post_criterion(
            api, target_level="CN_II", effective_from="2026-01-01T00:00:00Z",
            effective_until="2027-01-01T00:00:00Z",
        )
        validate_success(first, 201)
        adjacent = _post_criterion(
            api, target_level="CN_II", min_portfolio_score=78,
            differential_monthly_cents=32000,
            effective_from="2027-01-01T00:00:00Z", effective_until=None,
        )
        data = validate_success(adjacent, 201)
        assert data["id"], "adjacent (effective_from == prior effective_until) must be accepted"
        fetched = validate_success(api.get_ladder_criterion(data["id"], ADMIN))
        assert fetched["effective_from"] is not None

    def test_one_second_window_overlap_rejected(self, api):
        """PRD §3.1: "...a violation is rejected with
        `ERR_CRITERION_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/criterion_window_half_open_adjacency
        """
        set_clock("2026-08-01T00:00:00Z")
        validate_success(
            _post_criterion(
                api, target_level="CN_II",
                effective_from="2026-01-01T00:00:00Z",
                effective_until="2027-01-01T00:00:00Z",
            ),
            201,
        )
        resp = _post_criterion(
            api, target_level="CN_II", min_portfolio_score=79,
            differential_monthly_cents=33000,
            effective_from="2026-12-31T23:59:59Z", effective_until=None,
        )
        validate_error(resp, ApiErrorId.ERR_CRITERION_WINDOW_OVERLAP, 409)


class TestDifferentialMonotonicity:
    def test_differential_monotonicity_violation(self, api):
        """PRD §3.1: "Across the criterion sets active at the same time,
        monthly differentials must strictly increase with the rung: the `CN_IV`
        amount strictly greater than the `CN_III` amount, which is strictly
        greater than the `CN_II` amount; a violation is rejected with
        `ERR_DIFFERENTIAL_MONOTONICITY` (HTTP 422)."

        Design: Corner/validations/differential_monotonicity_violation
        """
        validate_success(
            _post_criterion(api, target_level="CN_II",
                            differential_monthly_cents=30000),
            201,
        )
        resp = _post_criterion(
            api, target_level="CN_III", min_portfolio_score=80,
            differential_monthly_cents=25000,
        )
        validate_error(resp, ApiErrorId.ERR_DIFFERENTIAL_MONOTONICITY, 422)


class TestApplicationEligibility:
    def test_skip_rung_application_rejected(self, api):
        """PRD §3.4: "The target must be exactly one rung above the nurse's
        current level — `CN_I` to `CN_II`, `CN_II` to `CN_III`, `CN_III` to
        `CN_IV` — and skip-rung or same-rung drafts are rejected with
        `ERR_LADDER_RUNG_VIOLATION` (HTTP 422)."

        Design: Corner/validations/skip_rung_application_rejected
        """
        create_criterion(target_level="CN_III", min_portfolio_score=80,
                         differential_monthly_cents=50000)
        nurse = create_nurse(employee_code="RN-SK1", full_name="Sk One")
        nurse_headers = make_nurse_headers(nurse["id"])
        resp = api.create_application(
            {
                "nurse_id": nurse["id"],
                "target_level": "CN_III",
                "portfolio_narrative": "skip",
                "expected_nurse_version": nurse["version"],
            },
            nurse_headers,
        )
        validate_error(resp, ApiErrorId.ERR_LADDER_RUNG_VIOLATION, 422)

    def test_submit_without_active_criterion(self, api):
        """PRD §3.4: "...then the existence of an active criterion set covering
        the target level at the current clock position (`ERR_NO_ACTIVE_CRITERION`
        when none does, remembering that the window is half-open and a null
        `effective_until` is open-ended)..."

        Setup note: drafting an application also evaluates the active-criterion
        rule (PRD §2.8), so the criterion is published covering the draft-time
        clock, and the clock is then advanced past `effective_until` so that no
        active criterion covers the submission instant.

        Design: Corner/validations/submit_without_active_criterion
        """
        set_clock("2026-08-01T00:00:00Z")
        create_criterion(
            target_level="CN_II",
            effective_from="2026-01-01T00:00:00Z",
            effective_until="2026-09-01T00:00:00Z",
        )
        nurse = create_nurse(employee_code="RN-NC1", full_name="Nc One")
        app = create_draft_application(nurse, "CN_II")
        set_clock("2026-09-15T00:00:00Z")
        resp = api.submit_application(app["id"], make_nurse_headers(nurse["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_CRITERION, 422)
