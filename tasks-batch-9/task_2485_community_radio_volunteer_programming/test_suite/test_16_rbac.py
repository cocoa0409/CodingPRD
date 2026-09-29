"""Who may call what, and the two layers of authorisation behind that question.

Four of these cases pair one allowed exclusive write with one refusal for the same
caller, so a permissive implementation cannot pass by simply allowing everything.
The remaining cases separate the endpoint's role list from the row-level identity
check that runs immediately after it — a caller can hold the right role and still be
the wrong person.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    DEVELOPMENT_HEADERS,
    DIRECTOR_HEADERS,
    OFFICER_ONE,
    OFFICER_TWO,
    TRAINER_HEADERS,
    api_client,
    factories,
    fixtures,
    make_committee_member_headers,
    make_compliance_officer_headers,
    make_volunteer_headers,
)

CLOCK = "2026-08-01T00:00:00Z"
INCIDENT_AT = "2026-07-30T14:00:00Z"
EPISODE_START = "2026-08-03T09:00:00Z"


def _submitted_proposal_with_a_staffed_committee():
    fixtures.set_clock(CLOCK)
    host = fixtures.create_certified_host()
    members = fixtures.create_committee_members(count=3)
    proposal = fixtures.create_proposal(host["id"], title="Delta Blues Hour")
    submitted = fixtures.submit_proposal(proposal["id"], host["id"])
    assert submitted["status"] == "SUBMITTED"
    return {"host_id": host["id"], "members": members, "proposal_id": proposal["id"]}


class TestTrainingCoordinatorScope:
    def test_the_coordinator_enrols_but_cannot_refer_a_proposal_to_committee(self):
        """One exclusive write is allowed and one belonging to the chair is refused.

        Enrolment is the coordinator's own operation and "Every newly enrolled
        volunteer begins with `status` `PROSPECT`". "Opening committee review is the
        director's move", so the coordinator's attempt meets the first check any
        endpoint performs and answers `ERR_UNAUTHORIZED` (HTTP 403) while the
        proposal stays where it stood.

        Design: Corner/rbac/training_coordinator_can_enrol_but_cannot_open_a_committee_review
        """
        setup = _submitted_proposal_with_a_staffed_committee()

        enrolled = validate_success(
            api_client.create_volunteer(
                factories.create_volunteer_payload(
                    legal_name="Ivo Bergman",
                    email="ivo@krcr.example",
                    role_track="ENGINEER",
                    seniority_start_date="2025-06-01",
                ),
                TRAINER_HEADERS,
            ),
            201,
        )
        assert enrolled["status"] == "PROSPECT"

        validate_error(
            api_client.open_proposal_review(setup["proposal_id"], TRAINER_HEADERS),
            "ERR_UNAUTHORIZED",
            403,
        )

        stored = validate_success(
            api_client.get_proposal(setup["proposal_id"], DIRECTOR_HEADERS), 200
        )
        assert stored["status"] == "SUBMITTED"


class TestProgramDirectorScope:
    def test_the_chair_opens_review_but_is_barred_from_the_ballot_box(self):
        """The chair runs the review and takes no part in scoring it.

        "Opening committee review is the director's move, taking the proposal
        `SUBMITTED → IN_COMMITTEE`", while casting a ballot is authorised for the
        `CommitteeMember` alone. The payload names a genuinely seated member, so the
        refusal is the role rule and not the seat rule.

        Design: Corner/rbac/program_director_can_open_a_review_but_cannot_cast_a_ballot
        """
        setup = _submitted_proposal_with_a_staffed_committee()

        opened = validate_success(
            api_client.open_proposal_review(setup["proposal_id"], DIRECTOR_HEADERS), 200
        )
        assert opened["status"] == "IN_COMMITTEE"

        validate_error(
            api_client.cast_vote(
                setup["proposal_id"],
                factories.cast_vote_payload(setup["members"][0]["id"]),
                DIRECTOR_HEADERS,
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        _, meta = validate_paginated(api_client.list_committee_votes(DIRECTOR_HEADERS))
        assert meta["total_count"] == 0


class TestCommitteeMemberScope:
    def test_a_seated_member_votes_but_cannot_tally_the_round(self):
        """The member's own write succeeds and the chair-only tally is refused.

        A ballot's "`review_round` is copied from that proposal's current
        `review_round` at cast time". "Tallying is the director's decision", so a
        member's attempt answers `ERR_UNAUTHORIZED`, and because the version guard is
        read fresh the refusal cannot be a concurrency rejection. The proposal keeps
        "a null `composite_score`" because no tally ran.

        Design: Corner/rbac/committee_member_can_vote_but_cannot_tally_the_decision
        """
        setup = _submitted_proposal_with_a_staffed_committee()
        members = setup["members"]
        fixtures.open_review(setup["proposal_id"])
        fixtures.cast_ballot(setup["proposal_id"], members[0]["id"])
        fixtures.cast_ballot(setup["proposal_id"], members[1]["id"])

        third = validate_success(
            api_client.cast_vote(
                setup["proposal_id"],
                factories.cast_vote_payload(members[2]["id"]),
                make_committee_member_headers(members[2]["id"]),
            ),
            201,
        )
        assert third["review_round"] == 1

        validate_error(
            api_client.decide_proposal(
                setup["proposal_id"],
                factories.decide_proposal_payload(
                    fixtures.proposal_version(setup["proposal_id"])
                ),
                make_committee_member_headers(members[2]["id"]),
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        stored = validate_success(
            api_client.get_proposal(setup["proposal_id"], DIRECTOR_HEADERS), 200
        )
        assert stored["status"] == "IN_COMMITTEE"
        assert stored["composite_score"] is None


class TestRowLevelOwnership:
    def test_a_volunteer_cannot_revise_someone_elses_draft(self):
        """The role is right, the state is mutable, and the identity is wrong.

        "Ownership is checked immediately after role membership and before any
        structural validation of the payload. A caller whose role is permitted but
        whose identity is wrong receives a more specific refusal than
        `ERR_UNAUTHORIZED`: `ERR_NOT_PROPOSAL_OWNER` (403) when a volunteer acts on
        someone else's proposal".

        Design: Corner/rbac/volunteer_cannot_patch_another_authors_proposal
        """
        fixtures.set_clock(CLOCK)
        author = fixtures.create_certified_host()
        stranger = fixtures.create_volunteer(
            legal_name="Bo Lin", email="bo@krcr.example", seniority_start_date="2023-01-01"
        )
        proposal = fixtures.create_proposal(author["id"], title="Delta Blues Hour")

        validate_error(
            api_client.update_proposal(
                proposal["id"],
                {"title": "Bo's Blues Hour"},
                make_volunteer_headers(stranger["id"]),
            ),
            "ERR_NOT_PROPOSAL_OWNER",
            403,
        )

        stored = validate_success(
            api_client.get_proposal(proposal["id"], DIRECTOR_HEADERS), 200
        )
        assert stored["title"] == "Delta Blues Hour"
        assert stored["version"] == 1

    def test_an_unseated_volunteer_passes_the_role_check_and_fails_the_seat_check(self):
        """Authorisation for a ballot has two layers, and only the second one fails.

        "When `X-User-Role` is `CommitteeMember`, `X-User-ID` is likewise the `id` of
        the acting `Volunteer` row — specifically one whose `committee_seat` is true",
        and "a caster whose `committee_seat` is false answers
        `ERR_NOT_COMMITTEE_MEMBER`".

        Design: Corner/rbac/unseated_volunteer_cannot_cast_a_ballot
        """
        setup = _submitted_proposal_with_a_staffed_committee()
        fixtures.open_review(setup["proposal_id"])
        unseated = fixtures.create_volunteer(
            legal_name="Fern Duval",
            email="fern@krcr.example",
            role_track="DEVELOPMENT",
            seniority_start_date="2023-01-01",
        )
        assert unseated["committee_seat"] is False

        validate_error(
            api_client.cast_vote(
                setup["proposal_id"],
                factories.cast_vote_payload(unseated["id"]),
                make_committee_member_headers(unseated["id"]),
            ),
            "ERR_NOT_COMMITTEE_MEMBER",
            403,
        )

        _, meta = validate_paginated(api_client.list_committee_votes(DIRECTOR_HEADERS))
        assert meta["total_count"] == 0

    def test_only_the_operator_of_record_may_submit_the_log(self):
        """A volunteer with no claim on the airing is refused before the log is read.

        "Only the volunteer whose id matches the airing's
        `board_operator_volunteer_id` may file entries, and anyone else is refused
        with `ERR_NOT_BOARD_OPERATOR`", the same ownership rule the submission
        carries: "`ERR_NOT_BOARD_OPERATOR` (403) when a volunteer logs a spin or
        submits a log for an airing they did not board-operate". Because ownership is
        checked "immediately after role membership and before any structural
        validation", the empty playlist never enters into it.

        Design: Corner/rbac/only_the_board_operator_can_submit_the_playlist_log
        """
        base = fixtures.station()
        chain = fixtures.episode_chain(
            base["host_id"],
            base["members"],
            title="Delta Blues Hour",
            format_code="MUSIC",
            requested_daypart="MIDDAY",
            duration_minutes=60,
            day_of_week=1,
            start_minute=540,
            scheduled_start_utc=EPISODE_START,
            air_status="AIRED",
        )
        aired = fixtures.read_episode(chain["episode_id"])
        assert aired["log_status"] == "PENDING"
        assert aired["board_operator_volunteer_id"] == base["host_id"]

        stranger = base["members"][0]["id"]
        validate_error(
            api_client.submit_playlist_log(
                chain["episode_id"], make_volunteer_headers(stranger)
            ),
            "ERR_NOT_BOARD_OPERATOR",
            403,
        )

        assert fixtures.read_episode(chain["episode_id"])["log_status"] == "PENDING"


class TestComplianceOfficerScope:
    def test_the_officer_adjudicates_but_cannot_register_a_premium(self):
        """The regulator-facing role does not reach the fundraising inventory.

        Adjudication is the officer's own operation, and "An `UNFOUNDED` finding
        moves the incident `OPEN → UNFOUNDED`, charges nothing at all and is
        terminal." Registering a thank-you gift belongs to the
        `DevelopmentCoordinator`, so the officer's attempt answers
        `ERR_UNAUTHORIZED`.

        Design: Corner/rbac/compliance_officer_can_adjudicate_but_cannot_stock_a_premium
        """
        fixtures.set_clock(CLOCK)
        respondent = fixtures.create_volunteer()
        incident = validate_success(
            api_client.create_compliance_incident(
                factories.create_incident_payload(
                    "VOLUNTEER_CONFLICT",
                    "MINOR",
                    INCIDENT_AT,
                    complainant_note="Two hosts booked the same production room.",
                    respondent_volunteer_id=respondent["id"],
                ),
                make_compliance_officer_headers(OFFICER_ONE),
            ),
            201,
        )

        ruled = validate_success(
            api_client.adjudicate_compliance_incident(
                incident["id"],
                factories.adjudicate_incident_payload(finding="UNFOUNDED"),
                make_compliance_officer_headers(OFFICER_TWO),
            ),
            200,
        )
        assert ruled["status"] == "UNFOUNDED"

        validate_error(
            api_client.create_premium_item(
                factories.create_premium_item_payload(
                    sku="TOTE-03",
                    name="Canvas tote",
                    tier_threshold_cents=12000,
                    fair_market_value_cents=3000,
                    units_received_qty=4,
                ),
                make_compliance_officer_headers(OFFICER_TWO),
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        _, meta = validate_paginated(api_client.list_premium_items(DEVELOPMENT_HEADERS))
        assert meta["total_count"] == 0


class TestDevelopmentCoordinatorScope:
    def test_the_fundraiser_plans_a_drive_but_cannot_publish_the_schedule(self):
        """The grid is readable by every role and writable by one.

        Planning a drive is the coordinator's own operation and "A new drive sits on
        `status` `PLANNED`". Publication belongs to the `ProgramDirector`, so the
        coordinator answers `ERR_UNAUTHORIZED`; the guard token is taken from a fresh
        read, so the refusal is provably the role rule. A grid keeps a null
        `published_at` until "A successful publication stamps `published_at` with the
        clock".

        Design: Corner/rbac/development_coordinator_cannot_publish_a_schedule_grid
        """
        fixtures.set_clock(CLOCK)
        grid = fixtures.create_grid()
        assert grid["status"] == "DRAFT"

        planned = validate_success(
            api_client.create_membership_drive(
                factories.create_membership_drive_payload(
                    name="Spring Drive 2027",
                    goal_cents=400000,
                    start_at="2027-03-01T00:00:00Z",
                    end_at="2027-03-10T00:00:00Z",
                    phone_line_count=3,
                ),
                DEVELOPMENT_HEADERS,
            ),
            201,
        )
        assert planned["status"] == "PLANNED"

        validate_error(
            api_client.publish_schedule_grid(
                grid["id"],
                factories.publish_grid_payload(fixtures.grid_version(grid["id"])),
                DEVELOPMENT_HEADERS,
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        stored = fixtures.read_grid(grid["id"])
        assert stored["status"] == "DRAFT"
        assert stored["published_at"] is None
