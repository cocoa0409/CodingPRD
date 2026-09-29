"""Entity-level compliance tests: creation stamps, declared defaults, computed
fields, read-back of stored derivations, list windows and the shape/reference
guards that protect them.

Every test builds its own world from an empty database through the public API
and sets the logical clock explicitly whenever a temporal rule matters.
"""

from datetime import datetime, timedelta

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiClient,
    BUSINESS_AFFAIRS,
    FINANCE_CONTROLLER,
    PRODUCTION_MANAGER,
    TALENT_BUYER,
    assert_common_fields,
    assert_envelope_meta,
    round_half_up,
)
from test_helpers import fixtures as fx
from test_helpers.constants import (
    ALLOCATABLE_BUDGET_CENTS,
    DEFAULT_CHANGEOVER_BUFFER_MINUTES,
    DEFAULT_CONTINGENCY_RESERVE_PCT,
    DEFAULT_RADIUS_MILES,
    TALENT_BUDGET_CENTS,
)
from test_helpers.factories import artist_payload, festival_payload, offer_payload


# --------------------------------------------------------------- local helpers
def _instant(text: str) -> datetime:
    """Parse an ISO 8601 UTC instant however many fractional digits it carries."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _draft_three_offers_on_one_stage_day(api: ApiClient, ctx: dict) -> dict:
    """Three DRAFT offers whose slot order disagrees with their insertion order."""
    late = fx.draft_offer(
        api,
        ctx,
        guarantee_cents=500000,
        billing_position=1,
        set_length_minutes=60,
        slot_start_utc="2026-12-04T21:00:00Z",
    )
    early = fx.draft_offer(
        api,
        ctx,
        guarantee_cents=500000,
        billing_position=3,
        set_length_minutes=60,
        slot_start_utc="2026-12-04T12:00:00Z",
    )
    mid = fx.draft_offer(
        api,
        ctx,
        guarantee_cents=500000,
        billing_position=2,
        set_length_minutes=60,
        slot_start_utc="2026-12-04T15:00:00Z",
    )
    return {"late": late, "early": early, "mid": mid}


def _second_edition(api: ApiClient) -> dict:
    """A separate allocated edition with its own flagship stage."""
    bayside = fx.create_festival(
        api,
        name="Bayside Sessions",
        edition_year=2026,
        event_start_date="2026-11-06",
        event_end_date="2026-11-07",
        talent_budget_cents=4000000,
        contingency_reserve_pct=0.0,
    )
    tier = fx.create_tier(
        api,
        bayside["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=1.00,
        max_slots=4,
        genre_focus="MIXED",
    )
    fx.allocate(api, bayside)
    stage = fx.create_stage(
        api,
        bayside["id"],
        name="Bayside Main",
        capacity=9000,
        daily_curfew_minute=1320,
        daily_program_minutes_cap=480,
        changeover_buffer_minutes=30,
        is_flagship=True,
    )
    return {"festival": bayside, "tier": tier, "stage": stage}


# ------------------------------------------------------------------ creation
def test_registering_an_edition_stamps_the_allocatable_budget_and_opening_posture(api):
    """A registered edition withholds the reserve once, off the top, and opens every
    ledger and posture field at its declared zero.

    "At registration the edition's `allocatable_budget_cents` is set to `talent_budget_cents` less the reserve, where the reserve is the `talent_budget_cents` multiplied by `contingency_reserve_pct` and rounded half up to whole cents, taken off the top exactly once."
    "The new edition also starts with `committed_budget_cents` at 0, `tiers_allocated` false, `announcement_phase` at `PRESALE`, `lineup_posture` at `OPEN`, and `headliner_anchor_count` at 0."
    Design: Corner/entities/festival_creation_stamps_derived_budget_and_posture
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")

    response = api.create_festival(
        festival_payload(
            name="Harbor Lights Festival",
            edition_year=2026,
            market_latitude=47.6062,
            market_longitude=-122.3321,
            event_start_date="2026-12-04",
            event_end_date="2026-12-06",
            talent_budget_cents=10000000,
            contingency_reserve_pct=0.05,
        ),
        TALENT_BUYER,
    )

    festival = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object"
    assert_envelope_meta(body)

    reserve = round_half_up(TALENT_BUDGET_CENTS * DEFAULT_CONTINGENCY_RESERVE_PCT)
    assert TALENT_BUDGET_CENTS - reserve == 9500000
    assert festival["allocatable_budget_cents"] == 9500000
    assert festival["committed_budget_cents"] == 0
    assert festival["tiers_allocated"] is False
    assert festival["announcement_phase"] == "PRESALE"
    assert festival["lineup_posture"] == "OPEN"
    assert festival["headliner_anchor_count"] == 0
    assert_common_fields(festival, expected_version=1)
    assert isinstance(festival["id"], str) and festival["id"]


