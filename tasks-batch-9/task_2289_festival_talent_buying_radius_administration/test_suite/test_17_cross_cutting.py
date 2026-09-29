"""Version-checked parents, aggregate counters and the stage-day channel advisory.

The harness restarts the API server before every individual test, so each test
below builds the whole Harbor Lights edition it needs from an empty database
through the public API only.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    BUSINESS_AFFAIRS,
    PRODUCTION_MANAGER,
    TALENT_BUYER,
    make_artist_rep_headers,
)
from test_helpers import fixtures as fx
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.factories import advance_packet_payload, cancel_payload

NOVA_SLOT_UTC = "2026-12-04T21:00:00Z"
VELA_SLOT_UTC = "2026-12-04T18:00:00Z"
RIDER_UNIT_COST_CENTS = 250000
GUARANTEE_CENTS = 1800000
AMENDED_GUARANTEE_CENTS = 1700000


# --------------------------------------------------------------- local builders
def harbor_lights_edition(api):
    """Allocated Harbor Lights edition: three tiers, one flagship stage, Nova Kade.

    Returns the festival row as it read at creation as well as the current one,
    because the creation-time version is what a later waterfall re-run replays.
    """
    fx.set_clock(api, DEFAULT_CLOCK_UTC)
    created = fx.create_festival(api)
    headliner = fx.create_tier(
        api,
        created["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=0.5,
        max_slots=5,
        genre_focus="MIXED",
    )
    fx.create_tier(
        api,
        created["id"],
        tier_code="MID_CARD",
        tier_rank=2,
        allocation_pct=0.3,
        max_slots=5,
        genre_focus="MIXED",
    )
    fx.create_tier(
        api,
        created["id"],
        tier_code="EMERGING",
        tier_rank=3,
        allocation_pct=0.2,
        max_slots=5,
        genre_focus="MIXED",
    )
    fx.allocate(api, created)
    stage = fx.create_stage(api, created["id"])
    artist = fx.create_artist(api, default_radius_miles=100)
    return {
        "festival": validate_success(api.get_festival(created["id"], TALENT_BUYER)),
        "festival_version_at_creation": created["version"],
        "tier": validate_success(api.get_budget_tier(headliner["id"], TALENT_BUYER)),
        "stage": stage,
        "artist": artist,
        "artist_headers": make_artist_rep_headers(artist["id"]),
    }


def second_act(api):
    """A second roster act, so one stage-day can carry two bookings."""
    return fx.create_artist(
        api,
        legal_name="Vela Roan Touring Ltd",
        performing_name="Vela Roan",
        primary_genre="ROCK",
        draw_score=72,
        default_radius_miles=100,
    )


# ----------------------------------------------------- optimistic concurrency
def test_a_stale_festival_version_outranks_the_allocation_lock(api):
    """A waterfall replay on a consumed festival version answers 412, not 409.

    "Re-running the budget waterfall requires `expected_festival_version` to match the target festival's `version`."
    "This sits above every state, safety and fiscal check, so a stale version on an otherwise-invalid request still reports 412."

    Design: Corner/cross-cutting complexity layers/occ_versions_guard_all_three_parents_and_outrank_state_checks
    """
    ctx = harbor_lights_edition(api)
    stale_version = ctx["festival_version_at_creation"]
    fx.accepted_booking(api, ctx, slot_start_utc=NOVA_SLOT_UTC)

    committed = validate_success(api.get_festival(ctx["festival"]["id"], TALENT_BUYER))
    assert committed["committed_budget_cents"] == GUARANTEE_CENTS

    validate_error(
        api.allocate_tiers(
            ctx["festival"]["id"],
            {"expected_festival_version": stale_version},
            TALENT_BUYER,
        ),
        "ERR_STALE_FESTIVAL_VERSION",
        412,
    )

    # With a fresh version the rule underneath is exposed.
    validate_error(
        api.allocate_tiers(
            ctx["festival"]["id"],
            {"expected_festival_version": committed["version"]},
            TALENT_BUYER,
        ),
        "ERR_ALLOCATION_LOCKED",
        409,
    )


def test_a_consumed_booking_version_is_refused_on_a_second_amendment(api):
    """The first amendment consumes the booking version the second one replays.

    "Amending an executed guarantee requires `expected_booking_version` to match the target booking's `version`."
    "Every installment of the booking whose `status` is `SCHEDULED` is voided and replaced by a rebuilt scheduled row, using the same two-row deposit-and-balance construction; installments already `PAID` or `RELEASED` are never rewritten, and the rebuilt scheduled rows absorb the whole difference so that the sum of `amount_cents` over the booking's non-voided installments again equals its `guarantee_cents`."

    Design: Corner/cross-cutting complexity layers/occ_versions_guard_all_three_parents_and_outrank_state_checks
    """
    ctx = harbor_lights_edition(api)
    countersigned = fx.countersigned_booking(
        api,
        ctx,
        unit_cost_cents=RIDER_UNIT_COST_CENTS,
        slot_start_utc=NOVA_SLOT_UTC,
    )
    booking_id = countersigned["booking"]["id"]
    observed = validate_success(api.get_booking(booking_id, TALENT_BUYER))

    amended = validate_success(
        api.amend_guarantee(
            booking_id,
            {
                "guarantee_cents": AMENDED_GUARANTEE_CENTS,
                "expected_booking_version": observed["version"],
                "amendment_reason": "Agreed reduction.",
            },
            TALENT_BUYER,
        )
    )
    assert amended["guarantee_cents"] == AMENDED_GUARANTEE_CENTS
    assert amended["version"] == observed["version"] + 1

    rows, _ = validate_paginated(api.list_payment_installments(booking_id, TALENT_BUYER))
    live = [row for row in rows if row["status"] != "VOIDED"]
    amounts = sorted(row["amount_cents"] for row in live)
    assert amounts == [850000, 850000]
    assert sum(amounts) == AMENDED_GUARANTEE_CENTS

    validate_error(
        api.amend_guarantee(
            booking_id,
            {
                "guarantee_cents": 1600000,
                "expected_booking_version": observed["version"],
                "amendment_reason": "Replay with the consumed version.",
            },
            TALENT_BUYER,
        ),
        "ERR_STALE_BOOKING_VERSION",
        412,
    )


def test_a_consumed_wave_version_outranks_the_already_assigned_refusal(api):
    """Replaying a wave assignment on its consumed version answers 412, not 409.

    "Assigning a booking into an announcement wave requires `expected_announcement_wave_version` to match the target wave's `version`."
    "On success the booking's `announcement_wave_id` is set and its `reveal_order` becomes the wave's `assignment_count` after the increment, so the first booking assigned reveals first."

    Design: Corner/cross-cutting complexity layers/occ_versions_guard_all_three_parents_and_outrank_state_checks
    """
    ctx = harbor_lights_edition(api)
    booking = fx.accepted_booking(api, ctx, slot_start_utc=NOVA_SLOT_UTC)
    wave = fx.planned_wave(
        api, ctx["festival"]["id"], scheduled_reveal_utc="2026-09-10T12:00:00Z"
    )
    consumed_version = wave["version"]

    validate_success(
        api.assign_booking_to_wave(
            wave["id"],
            {
                "booking_id": booking["id"],
                "expected_announcement_wave_version": consumed_version,
            },
            TALENT_BUYER,
        )
    )
    assigned = validate_success(api.get_booking(booking["id"], TALENT_BUYER))
    assert assigned["announcement_wave_id"] == wave["id"]
    assert assigned["reveal_order"] == 1

    validate_error(
        api.assign_booking_to_wave(
            wave["id"],
            {
                "booking_id": booking["id"],
                "expected_announcement_wave_version": consumed_version,
            },
            TALENT_BUYER,
        ),
        "ERR_STALE_WAVE_VERSION",
        412,
    )


# --------------------------------------------------------- aggregate counters
def test_cancelling_a_supporting_act_leaves_both_headliner_counters_alone(api):
    """Only a top-billed member moves the headliner counters when it leaves.

    "Both counters are aggregates: `assignment_count` is the count of bookings carrying this `announcement_wave_id` whose `contract_status` is not `CANCELLED`, and `headliner_count` is the count of those whose `billing_position` is 1."
    "`headliner_anchor_count` counts the edition's anchors: the number of its bookings drawn from the tier whose `tier_code` is `HEADLINER` whose `contract_status` is not `CANCELLED`."

    Design: Corner/cross-cutting complexity layers/wave_and_festival_headliner_counters_track_only_billing_position_one
    """
    ctx = harbor_lights_edition(api)
    nova = ctx["artist"]
    vela = second_act(api)

    top_billed = fx.countersigned_booking(
        api,
        ctx,
        nova,
        unit_cost_cents=RIDER_UNIT_COST_CENTS,
        slot_start_utc=NOVA_SLOT_UTC,
    )["booking"]
    support = fx.countersigned_booking(
        api,
        ctx,
        vela,
        unit_cost_cents=RIDER_UNIT_COST_CENTS,
        billing_position=2,
        slot_start_utc=VELA_SLOT_UTC,
    )["booking"]

    wave = fx.planned_wave(
        api, ctx["festival"]["id"], scheduled_reveal_utc="2026-09-10T12:00:00Z"
    )
    wave_id = wave["id"]
    fx.assign_to_wave(api, wave, top_billed["id"])
    wave = validate_success(api.get_announcement_wave(wave_id, TALENT_BUYER))
    fx.assign_to_wave(api, wave, support["id"])

    loaded = validate_success(api.get_announcement_wave(wave_id, TALENT_BUYER))
    assert loaded["assignment_count"] == 2
    assert loaded["headliner_count"] == 1
    assert loaded["version"] == 3

    validate_success(
        api.cancel_booking(
            support["id"],
            cancel_payload(cancelling_party="ARTIST", cancellation_reason="Illness."),
            BUSINESS_AFFAIRS,
        )
    )

    after_support = validate_success(api.get_announcement_wave(wave_id, TALENT_BUYER))
    assert after_support["assignment_count"] == 1
    assert after_support["headliner_count"] == 1, "the departed member was billed second"

    festival_mid = validate_success(api.get_festival(ctx["festival"]["id"], TALENT_BUYER))
    assert festival_mid["headliner_anchor_count"] == 1
    assert festival_mid["committed_budget_cents"] == GUARANTEE_CENTS

    validate_success(
        api.cancel_booking(
            top_billed["id"],
            cancel_payload(cancelling_party="PROMOTER", cancellation_reason="Storm."),
            TALENT_BUYER,
        )
    )

    emptied = validate_success(api.get_announcement_wave(wave_id, TALENT_BUYER))
    assert emptied["assignment_count"] == 0
    assert emptied["headliner_count"] == 0
    assert emptied["status"] == "PLANNED"

    festival_end = validate_success(api.get_festival(ctx["festival"]["id"], TALENT_BUYER))
    assert festival_end["headliner_anchor_count"] == 0
    assert festival_end["committed_budget_cents"] == 0

    _, meta = validate_paginated(
        api.list_bookings(
            TALENT_BUYER, {"announcement_wave_id": wave_id, "limit": 10}
        )
    )
    assert meta["total_count"] == 0, "the recount matches the emptied assignment_count"


# ------------------------------------------------------- channel advisory level
def test_a_stage_day_channel_total_of_exactly_ninety_six_stamps_no_overage(api):
    """The advisory level is exclusive, and each packet is stamped only on its own submission.

    "On success `status` moves to `SUBMITTED`, `submission_count` increases by one, `submitted_by_user_id` is overwritten with the submitter's `X-User-ID` on every submission, and `channel_overage` is re-stamped as the amount by which that same stage-day channel total including this packet exceeds the advisory comfort level of 96 channels, or 0 when it does not exceed it."
    "The advisory figure and the hard maximum are separate gates: a packet can be accepted while carrying a positive `channel_overage`, because 96 is advice and 112 is law."

    Design: Corner/cross-cutting complexity layers/channel_advisory_at_exactly_96_yields_zero_overage
    """
    ctx = harbor_lights_edition(api)
    nova = ctx["artist"]
    vela = second_act(api)
    nova_headers = make_artist_rep_headers(nova["id"])
    vela_headers = make_artist_rep_headers(vela["id"])

    nova_booking = fx.accepted_booking(api, ctx, nova, slot_start_utc=NOVA_SLOT_UTC)
    vela_booking = fx.accepted_booking(
        api, ctx, vela, billing_position=2, slot_start_utc=VELA_SLOT_UTC
    )

    big_packet = validate_success(
        api.create_advance_packet(
            advance_packet_payload(
                nova_booking["id"],
                stage_plot_ref="SP-AURORA-1",
                input_channel_count=96,
                load_in_offset_minutes=None,
            ),
            nova_headers,
        ),
        201,
    )
    small_packet = validate_success(
        api.create_advance_packet(
            advance_packet_payload(
                vela_booking["id"],
                stage_plot_ref="SP-AURORA-2",
                input_channel_count=1,
                load_in_offset_minutes=None,
            ),
            vela_headers,
        ),
        201,
    )

    first = validate_success(api.submit_advance_packet(big_packet["id"], nova_headers))
    assert first["channel_overage"] == 0, "a stage-day total of exactly 96 is not over"

    second = validate_success(api.submit_advance_packet(small_packet["id"], vela_headers))
    assert second["channel_overage"] == 1, "a stage-day total of 97 is over by one"
    assert second["status"] == "SUBMITTED", "97 is far inside the hard maximum of 112"

    unchanged = validate_success(
        api.get_advance_packet(big_packet["id"], PRODUCTION_MANAGER)
    )
    assert unchanged["channel_overage"] == 0, "an earlier packet is never re-stamped"
