"""State-machine compliance: declared transitions, terminal lockdown and self-edges.

Every test builds its own world from an empty database, because the server is
restarted before each individual test. The logical clock is always set
explicitly whenever a temporal rule is in play.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    BUSINESS_AFFAIRS,
    FINANCE_CONTROLLER,
    PRODUCTION_MANAGER,
    PRODUCTION_MANAGER_2,
    TALENT_BUYER,
    assert_booking_state,
    expected_adjudicated_risk_score,
    expected_draw_penalty,
    expected_strict_risk_score,
    make_artist_rep_headers,
)
from test_helpers import fixtures as fx
from test_helpers.constants import (
    ALLOCATABLE_BUDGET_CENTS,
    CANONICAL_GUARANTEE_CENTS,
    DEFAULT_CLOCK_UTC,
    PORTLAND_DISTANCE_MILES,
)
from test_helpers.factories import (
    advance_packet_payload,
    offer_payload,
)

# --------------------------------------------------------------- canonical world
# Harbor Lights Festival 2026: talent budget 10000000 less the 5% reserve leaves
# an allocatable 9500000, split 0.50 / 0.30 / 0.20 across three tiers, so the
# HEADLINER tier is allocated 4750000 and every tier carries max_slots 5.
HEADLINER_ALLOCATION_CENTS = 4750000
MID_CARD_ALLOCATION_CENTS = 2850000
EMERGING_ALLOCATION_CENTS = 1900000

# The act: Nova Kade, ELECTRONIC, draw_score 72 -> draw component
# max(500000, 72 * 25000) = 1800000, genre factor 1.00 on a fresh edition.
CANONICAL_CEILING_CENTS = 1800000
CANONICAL_DRAW_SCORE = 72

# One slot on the first show day: 21:00 -> 22:30 UTC, inside the curfew minute
# 1380 and inside the event window 2026-12-04 .. 2026-12-06.
CANONICAL_SLOT_START = "2026-12-04T21:00:00Z"
CANONICAL_SLOT_END = "2026-12-04T22:30:00Z"
CANONICAL_SET_MINUTES = 90

RIDER_UNIT_COST_CENTS = 250000
REVEAL_INSTANT_UTC = "2026-09-10T12:00:00Z"


def _instant(text: str) -> datetime:
    """Parse an ISO 8601 UTC instant so equality ignores fractional-digit style."""
    assert isinstance(text, str) and text, f"expected an ISO 8601 instant, got {text!r}"
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _canonical_edition(api, clock: str = DEFAULT_CLOCK_UTC) -> Dict[str, Any]:
    """Allocated three-tier edition with one flagship stage and one act.

    Keys: festival, tier (the HEADLINER tier), mid_card, emerging, stage,
    artist, artist_headers.
    """
    fx.set_clock(api, clock)
    festival = fx.create_festival(api)
    headliner = fx.create_tier(
        api,
        festival["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=0.5,
        max_slots=5,
        genre_focus="MIXED",
    )
    mid_card = fx.create_tier(
        api,
        festival["id"],
        tier_code="MID_CARD",
        tier_rank=2,
        allocation_pct=0.3,
        max_slots=5,
        genre_focus="MIXED",
    )
    emerging = fx.create_tier(
        api,
        festival["id"],
        tier_code="EMERGING",
        tier_rank=3,
        allocation_pct=0.2,
        max_slots=5,
        genre_focus="MIXED",
    )
    fx.allocate(api, festival)
    stage = fx.create_stage(api, festival["id"])
    artist = fx.create_artist(api, default_radius_miles=100)
    festival = validate_success(api.get_festival(festival["id"], TALENT_BUYER))
    headliner = validate_success(api.get_budget_tier(headliner["id"], TALENT_BUYER))
    assert headliner["allocation_cents"] == HEADLINER_ALLOCATION_CENTS
    return {
        "festival": festival,
        "tier": headliner,
        "mid_card": mid_card,
        "emerging": emerging,
        "stage": stage,
        "artist": artist,
        "artist_headers": make_artist_rep_headers(artist["id"]),
    }


def _draft_offer(
    api,
    ctx: Dict[str, Any],
    artist: Optional[Dict[str, Any]] = None,
    tier: Optional[Dict[str, Any]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Draft an offer on the canonical slot unless the caller moves it."""
    artist = artist or ctx["artist"]
    tier = tier or ctx["tier"]
    fields: Dict[str, Any] = {"slot_start_utc": CANONICAL_SLOT_START}
    fields.update(overrides)
    payload = offer_payload(
        ctx["festival"]["id"], artist["id"], tier["id"], ctx["stage"]["id"], **fields
    )
    return validate_success(api.create_offer(payload, TALENT_BUYER), 201)