# ------------------------------------------------------------------ defaults
def test_omitted_reserve_and_stage_options_fall_back_to_declared_defaults(api):
    """Omitting the reserve fraction still withholds five percent, and a stage added
    without a changeover buffer or a flagship flag takes 20 minutes and false.

    "`contingency_reserve_pct` is an optional fraction between 0.00 and 0.25 which defaults to 0.05 — five percent — and it is withheld from the tiers before any tier is funded."
    "`changeover_buffer_minutes` is the gap that must separate two set intervals on the stage; it defaults to 20 minutes and may be anywhere from 0 to 90."
    "An `is_flagship` flag marks the main stage and defaults to false."
    "A new stage starts with `booked_minutes` at 0."
    Design: Corner/entities/festival_and_stage_defaults_applied_when_optional_fields_omitted
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    created = fx.create_festival(api, contingency_reserve_pct=None)

    festival = validate_success(api.get_festival(created["id"], TALENT_BUYER))
    assert festival["contingency_reserve_pct"] == DEFAULT_CONTINGENCY_RESERVE_PCT
    assert festival["contingency_reserve_pct"] == 0.05
    assert festival["allocatable_budget_cents"] == 9500000

    stage_response = api.create_stage(
        {
            "festival_id": festival["id"],
            "name": "Grove",
            "capacity": 6000,
            "daily_curfew_minute": 1200,
            "daily_program_minutes_cap": 360,
        },
        PRODUCTION_MANAGER,
    )
    stage = validate_success(stage_response, 201)
    assert stage["changeover_buffer_minutes"] == DEFAULT_CHANGEOVER_BUFFER_MINUTES
    assert stage["changeover_buffer_minutes"] == 20
    assert stage["is_flagship"] is False
    assert stage["booked_minutes"] == 0


# -------------------------------------------------------------- system fields
def test_adding_an_act_to_the_roster_seeds_its_risk_counters_at_zero(api):
    """A new roster act carries no stored risk even though it already has a draw
    score, and an omitted default radius falls back to 75 miles.

    "A new act starts with `reported_conflict_count`, `radius_breach_count`, `strict_risk_score` and `adjudicated_risk_score` all at 0."
    "An optional `default_radius_miles` between 0 and 500, defaulting to 75, records the mileage the act's agency normally demands and is used as the radius for a new offer's clause when the offer does not name one explicitly."
    Design: Corner/entities/artist_creation_initialises_counters_and_system_fields
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")

    artist = validate_success(
        api.create_artist(
            artist_payload(
                legal_name="Nova Kade LLC",
                performing_name="Nova Kade",
                primary_genre="ELECTRONIC",
                agency="Meridian Talent",
                draw_score=72,
                default_radius_miles=None,
            ),
            TALENT_BUYER,
        ),
        201,
    )

    assert artist["draw_score"] == 72
    assert artist["reported_conflict_count"] == 0
    assert artist["radius_breach_count"] == 0
    assert artist["strict_risk_score"] == 0
    assert artist["adjudicated_risk_score"] == 0
    assert artist["default_radius_miles"] == DEFAULT_RADIUS_MILES
    assert artist["default_radius_miles"] == 75
    assert_common_fields(artist, expected_version=1)


