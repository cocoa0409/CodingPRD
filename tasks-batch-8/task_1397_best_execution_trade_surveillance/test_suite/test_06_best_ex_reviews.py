"""Best-execution committee reviews: submit gates, voting rules, quorum
auto-approval, return-for-rework, publish gate, and the terminate-routing
cascade (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    create_review_payload,
    make_best_ex_analyst_headers,
    make_committee_member_headers,
    make_order,
    make_published_disclosure,
    make_review_approved,
    make_review_in_committee,
    make_snapshot,
    make_venue,
    set_clock,
    setup_venue_with_active_arrangement,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CA = TEST_USERS["compliance_admin_headers"]
OPS = TEST_USERS["ops_admin_headers"]


class TestReviewSubmitGates:
    def test_review_submit_requires_locked_snapshots_and_complete_decisions(self, api):
        """PRD §3.5: "Submitting the review to committee — `DRAFT` to
        `IN_COMMITTEE` — enforces three gates: `snapshot_ids` must be
        non-empty (`ERR_INVALID_REQUEST`); every referenced snapshot must be
        `LOCKED` (`ERR_SNAPSHOT_NOT_LOCKED`); and the `venue_decisions` must
        cover every venue currently `ACTIVE` exactly once — no active venue
        omitted, none duplicated (`ERR_INCOMPLETE_VENUE_DECISIONS`, HTTP 409)."

        Design: Corner/validations/review_submit_requires_locked_snapshots_and_complete_decisions
        """
        analyst = make_best_ex_analyst_headers("ba-1")
        v1 = make_venue(venue_code="NYSE", name="New York Stock Exchange")
        v2 = make_venue(venue_code="ARCA", name="NYSE Arca")
        snapshot = make_snapshot(v1["id"], variant="FAR_TOUCH")  # stays PROVISIONAL

        review = validate_success(api.create_review(create_review_payload(
            [snapshot["id"]],
            [{"venue_id": v1["id"], "determination": "CONTINUE"},
             {"venue_id": v2["id"], "determination": "MODIFY"}],
        ), analyst), expected_status=201)
        resp = api.review_transition(review["id"], {"to_status": "IN_COMMITTEE"}, analyst)
        validate_error(resp, ApiErrorId.ERR_SNAPSHOT_NOT_LOCKED)

        validate_success(api.lock_snapshot(snapshot["id"], CA))
        ok = validate_success(api.review_transition(review["id"], {"to_status": "IN_COMMITTEE"}, analyst))
        assert ok["status"] == "IN_COMMITTEE"

        # A second review whose decisions omit the ACTIVE venue ARCA.
        cm = make_committee_member_headers("cm-9")
        validate_success(api.review_transition(review["id"], {"to_status": "DRAFT"}, cm))
        review2 = validate_success(api.create_review(create_review_payload(
            [snapshot["id"]],
            [{"venue_id": v1["id"], "determination": "CONTINUE"}],
        ), analyst), expected_status=201)
        resp2 = api.review_transition(review2["id"], {"to_status": "IN_COMMITTEE"}, analyst)
        validate_error(resp2, ApiErrorId.ERR_INCOMPLETE_VENUE_DECISIONS)

    def test_review_publish_requires_published_disclosure(self, api):
        """PRD §3.5: "a PFOF disclosure for the same quarter must already
        exist in `PUBLISHED` status, otherwise the publish is rejected with
        `ERR_DISCLOSURE_NOT_PUBLISHED` (HTTP 409)."

        Design: Corner/validations/review_publish_requires_published_disclosure
        """
        ctx = make_review_approved(venue_codes=["NYSE"])
        assert ctx["review"]["status"] == "APPROVED"
        resp = api.review_transition(
            ctx["review"]["id"], {"to_status": "PUBLISHED"},
            make_best_ex_analyst_headers("ba-1"))
        validate_error(resp, ApiErrorId.ERR_DISCLOSURE_NOT_PUBLISHED)
        after = validate_success(api.get_review(ctx["review"]["id"], CA))
        assert after["status"] == "APPROVED", "rejected publish leaves the review APPROVED"


class TestVoting:
    def test_review_return_to_draft_clears_votes(self, api):
        """PRD §3.5: "A committee member may instead return the review for
        rework, moving it from `IN_COMMITTEE` back to `DRAFT`; returning
        clears `voter_user_ids`, so a resubmitted review starts its vote count
        from zero." PRD §3.5: "the third distinct qualifying vote — the
        approval quorum of three — automatically moves the review from
        `IN_COMMITTEE` to `APPROVED`".

        Design: Corner/state_machines/review_return_to_draft_clears_votes
        """
        ctx = make_review_in_committee(venue_codes=["NYSE"])
        review = ctx["review"]
        analyst = make_best_ex_analyst_headers("ba-1")
        validate_success(api.vote_review(review["id"], make_committee_member_headers("cm-1")))
        after_two = validate_success(api.vote_review(review["id"], make_committee_member_headers("cm-2")))
        assert after_two["status"] == "IN_COMMITTEE", "no auto-approval below the quorum of three"
        assert len(after_two["voter_user_ids"]) == 2

        returned = validate_success(api.review_transition(
            review["id"], {"to_status": "DRAFT"}, make_committee_member_headers("cm-9")))
        assert returned["status"] == "DRAFT"
        assert returned["voter_user_ids"] == [], "return wipes the recorded votes"

        validate_success(api.review_transition(review["id"], {"to_status": "IN_COMMITTEE"}, analyst))
        revote = validate_success(api.vote_review(review["id"], make_committee_member_headers("cm-1")))
        assert revote["voter_user_ids"] == ["cm-1"], (
            "cm-1 votes again in the new round without ERR_DUPLICATE_VOTE")

    def test_review_creator_cannot_vote_returns_403(self, api):
        """PRD §3.5: "the review's creator may never vote on their own review
        — a voter whose `X-User-ID` equals `created_by_user_id` is rejected
        with `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403)".

        Design: Corner/rbac/review_creator_cannot_vote_returns_403
        """
        ctx = make_review_in_committee(venue_codes=["NYSE"])
        resp = api.vote_review(ctx["review"]["id"], make_committee_member_headers("ba-1"))
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)

    def test_duplicate_committee_vote_rejected(self, api):
        """PRD §3.5: "each committee member votes at most once per committee
        round, a repeat being rejected with `ERR_DUPLICATE_VOTE` (HTTP 409)".

        Design: Corner/rbac/duplicate_committee_vote_rejected
        """
        ctx = make_review_in_committee(venue_codes=["NYSE"])
        cm1 = make_committee_member_headers("cm-1")
        validate_success(api.vote_review(ctx["review"]["id"], cm1))
        resp = api.vote_review(ctx["review"]["id"], cm1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOTE)

    def test_committee_member_cannot_publish_review_returns_403(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint — or, for transition endpoints, not permitted for
        the requested transition target — is rejected with `ERR_FORBIDDEN`
        (HTTP 403)." PRD §3.5: "Publishing — `APPROVED` to `PUBLISHED` — is
        performed by a `BestExAnalyst`".

        Design: Corner/rbac/committee_member_cannot_publish_review_returns_403
        """
        ctx = make_review_in_committee(venue_codes=["NYSE"])
        resp = api.review_transition(
            ctx["review"]["id"], {"to_status": "PUBLISHED"},
            make_committee_member_headers("cm-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestTerminateRoutingCascade:
    def _setup_cascade(self):
        """XATS with one EXECUTED MARKET order and one ROUTED LIMIT order, a
        LOCKED snapshot, a PUBLISHED Q3 disclosure, and a TERMINATE_ROUTING
        review voted to APPROVED (PRD §3.5)."""
        set_clock("2026-08-10T14:00:00Z")
        venue, arrangement = setup_venue_with_active_arrangement(
            venue_code="XATS", name="Xeno ATS", venue_type="ATS")
        o1 = make_order(client_ref="T1", symbol="ZETA", side="BUY", quantity=100,
                        order_type="MARKET", arrangement_id=arrangement["id"])
        set_clock("2026-08-10T15:00:00Z")
        o1 = validate_success(api_client.order_transition(o1["id"], {
            "to_status": "EXECUTED", "executed_price_cents": 10000,
            "executed_at": "2026-08-10T14:30:00Z"}, OPS))
        snapshot = make_snapshot(venue["id"], variant="FAR_TOUCH", lock=True)
        make_published_disclosure(quarter="2026-Q3", pricing_variant="MARGINAL")
        o2 = make_order(client_ref="T2", symbol="ZETA", side="BUY", quantity=50,
                        order_type="LIMIT", limit_price_cents=9900,
                        arrangement_id=arrangement["id"])

        analyst = make_best_ex_analyst_headers("ba-1")
        review = validate_success(api_client.create_review(create_review_payload(
            [snapshot["id"]],
            [{"venue_id": venue["id"], "determination": "TERMINATE_ROUTING"}],
        ), analyst), expected_status=201)
        review = validate_success(api_client.review_transition(
            review["id"], {"to_status": "IN_COMMITTEE"}, analyst))
        return venue, arrangement, o1, o2, review, analyst

    def test_review_quorum_auto_approves(self, api):
        """PRD §3.5: "the third distinct qualifying vote — the approval quorum
        of three — automatically moves the review from `IN_COMMITTEE` to
        `APPROVED` with no further action required."

        Design: Difficulty/transitive_cascade/review_publish_terminate_cascade_depth3
        """
        _v, _a, _o1, _o2, review, _analyst = self._setup_cascade()
        validate_success(api.vote_review(review["id"], make_committee_member_headers("cm-1")))
        second = validate_success(api.vote_review(review["id"], make_committee_member_headers("cm-2")))
        assert second["status"] == "IN_COMMITTEE"
        third = validate_success(api.vote_review(review["id"], make_committee_member_headers("cm-3")))
        assert third["status"] == "APPROVED", "the third distinct vote auto-approves"

    def test_review_publish_terminates_venue_cascade(self, api):
        """PRD §3.5: "Link one: every `venue_decisions` entry whose
        `determination` is `TERMINATE_ROUTING` moves that venue from `ACTIVE`
        to `SUSPENDED`. Link two: each such venue suspension suspends every
        `ACTIVE` routing arrangement bound to that venue. Link three: each
        such arrangement suspension cancels its orders still in `ROUTED`."

        Design: Difficulty/transitive_cascade/review_publish_terminate_cascade_depth3
        """
        venue, arrangement, o1, o2, review, analyst = self._setup_cascade()
        for voter in ("cm-1", "cm-2", "cm-3"):
            validate_success(api.vote_review(review["id"], make_committee_member_headers(voter)))

        published = validate_success(api.review_transition(
            review["id"], {"to_status": "PUBLISHED"}, analyst))
        assert published["status"] == "PUBLISHED"

        venue_after = validate_success(api.get_venue(venue["id"], CA))
        assert venue_after["status"] == "SUSPENDED", "link 1: venue suspended"
        arr_after = validate_success(api.get_arrangement(arrangement["id"], CA))
        assert arr_after["status"] == "SUSPENDED", "link 2: arrangement suspended by the venue"
        orders, meta = validate_paginated(api.list_arrangement_orders(arrangement["id"], CA))
        assert meta["total_count"] == 2
        by_id = {o["id"]: o for o in orders}
        assert by_id[o2["id"]]["status"] == "CANCELLED", (
            "link 3: the ROUTED limit order is cancelled by the arrangement suspension")
        assert by_id[o1["id"]]["status"] == "EXECUTED", (
            "conditional selectivity: the already-EXECUTED order is untouched")
