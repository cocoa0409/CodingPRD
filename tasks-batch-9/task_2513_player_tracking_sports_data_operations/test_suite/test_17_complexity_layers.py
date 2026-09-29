"""
Layered mechanics: a version counter that every write moves, and a breach
counter that only trips the circuit at its third increment.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_SESSION_NOT_ACTIVE,
    ERR_STALE_GAME_VERSION,
)
from test_helpers.assertions import (
    assert_quality_index,
    assert_tag_census,
    assert_unit_ledger,
    expected_sla_credit_cents,
)
from test_helpers.constants import (
    HALT_SLA_BREACH_THRESHOLD,
    SESSION_ACTIVE,
    SESSION_SUSPENDED,
    SLA_BREACH_SUSPEND_THRESHOLD,
    TAG_DRAFT,
    TIER_GOLD,
)
from test_helpers.test_users import (
    OPS_HEADERS,
    STATISTICIAN_ALT_HEADERS,
    STATISTICIAN_HEADERS,
    STATISTICIAN_SECONDARY,
)

FIRST_TAG_CLOCK_MS = 60000
SECOND_TAG_CLOCK_MS = 70000
FIRST_TAG_CONFIDENCE = 0.9
SECOND_TAG_CONFIDENCE = 0.8
WINDOW_MAX_LATENCY_MS = 400
RECORD_SECONDS = 60
RECORD_UNITS = 30


# ---------------------------------------------------------------------------
# The guarded counter moves under the client's feet
# ---------------------------------------------------------------------------

def test_a_version_that_a_tag_already_consumed_cannot_be_replayed(api, clock):
    """PRD §2.8: "Creating an event tag therefore requires `expected_game_version` as a
    non-optional field of the request body, carrying the client's last observed
    `version` of the target `Game`."
    PRD §2.8: "If `expected_game_version` does not equal the game's current `version` at
    request time — because any other writer has advanced it since the client last read
    the game — the create is rejected with `ERR_STALE_GAME_VERSION` (HTTP 412), and no
    tag, no supersession and no census movement occurs."
    PRD §3.5: "The game's `version` is incremented by one, its `total_tag_count` and
    `draft_tag_count` each rise by one, and the tag's `game_version_at_tag` is stamped
    with the game's `version` *after* that increment — it is the audit anchor a reviewer
    uses to reconstruct which concurrency generation a disputed tag was written
    against."

    The version read at open-collection is spent the moment the first tag lands.

    A second statistician holding that stale figure is refused, and the refusal
    costs nothing: the counter does not move for a rejected write, so re-reading
    the game hands back the very same value, which then works.

    Design: Corner/complexity_layers/stale_expected_game_version_is_refused_and_every_write_bumps_it
    """
    world = fx.live_game_world(api)
    stale_version = world.game_version
    assert stale_version == 2, "creation mints version 1 and opening collection makes it 2"

    first = fx.create_tag(
        api,
        world.game_id,
        world.player["id"],
        stale_version,
        STATISTICIAN_HEADERS,
        clock_ms=FIRST_TAG_CLOCK_MS,
        confidence=FIRST_TAG_CONFIDENCE,
    )
    assert first["game_version_at_tag"] == stale_version + 1

    validate_error(
        api.create_event_tag(
            fac.event_tag_payload(
                world.game_id,
                world.player["id"],
                stale_version,
                tag_type="PASS",
                clock_ms=SECOND_TAG_CLOCK_MS,
                confidence=SECOND_TAG_CONFIDENCE,
            ),
            STATISTICIAN_ALT_HEADERS,
        ),
        ERR_STALE_GAME_VERSION,
    )

    after_refusal = validate_success(api.get_game(world.game_id, STATISTICIAN_HEADERS))
    assert after_refusal["version"] == first["game_version_at_tag"]
    assert_tag_census(
        after_refusal,
        draft=1,
        submitted=0,
        accepted=0,
        under_correction=0,
        superseded=0,
        total=1,
    )

    second = get_success_data(
        api.create_event_tag(
            fac.event_tag_payload(
                world.game_id,
                world.player["id"],
                after_refusal["version"],
                tag_type="PASS",
                clock_ms=SECOND_TAG_CLOCK_MS,
                confidence=SECOND_TAG_CONFIDENCE,
            ),
            STATISTICIAN_ALT_HEADERS,
        ),
        expected_status=201,
    )
    assert second["game_version_at_tag"] == after_refusal["version"] + 1
    assert second["review_status"] == TAG_DRAFT
    assert second["tagged_by_user_id"] == STATISTICIAN_SECONDARY

    final = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert final["version"] == second["game_version_at_tag"]
    assert_tag_census(
        final, draft=2, submitted=0, accepted=0, under_correction=0, superseded=0, total=2
    )
    assert_quality_index(final, 0.0)


# ---------------------------------------------------------------------------
# The circuit breaker trips on the third breach, not the second
# ---------------------------------------------------------------------------

def test_the_third_breach_on_one_session_suspends_it_and_holds_the_reservation(api, clock):
    """PRD §3.8: "Breaches are also a circuit breaker: on the third breach recorded against
    a single session, that session moves `ACTIVE → SUSPENDED` with `halt_reason` of
    `SLA_BREACH_THRESHOLD`."
    PRD §3.8: "A breach raises the session's `sla_breach_count` by one and the
    licensee's `audit_flag_count` by one, and it credits the licensee: a quarter of the
    record's charge — the record's `units_charged` multiplied by the tier rate,
    multiplied by 0.25 and rounded half up to whole cents — is added to the licensee's
    `sla_credit_cents`."
    PRD §3.8: "`TERMINATED` is terminal; a further termination attempt is refused with
    `ERR_SESSION_NOT_ACTIVE`, as is any usage report against a non-active session."

    Two breaches leave the feed running; the third takes it off the air.

    The credit ledger accumulates one quarter-charge per breach throughout, and
    the suspension is a halt rather than a settlement, so the reservation is
    still held and nothing has been consumed.

    Design: Corner/complexity_layers/third_sla_breach_on_one_session_suspends_it_at_the_threshold
    """
    world = fx.active_session_world(
        api, window_overrides={"max_latency_ms": WINDOW_MAX_LATENCY_MS}
    )
    assert world.session["reserved_units"] == 900

    breach_latencies = [500, WINDOW_MAX_LATENCY_MS + 1, 900]
    sample_times = [
        "2026-08-01T18:05:00Z",
        "2026-08-01T18:10:00Z",
        "2026-08-01T18:15:00Z",
    ]
    for index, (sampled_at_utc, latency_p95_ms) in enumerate(
        zip(sample_times, breach_latencies), start=1
    ):
        record = get_success_data(
            api.create_usage_record(
                world.session_id,
                fac.usage_record_payload(
                    sampled_at_utc=sampled_at_utc,
                    duration_seconds=RECORD_SECONDS,
                    latency_p95_ms=latency_p95_ms,
                ),
                world.licensee_headers,
            ),
            expected_status=201,
        )
        assert record["units_charged"] == RECORD_UNITS
        assert record["sla_breach"] is True

        session = validate_success(api.get_feed_session(world.session_id, OPS_HEADERS))
        assert session["sla_breach_count"] == index
        assert session["usage_record_count"] == index
        assert session["metered_units"] == index * RECORD_UNITS
        if index < SLA_BREACH_SUSPEND_THRESHOLD:
            assert session["status"] == SESSION_ACTIVE
            assert session["halt_reason"] is None
        else:
            assert session["status"] == SESSION_SUSPENDED
            assert session["halt_reason"] == HALT_SLA_BREACH_THRESHOLD

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert licensee["audit_flag_count"] == SLA_BREACH_SUSPEND_THRESHOLD
    assert licensee["sla_credit_cents"] == 495
    assert licensee["sla_credit_cents"] == SLA_BREACH_SUSPEND_THRESHOLD * (
        expected_sla_credit_cents(RECORD_UNITS, TIER_GOLD)
    )
    assert_unit_ledger(licensee, available=4100, reserved=900, consumed=0)

    validate_error(
        api.create_usage_record(
            world.session_id,
            fac.usage_record_payload(
                sampled_at_utc="2026-08-01T18:20:00Z",
                duration_seconds=RECORD_SECONDS,
                latency_p95_ms=200,
            ),
            world.licensee_headers,
        ),
        ERR_SESSION_NOT_ACTIVE,
    )

    _, meta = validate_paginated(
        api.list_usage_records(world.session_id, world.licensee_headers)
    )
    assert meta["total_count"] == SLA_BREACH_SUSPEND_THRESHOLD
