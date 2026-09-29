"""
Derived numbers: which rows feed a formula, which pool a draw comes out of, and
what the declared constants produce at their exact boundaries.
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
    ERR_CALIBRATION_NOT_PASSING,
)
from test_helpers.assertions import (
    assert_installation_census,
    assert_minute_ledger,
    assert_quality_index,
    assert_tag_census,
    assert_two_dp,
    assert_unit_ledger,
    expected_canonical_season_value,
    expected_charge_cents,
    expected_latency_multiplier,
    expected_quality_index,
    expected_record_units,
    expected_reserved_units,
    expected_sla_credit_cents,
)
from test_helpers.constants import (
    BASIS_CANONICAL_SEASON,
    CERTIFICATION_PROVISIONAL,
    CLOCK_NOON,
    COLLECTION_LIVE,
    INSTALLATION_CALIBRATING,
    INSTALLATION_CERTIFIED,
    MAPPING_VERSION,
    METRIC_TOTAL_DISTANCE,
    POSTURE_RESTRICTED,
    POSTURE_UNCERTIFIED,
    RESULT_FAIL,
    RESULT_PROVISIONAL,
    RIGHTS_CLASS_LEAGUE_ARCHIVE,
    SCOPE_EVENT,
    SCOPE_POSITIONAL,
    SESSION_ACTIVE,
    TIER_GOLD,
    WINDOW_ACTIVE,
)
from test_helpers.test_users import (
    ENGINEER_HEADERS,
    OPS_HEADERS,
    OPS_PRIMARY,
    REVIEWER_QA_HEADERS,
    STATISTICIAN_HEADERS,
)

ACCEPTED_CONFIDENCE = 0.9
DRAFT_CONFIDENCE = 0.1
G2_SEGMENTS = [123.456, 78.912, 45.678, 12.345]


# ---------------------------------------------------------------------------
# Which tags the quality index is allowed to see
# ---------------------------------------------------------------------------

def test_a_terrible_draft_tag_does_not_move_the_quality_index(api, clock):
    """PRD §3.6: "The scored population is the set of the game's event tags whose
    `review_status` is either `ACCEPTED` or `UNDER_CORRECTION`; `DRAFT`, `SUBMITTED` and
    `SUPERSEDED` tags are excluded."
    PRD §3.6: "The third is completeness: the game's `accepted_tag_count` is divided by
    the four accepted tags a fully-tagged game is expected to carry, and the result is
    capped at 1.0."
    PRD §3.6: "The index is then half the mean confidence, plus three tenths of one
    minus the correction penalty, plus two tenths of the completeness, rounded half up
    to four decimal places and written to `quality_index`."

    Only accepted and disputed rows are scored, so 0.1 in DRAFT is invisible.

    Completeness also counts accepted tags alone, not the two-row total, so the
    index stays on the certification floor instead of collapsing toward 0.55.

    Design: Corner/calculations/quality_index_excludes_draft_rows_from_the_confidence_mean
    """
    world = fx.accepted_tag_world(
        api, reviewer=REVIEWER_QA_HEADERS, confidence=ACCEPTED_CONFIDENCE
    )
    current = validate_success(api.get_game(world.game_id, STATISTICIAN_HEADERS))
    fx.create_tag(
        api,
        world.game_id,
        world.player["id"],
        current["version"],
        STATISTICIAN_HEADERS,
        tag_type="PASS",
        clock_ms=240000,
        confidence=DRAFT_CONFIDENCE,
    )

    game = validate_success(api.get_game(world.game_id, REVIEWER_QA_HEADERS))
    assert_quality_index(game, 0.8000)
    assert_quality_index(game, expected_quality_index([ACCEPTED_CONFIDENCE], 0, 0, 1))
    assert_tag_census(
        game, draft=1, submitted=0, accepted=1, under_correction=0, superseded=0, total=2
    )
    assert game["approved_correction_count"] == 0
    assert game["rejected_correction_count"] == 0
    assert game["certification_status"] == CERTIFICATION_PROVISIONAL
    assert game["collection_status"] == COLLECTION_LIVE


# ---------------------------------------------------------------------------
# The middle branch of the posture aggregation
# ---------------------------------------------------------------------------

def test_one_certified_rig_out_of_two_required_reads_restricted(api, clock):
    """PRD §3.1: "In every remaining case — some rigs certified but not enough of them, or
    enough of them but at least one rig back in calibration — `data_posture` is
    `RESTRICTED`."

    Non-zero but insufficient is its own posture, not a rounding of CERTIFIED.

    Design: Corner/calculations/venue_posture_restricted_when_required_certified_count_unmet
    """
    venue = fx.register_venue(api, required_certified_installations=2)
    rig = fx.deploy_rig(api, venue["id"])
    fx.record_run(api, rig["id"], ENGINEER_HEADERS)

    certified = validate_success(api.certify_installation(rig["id"], OPS_HEADERS))
    assert certified["status"] == INSTALLATION_CERTIFIED
    assert certified["certified_by_user_id"] == OPS_PRIMARY
    assert certified["certified_at_utc"] == CLOCK_NOON

    read_back = validate_success(api.get_venue(venue["id"], OPS_HEADERS))
    assert read_back["data_posture"] == POSTURE_RESTRICTED
    assert_installation_census(
        read_back, certified=1, recalibrating=0, uncertified=0, retired=0
    )
    assert read_back["active_installation_count"] == 1


# ---------------------------------------------------------------------------
# One terminal rounding on the canonical basis
# ---------------------------------------------------------------------------

def _collected_g2_game(api: ApiClient) -> fx.World:
    """A second-generation game whose collection has been opened and closed."""
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
                tracking_generation="G2",
            ),
            OPS_HEADERS,
        )
    )
    validate_success(api.open_collection(world.game["id"], OPS_HEADERS))
    world.game = validate_success(api.close_collection(world.game["id"], OPS_HEADERS))
    return world


def test_the_canonical_basis_rounds_a_g2_total_exactly_once(api, clock):
    """PRD §3.9: "Under the `CANONICAL_SEASON` basis the arithmetic is deliberately
    reversed: the elements of `segment_values` are added together at full precision with
    no intermediate rounding, that exact sum is multiplied once by the generation scale
    factor, the result is then multiplied by one plus the generation's drift correction
    expressed as a fraction — that is, the drift percentage divided by one hundred — and
    only then is the figure rounded half up to two decimal places, exactly once."
    PRD §3.9: "The drift corrections are a reduction of six tenths of one percent for
    `G1` data and two tenths of one percent for `G2` data, and no correction at all for
    `G3` data, so `drift_correction_pct` is written as -0.6, -0.2 and 0.0 respectively."
    PRD §3.9: "`scale_factor_applied` is the generation's scale constant: a `G1` capture
    scales by 1.042, a `G2` capture by 1.017, and a `G3` capture by 1.000, since the
    current generation is the reference."

    The scaled and drifted sum 264.288011... lands on 264.29.

    Any per-segment rounding on the canonical basis would miss this cent-level
    value, which is the whole point of summing before scaling.

    Design: Corner/calculations/normalization_canonical_season_rounds_once_on_generation_g2
    """
    world = _collected_g2_game(api)

    run = get_success_data(
        api.create_normalization_run(
            world.game_id,
            fac.normalization_run_payload(
                segment_values=G2_SEGMENTS,
                basis=BASIS_CANONICAL_SEASON,
                metric_code=METRIC_TOTAL_DISTANCE,
            ),
            OPS_HEADERS,
        ),
        expected_status=201,
    )
    assert_two_dp(run["normalized_value"], 264.29)
    assert_two_dp(
        run["normalized_value"], expected_canonical_season_value(G2_SEGMENTS, "G2")
    )
    assert run["source_generation"] == "G2"
    assert_two_dp(run["scale_factor_applied"], 1.017)
    assert_two_dp(run["drift_correction_pct"], -0.2)
    assert run["mapping_version"] == MAPPING_VERSION
    assert run["basis"] == BASIS_CANONICAL_SEASON
    assert run["metric_code"] == METRIC_TOTAL_DISTANCE
    assert [float(value) for value in run["segment_values"]] == G2_SEGMENTS

    _, meta = validate_paginated(
        api.list_normalization_runs(
            world.game_id, OPS_HEADERS, params={"basis": BASIS_CANONICAL_SEASON}
        )
    )
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# The two latency constants, from either side
# ---------------------------------------------------------------------------

def test_the_latency_multiplier_is_inclusive_at_both_declared_constants(api, clock):
    """PRD §3.8: "`latency_multiplier` is a premium selected from the latency the session
    asked for: a `requested_latency_ms` of at most 250 milliseconds — a quarter of a
    second — carries a multiplier of 1.50; anything above that but at most 1,000
    milliseconds, a full second, carries 1.20; anything slower carries 1.00."
    PRD §3.8: "Under the reserved-forward variant the session is priced as if the entire
    booked window were fully consumed: `reserved_units` is the product of
    `bandwidth_mbps`, `duration_minutes` and `latency_multiplier`, rounded up to a whole
    unit with a single ceiling over the whole window, and `reserved_charge_cents` is
    that unit count multiplied by the licensee's per-unit tier rate and rounded half up
    to whole cents."

    Three identical bookings differing only in the latency they ask for.

    250 ms and 1000 ms sit exactly on the two constants and must earn the premium
    and standard multipliers; one millisecond beyond the second drops to the base.

    Design: Corner/calculations/feed_session_latency_tier_multipliers_at_both_boundaries
    """
    world = fx.licensed_live_game_world(
        api, licensee_overrides={"licensee_class": "COMMERCIAL_LICENSEE"}
    )

    expectations = [
        (250, 1.50, 900, 19800),
        (1000, 1.20, 720, 15840),
        (1001, 1.00, 600, 13200),
    ]
    for requested_latency_ms, multiplier, units, charge_cents in expectations:
        session = fx.open_session(
            api,
            world.licensee_id,
            world.game_id,
            world.window_id,
            requested_latency_ms=requested_latency_ms,
        )
        assert_two_dp(session["latency_multiplier"], multiplier)
        assert_two_dp(
            session["latency_multiplier"],
            expected_latency_multiplier(requested_latency_ms),
        )
        assert session["duration_minutes"] == 30
        assert session["reserved_units"] == units
        assert session["reserved_units"] == expected_reserved_units(
            20, 1800, requested_latency_ms
        )
        assert session["reserved_charge_cents"] == charge_cents
        assert session["reserved_charge_cents"] == expected_charge_cents(units, TIER_GOLD)

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert_unit_ledger(licensee, available=2780, reserved=2220, consumed=0)

    windows, _ = validate_paginated(api.list_rights_windows(world.game_id, OPS_HEADERS))
    assert len(windows) == 1
    assert windows[0]["active_feed_session_count"] == 3


# ---------------------------------------------------------------------------
# Two disjoint minute pools
# ---------------------------------------------------------------------------

def _unrigged_scheduled_game(api: ApiClient) -> fx.World:
    """A venue with no rigs at all and one SCHEDULED game on it."""
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


def test_an_archive_window_eats_the_reserve_and_cannot_borrow_the_net_pool(api, clock):
    """PRD §3.7: "Step three establishes two disjoint pools, each drawn down in window
    creation order from oldest to newest: the reserve pool is drawn only by windows
    whose `rights_class` is `LEAGUE_ARCHIVE`, and the net pool is drawn by windows of
    all three other classes."
    PRD §3.7: "A `LEAGUE_ARCHIVE` candidate is admitted when its `allocated_minutes` is
    less than or equal to `league_reserve_minutes` less
    `league_reserve_allocated_minutes`; a candidate of any other class is admitted when
    its `allocated_minutes` is less than or equal to `remaining_allocatable_minutes`."
    PRD §3.7: "A candidate that does not fit is refused with
    `ERR_ALLOCATION_POOL_EXHAUSTED`, and the practical consequence is that the archival
    reserve can never be cannibalised by a broadcaster and a broadcaster can never be
    squeezed out by the archive."

    The reserve draw leaves the net pool untouched at its full 204 minutes.

    A second archive window is then refused even though those 204 net minutes are
    still free, because the two pools never lend to each other.

    Design: Corner/calculations/league_archive_window_draws_from_the_reserve_pool_only
    """
    world = _unrigged_scheduled_game(api)

    archive = get_success_data(
        api.create_rights_window(
            world.game_id,
            fac.league_archive_window_payload(
                window_start_utc="2026-08-01T18:00:00Z",
                window_end_utc="2026-08-01T18:36:00Z",
                allowed_scopes=[SCOPE_POSITIONAL, SCOPE_EVENT],
            ),
            OPS_HEADERS,
        ),
        expected_status=201,
    )
    assert archive["allocated_minutes"] == 36
    assert archive["holder_id"] is None
    assert archive["status"] == WINDOW_ACTIVE

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_minute_ledger(
        game,
        league_reserve_minutes=36,
        net_allocatable_minutes=204,
        allocated_minutes_total=0,
        remaining_allocatable_minutes=204,
        league_reserve_allocated_minutes=36,
    )

    validate_error(
        api.create_rights_window(
            world.game_id,
            fac.league_archive_window_payload(
                window_start_utc="2026-08-01T20:00:00Z",
                window_end_utc="2026-08-01T20:01:00Z",
            ),
            OPS_HEADERS,
        ),
        ERR_ALLOCATION_POOL_EXHAUSTED,
    )

    _, meta = validate_paginated(
        api.list_rights_windows(
            world.game_id,
            OPS_HEADERS,
            params={"rights_class": RIGHTS_CLASS_LEAGUE_ARCHIVE},
        )
    )
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# The upper accuracy threshold
# ---------------------------------------------------------------------------

def test_the_provisional_ceiling_is_inclusive_and_a_hundredth_worse_fails(api, clock):
    """PRD §3.2: "Otherwise, if `composite_rms_mm` is at most 140.00 millimetres, again
    inclusive, the verdict is `PROVISIONAL`."
    PRD §3.2: "Anything above that is a `FAIL`."
    PRD §3.2: "A rig whose latest verdict is not `PASS` is refused with
    `ERR_CALIBRATION_NOT_PASSING` ahead of any state complaint, per §2.10."

    140.00 mm is still provisional; 140.01 mm is a failure.

    Neither verdict lets the rig leave CALIBRATING, so the venue has nothing to
    certify and the certification attempt is refused on accuracy grounds.

    Design: Corner/calculations/calibration_provisional_ceiling_exact_then_one_hundredth_above
    """
    venue = fx.register_venue(api)
    rig = fx.deploy_rig(api, venue["id"], modality="LIDAR")

    at_ceiling = get_success_data(
        api.create_calibration_run(
            rig["id"], fac.uniform_calibration_run_payload(140.0), ENGINEER_HEADERS
        ),
        expected_status=201,
    )
    assert_two_dp(at_ceiling["composite_rms_mm"], 140.00)
    assert at_ceiling["result"] == RESULT_PROVISIONAL

    beyond_ceiling = get_success_data(
        api.create_calibration_run(
            rig["id"], fac.uniform_calibration_run_payload(140.01), ENGINEER_HEADERS
        ),
        expected_status=201,
    )
    assert_two_dp(beyond_ceiling["composite_rms_mm"], 140.01)
    assert beyond_ceiling["result"] == RESULT_FAIL

    read_back = validate_success(api.get_installation(rig["id"], ENGINEER_HEADERS))
    assert read_back["status"] == INSTALLATION_CALIBRATING
    assert read_back["latest_run_result"] == RESULT_FAIL
    assert_two_dp(read_back["latest_run_composite_rms_mm"], 140.01)
    assert read_back["calibration_run_count"] == 2

    venue_after = validate_success(api.get_venue(venue["id"], OPS_HEADERS))
    assert venue_after["data_posture"] == POSTURE_UNCERTIFIED
    assert_installation_census(venue_after, certified=0, recalibrating=1, uncertified=0)

    validate_error(
        api.certify_installation(rig["id"], OPS_HEADERS), ERR_CALIBRATION_NOT_PASSING
    )


# ---------------------------------------------------------------------------
# The credit a breached sample earns
# ---------------------------------------------------------------------------

def test_a_breached_sample_is_credited_at_a_quarter_of_its_own_charge(api, clock):
    """PRD §3.8: "Delivery quality is judged on the same record: `sla_breach` is set to
    true when the record's `latency_p95_ms` is strictly greater than the governing
    rights window's `max_latency_ms`."
    PRD §3.8: "A breach raises the session's `sla_breach_count` by one and the
    licensee's `audit_flag_count` by one, and it credits the licensee: a quarter of the
    record's charge — the record's `units_charged` multiplied by the tier rate,
    multiplied by 0.25 and rounded half up to whole cents — is added to the licensee's
    `sla_credit_cents`."

    The credit is priced off the record's units, never off the reservation.

    The sample's own 30 units at the gold rate, quartered, give 165 cents, and the
    breach also raises the licensee's audit flag without touching the ledger.

    Design: Corner/calculations/usage_record_sla_credit_uses_tier_rate_and_credit_pct
    """
    world = fx.active_session_world(api, window_overrides={"max_latency_ms": 400})

    record = get_success_data(
        api.create_usage_record(
            world.session_id,
            fac.usage_record_payload(duration_seconds=60, latency_p95_ms=500),
            world.licensee_headers,
        ),
        expected_status=201,
    )
    assert record["units_charged"] == 30
    assert record["units_charged"] == expected_record_units(20, 60, 1.50)
    assert record["sla_breach"] is True
    assert record["licensee_id"] == world.licensee_id
    assert record["feed_session_id"] == world.session_id

    session = validate_success(api.get_feed_session(world.session_id, OPS_HEADERS))
    assert session["metered_units"] == 30
    assert session["usage_record_count"] == 1
    assert session["sla_breach_count"] == 1
    assert session["status"] == SESSION_ACTIVE
    assert session["halt_reason"] is None

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert licensee["sla_credit_cents"] == 165
    assert licensee["sla_credit_cents"] == expected_sla_credit_cents(30, TIER_GOLD)
    assert licensee["audit_flag_count"] == 1
    assert_unit_ledger(licensee, available=4100, reserved=900, consumed=0)
