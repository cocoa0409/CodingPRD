"""Voting, attendance, and tally outcome computation.

PRD §3.4, §3.5, §2.9.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_resolution,
    assert_tally_conservation,
    assert_tally_shape,
    cast_vote,
    confirm_attendance,
    declare_conflict,
    get_agenda_item,
    get_application,
    get_resolution,
    make_committee_member_headers,
    resolve_agenda_item,
    seed_committee,
    setup_application_pending_review,
    setup_open_agenda_item,
    setup_resolved_initial_review,
    unique_sponsor_name,
    unique_applicant_id,
    validate_error,
)


# ===========================================================================
# Duplicate vote (PRD §3.4)
# ===========================================================================
class TestDuplicateVote:
    """PRD §3.4: 'a member may cast at most one vote per agenda item: a
    second insert from the same member with the same agenda_item_id is
    rejected with ERR_DUPLICATE_VOTE.'"""

    def test_second_vote_by_same_member_rejected(self, api):
        """PRD §3.4: 'a second insert from the same member with the
        same agenda_item_id is rejected with ERR_DUPLICATE_VOTE.'"""
        app, _ = setup_application_pending_review()
        members = seed_committee(total=9, chair_index=0)
        chair = members[0]
        meeting, item = setup_open_agenda_item(
            application=app, members=members, chair_member=chair,
        )
        # First vote OK
        cast_vote(item["id"], members[1], "APPROVE")
        # Second vote by same member -> duplicate
        res = api.cast_vote(item["id"], {"vote_mode": "APPROVE"},
                            make_committee_member_headers(members[1]["id"]))
        validate_error(res, ApiErrorId.ERR_DUPLICATE_VOTE.value)


# ===========================================================================
# Recusal beats invalid-state (PRD §2.7, §3.4)
# ===========================================================================
class TestRecusalBeatsInvalidState:
    """PRD §2.7: 'the conflict-of-interest gate runs before the state
    legality check, so a recused member who attempts to vote on a
    CLOSED agenda item receives ERR_MEMBER_RECUSED, not
    ERR_INVALID_STATE.'"""

    def test_recused_member_on_closed_agenda_item_gets_recused_error(
        self, api,
    ):
        """PRD §2.7: 'a recused member who attempts to vote on a CLOSED
        agenda item receives ERR_MEMBER_RECUSED, not ERR_INVALID_STATE.'
        Also PRD §3.4: 'the conflict gate runs before the state-
        legality check, so a recused member who tries to vote — even on
        an item that has already moved out of OPEN_FOR_VOTING —
        receives ERR_MEMBER_RECUSED rather than ERR_INVALID_STATE.'"""
        # Setup: resolve an INITIAL_REVIEW agenda item, then declare a
        # conflict for one member and have them attempt to vote.
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 6, "APPROVE_WITH_MODIFICATION": 2,
                        "REJECT": 1},
            member_count=9,
        )
        # Pick a member who already voted; declare a conflict against
        # the underlying application post-resolution.
        members = bundle["members"]
        app = bundle["application"]
        recused = members[2]
        declare_conflict(recused, app["id"])
        # Attempt to vote on the RESOLVED agenda item.
        res = api.cast_vote(
            bundle["agenda_item"]["id"], {"vote_mode": "APPROVE"},
            make_committee_member_headers(recused["id"]),
        )
        validate_error(res, ApiErrorId.ERR_MEMBER_RECUSED.value)


# ===========================================================================
# Quorum at resolve / NO_QUORUM outcome (PRD §3.5)
# ===========================================================================
class TestQuorumOutcome:
    """PRD §3.5: 'If the cast count is below the required count, two
    possibilities branch on a query parameter: with require_quorum set
    to true, the resolve is rejected with ERR_QUORUM_NOT_MET (HTTP 422)
    and the agenda item remains OPEN_FOR_VOTING; without require_quorum
    (the default, omitted, or false), the resolve succeeds with a
    NO_QUORUM outcome — a Resolution row is created whose outcome is
    NO_QUORUM, the agenda item moves to CLOSED_WITHOUT_QUORUM, and the
    parent application transitions from IN_REVIEW to DEFERRED (with no
    rectification created).'"""

    def test_no_quorum_default_resolve_creates_no_quorum_resolution(
        self, api,
    ):
        """PRD §3.5: 'without require_quorum (the default ...), the
        resolve succeeds with a NO_QUORUM outcome — a Resolution row is
        created whose outcome is NO_QUORUM, the agenda item moves to
        CLOSED_WITHOUT_QUORUM, and the parent application transitions
        from IN_REVIEW to DEFERRED (with no rectification created).'"""
        # 9 active members ⇒ quorum_required = max(5, ceil(0.67*9)) = 7.
        # Cast only 4 votes → below quorum.
        app, _ = setup_application_pending_review()
        members = seed_committee(total=9, chair_index=0)
        chair = members[0]
        meeting, item = setup_open_agenda_item(
            application=app, members=members, chair_member=chair,
        )
        for m in members[1:5]:  # 4 votes
            cast_vote(item["id"], m, "APPROVE")
        resolution = resolve_agenda_item(item["id"], chair)
        assert_resolution(resolution)
        assert resolution["outcome"] == "NO_QUORUM", (
            f"PRD §3.5: 'outcome is NO_QUORUM' when cast < quorum and "
            f"require_quorum is omitted; got {resolution['outcome']!r}"
        )
        item_after = get_agenda_item(item["id"])
        assert item_after["status"] == "CLOSED_WITHOUT_QUORUM", (
            f"PRD §3.5: 'the agenda item moves to CLOSED_WITHOUT_QUORUM'; "
            f"got {item_after['status']!r}"
        )
        app_after = get_application(app["id"])
        assert app_after["status"] == "DEFERRED", (
            f"PRD §3.5: 'parent application transitions from IN_REVIEW "
            f"to DEFERRED'; got {app_after['status']!r}"
        )

    def test_no_quorum_with_require_quorum_true_returns_error(self, api):
        """PRD §3.5: 'with require_quorum set to true, the resolve is
        rejected with ERR_QUORUM_NOT_MET (HTTP 422) and the agenda
        item remains OPEN_FOR_VOTING'."""
        from test_helpers import make_chair_headers
        app, _ = setup_application_pending_review()
        members = seed_committee(total=9, chair_index=0)
        chair = members[0]
        meeting, item = setup_open_agenda_item(
            application=app, members=members, chair_member=chair,
        )
        for m in members[1:5]:  # 4 votes < 7 quorum
            cast_vote(item["id"], m, "APPROVE")
        res = api.resolve_agenda_item(
            item["id"], make_chair_headers(chair["id"]),
            params={"require_quorum": "true"},
        )
        validate_error(res, ApiErrorId.ERR_QUORUM_NOT_MET.value)


