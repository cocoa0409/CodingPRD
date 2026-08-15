"""Hardship exception requests: committee quorum, guards, bypass, expiry."""
from test_helpers import (
    ApiErrorId,
    admin_headers,
    api_client,
    as_insider,
    assert_same_instant,
    complete_attestation_for,
    create_approved_exception,
    create_current_person,
    create_officer,
    create_person,
    create_quarterly_window,
    create_submitted_exception,
    get_success_data,
    run_sweep,
    set_logical_clock,
    validate_error,
    validate_success,
    vote_exception,
)


class TestCommitteeQuorum:
    def test_first_approve_vote_leaves_request_submitted(self, api):
        """PRD §3.5: "After each vote is tallied, if `votes_for` has reached two the
        request is decided `APPROVED`; otherwise, if `votes_against` has reached two
        it is decided `DENIED` — exactly two approvals decide, and exactly two
        rejections decide. A request that has reached neither threshold remains
        `SUBMITTED`."

        Design: Difficulty/boundary_precision_check/quorum_exactly_two_votes_decides
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        requester = create_person("Requester K", "requester_k@x.com")
        m1 = create_person("Member One", "member1@x.com", designation="DIRECTOR",
                           department="Board")
        exc = create_submitted_exception(requester, quantity=1000,
                                         hardship_reason="medical hardship")
        after = validate_success(vote_exception(m1, exc["id"], "APPROVE"))
        assert after["status"] == "SUBMITTED"
        assert after["votes_for"] == 1

    def test_second_approve_vote_reaches_quorum_and_decides(self, api):
        """PRD §3.5: "After each vote is tallied, if `votes_for` has reached two the
        request is decided `APPROVED`; otherwise, if `votes_against` has reached two
        it is decided `DENIED` — exactly two approvals decide, and exactly two
        rejections decide. A request that has reached neither threshold remains
        `SUBMITTED`. Deciding stamps `decided_at`."

        Design: Difficulty/boundary_precision_check/quorum_exactly_two_votes_decides
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        requester = create_person("Requester K2", "requester_k2@x.com")
        m1 = create_person("Member One", "member1b@x.com", designation="DIRECTOR",
                           department="Board")
        m2 = create_person("Member Two", "member2b@x.com", designation="DIRECTOR",
                           department="Board")
        exc = create_submitted_exception(requester, quantity=1000,
                                         hardship_reason="medical hardship")
        get_success_data(vote_exception(m1, exc["id"], "APPROVE"))
        after = validate_success(vote_exception(m2, exc["id"], "APPROVE"))
        assert after["status"] == "APPROVED"
        assert after["votes_for"] == 2
        assert after["decided_at"] is not None

    def test_duplicate_committee_vote_rejected(self, api):
        """PRD §3.5: "Three guards apply, in order: voting on a request no longer
        `SUBMITTED` is `ERR_INVALID_STATE`; a member voting on their own hardship
        request violates segregation of duties (`ERR_SELF_ACTION_FORBIDDEN`); and a
        member whose id already appears in `voter_ids` is rejected with
        `ERR_DUPLICATE_VOTE` (409)."

        Design: Corner/validations/exception_duplicate_vote_rejected
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        requester = create_person("Requester D", "requester_d@x.com")
        member = create_person("Member D", "member_d@x.com", designation="DIRECTOR",
                               department="Board")
        exc = create_submitted_exception(requester, quantity=100)
        get_success_data(vote_exception(member, exc["id"], "APPROVE"))

        resp = vote_exception(member, exc["id"], "REJECT")
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOTE)
        fresh = get_success_data(api.get_exception_request(exc["id"], admin_headers()))
        assert fresh["votes_for"] == 1
        assert fresh["votes_against"] == 0
        assert fresh["status"] == "SUBMITTED"


class TestExceptionWithdrawAndExpiry:
    def test_exception_withdrawn_by_owner(self, api):
        """PRD §3.5: "The petitioner may also withdraw their own request from
        `SUBMITTED`, moving it to `WITHDRAWN`."

        Design: Corner/state_machines/exception_withdraw_by_owner
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        requester = create_person("Requester W", "requester_w@x.com")
        exc = create_submitted_exception(requester, quantity=100,
                                         hardship_reason="relocation")
        data = validate_success(
            api.withdraw_exception_request(exc["id"], as_insider(requester))
        )
        assert data["status"] == "WITHDRAWN"
        assert data["votes_for"] == 0
        assert data["votes_against"] == 0

    def test_undecided_exception_expires_after_decision_window(self, api):
        """PRD §3.5: "the system immediately computes `decision_window_end` as five
        days after creation: the committee's clock is already ticking." PRD §3.5:
        "If the decision window closes first — the sweep finds a still-`SUBMITTED`
        request whose `decision_window_end` is earlier than now — the request moves
        to `EXPIRED`."

        Design: Corner/cross_cutting_layers/exception_expires_after_decision_window
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        requester = create_person("Requester X5", "requester_x5@x.com")
        member = create_person("Member X5", "member_x5@x.com", designation="DIRECTOR",
                               department="Board")
        officer = create_officer("officer_x5@x.com")
        exc = create_submitted_exception(requester, quantity=100)
        get_success_data(vote_exception(member, exc["id"], "APPROVE"))

        fresh = get_success_data(api.get_exception_request(exc["id"], admin_headers()))
        assert_same_instant(
            fresh["decision_window_end"], "2026-08-06T00:00:00Z", "decision_window_end"
        )

        set_logical_clock("2026-08-07T00:00:00Z")
        counts = run_sweep(officer)
        assert counts["exceptions_expired"] == 1
        expired = get_success_data(api.get_exception_request(exc["id"], admin_headers()))
        assert expired["status"] == "EXPIRED"


class TestExceptionBypass:
    def test_request_quantity_above_exception_rejected(self, api):
        """PRD §3.4: "When an exception is cited, the request's `quantity` must not
        exceed the exception's covered `quantity`, or submission fails with
        `ERR_QUANTITY_EXCEEDS_APPROVED`."

        Design: Corner/validations/exception_linked_quantity_exceeds_rejected
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        requester = create_current_person("Requester Q", "requester_q@x.com")
        m1 = create_person("Member Q1", "member_q1@x.com", designation="DIRECTOR",
                           department="Board")
        m2 = create_person("Member Q2", "member_q2@x.com", designation="DIRECTOR",
                           department="Board")
        exc = create_approved_exception(requester, m1, m2, ticker="ACME", quantity=100)

        resp = api.create_preclearance_request(
            {
                "covered_person_id": requester["id"],
                "security_ticker": "ACME",
                "trade_side": "SELL",
                "quantity": 150,
                "proposed_trade_date": "2026-08-20T00:00:00Z",
                "exception_id": exc["id"],
            },
            as_insider(requester),
        )
        validate_error(resp, ApiErrorId.ERR_QUANTITY_EXCEEDS_APPROVED)

    def test_approved_exception_bypasses_blackout_screen(self, api):
        """PRD §3.5: "Cited through `exception_id` on a preclearance request, it
        bypasses the blackout check for its ticker up to its covered `quantity`, both
        at submission and at decision time, and it protects the resulting approval
        from being voided when a younger window later activates."

        Design: Corner/validations/blackout_bypass_with_approved_exception
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        requester = create_current_person("Requester B", "requester_b@x.com")
        m1 = create_person("Member B1", "member_b1@x.com", designation="DIRECTOR",
                           department="Board")
        m2 = create_person("Member B2", "member_b2@x.com", designation="DIRECTOR",
                           department="Board")
        officer = create_officer("officer_v3@x.com")
        exc = create_approved_exception(requester, m1, m2, ticker="ACME", quantity=1000,
                                        hardship_reason="medical")
        create_quarterly_window(officer, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")

        resp = api.create_preclearance_request(
            {
                "covered_person_id": requester["id"],
                "security_ticker": "ACME",
                "trade_side": "SELL",
                "quantity": 500,
                "proposed_trade_date": "2026-08-10T00:00:00Z",
                "exception_id": exc["id"],
            },
            as_insider(requester),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SUBMITTED"
        assert data["exception_id"] == exc["id"]
