"""
Read-after-write: every derived figure is already final in the response that
caused it, and repeating the read never changes the answer.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_game_dimensions,
    assert_installation_census,
    assert_minute_ledger,
    assert_quality_index,
    assert_tag_census,
    assert_two_dp,
)
from test_helpers.constants import (
    CERTIFICATION_PENDING,
    CERTIFICATION_PROVISIONAL,
    CLOCK_NOON,
    COLLECTION_LIVE,
    COLLECTION_SCHEDULED,
    INSTALLATION_CERTIFIED,
    POSTURE_CERTIFIED,
    RESULT_PASS,
    TAG_ACCEPTED,
)
from test_helpers.test_users import (
    ENGINEER_HEADERS,
    OPS_HEADERS,
    OPS_PRIMARY,
    REVIEWER_HEADERS,
    REVIEWER_PRIMARY,
    STATISTICIAN_HEADERS,
)
from test_helpers.types import Json

PASSING_AXIS_MM = 90.0
TAG_CLOCK_MS = 60000
TAG_CONFIDENCE = 0.9

VENUE_DERIVED_FIELDS = [
    "data_posture",
    "certified_installation_count",
    "recalibrating_installation_count",
    "uncertified_installation_count",
    "retired_installation_count",
    "active_installation_count",
]
GAME_DERIVED_FIELDS = [
    "collection_status",
    "certification_status",
    "quality_index",
    "draft_tag_count",
    "submitted_tag_count",
    "accepted_tag_count",
    "under_correction_tag_count",
    "superseded_tag_count",
    "total_tag_count",
    "league_reserve_minutes",
    "net_allocatable_minutes",
    "allocated_minutes_total",
    "remaining_allocatable_minutes",
    "version",
]


def _projection(row: Json, fields) -> Json:
    """The derived subset of a row, for comparing one read against the next."""
    return {field: row[field] for field in fields}


def test_every_derived_figure_is_final_in_the_response_that_produced_it(api, clock):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."
    PRD §2.11: "A cascade is not optional and not deferred — by the time the request
    that triggered it returns, every affected row is already in its new state, with
    `updated_at` refreshed and `version` incremented on every row the cascade touched."
    PRD §3.1: "The venue's **data posture** is not an input; it is a derived gate over
    the venue's rigs, and it is re-derived from scratch on every single installation
    status change — when a calibration run is recorded, when a passing run
    auto-validates a rig, when a rig is certified, when drift is flagged, and when a rig
    is retired."

    The verdict, the posture, the ledger and the index all arrive at once.

    Each write response is compared against the read that follows it, and each
    read against a second identical read, so nothing is allowed to settle into
    place a request later.

    Design: Corner/consistency_model/derived_fields_are_already_correct_in_the_writing_response
    """
    venue = fx.register_venue(api)
    rig = fx.deploy_rig(api, venue["id"])
    clubs = fx.register_clubs(api)
    player = fx.register_player(api, clubs["home"]["id"])

    run = get_success_data(
        api.create_calibration_run(
            rig["id"],
            fac.uniform_calibration_run_payload(PASSING_AXIS_MM),
            ENGINEER_HEADERS,
        ),
        expected_status=201,
    )
    assert_two_dp(run["composite_rms_mm"], 90.00)
    assert run["result"] == RESULT_PASS

    certified = validate_success(api.certify_installation(rig["id"], OPS_HEADERS))
    assert certified["status"] == INSTALLATION_CERTIFIED
    assert certified["certified_at_utc"] == CLOCK_NOON
    assert certified["certified_by_user_id"] == OPS_PRIMARY
    assert certified["latest_run_result"] == RESULT_PASS
    assert_two_dp(certified["latest_run_composite_rms_mm"], 90.00)

    venue_read = validate_success(api.get_venue(venue["id"], OPS_HEADERS))
    assert venue_read["data_posture"] == POSTURE_CERTIFIED
    assert_installation_census(venue_read, certified=1, recalibrating=0, uncertified=0)
    venue_reread = validate_success(api.get_venue(venue["id"], OPS_HEADERS))
    assert _projection(venue_reread, VENUE_DERIVED_FIELDS) == _projection(
        venue_read, VENUE_DERIVED_FIELDS
    )

    game = get_success_data(
        api.create_game(
            fac.game_payload(venue["id"], clubs["home"]["id"], clubs["away"]["id"]),
            OPS_HEADERS,
        ),
        expected_status=201,
    )
    assert_minute_ledger(
        game,
        league_reserve_minutes=36,
        net_allocatable_minutes=204,
        allocated_minutes_total=0,
        remaining_allocatable_minutes=204,
    )
    assert_quality_index(game, 0.0)
    assert_game_dimensions(game, COLLECTION_SCHEDULED, CERTIFICATION_PENDING)

    live = validate_success(api.open_collection(game["id"], OPS_HEADERS))
    tag = fx.create_tag(
        api,
        game["id"],
        player["id"],
        live["version"],
        STATISTICIAN_HEADERS,
        clock_ms=TAG_CLOCK_MS,
        confidence=TAG_CONFIDENCE,
    )
    validate_success(api.submit_event_tag(tag["id"], STATISTICIAN_HEADERS))

    accepted = validate_success(api.accept_event_tag(tag["id"], REVIEWER_HEADERS))
    assert accepted["review_status"] == TAG_ACCEPTED
    assert accepted["reviewed_by_user_id"] == REVIEWER_PRIMARY

    game_read = validate_success(api.get_game(game["id"], OPS_HEADERS))
    assert_tag_census(
        game_read,
        draft=0,
        submitted=0,
        accepted=1,
        under_correction=0,
        superseded=0,
        total=1,
    )
    assert_game_dimensions(game_read, COLLECTION_LIVE, CERTIFICATION_PROVISIONAL)
    assert_quality_index(game_read, 0.8000)

    game_reread = validate_success(api.get_game(game["id"], STATISTICIAN_HEADERS))
    assert _projection(game_reread, GAME_DERIVED_FIELDS) == _projection(
        game_read, GAME_DERIVED_FIELDS
    )
    tag_reread = validate_success(api.get_event_tag(tag["id"], REVIEWER_HEADERS))
    assert tag_reread["review_status"] == accepted["review_status"]
    assert tag_reread["reviewed_by_user_id"] == accepted["reviewed_by_user_id"]
    assert tag_reread["game_version_at_tag"] == accepted["game_version_at_tag"]
