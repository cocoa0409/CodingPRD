"""Single writes whose consequences travel four links down the graph.

A missed public-file deadline reaches an airing it never names, and a revoked
board ticket reaches an airing through the show its holder hosts. Both chains
run to completion inside the one request that started them.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success
from test_helpers import (
    DIRECTOR_HEADERS,
    OFFICER_ADJUDICATOR,
    OFFICER_COPY_DESK,
    OFFICER_HEADERS,
    OFFICER_SWEEPER,
    api_client,
    assertions,
    factories,
    fixtures,
    make_compliance_officer_headers,
)

CANDIDATE_COPY = (
    "Paid for by Vega for Council. Marisol Vega asks for your vote on November third."
)
PUBLIC_FILE_DUE = "2026-08-08T00:00:00Z"


def _station_owing_a_political_file_entry():
    """An on-air music show already on watch, carrying a cleared political spot
    whose filing window has just run out."""
    base = fixtures.station()
    grid = fixtures.quota_ready_grid(base["host_id"], base["members"], publish=True)
    episode = fixtures.create_episode(
        grid["music_program_id"],
        grid["music_slot_id"],
        base["host_id"],
        scheduled_start_utc="2026-09-07T20:00:00Z",
    )
    spot = fixtures.create_reviewed_spot(
        officer=OFFICER_COPY_DESK,
        underwriter_name="Vega for Council",
        spot_class="POLITICAL_CANDIDATE",
        copy_text=CANDIDATE_COPY,
        flight_start="2026-08-01T00:00:00Z",
        flight_end="2026-09-30T00:00:00Z",
        assigned_program_id=grid["music_program_id"],
    )
    assert spot["spot"]["status"] == "APPROVED"
    assert spot["spot"]["public_file_status"] == "REQUIRED"
    assertions.assert_instant_equals(
        spot["spot"]["public_file_due_at"], PUBLIC_FILE_DUE, "public_file_due_at"
    )

    seeded = fixtures.substantiated_incident(
        "POLITICAL_CONTENT",
        "MAJOR",
        "2026-08-01T06:30:00Z",
        complainant_note="A candidate segment ran without a balancing offer.",
        program_id=grid["music_program_id"],
    )
    assert seeded["penalty_points"] == 3
    assert fixtures.read_program(grid["music_program_id"])["compliance_standing"] == "WATCH"

    fixtures.set_clock(PUBLIC_FILE_DUE)
    return {
        "host_id": base["host_id"],
        "grid_id": grid["grid_id"],
        "music_program_id": grid["music_program_id"],
        "news_program_id": grid["news_program_id"],
        "music_slot_id": grid["music_slot_id"],
        "news_slot_id": grid["news_slot_id"],
        "episode_id": episode["id"],
        "spot_id": spot["spot_id"],
    }


def _show_whose_host_is_about_to_lose_the_board_ticket():
    """A scheduled show on a still-mutable grid, one airing rostered to its
    host, and a substantiated conflict complaint naming that host."""
    base = fixtures.station()
    chain = fixtures.grid_chain(base["host_id"], base["members"], confirm=True, publish=False)
    episode = fixtures.create_episode(
        chain["program_id"],
        chain["slot_id"],
        base["host_id"],
        scheduled_start_utc="2026-09-07T20:00:00Z",
    )
    incident = fixtures.substantiated_incident(
        "VOLUNTEER_CONFLICT",
        "MAJOR",
        "2026-07-20T18:00:00Z",
        complainant_note="Locked a co-host out of the studio during a handover.",
        respondent_volunteer_id=base["host_id"],
    )
    return {
        "host_id": base["host_id"],
        "board_cert_id": base["certifications"]["BOARD_OPERATION"]["id"],
        "grid_id": chain["grid_id"],
        "slot_id": chain["slot_id"],
        "program_id": chain["program_id"],
        "episode_id": episode["id"],
        "incident_id": incident["id"],
    }


class TestSweepPublicFileCascade:
    def test_the_sweep_raises_the_substantiated_public_file_incident(self):
        """The sweep files the complaint the station owes against itself.

        "That incident is created with `category` `PUBLIC_FILE`, `severity`
        `MAJOR`, `status` `SUBSTANTIATED` from the outset, `penalty_points` 3, its
        `program_id` set to the spot's `assigned_program_id`, its
        `underwriting_spot_id` set to the spot, and its `occurred_at` set to the
        spot's `public_file_due_at` — the moment the obligation was breached, not
        the moment the sweep noticed."

        Design: Difficulty/transitive_cascade/sweep_missing_public_file_cascades_four_links_to_cancelled_episodes
        """
        setup = _station_owing_a_political_file_entry()

        result = fixtures.run_daily_sweep(officer=OFFICER_SWEEPER)

        assert result["missing_public_file_spot_ids"] == [setup["spot_id"]]
        assert len(result["created_incident_ids"]) == 1

        spot = fixtures.read_spot(setup["spot_id"])
        assert spot["public_file_status"] == "MISSING"
        assertions.assert_instant_equals(
            spot["public_file_due_at"], PUBLIC_FILE_DUE, "public_file_due_at"
        )
        assert spot["public_file_posted_at"] is None
        assert spot["status"] == "APPROVED"

        incident = validate_success(
            api_client.get_compliance_incident(
                result["created_incident_ids"][0], OFFICER_HEADERS
            ),
            200,
        )
        assert incident["category"] == "PUBLIC_FILE"
        assert incident["severity"] == "MAJOR"
        assert incident["status"] == "SUBSTANTIATED"
        assert incident["penalty_points"] == 3
        assert incident["program_id"] == setup["music_program_id"]
        assert incident["underwriting_spot_id"] == setup["spot_id"]
        assertions.assert_instant_equals(
            incident["occurred_at"], PUBLIC_FILE_DUE, "occurred_at"
        )

    def test_the_raised_incident_reaches_the_airing_four_links_away(self):
        """Three sweep-charged points restrict the show and cancel its airing.

        "Because that incident is born substantiated, its 3 points are charged to
        the carrying show immediately, which moves that show's
        `compliance_standing` to `WATCH`, or to `RESTRICTED` when the running
        total reaches 6. A show that reaches `RESTRICTED` then loses its air
        position: every occupation of that show in `TENTATIVE` or `CONFIRMED`
        moves to `PREEMPTED`, the owning grid's `total_assigned_minutes` and
        `public_affairs_minutes_pct` are recomputed and its `version` advanced,
        and every `SCHEDULED` airing of that show moves to `CANCELLED`."

        Design: Difficulty/transitive_cascade/sweep_missing_public_file_cascades_four_links_to_cancelled_episodes
        """
        setup = _station_owing_a_political_file_entry()

        fixtures.run_daily_sweep(officer=OFFICER_SWEEPER)

        music = fixtures.read_program(setup["music_program_id"])
        assert music["compliance_penalty_points"] == 6
        assert music["compliance_standing"] == "RESTRICTED"
        assert music["programming_status"] == "ON_AIR_ACTIVE"

        music_slot = fixtures.read_slot(setup["music_slot_id"])
        assert music_slot["status"] == "PREEMPTED"
        assert music_slot["preempted_by_program_id"] is None
        assert fixtures.read_episode(setup["episode_id"])["air_status"] == "CANCELLED"

        grid = fixtures.read_grid(setup["grid_id"])
        assert grid["total_assigned_minutes"] == 30
        assertions.assert_two_decimals_equal(
            grid["public_affairs_minutes_pct"], 100.00, "public_affairs_minutes_pct"
        )
        assert grid["status"] == "PUBLISHED"

        assert fixtures.read_slot(setup["news_slot_id"])["status"] == "CONFIRMED"
        news = fixtures.read_program(setup["news_program_id"])
        assert news["compliance_penalty_points"] == 0
        assert news["compliance_standing"] == "CLEAR"
        assertions.assert_two_decimals_equal(
            news["performance_score"], 100.00, "performance_score"
        )


class TestCertificationRevocationCascade:
    def test_revocation_suspends_the_holder_and_reprices_their_seniority(self):
        """The revoked ticket costs ten points and the roster standing.

        "A supported revocation moves the record `PASSED → REVOKED` and fires a
        four-link cascade in one request: the holder's
        `current_certification_count` is recomputed, their `needs_core_renewal` is
        set true and they are moved to `SUSPENDED`". The certification term is
        "10 points for each live certification", so two live tickets over
        twenty-four whole months of service leave the score at 44.00.

        Design: Difficulty/transitive_cascade/certification_revocation_cascades_four_links_to_orphaned_episodes
        """
        setup = _show_whose_host_is_about_to_lose_the_board_ticket()

        response = api_client.revoke_certification(
            setup["board_cert_id"],
            factories.revoke_certification_payload(
                setup["incident_id"],
                revocation_reason="Studio lockout substantiated; board privileges withdrawn.",
            ),
            make_compliance_officer_headers(OFFICER_ADJUDICATOR),
        )
        revoked = validate_success(response, 200)

        assert revoked["status"] == "REVOKED"

        volunteer = validate_success(
            api_client.get_volunteer(setup["host_id"], DIRECTOR_HEADERS), 200
        )
        assert volunteer["current_certification_count"] == 2
        assert volunteer["needs_core_renewal"] is True
        assert volunteer["status"] == "SUSPENDED"
        assertions.assert_two_decimals_equal(
            volunteer["seniority_score"], 44.00, "seniority_score"
        )

        _, meta = validate_paginated(
            api_client.list_certifications(
                DIRECTOR_HEADERS,
                params={"volunteer_id": setup["host_id"], "status": "PASSED"},
            )
        )
        assert meta["total_count"] == 2

    def test_revocation_orphans_the_airing_without_disturbing_the_grid(self):
        """The airing loses its operator; the occupation keeps its minutes.

        "every `Program` whose `host_volunteer_id` is that volunteer and whose
        `programming_status` is `SCHEDULED` or `ON_AIR_ACTIVE` moves to
        `UNDER_REVIEW`; and every airing of those now-under-review shows whose
        `air_status` is `SCHEDULED` and whose `board_operator_volunteer_id` is
        that volunteer has `board_operator_volunteer_id` cleared to null and
        `needs_substitute` set true." For shows pulled out of `SCHEDULED` "this
        path explicitly does **not** recompute `performance_score`".

        Design: Difficulty/transitive_cascade/certification_revocation_cascades_four_links_to_orphaned_episodes
        """
        setup = _show_whose_host_is_about_to_lose_the_board_ticket()

        validate_success(
            api_client.revoke_certification(
                setup["board_cert_id"],
                factories.revoke_certification_payload(
                    setup["incident_id"],
                    revocation_reason=(
                        "Studio lockout substantiated; board privileges withdrawn."
                    ),
                ),
                make_compliance_officer_headers(OFFICER_ADJUDICATOR),
            ),
            200,
        )

        program = fixtures.read_program(setup["program_id"])
        assert program["programming_status"] == "UNDER_REVIEW"
        assert program["performance_score"] is None
        assert program["compliance_standing"] == "CLEAR"
        assert program["compliance_penalty_points"] == 0

        episode = fixtures.read_episode(setup["episode_id"])
        assert episode["board_operator_volunteer_id"] is None
        assert episode["needs_substitute"] is True
        assert episode["air_status"] == "SCHEDULED"

        _, meta = validate_paginated(
            api_client.list_episodes(
                DIRECTOR_HEADERS, params={"board_operator_volunteer_id": setup["host_id"]}
            )
        )
        assert meta["total_count"] == 0

        assert fixtures.read_slot(setup["slot_id"])["status"] == "CONFIRMED"
        assert fixtures.read_grid(setup["grid_id"])["total_assigned_minutes"] == 120
