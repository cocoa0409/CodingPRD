"""Post-repair verification of cleared leaks (PRD §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    setup_completed_repair,
    setup_open_leak,
    setup_verifiable_leak,
    validate_error,
    validate_success,
)


class TestVerifyClearGate:
    def test_leak_verify_clear_from_open_rejected(self, api):
        """PRD §3.7: "the leak must be in `REPAIRED_PENDING_VERIFICATION`
        (`ERR_LEAK_NOT_PENDING_VERIFICATION`)"."

        Design: Corner/state_machines/leak_verify_clear_from_open_rejected
        """
        ctx = setup_open_leak(route_code="R-VO")
        resp = api.verify_clear_leak(ctx["leak"]["id"], ctx["co_h"])
        validate_error(resp, ApiErrorId.ERR_LEAK_NOT_PENDING_VERIFICATION)

    def test_leak_verify_blocked_by_missing_post_repair_survey(self, api):
        """PRD §3.7: "finally a post-repair survey run on the segment with
        `ACCEPTED` status and a leak-free finding must exist
        (`ERR_NO_POST_REPAIR_SURVEY`)" — the only accepted run here is the one
        that detected the leak, recorded before the repair.

        Design: Difficulty/cross_entity_state_dependency/leak_verify_blocked_by_missing_post_repair_survey
        """
        ctx = setup_completed_repair(route_code="R-Y")
        leak = get_success_data(api.get_leak(ctx["leak"]["id"], ctx["ia_h"]))
        assert leak["status"] == "REPAIRED_PENDING_VERIFICATION"
        resp = api.verify_clear_leak(ctx["leak"]["id"], ctx["co_h"])
        validate_error(resp, ApiErrorId.ERR_NO_POST_REPAIR_SURVEY)

    def test_leak_verify_succeeds_once_post_repair_survey_accepted(self, api):
        """PRD §3.7: "On success the leak moves to `VERIFIED_CLEARED`" once "a
        post-repair survey run on the segment with `ACCEPTED` status and a
        leak-free finding" exists; "`VERIFIED_CLEARED` is terminal."

        Design: Difficulty/cross_entity_state_dependency/leak_verify_blocked_by_missing_post_repair_survey
        """
        ctx = setup_verifiable_leak(route_code="R-Y2")
        data = validate_success(api.verify_clear_leak(ctx["leak"]["id"], ctx["co_h"]))
        assert data["status"] == "VERIFIED_CLEARED"


class TestVerifyClearCascade:
    def test_verify_clear_decrements_counter_and_recomputes_posture(self, api):
        """PRD §3.7: "On success the leak moves to `VERIFIED_CLEARED`, the order's
        `verified_by_officer_id` is set from `X-User-ID`, the segment's open-grade
        counter for the grade the leak held decrements, `posture` recomputes,
        `risk_score` recomputes per §3.8, and risk-model snapshots touching the
        segment go stale." One open G2 held `ELEVATED` beforehand
        (PRD §2.8: "Otherwise, if it has exactly one open Grade 2 leak, or at
        least one cathodic-protection anomaly in `OPEN` or `ACKNOWLEDGED` status,
        posture is `ELEVATED`."), returning to `NORMAL` after.

        Design: Difficulty/transitive_cascade/verify_clear_cascades_to_segment_counters
        """
        ctx = setup_verifiable_leak(route_code="R-V")
        segment = ctx["segments"][0]
        before = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))
        assert before["open_grade2_count"] == 1
        assert before["posture"] == "ELEVATED"

        validate_success(api.verify_clear_leak(ctx["leak"]["id"], ctx["co_h"]))
        after = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))
        assert after["open_grade2_count"] == 0
        assert after["posture"] == "NORMAL"
        leak = get_success_data(api.get_leak(ctx["leak"]["id"], ctx["ia_h"]))
        assert leak["status"] == "VERIFIED_CLEARED"

    def test_verify_clear_recomputes_risk_score(self, api):
        """PRD §3.7: "`risk_score` recomputes per §3.8" — the leak component
        (PRD §3.8: "The leak component takes `open_grade1_count` times 3.0 plus
        `open_grade2_count` times 1.5 plus `open_grade3_count` times 0.5, caps the
        result at 1.0, and multiplies by a weight of 0.30.") drops out once the
        only open G2 leak is verified cleared. For a STEEL/DISTRIBUTION/non-HCA
        segment installed 2005 (age 21 in 2026): 0.084 + 0.12 + 0.30 = 0.504 ->
        50.4 before; 0.084 + 0.12 = 0.204 -> 20.4 after.

        Design: Difficulty/transitive_cascade/verify_clear_cascades_to_segment_counters
        """
        ctx = setup_verifiable_leak(
            route_code="R-V2",
            segment_overrides={"segment_code": "SEG-V2", "install_year": 2005},
        )
        segment = ctx["segments"][0]
        before = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))
        assert before["risk_score"] == pytest.approx(50.4, abs=0.01)

        validate_success(api.verify_clear_leak(ctx["leak"]["id"], ctx["co_h"]))
        after = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))
        assert after["risk_score"] == pytest.approx(20.4, abs=0.01)
