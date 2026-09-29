"""Requests that breach two rules at once, where the order of refusal decides.

A placement aimed at a published grid also collides with a live occupation, and
a conflicted officer also rules on an incident that has already been decided. In
both cases the higher rung answers and the lower one is never reported.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    DIRECTOR_HEADERS,
    OFFICER_ADJUDICATOR,
    OFFICER_COPY_DESK,
    OFFICER_HEADERS,
    api_client,
    assertions,
    factories,
    fixtures,
    make_compliance_officer_headers,
)

SPONSOR_COPY = "Support for this hour comes from Fernwood Books on Third Street."


def _published_grid_with_two_occupations():
    base = fixtures.station()
    grid = fixtures.quota_ready_grid(base["host_id"], base["members"], publish=True)
    published = fixtures.read_grid(grid["grid_id"])
    assert published["status"] == "PUBLISHED"
    assert published["total_assigned_minutes"] == 150
    return {
        "grid_id": grid["grid_id"],
        "grid_version": published["version"],
        "music_program_id": grid["music_program_id"],
        "news_program_id": grid["news_program_id"],
    }


def _already_adjudicated_sponsor_complaint():
    """A complaint about a spot, cleared by one officer and already ruled on by
    another, so a second ruling from the clearing officer breaches two rules."""
    base = fixtures.station()
    approved = fixtures.create_approved_program(base["host_id"], base["members"])
    spot = fixtures.create_reviewed_spot(
        officer=OFFICER_COPY_DESK,
        underwriter_name="Fernwood Books",
        spot_class="UNDERWRITING",
        copy_text=SPONSOR_COPY,
        assigned_program_id=approved["program_id"],
    )
    assert spot["spot"]["status"] == "APPROVED"
    assert spot["spot"]["reviewed_by_user_id"] == OFFICER_COPY_DESK

    incident = fixtures.create_incident(
        "SPONSOR_ID",
        "MINOR",
        "2026-08-03T20:05:00Z",
        complainant_note="The sponsor was not identified in the break.",
        program_id=approved["program_id"],
        underwriting_spot_id=spot["spot_id"],
    )
    adjudicated = fixtures.adjudicate_incident(
        incident["id"], finding="SUBSTANTIATED", officer=OFFICER_ADJUDICATOR
    )
    assert adjudicated["status"] == "SUBSTANTIATED"
    return {
        "program_id": approved["program_id"],
        "spot_id": spot["spot_id"],
        "incident_id": incident["id"],
    }


class TestPublishedGridOutranksTheWindowConflict:
    def test_the_mutability_refusal_answers_ahead_of_the_slot_conflict(self):
        """A published grid refuses the placement on mutability alone.

        "`DRAFT` and `IN_REVIEW` are both mutable; `PUBLISHED` and `SUPERSEDED`
        are not, and any placement, publication, confirmation, release or
        reinstatement aimed at a grid in either of those two states is refused
        with `ERR_GRID_NOT_MUTABLE`." The requested window sits squarely on top of
        a live occupation, and the order of refusal still puts the mutability
        rule first, so the collision is never reported.

        Design: Difficulty/priority_pair_validation_conflict/published_grid_outranks_the_slot_window_conflict
        """
        setup = _published_grid_with_two_occupations()

        response = api_client.create_slot_assignment(
            setup["grid_id"],
            factories.create_slot_assignment_payload(
                setup["news_program_id"],
                setup["grid_version"],
                day_of_week=1,
                start_minute=1200,
                duration_minutes=60,
            ),
            DIRECTOR_HEADERS,
        )

        body = validate_error(response, "ERR_GRID_NOT_MUTABLE", 409)
        assert body["error_id"] != "ERR_SLOT_CONFLICT"

    def test_the_refused_placement_leaves_the_published_grid_untouched(self):
        """Nothing about the grid moves when the placement is refused.

        A grid's derived figures are "recomputed on every occupation created,
        confirmed, released, preempted or reinstated on it", so a placement that
        never lands leaves `total_assigned_minutes` and the grid's `version`
        exactly where they were.

        Design: Difficulty/priority_pair_validation_conflict/published_grid_outranks_the_slot_window_conflict
        """
        setup = _published_grid_with_two_occupations()

        validate_error(
            api_client.create_slot_assignment(
                setup["grid_id"],
                factories.create_slot_assignment_payload(
                    setup["news_program_id"],
                    setup["grid_version"],
                    day_of_week=1,
                    start_minute=1200,
                    duration_minutes=60,
                ),
                DIRECTOR_HEADERS,
            ),
            "ERR_GRID_NOT_MUTABLE",
            409,
        )

        _, meta = validate_paginated(
            api_client.list_slot_assignments(
                DIRECTOR_HEADERS, params={"grid_id": setup["grid_id"]}
            )
        )
        assert meta["total_count"] == 2

        grid = fixtures.read_grid(setup["grid_id"])
        assert grid["version"] == setup["grid_version"]
        assert grid["total_assigned_minutes"] == 150
        assert grid["status"] == "PUBLISHED"


class TestSegregationOfDutiesOutranksTheStateCheck:
    def test_the_conflicted_officer_is_told_they_are_conflicted(self):
        """The officer who cleared the copy cannot rule on it, decided or not.

        "when the incident names an `underwriting_spot_id`, the adjudicating
        officer's `X-User-ID` may not equal that spot's `reviewed_by_user_id`,
        because the officer who cleared a piece of copy may not sit in judgement
        on a complaint about that same copy. A violation answers
        `ERR_SEGREGATION_OF_DUTIES`, and §2.10 places that refusal **above** the
        state check — an officer who cleared the copy is told they are conflicted
        even when the incident has already been adjudicated and is no longer
        `OPEN`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_the_incident_state_check
        """
        setup = _already_adjudicated_sponsor_complaint()

        response = api_client.adjudicate_compliance_incident(
            setup["incident_id"],
            factories.adjudicate_incident_payload(finding="UNFOUNDED"),
            make_compliance_officer_headers(OFFICER_COPY_DESK),
        )

        body = validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 403)
        assert body["error_id"] != "ERR_INVALID_STATE"
        assert response.status_code != 409

    def test_the_refused_ruling_leaves_the_charge_and_the_suspension_standing(self):
        """The first ruling and everything it did survive the refusal.

        An `UNFOUNDED` finding "charges nothing at all and is terminal", so a
        refused second ruling must leave the earlier substantiation in place: a
        `SPONSOR_ID` base "is 1, 2 and 4" so the show keeps its single point and
        its `WATCH` standing, and "when the incident names an
        `underwriting_spot_id` and that spot's `status` is `APPROVED` or
        `APPROVED_WITH_EDITS`, the spot moves to `SUSPENDED` and stops running."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_the_incident_state_check
        """
        setup = _already_adjudicated_sponsor_complaint()

        validate_error(
            api_client.adjudicate_compliance_incident(
                setup["incident_id"],
                factories.adjudicate_incident_payload(finding="UNFOUNDED"),
                make_compliance_officer_headers(OFFICER_COPY_DESK),
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )

        incident = validate_success(
            api_client.get_compliance_incident(setup["incident_id"], OFFICER_HEADERS), 200
        )
        assert incident["status"] == "SUBSTANTIATED"
        assert incident["adjudicated_by_user_id"] == OFFICER_ADJUDICATOR

        program = fixtures.read_program(setup["program_id"])
        assert program["compliance_penalty_points"] == 1
        assert program["compliance_standing"] == "WATCH"

        spot = fixtures.read_spot(setup["spot_id"])
        assert spot["status"] == "SUSPENDED"
        assert spot["reviewed_by_user_id"] == OFFICER_COPY_DESK
        assertions.assert_underwriting_spot(spot)