# ===========================================================================
# Tally precedence (PRD §3.5)
# ===========================================================================
class TestTallyPrecedence:
    """PRD §3.5 vote-counting precedence:
      1. REJECT > votes_cast / 2 → REJECT
      2. APPROVE + APPROVE_WITH_MODIFICATION >= ceil(2/3 * votes_cast):
         - tie rule: AWM > APPROVE in count → APPROVE_WITH_MODIFICATION
         - equality (or APPROVE > AWM): APPROVE
      3. DEFER >= ceil(votes_cast/2) → DEFER
      4. fallback → DEFER
    """

    def test_majority_reject_yields_reject(self, api):
        """PRD §3.5: 'if the number of REJECT votes is strictly more
        than half of the votes cast, the outcome is REJECT.'"""
        bundle = setup_resolved_initial_review(
            vote_split={"REJECT": 5, "APPROVE": 1, "DEFER": 1},
            member_count=9,
        )
        assert bundle["resolution"]["outcome"] == "REJECT", (
            f"PRD §3.5: 'REJECT votes strictly more than half ... outcome "
            f"is REJECT'; got {bundle['resolution']['outcome']!r}"
        )

    def test_two_thirds_approve_yields_approve(self, api):
        """PRD §3.5: 'the sum of APPROVE and APPROVE_WITH_MODIFICATION
        votes is at least two-thirds of the votes cast (rounded up to
        the nearest whole vote — for example, with 7 cast votes the
        threshold is 5 approving votes), the outcome is one of the
        approval variants ... when the count of APPROVE_WITH_MODIFICATION
        votes is strictly greater than the count of APPROVE votes, the
        outcome is APPROVE_WITH_MODIFICATION; otherwise (including when
        the two counts are equal — equality resolves to
        APPROVE_WITH_MODIFICATION as the conservative default), the
        outcome is APPROVE.'"""
        # 7 votes cast, 5 APPROVE + 2 AWM → supermajority met,
        # APPROVE(5) > AWM(2) → APPROVE.
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        assert bundle["resolution"]["outcome"] == "APPROVE", (
            f"PRD §3.5: APPROVE(5) > AWM(2) under 2/3 supermajority → "
            f"APPROVE; got {bundle['resolution']['outcome']!r}"
        )

    def test_tally_conservation_invariant(self, api):
        """PRD §3.5: 'tally object recording per-mode counts plus
        total_votes_cast'. PRD §2.9: 'All quorum and vote tallies are
        integer-valued'. The per-mode counts must sum to
        total_votes_cast."""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 5, "APPROVE_WITH_MODIFICATION": 2},
            member_count=9,
        )
        tally = bundle["resolution"]["tally"]
        assert_tally_shape(tally)
        assert_tally_conservation(tally)


# ===========================================================================
# Resolution shape (PRD §3.5)
# ===========================================================================
class TestResolutionShape:
    """PRD §3.5: 'a server-generated document_uri whose value is the
    literal ethics-resolutions URI template formed by joining the
    resolution's id between a leading "/ethics/resolutions/" segment and
    a trailing "/document.pdf" suffix.'"""

    def test_document_uri_matches_template(self, api):
        """PRD §3.5: 'document_uri whose value is the literal ethics-
        resolutions URI template formed by joining the resolution's id
        between a leading "/ethics/resolutions/" segment and a trailing
        "/document.pdf" suffix.'"""
        bundle = setup_resolved_initial_review(
            vote_split={"APPROVE": 6, "APPROVE_WITH_MODIFICATION": 2,
                        "REJECT": 1},
            member_count=9,
        )
        r = bundle["resolution"]
        expected = f"/ethics/resolutions/{r['id']}/document.pdf"
        assert r["document_uri"] == expected, (
            f"PRD §3.5: document_uri template; expected {expected!r}, "
            f"got {r['document_uri']!r}"
        )
