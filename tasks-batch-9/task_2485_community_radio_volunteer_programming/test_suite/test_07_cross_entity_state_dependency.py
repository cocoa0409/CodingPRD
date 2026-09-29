"""Writes gated on a state field that lives on a different record.

A proposal cannot be submitted while its author is still a trainee, and an airing
cannot be scheduled while its show is restricted. In both cases the byte-identical
request flips from refusal to success the moment the *other* record moves, and
nothing about the request itself changes.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    DIRECTOR_HEADERS,
    OFFICER_ADJUDICATOR,
    TRAINER_HEADERS,
    api_client,
    assertions,
    factories,
    fixtures,
    make_compliance_officer_headers,
    make_volunteer_headers,
)

CLOCK = "2026-08-01T00:00:00Z"
THIRD_CERT_EXPIRY = "2028-08-01T00:00:00Z"
EPISODE_START = "2026-09-07T20:00:00Z"


def _proposal_authored_by_a_trainee():
    """A draft proposal whose author holds only two of the three core
    certifications, so the roster row is still `IN_TRAINING`."""
    fixtures.set_clock(CLOCK)
    host = fixtures.create_volunteer(
        legal_name="Ada Reyes", email="ada@krcr.example", seniority_start_date="2024-08-01"
    )
    fixtures.add_certification(host["id"], "BOARD_OPERATION", 88)
    fixtures.add_certification(host["id"], "STATION_POLICY", 90)
    fixtures.create_committee_members(count=3)
    proposal = fixtures.create_proposal(
        host["id"],
        title="Delta Sessions",
        format_code="MUSIC",
        language_code="EN",
        requested_daypart="EVENING",
        requested_duration_minutes=120,
    )
    return {"host_id": host["id"], "proposal_id": proposal["id"]}


def _restricted_show_on_a_mutable_grid():
    """A show carrying one confirmed occupation on a grid that is still in
    review, restricted by a single critical political-content charge."""
    base = fixtures.station()
    chain = fixtures.grid_chain(base["host_id"], base["members"], confirm=True, publish=False)
    incident = fixtures.create_incident(
        "POLITICAL_CONTENT",
        "CRITICAL",
        "2026-07-28T20:30:00Z",
        complainant_note="Unbalanced candidate advocacy through a whole hour.",
        program_id=chain["program_id"],
    )
    adjudicated = fixtures.adjudicate_incident(incident["id"], finding="SUBSTANTIATED")
    assert adjudicated["penalty_points"] == 6
    return {
        "host_id": base["host_id"],
        "program_id": chain["program_id"],
        "slot_id": chain["slot_id"],
        "grid_id": chain["grid_id"],
        "incident_id": incident["id"],
    }


def _episode_payload(setup):
    return factories.create_episode_payload(
        setup["program_id"],
        setup["slot_id"],
        setup["host_id"],
        scheduled_start_utc=EPISODE_START,
    )


class TestProposalSubmitReadsTheProposerRosterState:
    def test_a_trainee_author_cannot_submit_their_own_draft(self):
        """The author owns the proposal and is still refused on roster standing.

        "Two conditions bind: `X-User-ID` must be the proposal's
        `proposer_volunteer_id`, and the author's roster `status` must be exactly
        `CERTIFIED` — a `PROSPECT`, an `IN_TRAINING` trainee, a volunteer on
        `PROBATION`, a `SUSPENDED` volunteer and a `RESIGNED` one are all refused
        with `ERR_PROPOSER_NOT_CERTIFIED`." `needs_core_renewal` "is true whenever
        at least one of the three core curricula is absent, `EXPIRED` or `REVOKED`
        for that volunteer".

        Design: Difficulty/cross_entity_state_dependency/proposal_submit_depends_on_the_proposer_volunteer_state
        """
        setup = _proposal_authored_by_a_trainee()

        before = validate_success(
            api_client.get_volunteer(setup["host_id"], TRAINER_HEADERS), 200
        )
        assert before["status"] == "IN_TRAINING"
        assert before["current_certification_count"] == 2
        assert before["needs_core_renewal"] is True

        response = api_client.submit_proposal(
            setup["proposal_id"], make_volunteer_headers(setup["host_id"])
        )
        validate_error(response, "ERR_PROPOSER_NOT_CERTIFIED", 422)

        assert (
            validate_success(
                api_client.get_proposal(setup["proposal_id"], DIRECTOR_HEADERS), 200
            )["status"]
            == "DRAFT"
        )

    def test_the_third_certification_lets_the_same_submit_through(self):
        """Completing the core set certifies the author and unblocks the draft.

        "When the pass completes the core set ... the volunteer advances
        `IN_TRAINING → CERTIFIED`, `needs_core_renewal` is set false,
        `seniority_score` is recomputed". A pass stamps `issued_on` with the clock
        and "`expires_on` is set to twenty-four calendar months after
        `issued_on`", and "Submission by the author moves the proposal `DRAFT →
        SUBMITTED` and sets `review_round` to 1."

        Design: Difficulty/cross_entity_state_dependency/proposal_submit_depends_on_the_proposer_volunteer_state
        """
        setup = _proposal_authored_by_a_trainee()

        validate_error(
            api_client.submit_proposal(
                setup["proposal_id"], make_volunteer_headers(setup["host_id"])
            ),
            "ERR_PROPOSER_NOT_CERTIFIED",
            422,
        )

        third = validate_success(
            api_client.create_certification(
                setup["host_id"],
                factories.create_certification_payload(
                    cert_type="BROADCAST_REGULATION", exam_score=91
                ),
                TRAINER_HEADERS,
            ),
            201,
        )
        assert third["status"] == "PASSED"
        assertions.assert_instant_equals(third["expires_on"], THIRD_CERT_EXPIRY, "expires_on")
        assertions.assert_certification(third)

        volunteer = validate_success(
            api_client.get_volunteer(setup["host_id"], TRAINER_HEADERS), 200
        )
        assert volunteer["status"] == "CERTIFIED"
        assert volunteer["current_certification_count"] == 3
        assert volunteer["needs_core_renewal"] is False
        assertions.assert_two_decimals_equal(
            volunteer["seniority_score"], 54.00, "seniority_score"
        )

        submitted = validate_success(
            api_client.submit_proposal(
                setup["proposal_id"], make_volunteer_headers(setup["host_id"])
            ),
            200,
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["review_round"] == 1

        _, meta = validate_paginated(
            api_client.list_proposals(DIRECTOR_HEADERS, params={"status": "SUBMITTED"})
        )
        assert meta["total_count"] == 1


class TestEpisodeCreationReadsTheProgramComplianceState:
    def test_a_restricted_show_may_not_be_given_a_new_airing(self):
        """The airing is refused for a fact that lives on the show.

        "A show whose `compliance_standing` is `RESTRICTED` may not be given new
        airings at all, and answers `ERR_PROGRAM_RESTRICTED`." A `POLITICAL_CONTENT`
        base "is 1, 3 and 6", so a single `CRITICAL` charge reaches the
        `RESTRICTED` band on its own, which begins "at 6 points or more".

        Design: Difficulty/cross_entity_state_dependency/episode_creation_depends_on_the_program_compliance_state
        """
        setup = _restricted_show_on_a_mutable_grid()

        program = fixtures.read_program(setup["program_id"])
        assert program["compliance_penalty_points"] == 6
        assert program["compliance_standing"] == "RESTRICTED"

        response = api_client.create_episode(_episode_payload(setup), DIRECTOR_HEADERS)
        validate_error(response, "ERR_PROGRAM_RESTRICTED", 409)

        _, meta = validate_paginated(
            api_client.list_episodes(
                DIRECTOR_HEADERS, params={"program_id": setup["program_id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_remediation_and_reinstatement_let_the_same_airing_through(self):
        """Clearing the charge on the show admits the identical airing request.

        "It moves the incident `SUBSTANTIATED → REMEDIATED`, subtracts exactly the
        incident's `penalty_points` from the show's `compliance_penalty_points` and
        recomputes `compliance_standing` from the new total using the same
        thresholds". Occupations "stay preempted: recovering the air position requires
        the director to explicitly reinstate each one", and reinstatement "clears
        `preempted_by_program_id` back to null". A new airing then "lands on
        `air_status` `SCHEDULED` and `log_status` `NOT_REQUIRED`, with
        `needs_substitute` false".

        Design: Difficulty/cross_entity_state_dependency/episode_creation_depends_on_the_program_compliance_state
        """
        setup = _restricted_show_on_a_mutable_grid()

        validate_error(
            api_client.create_episode(_episode_payload(setup), DIRECTOR_HEADERS),
            "ERR_PROGRAM_RESTRICTED",
            409,
        )

        remediated = validate_success(
            api_client.remediate_compliance_incident(
                setup["incident_id"],
                factories.remediate_incident_payload(
                    remediation_note=(
                        "Balancing hour aired and the host retrained on political content."
                    )
                ),
                make_compliance_officer_headers(OFFICER_ADJUDICATOR),
            ),
            200,
        )
        assert remediated["status"] == "REMEDIATED"

        cleared = fixtures.read_program(setup["program_id"])
        assert cleared["compliance_penalty_points"] == 0
        assert cleared["compliance_standing"] == "CLEAR"

        reinstated = validate_success(
            api_client.reinstate_slot_assignment(setup["slot_id"], DIRECTOR_HEADERS), 200
        )
        assert reinstated["status"] == "CONFIRMED"
        assert reinstated["preempted_by_program_id"] is None

        episode = validate_success(
            api_client.create_episode(_episode_payload(setup), DIRECTOR_HEADERS), 201
        )
        assert episode["air_status"] == "SCHEDULED"
        assert episode["log_status"] == "NOT_REQUIRED"
        assert episode["needs_substitute"] is False
        assertions.assert_episode(episode)

        _, meta = validate_paginated(
            api_client.list_episodes(
                DIRECTOR_HEADERS, params={"program_id": setup["program_id"]}
            )
        )
        assert meta["total_count"] == 1
