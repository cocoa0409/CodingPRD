"""Difficulty: boundary_precision_check — KRI strict inequality on the red
threshold; appetite-breach inclusive >= on tolerance."""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId,
    create_category, create_assessed_risk,
    create_active_control, create_active_mapping,
    create_approved_appetite,
    create_residual_assessment,
    create_active_kri, observe_kri, advance_clock,
    get_risk,
    make_risk_owner_headers, make_risk_manager_headers,
    USER_RISK_OWNER, USER_RISK_MANAGER,
)


class TestKriRedThresholdStrictInequality:
    """Instance: value == red_threshold is NOT a red breach (strict >)."""

    def _build(self):
        cat = create_category(name="BK")
        kri = create_active_kri(
            cat["id"], name="Boundary KRI", direction="ABOVE",
            amber_threshold=50, red_threshold=75,
            min_observation_interval_days=0,
        )
        # Observation timestamps below lie after the default logical clock
        # (2026-08-01T00:00:00Z); advance it first so they are not rejected
        # as future observations (PRD §3.6 ERR_OBSERVATION_IN_FUTURE).
        advance_clock("2026-08-02T00:00:00Z")
        return kri

    def test_value_equal_to_red_yields_amber(self):
        """PRD §3.6: "Breach evaluation uses strict comparisons — equality
        with a threshold is never a breach of that band."
        PRD §3.6: "For an `ABOVE` indicator, the result is `RED_BREACH` when
        the observed value is strictly greater than the red threshold,
        `AMBER_BREACH` when it is strictly greater than the amber threshold
        and at most the red threshold".

        Design: Difficulty/boundary_precision_check/kri_red_threshold_strict_inequality
        """
        kri = self._build()
        obs = observe_kri(kri["id"], 75, "2026-08-01T01:00:00Z")
        assert obs["resulting_breach_status"] == "AMBER_BREACH"

    def test_value_above_red_yields_red(self):
        """PRD §3.6: "the result is `RED_BREACH` when the observed value is
        strictly greater than the red threshold".

        Design: Difficulty/boundary_precision_check/kri_red_threshold_strict_inequality
        """
        kri = self._build()
        observe_kri(kri["id"], 75, "2026-08-01T01:00:00Z")
        obs = observe_kri(kri["id"], 76, "2026-08-01T02:00:00Z")
        assert obs["resulting_breach_status"] == "RED_BREACH"


class TestAppetiteBreachInclusiveGreaterEqual:
    """Instance: residual_score >= tolerance_score is INCLUSIVE — equality
    creates a breach, residual tolerance-1 does not."""

    def _build_category_with_tolerance_9(self):
        cat = create_category(name="CB9")
        create_approved_appetite(
            cat["id"], tolerance_score=9, acceptance_cap_score=20,
        )
        return cat

    def test_residual_one_below_tolerance_no_breach(self):
        """PRD §3.4: "When the residual score is below the tolerance, no
        breach is created."

        Design: Difficulty/boundary_precision_check/appetite_breach_inclusive_greater_equal
        """
        cat = self._build_category_with_tolerance_9()
        # inherent 20, one mapping contribution 0.60 → residual ceil(20*0.40) = 8
        risk = create_assessed_risk(
            category_id=cat["id"], likelihood=4, impact=5, title="R8",
        )
        k = create_active_control(name="K60", effectiveness_pct=0.6)
        create_active_mapping(risk["id"], k["id"], coverage_weight=1.0)
        create_residual_assessment(risk["id"])
        after = get_risk(risk["id"])
        assert after["residual_score"] == 8
        breaches = validate_success(
            api_client.list_risk_tolerance_breaches(
                risk["id"], make_risk_manager_headers(USER_RISK_MANAGER),
            ), 200,
        )
        assert breaches == []

    def test_residual_equal_to_tolerance_creates_breach(self):
        """PRD §3.4: "the risk breaches appetite the moment its
        `residual_score` is greater than or equal to the statement's
        `tolerance_score` — equality with the tolerance is a breach."
        PRD §3.4: "the system then creates a ToleranceBreach in `OPEN`
        status... and records the offending score in `residual_at_breach`."

        Design: Difficulty/boundary_precision_check/appetite_breach_inclusive_greater_equal
        """
        cat = create_category(name="CB9")
        # inherent 20, two mappings contributions 0.40 + 0.30 →
        # discount 0.58 → residual ceil(20*0.42) = 9 (== tolerance)
        risk = create_assessed_risk(
            category_id=cat["id"], likelihood=4, impact=5, title="R9",
        )
        k80 = create_active_control(name="K80", effectiveness_pct=0.8)
        k60b = create_active_control(name="K60b", effectiveness_pct=0.6)
        create_active_mapping(risk["id"], k80["id"], coverage_weight=0.5)
        create_active_mapping(risk["id"], k60b["id"], coverage_weight=0.5)
        # Approve the appetite only now: mapping approvals recompute the
        # residual and run breach evaluation (PRD §3.3), and with tolerance 9
        # in place the intermediate residual 12 would already have breached
        # (residual_at_breach 12), defeating this test's premise. With no
        # APPROVED statement, "no breach is possible" (PRD §3.4) during the
        # approvals, and the residual assessment below is the first
        # evaluation that can breach — at exactly residual == tolerance.
        create_approved_appetite(
            cat["id"], tolerance_score=9, acceptance_cap_score=20,
        )
        create_residual_assessment(risk["id"])
        after = get_risk(risk["id"])
        assert after["residual_score"] == 9
        breaches = validate_success(
            api_client.list_risk_tolerance_breaches(
                risk["id"], make_risk_manager_headers(USER_RISK_MANAGER),
            ), 200,
        )
        assert len(breaches) == 1
        assert breaches[0]["status"] == "OPEN"
        assert breaches[0]["residual_at_breach"] == 9