# ------------------------------------------------------------ computed fields
def test_drafting_an_offer_derives_the_slot_end_and_opens_a_provisional_clause(api):
    """Drafting derives the slot end from the set length, opens exactly one
    provisional clause with no booking attached, and commits nothing to the tier.

    "Drafting stamps `slot_end_utc` as `slot_start_utc` advanced by `set_length_minutes`, sets `status` to `DRAFT` and `round_number` to 0, and creates exactly one radius clause carrying the offer's identifier and the act's `artist_id`, with `enforcement_status` `PROVISIONAL`, `waiver_status` `NONE`, no `booking_id` yet, `waiver_fee_cents` 0 and `breach_count` 0."
    "A draft commits no budget and reserves no stage time."
    Design: Corner/entities/offer_creation_computes_slot_end_and_creates_provisional_clause
    """
    ctx = fx.three_tier_edition(api, "2026-08-01T00:00:00Z")

    offer = fx.draft_offer(
        api,
        ctx,
        guarantee_cents=1800000,
        billing_position=1,
        set_length_minutes=90,
        slot_start_utc="2026-12-04T21:00:00Z",
        radius_miles=150,
        exclusivity_scope=None,
    )

    assert _instant(offer["slot_end_utc"]) == _instant("2026-12-04T21:00:00Z") + timedelta(
        minutes=90
    )
    assert _instant(offer["slot_end_utc"]) == _instant("2026-12-04T22:30:00Z")
    assert offer["status"] == "DRAFT"
    assert offer["round_number"] == 0
    assert offer["issued_by_user_id"] is None

    clauses, meta = validate_paginated(
        api.list_radius_clauses(BUSINESS_AFFAIRS, {"offer_id": offer["id"]})
    )
    assert meta["total_count"] == 1
    assert len(clauses) == 1
    clause = clauses[0]
    assert clause["offer_id"] == offer["id"]
    assert clause["artist_id"] == ctx["artist"]["id"]
    assert clause["enforcement_status"] == "PROVISIONAL"
    assert clause["waiver_status"] == "NONE"
    assert clause["booking_id"] is None
    assert clause["waiver_fee_cents"] == 0
    assert clause["breach_count"] == 0
    assert clause["radius_miles"] == 150
    assert clause["exclusivity_scope"] == "FULL"

    tier = validate_success(api.get_budget_tier(ctx["headliner"]["id"], TALENT_BUYER))
    assert tier["committed_cents"] == 0
    assert tier["slots_committed"] == 0

    stage = validate_success(api.get_stage(ctx["stage"]["id"], TALENT_BUYER))
    assert stage["booked_minutes"] == 0


