"""Endpoint shapes: a partial update, a bodyless action, a link write and a read.

The four styles of write in this API behave differently and are checked
accordingly — a PATCH must leave unmentioned fields alone, an action endpoint
carries its whole contract in a state change, an occupation write joins a grid from
the path to a show from the body, and a grid read must serve figures the server
derived rather than fields a client sent.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import (
    DEVELOPMENT_HEADERS,
    DIRECTOR_HEADERS,
    api_client,
    assertions,
    factories,
    fixtures,
    make_committee_member_headers,
)

CLOCK = "2026-08-01T00:00:00Z"
FLIGHT_START = "2026-08-05T00:00:00Z"
FLIGHT_END = "2026-09-05T00:00:00Z"


def _approved_music_show_and_a_draft_grid():
    """The canonical approved sixty-minute music show alongside a grid that has
    not yet been written to."""
    base = fixtures.station()
    approved = fixtures.create_approved_program(
        base["host_id"],
        base["members"],
        title="Delta Blues Hour",
        format_code="MUSIC",
        language_code="EN",
        requested_daypart="MIDDAY",
        requested_duration_minutes=60,
    )
    grid = fixtures.create_grid()
    return {
        "members": base["members"],
        "program_id": approved["program_id"],
        "decided_proposal": approved["proposal"],
        "grid_id": grid["id"],
        "grid_version": grid["version"],
    }


def _place_the_midday_hour(setup):
    return api_client.create_slot_assignment(
        setup["grid_id"],
        factories.create_slot_assignment_payload(
            setup["program_id"],
            setup["grid_version"],
            day_of_week=1,
            start_minute=540,
            duration_minutes=60,
        ),
        DIRECTOR_HEADERS,
    )


class TestPartialUpdate:
    def test_a_draft_spots_copy_is_replaced_and_nothing_else_moves(self):
        """A partial body rewrites one field, advances the version and stops there.

        "Development staff may amend a `DRAFT` spot's `copy_text`,
        `assigned_program_id`, `flight_start` and `flight_end` — the
        `underwriter_name` is fixed at drafting". A new spot sits "on `status`
        `DRAFT` with `noncommercial_risk_score` 0, an empty `compliance_flags`
        array", and screening happens at review, so an amendment leaves both
        untouched while `version` "increases by exactly 1 on every mutation of the
        row".

        Design: Corner/endpoints/underwriting_spot_patch_updates_a_draft_copy
        """
        fixtures.set_clock(CLOCK)
        spot = fixtures.create_spot(
            underwriter_name="Bluebird Bakery",
            spot_class="UNDERWRITING",
            copy_text="Fresh sourdough is baked daily on Fifth Street.",
            flight_start=FLIGHT_START,
            flight_end=FLIGHT_END,
        )
        assert spot["version"] == 1

        amended = validate_success(
            api_client.update_underwriting_spot(
                spot["id"],
                {"copy_text": "Bluebird Bakery bakes fresh sourdough daily on Fifth Street."},
                DEVELOPMENT_HEADERS,
            ),
            200,
        )

        assert amended["copy_text"] == (
            "Bluebird Bakery bakes fresh sourdough daily on Fifth Street."
        )
        assert amended["underwriter_name"] == "Bluebird Bakery"
        assertions.assert_instant_equals(amended["flight_start"], FLIGHT_START, "flight_start")
        assert amended["status"] == "DRAFT"
        assert amended["version"] == 2
        assert amended["noncommercial_risk_score"] == 0
        assert amended["compliance_flags"] == []
        assertions.assert_underwriting_spot(amended)


class TestActionEndpoint:
    def test_activation_moves_the_drive_and_unlocks_its_child_writes(self):
        """A bodyless POST whose whole contract is one transition.

        "A new drive sits on `status` `PLANNED` with all five money aggregates at 0
        and `attainment_pct` at `0.00`. Activation moves it `PLANNED → ACTIVE`, which
        is what makes phone-bank shifts and pledges writable: rostering a shift or
        taking a pledge against a drive that is `PLANNED` or `CLOSED` is refused with
        `ERR_DRIVE_NOT_ACTIVE`."

        Design: Corner/endpoints/membership_drive_activate_is_a_state_changing_action_endpoint
        """
        fixtures.set_clock(CLOCK)
        drive = fixtures.create_drive(
            name="Fall Drive 2026",
            goal_cents=500000,
            start_at="2026-08-01T00:00:00Z",
            end_at="2026-08-10T00:00:00Z",
            phone_line_count=2,
        )
        assert drive["status"] == "PLANNED"

        activated = validate_success(
            api_client.activate_membership_drive(drive["id"], DEVELOPMENT_HEADERS), 200
        )
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == 2
        assert activated["gross_pledged_cents"] == 0
        assert activated["pledged_total_cents"] == 0
        assert activated["fulfilled_total_cents"] == 0
        assert activated["refunded_total_cents"] == 0
        assert activated["lapsed_total_cents"] == 0
        assertions.assert_two_decimals_equal(
            activated["attainment_pct"], 0.00, "attainment_pct"
        )
        assertions.assert_membership_drive(activated)

        pledge = validate_success(
            api_client.create_pledge(
                factories.create_pledge_payload(
                    drive["id"], donor_name="Iris Vance", amount_cents=6000, wants_premium=False
                ),
                DEVELOPMENT_HEADERS,
            ),
            201,
        )
        assert pledge["drive_id"] == drive["id"]


class TestCrossReferenceLink:
    def test_one_write_joins_the_grid_from_the_path_to_the_show_from_the_body(self):
        """Both foreign keys come back, and the grid moves off `DRAFT` in the same call.

        Uniform fours weight to `4.00` — the format-fit mean "at 0.40, the diversity
        mean at 0.35 and the quality mean at 0.25" — and "a `composite_score` of at
        least `4.00` moves the proposal `IN_COMMITTEE → APPROVED`". "A new occupation
        lands on `status` `TENTATIVE` with a null `preempted_by_program_id` ... The
        very first occupation created on a `DRAFT` grid moves that grid `DRAFT →
        IN_REVIEW`", and only a confirmation moves the show, because "When this is the
        show's **first** confirmation it moves `APPROVED_UNSCHEDULED → SCHEDULED`".

        Design: Corner/endpoints/slot_assignment_create_links_a_grid_to_a_program
        """
        setup = _approved_music_show_and_a_draft_grid()
        assertions.assert_two_decimals_equal(
            setup["decided_proposal"]["composite_score"], 4.00, "composite_score"
        )
        assert setup["decided_proposal"]["status"] == "APPROVED"

        placed = validate_success(_place_the_midday_hour(setup), 201)
        assert placed["grid_id"] == setup["grid_id"]
        assert placed["program_id"] == setup["program_id"]
        assert placed["status"] == "TENTATIVE"
        assert placed["day_of_week"] == 1
        assert placed["start_minute"] == 540
        assert placed["duration_minutes"] == 60
        assert placed["preempted_by_program_id"] is None
        assertions.assert_slot_assignment(placed)

        grid = fixtures.read_grid(setup["grid_id"])
        assert grid["status"] == "IN_REVIEW"
        assert grid["total_assigned_minutes"] == 60

        assert (
            fixtures.read_program(setup["program_id"])["programming_status"]
            == "APPROVED_UNSCHEDULED"
        )


class TestComputedRead:
    def test_the_grid_read_serves_the_derived_minutes_and_share(self):
        """A pure read returns figures no client ever sent.

        The grid's figures are "recomputed on every occupation created, confirmed,
        released, preempted or reinstated on it", and the share counts only
        public-affairs formats, so a lone music hour reads `0.00`. `published_at`
        stays null until "A successful publication stamps `published_at` with the
        clock", and the show reaches `SCHEDULED` on its first confirmation.

        Design: Corner/endpoints/grid_read_exposes_the_derived_minute_and_share_fields
        """
        setup = _approved_music_show_and_a_draft_grid()
        placed = validate_success(_place_the_midday_hour(setup), 201)
        fixtures.confirm_slot(placed["id"])

        data = validate_success(
            api_client.get_schedule_grid(
                setup["grid_id"], make_committee_member_headers(setup["members"][0]["id"])
            ),
            200,
        )
        assert data["total_assigned_minutes"] == 60
        assertions.assert_two_decimals_equal(
            data["public_affairs_minutes_pct"], 0.00, "public_affairs_minutes_pct"
        )
        assert data["status"] == "IN_REVIEW"
        assert data["published_at"] is None
        assertions.assert_schedule_grid(data)

        assert (
            fixtures.read_program(setup["program_id"])["programming_status"] == "SCHEDULED"
        )


class TestConditionalAction:
    def test_reinstating_a_healthy_occupation_is_refused(self):
        """The action is defined from one source state only.

        "Reinstatement is the compensating action for preemption, moving an
        occupation `PREEMPTED → CONFIRMED`", so aimed at a `CONFIRMED` occupation it
        is a transition "not declared for the record's current state" and answers
        `ERR_INVALID_STATE`. A refused call recomputes nothing.

        Design: Corner/endpoints/reinstate_is_a_conditional_action_and_refuses_a_confirmed_slot
        """
        setup = _approved_music_show_and_a_draft_grid()
        placed = validate_success(_place_the_midday_hour(setup), 201)
        confirmed = fixtures.confirm_slot(placed["id"])
        assert confirmed["status"] == "CONFIRMED"

        validate_error(
            api_client.reinstate_slot_assignment(placed["id"], DIRECTOR_HEADERS),
            "ERR_INVALID_STATE",
            409,
        )

        slot = fixtures.read_slot(placed["id"])
        assert slot["status"] == "CONFIRMED"
        assert slot["preempted_by_program_id"] is None
        assert fixtures.read_grid(setup["grid_id"])["total_assigned_minutes"] == 60