def _issued_offer(api, ctx: Dict[str, Any], **overrides) -> Dict[str, Any]:
    offer = _draft_offer(api, ctx, **overrides)
    return validate_success(api.issue_offer(offer["id"], TALENT_BUYER))


def _accepted_booking(api, ctx: Dict[str, Any], **overrides) -> Dict[str, Any]:
    offer = _issued_offer(api, ctx, **overrides)
    return validate_success(api.accept_offer(offer["id"], ctx["artist_headers"]), 201)


def _rider_settled_booking(api, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Accepted booking whose single TECHNICAL rider line is already APPROVED."""
    booking = _accepted_booking(api, ctx)
    line = fx.add_rider_line(
        api,
        booking["id"],
        ctx["artist"]["id"],
        category="TECHNICAL",
        description="Line-array PA package",
        quantity=1,
        unit_cost_cents=RIDER_UNIT_COST_CENTS,
    )
    fx.decide_rider_line(api, line["id"], "APPROVED")
    return {
        "booking": validate_success(api.get_booking(booking["id"], TALENT_BUYER)),
        "rider_item": validate_success(api.get_rider_item(line["id"], TALENT_BUYER)),
    }


def _advance_packet(api, booking_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    payload = advance_packet_payload(
        booking_id,
        stage_plot_ref="SP-AURORA-1",
        input_channel_count=48,
        monitor_mix_count=8,
        travel_party_size=12,
        load_in_offset_minutes=None,
    )
    return validate_success(api.create_advance_packet(payload, headers), 201)


def _countersigned_booking(api, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Booking taken to COUNTERSIGNED, its packet submitted by the agent side."""
    settled = _rider_settled_booking(api, ctx)
    booking_id = settled["booking"]["id"]
    packet = _advance_packet(api, booking_id, ctx["artist_headers"])
    packet = validate_success(
        api.submit_advance_packet(packet["id"], ctx["artist_headers"])
    )
    packet = validate_success(
        api.approve_advance_packet(packet["id"], PRODUCTION_MANAGER)
    )
    booking = validate_success(api.countersign_booking(booking_id, BUSINESS_AFFAIRS))
    return {"booking": booking, "rider_item": settled["rider_item"], "packet": packet}


def _locked_presale_wave(api, ctx: Dict[str, Any], booking_id: str) -> Dict[str, Any]:
    wave = fx.planned_wave(
        api,
        ctx["festival"]["id"],
        wave_number=1,
        phase="PRESALE",
        scheduled_reveal_utc=REVEAL_INSTANT_UTC,
    )
    wave = fx.assign_to_wave(api, wave, booking_id)
    return validate_success(api.lock_wave(wave["id"], TALENT_BUYER))


# ------------------------------------------------------------------ initial state
def test_a_new_advance_packet_opens_in_draft_with_no_submissions(api):
    """Opening the technical advance yields DRAFT with both counters at zero.

    "A new packet opens with `status` `DRAFT`, `submission_count` 0 and `channel_overage` 0."
    "On success `status` moves to `SUBMITTED`, `submission_count` increases by one, `submitted_by_user_id` is overwritten with the submitter's `X-User-ID` on every submission, and `channel_overage` is re-stamped as the amount by which that same stage-day channel total including this packet exceeds the advisory comfort level of 96 channels, or 0 when it does not exceed it."
    Design: Corner/state_machines/advance_packet_initial_state_draft
    """
    ctx = _canonical_edition(api)
    booking = _accepted_booking(api, ctx)
    assert_booking_state(booking, "PENDING_RIDER", "UNFUNDED")

    payload = advance_packet_payload(
        booking["id"],
        stage_plot_ref="SP-AURORA-1",
        input_channel_count=48,
        monitor_mix_count=8,
        travel_party_size=12,
        load_in_offset_minutes=None,
    )
    packet = validate_success(
        api.create_advance_packet(payload, ctx["artist_headers"]), 201
    )

    assert packet["status"] == "DRAFT"
    assert packet["submission_count"] == 0
    # 48 channels already exist on the packet, but the advisory overage against
    # the 96-channel comfort level is only stamped by a submission.
    assert packet["channel_overage"] == 0
    assert packet["input_channel_count"] == 48
    assert packet.get("submitted_by_user_id") is None
    assert packet.get("approved_by_user_id") is None
    assert packet.get("return_reason") is None


# -------------------------------------------------------------- valid transitions
def test_issuing_an_offer_stamps_the_ceiling_and_activates_its_radius_clause(api):
    """DRAFT -> ISSUED stamps the ceiling and moves the clause PROVISIONAL -> ACTIVE.

    "When all of that passes, `status` moves `DRAFT → ISSUED`, `round_number` increases by one, `genre_balance_factor` and `guarantee_ceiling_cents` are stamped from the ceiling computation, `issued_by_user_id` records the acting buyer's `X-User-ID`, `slot_end_utc` is recomputed from the current `slot_start_utc` and `set_length_minutes`, and the offer's radius clause moves `PROVISIONAL → ACTIVE`."
    "A draft commits no budget and reserves no stage time."
    Design: Corner/state_machines/offer_issue_transition_stamps_ceiling_and_activates_clause
    """
    ctx = _canonical_edition(api)
    offer = _draft_offer(api, ctx)
    assert offer["status"] == "DRAFT"

    issued = validate_success(api.issue_offer(offer["id"], TALENT_BUYER))

    assert issued["status"] == "ISSUED"
    # min(tier headroom 4750000, festival headroom 9500000,
    #     floor(max(500000, 72 * 25000) * 1.00) = 1800000)
    assert issued["guarantee_ceiling_cents"] == CANONICAL_CEILING_CENTS
    assert HEADLINER_ALLOCATION_CENTS - 0 >= CANONICAL_CEILING_CENTS
    assert ALLOCATABLE_BUDGET_CENTS - 0 >= CANONICAL_CEILING_CENTS
    assert float(issued["genre_balance_factor"]) == 1.00
    assert issued["round_number"] == 1
    assert issued["issued_by_user_id"] == TALENT_BUYER["X-User-ID"]
    assert _instant(issued["slot_end_utc"]) == _instant(CANONICAL_SLOT_END)

    clause = fx.clause_of_offer(api, offer["id"])
    assert clause["enforcement_status"] == "ACTIVE"
    assert clause["booking_id"] is None

    tier = validate_success(api.get_budget_tier(ctx["tier"]["id"], TALENT_BUYER))
    assert tier["committed_cents"] == 0
    assert tier["slots_committed"] == 0
    stage = validate_success(api.get_stage(ctx["stage"]["id"], PRODUCTION_MANAGER))
    assert stage["booked_minutes"] == 0


def test_countering_records_the_agents_ask_without_moving_the_promoters_terms(api):
    """ISSUED -> COUNTERED records the ask and consumes no negotiation round.

    "The payload carries a `counter_guarantee_cents` and optionally a `counter_billing_position`, a `counter_set_length_minutes` and a free-text `counter_note`; each is recorded on the offer, and any of the three optional fields that the counter does not move stays null."
    "Critically, `round_number` does not change — only promoter-side issuances consume rounds — and `guarantee_cents`, `billing_position`, `set_length_minutes` and the slot itself are untouched."
    Design: Corner/state_machines/offer_counter_records_ask_without_moving_terms
    """
    ctx = _canonical_edition(api)
    issued = _issued_offer(api, ctx)
    assert issued["round_number"] == 1

    countered = validate_success(
        api.counter_offer(
            issued["id"],
            {
                "counter_guarantee_cents": 2100000,
                "counter_billing_position": 1,
                "counter_set_length_minutes": 100,
                "counter_note": "Agent asks for 21k and ten more minutes.",
            },
            ctx["artist_headers"],
        )
    )

    assert countered["status"] == "COUNTERED"
    assert countered["round_number"] == 1
    assert countered["guarantee_cents"] == CANONICAL_GUARANTEE_CENTS
    assert countered["set_length_minutes"] == CANONICAL_SET_MINUTES
    assert countered["billing_position"] == 1
    assert _instant(countered["slot_start_utc"]) == _instant(CANONICAL_SLOT_START)
    assert _instant(countered["slot_end_utc"]) == _instant(CANONICAL_SLOT_END)
    assert countered["counter_guarantee_cents"] == 2100000
    assert countered["counter_set_length_minutes"] == 100
    assert countered["counter_billing_position"] == 1
    # An ask of 2100000 sits above the stamped ceiling of 1800000 and is still
    # recorded, because the ceiling gate belongs to issuance and revision.
    assert countered["guarantee_ceiling_cents"] == CANONICAL_CEILING_CENTS


def test_declining_a_countered_offer_releases_its_radius_clause(api):
    """COUNTERED -> DECLINED releases the clause and touches no ledger.

    "Declining is available from `ISSUED` and from `COUNTERED`, requires the caller to be the offer's act, accepts an optional `decline_reason`, and moves `status` to `DECLINED`."
    "The offer's radius clause goes to `RELEASED` — from `PROVISIONAL` when the offer was never issued, from `ACTIVE` when it was — and no budget or stage ledger is touched, because none was ever committed."
    Design: Corner/state_machines/offer_decline_from_countered_releases_clause
    """
    ctx = _canonical_edition(api)
    issued = _issued_offer(api, ctx)
    validate_success(
        api.counter_offer(
            issued["id"], {"counter_guarantee_cents": 2100000}, ctx["artist_headers"]
        )
    )

    declined = validate_success(
        api.decline_offer(
            issued["id"],
            ctx["artist_headers"],
            {"decline_reason": "Artist took a competing routing."},
        )
    )
    assert declined["status"] == "DECLINED"

    clause = fx.clause_of_offer(api, issued["id"])
    assert clause["enforcement_status"] == "RELEASED"
    assert clause["waiver_status"] == "NONE"

    summary = validate_success(
        api.get_budget_summary(ctx["festival"]["id"], TALENT_BUYER)
    )
    assert summary["committed_budget_cents"] == 0
    assert summary["tier_committed_sum_cents"] == 0
    assert summary["booking_committed_sum_cents"] == 0
    assert summary["lineup_posture"] == "OPEN"
    assert summary["headliner_anchor_count"] == 0


def test_denying_a_waiver_leaves_the_clause_breached_and_the_money_held(api):
    """A DENIED decision is a declared self-edge on a BREACHED clause.

    "Denying is the declared self-edge: the clause's `waiver_status` becomes `DENIED`, `waiver_fee_cents` stays 0, `enforcement_status` remains `BREACHED`, and consequently the money stays held."
    Design: Corner/state_machines/waiver_denied_keeps_clause_breached_on_self_edge
    """
    ctx = _canonical_edition(api)
    booking = _countersigned_booking(api, ctx)["booking"]
    assert_booking_state(booking, "COUNTERSIGNED", "UNFUNDED")

    performance = fx.report_performance(
        api,
        ctx["artist"]["id"],
        performance_date="2026-11-15",
        announced_capacity=4000,
    )
    assert performance["conflict_assessment"] == "CONFLICT"
    assert performance["distance_to_market_miles"] == PORTLAND_DISTANCE_MILES
    fx.adjudicate(api, performance["id"], "VIOLATION", "Adjudicated by business affairs.")

    clause = fx.clause_of_booking(api, booking["id"])
    assert clause["enforcement_status"] == "BREACHED"
    validate_success(
        api.request_waiver(
            clause["id"],
            {
                "competing_performance_id": performance["id"],
                "waiver_fee_offer_cents": 200000,
                "request_note": "One-off ticketed club show.",
            },
            ctx["artist_headers"],
        )
    )

    decided = validate_success(
        api.decide_waiver(
            clause["id"],
            {"decision": "DENIED", "decision_note": "Inside the protected window."},
            BUSINESS_AFFAIRS,
        )
    )

    assert decided["waiver_status"] == "DENIED"
    assert decided["enforcement_status"] == "BREACHED"
    assert decided["breach_count"] == 1
    assert decided["waiver_fee_cents"] == 0

    installments = fx.installments_of(api, booking["id"])
    assert installments["DEPOSIT"]["status"] == "HELD"
    assert installments["BALANCE"]["status"] == "HELD"

    after = validate_success(api.get_booking(booking["id"], BUSINESS_AFFAIRS))
    assert_booking_state(after, "COUNTERSIGNED", "WITHHELD")

    report = validate_success(
        api.get_competing_performance(performance["id"], BUSINESS_AFFAIRS)
    )
    assert report["status"] == "VIOLATION"


def test_sweeping_expired_offers_expires_live_offers_and_repeats_harmlessly(api):
    """The sweep rewrites only ISSUED or COUNTERED offers whose expiry has arrived.

    "The ops-run sweep is what actually rewrites state: every offer whose `status` is `ISSUED` or `COUNTERED` and whose `offer_expires_utc` is at or before the logical clock becomes `EXPIRED`, and each such offer's clause becomes `RELEASED` so that conflict detection stops seeing it."
    "A `DRAFT` offer is never swept, because no transition from `DRAFT` to `EXPIRED` exists."
    "A second sweep with nothing newly expired reports `expired_count` 0 and is not an error."
    Design: Corner/state_machines/sweep_expired_moves_live_offers_and_is_idempotent
    """
    ctx = _canonical_edition(api)
    vela = fx.create_artist(
        api,
        legal_name="Vela Roan Touring Ltd",
        performing_name="Vela Roan",
        primary_genre="ROCK",
        draw_score=40,
        default_radius_miles=100,
    )

    never_issued = _draft_offer(
        api,
        ctx,
        slot_start_utc="2026-12-06T21:00:00Z",
        offer_expires_utc="2026-09-01T00:00:00Z",
    )
    first_live = _issued_offer(
        api,
        ctx,
        slot_start_utc="2026-12-04T21:00:00Z",
        offer_expires_utc="2026-09-01T00:00:00Z",
    )
    second_live = _issued_offer(
        api,
        ctx,
        slot_start_utc="2026-12-05T21:00:00Z",
        offer_expires_utc="2026-09-01T00:00:00Z",
    )
    still_live = _issued_offer(
        api,
        ctx,
        artist=vela,
        tier=ctx["mid_card"],
        guarantee_cents=1000000,
        billing_position=2,
        set_length_minutes=60,
        slot_start_utc="2026-12-04T12:00:00Z",
        offer_expires_utc="2026-10-01T00:00:00Z",
        radius_miles=100,
    )

    fx.set_clock(api, "2026-09-01T00:00:00Z")
    swept = validate_success(
        api.sweep_expired_offers(BUSINESS_AFFAIRS, {"festival_id": ctx["festival"]["id"]})
    )
    assert swept["expired_count"] == 2
    assert swept["released_clause_count"] == 2
    assert swept["expired_offer_ids"] == [first_live["id"], second_live["id"]]

    repeat = get_success_data(
        api.sweep_expired_offers(BUSINESS_AFFAIRS, {"festival_id": ctx["festival"]["id"]})
    )
    assert repeat["expired_count"] == 0
    assert repeat["released_clause_count"] == 0

    rows, meta = validate_paginated(
        api.list_offers(
            TALENT_BUYER, {"festival_id": ctx["festival"]["id"], "status": "EXPIRED"}
        )
    )
    assert meta["total_count"] == 2
    expired_ids = {row["id"] for row in rows}
    assert never_issued["id"] not in expired_ids
    assert still_live["id"] not in expired_ids

    assert (
        validate_success(api.get_offer(never_issued["id"], TALENT_BUYER))["status"]
        == "DRAFT"
    )
    assert (
        validate_success(api.get_offer(still_live["id"], TALENT_BUYER))["status"]
        == "ISSUED"
    )
    assert fx.clause_of_offer(api, never_issued["id"])["enforcement_status"] == "PROVISIONAL"
    assert fx.clause_of_offer(api, first_live["id"])["enforcement_status"] == "RELEASED"
    assert fx.clause_of_offer(api, still_live["id"])["enforcement_status"] == "ACTIVE"


# ----------------------------------------------------------- invalid transitions
def test_accepting_a_never_issued_draft_offer_is_refused(api):
    """Acceptance is declared only from ISSUED, so a DRAFT offer cannot be accepted.

    "It requires the offer to be `ISSUED`, the caller's `X-User-ID` to equal the offer's `artist_id`, the logical clock to be strictly before `offer_expires_utc`, the edition's `lineup_posture` to be `OPEN` or `RESTRICTED`, and the tier's `status` to be `OPEN`."
    "`ACCEPTED`, `DECLINED`, `EXPIRED` and `SUPERSEDED` are all terminal: a further negotiation call against any of them is `ERR_OFFER_NOT_NEGOTIABLE`, which is also what a repeat call on an already-transitioned offer returns."
    Design: Corner/state_machines/offer_accept_from_draft_state_rejected
    """
    ctx = _canonical_edition(api)
    offer = _draft_offer(api, ctx)

    validate_error(
        api.accept_offer(offer["id"], ctx["artist_headers"]),
        "ERR_OFFER_NOT_NEGOTIABLE",
        409,
    )

    after = validate_success(api.get_offer(offer["id"], TALENT_BUYER))
    assert after["status"] == "DRAFT"

    _rows, meta = validate_paginated(
        api.list_bookings(TALENT_BUYER, {"offer_id": offer["id"]})
    )
    assert meta["total_count"] == 0

    tier = validate_success(api.get_budget_tier(ctx["tier"]["id"], TALENT_BUYER))
    assert tier["committed_cents"] == 0
    assert tier["slots_committed"] == 0
    stage = validate_success(api.get_stage(ctx["stage"]["id"], PRODUCTION_MANAGER))
    assert stage["booked_minutes"] == 0


def test_returning_a_draft_advance_packet_is_refused(api):
    """Return is declared only from SUBMITTED, so a DRAFT packet cannot be returned.

    "Production returns a packet for revision with a `return_reason`, which is recorded on the packet and moves `status` `SUBMITTED → RETURNED`."
    "Any other advance transition — submitting an `APPROVED` packet, approving a `DRAFT` one — is `ERR_INVALID_ADVANCE_STATE`."
    Design: Corner/state_machines/advance_packet_return_from_draft_rejected
    """
    ctx = _canonical_edition(api)
    booking = _accepted_booking(api, ctx)
    packet = _advance_packet(api, booking["id"], ctx["artist_headers"])
    assert packet["status"] == "DRAFT"
    assert packet.get("submitted_by_user_id") is None

    # pm-001 differs from the packet's (still unset) submitter, so the
    # segregation-of-duties comparison cannot be what fails here.
    validate_error(
        api.return_advance_packet(
            packet["id"],
            {"return_reason": "Stage plot missing monitor positions."},
            PRODUCTION_MANAGER,
        ),
        "ERR_INVALID_ADVANCE_STATE",
        409,
    )

    after = validate_success(api.get_advance_packet(packet["id"], PRODUCTION_MANAGER))
    assert after["status"] == "DRAFT"
    assert after["submission_count"] == 0
    assert after.get("return_reason") is None


# ------------------------------------------------------- terminal-state lockdown
def test_an_approved_advance_packet_accepts_no_further_action(api):
    """APPROVED is terminal: submit, return and approve are all refused from it.

    "Approval writes `approved_by_user_id` and moves `status` to `APPROVED`, which is terminal."
    "Any other advance transition — submitting an `APPROVED` packet, approving a `DRAFT` one — is `ERR_INVALID_ADVANCE_STATE`."
    Design: Corner/state_machines/advance_packet_approved_state_is_terminal
    """
    ctx = _canonical_edition(api)
    settled = _rider_settled_booking(api, ctx)
    booking_id = settled["booking"]["id"]
    packet = _advance_packet(api, booking_id, ctx["artist_headers"])
    packet = validate_success(
        api.submit_advance_packet(packet["id"], ctx["artist_headers"])
    )
    assert packet["status"] == "SUBMITTED"
    assert packet["submission_count"] == 1
    packet = validate_success(
        api.approve_advance_packet(packet["id"], PRODUCTION_MANAGER)
    )
    assert packet["status"] == "APPROVED"

    validate_error(
        api.submit_advance_packet(packet["id"], ctx["artist_headers"]),
        "ERR_INVALID_ADVANCE_STATE",
        409,
    )
    # A second production manager, whose X-User-ID differs from the artist-side
    # submitter, is still refused — the lockdown is the state, not the duties gate.
    validate_error(
        api.return_advance_packet(
            packet["id"],
            {"return_reason": "Late change to the input list."},
            PRODUCTION_MANAGER_2,
        ),
        "ERR_INVALID_ADVANCE_STATE",
        409,
    )
    validate_error(
        api.approve_advance_packet(packet["id"], PRODUCTION_MANAGER_2),
        "ERR_INVALID_ADVANCE_STATE",
        409,
    )

    after = validate_success(api.get_advance_packet(packet["id"], PRODUCTION_MANAGER))
    assert after["status"] == "APPROVED"
    assert after["submission_count"] == 1
    assert after["approved_by_user_id"] == PRODUCTION_MANAGER["X-User-ID"]


def test_cancelling_an_already_cancelled_booking_is_refused_and_credits_once(api):
    """CANCELLED is terminal and the compensating credit ran exactly once.

    "Cancellation is the system's principal compensating operation, available to a `TalentBuyer` or `BusinessAffairs` from `PENDING_RIDER`, `RIDER_SETTLED` and `COUNTERSIGNED` alike, with identical consequences from each."
    "Neither dimension waits on the other, and a transition illegal on either dimension is `ERR_INVALID_BOOKING_STATE`."
    Design: Corner/state_machines/booking_cancelled_state_is_terminal_and_credits_once
    """
    ctx = _canonical_edition(api)
    booking = _accepted_booking(api, ctx)

    cancelled = validate_success(
        api.cancel_booking(
            booking["id"],
            {
                "cancelling_party": "PROMOTER",
                "cancellation_reason": "Stage reconfiguration dropped the slot.",
            },
            TALENT_BUYER,
        )
    )
    assert cancelled["contract_status"] == "CANCELLED"

    validate_error(
        api.cancel_booking(
            booking["id"],
            {
                "cancelling_party": "PROMOTER",
                "cancellation_reason": "Duplicate cancellation request.",
            },
            BUSINESS_AFFAIRS,
        ),
        "ERR_INVALID_BOOKING_STATE",
        409,
    )

    after = validate_success(api.get_booking(booking["id"], BUSINESS_AFFAIRS))
    assert_booking_state(after, "CANCELLED", "RECOVERED")
    # A promoter cancellation carries neither a deposit share nor liquidated damages.
    assert after["contractual_recovery_cents"] == 0
    assert after["actual_recovered_cents"] == 0

    summary = validate_success(
        api.get_budget_summary(ctx["festival"]["id"], FINANCE_CONTROLLER)
    )
    assert summary["committed_budget_cents"] == 0
    assert summary["tier_committed_sum_cents"] == 0
    assert summary["booking_committed_sum_cents"] == 0
    assert summary["headliner_anchor_count"] == 0

    stage = validate_success(api.get_stage(ctx["stage"]["id"], PRODUCTION_MANAGER))
    assert stage["booked_minutes"] == 0

    installments = fx.installments_of(api, booking["id"])
    assert installments["DEPOSIT"]["status"] == "VOIDED"
    assert installments["BALANCE"]["status"] == "VOIDED"


# --------------------------------------------------------------------- idempotency
def test_declining_an_already_declined_offer_is_refused(api):
    """DECLINED is terminal, so the repeated decline errors and re-runs no side effect.

    "`ACCEPTED`, `DECLINED`, `EXPIRED` and `SUPERSEDED` are all terminal: a further negotiation call against any of them is `ERR_OFFER_NOT_NEGOTIABLE`, which is also what a repeat call on an already-transitioned offer returns."
    Design: Corner/state_machines/offer_decline_twice_second_call_rejected
    """
    ctx = _canonical_edition(api)
    issued = _issued_offer(api, ctx)
    declined = validate_success(
        api.decline_offer(
            issued["id"], ctx["artist_headers"], {"decline_reason": "Routing conflict."}
        )
    )
    assert declined["status"] == "DECLINED"

    validate_error(
        api.decline_offer(
            issued["id"],
            ctx["artist_headers"],
            {"decline_reason": "Duplicate submission of the same decline."},
        ),
        "ERR_OFFER_NOT_NEGOTIABLE",
        409,
    )

    rows, meta = validate_paginated(
        api.list_radius_clauses(BUSINESS_AFFAIRS, {"offer_id": issued["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["enforcement_status"] == "RELEASED"
    assert rows[0]["breach_count"] == 0

    after = validate_success(api.get_offer(issued["id"], TALENT_BUYER))
    assert after["status"] == "DECLINED"


def test_deciding_an_already_approved_rider_line_twice_is_refused(api):
    """A decided rider line is terminal and the retry re-adds nothing to either total.

    "The line must still be `PROPOSED` — a second decision is `ERR_RIDER_ITEM_ALREADY_DECIDED` — and the parent booking's `contract_status` must be `PENDING_RIDER` or `RIDER_SETTLED`."
    "In all three branches, when the decision leaves no line of that booking still `PROPOSED` and the booking has at least one rider line, the booking's `contract_status` moves `PENDING_RIDER → RIDER_SETTLED`."
    Design: Corner/state_machines/rider_item_second_decision_rejected
    """
    ctx = _canonical_edition(api)
    settled = _rider_settled_booking(api, ctx)
    booking_id = settled["booking"]["id"]
    line = settled["rider_item"]
    assert line["approval_status"] == "APPROVED"
    assert line["line_cost_cents"] == RIDER_UNIT_COST_CENTS

    validate_error(
        api.decide_rider_item(line["id"], {"decision": "APPROVED"}, PRODUCTION_MANAGER),
        "ERR_RIDER_ITEM_ALREADY_DECIDED",
        409,
    )

    booking = validate_success(api.get_booking(booking_id, PRODUCTION_MANAGER))
    assert booking["contract_status"] == "RIDER_SETTLED"
    assert booking["rider_proposed_cents"] == RIDER_UNIT_COST_CENTS
    assert booking["rider_estimate_cents"] == RIDER_UNIT_COST_CENTS

    estimate = validate_success(
        api.get_rider_estimate(booking_id, PRODUCTION_MANAGER, {"variant": "BOTH"})
    )
    assert estimate["proposed_scope_cents"] == RIDER_UNIT_COST_CENTS
    assert estimate["contracted_scope_cents"] == RIDER_UNIT_COST_CENTS
    assert estimate["variant_delta_cents"] == 0
    assert estimate["priced_line_count"] == 1


# ------------------------------------------------------- precondition enforcement
def test_publishing_a_wave_is_refused_before_and_allowed_at_the_reveal_instant(api):
    """The reveal gate is inclusive: early publication fails, publication at it passes.

    "It requires the logical clock to have reached `scheduled_reveal_utc` — publishing exactly at the reveal instant is allowed, and publishing early is `ERR_REVEAL_NOT_DUE` — and it re-checks phase parity with the edition."
    "It stamps `published_at` from the logical clock."
    Design: Corner/state_machines/wave_publish_boundary_before_and_at_reveal_instant
    """
    ctx = _canonical_edition(api)
    booking = _countersigned_booking(api, ctx)["booking"]
    wave = _locked_presale_wave(api, ctx, booking["id"])
    assert wave["status"] == "LOCKED"

    validate_error(
        api.publish_wave(wave["id"], TALENT_BUYER), "ERR_REVEAL_NOT_DUE", 409
    )
    still_locked = validate_success(
        api.get_announcement_wave(wave["id"], TALENT_BUYER)
    )
    assert still_locked["status"] == "LOCKED"
    assert still_locked["published_at"] is None

    fx.set_clock(api, REVEAL_INSTANT_UTC)
    published = validate_success(api.publish_wave(wave["id"], TALENT_BUYER))

    assert published["status"] == "PUBLISHED"
    assert _instant(published["published_at"]) == _instant(REVEAL_INSTANT_UTC)
    assert published["assignment_count"] == 1
    assert published["headliner_count"] == 1


def test_advancing_a_phase_requires_the_next_step_and_a_published_wave(api):
    """Phase progression is one step at a time and gated on the vacated phase's waves.

    "The request is refused with `ERR_PHASE_PREREQ_UNMET` unless `target_phase` is the immediate successor of the current `announcement_phase`, at least one announcement wave of this edition is tied to the phase being left, and every wave tied to that phase has reached `PUBLISHED`."
    Design: Corner/state_machines/advance_phase_requires_immediate_successor_and_published_wave
    """
    ctx = _canonical_edition(api)
    festival_id = ctx["festival"]["id"]
    booking = _countersigned_booking(api, ctx)["booking"]
    wave = _locked_presale_wave(api, ctx, booking["id"])

    # The PRESALE wave is only LOCKED, so the immediate successor is still refused.
    validate_error(
        api.advance_phase(festival_id, {"target_phase": "TIER1_ONSALE"}, TALENT_BUYER),
        "ERR_PHASE_PREREQ_UNMET",
        409,
    )
    # GA_ONSALE is not the immediate successor of PRESALE.
    validate_error(
        api.advance_phase(festival_id, {"target_phase": "GA_ONSALE"}, TALENT_BUYER),
        "ERR_PHASE_PREREQ_UNMET",
        409,
    )
    unchanged = validate_success(api.get_festival(festival_id, TALENT_BUYER))
    assert unchanged["announcement_phase"] == "PRESALE"

    fx.set_clock(api, REVEAL_INSTANT_UTC)
    published = validate_success(api.publish_wave(wave["id"], TALENT_BUYER))
    assert published["status"] == "PUBLISHED"

    advanced = validate_success(
        api.advance_phase(festival_id, {"target_phase": "TIER1_ONSALE"}, TALENT_BUYER)
    )
    assert advanced["announcement_phase"] == "TIER1_ONSALE"
    # 1800000 / 9500000 is far below 0.85, so the posture stays OPEN.
    assert advanced["committed_budget_cents"] == CANONICAL_GUARANTEE_CENTS
    assert advanced["lineup_posture"] == "OPEN"


# -------------------------------------------------------------- side effects
def test_clearing_a_report_lowers_the_conflict_count_without_touching_the_clause(api):
    """CLEARED re-derives the act's counts and moves nothing else at all.

    "It moves `status` `REPORTED → CLEARED`."
    "Nothing else moves: no clause, no booking and no installment is touched by a clearing."
    Design: Corner/state_machines/cleared_finding_reverses_report_count_without_touching_the_clause
    """
    ctx = _canonical_edition(api)
    booking = _accepted_booking(api, ctx)
    artist_id = ctx["artist"]["id"]

    performance = fx.report_performance(
        api, artist_id, performance_date="2026-11-15", announced_capacity=4000
    )
    assert performance["conflict_assessment"] == "CONFLICT"
    reported = validate_success(api.get_artist(artist_id, BUSINESS_AFFAIRS))
    assert reported["reported_conflict_count"] == 1
    # 12 * 1 unadjudicated conflict + a draw penalty of round_half_up(0.20 * 28) = 6.
    assert reported["strict_risk_score"] == 18
    assert reported["strict_risk_score"] == expected_strict_risk_score(
        1, 0, CANONICAL_DRAW_SCORE
    )
    assert reported["adjudicated_risk_score"] == 6

    cleared = validate_success(
        api.adjudicate_performance(
            performance["id"],
            {"finding": "CLEARED", "finding_note": "Adjudicated by business affairs."},
            BUSINESS_AFFAIRS,
        )
    )
    assert cleared["status"] == "CLEARED"

    artist = validate_success(api.get_artist(artist_id, BUSINESS_AFFAIRS))
    assert artist["reported_conflict_count"] == 0
    assert artist["radius_breach_count"] == 0
    assert artist["strict_risk_score"] == 6
    assert artist["adjudicated_risk_score"] == 6
    assert artist["adjudicated_risk_score"] == expected_adjudicated_risk_score(
        0, CANONICAL_DRAW_SCORE
    )

    risk = validate_success(
        api.get_radius_risk(artist_id, BUSINESS_AFFAIRS, {"variant": "STRICT"})
    )
    assert risk["variant"] == "STRICT"
    assert risk["risk_score"] == 6
    assert risk["draw_penalty"] == expected_draw_penalty(CANONICAL_DRAW_SCORE) == 6
    assert risk["reported_conflict_count"] == 0
    assert risk["blocked"] is False

    clause = fx.clause_of_booking(api, booking["id"])
    assert clause["enforcement_status"] == "ACTIVE"
    assert clause["breach_count"] == 0

    installments = fx.installments_of(api, booking["id"])
    assert installments["DEPOSIT"]["status"] == "SCHEDULED"
    assert installments["BALANCE"]["status"] == "SCHEDULED"