# ----------------------------------------------------------------- retrieval
def test_reading_back_the_tiers_after_the_waterfall_shows_the_floored_split(api):
    """The stored waterfall output reads back per tier and as a rank-ordered
    collection whose figures still add up to the allocatable budget.

    "Then each tier's `allocation_cents` is set to the edition's `allocatable_budget_cents` multiplied by that tier's `allocation_pct` and **floored** to whole cents — floored per tier, never rounded half up."
    "It reads `CLOSED` once its `slots_committed` has reached its `max_slots`, or once its `committed_cents` has reached or passed its `allocation_cents`; otherwise it reads `OPEN`."
    "The documented orderings are: budget tiers by `tier_rank` ascending; stages by `is_flagship` descending, then `name` ascending; offers by `slot_start_utc` ascending; radius clauses by `radius_miles` descending, then `window_start_date` ascending — deliberately the same ranking the radius conflict detector uses to pick a winning clause; competing performances by `performance_date` ascending; bookings by `slot_start_utc` ascending; rider items by `category` ascending; advance packets by `created_at` ascending alone; payment installments by `due_date` ascending, which is exactly the order the chronological recovery replay uses; and announcement waves by `wave_number` ascending."
    Design: Corner/entities/budget_tier_retrieval_after_waterfall
    """
    ctx = fx.three_tier_edition(api, "2026-08-01T00:00:00Z")

    headliner = validate_success(
        api.get_budget_tier(ctx["headliner"]["id"], FINANCE_CONTROLLER)
    )
    assert headliner["allocation_cents"] == 4750000
    assert headliner["committed_cents"] == 0
    assert headliner["slots_committed"] == 0
    assert headliner["status"] == "OPEN"

    rows, meta = validate_paginated(
        api.list_festival_budget_tiers(
            ctx["festival"]["id"], FINANCE_CONTROLLER, {"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(rows) == 3
    assert rows[0]["tier_rank"] == 1
    assert rows[0]["allocation_cents"] == 4750000
    assert rows[1]["allocation_cents"] == 2850000
    assert rows[2]["allocation_cents"] == 1900000
    assert [row["tier_rank"] for row in rows] == [1, 2, 3]
    assert sum(row["allocation_cents"] for row in rows) == ALLOCATABLE_BUDGET_CENTS
    assert sum(row["allocation_cents"] for row in rows) == 9500000


# ------------------------------------------------------------------- listing
def test_listing_offers_pages_the_window_and_orders_by_slot_start(api):
    """The offer list is ordered by slot start rather than by insertion order, and
    its meta reports the pre-window count with has_more across two pages.

    "The documented orderings are: budget tiers by `tier_rank` ascending; stages by `is_flagship` descending, then `name` ascending; offers by `slot_start_utc` ascending; radius clauses by `radius_miles` descending, then `window_start_date` ascending — deliberately the same ranking the radius conflict detector uses to pick a winning clause; competing performances by `performance_date` ascending; bookings by `slot_start_utc` ascending; rider items by `category` ascending; advance packets by `created_at` ascending alone; payment installments by `due_date` ascending, which is exactly the order the chronological recovery replay uses; and announcement waves by `wave_number` ascending."
    "Each of those responses reports `limit`, `offset`, `total_count` and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before the window is applied and `has_more` is true when rows remain beyond it."
    Design: Corner/entities/offers_list_pagination_envelope_and_slot_ordering
    """
    ctx = fx.three_tier_edition(api, "2026-08-01T00:00:00Z")
    _draft_three_offers_on_one_stage_day(api, ctx)

    first_response = api.list_offers(
        TALENT_BUYER, {"festival_id": ctx["festival"]["id"], "limit": 2, "offset": 0}
    )
    first_page, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert len(first_page) == 2
    assert _instant(first_page[0]["slot_start_utc"]) == _instant("2026-12-04T12:00:00Z")
    assert _instant(first_page[1]["slot_start_utc"]) == _instant("2026-12-04T15:00:00Z")

    second_page, second_meta = validate_paginated(
        api.list_offers(
            TALENT_BUYER, {"festival_id": ctx["festival"]["id"], "limit": 2, "offset": 2}
        )
    )
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert len(second_page) == 1
    assert _instant(second_page[0]["slot_start_utc"]) == _instant("2026-12-04T21:00:00Z")

    for row in first_page + second_page:
        assert row["status"] == "DRAFT"


# ----------------------------------------------------------------- not found
def test_unknown_identifiers_report_the_not_found_error_of_their_own_entity(api):
    """One syntactically valid identifier that matches no row yields a different
    404 on each path, and an unresolvable body reference is a 404 too.

    "A syntactically valid identifier that matches no stored row is always a 404, never a 422."
    "Every identifier-bearing body field resolves to a stored row, resolved in the order the fields are declared for that operation — again the entity-specific not-found error from the list above, so an unresolvable `festival_id` is `ERR_FESTIVAL_NOT_FOUND`, an unresolvable `budget_tier_id` is `ERR_BUDGET_TIER_NOT_FOUND`, an unresolvable `stage_id` is `ERR_STAGE_NOT_FOUND`, an unresolvable `artist_id` is `ERR_ARTIST_NOT_FOUND`, an unresolvable `booking_id` or `replaces_booking_id` is `ERR_BOOKING_NOT_FOUND` and an unresolvable `competing_performance_id` is `ERR_COMPETING_PERFORMANCE_NOT_FOUND`."
    Design: Corner/entities/unknown_ids_return_entity_specific_not_found
    """
    ctx = fx.three_tier_edition(api, "2026-08-01T00:00:00Z")

    validate_error(
        api.get_festival(NON_EXISTENT_UUID, TALENT_BUYER), "ERR_FESTIVAL_NOT_FOUND", 404
    )
    validate_error(
        api.get_offer(NON_EXISTENT_UUID, TALENT_BUYER), "ERR_OFFER_NOT_FOUND", 404
    )
    validate_error(
        api.get_booking(NON_EXISTENT_UUID, TALENT_BUYER), "ERR_BOOKING_NOT_FOUND", 404
    )
    validate_error(
        api.create_budget_tier(
            {
                "festival_id": NON_EXISTENT_UUID,
                "tier_code": "DIRECT_SUPPORT",
                "tier_rank": 4,
                "allocation_pct": 0.1,
                "max_slots": 2,
            },
            TALENT_BUYER,
        ),
        "ERR_FESTIVAL_NOT_FOUND",
        404,
    )

    rows, meta = validate_paginated(
        api.list_festival_budget_tiers(ctx["festival"]["id"], TALENT_BUYER)
    )
    assert meta["total_count"] == 3
    assert len(rows) == 3


# ----------------------------------------------------------- required fields
def test_drafting_an_offer_without_its_required_terms_is_rejected(api):
    """An offer draft missing its set length, and one missing its slot start, both
    fail pure shape validation and leave no offer and no clause behind.

    "A `TalentBuyer` drafts one against a `festival_id`, an `artist_id`, a `budget_tier_id` and a `stage_id`, with `guarantee_cents` of at least 0, a `billing_position`, a `set_length_minutes` between 20 and 180, a `slot_start_utc`, and an `offer_expires_utc` after which the offer may be swept."
    "Request shape: required body fields present, JSON types correct, enum values members of their declared set, integers non-negative where declared so, dates and instants well-formed ISO 8601 — `ERR_INVALID_REQUEST`."
    Design: Corner/entities/offer_creation_missing_required_fields_rejected
    """
    ctx = fx.three_tier_edition(api, "2026-08-01T00:00:00Z")
    base = dict(
        festival_id=ctx["festival"]["id"],
        artist_id=ctx["artist"]["id"],
        budget_tier_id=ctx["headliner"]["id"],
        stage_id=ctx["stage"]["id"],
    )

    without_set_length = offer_payload(
        base["festival_id"],
        base["artist_id"],
        base["budget_tier_id"],
        base["stage_id"],
        guarantee_cents=1800000,
        billing_position=1,
        slot_start_utc="2026-12-04T21:00:00Z",
        set_length_minutes=None,
    )
    validate_error(
        api.create_offer(without_set_length, TALENT_BUYER), "ERR_INVALID_REQUEST", 422
    )

    without_slot_start = offer_payload(
        base["festival_id"],
        base["artist_id"],
        base["budget_tier_id"],
        base["stage_id"],
        guarantee_cents=1800000,
        billing_position=1,
        set_length_minutes=90,
        slot_start_utc=None,
    )
    validate_error(
        api.create_offer(without_slot_start, TALENT_BUYER), "ERR_INVALID_REQUEST", 422
    )

    _, offer_meta = validate_paginated(
        api.list_offers(TALENT_BUYER, {"festival_id": ctx["festival"]["id"]})
    )
    assert offer_meta["total_count"] == 0

    _, clause_meta = validate_paginated(
        api.list_radius_clauses(BUSINESS_AFFAIRS, {"artist_id": ctx["artist"]["id"]})
    )
    assert clause_meta["total_count"] == 0


# ---------------------------------------------------------- type constraints
def test_adding_an_act_with_an_unknown_genre_or_an_out_of_range_draw_is_rejected(api):
    """A genre outside the declared set and a draw score above 100 are both refused
    as shape failures rather than coerced or clamped.

    "A roster act is created by a `TalentBuyer` with a `legal_name` and a `performing_name`, both 1 to 120 characters, a `primary_genre` drawn from `ELECTRONIC`, `HIP_HOP`, `ROCK`, `POP`, `LATIN`, `JAZZ_SOUL` and `COUNTRY`, the `agency` of record, and a `draw_score` between 0 and 100 representing the promoter's own estimate of the act's ticket-driving power."
    "Request shape: required body fields present, JSON types correct, enum values members of their declared set, integers non-negative where declared so, dates and instants well-formed ISO 8601 — `ERR_INVALID_REQUEST`."
    Design: Corner/entities/artist_creation_invalid_enum_and_out_of_range_rejected
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")

    validate_error(
        api.create_artist(
            artist_payload(
                legal_name="Ska Revival Ltd",
                performing_name="Ska Revival",
                primary_genre="SKA",
                agency="Meridian Talent",
                draw_score=40,
                default_radius_miles=None,
            ),
            TALENT_BUYER,
        ),
        "ERR_INVALID_REQUEST",
        422,
    )

    validate_error(
        api.create_artist(
            artist_payload(
                legal_name="Tidal Kid LLC",
                performing_name="Tidal Kid",
                primary_genre="POP",
                agency="Meridian Talent",
                draw_score=140,
                default_radius_miles=None,
            ),
            TALENT_BUYER,
        ),
        "ERR_INVALID_REQUEST",
        422,
    )


# ------------------------------------------------------- parent relationships
def test_drafting_an_offer_against_another_editions_stage_is_a_festival_mismatch(api):
    """Every reference in the body exists, so the coherence failure between the
    named edition and the stage's edition is a mismatch rather than a 404.

    "The tier and the stage must both belong to the named edition; when they do not, the draft is refused with `ERR_FESTIVAL_MISMATCH` even though each row exists."
    "Body references that must belong to the same festival do: an offer's budget tier, stage and festival must agree, and a wave assignment's booking must belong to the wave's festival — `ERR_FESTIVAL_MISMATCH`."
    Design: Corner/entities/offer_creation_with_cross_festival_fks_rejected
    """
    ctx = fx.three_tier_edition(api, "2026-08-01T00:00:00Z")
    other = _second_edition(api)

    payload = offer_payload(
        ctx["festival"]["id"],
        ctx["artist"]["id"],
        ctx["headliner"]["id"],
        other["stage"]["id"],
        guarantee_cents=1800000,
        billing_position=1,
        set_length_minutes=90,
        slot_start_utc="2026-12-04T21:00:00Z",
        radius_miles=150,
    )
    validate_error(api.create_offer(payload, TALENT_BUYER), "ERR_FESTIVAL_MISMATCH", 409)

    foreign_stage = validate_success(api.get_stage(other["stage"]["id"], TALENT_BUYER))
    assert foreign_stage["festival_id"] == other["festival"]["id"]

    _, offer_meta = validate_paginated(
        api.list_offers(TALENT_BUYER, {"festival_id": ctx["festival"]["id"]})
    )
    assert offer_meta["total_count"] == 0

    _, clause_meta = validate_paginated(
        api.list_radius_clauses(BUSINESS_AFFAIRS, {"artist_id": ctx["artist"]["id"]})
    )
    assert clause_meta["total_count"] == 0
