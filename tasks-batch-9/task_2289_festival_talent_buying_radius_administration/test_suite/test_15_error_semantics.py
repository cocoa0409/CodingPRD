"""Error semantics: which identifier answers, and in which order it wins.

Each test builds its own world from an empty database, so no failure below
depends on state left behind by another test.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import (
    BUSINESS_AFFAIRS,
    FINANCE_CONTROLLER,
    NO_AUTH_HEADERS,
    PRODUCTION_MANAGER,
    PRODUCTION_MANAGER_2,
    TALENT_BUYER,
    make_artist_rep_headers,
    make_headers,
)
from test_helpers import fixtures as fx
from test_helpers.factories import (
    advance_packet_payload,
    budget_tier_payload,
    rider_item_payload,
)

MISSING_ROLE_HEADERS = {"Content-Type": "application/json", "X-User-ID": "buyer-001"}
MISSING_ID_HEADERS = {"Content-Type": "application/json", "X-User-Role": "TalentBuyer"}
EMPTY_ID_HEADERS = {
    "Content-Type": "application/json",
    "X-User-ID": "",
    "X-User-Role": "TalentBuyer",
}
EMPTY_ROLE_HEADERS = {
    "Content-Type": "application/json",
    "X-User-ID": "buyer-001",
    "X-User-Role": "",
}
UNKNOWN_ROLE_HEADERS = make_headers("promo-001", "Promoter")
MISCASED_ROLE_HEADERS = make_headers("buyer-001", "talentbuyer")

BROKEN_FESTIVAL_PAYLOAD = {
    "name": 12345,
    "talent_budget_cents": "quite a lot",
    "event_start_date": "not-a-date",
}


def test_missing_or_unknown_identity_is_reported_before_shape_or_existence(api):
    """Authentication answers first: broken bodies and dead ids never surface.

    "If either header is missing or empty, the request fails with `ERR_UNAUTHENTICATED` (HTTP 401) before the body is even parsed, so a syntactically broken payload sent without headers still reports `ERR_UNAUTHENTICATED` rather than a shape complaint."
    "An unrecognised role string is treated as an authentication failure — `ERR_UNAUTHENTICATED` (HTTP 401) — not as an authorization failure."

    Design: Corner/errors/unauthenticated_requests_rejected_before_shape_and_existence
    """
    validate_error(
        api.create_festival(BROKEN_FESTIVAL_PAYLOAD, NO_AUTH_HEADERS),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.create_festival(BROKEN_FESTIVAL_PAYLOAD, MISSING_ROLE_HEADERS),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.create_festival(BROKEN_FESTIVAL_PAYLOAD, MISSING_ID_HEADERS),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.create_festival(BROKEN_FESTIVAL_PAYLOAD, EMPTY_ID_HEADERS),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.create_festival(BROKEN_FESTIVAL_PAYLOAD, EMPTY_ROLE_HEADERS),
        "ERR_UNAUTHENTICATED",
        401,
    )

    validate_error(
        api.get_festival(NON_EXISTENT_UUID, NO_AUTH_HEADERS),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.get_booking(NON_EXISTENT_UUID, MISSING_ROLE_HEADERS),
        "ERR_UNAUTHENTICATED",
        401,
    )

    validate_error(
        api.get_festival(NON_EXISTENT_UUID, UNKNOWN_ROLE_HEADERS),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.get_festival(NON_EXISTENT_UUID, MISCASED_ROLE_HEADERS),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.create_budget_tier(
            budget_tier_payload(NON_EXISTENT_UUID), UNKNOWN_ROLE_HEADERS
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.set_clock("2026-08-01T00:00:00Z", UNKNOWN_ROLE_HEADERS),
        "ERR_UNAUTHENTICATED",
        401,
    )

    # The same broken body, authenticated, is now allowed to be a shape complaint.
    validate_error(
        api.create_festival(BROKEN_FESTIVAL_PAYLOAD, TALENT_BUYER),
        "ERR_INVALID_REQUEST",
        422,
    )


def test_every_entity_answers_a_dead_identifier_with_its_own_not_found_id(api):
    """One dead identifier, twelve distinct answers, and parents answer first.

    "A syntactically valid identifier that matches no stored row is always a 404, never a 422."
    "For all of those, path parameters are resolved strictly left to right: the parent must be found before the child collection is filtered, and if the parent identifier does not resolve, the response is the parent's own not-found error."

    Design: Corner/errors/remaining_not_found_ids_are_entity_specific
    """
    canonical_reads = [
        (api.get_festival(NON_EXISTENT_UUID, TALENT_BUYER), "ERR_FESTIVAL_NOT_FOUND"),
        (
            api.get_budget_tier(NON_EXISTENT_UUID, TALENT_BUYER),
            "ERR_BUDGET_TIER_NOT_FOUND",
        ),
        (api.get_stage(NON_EXISTENT_UUID, PRODUCTION_MANAGER), "ERR_STAGE_NOT_FOUND"),
        (api.get_artist(NON_EXISTENT_UUID, TALENT_BUYER), "ERR_ARTIST_NOT_FOUND"),
        (api.get_offer(NON_EXISTENT_UUID, TALENT_BUYER), "ERR_OFFER_NOT_FOUND"),
        (api.get_booking(NON_EXISTENT_UUID, TALENT_BUYER), "ERR_BOOKING_NOT_FOUND"),
        (
            api.get_radius_clause(NON_EXISTENT_UUID, BUSINESS_AFFAIRS),
            "ERR_RADIUS_CLAUSE_NOT_FOUND",
        ),
        (
            api.get_competing_performance(NON_EXISTENT_UUID, BUSINESS_AFFAIRS),
            "ERR_COMPETING_PERFORMANCE_NOT_FOUND",
        ),
        (
            api.get_rider_item(NON_EXISTENT_UUID, PRODUCTION_MANAGER),
            "ERR_RIDER_ITEM_NOT_FOUND",
        ),
        (
            api.get_advance_packet(NON_EXISTENT_UUID, PRODUCTION_MANAGER),
            "ERR_ADVANCE_PACKET_NOT_FOUND",
        ),
        (
            api.get_payment_installment(NON_EXISTENT_UUID, FINANCE_CONTROLLER),
            "ERR_PAYMENT_INSTALLMENT_NOT_FOUND",
        ),
        (
            api.get_announcement_wave(NON_EXISTENT_UUID, TALENT_BUYER),
            "ERR_ANNOUNCEMENT_WAVE_NOT_FOUND",
        ),
    ]
    seen = set()
    for response, expected_error_id in canonical_reads:
        validate_error(response, expected_error_id, 404)
        seen.add(expected_error_id)
    assert len(seen) == 12, "each entity must own a distinct not-found identifier"

    nested_reads = [
        (
            api.list_festival_budget_tiers(NON_EXISTENT_UUID, TALENT_BUYER),
            "ERR_FESTIVAL_NOT_FOUND",
        ),
        (
            api.list_festival_stages(NON_EXISTENT_UUID, PRODUCTION_MANAGER),
            "ERR_FESTIVAL_NOT_FOUND",
        ),
        (
            api.get_budget_summary(NON_EXISTENT_UUID, FINANCE_CONTROLLER),
            "ERR_FESTIVAL_NOT_FOUND",
        ),
        (
            api.get_radius_risk(NON_EXISTENT_UUID, BUSINESS_AFFAIRS),
            "ERR_ARTIST_NOT_FOUND",
        ),
        (
            api.list_rider_items(NON_EXISTENT_UUID, PRODUCTION_MANAGER),
            "ERR_BOOKING_NOT_FOUND",
        ),
        (
            api.list_advance_packets(NON_EXISTENT_UUID, PRODUCTION_MANAGER),
            "ERR_BOOKING_NOT_FOUND",
        ),
        (
            api.list_payment_installments(NON_EXISTENT_UUID, FINANCE_CONTROLLER),
            "ERR_BOOKING_NOT_FOUND",
        ),
        (
            api.get_rider_estimate(NON_EXISTENT_UUID, PRODUCTION_MANAGER),
            "ERR_BOOKING_NOT_FOUND",
        ),
        (
            api.get_settlement(NON_EXISTENT_UUID, FINANCE_CONTROLLER),
            "ERR_BOOKING_NOT_FOUND",
        ),
    ]
    for response, expected_error_id in nested_reads:
        validate_error(response, expected_error_id, 404)


def test_the_three_forbidden_answers_are_told_apart(api):
    """Role, row ownership and duty separation each keep their own identifier.

    "That authorization decision is made against the static endpoint matrix before any path resource is loaded, which means a forbidden role addressing an identifier that does not exist receives 403, never 404."
    "`ArtistRep` is never authorized on festival, budget-tier or stage reads at all; those come back as `ERR_ROLE_NOT_PERMITTED`."
    "A mismatch is `ERR_ARTIST_SCOPE_VIOLATION` (HTTP 403), and because it is a row-level test it can only be evaluated after the row has been found: an `ArtistRep` reaching for another act's booking gets 403 even when the operation itself is open to the role."
    "Both returning and approving are subject to segregation of duties: the acting `X-User-ID` must differ from `submitted_by_user_id`, and a match is `ERR_SEGREGATION_OF_DUTIES` even for a caller who legitimately holds `ProductionManager`."

    Design: Corner/errors/three_distinct_403_ids_are_not_interchangeable
    """
    ctx = fx.single_tier_edition(api)
    own_headers = make_artist_rep_headers(ctx["artist"]["id"])
    other_act = fx.create_artist(
        api,
        legal_name="Vela Roan Touring Ltd",
        performing_name="Vela Roan",
        primary_genre="ROCK",
    )
    other_headers = make_artist_rep_headers(other_act["id"])

    # (1) The role is not on the endpoint's list at all.
    validate_error(
        api.get_festival(ctx["festival"]["id"], own_headers),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.get_budget_tier(ctx["tier"]["id"], own_headers),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.get_stage(ctx["stage"]["id"], own_headers), "ERR_ROLE_NOT_PERMITTED", 403
    )
    validate_error(
        api.create_festival({"name": "Nope"}, FINANCE_CONTROLLER),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    # Decided before the path resource is loaded, so a dead id still reads 403.
    validate_error(
        api.get_festival(NON_EXISTENT_UUID, own_headers), "ERR_ROLE_NOT_PERMITTED", 403
    )

    # (2) The role is authorized, but the row belongs to another act.
    offer = fx.issued_offer(api, ctx)
    validate_error(
        api.accept_offer(offer["id"], other_headers), "ERR_ARTIST_SCOPE_VIOLATION", 403
    )
    validate_error(
        api.get_offer(offer["id"], other_headers), "ERR_ARTIST_SCOPE_VIOLATION", 403
    )
    booking = validate_success(api.accept_offer(offer["id"], own_headers), 201)
    validate_error(
        api.get_booking(booking["id"], other_headers), "ERR_ARTIST_SCOPE_VIOLATION", 403
    )
    validate_error(
        api.create_rider_item(booking["id"], rider_item_payload(), other_headers),
        "ERR_ARTIST_SCOPE_VIOLATION",
        403,
    )

    # (3) The role and the row are both fine; only the acting identity is wrong.
    packet = validate_success(
        api.create_advance_packet(
            advance_packet_payload(booking["id"]), PRODUCTION_MANAGER
        ),
        201,
    )
    submitted = validate_success(
        api.submit_advance_packet(packet["id"], PRODUCTION_MANAGER)
    )
    assert submitted["submitted_by_user_id"] == "pm-001"
    validate_error(
        api.return_advance_packet(
            packet["id"], {"return_reason": "Channel plan unclear."}, PRODUCTION_MANAGER
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )
    validate_error(
        api.approve_advance_packet(packet["id"], PRODUCTION_MANAGER),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )
    approved = validate_success(
        api.approve_advance_packet(packet["id"], PRODUCTION_MANAGER_2)
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "pm-002"


def test_percentages_that_do_not_close_and_waves_out_of_phase_are_refused(api):
    """A split that misses one whole and a wave ahead of the edition both fail.

    "If the set is empty, or if the sum of `allocation_pct` across the set differs from 1.00 by more than one billionth, the run is refused with `ERR_ALLOCATION_PCT_INVALID`."
    "A wave planned for `TIER2_ONSALE` cannot lock while the edition is still in `PRESALE`, and that mismatch is `ERR_WAVE_PHASE_MISMATCH`."

    Design: Corner/errors/allocation_percentages_and_wave_phase_mismatches_rejected
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    festival = fx.create_festival(api)
    assert festival["announcement_phase"] == "PRESALE"
    assert festival["allocatable_budget_cents"] == 9500000

    validate_error(
        api.allocate_tiers(
            festival["id"],
            {"expected_festival_version": festival["version"]},
            TALENT_BUYER,
        ),
        "ERR_ALLOCATION_PCT_INVALID",
        422,
    )

    fx.create_tier(
        api,
        festival["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=0.5,
        max_slots=2,
        genre_focus="MIXED",
    )
    fx.create_tier(
        api,
        festival["id"],
        tier_code="MID_CARD",
        tier_rank=2,
        allocation_pct=0.4,
        max_slots=3,
        genre_focus="MIXED",
    )
    before_failure = validate_success(api.get_festival(festival["id"], TALENT_BUYER))
    validate_error(
        api.allocate_tiers(
            festival["id"],
            {"expected_festival_version": before_failure["version"]},
            TALENT_BUYER,
        ),
        "ERR_ALLOCATION_PCT_INVALID",
        422,
    )
    unallocated = validate_success(api.get_festival(festival["id"], TALENT_BUYER))
    assert unallocated["tiers_allocated"] is False
    assert unallocated["version"] == before_failure["version"]

    fx.create_tier(
        api,
        festival["id"],
        tier_code="EMERGING",
        tier_rank=3,
        allocation_pct=0.1,
        max_slots=4,
        genre_focus="MIXED",
    )
    tiers = fx.allocate(api, unallocated)
    assert [tier["allocation_cents"] for tier in tiers] == [4750000, 3800000, 950000]
    allocated = validate_success(api.get_festival(festival["id"], TALENT_BUYER))
    assert allocated["tiers_allocated"] is True

    stage = fx.create_stage(api, festival["id"])
    artist = fx.create_artist(api)
    ctx = {
        "festival": allocated,
        "tier": tiers[0],
        "stage": stage,
        "artist": artist,
    }
    executed = fx.countersigned_booking(api, ctx)["booking"]
    assert executed["contract_status"] == "COUNTERSIGNED"

    ahead_of_phase = fx.planned_wave(
        api,
        festival["id"],
        wave_number=2,
        phase="TIER2_ONSALE",
        scheduled_reveal_utc="2026-10-01T12:00:00Z",
    )
    assert ahead_of_phase["assignment_count"] == 0
    validate_error(
        api.lock_wave(ahead_of_phase["id"], BUSINESS_AFFAIRS),
        "ERR_WAVE_PHASE_MISMATCH",
        409,
    )

    in_phase = fx.planned_wave(
        api,
        festival["id"],
        wave_number=1,
        phase="PRESALE",
        scheduled_reveal_utc="2026-09-10T12:00:00Z",
    )
    validate_error(
        api.lock_wave(in_phase["id"], BUSINESS_AFFAIRS), "ERR_EMPTY_WAVE", 409
    )

    fx.assign_to_wave(api, in_phase, executed["id"])
    locked = validate_success(api.lock_wave(in_phase["id"], BUSINESS_AFFAIRS))
    assert locked["status"] == "LOCKED"

    still_planned = validate_success(
        api.get_announcement_wave(ahead_of_phase["id"], TALENT_BUYER)
    )
    assert still_planned["status"] == "PLANNED"
