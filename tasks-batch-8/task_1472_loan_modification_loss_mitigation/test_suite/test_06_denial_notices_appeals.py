"""Denial notices, appeal windows, appeal decisions, and the overturn cascade."""
import pytest

from test_helpers import (
    OPS,
    UW,
    ApiErrorId,
    decide,
    get_application,
    get_denial_notice,
    get_foreclosure_case,
    get_loan,
    get_success_data,
    make_appeal_reviewer_headers,
    make_borrower_headers,
    make_underwriter_headers,
    run_waterfall,
    set_clock,
    setup_appeal,
    setup_denial,
    validate_error,
    validate_success,
)


class TestAppealWindowAndEligibility:
    def test_appeal_window_expired_clean_trigger(self, api):
        """PRD §3.8: "Submitting after `appeal_deadline` is rejected with
        `ERR_APPEAL_WINDOW_EXPIRED`"
        PRD §3.8: "an `appeal_deadline` of `issued_at` plus fourteen days
        (inclusive — submission is accepted while now is at or before the
        deadline)".

        Design: Corner/errors/error_appeal_window_expired_clean_trigger
        """
        scenario = setup_denial(denied_at="2026-08-10T00:00:00Z")
        notice = scenario["notice"]
        assert notice["status"] == "ISSUED"
        assert notice["appeal_eligible"] is True
        set_clock("2026-08-25T00:00:00Z")  # past the 2026-08-24 deadline
        res = api.submit_appeal(
            notice["id"],
            {"grounds": "too late"},
            make_borrower_headers(scenario["borrower"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED, expected_status=422)
        assert get_denial_notice(notice["id"])["status"] == "ISSUED"
        appeals = get_success_data(api.list_notice_appeals(notice["id"], UW))
        assert appeals == []

    def test_appeal_not_available_inside_90_day_rule(self, api):
        """PRD §3.8: "A notice is appeal-eligible when the loan has no
        foreclosure case in `SALE_SCHEDULED` or `SALE_HOLD`, **or** when the
        application's `completed_at` date is at least ninety days before the
        scheduled `sale_date`. A complete application received fewer than ninety
        days before a scheduled sale is not appealable."
        PRD §3.8: "submitting when `appeal_eligible` is false is rejected with
        `ERR_APPEAL_NOT_AVAILABLE`."

        Design: Corner/calculations/appeal_not_available_inside_90_day_rule
        """
        # Sale 2026-09-20 scheduled before the application; package completed
        # 2026-08-05, which is fewer than 90 days before the sale (cutoff
        # 2026-06-22) -> appeal_eligible false.
        scenario = setup_denial(
            sale_date="2026-09-20",
            complete_at="2026-08-05T00:00:00Z",
            denied_at="2026-08-10T00:00:00Z",
        )
        notice = scenario["notice"]
        assert notice["appeal_eligible"] is False
        set_clock("2026-08-12T00:00:00Z")  # inside the 14-day window
        res = api.submit_appeal(
            notice["id"],
            {"grounds": "please review"},
            make_borrower_headers(scenario["borrower"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_APPEAL_NOT_AVAILABLE, expected_status=422)


class TestNoticeStateGates:
    def test_appeal_after_affirm_rejected_not_appealable(self, api):
        """PRD §3.8: "The notice must be `ISSUED` — an appeal against an
        already-`APPEALED` notice is rejected with `ERR_NOTICE_ALREADY_APPEALED`,
        and against a `SUPERSEDED` or `AFFIRMED` notice with
        `ERR_NOTICE_NOT_APPEALABLE_STATE`."

        Design: Corner/errors/error_notice_not_appealable_after_affirm
        """
        scenario = setup_denial(denied_at="2026-08-10T00:00:00Z")
        scenario = setup_appeal(scenario, appeal_at="2026-08-12T00:00:00Z")
        decide(scenario, "AFFIRMED", reviewer_user_id="rev_1")
        set_clock("2026-08-13T00:00:00Z")
        res = api.submit_appeal(
            scenario["notice"]["id"],
            {"grounds": "second after affirm"},
            make_borrower_headers(scenario["borrower"]["id"]),
        )
        validate_error(
            res, ApiErrorId.ERR_NOTICE_NOT_APPEALABLE_STATE, expected_status=409
        )
        assert (
            get_application(scenario["application"]["id"])["status"] == "CLOSED_DENIED"
        )

    def test_double_decision_rejected(self, api):
        """PRD §3.8: "Deciding an appeal not in `SUBMITTED` is rejected with
        `ERR_APPEAL_ALREADY_DECIDED`."

        Design: Corner/state_machines/appeal_double_decision_rejected
        """
        scenario = setup_denial(denied_at="2026-08-10T00:00:00Z")
        scenario = setup_appeal(scenario, appeal_at="2026-08-12T00:00:00Z")
        decide(scenario, "AFFIRMED", reviewer_user_id="rev_1")
        res = api.decide_appeal(
            scenario["appeal"]["id"],
            {"outcome": "OVERTURNED"},
            make_appeal_reviewer_headers("rev_2"),
        )
        validate_error(res, ApiErrorId.ERR_APPEAL_ALREADY_DECIDED, expected_status=409)
        appeals = get_success_data(api.list_notice_appeals(scenario["notice"]["id"], UW))
        assert appeals[0]["status"] == "AFFIRMED"
        assert get_denial_notice(scenario["notice"]["id"])["status"] == "AFFIRMED"
        assert (
            get_application(scenario["application"]["id"])["status"] == "CLOSED_DENIED"
        )


class TestAppealPriorityPair:
    def test_state_error_beats_window_expiry(self, api):
        """PRD §2.7: "When multiple validation rules could fire on a single
        request, the server evaluates them in this fixed priority order,
        returning the first failure:" — "7. **State preconditions**" precede
        "9. **Temporal gates** — appeal window, appeal eligibility, sale minimum
        notice, rescission window: `ERR_APPEAL_WINDOW_EXPIRED`, ...".

        Design: Difficulty/priority_pair_validation_conflict/appeal_state_error_beats_window_expiry
        """
        scenario = setup_denial(denied_at="2026-08-10T00:00:00Z")
        scenario = setup_appeal(scenario, appeal_at="2026-08-12T00:00:00Z")
        # Notice is APPEALED (state violation) AND the window closed 2026-08-24.
        set_clock("2026-08-26T00:00:00Z")
        res = api.submit_appeal(
            scenario["notice"]["id"],
            {"grounds": "second appeal, window expired"},
            make_borrower_headers(scenario["borrower"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOTICE_ALREADY_APPEALED, expected_status=409)

    def test_state_priority_leaves_notice_untouched(self, api):
        """PRD §2.7: "7. **State preconditions** — each entity's state machine
        guards ... `ERR_NOTICE_ALREADY_APPEALED` ..." and the fixed order returns
        "the first failure", so the temporal gate never runs and nothing mutates.

        Design: Difficulty/priority_pair_validation_conflict/appeal_state_error_beats_window_expiry
        """
        scenario = setup_denial(denied_at="2026-08-10T00:00:00Z")
        scenario = setup_appeal(scenario, appeal_at="2026-08-12T00:00:00Z")
        set_clock("2026-08-26T00:00:00Z")
        res = api.submit_appeal(
            scenario["notice"]["id"],
            {"grounds": "second appeal, window expired"},
            make_borrower_headers(scenario["borrower"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOTICE_ALREADY_APPEALED, expected_status=409)
        assert get_denial_notice(scenario["notice"]["id"])["status"] == "APPEALED"
        appeals = get_success_data(
            api.list_notice_appeals(scenario["notice"]["id"], UW)
        )
        assert len(appeals) == 1, "the rejected second appeal must not persist"


class TestOverturnCascade:
    def _overturned(self, api):
        """Sale scheduled pre-application (2026-12-01), denial 2026-08-10,
        appeal 2026-08-12, OVERTURNED decision at 2026-08-14."""
        scenario = setup_denial(
            sale_date="2026-12-01",
            complete_at="2026-08-05T00:00:00Z",
            denied_at="2026-08-10T00:00:00Z",
        )
        scenario = setup_appeal(
            scenario, appeal_at="2026-08-12T00:00:00Z",
            grounds="stated income was verifiable",
        )
        set_clock("2026-08-14T00:00:00Z")
        appeal = decide(scenario, "OVERTURNED", reviewer_user_id="rev_1")
        scenario["appeal"] = appeal
        return scenario

    def test_overturn_supersedes_notice_and_reopens_application(self, api):
        """PRD §3.8: "**OVERTURNED** — a three-level cascade fires. L1: the
        notice moves from `APPEALED` to `SUPERSEDED` (the overturn itself). L2:
        caused by the notice's supersession, the application moves from
        `APPEAL_REVIEW` back to `COMPLETE_PACKAGE` — re-evaluation is required,
        and the application re-enters the blocking state."

        Design: Difficulty/transitive_cascade/appeal_overturn_three_level_cascade
        """
        scenario = self._overturned(api)
        assert scenario["appeal"]["status"] == "OVERTURNED"
        assert get_denial_notice(scenario["notice"]["id"])["status"] == "SUPERSEDED"
        assert (
            get_application(scenario["application"]["id"])["status"]
            == "COMPLETE_PACKAGE"
        )

    def test_overturn_moves_scheduled_sale_to_hold(self, api):
        """PRD §3.8: "L3: caused by the application re-entering
        `COMPLETE_PACKAGE`, the loan's active foreclosure case (if in
        `SALE_SCHEDULED`) moves to `SALE_HOLD` (see §3.9)."
        PRD §3.9: "A scheduled sale can be displaced automatically: when an
        appeal overturn returns an application to `COMPLETE_PACKAGE` (§3.8, L2),
        the active case moves from `SALE_SCHEDULED` to `SALE_HOLD` and the mirror
        follows."

        Design: Difficulty/transitive_cascade/appeal_overturn_three_level_cascade
        """
        scenario = self._overturned(api)
        case = get_foreclosure_case(scenario["case"]["id"])
        assert case["status"] == "SALE_HOLD"
        assert get_loan(scenario["loan"]["id"])["foreclosure_status"] == "SALE_HOLD"


class TestAppealRbac:
    def test_underwriter_cannot_decide_appeal(self, api):
        """PRD §3.8: "Deciding an appeal is the `AppealReviewer`'s exclusive
        operation"
        PRD §2.1: "A request whose role is authenticated but is not in the
        endpoint's authorized role list is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/underwriter_role_cannot_decide_appeal
        """
        scenario = setup_denial(denied_at="2026-08-10T00:00:00Z")
        scenario = setup_appeal(scenario, appeal_at="2026-08-12T00:00:00Z")
        res = api.decide_appeal(
            scenario["appeal"]["id"],
            {"outcome": "OVERTURNED"},
            make_underwriter_headers("uw_9"),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        appeals = get_success_data(api.list_notice_appeals(scenario["notice"]["id"], UW))
        assert appeals[0]["status"] == "SUBMITTED"

    def test_same_identity_as_denying_underwriter_rejected(self, api):
        """PRD §3.8: "Deciding an appeal is the `AppealReviewer`'s exclusive
        operation, with a hard segregation-of-duties rule: the caller's
        `X-User-ID` must differ from the notice's `underwriter_user_id`,
        otherwise the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/appeal_reviewer_same_identity_as_underwriter_rejected
        """
        scenario = setup_denial(
            denied_at="2026-08-10T00:00:00Z", underwriter_user_id="uw_1"
        )
        scenario = setup_appeal(scenario, appeal_at="2026-08-12T00:00:00Z")
        # Same X-User-ID as the denying underwriter, correct role.
        res = api.decide_appeal(
            scenario["appeal"]["id"],
            {"outcome": "OVERTURNED"},
            make_appeal_reviewer_headers("uw_1"),
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        # A different reviewer identity is not blocked.
        decided = validate_success(
            api.decide_appeal(
                scenario["appeal"]["id"],
                {"outcome": "OVERTURNED"},
                make_appeal_reviewer_headers("rev_1"),
            ),
            200,
        )
        assert decided["status"] == "OVERTURNED"
