"""Composite state builders.

The harness restarts the server before every test, so each builder below
constructs its preconditions from an empty database through the public API
only. Builders return plain dicts of the rows they created so tests can read
ids, versions and derived fields without re-fetching.

Ownership-gated calls always thread the real Artist id through
`make_artist_rep_headers`, because an `ArtistRep`'s `X-User-ID` is the id of
the act it represents.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import validate_paginated, validate_success

from .api_client import ApiClient
from .constants import DEFAULT_CLOCK_UTC
from .factories import (
    advance_packet_payload,
    announcement_wave_payload,
    artist_payload,
    budget_tier_payload,
    competing_performance_payload,
    festival_payload,
    offer_payload,
    rider_item_payload,
    stage_payload,
)
from .test_users import (
    BUSINESS_AFFAIRS,
    FINANCE_CONTROLLER,
    PRODUCTION_MANAGER,
    TALENT_BUYER,
    make_artist_rep_headers,
)


# --------------------------------------------------------------------- clock
def set_clock(api: ApiClient, current_utc: str = DEFAULT_CLOCK_UTC) -> Dict[str, Any]:
    """Move the logical clock; the setting itself changes no business row."""
    return validate_success(api.set_clock(current_utc, TALENT_BUYER))


# ------------------------------------------------------------------ editions
def create_festival(api: ApiClient, **overrides) -> Dict[str, Any]:
    return validate_success(
        api.create_festival(festival_payload(**overrides), TALENT_BUYER), 201
    )


def create_tier(api: ApiClient, festival_id: str, **overrides) -> Dict[str, Any]:
    return validate_success(
        api.create_budget_tier(budget_tier_payload(festival_id, **overrides), TALENT_BUYER),
        201,
    )


def create_stage(api: ApiClient, festival_id: str, **overrides) -> Dict[str, Any]:
    return validate_success(
        api.create_stage(stage_payload(festival_id, **overrides), PRODUCTION_MANAGER), 201
    )


def create_artist(api: ApiClient, **overrides) -> Dict[str, Any]:
    return validate_success(api.create_artist(artist_payload(**overrides), TALENT_BUYER), 201)


def allocate(api: ApiClient, festival: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run the waterfall using the festival row's current version."""
    return validate_success(
        api.allocate_tiers(
            festival["id"], {"expected_festival_version": festival["version"]}, TALENT_BUYER
        )
    )


