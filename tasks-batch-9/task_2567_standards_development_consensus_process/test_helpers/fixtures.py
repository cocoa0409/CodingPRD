"""
Composite state builders for the standards-development consensus API.

The harness restarts the server before every test, so each test starts against an
empty store and an unchanged logical clock. Everything here therefore builds its
state from scratch through published endpoints only — there is no seeding.

The Scenario object below carries the participants, the committee, its seats and
the work items a test has built so far, and exposes one method per step of the
standards process so a test can say "carry this draft to consensus" in a line.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_STARTUP_UTC
from .test_users import (
    APPEALS_BOARD_HEADERS,
    STAFF_HEADERS,
    make_chair_headers,
    make_member_headers,
    make_proposer_headers,
    make_public_commenter_headers,
)

# The standing cast. Three interest categories carry a committee into BALANCED;
# the two extra PRODUCERs let a test tip dominance; Zoe never holds a seat.
CORE_PARTICIPANTS = {
    "p1": dict(
        full_name="Ada Producer",
        organization="Acme Steel",
        interest_category="PRODUCER",
        employer_affiliation_code="ACME",
    ),
    "p2": dict(
        full_name="Ben User",
        organization="City Water",
        interest_category="USER",
        employer_affiliation_code="CITYW",
    ),
    "p3": dict(
        full_name="Cleo General",
        organization="Safety League",
        interest_category="GENERAL_INTEREST",
        employer_affiliation_code="SAFEL",
    ),
}

EXTRA_PARTICIPANTS = {
    "p4": dict(
        full_name="Dov Producer",
        organization="Axle Forge",
        interest_category="PRODUCER",
        employer_affiliation_code="AXLE",
    ),
    "p5": dict(
        full_name="Eve Producer",
        organization="Boltco",
        interest_category="PRODUCER",
        employer_affiliation_code="BOLTCO",
    ),
    "p6": dict(
        full_name="Zoe Outsider",
        organization="Unaffiliated Consultancy",
        interest_category="ACADEMIC",
        employer_affiliation_code="ZOEC",
    ),
}


class Scenario:
    """Mutable bundle of everything a test has built, with one method per step."""

    def __init__(self, api: ApiClient):
        self.api = api
        self.participants: Dict[str, Dict[str, Any]] = {}
        self.memberships: Dict[str, Dict[str, Any]] = {}
        self.committee_id: Optional[str] = None
        self.work_item_id: Optional[str] = None
        self.draft_id: Optional[str] = None
        self.ballot_id: Optional[str] = None
        self.public_review_id: Optional[str] = None
        self.comment_id: Optional[str] = None
        self.votes: Dict[str, Dict[str, Any]] = {}
        self.work_item_ids: List[str] = []
        self.draft_ids: List[str] = []
        self.ballot_ids: List[str] = []
        self.appeal_id: Optional[str] = None
        self.disclosure_id: Optional[str] = None
        self.maintenance_item_id: Optional[str] = None
        self.clock = CLOCK_STARTUP_UTC

    # ------------------------------------------------------------------ identity
    def pid(self, key: str) -> str:
        """Participant id for a cast member key such as "p1"."""
        return self.participants[key]["id"]

    def mid(self, key: str) -> str:
        """Membership id for a seat key such as "m1"."""
        return self.memberships[key]["id"]

    @property
    def staff(self) -> dict:
        return STAFF_HEADERS

    @property
    def appeals_board(self) -> dict:
        return APPEALS_BOARD_HEADERS

    @property
    def chair(self) -> dict:
        """Headers for the chair, carrying the chair's own participant id."""
        return make_chair_headers(self.pid("p1"))

    def member(self, key: str) -> dict:
        """Headers for a seated participant acting as CommitteeMember."""
        return make_member_headers(self.pid(key))

    def proposer(self, key: str) -> dict:
        """Headers for a participant acting as Proposer."""
        return make_proposer_headers(self.pid(key))

    def commenter(self, key: str) -> dict:
        """Headers for a participant acting as PublicCommenter."""
        return make_public_commenter_headers(self.pid(key))

    # ------------------------------------------------------------ registry steps
    def register(self, key: str, **overrides) -> Dict[str, Any]:
        """Register one participant from the standing cast (or an override of it)."""
        spec = dict(CORE_PARTICIPANTS.get(key) or EXTRA_PARTICIPANTS[key])
        spec.update(overrides)
        response = self.api.create_participant(f.participant_payload(**spec), self.staff)
        data = validate_success(response, 201)
        self.participants[key] = data
        return data

    def register_core(self) -> Dict[str, Dict[str, Any]]:
        """Register the three participants that make a committee balanced."""
        for key in CORE_PARTICIPANTS:
            self.register(key)
        return self.participants

    def register_extras(self, *keys: str) -> Dict[str, Dict[str, Any]]:
        """Register any of the extra cast members by key."""
        for key in keys or tuple(EXTRA_PARTICIPANTS):
            self.register(key)
        return self.participants

    # ----------------------------------------------------------- committee steps
    def create_committee(self, chair_key: str = "p1", **overrides) -> Dict[str, Any]:
        """Form a committee chaired by the given participant; status FORMING."""
        payload = f.committee_payload(self.pid(chair_key), **overrides)
        data = validate_success(self.api.create_committee(payload, self.staff), 201)
        self.committee_id = data["id"]
        return data

    def appoint(self, participant_key: str, seat_key: str, **overrides) -> Dict[str, Any]:
        """Appoint a participant to a seat on the committee."""
        payload = f.membership_payload(self.pid(participant_key), **overrides)
        data = validate_success(
            self.api.create_membership(self.committee_id, payload, self.staff), 201
        )
        self.memberships[seat_key] = data
        return data

    def activate_committee(self) -> Dict[str, Any]:
        """Activate the committee; requires a balanced voting roster."""
        return validate_success(
            self.api.activate_committee(self.committee_id, self.staff), 200
        )

    def patch_membership(self, seat_key: str, **fields) -> Dict[str, Any]:
        """Suspend, restore or re-enfranchise a seat."""
        payload = f.membership_patch_payload(**fields)
        data = validate_success(
            self.api.update_membership(self.mid(seat_key), payload, self.staff), 200
        )
        self.memberships[seat_key] = data
        return data

    def get_committee(self) -> Dict[str, Any]:
        """Re-read the committee, including its derived balance fields."""
        return validate_success(
            self.api.get_committee(self.committee_id, self.staff), 200
        )

    def get_membership(self, seat_key: str) -> Dict[str, Any]:
        return validate_success(
            self.api.get_membership(self.mid(seat_key), self.staff), 200
        )

    # ----------------------------------------------------------- work item steps
    def propose_work_item(self, proposer_key: str = "p1", **overrides) -> Dict[str, Any]:
        """Submit a work item proposal in the proposer's own name."""
        payload = f.work_item_payload(self.pid(proposer_key), **overrides)
        data = validate_success(
            self.api.create_work_item(payload, self.proposer(proposer_key)), 201
        )
        self.work_item_id = data["id"]
        self.work_item_ids.append(data["id"])
        return data

    def approve_scope(self, work_item_id: Optional[str] = None, **overrides) -> Dict[str, Any]:
        """Approve a scope onto the committee, which opens development."""
        payload = f.approve_scope_payload(
            sponsoring_committee_id=self.committee_id, **overrides
        )
        return validate_success(
            self.api.approve_scope(work_item_id or self.work_item_id, payload, self.staff),
            200,
        )

    def add_draft(self, work_item_id: Optional[str] = None, **overrides) -> Dict[str, Any]:
        """Issue a draft revision on a work item, as the chair."""
        payload = f.draft_payload(**overrides)
        data = validate_success(
            self.api.create_draft(
                work_item_id or self.work_item_id, payload, self.chair
            ),
            201,
        )
        self.draft_id = data["id"]
        self.draft_ids.append(data["id"])
        return data

    def get_work_item(self, work_item_id: Optional[str] = None) -> Dict[str, Any]:
        return validate_success(
            self.api.get_work_item(work_item_id or self.work_item_id, self.staff), 200
        )

    def get_draft(self, draft_id: Optional[str] = None) -> Dict[str, Any]:
        return validate_success(
            self.api.get_draft(draft_id or self.draft_id, self.staff), 200
        )

    def publish(self, work_item_id: Optional[str] = None) -> Dict[str, Any]:
        return validate_success(
            self.api.publish_work_item(work_item_id or self.work_item_id, self.staff), 200
        )

    # -------------------------------------------------------------- ballot steps
    def open_ballot(
        self,
        draft_id: Optional[str] = None,
        ballot_kind: str = "SUBCOMMITTEE",
        opens_at: str = "2026-08-01T00:00:00Z",
        closes_at: str = "2026-08-15T00:00:00Z",
        **overrides,
    ) -> Dict[str, Any]:
        """Open a ballot on a draft, as the chair."""
        payload = f.ballot_payload(
            draft_id or self.draft_id,
            self.committee_id,
            ballot_kind=ballot_kind,
            opens_at=opens_at,
            closes_at=closes_at,
            **overrides,
        )
        data = validate_success(self.api.create_ballot(payload, self.chair), 201)
        self.ballot_id = data["id"]
        self.ballot_ids.append(data["id"])
        return data

    def cast(
        self,
        seat_key: str,
        position: str = "AFFIRMATIVE",
        ballot_id: Optional[str] = None,
        vote_key: Optional[str] = None,
        **overrides,
    ) -> Dict[str, Any]:
        """
        Cast one seat's vote. The seat's own occupant votes: the chair's seat votes
        as CommitteeChair, every other seat as CommitteeMember.
        """
        participant_key = self._participant_for_seat(seat_key)
        headers = (
            self.chair if participant_key == "p1" else self.member(participant_key)
        )
        payload = f.vote_payload(self.mid(seat_key), position=position, **overrides)
        data = validate_success(
            self.api.cast_vote(ballot_id or self.ballot_id, payload, headers), 201
        )
        self.votes[vote_key or seat_key] = data
        return data

    def cast_negative(
        self,
        seat_key: str,
        comment_text: str = "Clause 12 torque ceiling is unsafe",
        clause_reference: str = "12",
        ballot_id: Optional[str] = None,
        vote_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Cast a negative with the accompanying comment the PRD requires."""
        return self.cast(
            seat_key,
            position="NEGATIVE",
            ballot_id=ballot_id,
            vote_key=vote_key,
            comment_text=comment_text,
            clause_reference=clause_reference,
        )

    def close_ballot(self, ballot_id: Optional[str] = None) -> Dict[str, Any]:
        """Close a ballot, as the chair, and evaluate consensus."""
        return validate_success(
            self.api.close_ballot(ballot_id or self.ballot_id, self.chair), 200
        )

    def get_ballot(self, ballot_id: Optional[str] = None) -> Dict[str, Any]:
        return validate_success(
            self.api.get_ballot(ballot_id or self.ballot_id, self.staff), 200
        )

    def get_vote(self, vote_key: str) -> Dict[str, Any]:
        return validate_success(
            self.api.get_vote(self.votes[vote_key]["id"], self.staff), 200
        )

    def adjudicate(
        self,
        vote_key: str,
        resolution: str = "NON_PERSUASIVE",
        headers: Optional[dict] = None,
        **overrides,
    ):
        """
        Adjudicate a pending negative. The chair rules a negative persuasive or
        non-persuasive; a withdrawal by the voter must be sent by the voter, so
        callers pass that seat's own headers.
        """
        payload = f.adjudication_payload(resolution=resolution, **overrides)
        return validate_success(
            self.api.adjudicate_vote(
                self.votes[vote_key]["id"], payload, headers or self.chair
            ),
            200,
        )

    def change_vote(
        self, vote_key: str, position: str, headers: Optional[dict] = None, **overrides
    ) -> Dict[str, Any]:
        """Revise one's own vote to a different position while the ballot is open."""
        payload = f.vote_patch_payload(position=position, **overrides)
        return self._patch_vote(vote_key, payload, headers)

    def withdraw_vote(
        self, vote_key: str, headers: Optional[dict] = None
    ) -> Dict[str, Any]:
        """Retract one's own vote, returning the seat to not_returned_count."""
        return self._patch_vote(vote_key, f.vote_patch_payload(status="WITHDRAWN"), headers)

    def _patch_vote(
        self, vote_key: str, payload: Dict[str, Any], headers: Optional[dict]
    ) -> Dict[str, Any]:
        vote = self.votes[vote_key]
        if headers is None:
            seat_participant = self._participant_by_id(vote["membership_id"])
            headers = (
                self.chair if seat_participant == "p1" else self.member(seat_participant)
            )
        data = validate_success(
            self.api.update_vote(vote["id"], payload, headers), 200
        )
        self.votes[vote_key] = data
        return data

    def _participant_by_id(self, membership_id: str) -> str:
        """Which cast member holds the seat with this membership id."""
        for seat_key, seat in self.memberships.items():
            if seat["id"] == membership_id:
                return self._participant_for_seat(seat_key)
        raise AssertionError(f"No known seat carries membership {membership_id}")

    def _participant_for_seat(self, seat_key: str) -> str:
        """Which cast member sits in a given seat."""
        seat = self.memberships[seat_key]
        for key, participant in self.participants.items():
            if participant["id"] == seat["participant_id"]:
                return key
        raise AssertionError(f"No registered participant occupies seat {seat_key}")

    # ------------------------------------------------------- public review steps
    def announce_public_review(
        self,
        draft_id: Optional[str] = None,
        start_date: str = "2026-08-01",
        end_date: str = "2026-09-14",
        expected_draft_version: Optional[int] = None,
        **overrides,
    ) -> Dict[str, Any]:
        """Announce a public review, pinning the draft version the PRD requires."""
        target = draft_id or self.draft_id
        version = (
            expected_draft_version
            if expected_draft_version is not None
            else self.get_draft(target)["version"]
        )
        payload = f.public_review_payload(
            target,
            version,
            start_date=start_date,
            end_date=end_date,
            **overrides,
        )
        data = validate_success(self.api.create_public_review(payload, self.staff), 201)
        self.public_review_id = data["id"]
        return data

    def close_public_review(self, public_review_id: Optional[str] = None) -> Dict[str, Any]:
        return validate_success(
            self.api.close_public_review(
                public_review_id or self.public_review_id, self.staff
            ),
            200,
        )

    def approve_disposition(
        self, public_review_id: Optional[str] = None, headers: Optional[dict] = None
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.approve_disposition(
                public_review_id or self.public_review_id, headers or self.staff
            ),
            200,
        )

    def get_public_review(self, public_review_id: Optional[str] = None) -> Dict[str, Any]:
        return validate_success(
            self.api.get_public_review(
                public_review_id or self.public_review_id, self.staff
            ),
            200,
        )

    def submit_public_comment(self, submitter_key: str, **overrides) -> Dict[str, Any]:
        """File one public-review comment as the given participant."""
        payload = f.public_review_comment_payload(
            self.pid(submitter_key), self.draft_id, self.public_review_id, **overrides
        )
        return validate_success(
            self.api.create_comment(payload, self.commenter(submitter_key)), 201
        )

    def dispose_comment(self, comment_id: str, **overrides) -> Dict[str, Any]:
        payload = f.disposition_payload(**overrides)
        return validate_success(
            self.api.dispose_comment(comment_id, payload, self.chair), 200
        )

    def get_comment(self, comment_id: Optional[str] = None) -> Dict[str, Any]:
        return validate_success(
            self.api.get_comment(comment_id or self.comment_id, self.staff), 200
        )

    def submit_committee_comment(
        self, submitter_key: str, draft_id: Optional[str] = None, **overrides
    ) -> Dict[str, Any]:
        """File one committee comment attached straight to a draft revision."""
        payload = f.committee_comment_payload(
            self.pid(submitter_key), draft_id or self.draft_id, **overrides
        )
        data = validate_success(
            self.api.create_comment(payload, self.commenter(submitter_key)), 201
        )
        self.comment_id = data["id"]
        return data

    # -------------------------------------------------------------- appeal steps
    def file_appeal(
        self,
        appellant_key: str,
        cited_ballot_id: Optional[str] = None,
        work_item_id: Optional[str] = None,
        headers: Optional[dict] = None,
        **overrides,
    ) -> Dict[str, Any]:
        """File an appeal in the appellant's own name."""
        payload = f.appeal_payload(
            work_item_id or self.work_item_id,
            self.pid(appellant_key),
            cited_ballot_id=cited_ballot_id,
            **overrides,
        )
        data = validate_success(
            self.api.create_appeal(payload, headers or self.proposer(appellant_key)), 201
        )
        self.appeal_id = data["id"]
        return data

    def decide_appeal(
        self, decision: str = "DENY", appeal_id: Optional[str] = None, **overrides
    ) -> Dict[str, Any]:
        """Decide an appeal, which only the appeals panel may do."""
        payload = f.appeal_decision_payload(decision=decision, **overrides)
        return validate_success(
            self.api.decide_appeal(
                appeal_id or self.appeal_id, payload, self.appeals_board
            ),
            200,
        )

    def get_appeal(self, appeal_id: Optional[str] = None) -> Dict[str, Any]:
        return validate_success(
            self.api.get_appeal(appeal_id or self.appeal_id, self.staff), 200
        )

    # --------------------------------------------------- patent disclosure steps
    def disclose_patent(
        self,
        discloser_key: str,
        work_item_id: Optional[str] = None,
        expected_work_item_version: Optional[int] = None,
        headers: Optional[dict] = None,
        **overrides,
    ) -> Dict[str, Any]:
        """Record a patent disclosure, pinning the work item version last read."""
        target = work_item_id or self.work_item_id
        version = (
            expected_work_item_version
            if expected_work_item_version is not None
            else self.get_work_item(target)["version"]
        )
        payload = f.patent_disclosure_payload(
            target, self.pid(discloser_key), version, **overrides
        )
        data = validate_success(
            self.api.create_patent_disclosure(
                payload, headers or self.proposer(discloser_key)
            ),
            201,
        )
        self.disclosure_id = data["id"]
        return data

    def commit_licence(
        self,
        disclosure_id: Optional[str] = None,
        commitment: str = "RAND",
        headers: Optional[dict] = None,
        discloser_key: str = "p1",
        **overrides,
    ) -> Dict[str, Any]:
        """Record the licensing commitment behind a disclosure."""
        payload = f.commitment_payload(commitment=commitment, **overrides)
        return validate_success(
            self.api.submit_commitment(
                disclosure_id or self.disclosure_id,
                payload,
                headers or self.proposer(discloser_key),
            ),
            200,
        )

    def get_disclosure(self, disclosure_id: Optional[str] = None) -> Dict[str, Any]:
        return validate_success(
            self.api.get_patent_disclosure(
                disclosure_id or self.disclosure_id, self.staff
            ),
            200,
        )

    # --------------------------------------------------- maintenance item steps
    def submit_maintenance_item(
        self,
        requester_key: str,
        work_item_id: Optional[str] = None,
        headers: Optional[dict] = None,
        **overrides,
    ) -> Dict[str, Any]:
        """Submit an interpretation request or an erratum report."""
        payload = f.maintenance_item_payload(
            work_item_id or self.work_item_id, self.pid(requester_key), **overrides
        )
        data = validate_success(
            self.api.create_maintenance_item(
                payload, headers or self.proposer(requester_key)
            ),
            201,
        )
        self.maintenance_item_id = data["id"]
        return data

    def resolve_maintenance(
        self,
        maintenance_item_id: Optional[str] = None,
        headers: Optional[dict] = None,
        **overrides,
    ) -> Dict[str, Any]:
        """Resolve a maintenance item; the interpretation branch is the chair's."""
        payload = f.maintenance_resolution_payload(**overrides)
        return validate_success(
            self.api.resolve_maintenance_item(
                maintenance_item_id or self.maintenance_item_id,
                payload,
                headers or self.chair,
            ),
            200,
        )

    def get_maintenance_item(
        self, maintenance_item_id: Optional[str] = None
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.get_maintenance_item(
                maintenance_item_id or self.maintenance_item_id, self.staff
            ),
            200,
        )

    # ----------------------------------------------------- periodic review steps
    def periodic_review(
        self, action: str = "OPEN_REVIEW", work_item_id: Optional[str] = None, **overrides
    ) -> Dict[str, Any]:
        """Open a periodic review, reaffirm the standard, or withdraw it."""
        payload = f.periodic_review_payload(action=action, **overrides)
        return validate_success(
            self.api.periodic_review(
                work_item_id or self.work_item_id, payload, self.staff
            ),
            200,
        )

    # ---------------------------------------------------------------- clock step
    def set_clock(self, instant: str) -> Dict[str, Any]:
        """Move the logical clock; nothing else in the store is touched."""
        data = validate_success(self.api.set_clock(instant, self.staff), 200)
        self.clock = instant
        return data


# ============================================================================
# Tiered builders. Each one takes the plain client and returns a Scenario that
# has reached a named point in the standards process, so a test only has to
# perform the step it is actually about.
# ============================================================================


def balanced_active_committee(api: ApiClient, **committee_overrides) -> Scenario:
    """
    Three participants in three interest categories hold voting seats on TC-14,
    which is chaired by the PRODUCER and has been activated.
    """
    s = Scenario(api)
    s.register_core()
    s.create_committee("p1", **committee_overrides)
    s.appoint("p1", "m1")
    s.appoint("p2", "m2")
    s.appoint("p3", "m3")
    s.activate_committee()
    return s


def work_item_in_development(
    api: ApiClient, designation: str = "STD-1400", **committee_overrides
) -> Scenario:
    """A scope-approved work item sponsored by the balanced committee."""
    s = balanced_active_committee(api, **committee_overrides)
    s.propose_work_item("p1")
    s.approve_scope(designation=designation)
    return s


def work_item_with_draft(
    api: ApiClient,
    total_clause_count: int = 40,
    changed_clause_count: int = 0,
    **kwargs,
) -> Scenario:
    """A work item in development carrying a revision-1 draft in DRAFTING."""
    s = work_item_in_development(api, **kwargs)
    s.add_draft(
        total_clause_count=total_clause_count,
        changed_clause_count=changed_clause_count,
        summary="Revision 1",
    )
    return s


def open_subcommittee_ballot(
    api: ApiClient,
    opens_at: str = "2026-08-01T00:00:00Z",
    closes_at: str = "2026-08-15T00:00:00Z",
    **kwargs,
) -> Scenario:
    """A revision-1 draft under an OPEN subcommittee ballot, no votes cast yet."""
    s = work_item_with_draft(api, **kwargs)
    s.open_ballot(opens_at=opens_at, closes_at=closes_at)
    return s


def voted_subcommittee_ballot(api: ApiClient, **kwargs) -> Scenario:
    """
    An OPEN subcommittee ballot with two affirmatives and the GENERAL_INTEREST
    seat's negative, which carries its mandatory comment.
    """
    s = open_subcommittee_ballot(api, **kwargs)
    s.cast("m1", "AFFIRMATIVE", vote_key="v1")
    s.cast("m2", "AFFIRMATIVE", vote_key="v2")
    s.cast_negative("m3", vote_key="v3")
    return s


def unanimous_subcommittee_ballot(api: ApiClient, **kwargs) -> Scenario:
    """An OPEN subcommittee ballot every seat has returned affirmative."""
    s = open_subcommittee_ballot(api, **kwargs)
    s.cast("m1", "AFFIRMATIVE", vote_key="v1")
    s.cast("m2", "AFFIRMATIVE", vote_key="v2")
    s.cast("m3", "AFFIRMATIVE", vote_key="v3")
    return s


def draft_ready_for_public_review(api: ApiClient, **kwargs) -> Scenario:
    """
    A unanimously approved subcommittee ballot, closed early once every seat had
    returned, leaving the draft ready for public review.
    """
    s = unanimous_subcommittee_ballot(api, **kwargs)
    s.close_ballot()
    return s


def draft_through_public_review(api: ApiClient, **kwargs) -> Scenario:
    """
    The revision-1 draft has run a zero-comment public review over the closed
    inclusive window 2026-08-01 .. 2026-09-14, closed at 2026-09-15. The clock is
    left at 2026-09-15T00:00:00Z.
    """
    s = draft_ready_for_public_review(api, **kwargs)
    s.announce_public_review(start_date="2026-08-01", end_date="2026-09-14")
    s.set_clock("2026-09-15T00:00:00Z")
    s.close_public_review()
    return s


def consensus_approved_work_item(api: ApiClient, **kwargs) -> Scenario:
    """
    The work item has cleared a unanimous consensus-body ballot over
    2026-09-15 .. 2026-10-15, closed early at 2026-09-15 with every seat returned,
    so the draft is approved and the work item is consensus approved.
    """
    s = draft_through_public_review(api, **kwargs)
    s.open_ballot(
        ballot_kind="CONSENSUS_BODY",
        opens_at="2026-09-15T00:00:00Z",
        closes_at="2026-10-15T00:00:00Z",
    )
    s.cast("m1", "AFFIRMATIVE", vote_key="cv1")
    s.cast("m2", "AFFIRMATIVE", vote_key="cv2")
    s.cast("m3", "AFFIRMATIVE", vote_key="cv3")
    s.close_ballot()
    return s


def published_work_item(api: ApiClient, **kwargs) -> Scenario:
    """A consensus-approved work item that has been published."""
    s = consensus_approved_work_item(api, **kwargs)
    s.publish()
    return s


def public_review_with_one_comment(api: ApiClient, **kwargs) -> Scenario:
    """
    An OPEN public review over 2026-08-01 .. 2026-09-14 carrying exactly one
    technical comment from a participant who holds no seat, then closed at
    2026-09-15 so the comment count is frozen with the comment still outstanding.
    """
    s = draft_ready_for_public_review(api, **kwargs)
    s.register("p6")
    s.announce_public_review(start_date="2026-08-01", end_date="2026-09-14")
    comment = s.submit_public_comment("p6")
    s.comment_id = comment["id"]
    s.set_clock("2026-09-15T00:00:00Z")
    s.close_public_review()
    return s


def committee_with_extra_producer_seats(
    api: ApiClient, suspend_seats=("m4", "m5"), **committee_overrides
) -> Scenario:
    """
    The balanced ACTIVE committee, plus two further PRODUCER seats on distinct
    employer codes. The seats named in suspend_seats are then moved to SUSPENDED,
    so the roster keeps five seats while fewer of them vote.
    """
    s = balanced_active_committee(api, **committee_overrides)
    s.register_extras("p4", "p5")
    s.appoint("p4", "m4")
    s.appoint("p5", "m5")
    for seat_key in suspend_seats:
        s.patch_membership(seat_key, status="SUSPENDED")
    return s


def read_data(response) -> Dict[str, Any]:
    """Lenient read of a setup response body when the exact 2xx code is not the point."""
    return get_success_data(response)


def evaluated_ballot_with_pending_negative(api: ApiClient, **kwargs) -> Scenario:
    """
    The subcommittee ballot with two affirmatives and one negative, closed early
    once all three seats had returned. The close leaves the negative PENDING, so
    the draft sits in COMMENT_RESOLUTION and the work item's gate is shut.
    """
    s = voted_subcommittee_ballot(api, **kwargs)
    s.close_ballot()
    return s


def draft_ready_after_non_persuasive_negative(api: ApiClient, **kwargs) -> Scenario:
    """
    The one negative on the evaluated subcommittee ballot has been ruled
    NON_PERSUASIVE, which clears the last pending negative and carries the draft
    out of COMMENT_RESOLUTION to PUBLIC_REVIEW_READY.
    """
    s = evaluated_ballot_with_pending_negative(api, **kwargs)
    s.adjudicate("v3", "NON_PERSUASIVE")
    return s


def announced_zero_comment_public_review(api: ApiClient, **kwargs) -> Scenario:
    """
    A public review announced over the closed inclusive window 2026-08-01 ..
    2026-09-14 that has drawn no comments, with the clock moved to
    2026-09-15T00:00:00Z so the window has fully elapsed but the review is still
    OPEN — the close itself has not been performed.
    """
    s = draft_ready_for_public_review(api, **kwargs)
    s.announce_public_review(start_date="2026-08-01", end_date="2026-09-14")
    s.set_clock("2026-09-15T00:00:00Z")
    return s


def contested_draft_through_public_review(api: ApiClient, **kwargs) -> Scenario:
    """
    The draft whose subcommittee negative was ruled NON_PERSUASIVE has since run
    a zero-comment public review over 2026-08-01 .. 2026-09-14, closed at
    2026-09-15 straight into DISPOSITION_APPROVED. The clock stays at
    2026-09-15T00:00:00Z.
    """
    s = draft_ready_after_non_persuasive_negative(api, **kwargs)
    s.announce_public_review(start_date="2026-08-01", end_date="2026-09-14")
    s.set_clock("2026-09-15T00:00:00Z")
    s.close_public_review()
    return s


def voted_consensus_ballot(api: ApiClient, **kwargs) -> Scenario:
    """
    A CONSENSUS_BODY ballot over 2026-09-15T00:00:00Z .. 2026-10-15T00:00:00Z on
    the reviewed draft, holding two affirmatives and one negative, still OPEN.
    """
    s = contested_draft_through_public_review(api, **kwargs)
    s.open_ballot(
        ballot_kind="CONSENSUS_BODY",
        opens_at="2026-09-15T00:00:00Z",
        closes_at="2026-10-15T00:00:00Z",
    )
    s.cast("m1", "AFFIRMATIVE", vote_key="cv1")
    s.cast("m2", "AFFIRMATIVE", vote_key="cv2")
    s.cast_negative("m3", vote_key="cv3")
    return s


def consensus_approved_after_non_persuasive(api: ApiClient, **kwargs) -> Scenario:
    """
    The consensus-body ballot closed to APPROVED_PENDING_NEGATIVES and its one
    negative was then ruled NON_PERSUASIVE, so the ballot refreshed to APPROVED
    with its negative_count still 1, the draft reached APPROVED and the work item
    reached CONSENSUS_APPROVED.
    """
    s = voted_consensus_ballot(api, **kwargs)
    s.close_ballot()
    s.adjudicate("cv3", "NON_PERSUASIVE")
    return s


def suspended_committee_with_draft(api: ApiClient, **kwargs) -> Scenario:
    """
    The work item's revision-1 draft is in DRAFTING, but the GENERAL_INTEREST seat
    has been suspended, dropping the voting basis to two seats — below the three
    the balanced verdict needs — so the committee has been system-suspended.
    """
    s = work_item_with_draft(api, **kwargs)
    s.patch_membership("m3", status="SUSPENDED")
    return s


def revision_two_after_failed_subcommittee_ballot(api: ApiClient, **kwargs) -> Scenario:
    """
    Only two of the three seats returned on the first subcommittee ballot — one
    affirmative and one negative — so it evaluated to FAILED_THRESHOLD at 50.0
    against the 50.1 bar. The negative was ruled NON_PERSUASIVE, returning the
    draft to DRAFTING, and a revision-2 draft with 4 of 40 clauses changed now
    supersedes it. The clock is left at 2026-08-15T00:00:00Z.
    """
    s = open_subcommittee_ballot(api, **kwargs)
    s.cast("m1", "AFFIRMATIVE", vote_key="v1")
    s.cast_negative("m3", vote_key="v3")
    s.set_clock("2026-08-15T00:00:00Z")
    s.close_ballot()
    s.adjudicate("v3", "NON_PERSUASIVE")
    first_draft_id = s.draft_id
    s.add_draft(
        total_clause_count=40,
        changed_clause_count=4,
        prior_draft_id=first_draft_id,
        summary="Revision 2",
    )
    return s


def revision_two_after_closed_public_review(api: ApiClient, **kwargs) -> Scenario:
    """
    Revision 1 ran a zero-comment public review over 2026-08-01 .. 2026-09-14,
    closed at 2026-09-15 into DISPOSITION_APPROVED, and was then superseded by a
    revision-2 draft of 40 clauses with none changed. Revision 2 has passed its
    own unanimous subcommittee ballot over 2026-09-15 .. 2026-09-29, closed early
    once all three seats returned, so it sits in PUBLIC_REVIEW_READY.
    """
    s = draft_through_public_review(api, **kwargs)
    first_draft_id = s.draft_id
    s.add_draft(
        total_clause_count=40,
        changed_clause_count=0,
        prior_draft_id=first_draft_id,
        summary="Revision 2",
    )
    s.open_ballot(
        opens_at="2026-09-15T00:00:00Z",
        closes_at="2026-09-29T00:00:00Z",
    )
    s.cast("m1", "AFFIRMATIVE", vote_key="rv1")
    s.cast("m2", "AFFIRMATIVE", vote_key="rv2")
    s.cast("m3", "AFFIRMATIVE", vote_key="rv3")
    s.close_ballot()
    return s


def committee_with_four_drafted_work_items(api: ApiClient, **kwargs) -> Scenario:
    """
    One balanced ACTIVE committee sponsoring four separate work items STD-1400 ..
    STD-1403, each carrying its own revision-1 draft in DRAFTING, so nothing but
    the committee's overlap budget can ever be contended.
    """
    s = balanced_active_committee(api, **kwargs)
    for offset in range(4):
        s.propose_work_item("p1", title=f"Fastener torque spec part {offset + 1}")
        s.approve_scope(designation=f"STD-{1400 + offset}")
        s.add_draft(total_clause_count=40, changed_clause_count=0, summary="Revision 1")
    return s
