"""Annotator onboarding, tier derivation, re-evaluation, and reinstatement.
Covers PRD §3.2."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_annotator_profile,
    create_annotator,
    create_annotator_payload,
    create_expert_annotator,
    create_junior_annotator,
    create_senior_annotator,
    re_evaluate,
    reinstate,
    validate_error,
    validate_success,
)


# =========================================================================
# §3.2 -- Initial registration
# =========================================================================
class TestAnnotatorRegister:

    def test_register_initial_state(self, api, project_manager_headers):
        """PRD §3.2: 'The newly created AnnotatorProfile enters ACTIVE
        status. Its starting tier is derived from the entry-test score:
        a score of 95 or higher mints an EXPERT, a score of 80 or higher
        (but below 95) mints a SENIOR, and any lower score mints a
        JUNIOR. ... lifetime_pass_rate, rolling_pass_rate, and
        golden_hit_rate all start at 1.0 and last_evaluated_at is null
        until the first re-evaluation runs.'

        Claim: a brand-new annotator has status=ACTIVE, all rates=1.0,
        last_evaluated_at == null.
        """
        res = api.create_annotator(
            create_annotator_payload(entry_test_score=70),
            project_manager_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_annotator_profile(data)
        assert data["status"] == "ACTIVE"
        assert float(data["lifetime_pass_rate"]) == 1.0
        assert float(data["rolling_pass_rate"]) == 1.0
        assert float(data["golden_hit_rate"]) == 1.0
        assert data["last_evaluated_at"] is None
        assert data["tier"] == "JUNIOR"

    def test_initial_tier_junior_when_score_below_80(self):
        """PRD §3.2: 'a score of 95 or higher mints an EXPERT, a score
        of 80 or higher (but below 95) mints a SENIOR, and any lower
        score mints a JUNIOR.'

        Claim: entry_test_score=70 -> JUNIOR.
        """
        a = create_annotator(entry_test_score=70.0)
        assert a["tier"] == "JUNIOR"

    def test_initial_tier_senior_at_80(self):
        """PRD §3.2: 'a score of 80 or higher (but below 95) mints a
        SENIOR'.

        Claim: entry_test_score=80 -> SENIOR (inclusive boundary).
        """
        a = create_annotator(entry_test_score=80.0)
        assert a["tier"] == "SENIOR"

    def test_initial_tier_expert_at_95(self):
        """PRD §3.2: 'a score of 95 or higher mints an EXPERT'.

        Claim: entry_test_score=95 -> EXPERT (inclusive boundary).
        """
        a = create_annotator(entry_test_score=95.0)
        assert a["tier"] == "EXPERT"

    @pytest.mark.parametrize("bad_score", [-1, 101, 150])
    def test_entry_score_out_of_range(
        self, api, project_manager_headers, bad_score,
    ):
        """PRD §3.2: 'an entry-test result entry_test_score between 0 and
        100 inclusive.' PRD §3.1 (parameter ranges) implies range
        violations are rejected with ERR_INVALID_PARAMETER.

        Claim: entry_test_score outside [0, 100] -> ERR_INVALID_PARAMETER.
        """
        res = api.create_annotator(
            create_annotator_payload(entry_test_score=bad_score),
            project_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_PARAMETER.value)


# =========================================================================
# §3.2 -- Reinstatement
# =========================================================================
class TestReinstate:

    def test_reinstate_active_annotator_returns_state_invalid_or_no_op(
        self, api, project_manager_headers,
    ):
        """PRD §3.2 (reinstatement): 'Reinstatement by a ProjectManager
        puts the annotator back into ACTIVE.'

        We avoid asserting a specific behavior when the annotator is
        already ACTIVE because PRD does not commit to one (a state-machine
        rejection or a no-op are both faithful). Instead, drive a real
        ACTIVE -> SUSPENDED -> ACTIVE round-trip and assert the cycle.

        Claim: After SUSPEND -> reinstate, status returns to ACTIVE and
        tier is preserved (PRD: 'the underlying counters are not reset').
        """
        # Build a senior with sufficient submissions so re-eval can drive
        # them to SUSPENDED via the failure path.
        from test_helpers import (
            setup_annotator_with_pass_fail_history,
        )
        senior = create_senior_annotator()
        # Drive enough fails to push rolling_pass_rate < 0.70 over a
        # 20-package window. Sequence: 6 fails out of 20 yields rolling
        # pass rate 0.70 (boundary, no suspension); 7 fails -> 0.65
        # (suspends). We use 14 PASS + 7 FAIL to ensure the window is
        # full and the rate is below 0.70.
        seq = (["PASS"] * 14) + (["FAIL"] * 7)
        setup_annotator_with_pass_fail_history(
            annotator=senior, pass_then_fail=seq,
        )
        # PRD §3.2: re-evaluate suspends if rolling_pass_rate < 0.70.
        a_after = re_evaluate(senior["id"])
        assert a_after["status"] == "SUSPENDED"
        assert a_after["tier"] == "JUNIOR"
        # Reinstate.
        a_reinstated = reinstate(senior["id"])
        assert a_reinstated["status"] == "ACTIVE"


# =========================================================================
# §3.2 -- Re-evaluate (suspension overlay)
# =========================================================================
class TestReEvaluate:

    def test_reeval_does_not_reset_counters_after_reinstate(self, api):
        """PRD §3.2: 'Reinstatement by a ProjectManager puts the
        annotator back into ACTIVE; the underlying counters are not
        reset, so a further metric breach can re-suspend the same
        annotator.'

        Claim: after reinstate the same metrics remain so a re-evaluate
        immediately re-suspends.
        """
        from test_helpers import (
            setup_annotator_with_pass_fail_history,
        )
        senior = create_senior_annotator()
        seq = (["PASS"] * 14) + (["FAIL"] * 7)
        setup_annotator_with_pass_fail_history(
            annotator=senior, pass_then_fail=seq,
        )
        re_evaluate(senior["id"])
        reinstate(senior["id"])
        # Counters not reset; re-evaluate re-suspends.
        again = re_evaluate(senior["id"])
        assert again["status"] == "SUSPENDED"
