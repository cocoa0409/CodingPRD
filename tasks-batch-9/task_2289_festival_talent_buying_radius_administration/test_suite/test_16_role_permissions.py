"""Role authority, artist-row ownership and segregation of duties.

The harness restarts the API server before every individual test, so each test
below builds the whole Harbor Lights edition it needs from an empty database
through the public API only.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
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
    make_artist_rep_headers,
)
from test_helpers import fixtures as fx
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.factories import advance_packet_payload, cancel_payload

NOVA_SLOT_UTC = "2026-12-04T21:00:00Z"
VELA_SLOT_UTC = "2026-12-04T18:00:00Z"
RIDER_UNIT_COST_CENTS = 250000
GUARANTEE_CENTS = 1800000


# --------------------------------------------------------------- local builders
def harbor_lights_edition(api):
    """Allocated Harbor Lights edition: three tiers, one flagship stage, Nova Kade.

    HEADLINER takes 0.50 of the 9500000 allocatable budget, MID_CARD 0.30 and
    EMERGING 0.20, so the headliner tier is funded at 4750000.
    """
    fx.set_clock(api, DEFAULT_CLOCK_UTC)
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
    fx.create_tier(
        api,
        festival["id"],
        tier_code="MID_CARD",
        tier_rank=2,
        allocation_pct=0.3,
        max_slots=5,
        genre_focus="MIXED",
    )
    fx.create_tier(
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
    return {
        "festival": validate_success(api.get_festival(festival["id"], TALENT_BUYER)),
        "tier": validate_success(api.get_budget_tier(headliner["id"], TALENT_BUYER)),
        "stage": stage,
        "artist": artist,
        "artist_headers": make_artist_rep_headers(artist["id"]),
    }


def second_act(api):
    """A second roster act, so cross-act ownership can be exercised."""
    return fx.create_artist(
        api,
        legal_name="Vela Roan Touring Ltd",
        performing_name="Vela Roan",
        primary_genre="ROCK",
        draw_score=72,
        default_radius_miles=100,
    )


# ------------------------------------------------------------------------ tests
def test_an_agent_is_refused_every_festival_budget_and_stage_endpoint(api):
    """An agent holds no authority at all over edition, tier and stage rows.

    "`ArtistRep` is never authorized on festival, budget-tier or stage reads at all; those come back as `ERR_ROLE_NOT_PERMITTED`."
    "An `ArtistRep` acts on behalf of exactly one act: countering, accepting or declining offers, filing rider lines, opening and submitting the technical advance, and asking to be let out of a radius clause."

    Design: Corner/rbac/artist_rep_is_denied_every_festival_scoped_collection
    """
    ctx = harbor_lights_edition(api)
    agent = ctx["artist_headers"]
    offer = fx.draft_offer(api, ctx, slot_start_utc=NOVA_SLOT_UTC)

    validate_error(
        api.get_festival(ctx["festival"]["id"], agent), "ERR_ROLE_NOT_PERMITTED", 403
    )
    validate_error(
        api.get_budget_tier(ctx["tier"]["id"], agent), "ERR_ROLE_NOT_PERMITTED", 403
    )
    validate_error(
        api.list_festival_stages(ctx["festival"]["id"], agent, {"limit": 10}),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    # Drafting an offer belongs to the buyer, so the agent is refused before any
    # shape or resource check can run.
    denied_draft = api.create_offer(
        {
            "festival_id": ctx["festival"]["id"],
            "artist_id": ctx["artist"]["id"],
            "budget_tier_id": ctx["tier"]["id"],
            "stage_id": ctx["stage"]["id"],
            "guarantee_cents": GUARANTEE_CENTS,
            "billing_position": 2,
            "set_length_minutes": 60,
            "slot_start_utc": "2026-12-05T21:00:00Z",
            "offer_expires_utc": "2026-09-15T00:00:00Z",
            "radius_miles": 150,
            "window_start_date": "2026-10-05",
            "window_end_date": "2027-01-04",
        },
        agent,
    )
    validate_error(denied_draft, "ERR_ROLE_NOT_PERMITTED", 403)

    # The identical caller reads its own offer, so the refusals above are
    # authorization decisions rather than authentication failures.
    own_offer = validate_success(api.get_offer(offer["id"], agent))
    assert own_offer["id"] == offer["id"]
    assert own_offer["artist_id"] == ctx["artist"]["id"]

    rows, meta = validate_paginated(
        api.list_offers(TALENT_BUYER, {"festival_id": ctx["festival"]["id"], "limit": 10})
    )
    assert meta["total_count"] == 1, "the refused draft must not have been written"
    assert rows[0]["id"] == offer["id"]


def test_each_exclusive_operation_refuses_a_plausible_neighbouring_role(api):
    """Every exclusively owned write is refused to the four roles that do not own it.

    "Countersignature is where the contract dimension is executed, and it is `BusinessAffairs`'s exclusive act."
    "A `FinanceController` owns every movement of cash."
    "`BusinessAffairs` owns the paper: countersigning contracts, adjudicating competing-performance reports and deciding radius waivers."
    "Guarantees do get renegotiated after execution, and amending one is a `TalentBuyer` act that ripples through every ledger at once."

    Design: Corner/rbac/each_exclusive_operation_refuses_the_other_four_roles
    """
    ctx = harbor_lights_edition(api)
    artist = ctx["artist"]
    settled = fx.rider_settled_booking(
        api,
        ctx,
        artist,
        unit_cost_cents=RIDER_UNIT_COST_CENTS,
        slot_start_utc=NOVA_SLOT_UTC,
    )
    booking_id = settled["booking"]["id"]
    fx.approved_advance_packet(api, booking_id, artist["id"])
    installments = fx.installments_of(api, booking_id)
    clause = fx.clause_of_booking(api, booking_id)
    booking = validate_success(api.get_booking(booking_id, TALENT_BUYER))

    # The booking is RIDER_SETTLED with an APPROVED packet, so only the role blocks it.
    validate_error(
        api.countersign_booking(booking_id, FINANCE_CONTROLLER),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    # The release window is also closed, yet the role decision comes first.
    validate_error(
        api.release_installment(installments["DEPOSIT"]["id"], TALENT_BUYER),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    # waiver_status is still NONE, yet the role decision comes first.
    validate_error(
        api.decide_waiver(clause["id"], {"decision": "DENIED"}, PRODUCTION_MANAGER),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    # The body carries the current booking version, so nothing else would refuse it.
    validate_error(
        api.amend_guarantee(
            booking_id,
            {"guarantee_cents": 1700000, "expected_booking_version": booking["version"]},
            BUSINESS_AFFAIRS,
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    after = validate_success(api.get_booking(booking_id, TALENT_BUYER))
    assert after["contract_status"] == "RIDER_SETTLED"
    assert after["guarantee_cents"] == GUARANTEE_CENTS


def test_an_agent_cannot_read_another_acts_booking_but_lists_are_narrowed(api):
    """Artist ownership is a row-level refusal and, on collections, a silent filter.

    "A mismatch is `ERR_ARTIST_SCOPE_VIOLATION` (HTTP 403), and because it is a row-level test it can only be evaluated after the row has been found: an `ArtistRep` reaching for another act's booking gets 403 even when the operation itself is open to the role."
    "On list reads, the same binding is applied implicitly — an `ArtistRep` listing offers or bookings sees only rows belonging to their own act."

    Design: Corner/rbac/artist_rep_identity_binding_scopes_rows_and_lists
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

    # The row exists, so the ownership test is reached and answers 403.
    validate_error(
        api.get_booking(nova_booking["id"], vela_headers),
        "ERR_ARTIST_SCOPE_VIOLATION",
        403,
    )
    # The same caller on an unknown id gets the not-found error instead.
    validate_error(
        api.get_booking(NON_EXISTENT_UUID, vela_headers), "ERR_BOOKING_NOT_FOUND", 404
    )

    own = validate_success(api.get_booking(vela_booking["id"], vela_headers))
    assert own["artist_id"] == vela["id"]

    vela_rows, vela_meta = validate_paginated(
        api.list_bookings(vela_headers, {"festival_id": ctx["festival"]["id"], "limit": 10})
    )
    assert vela_meta["total_count"] == 1, "the list is narrowed, not rejected"
    assert vela_rows[0]["id"] == vela_booking["id"]

    nova_rows, nova_meta = validate_paginated(
        api.list_bookings(nova_headers, {"festival_id": ctx["festival"]["id"], "limit": 10})
    )
    assert nova_meta["total_count"] == 1
    assert nova_rows[0]["id"] == nova_booking["id"]

    _, buyer_meta = validate_paginated(
        api.list_bookings(TALENT_BUYER, {"festival_id": ctx["festival"]["id"], "limit": 10})
    )
    assert buyer_meta["total_count"] == 2


