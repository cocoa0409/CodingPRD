"""Late-response adjudication terminality and void gating (PRD §3.5, §3.6)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_cycle,
    get_response,
    get_success_data,
    record_response,
    set_clock,
    setup_cycle_in_state,
    setup_program,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
STEWARD = TEST_USERS["steward_headers"]


def _late_response_ctx(api, name):
    """Cycle FIELDING with one case; the logical clock is moved past
    fielding_end_date so intake lands PENDING_REVIEW."""
    ctx = setup_cycle_in_state(
        setup_program(name=name), "FIELDING", discharge_count=1)
    set_clock("2026-09-05T00:00:00Z")
    late = record_response(ctx["case_ids"][0], ctx["vendor"]["id"])
    assert late["is_late"] is True
    assert late["status"] == "PENDING_REVIEW"
    return ctx, late


class TestAdjudicatedResponseIsTerminal:
    def test_adjudicated_response_is_terminal(self, api):
        """PRD §3.5: "A `DataSteward` adjudicates a response in
        `PENDING_REVIEW` by supplying a `decision` of `INCLUDE` or `EXCLUDE`;
        the response must be `PENDING_REVIEW`
        (`ERR_RESPONSE_NOT_PENDING_REVIEW`) and the cycle must be
        `RECONCILIATION` (`ERR_CYCLE_NOT_RECONCILING`). A `decision` of
        `INCLUDE` moves the response to `INCLUDED` and increments the cycle's
        `completed_responses`; a `decision` of `EXCLUDE` moves it to
        `EXCLUDED`, leaving the counter untouched."

        Design: Corner/state_machines/adjudicated_response_is_terminal
        """
        ctx, late = _late_response_ctx(api, "P-SM4")
        get_success_data(api.close_fielding(ctx["cycle"]["id"], ADMIN))
        included = validate_success(
            api.adjudicate_response(late["id"], {"decision": "INCLUDE"},
                                    STEWARD),
            200)
        assert included["status"] == "INCLUDED"
        assert get_cycle(ctx["cycle"]["id"])["completed_responses"] == 1

        res = api.adjudicate_response(late["id"], {"decision": "EXCLUDE"},
                                      STEWARD)
        validate_error(res, ApiErrorId.ERR_RESPONSE_NOT_PENDING_REVIEW)
        assert get_response(late["id"])["status"] == "INCLUDED"
        assert get_cycle(ctx["cycle"]["id"])["completed_responses"] == 1

    def test_second_adjudicate_rejected_and_counter_unchanged(self, api):
        """PRD §3.5: "the response must be `PENDING_REVIEW`
        (`ERR_RESPONSE_NOT_PENDING_REVIEW`) and the cycle must be
        `RECONCILIATION` (`ERR_CYCLE_NOT_RECONCILING`). A `decision` of
        `INCLUDE` moves the response to `INCLUDED` and increments the cycle's
        `completed_responses`; a `decision` of `EXCLUDE` moves it to
        `EXCLUDED`, leaving the counter untouched."

        Design: Corner/state_machines/adjudicated_response_is_terminal
        """
        ctx, late = _late_response_ctx(api, "P-SM4B")
        get_success_data(api.close_fielding(ctx["cycle"]["id"], ADMIN))
        get_success_data(api.adjudicate_response(
            late["id"], {"decision": "INCLUDE"}, STEWARD))
        before = get_cycle(ctx["cycle"]["id"])["completed_responses"]

        res = api.adjudicate_response(late["id"], {"decision": "EXCLUDE"},
                                      STEWARD)
        validate_error(res, ApiErrorId.ERR_RESPONSE_NOT_PENDING_REVIEW)
        assert res.status_code == 409
        assert get_response(late["id"])["status"] == "INCLUDED"
        assert get_cycle(ctx["cycle"]["id"])["completed_responses"] == before


class TestVoidGating:
    def test_response_void_locked_after_scoring(self, api):
        """PRD §3.5: "A `DataSteward` voids a response, supplying a `reason`,
        only while the response is `ACCEPTED` (`ERR_RESPONSE_NOT_VOIDABLE`) and
        only while the response's cycle is in `FIELDING` or `RECONCILIATION`
        (`ERR_CYCLE_LOCKED`)."
        PRD §2.7: "voiding an accepted response requires `FIELDING` or
        `RECONCILIATION`."

        Design: Corner/validations/response_void_locked_after_scoring
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V22"), "FIELDING", discharge_count=1)
        response = record_response(ctx["case_ids"][0], ctx["vendor"]["id"])
        assert response["status"] == "ACCEPTED"
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(ctx["cycle"]["id"], ADMIN))
        get_success_data(api.begin_scoring(ctx["cycle"]["id"], ADMIN))
        assert get_cycle(ctx["cycle"]["id"])["status"] == "SCORING"

        res = api.void_response(response["id"], {"reason": "late fraud signal"},
                                STEWARD)
        validate_error(res, ApiErrorId.ERR_CYCLE_LOCKED)
        assert get_response(response["id"])["status"] == "ACCEPTED"
        assert get_cycle(ctx["cycle"]["id"])["scored_completed_responses"] == 1

    def test_scored_snapshot_frozen_against_void(self, api):
        """PRD §3.5: "only while the response's cycle is in `FIELDING` or
        `RECONCILIATION` (`ERR_CYCLE_LOCKED`). The response moves to `VOIDED`,
        and the cycle's `completed_responses` is recomputed downward."
        PRD §3.6: "Beginning scoring freezes the analytical snapshot"

        Design: Corner/validations/response_void_locked_after_scoring
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V22B"), "FIELDING", discharge_count=1)
        response = record_response(ctx["case_ids"][0], ctx["vendor"]["id"],
                                   score=3)
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(ctx["cycle"]["id"], ADMIN))
        get_success_data(api.begin_scoring(ctx["cycle"]["id"], ADMIN))

        res = api.void_response(response["id"], {"reason": "duplicate"},
                                STEWARD)
        validate_error(res, ApiErrorId.ERR_CYCLE_LOCKED)
        assert res.status_code == 409
        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["scored_completed_responses"] == 1
        assert get_response(response["id"])["status"] == "ACCEPTED"

    def test_void_of_pending_review_rejected(self, api):
        """PRD §3.5: "A `DataSteward` voids a response, supplying a `reason`,
        only while the response is `ACCEPTED` (`ERR_RESPONSE_NOT_VOIDABLE`)"

        Design: Corner/validations/void_of_pending_review_rejected
        """
        ctx, late = _late_response_ctx(api, "P-V27")
        # Cycle still FIELDING: the cycle-posture gate passes, so the
        # response-local ACCEPTED requirement decides.
        res = api.void_response(late["id"], {"reason": "duplicate"}, STEWARD)
        validate_error(res, ApiErrorId.ERR_RESPONSE_NOT_VOIDABLE)
        assert get_response(late["id"])["status"] == "PENDING_REVIEW"

    def test_pending_review_must_be_adjudicated_not_voided(self, api):
        """PRD §3.5: "A `DataSteward` voids a response, supplying a `reason`,
        only while the response is `ACCEPTED` (`ERR_RESPONSE_NOT_VOIDABLE`) and
        only while the response's cycle is in `FIELDING` or `RECONCILIATION`
        (`ERR_CYCLE_LOCKED`)."
        PRD §3.5: "A `DataSteward` adjudicates a response in `PENDING_REVIEW`
        by supplying a `decision` of `INCLUDE` or `EXCLUDE`"

        Design: Corner/validations/void_of_pending_review_rejected
        """
        ctx, late = _late_response_ctx(api, "P-V27B")
        res = api.void_response(late["id"], {"reason": "duplicate"}, STEWARD)
        validate_error(res, ApiErrorId.ERR_RESPONSE_NOT_VOIDABLE)
        assert res.status_code == 409
        assert get_response(late["id"])["status"] == "PENDING_REVIEW"
