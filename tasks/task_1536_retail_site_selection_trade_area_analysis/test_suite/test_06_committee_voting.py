"""Committee voting: quorum and percentage math, ballot safety checks, OCC on
the review tally, ratification authority, and the reject-revise loop
(PRD §3.6, §3.2)."""
from test_helpers import (
    ApiErrorId,
    assert_committee_review,
    assert_vote,
    cast_ballot,
    create_committee_member_payload,
    create_committee_roster,
    create_forecast_locked_site,
    create_in_committee_site,
    create_qualified_market,
    create_stores,
    create_vote_payload,
    get_success_data,
    make_committee_chair_headers,
    make_committee_member_headers,
    run_ballot_plan,
    submit_to_committee,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
MANAGER = TEST_USERS["manager_headers"]


class TestQuorumBoundary:
    def test_eligible_count_and_quorum_pinned_at_creation(self, api):
        """PRD §3.6: "The eligible voter pool — the count of `ACTIVE` members
        other than the sponsor — must contain at least one member, else
        `ERR_NO_ELIGIBLE_VOTERS`; this count is pinned on the review as
        `eligible_member_count` at creation, along with `quorum_count`, the
        smallest integer greater than or equal to two-thirds of the eligible
        count."

        Design: Difficulty/boundary_precision_check/vote_quorum_exactly_met_approves
        """
        ctx = create_in_committee_site(num_voters=5)
        review = ctx["review"]
        assert_committee_review(review)
        # Sponsor + chair + 5 voters; the sponsor is excluded from the pool.
        assert review["eligible_member_count"] == 6
        assert review["quorum_count"] == 4, "ceil(6 * 2/3)"
        assert review["review_status"] == "OPEN"

    def test_quorum_exactly_met_approves(self, api):
        """PRD §3.6: "The outcome is `APPROVE` only when both conditions hold:
        the approve tally multiplied by 100 is strictly greater than 60 times
        the sum of approve and reject tallies — an exact sixty percent is not
        enough and yields `REJECT` — and the sum of approve and reject tallies
        is at least the pinned `quorum_count`."
        PRD §3.6: "Abstentions are excluded from both the percentage
        denominator and the quorum count, and if no non-abstain ballots exist
        at all, the outcome is `REJECT`."

        Design: Difficulty/boundary_precision_check/vote_quorum_exactly_met_approves
        """
        ctx = create_in_committee_site(num_voters=5)
        roster = ctx["roster"]
        voters = [v["id"] for v in roster["voters"]]
        chair = roster["chair"]["id"]
        # A/A/A/R/Ab/Ab: turnout 6 == E; A+R == 4 == quorum (inclusive);
        # 3*100 > 60*4 (300 > 240).
        plan = [
            (voters[0], "APPROVE", False),
            (voters[1], "APPROVE", False),
            (voters[2], "APPROVE", False),
            (voters[3], "REJECT", False),
            (voters[4], "ABSTAIN", False),
            (chair, "ABSTAIN", True),
        ]
        for resp in run_ballot_plan(ctx["review"]["id"], plan):
            validate_success(resp, expected_status=201)
        review = validate_success(
            api.get_committee_review(ctx["review"]["id"], MANAGER)
        )
        assert review["review_status"] == "DECIDED"
        assert review["decided_outcome"] == "APPROVE"
        assert review["approve_votes"] == 3
        assert review["reject_votes"] == 1
        assert review["abstain_votes"] == 2


class TestExactlySixtyPercentRejects:
    def _decided_reject_review(self, api):
        """E=5 review decided at exactly 60% approval (A/A/A/R/R)."""
        ctx = create_in_committee_site(num_voters=4)
        roster = ctx["roster"]
        voters = [v["id"] for v in roster["voters"]]
        plan = [
            (voters[0], "APPROVE", False),
            (voters[1], "APPROVE", False),
            (voters[2], "APPROVE", False),
            (voters[3], "REJECT", False),
            (roster["chair"]["id"], "REJECT", True),
        ]
        for resp in run_ballot_plan(ctx["review"]["id"], plan):
            validate_success(resp, expected_status=201)
        return ctx

    def test_exactly_sixty_percent_is_reject(self, api):
        """PRD §3.6: "The outcome is `APPROVE` only when both conditions hold:
        the approve tally multiplied by 100 is strictly greater than 60 times
        the sum of approve and reject tallies — an exact sixty percent is not
        enough and yields `REJECT` — and the sum of approve and reject tallies
        is at least the pinned `quorum_count`."
        PRD §3.6: "a rejection moves the site to `REJECTED`, from which §3.2's
        revise path remains available."

        Design: Difficulty/non_linear_state_machine/site_rejected_revision_loop
        """
        ctx = self._decided_reject_review(api)
        review = validate_success(
            api.get_committee_review(ctx["review"]["id"], MANAGER)
        )
        # 3*100 not > 60*5 (300 > 300 is false) -> REJECT.
        assert review["decided_outcome"] == "REJECT"
        resp = api.ratify_review(
            ctx["review"]["id"],
            make_committee_chair_headers(ctx["roster"]["chair"]["id"]),
        )
        ratified = validate_success(resp)
        assert ratified["review_status"] == "RATIFIED"
        site = validate_success(api.get_site(ctx["site"]["id"], MANAGER))
        assert site["site_status"] == "REJECTED"

    def test_revise_returns_site_to_draft_and_supersedes_artifacts(self, api):
        """PRD §3.2: "Revising a `REJECTED` site returns it to `DRAFT` and
        retires its analytical work product in one cascade: every trade-area
        model of the site in `LOCKED` or `DRAFT` becomes `SUPERSEDED`, every
        submitted site visit becomes `SUPERSEDED`, and every sales forecast in
        `DRAFT` or `COMMITTEE_LOCKED` becomes `SUPERSEDED`."

        Design: Difficulty/non_linear_state_machine/site_rejected_revision_loop
        """
        ctx = self._decided_reject_review(api)
        resp = api.ratify_review(
            ctx["review"]["id"],
            make_committee_chair_headers(ctx["roster"]["chair"]["id"]),
        )
        validate_success(resp)
        revised = validate_success(api.revise_site(ctx["site"]["id"], MANAGER))
        assert revised["site_status"] == "DRAFT"
        model = validate_success(
            api.get_trade_area_model(ctx["model"]["id"], ANALYST)
        )
        assert model["model_status"] == "SUPERSEDED"
        visit = validate_success(api.get_site_visit(ctx["visit"]["id"], ANALYST))
        assert visit["visit_status"] == "SUPERSEDED"
        forecast = validate_success(
            api.get_sales_forecast(ctx["forecast"]["id"], ANALYST)
        )
        assert forecast["forecast_status"] == "SUPERSEDED"
        market = validate_success(api.get_market(ctx["market"]["id"], ADMIN))
        assert market["committed_capex_cents"] == 0, (
            "a rejected site never committed capital"
        )


class TestBallotSafetyAndOcc:
    def test_vote_cast_updates_tally_and_version(self, api):
        """PRD §3.6: "Each recorded ballot increments the matching tally and
        advances the review's `version` by one."
        PRD §3.6: "The review decides itself at full turnout: when the sum of
        approve, reject, and abstain ballots reaches the pinned
        `eligible_member_count`, the review moves from `OPEN` to `DECIDED` and
        its `decided_outcome` is fixed."

        Design: Corner/state_machines/vote_cast_updates_tally_and_version
        """
        ctx = create_in_committee_site(num_voters=1)
        review = ctx["review"]
        assert review["version"] == 1
        resp = cast_ballot(review["id"], ctx["roster"]["voters"][0]["id"],
                           "APPROVE")
        validate_success(resp, expected_status=201)
        after = validate_success(api.get_committee_review(review["id"], MANAGER))
        assert after["approve_votes"] == 1
        assert after["version"] == 2, "one ballot advances version by exactly 1"
        assert after["review_status"] == "OPEN", "cast 1 < eligible 2"

    def test_occ_stale_vote_rejected(self, api):
        """PRD §2.6: "A request to `POST /api/committee-reviews/{id}/votes`
        must carry `expected_review_version`, equal to the current `version` of
        the committee review as the member last observed it. Every recorded
        ballot advances the review's tally and its `version`; a cast against a
        stale tally is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_vote_rejected
        """
        ctx = create_in_committee_site(num_voters=1)
        review = ctx["review"]
        stale_version = review["version"]
        first = api.cast_vote(
            review["id"],
            create_vote_payload(ballot="APPROVE",
                                expected_review_version=stale_version),
            make_committee_member_headers(ctx["roster"]["voters"][0]["id"]),
        )
        validate_success(first, expected_status=201)
        second = api.cast_vote(
            review["id"],
            create_vote_payload(ballot="REJECT",
                                expected_review_version=stale_version),
            make_committee_chair_headers(ctx["roster"]["chair"]["id"]),
        )
        validate_error(second, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_committee_review(review["id"], MANAGER))
        assert after["approve_votes"] == 1
        assert after["reject_votes"] == 0

    def test_vote_record_is_immutable(self, api):
        """PRD §2.4: "A vote is the sole exception: it carries only `id` and
        `created_at`; both `updated_at` and `version` are absent from the vote
        resource."
        PRD §3.6: "the casting member's identity is the `X-User-ID`, recorded
        as the vote's `member_id`, and the vote's `review_id` is taken from the
        path."

        Design: Corner/entities/vote_record_is_immutable
        """
        ctx = create_in_committee_site(num_voters=1)
        voter_id = ctx["roster"]["voters"][0]["id"]
        resp = cast_ballot(ctx["review"]["id"], voter_id, "APPROVE")
        vote = validate_success(resp, expected_status=201)
        assert_vote(vote)
        assert vote["member_id"] == voter_id
        assert vote["review_id"] == ctx["review"]["id"]
        assert vote["ballot"] == "APPROVE"
        reloaded = validate_success(api.get_vote(vote["id"], MANAGER))
        assert_vote(reloaded)

    def test_error_segregation_sponsor_cannot_vote(self, api):
        """PRD §3.6: "Three safety checks precede recording: the sponsor of the
        review may not vote on it (`ERR_SEGREGATION_OF_DUTIES`); the casting
        identity must reference an `ACTIVE` committee member
        (`ERR_VOTER_INELIGIBLE`); and each member casts at most one ballot per
        review (`ERR_DUPLICATE_VOTE`)."

        Design: Corner/errors/error_segregation_sponsor_cannot_vote
        """
        ctx = create_in_committee_site(num_voters=1)
        resp = cast_ballot(ctx["review"]["id"], ctx["roster"]["sponsor"]["id"],
                           "APPROVE")
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        review = validate_success(
            api.get_committee_review(ctx["review"]["id"], MANAGER)
        )
        assert (review["approve_votes"], review["reject_votes"],
                review["abstain_votes"]) == (0, 0, 0)

    def test_deactivated_member_cannot_vote(self, api):
        """PRD §3.6: "Deactivating a member moves them to `INACTIVE`; a
        deactivated member is immediately ineligible to vote or ratify, but
        ballots they have already cast remain counted."

        Design: Corner/state_machines/deactivated_member_cannot_vote
        """
        ctx = create_in_committee_site(num_voters=1)
        voter_id = ctx["roster"]["voters"][0]["id"]
        get_success_data(api.deactivate_committee_member(voter_id, ADMIN))
        resp = cast_ballot(ctx["review"]["id"], voter_id, "APPROVE")
        validate_error(resp, ApiErrorId.ERR_VOTER_INELIGIBLE)
        review = validate_success(
            api.get_committee_review(ctx["review"]["id"], MANAGER)
        )
        assert (review["approve_votes"], review["reject_votes"],
                review["abstain_votes"]) == (0, 0, 0)
        assert review["review_status"] == "OPEN"

    def test_error_duplicate_vote(self, api):
        """PRD §3.6: "each member casts at most one ballot per review
        (`ERR_DUPLICATE_VOTE`)"

        Design: Corner/errors/error_duplicate_vote
        """
        ctx = create_in_committee_site(num_voters=1)
        voter_id = ctx["roster"]["voters"][0]["id"]
        first = cast_ballot(ctx["review"]["id"], voter_id, "APPROVE")
        validate_success(first, expected_status=201)
        # Second ballot carries the CURRENT version, so the OCC gate passes and
        # the one-ballot-per-member constraint is what fires.
        second = cast_ballot(ctx["review"]["id"], voter_id, "REJECT")
        validate_error(second, ApiErrorId.ERR_DUPLICATE_VOTE)

    def test_vote_after_decided_rejected(self, api):
        """PRD §3.6: "Only an `OPEN` review accepts ballots."
        PRD §2.7: "a live resource in the wrong state yields
        `ERR_INVALID_STATE` (409)"

        Design: Corner/state_machines/vote_after_decided_rejected
        """
        ctx = create_in_committee_site(num_voters=1)
        roster = ctx["roster"]
        first = cast_ballot(ctx["review"]["id"], roster["chair"]["id"],
                            "APPROVE", as_chair=True)
        validate_success(first, expected_status=201)
        second = cast_ballot(ctx["review"]["id"], roster["voters"][0]["id"],
                             "REJECT")
        validate_success(second, expected_status=201)
        decided = validate_success(
            api.get_committee_review(ctx["review"]["id"], MANAGER)
        )
        assert decided["review_status"] == "DECIDED"
        extra = cast_ballot(ctx["review"]["id"], roster["voters"][0]["id"],
                            "APPROVE")
        validate_error(extra, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(
            api.get_committee_review(ctx["review"]["id"], MANAGER)
        )
        assert (after["approve_votes"], after["reject_votes"],
                after["abstain_votes"]) == (1, 1, 0)


class TestRatificationAuthority:
    def test_ratify_open_review_rejected(self, api):
        """PRD §3.6: "Ratifying a `DECIDED` review moves it to the terminal
        `RATIFIED` state and applies the outcome"
        PRD §2.7: "a live resource in the wrong state yields
        `ERR_INVALID_STATE` (409)"

        Design: Corner/state_machines/ratify_open_review_rejected
        """
        ctx = create_in_committee_site(num_voters=1)
        resp = api.ratify_review(
            ctx["review"]["id"],
            make_committee_chair_headers(ctx["roster"]["chair"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        review = validate_success(
            api.get_committee_review(ctx["review"]["id"], MANAGER)
        )
        assert review["review_status"] == "OPEN"
        assert review["decided_outcome"] is None

    def test_error_not_chair_ratify(self, api):
        """PRD §3.6: "Ratification belongs to the chair alone, acting as
        `CommitteeChair` with an `ACTIVE`, `is_chair` member identity, else
        `ERR_NOT_CHAIR`; a chair who is also the deal's sponsor is barred by
        segregation of duties (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/errors/error_not_chair_ratify
        """
        ctx = create_in_committee_site(num_voters=1)
        roster = ctx["roster"]
        first = cast_ballot(ctx["review"]["id"], roster["chair"]["id"],
                            "APPROVE", as_chair=True)
        validate_success(first, expected_status=201)
        second = cast_ballot(ctx["review"]["id"], roster["voters"][0]["id"],
                             "APPROVE")
        validate_success(second, expected_status=201)
        review = validate_success(
            api.get_committee_review(ctx["review"]["id"], MANAGER)
        )
        assert review["review_status"] == "DECIDED"
        # The plain voter presents CommitteeChair but holds is_chair=false.
        resp = api.ratify_review(
            ctx["review"]["id"],
            make_committee_chair_headers(roster["voters"][0]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_CHAIR)
        after = validate_success(
            api.get_committee_review(ctx["review"]["id"], MANAGER)
        )
        assert after["review_status"] == "DECIDED"

    def test_error_segregation_sponsor_chair_cannot_ratify(self, api):
        """PRD §3.6: "Ratification belongs to the chair alone, acting as
        `CommitteeChair` with an `ACTIVE`, `is_chair` member identity, else
        `ERR_NOT_CHAIR`; a chair who is also the deal's sponsor is barred by
        segregation of duties (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/errors/error_segregation_sponsor_chair_cannot_ratify
        """
        market = create_qualified_market(name="Metro E13")
        create_stores(market["id"])
        ctx = create_forecast_locked_site(market["id"])
        # Sponsor holds the chair; one plain voter is the only eligible member.
        roster = create_committee_roster(num_voters=1, sponsor_is_chair=True)
        review = submit_to_committee(
            ctx["site"]["id"], ctx["forecast"]["id"], roster["sponsor"]["id"],
        )
        assert review["eligible_member_count"] == 1
        cast = cast_ballot(review["id"], roster["voters"][0]["id"], "APPROVE")
        validate_success(cast, expected_status=201)
        decided = validate_success(api.get_committee_review(review["id"], MANAGER))
        assert decided["review_status"] == "DECIDED"
        # The sponsor passes the is_chair check but is barred by segregation.
        resp = api.ratify_review(
            review["id"], make_committee_chair_headers(roster["sponsor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = validate_success(api.get_committee_review(review["id"], MANAGER))
        assert after["review_status"] == "DECIDED"

    def test_analyst_cannot_ratify(self, api):
        """PRD §4: the `POST /api/committee-reviews/{id}/ratify` row authorizes
        only "CommitteeChair".
        PRD §2.1: "If the role is declared but not listed among the roles
        authorized for the endpoint, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/analyst_cannot_ratify
        """
        ctx = create_in_committee_site(num_voters=0)
        cast = cast_ballot(ctx["review"]["id"], ctx["roster"]["chair"]["id"],
                           "APPROVE", as_chair=True)
        validate_success(cast, expected_status=201)
        review = validate_success(
            api.get_committee_review(ctx["review"]["id"], MANAGER)
        )
        assert review["review_status"] == "DECIDED"
        resp = api.ratify_review(ctx["review"]["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        after = validate_success(
            api.get_committee_review(ctx["review"]["id"], MANAGER)
        )
        assert after["review_status"] == "DECIDED"


class TestRosterConstraints:
    def test_error_chair_conflict(self, api):
        """PRD §3.6: "At most one `ACTIVE` member may hold the chair — creating
        a second chair is rejected with `ERR_CHAIR_CONFLICT`."

        Design: Corner/errors/error_chair_conflict
        """
        first = api.create_committee_member(
            create_committee_member_payload(display_name="Chair One",
                                            is_chair=True), ADMIN,
        )
        validate_success(first, expected_status=201)
        second = api.create_committee_member(
            create_committee_member_payload(display_name="Chair Two",
                                            is_chair=True), ADMIN,
        )
        validate_error(second, ApiErrorId.ERR_CHAIR_CONFLICT)
