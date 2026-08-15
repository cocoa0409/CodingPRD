"""Questionnaire review cycle, acceptance gates, and issuance concurrency."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_third_party,
    issue_questionnaire,
    officer_headers,
    setup_third_party_in_state,
    sponsor_headers,
    submit_questionnaire,
    validate_error,
    validate_success,
)


class TestReturnResubmitCycle:
    """The questionnaire machine loops SUBMITTED -> RETURNED -> SUBMITTED before
    reaching ACCEPTED."""

    def _setup_submitted_questionnaire(self, api):
        ctx = setup_third_party_in_state("DD_REVIEW", "CH", 80, "TECHNOLOGY", "NONE")
        tp_id = ctx["third_party"]["id"]
        q = issue_questionnaire(tp_id)
        submit_questionnaire(q["id"])
        return tp_id, q["id"]

    def test_return_resubmit_accept_cycle(self, api, officer_headers):
        """PRD §3.4: "An officer who finds the answers deficient returns the
        questionnaire — `SUBMITTED` back to `RETURNED` with an optional
        `return_note` — and the sponsor may resubmit, looping until the officer
        is satisfied."
        PRD §3.4: "Submission computes `red_flag_count`, the number of risky
        answers among the three: government ownership above zero, facilitation
        payments admitted, sub-agents in use."

        Design: Difficulty/non_linear_state_machine/questionnaire_return_resubmit_cycle
        """
        tp_id, q_id = self._setup_submitted_questionnaire(api)

        ret = validate_success(
            api.return_questionnaire(q_id, {"return_note": "section 4 incomplete"},
                                     officer_headers), 200)
        assert ret["questionnaire_status"] == "RETURNED"

        resub = validate_success(
            api.submit_questionnaire(
                q_id,
                {"government_ownership_pct": 5, "has_facilitation_payments": False,
                 "uses_sub_agents": False},
                sponsor_headers(),
            ), 200)
        assert resub["questionnaire_status"] == "SUBMITTED", "the cycle re-enters SUBMITTED"
        assert resub["red_flag_count"] == 1, "government_ownership_pct 5 > 0 is one risky answer"

        acc = validate_success(api.accept_questionnaire(q_id, officer_headers), 200)
        assert acc["questionnaire_status"] == "ACCEPTED"

    def test_resubmitted_answers_feed_final_score(self, api, officer_headers):
        """PRD §3.4: "The final variant starts from the provisional score and
        adds two modifiers. The questionnaire modifier is 10 when
        `government_ownership_pct` is above zero, plus 15 when
        `has_facilitation_payments` is true, plus 5 when `uses_sub_agents` is
        true."
        PRD §3.4: "Acceptance moves the questionnaire to `ACCEPTED` and computes
        `risk_score_final`, then re-derives `risk_tier` from it through the same
        inclusive thresholds."

        Design: Difficulty/non_linear_state_machine/questionnaire_return_resubmit_cycle
        """
        tp_id, q_id = self._setup_submitted_questionnaire(api)
        validate_success(api.return_questionnaire(q_id, {"return_note": "section 4 incomplete"},
                                                  officer_headers), 200)
        validate_success(
            api.submit_questionnaire(
                q_id,
                {"government_ownership_pct": 5, "has_facilitation_payments": False,
                 "uses_sub_agents": False},
                sponsor_headers(),
            ), 200)
        validate_success(api.accept_questionnaire(q_id, officer_headers), 200)

        tp = get_third_party(tp_id)
        # Provisional 16 (CH/TECHNOLOGY/NONE) + 10 (gov ownership > 0) = 26 -> LOW.
        assert tp["risk_score_final"] == 26
        assert tp["risk_tier"] == "LOW"


class TestAcceptanceGates:
    def test_questionnaire_accept_from_issued_rejected(self, api, officer_headers):
        """PRD §3.4: "The officer may accept only while the third party is in
        `DD_REVIEW` or `ENHANCED_REVIEW` (otherwise `ERR_INVALID_STATE`), only
        the current questionnaire (`ERR_INVALID_STATE`), and only once every
        screening check on the party is terminal"
        PRD §2.10: "a transition the machine does not permit from the entity's
        current non-terminal state is rejected with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/questionnaire_accept_from_issued_rejected
        """
        # Questionnaire issued while screening runs; never submitted.
        ctx = setup_third_party_in_state("SCREENING", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        q = issue_questionnaire(tp_id)

        resp = api.accept_questionnaire(q["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestIssuanceConcurrency:
    def test_questionnaire_issue_stale_version_returns_412(self, api, officer_headers):
        """PRD §2.7: "Issuing a questionnaire for a third party and updating a
        third party's profile each require the non-optional field
        `expected_third_party_version`, carrying the third party's `version` as
        the client last read it"
        PRD §2.7: "In all three cases a mismatch with the parent's current
        `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.4: "Issuing creates the questionnaire in `ISSUED`, flips any
        predecessor still sitting in `ISSUED`, `SUBMITTED`, or `RETURNED` to
        `SUPERSEDED`, and increments the third party's `version` by one; an
        `ACCEPTED` predecessor is terminal and is left untouched."

        Design: Corner/cross_cutting_complexity_layers/questionnaire_issue_stale_version_returns_412
        """
        ctx = setup_third_party_in_state("DD_REVIEW", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        observed = get_third_party(tp_id)["version"]

        q1 = validate_success(
            api.issue_questionnaire(tp_id, {"expected_third_party_version": observed},
                                    officer_headers), 201)

        stale = api.issue_questionnaire(tp_id, {"expected_third_party_version": observed},
                                        officer_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = get_third_party(tp_id)["version"]
        q2 = validate_success(
            api.issue_questionnaire(tp_id, {"expected_third_party_version": fresh},
                                    officer_headers), 201)

        listing = validate_success(api.list_questionnaires(tp_id, officer_headers), 200)
        by_id = {q["id"]: q for q in listing}
        assert by_id[q1["id"]]["questionnaire_status"] == "SUPERSEDED"
        assert by_id[q2["id"]]["questionnaire_status"] == "ISSUED"