def test_the_advance_submitter_can_neither_return_nor_approve_its_own_packet(api):
    """Segregation of duties follows the submitting user id, not the role.

    "Both returning and approving are subject to segregation of duties: the acting `X-User-ID` must differ from `submitted_by_user_id`, and a match is `ERR_SEGREGATION_OF_DUTIES` even for a caller who legitimately holds `ProductionManager`."
    "On success `status` moves to `SUBMITTED`, `submission_count` increases by one, `submitted_by_user_id` is overwritten with the submitter's `X-User-ID` on every submission, and `channel_overage` is re-stamped as the amount by which that same stage-day channel total including this packet exceeds the advisory comfort level of 96 channels, or 0 when it does not exceed it."

    Design: Corner/rbac/advance_submitter_cannot_return_or_approve_its_own_packet
    """
    ctx = harbor_lights_edition(api)
    artist = ctx["artist"]
    settled = fx.rider_settled_booking(
        api,
        ctx,
        artist,
        unit_cost_cents=RIDER_UNIT_COST_CENTS,
        slot_start_utc=NOVA_SLOT_UTC,
    )
    booking_id = settled["booking"]["id"]

    # pm-001 opens and submits the packet, so pm-001 is the recorded submitter.
    packet = validate_success(
        api.create_advance_packet(
            advance_packet_payload(
                booking_id, stage_plot_ref="SP-AURORA-1", load_in_offset_minutes=None
            ),
            PRODUCTION_MANAGER,
        ),
        201,
    )
    submitted = validate_success(
        api.submit_advance_packet(packet["id"], PRODUCTION_MANAGER)
    )
    assert submitted["submitted_by_user_id"] == "pm-001"

    validate_error(
        api.return_advance_packet(
            packet["id"], {"return_reason": "Channel list incomplete."}, PRODUCTION_MANAGER
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )
    validate_error(
        api.approve_advance_packet(packet["id"], PRODUCTION_MANAGER),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    returned = validate_success(
        api.return_advance_packet(
            packet["id"],
            {"return_reason": "Channel list incomplete."},
            PRODUCTION_MANAGER_2,
        )
    )
    assert returned["status"] == "RETURNED"
    assert returned["submission_count"] == 1, "the counter is not reset by a return"

    resubmitted = validate_success(
        api.submit_advance_packet(packet["id"], PRODUCTION_MANAGER_2)
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["submission_count"] == 2
    assert resubmitted["submitted_by_user_id"] == "pm-002"

    # The lock followed the new submitter.
    validate_error(
        api.approve_advance_packet(packet["id"], PRODUCTION_MANAGER_2),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )
    approved = validate_success(
        api.approve_advance_packet(packet["id"], PRODUCTION_MANAGER)
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "pm-001"


def test_shared_operations_accept_either_owning_role(api):
    """Sharing makes the two owning roles interchangeable rather than ranked.

    "Sweeping expired offers, reporting a competing performance, cancelling a booking and locking an announcement wave are each shared between `TalentBuyer` and `BusinessAffairs`; opening and submitting an advance packet are shared between `ArtistRep` and `ProductionManager`; setting the logical clock is available to all five."
    "Cancellation is the system's principal compensating operation, available to a `TalentBuyer` or `BusinessAffairs` from `PENDING_RIDER`, `RIDER_SETTLED` and `COUNTERSIGNED` alike, with identical consequences from each."

    Design: Corner/rbac/shared_operations_accept_either_owning_role
    """
    ctx = harbor_lights_edition(api)
    nova = ctx["artist"]
    vela = second_act(api)

    countersigned = fx.countersigned_booking(
        api,
        ctx,
        nova,
        unit_cost_cents=RIDER_UNIT_COST_CENTS,
        slot_start_utc=NOVA_SLOT_UTC,
    )
    nova_booking_id = countersigned["booking"]["id"]
    vela_booking = fx.accepted_booking(
        api, ctx, vela, billing_position=2, slot_start_utc=VELA_SLOT_UTC
    )

    wave = fx.planned_wave(
        api, ctx["festival"]["id"], scheduled_reveal_utc="2026-09-10T12:00:00Z"
    )
    wave_id = wave["id"]
    fx.assign_to_wave(api, wave, nova_booking_id)

    # Business affairs locks a wave even though every other wave call is the buyer's.
    locked = validate_success(api.lock_wave(wave_id, BUSINESS_AFFAIRS))
    assert locked["status"] == "LOCKED"

    # The buyer files a competing-performance report, normally enforcement's work.
    report = validate_success(
        api.create_competing_performance(
            {
                "artist_id": vela["id"],
                "venue_city": "Boise",
                "venue_latitude": 43.615,
                "venue_longitude": -116.2023,
                "performance_date": "2026-11-20",
                "is_ticketed": True,
                "is_festival": False,
            },
            TALENT_BUYER,
        ),
        201,
    )
    assert report["reported_by_user_id"]
    assert report["conflict_assessment"] == "NO_CONFLICT", "Boise is beyond 150 miles"

    # One cancellation from each owning role, with identical consequences.
    cancelled_by_ba = validate_success(
        api.cancel_booking(
            vela_booking["id"],
            cancel_payload(cancelling_party="ARTIST", cancellation_reason="Illness."),
            BUSINESS_AFFAIRS,
        )
    )
    assert cancelled_by_ba["contract_status"] == "CANCELLED"
    assert cancelled_by_ba["cancelling_party"] == "ARTIST"

    cancelled_by_buyer = validate_success(
        api.cancel_booking(
            nova_booking_id,
            cancel_payload(cancelling_party="PROMOTER", cancellation_reason="Storm."),
            TALENT_BUYER,
        )
    )
    assert cancelled_by_buyer["contract_status"] == "CANCELLED"
    assert cancelled_by_buyer["cancelling_party"] == "PROMOTER"

    emptied = validate_success(api.get_announcement_wave(wave["id"], TALENT_BUYER))
    assert emptied["assignment_count"] == 0
    assert emptied["headliner_count"] == 0
    assert emptied["status"] == "PLANNED"

    swept = validate_success(api.sweep_expired_offers(BUSINESS_AFFAIRS))
    assert swept["expired_count"] == 0