def single_tier_edition(
    api: ApiClient,
    clock: str = DEFAULT_CLOCK_UTC,
    tier_overrides: Optional[Dict[str, Any]] = None,
    stage_overrides: Optional[Dict[str, Any]] = None,
    festival_overrides: Optional[Dict[str, Any]] = None,
    artist_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Allocated single-HEADLINER-tier edition with one flagship stage and one act.

    Keys: festival, tier, stage, artist, artist_headers. The festival row is
    the post-allocation read, so `version` is current.
    """
    set_clock(api, clock)
    festival = create_festival(api, **(festival_overrides or {}))
    tier = create_tier(api, festival["id"], **(tier_overrides or {}))
    allocate(api, festival)
    stage = create_stage(api, festival["id"], **(stage_overrides or {}))
    artist = create_artist(api, **(artist_overrides or {}))
    festival = validate_success(api.get_festival(festival["id"], TALENT_BUYER))
    tier = validate_success(api.get_budget_tier(tier["id"], TALENT_BUYER))
    return {
        "festival": festival,
        "tier": tier,
        "stage": stage,
        "artist": artist,
        "artist_headers": make_artist_rep_headers(artist["id"]),
    }


def three_tier_edition(
    api: ApiClient, clock: str = DEFAULT_CLOCK_UTC
) -> Dict[str, Any]:
    """Allocated edition whose three tiers split 0.50 / 0.30 / 0.20 of 9500000."""
    set_clock(api, clock)
    festival = create_festival(api)
    headliner = create_tier(
        api,
        festival["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=0.50,
        max_slots=2,
        genre_focus="ELECTRONIC",
    )
    mid_card = create_tier(
        api,
        festival["id"],
        tier_code="MID_CARD",
        tier_rank=2,
        allocation_pct=0.30,
        max_slots=3,
        genre_focus=None,
    )
    emerging = create_tier(
        api,
        festival["id"],
        tier_code="EMERGING",
        tier_rank=3,
        allocation_pct=0.20,
        max_slots=4,
        genre_focus=None,
    )
    tiers = allocate(api, festival)
    stage = create_stage(api, festival["id"])
    artist = create_artist(api)
    return {
        "festival": validate_success(api.get_festival(festival["id"], TALENT_BUYER)),
        "tiers": tiers,
        "headliner": validate_success(api.get_budget_tier(headliner["id"], TALENT_BUYER)),
        "mid_card": validate_success(api.get_budget_tier(mid_card["id"], TALENT_BUYER)),
        "emerging": validate_success(api.get_budget_tier(emerging["id"], TALENT_BUYER)),
        "stage": stage,
        "artist": artist,
        "artist_headers": make_artist_rep_headers(artist["id"]),
    }


# -------------------------------------------------------------------- offers
def draft_offer(
    api: ApiClient, ctx: Dict[str, Any], artist: Optional[Dict[str, Any]] = None, **overrides
) -> Dict[str, Any]:
    """Draft an offer against an edition context built by the helpers above."""
    artist = artist or ctx["artist"]
    tier = ctx.get("tier") or ctx.get("headliner")
    payload = offer_payload(
        ctx["festival"]["id"], artist["id"], tier["id"], ctx["stage"]["id"], **overrides
    )
    return validate_success(api.create_offer(payload, TALENT_BUYER), 201)


def issued_offer(
    api: ApiClient, ctx: Dict[str, Any], artist: Optional[Dict[str, Any]] = None, **overrides
) -> Dict[str, Any]:
    offer = draft_offer(api, ctx, artist, **overrides)
    return validate_success(api.issue_offer(offer["id"], TALENT_BUYER))


def accepted_booking(
    api: ApiClient, ctx: Dict[str, Any], artist: Optional[Dict[str, Any]] = None, **overrides
) -> Dict[str, Any]:
    """Issue and accept an offer, returning the opened booking row."""
    artist = artist or ctx["artist"]
    offer = issued_offer(api, ctx, artist, **overrides)
    return validate_success(
        api.accept_offer(offer["id"], make_artist_rep_headers(artist["id"])), 201
    )


def clause_of_offer(api: ApiClient, offer_id: str) -> Dict[str, Any]:
    rows, _ = validate_paginated(
        api.list_radius_clauses(BUSINESS_AFFAIRS, {"offer_id": offer_id})
    )
    assert rows, f"no radius clause for offer {offer_id}"
    return rows[0]


def clause_of_booking(api: ApiClient, booking_id: str) -> Dict[str, Any]:
    rows, _ = validate_paginated(
        api.list_radius_clauses(BUSINESS_AFFAIRS, {"booking_id": booking_id})
    )
    assert rows, f"no radius clause for booking {booking_id}"
    return rows[0]


# -------------------------------------------------------------- installments
def installments_of(api: ApiClient, booking_id: str) -> Dict[str, Dict[str, Any]]:
    """Return {"DEPOSIT": row, "BALANCE": row} for a booking."""
    rows, _ = validate_paginated(
        api.list_payment_installments(booking_id, FINANCE_CONTROLLER)
    )
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        out[row["installment_type"]] = row
    return out


def pay_installment(
    api: ApiClient, installment: Dict[str, Any], amount_cents: Optional[int] = None
) -> Dict[str, Any]:
    """Release then record payment of one installment at its own amount."""
    validate_success(api.release_installment(installment["id"], FINANCE_CONTROLLER))
    return validate_success(
        api.mark_installment_paid(
            installment["id"],
            {"paid_amount_cents": amount_cents or installment["amount_cents"]},
            FINANCE_CONTROLLER,
        )
    )


# -------------------------------------------------------- rider and advance
def add_rider_line(
    api: ApiClient, booking_id: str, artist_id: str, **overrides
) -> Dict[str, Any]:
    return validate_success(
        api.create_rider_item(
            booking_id, rider_item_payload(**overrides), make_artist_rep_headers(artist_id)
        ),
        201,
    )


def decide_rider_line(
    api: ApiClient, rider_item_id: str, decision: str = "APPROVED", **extra
) -> Dict[str, Any]:
    payload = {"decision": decision}
    payload.update(extra)
    return validate_success(
        api.decide_rider_item(rider_item_id, payload, PRODUCTION_MANAGER)
    )


def rider_settled_booking(
    api: ApiClient,
    ctx: Dict[str, Any],
    artist: Optional[Dict[str, Any]] = None,
    unit_cost_cents: int = 100000,
    **offer_overrides,
) -> Dict[str, Any]:
    """Accepted booking with one approved rider line, so it reads RIDER_SETTLED."""
    artist = artist or ctx["artist"]
    booking = accepted_booking(api, ctx, artist, **offer_overrides)
    line = add_rider_line(
        api, booking["id"], artist["id"], unit_cost_cents=unit_cost_cents
    )
    decide_rider_line(api, line["id"], "APPROVED")
    return {
        "booking": validate_success(api.get_booking(booking["id"], TALENT_BUYER)),
        "rider_item": validate_success(api.get_rider_item(line["id"], TALENT_BUYER)),
    }


def approved_advance_packet(
    api: ApiClient, booking_id: str, artist_id: str, **overrides
) -> Dict[str, Any]:
    """Open, submit and approve a packet; the approver differs from the submitter."""
    packet = validate_success(
        api.create_advance_packet(
            advance_packet_payload(booking_id, **overrides),
            make_artist_rep_headers(artist_id),
        ),
        201,
    )
    validate_success(
        api.submit_advance_packet(packet["id"], make_artist_rep_headers(artist_id))
    )
    return validate_success(api.approve_advance_packet(packet["id"], PRODUCTION_MANAGER))


def countersigned_booking(
    api: ApiClient,
    ctx: Dict[str, Any],
    artist: Optional[Dict[str, Any]] = None,
    unit_cost_cents: int = 100000,
    **offer_overrides,
) -> Dict[str, Any]:
    """Booking taken all the way to COUNTERSIGNED.

    Keys: booking, rider_item, packet.
    """
    artist = artist or ctx["artist"]
    settled = rider_settled_booking(
        api, ctx, artist, unit_cost_cents=unit_cost_cents, **offer_overrides
    )
    booking_id = settled["booking"]["id"]
    packet = approved_advance_packet(api, booking_id, artist["id"])
    booking = validate_success(api.countersign_booking(booking_id, BUSINESS_AFFAIRS))
    return {"booking": booking, "rider_item": settled["rider_item"], "packet": packet}


# ----------------------------------------------------- radius enforcement
def report_performance(
    api: ApiClient, artist_id: str, **overrides
) -> Dict[str, Any]:
    return validate_success(
        api.create_competing_performance(
            competing_performance_payload(artist_id, **overrides), BUSINESS_AFFAIRS
        ),
        201,
    )


def adjudicate(
    api: ApiClient, performance_id: str, finding: str, note: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"finding": finding}
    if note:
        payload["finding_note"] = note
    return validate_success(
        api.adjudicate_performance(performance_id, payload, BUSINESS_AFFAIRS)
    )


def breached_clause_booking(
    api: ApiClient, ctx: Dict[str, Any], artist: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Accepted booking whose clause has been driven to BREACHED by a violation.

    Keys: booking, clause, performance, installments.
    """
    artist = artist or ctx["artist"]
    booking = accepted_booking(api, ctx, artist)
    clause = clause_of_booking(api, booking["id"])
    performance = report_performance(api, artist["id"])
    adjudicate(api, performance["id"], "VIOLATION", "Inside the radius window")
    return {
        "booking": validate_success(api.get_booking(booking["id"], TALENT_BUYER)),
        "clause": validate_success(api.get_radius_clause(clause["id"], BUSINESS_AFFAIRS)),
        "performance": validate_success(
            api.get_competing_performance(performance["id"], BUSINESS_AFFAIRS)
        ),
        "installments": installments_of(api, booking["id"]),
    }


# ---------------------------------------------------------------- waves
def planned_wave(api: ApiClient, festival_id: str, **overrides) -> Dict[str, Any]:
    return validate_success(
        api.create_announcement_wave(
            announcement_wave_payload(festival_id, **overrides), TALENT_BUYER
        ),
        201,
    )


def assign_to_wave(
    api: ApiClient, wave: Dict[str, Any], booking_id: str
) -> Dict[str, Any]:
    return validate_success(
        api.assign_booking_to_wave(
            wave["id"],
            {
                "booking_id": booking_id,
                "expected_announcement_wave_version": wave["version"],
            },
            TALENT_BUYER,
        )
    )


def locked_wave(
    api: ApiClient, festival_id: str, booking_id: str, **overrides
) -> Dict[str, Any]:
    """PRESALE wave holding one countersigned booking, locked."""
    wave = planned_wave(api, festival_id, **overrides)
    wave = assign_to_wave(api, wave, booking_id)
    return validate_success(api.lock_wave(wave["id"], BUSINESS_AFFAIRS))
