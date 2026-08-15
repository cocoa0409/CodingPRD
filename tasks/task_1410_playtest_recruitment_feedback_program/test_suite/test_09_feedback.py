"""Feedback tickets: triage scoring, the triage/info loop, forced P1 override,
and routing."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_study,
    create_ticket,
    get_success_data,
    TEST_USERS,
    validate_error,
    validate_success,
)

RESEARCHER = TEST_USERS["researcher_headers"]


class TestFeedbackTriageInfoLoop:
    def _file_medium_ticket(self, api):
        study = create_study(open_recruitment=False, code="NL2")
        ticket = create_ticket(study["id"], title="Crash on startup",
                               severity="MEDIUM", reach_count=10,
                               reproducibility_pct=0.5)
        assert ticket["status"] == "NEW"
        return ticket

    def test_triage_info_cycle_recomputes_score_stably(self, api):
        """PRD §3.7: "Requesting more information moves `TRIAGED` →
        `NEEDS_INFO`, and the `TRIAGED` → `NEEDS_INFO` → `TRIAGED` cycle may
        repeat, with each triage recomputing the score and tier from the
        ticket's current fields."
        PRD §3.7: "The priority score starts from a severity weight: 1 for
        `LOW`, 2 for `MEDIUM`, 3 for `HIGH`, and 5 for `CRITICAL`. The raw
        score is that weight multiplied by 100 and by the ticket's
        `reproducibility_pct`, plus a reach contribution that counts each
        affected user as half a point but never counts more than one thousand
        affected users. The `priority_score` is that raw value rounded half-up
        to two decimal places. The `priority_tier` then buckets the score: `P1`
        when the score is at least 400, otherwise `P2` when at least 200,
        otherwise `P3` when at least 80, otherwise `P4`."

        Design: Difficulty/non_linear_state_machine/feedback_ticket_triage_info_loop
        """
        ticket = self._file_medium_ticket(api)
        # MEDIUM weight 2: 2*100*0.5 + min(10, 1000)*0.5 = 100 + 5 = 105.0.
        t1 = validate_success(api.triage_feedback_ticket(ticket["id"], RESEARCHER))
        assert t1["status"] == "TRIAGED"
        assert t1["priority_score"] == pytest.approx(105.0, abs=0.001)
        assert t1["priority_tier"] == "P3"
        t2 = validate_success(api.request_ticket_info(ticket["id"], RESEARCHER))
        assert t2["status"] == "NEEDS_INFO"
        t3 = validate_success(api.triage_feedback_ticket(ticket["id"], RESEARCHER))
        assert t3["status"] == "TRIAGED", "the loop returns to TRIAGED"
        assert t3["priority_score"] == pytest.approx(105.0, abs=0.001), (
            "recompute over unchanged fields is stable")

    def test_loop_continues_to_route_and_resolve(self, api):
        """PRD §3.7: "Routing moves `TRIAGED` → `ROUTED` and sets
        `backlog_target` to one of `GAMEPLAY`, `PERFORMANCE`, `UX`, `AUDIO`, or
        `INFRA`. From `ROUTED`, resolution moves the ticket `ROUTED` →
        `RESOLVED` and the won't-fix call moves it `ROUTED` → `WONT_FIX`; both
        are terminal."

        Design: Difficulty/non_linear_state_machine/feedback_ticket_triage_info_loop
        """
        ticket = self._file_medium_ticket(api)
        get_success_data(api.triage_feedback_ticket(ticket["id"], RESEARCHER))
        get_success_data(api.request_ticket_info(ticket["id"], RESEARCHER))
        get_success_data(api.triage_feedback_ticket(ticket["id"], RESEARCHER))
        routed = validate_success(api.route_feedback_ticket(ticket["id"], "GAMEPLAY",
                                                            RESEARCHER))
        assert routed["status"] == "ROUTED"
        assert routed["backlog_target"] == "GAMEPLAY"
        resolved = validate_success(api.resolve_feedback_ticket(ticket["id"], RESEARCHER))
        assert resolved["status"] == "RESOLVED"


def test_forced_p1_priority_override(api):
    """PRD §3.7: "One forced override stands above the arithmetic: a ticket
    whose `severity` is `CRITICAL` and whose `reach_count` is at least 100 is
    `P1` regardless of its score."
    PRD §3.7: "The `priority_tier` then buckets the score: `P1` when the score
    is at least 400, otherwise `P2` when at least 200, otherwise `P3` when at
    least 80, otherwise `P4`."

    Design: Corner/calculations/forced_p1_priority_override
    """
    study = create_study(open_recruitment=False, code="PRIO")
    ticket = create_ticket(study["id"], title="Save corruption on logout",
                           severity="CRITICAL", reach_count=150,
                           reproducibility_pct=0.3)
    triaged = validate_success(api.triage_feedback_ticket(ticket["id"], RESEARCHER))
    # CRITICAL weight 5: 5*100*0.3 + min(150, 1000)*0.5 = 150 + 75 = 225.0.
    assert triaged["priority_score"] == pytest.approx(225.0, abs=0.001)
    # 225.0 buckets to P2 arithmetically; CRITICAL + reach >= 100 forces P1.
    assert triaged["priority_tier"] == "P1"


def test_feedback_route_sets_backlog_target(api):
    """PRD §3.7: "Routing moves `TRIAGED` → `ROUTED` and sets `backlog_target`
    to one of `GAMEPLAY`, `PERFORMANCE`, `UX`, `AUDIO`, or `INFRA`."
    PRD §3.7: "The priority score starts from a severity weight: 1 for `LOW`,
    2 for `MEDIUM`, 3 for `HIGH`, and 5 for `CRITICAL`. The raw score is that
    weight multiplied by 100 and by the ticket's `reproducibility_pct`, plus a
    reach contribution that counts each affected user as half a point but never
    counts more than one thousand affected users."

    Design: Corner/endpoints/feedback_route_sets_backlog_target
    """
    study = create_study(open_recruitment=False, code="RT1")
    ticket = create_ticket(study["id"], title="Audio desync in cutscenes",
                           severity="HIGH", reach_count=40, reproducibility_pct=0.9)
    get_success_data(api.triage_feedback_ticket(ticket["id"], RESEARCHER))
    routed = validate_success(api.route_feedback_ticket(ticket["id"], "AUDIO",
                                                        RESEARCHER))
    assert routed["status"] == "ROUTED"
    assert routed["backlog_target"] == "AUDIO"
    # HIGH weight 3: 3*100*0.9 + min(40, 1000)*0.5 = 270 + 20 = 290.0 -> P2.
    assert routed["priority_score"] == pytest.approx(290.0, abs=0.001)
    assert routed["priority_tier"] == "P2"


def test_feedback_ticket_route_from_new_rejected(api):
    """PRD §3.7: "Routing moves `TRIAGED` → `ROUTED` and sets `backlog_target`
    to one of `GAMEPLAY`, `PERFORMANCE`, `UX`, `AUDIO`, or `INFRA`."
    PRD §2.9: "The generic rejection is `ERR_INVALID_STATE`"

    Design: Corner/endpoints/feedback_ticket_route_from_new_rejected
    """
    study = create_study(open_recruitment=False, code="NR1")
    ticket = create_ticket(study["id"], title="Untriaged", severity="LOW",
                           reach_count=1, reproducibility_pct=0.1)
    assert ticket["status"] == "NEW"
    resp = api.route_feedback_ticket(ticket["id"], "UX", RESEARCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
