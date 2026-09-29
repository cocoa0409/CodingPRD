"""
Rejection order and inclusive bounds: which of several simultaneous violations a
caller is told about, and which request is admitted while sitting exactly on the
threshold that governs it.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_ALLOCATION_POOL_EXHAUSTED,
    ERR_BIOMETRIC_SCOPE_NOT_LICENSED,
    ERR_CALIBRATION_EXPIRED,
    ERR_CALIBRATION_NOT_PASSING,
    ERR_CBA_VERSION_MISMATCH,
    ERR_CONSENT_ALREADY_PENDING,
    ERR_CONSENT_EXPIRY_IN_PAST,
    ERR_CORRECTION_ALREADY_RESOLVED,
    ERR_GAME_NOT_COLLECTED,
    ERR_GAME_NOT_COLLECTING,
    ERR_INVALID_WINDOW_BOUNDS,
    ERR_LATENCY_BELOW_VENUE_FLOOR,
    ERR_LATENCY_SLA_UNSATISFIABLE,
    ERR_NORMALIZATION_SEGMENTS_EMPTY,
    ERR_OPEN_CORRECTIONS,
    ERR_QUALITY_INDEX_BELOW_THRESHOLD,
    ERR_RIGHTS_HOLDER_MISMATCH,
    ERR_RIGHTS_WINDOW_GAME_MISMATCH,
    ERR_RIGHTS_WINDOW_REVOKED,
    ERR_SCOPE_NOT_IN_RIGHTS_WINDOW,
    ERR_SCOPE_NOT_IN_TIER,
    ERR_SESSION_NOT_ACTIVE,
    ERR_SESSION_RESERVATION_EXCEEDED,
    ERR_SESSION_WINDOW_OUTSIDE_RIGHTS,
)
from test_helpers.assertions import (
    assert_installation_census,
    assert_minute_ledger,
    assert_quality_index,
    assert_tag_census,
    assert_two_dp,
    assert_unit_ledger,
    expected_charge_cents,
    expected_quality_index,
    expected_raw_generation_value,
    expected_record_units,
    expected_reserved_units,
)
from test_helpers.constants import (
    CERTIFICATION_OFFICIAL,
    CERTIFICATION_PROVISIONAL,
    CLOCK_NOON,
    COLLECTION_ARCHIVED,
    COLLECTION_COLLECTED,
    COLLECTION_LIVE,
    CONSENT_PENDING,
    CORRECTION_REJECTED,
    DELIVERY_POST_GAME,
    HALT_CLIENT_REQUEST,
    HOLDER_LEAGUE,
    INSTALLATION_CALIBRATING,
    INSTALLATION_CERTIFIED,
    INSTALLATION_VALIDATED,
    MAPPING_VERSION,
    POSTURE_CERTIFIED,
    QUALITY_FLAG_CLEAN,
    QUALITY_INDEX_FLOOR,
    RELEASE_NONE,
    RESULT_FAIL,
    RESULT_PASS,
    RIGHTS_CLASS_BROADCAST_LIVE,
    SCOPE_BIOMETRIC,
    SCOPE_EVENT,
    SCOPE_POSITIONAL,
    SESSION_ACTIVE,
    SESSION_TERMINATED,
    TAG_ACCEPTED,
    TERRITORY_GLOBAL,
    TIER_GOLD,
    TIER_SILVER,
    WINDOW_REVOKED,
)
from test_helpers.test_users import (
    ENGINEER_ALT_HEADERS,
    ENGINEER_HEADERS,
    OPS_HEADERS,
    REVIEWER_HEADERS,
    REVIEWER_PRIMARY,
    STATISTICIAN_HEADERS,
    make_club_data_officer_headers,
    make_licensee_headers,
)

PAST_CONSENT_EXPIRY = "2026-07-01T00:00:00Z"
VENUE_LATENCY_FLOOR_MS = 200
CLOCK_PLUS_72H = "2026-08-04T12:00:00Z"
CLOCK_PLUS_73H = "2026-08-04T13:00:00Z"
SINGLE_SEGMENT = [120.5]
ACCEPTED_CONFIDENCE = 0.9


# ---------------------------------------------------------------------------
# Three consent rules broken by one body
# ---------------------------------------------------------------------------

def test_the_consent_ladder_reports_the_agreement_before_the_calendar(api, clock):
    """PRD §2.10: "Checks are evaluated in the following fixed order, and the first
    violated check determines the response."
    PRD §3.3: "The agreement version is not free text: it must equal the current
    collective bargaining agreement version, whose fixed value is `CBA-2026A`, and any
    other value is refused with `ERR_CBA_VERSION_MISMATCH`."
    PRD §3.3: "The interval must be coherent and forward-looking — `effective_from_utc`
    strictly earlier than `expires_at_utc`, and `expires_at_utc` strictly later than the
    current logical clock — with `ERR_CONSENT_EXPIRY_IN_PAST` covering both failures."
    PRD §3.3: "A player may hold at most one live record per scope: if the player
    already has a record in `PENDING` or `ACTIVE` status covering the same `scope`, the
    filing is refused with `ERR_CONSENT_ALREADY_PENDING`."

    Four filings, each fixing exactly one rung of the ladder.

    The first body breaks the agreement rule and the expiry rule together and
    must answer on the agreement; the second answers on the calendar; the third
    is accepted; the fourth collides with the record the third created.

    Design: Corner/validations/cba_version_check_outranks_expiry_and_duplicate_consent_checks
    """
    club = get_success_data(api.create_club(fac.club_payload(), OPS_HEADERS))
    player = fx.register_player(api, club["id"])
    officer = make_club_data_officer_headers(club["id"])

    validate_error(
        api.create_consent_record(
            player["id"],
            fac.consent_record_payload(
                cba_agreement_version="CBA-2025B",
                expires_at_utc=PAST_CONSENT_EXPIRY,
            ),
            officer,
        ),
        ERR_CBA_VERSION_MISMATCH,
    )
    validate_error(
        api.create_consent_record(
            player["id"],
            fac.consent_record_payload(expires_at_utc=PAST_CONSENT_EXPIRY),
            officer,
        ),
        ERR_CONSENT_EXPIRY_IN_PAST,
    )

    record = get_success_data(
        api.create_consent_record(player["id"], fac.consent_record_payload(), officer),
        expected_status=201,
    )
    assert record["status"] == CONSENT_PENDING
    assert record["submitted_by_club_id"] == club["id"]
    assert record["ratified_by_user_id"] is None
    assert record["terminated_at_utc"] is None

    validate_error(
        api.create_consent_record(player["id"], fac.consent_record_payload(), officer),
        ERR_CONSENT_ALREADY_PENDING,
    )

    rows, meta = validate_paginated(api.list_consent_records(player["id"], OPS_HEADERS))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == record["id"]

    unchanged = validate_success(api.get_player(player["id"], OPS_HEADERS))
    assert unchanged["biometric_release_state"] == RELEASE_NONE
    assert unchanged["active_consent_record_id"] is None


# ---------------------------------------------------------------------------
# Three allocation rules broken in turn
# ---------------------------------------------------------------------------

def _scheduled_game(api: ApiClient) -> fx.World:
    """A SCHEDULED game with 240 licensable minutes and no rights windows."""
    world = fx.World()
    world.venue = fx.register_venue(api)
    clubs = fx.register_clubs(api)
    world.home_club = clubs["home"]
    world.away_club = clubs["away"]
    world.game = get_success_data(
        api.create_game(
            fac.game_payload(
                world.venue["id"], world.home_club["id"], world.away_club["id"]
            ),
            OPS_HEADERS,
        )
    )
    return world


def test_the_allocation_ladder_reads_bounds_then_holder_then_pool(api, clock):
    """PRD §2.10: "Checks are evaluated in the following fixed order, and the first
    violated check determines the response."
    PRD §3.7: "Independently of exclusivity, the interval itself must be coherent:
    `window_end_utc` strictly after `window_start_utc`, or `ERR_INVALID_WINDOW_BOUNDS`."
    PRD §3.7: "Any mismatch of this contract — a league window that supplies a holder, a
    club window naming an uninvolved club, a licensee window with no licensee — is
    refused with `ERR_RIGHTS_HOLDER_MISMATCH`, while a `holder_id` that simply does not
    exist is a 404 naming the missing type."
    PRD §3.7: "A candidate that does not fit is refused with
    `ERR_ALLOCATION_POOL_EXHAUSTED`, and the practical consequence is that the archival
    reserve can never be cannibalised by a broadcaster and a broadcaster can never be
    squeezed out by the archive."

    An inverted interval hides the holder fault, which hides the pool fault.

    The last call books the whole net pool to the minute, which the admission
    test allows because it compares inclusively.

    Design: Corner/validations/window_bounds_outrank_holder_resolution_which_outranks_the_pool
    """
    world = _scheduled_game(api)

    def league_window(**overrides):
        return fac.rights_window_payload(
            rights_class=RIGHTS_CLASS_BROADCAST_LIVE,
            holder_type=HOLDER_LEAGUE,
            territory=TERRITORY_GLOBAL,
            max_latency_ms=5000,
            **overrides,
        )

    validate_error(
        api.create_rights_window(
            world.game_id,
            fac.rights_window_payload(
                world.home_club["id"],
                rights_class=RIGHTS_CLASS_BROADCAST_LIVE,
                holder_type=HOLDER_LEAGUE,
                territory=TERRITORY_GLOBAL,
                max_latency_ms=5000,
                window_start_utc="2026-08-01T18:00:00Z",
                window_end_utc="2026-08-01T17:00:00Z",
            ),
            OPS_HEADERS,
        ),
        ERR_INVALID_WINDOW_BOUNDS,
    )
    validate_error(
        api.create_rights_window(
            world.game_id,
            fac.rights_window_payload(
                world.home_club["id"],
                rights_class=RIGHTS_CLASS_BROADCAST_LIVE,
                holder_type=HOLDER_LEAGUE,
                territory=TERRITORY_GLOBAL,
                max_latency_ms=5000,
                window_start_utc="2026-08-01T18:00:00Z",
                window_end_utc="2026-08-01T18:30:00Z",
            ),
            OPS_HEADERS,
        ),
        ERR_RIGHTS_HOLDER_MISMATCH,
    )
    validate_error(
        api.create_rights_window(
            world.game_id,
            league_window(
                window_start_utc="2026-08-01T18:00:00Z",
                window_end_utc="2026-08-01T21:25:00Z",
            ),
            OPS_HEADERS,
        ),
        ERR_ALLOCATION_POOL_EXHAUSTED,
    )

    window = get_success_data(
        api.create_rights_window(
            world.game_id,
            league_window(
                window_start_utc="2026-08-01T18:00:00Z",
                window_end_utc="2026-08-01T21:24:00Z",
            ),
            OPS_HEADERS,
        ),
        expected_status=201,
    )
    assert window["allocated_minutes"] == 204

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_minute_ledger(
        game,
        league_reserve_minutes=36,
        net_allocatable_minutes=204,
        allocated_minutes_total=204,
        remaining_allocatable_minutes=0,
    )

    _, meta = validate_paginated(api.list_rights_windows(world.game_id, OPS_HEADERS))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# One field, two opposite-facing bounds
# ---------------------------------------------------------------------------

def test_the_latency_request_is_squeezed_from_physics_and_from_contract(api, clock):
    """PRD §3.8: "The latency request is squeezed from both sides: `requested_latency_ms`
    must be greater than or equal to the hosting venue's `min_achievable_latency_ms`,
    since no amount of contract writing beats physics, and less than or equal to the
    rights window's `max_latency_ms`, since a session may not claim a tighter guarantee
    than the window actually sells; equality is acceptable at both bounds, and the two
    failures are `ERR_LATENCY_BELOW_VENUE_FLOOR` and `ERR_LATENCY_SLA_UNSATISFIABLE`."
    PRD §3.8: "`latency_multiplier` is a premium selected from the latency the session
    asked for: a `requested_latency_ms` of at most 250 milliseconds — a quarter of a
    second — carries a multiplier of 1.50; anything above that but at most 1,000
    milliseconds, a full second, carries 1.20; anything slower carries 1.00."

    One millisecond below the venue floor, one above the window ceiling.

    The third attempt asks for exactly the floor, which is admitted and lands in
    the premium multiplier band.

    Design: Corner/validations/session_latency_is_bracketed_by_venue_floor_and_window_ceiling
    """
    world = fx.licensed_live_game_world(api, window_overrides={"max_latency_ms": 400})
    headers = world.licensee_headers

    validate_error(
        api.create_feed_session(
            fac.feed_session_payload(
                world.game_id, world.window_id, requested_latency_ms=199
            ),
            headers,
        ),
        ERR_LATENCY_BELOW_VENUE_FLOOR,
    )
    validate_error(
        api.create_feed_session(
            fac.feed_session_payload(
                world.game_id, world.window_id, requested_latency_ms=401
            ),
            headers,
        ),
        ERR_LATENCY_SLA_UNSATISFIABLE,
    )

    session = get_success_data(
        api.create_feed_session(
            fac.feed_session_payload(
                world.game_id,
                world.window_id,
                requested_latency_ms=VENUE_LATENCY_FLOOR_MS,
            ),
            headers,
        ),
        expected_status=201,
    )
    assert session["status"] == SESSION_ACTIVE
    assert_two_dp(session["latency_multiplier"], 1.50)
    assert session["reserved_units"] == 900
    assert session["reserved_units"] == expected_reserved_units(
        20, 1800, VENUE_LATENCY_FLOOR_MS
    )
    assert session["reserved_charge_cents"] == 19800
    assert session["reserved_charge_cents"] == expected_charge_cents(900, TIER_GOLD)

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert_unit_ledger(licensee, available=4100, reserved=900, consumed=0)

    _, meta = validate_paginated(
        api.list_feed_sessions(OPS_HEADERS, params={"game_id": world.game_id})
    )
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Three authorities over the same scope array
# ---------------------------------------------------------------------------

def test_the_scope_gates_read_paperwork_then_tier_then_window(api, clock):
    """PRD §2.10: "Checks are evaluated in the following fixed order, and the first
    violated check determines the response."
    PRD §3.8: "Biometric access requires both conditions independently: the tier must be
    `GOLD` *and* `biometric_entitled` must be true, and a `GOLD` licensee whose
    paperwork never permitted biometrics is refused with
    `ERR_BIOMETRIC_SCOPE_NOT_LICENSED`."
    PRD §3.8: "A scope member outside the tier's set is refused with
    `ERR_SCOPE_NOT_IN_TIER`."
    PRD §3.8: "Every requested scope member must appear both in the tier's permitted set
    and in the window's `allowed_scopes`, the latter failing with
    `ERR_SCOPE_NOT_IN_RIGHTS_WINDOW`."

    A gold licence without biometric paperwork answers on the paperwork.

    A silver licence that does hold the paperwork answers on its tier instead,
    which separates the two authorities; asking for a scope the tier allows but
    the window never sold answers on the window.

    Design: Corner/validations/biometric_paperwork_gate_precedes_tier_gate_precedes_window_gate
    """
    world = fx.live_game_world(api)
    gold = fx.onboard_licensee(api, tier=TIER_GOLD, biometric_entitled=False)
    silver = fx.onboard_licensee(
        api,
        name="Summit Analytics",
        licensee_class="DEVELOPER",
        tier=TIER_SILVER,
        biometric_entitled=True,
    )
    window = fx.allocate_window(
        api, world.game_id, holder_type=HOLDER_LEAGUE, max_latency_ms=5000
    )

    def booking(**overrides):
        return fac.feed_session_payload(
            world.game_id,
            window["id"],
            bandwidth_mbps=10,
            requested_latency_ms=2000,
            **overrides,
        )

    validate_error(
        api.create_feed_session(
            booking(scope=[SCOPE_POSITIONAL, SCOPE_BIOMETRIC]),
            make_licensee_headers(gold["id"]),
        ),
        ERR_BIOMETRIC_SCOPE_NOT_LICENSED,
    )
    validate_error(
        api.create_feed_session(
            booking(scope=[SCOPE_POSITIONAL, SCOPE_BIOMETRIC]),
            make_licensee_headers(silver["id"]),
        ),
        ERR_SCOPE_NOT_IN_TIER,
    )
    validate_error(
        api.create_feed_session(
            booking(scope=[SCOPE_POSITIONAL, SCOPE_EVENT]),
            make_licensee_headers(silver["id"]),
        ),
        ERR_SCOPE_NOT_IN_RIGHTS_WINDOW,
    )

    session = get_success_data(
        api.create_feed_session(
            booking(scope=[SCOPE_POSITIONAL]), make_licensee_headers(silver["id"])
        ),
        expected_status=201,
    )
    assert_two_dp(session["latency_multiplier"], 1.00)
    assert session["reserved_units"] == 300
    assert session["reserved_units"] == expected_reserved_units(10, 1800, 2000)
    assert session["reserved_charge_cents"] == expected_charge_cents(300, TIER_SILVER)

    refused_side = validate_success(api.get_licensee(gold["id"], OPS_HEADERS))
    assert_unit_ledger(refused_side, available=5000, reserved=0, consumed=0)

    admitted_side = validate_success(api.get_licensee(silver["id"], OPS_HEADERS))
    assert_unit_ledger(admitted_side, available=4700, reserved=300, consumed=0)


# ---------------------------------------------------------------------------
# The three substantive certification gates, in order
# ---------------------------------------------------------------------------

def test_an_open_dispute_is_reported_ahead_of_the_empty_accepted_set(api, clock):
    """PRD §2.10: "Checks are evaluated in the following fixed order, and the first
    violated check determines the response."
    PRD §3.6: "Beyond that, three substantive conditions apply, evaluated in the order
    §2.10 fixes: no correction may be open, so `under_correction_tag_count` must be zero
    or the attempt is refused with `ERR_OPEN_CORRECTIONS`; `accepted_tag_count` must be
    at least 1; and `quality_index` must be at least 0.8000 inclusive, or the attempt is
    refused with `ERR_QUALITY_INDEX_BELOW_THRESHOLD`."
    PRD §3.6: "The game's `rejected_correction_count` rises by one, its census is
    restored exactly as on approval, its `quality_index` is recomputed — with the
    lighter rejected-dispute weight, so a rejected challenge costs the game far less
    than an upheld one — and its `version` is incremented."

    Pulling the only accepted tag into dispute breaks two gates at once.

    Resolving the dispute against its author fixes both, and the attempt then
    reaches the quality gate that the rejection penalty has just closed.

    Design: Corner/validations/open_corrections_outrank_the_quality_index_gate_on_certify
    """
    world = fx.collected_game_world(api)
    correction = fx.open_correction(api, world.tag_id, STATISTICIAN_HEADERS)

    before = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_tag_census(
        before, draft=0, submitted=0, accepted=0, under_correction=1, superseded=0, total=1
    )
    assert before["certification_status"] == CERTIFICATION_PROVISIONAL

    validate_error(api.certify_game(world.game_id, OPS_HEADERS), ERR_OPEN_CORRECTIONS)

    rejected = validate_success(
        api.reject_correction(correction["id"], REVIEWER_HEADERS)
    )
    assert rejected["status"] == CORRECTION_REJECTED
    assert rejected["reviewed_by_user_id"] == REVIEWER_PRIMARY

    tag = validate_success(api.get_event_tag(world.tag_id, STATISTICIAN_HEADERS))
    assert tag["review_status"] == TAG_ACCEPTED
    assert tag["correction_count"] == 0
    assert tag["corrected_clock_ms"] is None

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_tag_census(
        game, draft=0, submitted=0, accepted=1, under_correction=0, superseded=0, total=1
    )
    assert game["rejected_correction_count"] == 1
    assert_quality_index(game, 0.7250)
    assert_quality_index(game, expected_quality_index([ACCEPTED_CONFIDENCE], 0, 1, 1))

    validate_error(
        api.certify_game(world.game_id, OPS_HEADERS), ERR_QUALITY_INDEX_BELOW_THRESHOLD
    )
    validate_error(
        api.approve_correction(correction["id"], REVIEWER_HEADERS),
        ERR_CORRECTION_ALREADY_RESOLVED,
    )

    rows, meta = validate_paginated(
        api.list_correction_requests(world.tag_id, OPS_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == CORRECTION_REJECTED

    final = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert final["certification_status"] == CERTIFICATION_PROVISIONAL
    assert final["collection_status"] == COLLECTION_COLLECTED


def test_certification_is_admitted_sitting_exactly_on_the_quality_floor(api, clock):
    """PRD §2.10: "Quality floor: the game's `quality_index` is at least 0.8000, equality
    allowed — otherwise `ERR_QUALITY_INDEX_BELOW_THRESHOLD` (HTTP 422)."
    PRD §2.7: "A game's `quality_index` is rounded half up to four decimal places, and
    the certification floor is compared against that four-decimal figure."
    PRD §3.6: "On success `certification_status` advances to `OFFICIAL`,
    `certified_at_utc` is stamped with the logical clock, `collection_status` advances
    `COLLECTED → ARCHIVED` (or stays `ARCHIVED` on a re-certification), and the game's
    `version` is incremented."

    One accepted tag at 0.90 scores the floor to the last decimal place.

    The gate compares inclusively, so the certification succeeds and archives
    the game in the same request.

    Design: Corner/validations/certify_admitted_at_exactly_the_quality_index_floor
    """
    world = fx.collected_game_world(api)
    assert_quality_index(world.game, QUALITY_INDEX_FLOOR)

    certified = validate_success(api.certify_game(world.game_id, OPS_HEADERS))
    assert certified["certification_status"] == CERTIFICATION_OFFICIAL
    assert_quality_index(certified, 0.8000)
    assert certified["collection_status"] == COLLECTION_ARCHIVED
    assert certified["certified_at_utc"] == CLOCK_NOON
    assert certified["version"] == 7
    assert_tag_census(
        certified,
        draft=0,
        submitted=0,
        accepted=1,
        under_correction=0,
        superseded=0,
        total=1,
    )
    assert certified["approved_correction_count"] == 0
    assert certified["rejected_correction_count"] == 0


# ---------------------------------------------------------------------------
# The accuracy claim answers before the rig's lifecycle
# ---------------------------------------------------------------------------

def test_the_accuracy_verdict_answers_before_the_rig_lifecycle(api, clock):
    """PRD §2.10: "Accuracy claim: the rig's `latest_run_result` is `PASS` — otherwise
    `ERR_CALIBRATION_NOT_PASSING`."
    PRD §2.10: "This check sits deliberately *ahead* of the installation lifecycle gate
    at rank 10: the accuracy claim is the thing being certified, so a rig with no
    passing run is refused on accuracy grounds even when its lifecycle state would also
    have been wrong."

    A rig with no passing run is refused on accuracy, not on state.

    That holds from DEPLOYED, where the lifecycle is also wrong, and again from
    CALIBRATING after a failing run, where it is wrong for a second reason.

    Design: Corner/validations/calibration_result_gate_precedes_the_installation_state_gate
    """
    venue = fx.register_venue(api)
    rig = fx.deploy_rig(api, venue["id"])

    validate_error(
        api.certify_installation(rig["id"], OPS_HEADERS), ERR_CALIBRATION_NOT_PASSING
    )

    failing = get_success_data(
        api.create_calibration_run(
            rig["id"], fac.uniform_calibration_run_payload(200.0), ENGINEER_HEADERS
        ),
        expected_status=201,
    )
    assert_two_dp(failing["composite_rms_mm"], 200.00)
    assert failing["result"] == RESULT_FAIL

    mid_cycle = validate_success(api.get_installation(rig["id"], ENGINEER_HEADERS))
    assert mid_cycle["status"] == INSTALLATION_CALIBRATING

    validate_error(
        api.certify_installation(rig["id"], OPS_HEADERS), ERR_CALIBRATION_NOT_PASSING
    )

    passing = get_success_data(
        api.create_calibration_run(
            rig["id"], fac.uniform_calibration_run_payload(90.0), ENGINEER_HEADERS
        ),
        expected_status=201,
    )
    assert passing["result"] == RESULT_PASS

    validated = validate_success(api.get_installation(rig["id"], ENGINEER_HEADERS))
    assert validated["status"] == INSTALLATION_VALIDATED
    assert validated["calibration_run_count"] == 2
    assert_two_dp(validated["latest_run_composite_rms_mm"], 90.00)

    certified = validate_success(api.certify_installation(rig["id"], OPS_HEADERS))
    assert certified["status"] == INSTALLATION_CERTIFIED

    venue_after = validate_success(api.get_venue(venue["id"], OPS_HEADERS))
    assert venue_after["data_posture"] == POSTURE_CERTIFIED
    assert_installation_census(venue_after, certified=1, recalibrating=0, uncertified=0)
    assert venue_after["active_installation_count"] == 1


def test_a_measurement_is_fresh_at_seventy_two_hours_and_stale_at_seventy_three(api, clock):
    """PRD §2.10: "Calibration freshness: the elapsed time from the rig's
    `latest_run_recorded_at_utc` to the logical clock is at most 72 hours — otherwise
    `ERR_CALIBRATION_EXPIRED` (HTTP 422)."
    PRD §3.2: "A rig may be certified only from `VALIDATED`; its `latest_run_result`
    must be `PASS`; the elapsed time from `latest_run_recorded_at_utc` to the current
    logical clock must be at most 72 hours — three days of validity, after which the
    measurement is stale and the attempt is refused with `ERR_CALIBRATION_EXPIRED`; and
    the acting `X-User-ID` must differ from the rig's `latest_run_engineer_user_id`, so
    that the engineer who measured the rig cannot be the operator who certifies it."

    Two rigs measured at the same instant, certified an hour apart.

    The freshness window is counted from the run, not from the deployment, and it
    is inclusive at its far end.

    Design: Corner/validations/certification_valid_at_exactly_seventy_two_hours_expired_at_seventy_three
    """
    venue = fx.register_venue(api)
    rig_a = fx.deploy_rig(api, venue["id"], rig_label="RIG-A")
    rig_b = fx.deploy_rig(api, venue["id"], rig_label="RIG-B")
    fx.record_run(api, rig_a["id"], ENGINEER_HEADERS)
    fx.record_run(api, rig_b["id"], ENGINEER_ALT_HEADERS)

    advanced = validate_success(api.set_clock(CLOCK_PLUS_72H, OPS_HEADERS))
    assert advanced["current_utc"] == CLOCK_PLUS_72H
    assert advanced["expired_consent_record_count"] == 0
    assert advanced["suspended_feed_session_count"] == 0

    certified = validate_success(api.certify_installation(rig_a["id"], OPS_HEADERS))
    assert certified["status"] == INSTALLATION_CERTIFIED
    assert certified["certified_at_utc"] == CLOCK_PLUS_72H

    validate_success(api.set_clock(CLOCK_PLUS_73H, OPS_HEADERS))
    validate_error(
        api.certify_installation(rig_b["id"], OPS_HEADERS), ERR_CALIBRATION_EXPIRED
    )

    stale = validate_success(api.get_installation(rig_b["id"], ENGINEER_HEADERS))
    assert stale["status"] == INSTALLATION_VALIDATED
    assert stale["certified_at_utc"] is None
    assert stale["latest_run_result"] == RESULT_PASS

    venue_after = validate_success(api.get_venue(venue["id"], OPS_HEADERS))
    assert venue_after["data_posture"] == POSTURE_CERTIFIED
    assert_installation_census(venue_after, certified=1, recalibrating=0, uncertified=1)


# ---------------------------------------------------------------------------
# A well-typed body that the domain still refuses
# ---------------------------------------------------------------------------

def _collected_game(api: ApiClient, **game_overrides) -> fx.World:
    """A game whose collection has been opened and closed, carrying no tags."""
    world = fx.certified_venue(api)
    clubs = fx.register_clubs(api)
    world.home_club = clubs["home"]
    world.away_club = clubs["away"]
    world.game = get_success_data(
        api.create_game(
            fac.game_payload(
                world.venue["id"],
                world.home_club["id"],
                world.away_club["id"],
                **game_overrides,
            ),
            OPS_HEADERS,
        )
    )
    validate_success(api.open_collection(world.game["id"], OPS_HEADERS))
    world.game = validate_success(api.close_collection(world.game["id"], OPS_HEADERS))
    return world


def test_an_empty_segment_array_reaches_the_domain_refusal(api):
    """PRD §2.10: "Normalization input: `segment_values` is a non-empty array — otherwise
    `ERR_NORMALIZATION_SEGMENTS_EMPTY` (HTTP 422)."
    PRD §3.9: "It passes the request-schema check, which is what allows the
    domain-specific refusal to reach the caller: an empty array is refused with
    `ERR_NORMALIZATION_SEGMENTS_EMPTY` at HTTP 422 rather than with a generic
    malformed-body error, so operators can tell "you sent nothing to normalize" apart
    from "you sent nonsense"."

    An empty array is well-typed, so the schema layer must let it through.

    The one-element array that follows proves the endpoint itself was never the
    problem.

    Design: Corner/validations/normalization_rejects_the_schema_legal_empty_segment_array
    """
    world = _collected_game(api)

    validate_error(
        api.create_normalization_run(
            world.game_id,
            fac.normalization_run_payload(segment_values=[]),
            OPS_HEADERS,
        ),
        ERR_NORMALIZATION_SEGMENTS_EMPTY,
    )

    run = get_success_data(
        api.create_normalization_run(
            world.game_id,
            fac.normalization_run_payload(segment_values=SINGLE_SEGMENT),
            OPS_HEADERS,
        ),
        expected_status=201,
    )
    assert_two_dp(run["normalized_value"], 125.56)
    assert_two_dp(
        run["normalized_value"], expected_raw_generation_value(SINGLE_SEGMENT, "G1")
    )
    assert run["source_generation"] == "G1"
    assert_two_dp(run["scale_factor_applied"], 1.042)
    assert_two_dp(run["drift_correction_pct"], 0.0)
    assert run["mapping_version"] == MAPPING_VERSION

    _, meta = validate_paginated(
        api.list_normalization_runs(world.game_id, OPS_HEADERS)
    )
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Two ways a session can be wrong about its window
# ---------------------------------------------------------------------------

def _two_live_games(api: ApiClient) -> fx.World:
    """Two LIVE games sharing one certified venue and one pair of clubs."""
    world = fx.certified_venue(api)
    clubs = fx.register_clubs(api)
    world.home_club = clubs["home"]
    world.away_club = clubs["away"]
    world.game = get_success_data(
        api.create_game(
            fac.game_payload(
                world.venue["id"], world.home_club["id"], world.away_club["id"]
            ),
            OPS_HEADERS,
        )
    )
    world.extra["other_game"] = get_success_data(
        api.create_game(
            fac.game_payload(
                world.venue["id"],
                world.away_club["id"],
                world.home_club["id"],
                scheduled_start_utc="2026-08-02T18:00:00Z",
            ),
            OPS_HEADERS,
        )
    )
    world.game = validate_success(api.open_collection(world.game["id"], OPS_HEADERS))
    validate_success(api.open_collection(world.extra["other_game"]["id"], OPS_HEADERS))
    return world


def test_a_session_must_cite_its_own_game_and_stay_inside_the_window(api, clock):
    """PRD §3.8: "The referenced window must belong to the same game the session names, or
    the request is refused with `ERR_RIGHTS_WINDOW_GAME_MISMATCH`."
    PRD §3.8: "The occupation interval must be coherent, and it must be **contained** in
    the rights window's interval: the session's interval is half-open, covering its
    start instant and stopping short of its end instant, while the window's interval is
    closed on both ends, and a session reaching outside is refused with
    `ERR_SESSION_WINDOW_OUTSIDE_RIGHTS`."

    A window that fits the clock but belongs to the neighbouring game.

    The second attempt names the right game and opens one minute early, so the
    two failures are told apart by their own errors rather than by collection
    state, which is live for both games.

    Design: Corner/validations/session_must_cite_its_own_game_and_stay_inside_the_rights_window
    """
    world = _two_live_games(api)
    world.licensee = fx.onboard_licensee(api)
    world.window = fx.allocate_window(
        api, world.game_id, world.licensee_id, max_latency_ms=5000
    )
    headers = world.licensee_headers
    other_game_id = world.extra["other_game"]["id"]

    validate_error(
        api.create_feed_session(
            fac.feed_session_payload(
                other_game_id, world.window_id, requested_latency_ms=300
            ),
            headers,
        ),
        ERR_RIGHTS_WINDOW_GAME_MISMATCH,
    )
    validate_error(
        api.create_feed_session(
            fac.feed_session_payload(
                world.game_id,
                world.window_id,
                window_start_utc="2026-08-01T17:59:00Z",
                requested_latency_ms=300,
            ),
            headers,
        ),
        ERR_SESSION_WINDOW_OUTSIDE_RIGHTS,
    )

    session = get_success_data(
        api.create_feed_session(
            fac.feed_session_payload(
                world.game_id, world.window_id, requested_latency_ms=300
            ),
            headers,
        ),
        expected_status=201,
    )
    assert session["game_id"] == world.game_id
    assert session["licensee_id"] == world.licensee_id
    assert_two_dp(session["latency_multiplier"], 1.20)
    assert session["reserved_units"] == 720
    assert session["reserved_charge_cents"] == 15840

    windows, _ = validate_paginated(api.list_rights_windows(world.game_id, OPS_HEADERS))
    assert len(windows) == 1
    assert windows[0]["active_feed_session_count"] == 1

    _, meta = validate_paginated(
        api.list_feed_sessions(OPS_HEADERS, params={"game_id": other_game_id})
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Terminal on both sides of the revocation cascade
# ---------------------------------------------------------------------------

def test_a_revoked_window_and_the_session_it_settled_refuse_everything(api, clock):
    """PRD §3.7: "A window may be revoked only from `ACTIVE`; a repeat attempt on an
    already-revoked window is refused with `ERR_RIGHTS_WINDOW_REVOKED`."
    PRD §3.8: "`TERMINATED` is terminal; a further termination attempt is refused with
    `ERR_SESSION_NOT_ACTIVE`, as is any usage report against a non-active session."

    Revocation is terminal for the window and for the session beneath it.

    A second termination proves the termination source set excludes the state
    termination itself produced.

    Design: Corner/validations/revoked_window_and_terminated_session_refuse_all_further_traffic
    """
    world = fx.active_session_world(
        api, session_overrides={"requested_latency_ms": 300}
    )

    revoked = validate_success(api.revoke_rights_window(world.window_id, OPS_HEADERS))
    assert revoked["status"] == WINDOW_REVOKED
    assert revoked["revoked_at_utc"] == CLOCK_NOON
    assert revoked["active_feed_session_count"] == 0

    settled = validate_success(api.get_feed_session(world.session_id, OPS_HEADERS))
    assert settled["status"] == SESSION_TERMINATED
    assert settled["halt_reason"] == HALT_CLIENT_REQUEST
    assert settled["reserved_units"] == 720
    assert settled["metered_units"] == 0
    assert settled["settled_charge_cents"] == 0
    assert settled["refunded_units"] == 720

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_minute_ledger(
        game,
        league_reserve_minutes=36,
        net_allocatable_minutes=204,
        allocated_minutes_total=0,
        remaining_allocatable_minutes=204,
    )

    validate_error(
        api.create_feed_session(
            fac.feed_session_payload(
                world.game_id,
                world.window_id,
                window_start_utc="2026-08-01T19:00:00Z",
                window_end_utc="2026-08-01T19:30:00Z",
                requested_latency_ms=300,
            ),
            world.licensee_headers,
        ),
        ERR_RIGHTS_WINDOW_REVOKED,
    )
    validate_error(
        api.create_usage_record(
            world.session_id,
            fac.usage_record_payload(duration_seconds=60, latency_p95_ms=300),
            world.licensee_headers,
        ),
        ERR_SESSION_NOT_ACTIVE,
    )
    validate_error(
        api.terminate_feed_session(world.session_id, world.licensee_headers),
        ERR_SESSION_NOT_ACTIVE,
    )

    unchanged = validate_success(api.get_feed_session(world.session_id, OPS_HEADERS))
    assert unchanged["usage_record_count"] == 0

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert_unit_ledger(licensee, available=5000, reserved=0, consumed=0)


# ---------------------------------------------------------------------------
# One game state, two delivery modes, two errors
# ---------------------------------------------------------------------------

def test_the_two_delivery_modes_read_the_same_game_differently(api, clock):
    """PRD §3.8: "The delivery mode picks the game gate: a `REALTIME` session requires the
    game's `collection_status` to be `LIVE` and is otherwise refused with
    `ERR_GAME_NOT_COLLECTING`, while a `POST_GAME` session requires `COLLECTED` or
    `ARCHIVED` and is otherwise refused with `ERR_GAME_NOT_COLLECTED`."

    A scheduled game is neither collecting nor collected, and says so twice.

    Opening collection satisfies only the real-time gate: the post-game gate
    still refuses, because live is not the same thing as closed.

    Design: Corner/validations/delivery_mode_gates_read_two_different_collection_states
    """
    world = fx.scheduled_game_world(api)
    world.licensee = fx.onboard_licensee(api)
    world.window = fx.allocate_window(
        api, world.game_id, world.licensee_id, max_latency_ms=5000
    )
    headers = world.licensee_headers

    current = validate_success(api.get_game(world.game_id, STATISTICIAN_HEADERS))
    validate_error(
        api.create_event_tag(
            fac.event_tag_payload(
                world.game_id, world.player["id"], current["version"]
            ),
            STATISTICIAN_HEADERS,
        ),
        ERR_GAME_NOT_COLLECTING,
    )
    validate_error(
        api.create_feed_session(
            fac.feed_session_payload(
                world.game_id, world.window_id, requested_latency_ms=300
            ),
            headers,
        ),
        ERR_GAME_NOT_COLLECTING,
    )

    def post_game_booking():
        return fac.feed_session_payload(
            world.game_id,
            world.window_id,
            delivery_mode=DELIVERY_POST_GAME,
            window_start_utc="2026-08-01T19:00:00Z",
            window_end_utc="2026-08-01T19:30:00Z",
            requested_latency_ms=300,
        )

    validate_error(
        api.create_feed_session(post_game_booking(), headers), ERR_GAME_NOT_COLLECTED
    )

    opened = validate_success(api.open_collection(world.game_id, OPS_HEADERS))
    assert opened["collection_status"] == COLLECTION_LIVE
    assert opened["data_quality_flag"] == QUALITY_FLAG_CLEAN
    assert opened["version"] == current["version"] + 1

    session = get_success_data(
        api.create_feed_session(
            fac.feed_session_payload(
                world.game_id, world.window_id, requested_latency_ms=300
            ),
            headers,
        ),
        expected_status=201,
    )
    assert session["status"] == SESSION_ACTIVE
    assert session["reserved_units"] == 720

    validate_error(
        api.create_feed_session(post_game_booking(), headers), ERR_GAME_NOT_COLLECTED
    )

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert game["total_tag_count"] == 0
    assert game["draft_tag_count"] == 0


# ---------------------------------------------------------------------------
# The reservation ceiling, filled exactly and then overshot
# ---------------------------------------------------------------------------

def test_a_usage_sample_may_fill_the_reservation_but_never_pass_it(api, clock):
    """PRD §3.8: "Before the record is accepted, the reservation is re-checked: the
    session's already-accumulated `metered_units` plus the new record's `units_charged`
    must be less than or equal to the session's `reserved_units`, equality allowed, or
    the report is refused with `ERR_SESSION_RESERVATION_EXCEEDED` at HTTP 402."
    PRD §3.8: "The record's `units_charged` is the product of its `bandwidth_mbps`, its
    `duration_seconds` divided by sixty, and the parent session's `latency_multiplier`,
    rounded up to a whole unit — the ceiling is applied to this record alone."

    Half a minute too much is refused before anything is recorded.

    The exact fill is then accepted, and the next sample is refused on the
    running total rather than on its own modest size.

    Design: Corner/validations/usage_record_may_fill_the_reservation_exactly_but_not_exceed_it
    """
    world = fx.active_session_world(api, window_overrides={"max_latency_ms": 5000})
    assert world.session["reserved_units"] == 900

    validate_error(
        api.create_usage_record(
            world.session_id,
            fac.usage_record_payload(
                sampled_at_utc="2026-08-01T18:01:00Z",
                duration_seconds=1830,
                latency_p95_ms=100,
            ),
            world.licensee_headers,
        ),
        ERR_SESSION_RESERVATION_EXCEEDED,
    )

    record = get_success_data(
        api.create_usage_record(
            world.session_id,
            fac.usage_record_payload(
                sampled_at_utc="2026-08-01T18:02:00Z",
                duration_seconds=1800,
                latency_p95_ms=100,
            ),
            world.licensee_headers,
        ),
        expected_status=201,
    )
    assert record["units_charged"] == 900
    assert record["units_charged"] == expected_record_units(20, 1800, 1.50)
    assert record["sla_breach"] is False

    validate_error(
        api.create_usage_record(
            world.session_id,
            fac.usage_record_payload(
                sampled_at_utc="2026-08-01T18:03:00Z",
                duration_seconds=60,
                latency_p95_ms=100,
            ),
            world.licensee_headers,
        ),
        ERR_SESSION_RESERVATION_EXCEEDED,
    )

    session = validate_success(api.get_feed_session(world.session_id, OPS_HEADERS))
    assert session["metered_units"] == 900
    assert session["usage_record_count"] == 1
    assert session["sla_breach_count"] == 0
    assert session["status"] == SESSION_ACTIVE

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert_unit_ledger(licensee, available=4100, reserved=900, consumed=0)
    assert licensee["sla_credit_cents"] == 0
    assert licensee["audit_flag_count"] == 0
