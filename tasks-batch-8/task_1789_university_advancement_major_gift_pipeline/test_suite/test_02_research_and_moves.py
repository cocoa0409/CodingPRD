"""Research assessment lifecycle, capacity rating, supersession, and the
prospect's parallel research/moves dimensions."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_gift_officer_headers,
    create_prospect, create_fundraiser, create_assessment_payload,
    rate_prospect, assign_prospect, move_prospect, get_prospect,
    setup_rated_assigned_prospect, create_proposal_for,
)

RES = TEST_USERS["researcher_headers"]
DIR = TEST_USERS["director_headers"]
DIR2 = TEST_USERS["director2_headers"]


class TestAssessmentReview:
    def test_assessment_approval_supersedes_prior_approved(self, api):
        """PRD §3.2: "Approval also supersedes the prior rating: any other
        assessment of the same prospect still in `APPROVED` status moves to
        `SUPERSEDED`."

        Design: Corner/state_machines/assessment_approval_supersedes_prior_approved
        """
        p = create_prospect()
        a1 = rate_prospect(p["id"], assessed_capacity_cents=30000000)
        # Re-screen and approve a second, larger assessment.
        a2 = rate_prospect(p["id"], assessed_capacity_cents=200000000,
                           engagement_score=90, philanthropy_score=90, recency_score=90)

        rows, meta = validate_paginated(api.list_prospect_assessments(p["id"], RES))
        by_id = {r["id"]: r for r in rows}
        assert by_id[a1["id"]]["status"] == "SUPERSEDED"
        assert by_id[a2["id"]]["status"] == "APPROVED"

        p_after = validate_success(api.get_prospect(p["id"], RES))
        assert p_after["capacity_band"] == "B"
        assert p_after["rated_assessment_id"] == a2["id"]

    def test_assessment_review_of_decided_assessment_rejected(self, api):
        """PRD §3.2: "Two guards precede every review: the assessment must still
        be `SUBMITTED` (otherwise `ERR_ASSESSMENT_NOT_REVIEWABLE`), and the
        reviewer's `X-User-ID` must differ from the assessment's `created_by`
        (otherwise `ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/state_machines/assessment_review_of_decided_assessment_rejected
        """
        p = create_prospect()
        a1 = rate_prospect(p["id"])
        # Reviewer dir-2 differs from creator res-1, so only the state rule can fire.
        resp = api.review_assessment(a1["id"], {"decision": "REJECT"}, DIR2)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_REVIEWABLE)

        rows, _ = validate_paginated(api.list_prospect_assessments(p["id"], RES))
        assert rows[0]["status"] == "APPROVED"


class TestCapacityRating:
    def test_capacity_rating_multipliers_and_band_boundaries(self, api):
        """PRD §3.2: "The raw `assessed_capacity_cents` is multiplied by the
        evidence multiplier for the assessment's `evidence_tier` — 0.6 for
        `SELF_REPORTED`, 0.8 for `PUBLIC_RECORD`, and 1.0 for
        `VERIFIED_DOCUMENT` — and the product is rounded down to a whole cent to
        yield `adjusted_capacity_cents`."
        PRD §3.2: "The capacity band follows from the adjusted amount using
        inclusive lower bounds: band `A` when the adjusted capacity is at least
        $10,000,000 (1000000000 cents), otherwise band `B` when at least
        $1,000,000 (100000000 cents), otherwise band `C` when at least $250,000
        (25000000 cents), otherwise band `D` when at least $50,000 (5000000
        cents), and otherwise band `E`."
        PRD §3.2: "The affinity score is a weighted blend — half of
        `engagement_score`, three-tenths of `philanthropy_score`, and one-fifth
        of `recency_score`, summed and rounded half up to a whole integer between
        0 and 100 — recorded as `affinity_score_result`."

        Design: Corner/calculations/capacity_rating_multipliers_and_band_boundaries
        """
        # PUBLIC_RECORD 30000000 -> adjusted 24000000 -> band D; affinity 73.
        p1 = create_prospect(full_name="P1", contact_email="p1@x.com")
        a1 = rate_prospect(p1["id"], assessed_capacity_cents=30000000,
                           evidence_tier="PUBLIC_RECORD")
        assert a1["adjusted_capacity_cents"] == 24000000  # floor(30000000 * 0.8)
        assert a1["capacity_band_result"] == "D"  # 24000000 < BAND_C_MIN
        assert a1["affinity_score_result"] == 73  # round_half_up(40 + 21 + 12)

        # VERIFIED 100000000 -> exactly BAND_B_MIN qualifies as B (inclusive).
        p2 = create_prospect(full_name="P2", contact_email="p2@x.com")
        a2 = rate_prospect(p2["id"], assessed_capacity_cents=100000000,
                           engagement_score=50, philanthropy_score=50, recency_score=50)
        assert a2["capacity_band_result"] == "B"

        # VERIFIED 99999999 -> one cent below B, so band C.
        p3 = create_prospect(full_name="P3", contact_email="p3@x.com")
        a3 = rate_prospect(p3["id"], assessed_capacity_cents=99999999,
                           engagement_score=50, philanthropy_score=50, recency_score=50)
        assert a3["capacity_band_result"] == "C"


class TestMovesMachine:
    def _assigned_prospect(self):
        f = create_fundraiser()
        p = create_prospect()
        assign_prospect(f["id"], p["id"])
        return f, p

    def test_moves_qualification_to_negotiation_rejected(self, api):
        """PRD §3.3: "The pipeline is deliberately cyclic. From any of
        `SOLICITATION`, `NEGOTIATION`, or `STEWARDSHIP`, an officer may pull the
        prospect back to `CULTIVATION` — the recultivation loop — and from
        `CULTIVATION` back to `QUALIFICATION`; any other stage pairing is an
        illegal jump and draws `ERR_INVALID_MOVES_TRANSITION`."

        Design: Corner/state_machines/moves_qualification_to_negotiation_rejected
        """
        f, p = self._assigned_prospect()
        officer = make_gift_officer_headers(f["id"])
        resp = api.move_prospect(p["id"], {"target_stage": "NEGOTIATION"}, officer)
        validate_error(resp, ApiErrorId.ERR_INVALID_MOVES_TRANSITION)
        assert get_prospect(p["id"])["moves_stage"] == "QUALIFICATION"

    def test_moves_to_stewardship_directly_rejected(self, api):
        """PRD §3.3: "One stage is system-reserved: `STEWARDSHIP` is reached only
        as a side effect of executing a gift agreement (§3.5) from `CULTIVATION`,
        `SOLICITATION`, or `NEGOTIATION`, and a direct API move naming
        `STEWARDSHIP` as the target is rejected with
        `ERR_INVALID_MOVES_TRANSITION`."

        Design: Corner/state_machines/moves_to_stewardship_directly_rejected
        """
        f, p = self._assigned_prospect()
        move_prospect(p["id"], f["id"], "CULTIVATION")
        officer = make_gift_officer_headers(f["id"])
        resp = api.move_prospect(p["id"], {"target_stage": "STEWARDSHIP"}, officer)
        validate_error(resp, ApiErrorId.ERR_INVALID_MOVES_TRANSITION)
        assert get_prospect(p["id"])["moves_stage"] == "CULTIVATION"

    def test_moves_closed_lost_terminal_lockdown(self, api):
        """PRD §3.3: "Finally, from any stage other than `CLOSED_LOST` an officer
        may close the book by moving the prospect to `CLOSED_LOST`; a prospect
        already in `CLOSED_LOST` rejects further moves with
        `ERR_INVALID_MOVES_TRANSITION`."

        Design: Corner/state_machines/moves_closed_lost_terminal_lockdown
        """
        f, p = self._assigned_prospect()
        move_prospect(p["id"], f["id"], "CULTIVATION")
        move_prospect(p["id"], f["id"], "CLOSED_LOST")
        officer = make_gift_officer_headers(f["id"])
        resp = api.move_prospect(p["id"], {"target_stage": "CULTIVATION"}, officer)
        validate_error(resp, ApiErrorId.ERR_INVALID_MOVES_TRANSITION)
        assert get_prospect(p["id"])["moves_stage"] == "CLOSED_LOST"


class TestProspectParallelDimensions:
    """Queue A: non_linear_state_machine / prospect_parallel_research_moves_dimensions."""

    def test_re_screen_keeps_moves_stage_and_prior_band(self, api):
        """PRD §3.2: "filing one against a `RATED` prospect re-opens screening
        (`RATED` back to `IN_SCREENING`), and in that cyclic case the prospect's
        existing `capacity_band`, `affinity_score`, `rated_assessment_id`, and
        `rated_adjusted_capacity_cents` remain in force from the prior rating
        until a new approval replaces them."

        Design: Difficulty/non_linear_state_machine/prospect_parallel_research_moves_dimensions
        """
        f, p, _asg = setup_rated_assigned_prospect(move_to="CULTIVATION")
        assert p["capacity_band"] == "C"

        # Re-screen: research dimension cycles, moves dimension untouched.
        resp = api.create_assessment(
            p["id"], create_assessment_payload(
                assessed_capacity_cents=200000000, engagement_score=90,
                philanthropy_score=85, recency_score=80),
            RES,
        )
        a2 = validate_success(resp, expected_status=201)

        mid = validate_success(api.get_prospect(p["id"], RES))
        assert mid["research_status"] == "IN_SCREENING"
        assert mid["moves_stage"] == "CULTIVATION"
        assert mid["capacity_band"] == "C"  # prior rating retained

        review = api.review_assessment(a2["id"], {"decision": "APPROVE"}, DIR)
        validate_success(review)
        end = validate_success(api.get_prospect(p["id"], RES))
        assert end["research_status"] == "RATED"
        assert end["capacity_band"] == "B"  # 200000000 -> band B
        assert end["moves_stage"] == "CULTIVATION"

    def test_re_screen_supersedes_prior_approved_assessment(self, api):
        """PRD §3.2: "Approval also supersedes the prior rating: any other
        assessment of the same prospect still in `APPROVED` status moves to
        `SUPERSEDED`."
        PRD §3.2: "filing one against a `RATED` prospect re-opens screening
        (`RATED` back to `IN_SCREENING`), and in that cyclic case the prospect's
        existing `capacity_band`, `affinity_score`, `rated_assessment_id`, and
        `rated_adjusted_capacity_cents` remain in force from the prior rating
        until a new approval replaces them."

        Design: Difficulty/non_linear_state_machine/prospect_parallel_research_moves_dimensions
        """
        f, p, _asg = setup_rated_assigned_prospect(move_to="CULTIVATION")
        rows, _ = validate_paginated(api.list_prospect_assessments(p["id"], RES))
        a1_id = rows[0]["id"]
        assert rows[0]["status"] == "APPROVED"

        resp = api.create_assessment(
            p["id"], create_assessment_payload(assessed_capacity_cents=200000000),
            RES,
        )
        a2 = validate_success(resp, expected_status=201)
        validate_success(api.review_assessment(a2["id"], {"decision": "APPROVE"}, DIR))

        rows, _ = validate_paginated(api.list_prospect_assessments(p["id"], RES))
        by_id = {r["id"]: r for r in rows}
        assert by_id[a1_id]["status"] == "SUPERSEDED"
        assert by_id[a2["id"]]["status"] == "APPROVED"
