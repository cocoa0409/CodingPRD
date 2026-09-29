"""
Collection surfaces: the one listing that reverses the default order, the filters
that narrow a projection without touching the ledger, and the administrative call
whose response reports the work it just did.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_page_meta,
    assert_two_dp,
    assert_unit_ledger,
    expected_sla_credit_cents,
    ids_of,
)
from test_helpers.constants import (
    CONSENT_EXPIRED,
    HALT_CONSENT_EXPIRED,
    INSTALLATION_VALIDATED,
    RELEASE_EXPIRED,
    RELEASE_NONE,
    RESULT_FAIL,
    RESULT_PASS,
    SCOPE_BIOMETRIC,
    SCOPE_POSITIONAL,
    SESSION_ACTIVE,
    SESSION_SUSPENDED,
    TIER_GOLD,
)
from test_helpers.test_users import (
    ENGINEER_ALT_HEADERS,
    ENGINEER_HEADERS,
    ENGINEER_PRIMARY,
    OPS_HEADERS,
    OPS_PRIMARY,
    REVIEWER_HEADERS,
    STATISTICIAN_HEADERS,
    make_club_data_officer_headers,
)

CLOCK_ONE_PM = "2026-08-01T13:00:00Z"
CONSENT_EXPIRY = "2026-08-01T20:00:00Z"
BIOMETRIC_SCOPE = [SCOPE_POSITIONAL, SCOPE_BIOMETRIC]


# ---------------------------------------------------------------------------
# The one listing that runs newest first
# ---------------------------------------------------------------------------

def test_the_calibration_history_is_paged_newest_first(api, clock):
    """PRD §2.3: "List results are ordered by `created_at` ascending unless a specific
    endpoint states otherwise; the calibration-run history of a rig is the one
    deliberate exception and is returned newest first, so that the run currently
    governing the rig's accuracy claim is the first row a reader sees."
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and
    `has_more` inside `meta`, where `total_count` is the number of rows matching the
    filters before pagination is applied and `has_more` indicates whether rows remain
    beyond the returned page."
    PRD §3.2: "The recording always moves the rig into `CALIBRATING`, whether it came
    from `DEPLOYED` or from `RECALIBRATION_REQUIRED`, and in both cases the same effects
    follow: the run row is created, the rig's `calibration_run_count` rises by one, and
    its four mirror fields — `latest_run_result`, `latest_run_composite_rms_mm`,
    `latest_run_recorded_at_utc` and `latest_run_engineer_user_id` — are refreshed from
    the run that now has the greatest `recorded_at_utc` (with `created_at` ascending as
    the tie-break, so the last-written of two runs sharing an instant wins)."

    A limit=1 page of two runs returns the second run, not the first.

    The failing run is not discarded when the passing one lands: it is still
    reachable one offset further down, because the history is an audit trail.

    Design: Corner/endpoints/calibration_runs_are_listed_newest_first_under_pagination
    """
    venue = fx.register_venue(api)
    rig = fx.deploy_rig(api, venue["id"], modality="LIDAR")

    older = get_success_data(
        api.create_calibration_run(
            rig["id"], fac.uniform_calibration_run_payload(150.0), ENGINEER_HEADERS
        ),
        expected_status=201,
    )
    validate_success(api.set_clock(CLOCK_ONE_PM, OPS_HEADERS))
    newer = get_success_data(
        api.create_calibration_run(
            rig["id"], fac.uniform_calibration_run_payload(90.0), ENGINEER_HEADERS
        ),
        expected_status=201,
    )

    first_page, first_meta = validate_paginated(
        api.list_calibration_runs(
            rig["id"], ENGINEER_ALT_HEADERS, params={"limit": 1, "offset": 0}
        )
    )
    assert_page_meta(first_meta, limit=1, offset=0, total_count=2, has_more=True)
    assert len(first_page) == 1
    assert first_page[0]["id"] == newer["id"]
    assert first_page[0]["result"] == RESULT_PASS
    assert first_page[0]["recorded_at_utc"] == CLOCK_ONE_PM
    assert first_page[0]["recorded_by_user_id"] == ENGINEER_PRIMARY

    second_page, second_meta = validate_paginated(
        api.list_calibration_runs(
            rig["id"], ENGINEER_ALT_HEADERS, params={"limit": 1, "offset": 1}
        )
    )
    assert_page_meta(second_meta, limit=1, offset=1, total_count=2, has_more=False)
    assert len(second_page) == 1
    assert second_page[0]["id"] == older["id"]
    assert second_page[0]["result"] == RESULT_FAIL
    assert_two_dp(second_page[0]["composite_rms_mm"], 150.00)

    rig_after = validate_success(api.get_installation(rig["id"], ENGINEER_HEADERS))
    assert rig_after["calibration_run_count"] == 2
    assert rig_after["latest_run_result"] == RESULT_PASS
    assert rig_after["latest_run_recorded_at_utc"] == CLOCK_ONE_PM
    assert rig_after["status"] == INSTALLATION_VALIDATED


# ---------------------------------------------------------------------------
# A filtered projection over immutable rows
# ---------------------------------------------------------------------------

def test_the_audit_trail_narrows_to_the_breaching_sample_alone(api, clock):
    """PRD §2.3: "The venue installation list accepts `status`; the player list accepts
    `club_id`; the consent-record list of a player accepts `status`; the game list
    accepts `venue_id`, `home_club_id`, `away_club_id` and `collection_status`; the
    event-tag list accepts `game_id`, `player_id` and `review_status`; the
    correction-request list of a tag accepts `status`; the rights-window list of a game
    accepts `rights_class` and `status`; the feed-session list accepts `game_id`,
    `licensee_id`, `rights_window_id` and `status`; the licensee audit trail accepts
    `feed_session_id` and `sla_breach`; and the normalization-run list of a game accepts
    `basis` and `metric_code`."
    PRD §2.3: "A session's usage records are returned in chronological order, which for
    immutable records coincides with `created_at` ascending."
    PRD §3.8: "A breach raises the session's `sla_breach_count` by one and the
    licensee's `audit_flag_count` by one, and it credits the licensee: a quarter of the
    record's charge — the record's `units_charged` multiplied by the tier rate,
    multiplied by 0.25 and rounded half up to whole cents — is added to the licensee's
    `sla_credit_cents`."

    One sample over the window SLA, one under it, three views of both.

    The filter changes what a reader sees and nothing else: the session and the
    licensee still account for both samples.

    Design: Corner/endpoints/usage_records_are_filterable_by_the_sla_breach_flag
    """
    world = fx.active_session_world(api, window_overrides={"max_latency_ms": 400})

    breaching = get_success_data(
        api.create_usage_record(
            world.session_id,
            fac.usage_record_payload(duration_seconds=60, latency_p95_ms=500),
            world.licensee_headers,
        ),
        expected_status=201,
    )
    clean = get_success_data(
        api.create_usage_record(
            world.session_id,
            fac.usage_record_payload(
                sampled_at_utc="2026-08-01T18:10:00Z",
                duration_seconds=60,
                latency_p95_ms=300,
            ),
            world.licensee_headers,
        ),
        expected_status=201,
    )

    flagged, flagged_meta = validate_paginated(
        api.list_licensee_usage_records(
            world.licensee_id, OPS_HEADERS, params={"sla_breach": "true"}
        )
    )
    assert flagged_meta["total_count"] == 1
    assert len(flagged) == 1
    assert flagged[0]["id"] == breaching["id"]
    assert flagged[0]["sla_breach"] is True
    assert flagged[0]["latency_p95_ms"] == 500
    assert flagged[0]["units_charged"] == 30

    everything, everything_meta = validate_paginated(
        api.list_licensee_usage_records(world.licensee_id, world.licensee_headers)
    )
    assert everything_meta["total_count"] == 2
    assert everything_meta["has_more"] is False
    assert ids_of(everything) == [breaching["id"], clean["id"]]

    per_session, per_session_meta = validate_paginated(
        api.list_usage_records(world.session_id, world.licensee_headers)
    )
    assert per_session_meta["total_count"] == 2
    for row in per_session:
        assert row["feed_session_id"] == world.session_id
        assert row["licensee_id"] == world.licensee_id

    session = validate_success(api.get_feed_session(world.session_id, OPS_HEADERS))
    assert session["metered_units"] == 60
    assert session["usage_record_count"] == 2
    assert session["sla_breach_count"] == 1
    assert session["status"] == SESSION_ACTIVE

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert licensee["audit_flag_count"] == 1
    assert licensee["sla_credit_cents"] == 165
    assert licensee["sla_credit_cents"] == expected_sla_credit_cents(30, TIER_GOLD)


# ---------------------------------------------------------------------------
# Moving the clock is work, and the response reports it
# ---------------------------------------------------------------------------

def _biometric_session_world(api: ApiClient) -> fx.World:
    """A biometric tag and a biometric feed session, both riding one consent."""
    world = fx.certified_venue(api)
    clubs = fx.register_clubs(api)
    world.home_club = clubs["home"]
    world.away_club = clubs["away"]
    world.player = fx.register_player(api, world.home_club["id"])
    world.consent = get_success_data(
        api.create_consent_record(
            world.player["id"],
            fac.consent_record_payload(expires_at_utc=CONSENT_EXPIRY),
            world.home_officer,
        )
    )
    validate_success(api.ratify_consent_record(world.consent["id"], OPS_HEADERS))
    world.game = get_success_data(
        api.create_game(
            fac.game_payload(
                world.venue["id"], world.home_club["id"], world.away_club["id"]
            ),
            OPS_HEADERS,
        )
    )
    world.game = validate_success(api.open_collection(world.game["id"], OPS_HEADERS))
    world.licensee = fx.onboard_licensee(api, biometric_entitled=True)
    world.window = fx.allocate_window(
        api,
        world.game_id,
        world.licensee_id,
        window_end_utc="2026-08-01T21:00:00Z",
        max_latency_ms=5000,
        allowed_scopes=BIOMETRIC_SCOPE,
    )
    world.session = fx.open_session(
        api,
        world.licensee_id,
        world.game_id,
        world.window_id,
        requested_latency_ms=300,
        scope=BIOMETRIC_SCOPE,
    )
    current = validate_success(api.get_game(world.game_id, STATISTICIAN_HEADERS))
    world.tag = fx.create_tag(
        api,
        world.game_id,
        world.player["id"],
        current["version"],
        STATISTICIAN_HEADERS,
        biometric_payload_present=True,
    )
    return world


def test_advancing_the_clock_reports_the_expiry_and_suspension_census(api, clock):
    """PRD §2.6: "Every `ConsentRecord` in `ACTIVE` status whose `expires_at_utc` is at or
    before the new clock value is materialised into `EXPIRED`, and the records are
    processed in ascending `expires_at_utc` order with `created_at` ascending as the
    tie-break, so that the observable order of the resulting cascades is deterministic."
    PRD §2.6: "The response reports the resulting `current_utc`, the
    `expired_consent_record_count` and the `suspended_feed_session_count`."
    PRD §3.3: "When the logical clock advances past an active record's `expires_at_utc`,
    that record moves `ACTIVE → EXPIRED` with `terminated_at_utc` set to the new clock
    value and `active_consent_record_id` cleared, the player's `biometric_release_state`
    moves from `GRANTED` to `EXPIRED`, and the identical tag-masking and
    biometric-session-suspension cascade runs — the only difference being that the
    suspended sessions carry `halt_reason` of `CONSENT_EXPIRED` rather than
    `CONSENT_WITHDRAWN`."

    The response counts one lapsed consent and one halted session.

    Reaching the consent's expiry instant is enough — the boundary is inclusive —
    and the halt is a suspension, not a settlement, so the reservation stands.

    Design: Corner/endpoints/clock_endpoint_reports_the_consent_expiry_and_suspension_census
    """
    world = _biometric_session_world(api)

    advanced = validate_success(api.set_clock(CONSENT_EXPIRY, OPS_HEADERS))
    assert advanced["current_utc"] == CONSENT_EXPIRY
    assert advanced["expired_consent_record_count"] == 1
    assert advanced["suspended_feed_session_count"] == 1

    rows, meta = validate_paginated(
        api.list_consent_records(
            world.player["id"], OPS_HEADERS, params={"status": CONSENT_EXPIRED}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == world.consent["id"]
    assert rows[0]["terminated_at_utc"] == CONSENT_EXPIRY
    assert rows[0]["ratified_by_user_id"] == OPS_PRIMARY

    player = validate_success(api.get_player(world.player["id"], OPS_HEADERS))
    assert player["biometric_release_state"] == RELEASE_EXPIRED
    assert player["active_consent_record_id"] is None
    assert player["masked_tag_count"] == 1

    tag = validate_success(api.get_event_tag(world.tag_id, STATISTICIAN_HEADERS))
    assert tag["biometric_masked"] is True

    session = validate_success(api.get_feed_session(world.session_id, OPS_HEADERS))
    assert session["status"] == SESSION_SUSPENDED
    assert session["halt_reason"] == HALT_CONSENT_EXPIRED
    assert session["reserved_units"] == 720
    assert session["metered_units"] == 0

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert_unit_ledger(licensee, available=4280, reserved=720, consumed=0)


# ---------------------------------------------------------------------------
# Filter first, then page
# ---------------------------------------------------------------------------

def test_a_club_filter_narrows_the_roster_before_the_page_is_cut(api):
    """PRD §2.3: "Filtering parameters, where a list endpoint offers them, are combined
    conjunctively with each other and with pagination."
    PRD §3.3: "The player list may be narrowed by `club_id`, and `LeagueDataOps`,
    `ClubDataOfficer`, `Statistician` and `QualityReviewer` may all read players — the
    tagging and review desks need to see `biometric_release_state` before they attach
    biometric attributes to anything."
    PRD §2.3: "`limit` controls page size: its default is 10, its minimum accepted value
    is 1, and its maximum accepted value is 100."
    PRD §3.3: "A club's `roster_size` is derived, starting at zero and rising by one for
    every player registered against it."

    Three players, two clubs, and an offset that must land inside the filter.

    Design: Corner/endpoints/players_listing_filters_by_club_and_pages_the_remainder
    """
    clubs = fx.register_clubs(api)
    home = clubs["home"]
    away = clubs["away"]
    fx.register_player(api, home["id"])
    second = fx.register_player(
        api,
        home["id"],
        headers=make_club_data_officer_headers(home["id"]),
        full_name="Kai Larsen",
        jersey_number=4,
    )
    fx.register_player(api, away["id"], full_name="Bo Chen", jersey_number=7)

    everyone, everyone_meta = validate_paginated(api.list_players(STATISTICIAN_HEADERS))
    assert_page_meta(everyone_meta, limit=10, offset=0, total_count=3, has_more=False)
    for row in everyone:
        assert row["biometric_release_state"] == RELEASE_NONE
        assert row["active_consent_record_id"] is None
        assert row["masked_tag_count"] == 0

    filtered, filtered_meta = validate_paginated(
        api.list_players(STATISTICIAN_HEADERS, params={"club_id": home["id"]})
    )
    assert filtered_meta["total_count"] == 2
    for row in filtered:
        assert row["club_id"] == home["id"]

    page, page_meta = validate_paginated(
        api.list_players(
            REVIEWER_HEADERS, params={"club_id": home["id"], "limit": 1, "offset": 1}
        )
    )
    assert_page_meta(page_meta, limit=1, offset=1, total_count=2, has_more=False)
    assert len(page) == 1
    assert page[0]["id"] == second["id"]

    assert validate_success(api.get_club(home["id"], OPS_HEADERS))["roster_size"] == 2
    assert validate_success(api.get_club(away["id"], OPS_HEADERS))["roster_size"] == 1
