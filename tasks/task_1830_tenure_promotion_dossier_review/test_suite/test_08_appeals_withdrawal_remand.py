"""Appeals, the remand cascade, and case withdrawal teardown (PRD §3.8, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    cast_ballot,
    file_appeal,
    file_clock_extension,
    list_case_rounds,
    make_candidate_headers,
    open_round,
    read_candidate,
    read_case,
    read_clock_extension,
    read_round,
    set_logical_clock,
    setup_department_stage_case,
    setup_notified_case,
    validate_error,
    validate_success,
)

PO_HEADERS = TEST_USERS["provost_creator_headers"]
APPEAL_OFFICER = TEST_USERS["appeal_officer_headers"]
READER_HEADERS = TEST_USERS["reader_headers"]


def test_appeal_lapse_and_close_gates(api):
    """PRD §3.7: "Closing requires the logical clock to be strictly past the
    `appeal_filing_deadline` — an attempt at or before the deadline is rejected
    with `ERR_APPEAL_WINDOW_OPEN`".
    PRD §3.8: "requires the filing to fall on or before the case's
    `appeal_filing_deadline`, with a filing exactly at the deadline permitted —
    a late filing is rejected with `ERR_APPEAL_WINDOW_LAPSED`".

    Design: Corner/validations/appeal_lapse_and_close_gates
    """
    # Decided (DENY) and notified at 2026-08-01: appeal deadline 2026-08-31.
    ctx = setup_notified_case("E9314", decision="DENY", email_prefix="ag")
    case_id = ctx["case"]["id"]
    candidate_id = ctx["candidate"]["id"]

    # Close while the appeal window is still open.
    set_logical_clock("2026-08-15T00:00:00Z")
    err_close = api.close_case(case_id, PO_HEADERS)
    validate_error(err_close, ApiErrorId.ERR_APPEAL_WINDOW_OPEN)

    # Appeal filed one day past the 30-day deadline.
    set_logical_clock("2026-09-01T00:00:00Z")
    err_appeal = api.create_appeal(
        {"case_id": case_id, "grounds": "CAPRICIOUS_EVALUATION"},
        make_candidate_headers(candidate_id),
    )
    validate_error(err_appeal, ApiErrorId.ERR_APPEAL_WINDOW_LAPSED)

    # The same day, closure succeeds: the window lapsed and no appeal is open.
    closed = validate_success(api.close_case(case_id, PO_HEADERS))
    assert closed["stage"] == "CLOSED"
    assert read_candidate(candidate_id)["status"] == "NOT_RENEWED", (
        "The DENY cascade survives the failed close/appeal attempts"
    )


def test_appeal_pending_blocks_close_until_withdrawn(api):
    """PRD §3.7: "requires that no appeal of the case stands in `FILED` or
    `UNDER_REVIEW` (`ERR_APPEAL_PENDING`)".
    PRD §3.8: "The candidate may also withdraw a `FILED` appeal — an
    ownership-checked action moving it to `WITHDRAWN`."

    Design: Corner/validations/appeal_pending_blocks_close_until_withdrawn
    """
    ctx = setup_notified_case("E9315", decision="DENY", email_prefix="ap")
    case_id = ctx["case"]["id"]
    candidate_id = ctx["candidate"]["id"]

    set_logical_clock("2026-08-05T00:00:00Z")
    appeal = file_appeal(case_id, candidate_id, grounds="DISCRIMINATION")
    assert appeal["status"] == "FILED"

    # Window lapsed (deadline 2026-08-31) but the appeal still stands.
    set_logical_clock("2026-09-01T00:00:00Z")
    err_close = api.close_case(case_id, PO_HEADERS)
    validate_error(err_close, ApiErrorId.ERR_APPEAL_PENDING)

    withdrawn = validate_success(
        api.withdraw_appeal(appeal["id"], make_candidate_headers(candidate_id))
    )
    assert withdrawn["status"] == "WITHDRAWN"

    closed = validate_success(api.close_case(case_id, PO_HEADERS))
    assert closed["stage"] == "CLOSED"


class TestAppealRemandCascade:
    def _resolve_remanded(self, api, employee_id):
        ctx = setup_notified_case(employee_id, decision="DENY", email_prefix="w")
        case_id = ctx["case"]["id"]
        candidate_id = ctx["candidate"]["id"]
        appeal = file_appeal(case_id, candidate_id, grounds="PROCEDURAL_ERROR")
        validate_success(api.begin_review_appeal(appeal["id"], APPEAL_OFFICER))
        resolved = validate_success(
            api.resolve_appeal(
                appeal["id"],
                {"resolution": "REMANDED",
                 "resolution_text": "Dept vote miscounted; redo."},
                APPEAL_OFFICER,
            )
        )
        return ctx, appeal, resolved

    def test_remand_cascade_voids_decision_and_reactivates_candidate(self, api):
        """PRD §3.8: "The remand cascade reopens the entire committee ladder.
        The `RECORDED` decision flips to `VOIDED`. The candidate's `status`
        returns to `ACTIVE` from either `TENURED` or `NOT_RENEWED`."
        PRD §3.8: "The case's `stage` moves from `DECIDED` or `NOTIFIED` back to
        `DEPT_COMMITTEE` and its `version` increments by one."

        Design: Difficulty/transitive_cascade/appeal_remand_four_entity_cascade
        """
        ctx, appeal, resolved = self._resolve_remanded(api, "E900")
        assert resolved["status"] == "REMANDED"

        case_after = read_case(ctx["case"]["id"])
        assert case_after["stage"] == "DEPT_COMMITTEE"

        decision_after = validate_success(
            api.get_decision(ctx["decision"]["id"], READER_HEADERS)
        )
        assert decision_after["status"] == "VOIDED"

        candidate_after = read_candidate(ctx["candidate"]["id"])
        assert candidate_after["status"] == "ACTIVE"

    def test_remand_creates_fresh_department_round_and_clears_score(self, api):
        """PRD §3.8: "The case's `recommendation_score` is cleared to null, and
        when the remand fires from `NOTIFIED` the `appeal_filing_deadline` is
        cleared as well."
        PRD §3.8: "the system creates a fresh department round in `SCHEDULED`
        status".
        PRD §2.3: "Unless otherwise specified, all list endpoints return
        resources sorted by their creation timestamp in ascending order."

        Design: Difficulty/transitive_cascade/appeal_remand_four_entity_cascade
        """
        ctx, _appeal, resolved = self._resolve_remanded(api, "E901")
        assert resolved["status"] == "REMANDED"

        case_after = read_case(ctx["case"]["id"])
        assert case_after["recommendation_score"] is None
        assert case_after["appeal_filing_deadline"] is None

        dept_rounds = list_case_rounds(ctx["case"]["id"], level="DEPARTMENT")
        assert len(dept_rounds) == 2, (
            f"The pre-remand round plus the fresh remand round, got {len(dept_rounds)}"
        )
        assert dept_rounds[-1]["status"] == "SCHEDULED", (
            "The fresh remand round (latest by created_at) is SCHEDULED"
        )


class TestCaseWithdrawalTeardownCascade:
    def _setup_open_round_with_extension(self, employee_id):
        ctx = setup_department_stage_case(employee_id, member_count=3,
                                          email_prefix="z")
        case_id = ctx["case"]["id"]
        candidate_id = ctx["candidate"]["id"]
        round_id = ctx["round"]["id"]
        chair_id = ctx["committee_ctx"]["chair"]["id"]
        members = ctx["committee_ctx"]["members"]
        open_round(round_id, chair_id)
        vote1 = cast_ballot(round_id, members[0]["id"], "YES")
        vote2 = cast_ballot(round_id, members[1]["id"], "NO")
        # A pending stop-the-clock request on the case (pre-DECIDED stage).
        ext = file_clock_extension(
            case_id, candidate_id, "2023-01-01", "2023-04-01",
            reason="PARENTAL_LEAVE",
        )
        return ctx, round_id, vote1, vote2, ext

    def test_withdrawal_cancels_open_round_and_retracts_votes(self, api):
        """PRD §3.9: "From the three committee stages, every round in
        `SCHEDULED`, `VOTING_OPEN`, or `TALLYING` flips to the terminal
        `CANCELLED` status, and for rounds cancelled from `VOTING_OPEN` or
        `TALLYING` all of the round's `CAST` votes are retracted by the system
        with `retracted_at` stamped."

        Design: Difficulty/transitive_cascade/case_withdrawal_round_vote_teardown_cascade
        """
        ctx, round_id, vote1, vote2, _ext = (
            self._setup_open_round_with_extension("E1000")
        )
        case_id = ctx["case"]["id"]
        candidate_id = ctx["candidate"]["id"]

        withdrawn = validate_success(
            api.withdraw_case(case_id, make_candidate_headers(candidate_id))
        )
        assert withdrawn["stage"] == "WITHDRAWN"

        round_after = read_round(round_id)
        assert round_after["status"] == "CANCELLED"

        for vote in (vote1, vote2):
            vote_after = validate_success(
                api.get_vote(vote["id"], READER_HEADERS)
            )
            assert vote_after["status"] == "RETRACTED"
            assert vote_after["retracted_at"] is not None, (
                "System retraction stamps retracted_at"
            )

    def test_withdrawal_cancels_pending_extension_and_marks_candidate(self, api):
        """PRD §3.9: "Every withdrawal moves the case to the terminal
        `WITHDRAWN` stage, moves the candidate's `status` to `WITHDRAWN`,
        cancels the case's still-`PENDING` clock-extension requests, and
        increments the case's `version` by one."
        PRD §3.3: "When a case is withdrawn, its still-`PENDING` requests are
        cancelled automatically, moving to `CANCELLED`".

        Design: Difficulty/transitive_cascade/case_withdrawal_round_vote_teardown_cascade
        """
        ctx, _round_id, _v1, _v2, ext = (
            self._setup_open_round_with_extension("E1001")
        )
        case_id = ctx["case"]["id"]
        candidate_id = ctx["candidate"]["id"]

        validate_success(
            api.withdraw_case(case_id, make_candidate_headers(candidate_id))
        )

        ext_after = read_clock_extension(ext["id"])
        assert ext_after["status"] == "CANCELLED"

        candidate_after = read_candidate(candidate_id)
        assert candidate_after["status"] == "WITHDRAWN"
