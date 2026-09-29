"""Validation-rule compliance tests for the festival talent-buying API.

Every test below drives the public HTTP surface only. The harness restarts the
server before each test, so each test builds the whole world it needs and the
logical clock is set explicitly wherever a temporal rule is in play.
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
    TALENT_BUYER,
    make_artist_rep_headers,
)
from test_helpers import fixtures as fx
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.factories import (
    advance_packet_payload,
    announcement_wave_payload,
    artist_payload,
    budget_tier_payload,
    cancel_payload,
    offer_payload,
    stage_payload,
)


# --------------------------------------------------------------------- helpers
def _edition(
    api,
    clock=DEFAULT_CLOCK_UTC,
    festival_overrides=None,
    tier_overrides=None,
    stage_overrides=None,
    artist_overrides=None,
):
    """Allocated edition with one roomy tier, one flagship stage and one act.

    Keys: festival, tier, stage, artist, artist_headers — the same shape the
    shared composite builders consume, so offers can be drafted against it.
    """
    fx.set_clock(api, clock)
    festival = fx.create_festival(api, **(festival_overrides or {}))
    tier_kwargs = {
        "tier_code": "HEADLINER",
        "tier_rank": 1,
        "allocation_pct": 1.00,
        "max_slots": 10,
        "genre_focus": "MIXED",
    }
    tier_kwargs.update(tier_overrides or {})
    tier = fx.create_tier(api, festival["id"], **tier_kwargs)
    festival = validate_success(api.get_festival(festival["id"], TALENT_BUYER))
    fx.allocate(api, festival)
    stage = fx.create_stage(api, festival["id"], **(stage_overrides or {}))
    artist = fx.create_artist(api, **(artist_overrides or {}))
    return {
        "festival": validate_success(api.get_festival(festival["id"], TALENT_BUYER)),
        "tier": validate_success(api.get_budget_tier(tier["id"], TALENT_BUYER)),
        "stage": stage,
        "artist": artist,
        "artist_headers": make_artist_rep_headers(artist["id"]),
    }


def _artist(api, performing_name, primary_genre, draw_score=72):
    """Another roster act, distinct in name and genre from the canonical one."""
    return fx.create_artist(
        api,
        legal_name=f"{performing_name} Touring Ltd",
        performing_name=performing_name,
        primary_genre=primary_genre,
        agency="Meridian Talent",
        draw_score=draw_score,
        default_radius_miles=100,
    )


def _side_stage(api, festival_id):
    """A second, non-flagship stage with its own curfew, cap and buffer."""
    return fx.create_stage(
        api,
        festival_id,
        name="Grove",
        capacity=6000,
        daily_curfew_minute=1200,
        daily_program_minutes_cap=360,
        changeover_buffer_minutes=20,
        is_flagship=False,
    )


def _draft(api, ctx, artist=None, stage=None, tier=None, **overrides):
    """Draft one offer, optionally on another act, stage or tier."""
    artist = artist or ctx["artist"]
    stage = stage or ctx["stage"]
    tier = tier or ctx["tier"]
    payload = offer_payload(
        ctx["festival"]["id"], artist["id"], tier["id"], stage["id"], **overrides
    )
    return validate_success(api.create_offer(payload, TALENT_BUYER), 201)


def _issue(api, offer_id):
    return validate_success(api.issue_offer(offer_id, TALENT_BUYER))


def _accept(api, offer_id, artist):
    return validate_success(
        api.accept_offer(offer_id, make_artist_rep_headers(artist["id"])), 201
    )


# ----------------------------------------------------------------------- tests
def test_duplicate_keys_are_refused_on_tiers_stages_acts_and_waves(api):
    """Four uniqueness keys each refuse a second row, the tier key on both halves.

    "Both `tier_code` and `tier_rank` must be unique within a festival, and a collision on either surfaces the same `ERR_DUPLICATE_TIER_CODE`."
    "A `ProductionManager` adds one to an edition with a `festival_id`, a `name` of 1 to 80 characters that must be unique within the edition — a collision is `ERR_DUPLICATE_STAGE_NAME`, because the stage name is the human key production works from on the day sheet — and a standing-field `capacity` of at least 500."
    "`performing_name` is globally unique across the roster — two rows for the same act would silently defeat radius enforcement, so a duplicate is `ERR_DUPLICATE_ARTIST_NAME`."
    "A `TalentBuyer` plans a wave with a `festival_id`, a `wave_number` between 1 and 20 that must be unique within the edition — a collision is `ERR_DUPLICATE_WAVE_NUMBER`, since wave numbers drive announcement ordering — a `phase` drawn from `PRESALE`, `TIER1_ONSALE`, `TIER2_ONSALE` and `GA_ONSALE` tying the wave to a ticket-sales phase, and a `scheduled_reveal_utc` giving the earliest instant the wave may go out."

    Design: Corner/validations/uniqueness_collisions_rejected_across_four_entities
    """
    fx.set_clock(api)
    festival = fx.create_festival(api)
    fx.create_tier(
        api,
        festival["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=1.00,
        max_slots=5,
        genre_focus="MIXED",
    )

    # The tier key is composite: either half collides into the same error.
    validate_error(
        api.create_budget_tier(
            budget_tier_payload(
                festival["id"], tier_code="HEADLINER", tier_rank=2, allocation_pct=0.10
            ),
            TALENT_BUYER,
        ),
        "ERR_DUPLICATE_TIER_CODE",
        409,
    )
    validate_error(
        api.create_budget_tier(
            budget_tier_payload(
                festival["id"], tier_code="MID_CARD", tier_rank=1, allocation_pct=0.10
            ),
            TALENT_BUYER,
        ),
        "ERR_DUPLICATE_TIER_CODE",
        409,
    )

    fx.create_stage(api, festival["id"])
    validate_error(
        api.create_stage(
            stage_payload(
                festival["id"],
                capacity=5000,
                daily_curfew_minute=1200,
                daily_program_minutes_cap=300,
                is_flagship=False,
            ),
            PRODUCTION_MANAGER,
        ),
        "ERR_DUPLICATE_STAGE_NAME",
        409,
    )

    fx.create_artist(api)
    validate_error(
        api.create_artist(
            artist_payload(
                legal_name="Nova Kade Touring GmbH",
                primary_genre="ROCK",
                agency="Other Agency",
                draw_score=10,
            ),
            TALENT_BUYER,
        ),
        "ERR_DUPLICATE_ARTIST_NAME",
        409,
    )

    fx.planned_wave(
        api, festival["id"], wave_number=1, scheduled_reveal_utc="2026-09-10T12:00:00Z"
    )
    validate_error(
        api.create_announcement_wave(
            announcement_wave_payload(
                festival["id"],
                wave_number=1,
                phase="TIER1_ONSALE",
                scheduled_reveal_utc="2026-10-01T12:00:00Z",
            ),
            TALENT_BUYER,
        ),
        "ERR_DUPLICATE_WAVE_NUMBER",
        409,
    )

    _, meta = validate_paginated(
        api.list_festival_budget_tiers(festival["id"], TALENT_BUYER)
    )
    assert meta["total_count"] == 1, "the refused tier must not have been stored"


def test_a_limit_of_zero_or_one_hundred_and_one_is_refused_while_one_and_hundred_pass(api):
    """The limit bounds are closed on both ends and the accepted values echo back.

    "A `limit` of 0 and a `limit` of 101 are both rejected with `ERR_INVALID_PAGINATION` (HTTP 400); a `limit` of 1 and a `limit` of 100 are both accepted, as is any non-negative `offset`."

    Design: Corner/validations/pagination_limit_bounds_rejected_at_zero_and_101
    """
    ctx = _edition(api)
    for position, start in ((1, "2026-12-04T12:00:00Z"), (2, "2026-12-04T15:00:00Z"), (3, "2026-12-04T18:00:00Z")):
        _draft(
            api,
            ctx,
            guarantee_cents=500000,
            billing_position=position,
            set_length_minutes=60,
            slot_start_utc=start,
        )

    festival_id = ctx["festival"]["id"]
    for bad_limit in (0, 101):
        validate_error(
            api.list_offers(TALENT_BUYER, {"festival_id": festival_id, "limit": bad_limit}),
            "ERR_INVALID_PAGINATION",
            400,
        )
        validate_error(
            api.list_festival_budget_tiers(festival_id, TALENT_BUYER, {"limit": bad_limit}),
            "ERR_INVALID_PAGINATION",
            400,
        )

    rows, meta = validate_paginated(
        api.list_offers(TALENT_BUYER, {"festival_id": festival_id, "limit": 1})
    )
    assert meta["limit"] == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert len(rows) == 1

    rows, meta = validate_paginated(
        api.list_offers(TALENT_BUYER, {"festival_id": festival_id, "limit": 100, "offset": 0})
    )
    assert meta["limit"] == 100
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert len(rows) == 3

    rows, meta = validate_paginated(
        api.list_offers(TALENT_BUYER, {"festival_id": festival_id, "limit": 1, "offset": 7})
    )
    assert meta["offset"] == 7
    assert meta["total_count"] == 3
    assert rows == []


def test_countersigning_without_an_approved_advance_packet_is_refused(api):
    """A merely submitted packet does not unlock the contract; only an approved one does.

    "It requires the booking's `contract_status` to be `RIDER_SETTLED`, requires the booking's radius clause to be in `ACTIVE` or `WAIVED` — a `BREACHED` clause is refused with `ERR_RADIUS_BREACH_ACTIVE` — and requires the booking to have at least one advance packet in `APPROVED`, without which the answer is `ERR_ADVANCE_NOT_APPROVED`."
    "The order is: take the booking's `rider_estimate_cents`, which is the contracted-scope rider total; take the `waiver_fee_cents` of the booking's clause, or 0 when the booking has no clause row; form the pre-share gross as `guarantee_cents` plus that rider figure plus that waiver fee, using the **unadjusted** rider on purpose; select the promoter share from that pre-share gross — 0.60 when the gross has reached 5000000 cents (fifty thousand dollars), 0.75 when it has reached 2000000 cents (twenty thousand dollars) but is below the higher bracket, and 0.90 when it is below 2000000 cents; compute the reimbursed rider as the rider figure multiplied by that share, rounded half up once; and finally set `settlement_total_cents` to `guarantee_cents` plus the reimbursed rider plus the waiver fee, less `deposit_paid_cents`."

    Design: Corner/validations/countersign_without_an_approved_advance_rejected
    """
    ctx = _edition(api)
    settled = fx.rider_settled_booking(api, ctx, unit_cost_cents=250000)
    booking_id = settled["booking"]["id"]
    assert settled["booking"]["contract_status"] == "RIDER_SETTLED"

    packet = validate_success(
        api.create_advance_packet(
            advance_packet_payload(booking_id, stage_plot_ref="SP-AURORA-1"),
            ctx["artist_headers"],
        ),
        201,
    )
    assert packet["status"] == "DRAFT"

    validate_error(
        api.countersign_booking(booking_id, BUSINESS_AFFAIRS),
        "ERR_ADVANCE_NOT_APPROVED",
        409,
    )

    validate_success(api.submit_advance_packet(packet["id"], ctx["artist_headers"]))
    validate_error(
        api.countersign_booking(booking_id, BUSINESS_AFFAIRS),
        "ERR_ADVANCE_NOT_APPROVED",
        409,
    )

    validate_success(api.approve_advance_packet(packet["id"], PRODUCTION_MANAGER))
    booking = validate_success(api.countersign_booking(booking_id, BUSINESS_AFFAIRS))
    assert booking["contract_status"] == "COUNTERSIGNED"
    assert booking["settlement_total_cents"] == 1987500


def test_a_replacement_offer_pointing_at_a_live_booking_is_refused_at_draft(api):
    """A replacement may only stand in for a booking that has already been cancelled.

    "A replacement offer is drafted with `replaces_booking_id` naming the booking it stands in for; that booking must belong to the same edition and must already be `CANCELLED`, or the draft is refused with `ERR_REPLACEMENT_TARGET_NOT_CANCELLED`."

    Design: Corner/validations/replacement_offer_pointing_at_a_live_booking_rejected
    """
    ctx = _edition(api)
    booking = fx.accepted_booking(api, ctx)
    assert booking["contract_status"] == "PENDING_RIDER"
    replacement_act = _artist(api, "Vela Roan", "ROCK")

    body = offer_payload(
        ctx["festival"]["id"],
        replacement_act["id"],
        ctx["tier"]["id"],
        ctx["stage"]["id"],
        billing_position=2,
        slot_start_utc="2026-12-06T21:00:00Z",
        replaces_booking_id=booking["id"],
    )
    validate_error(
        api.create_offer(body, TALENT_BUYER),
        "ERR_REPLACEMENT_TARGET_NOT_CANCELLED",
        409,
    )

    cancelled = validate_success(
        api.cancel_booking(
            booking["id"],
            cancel_payload(cancelling_party="ARTIST", cancellation_reason="Routing collapsed."),
            BUSINESS_AFFAIRS,
        )
    )
    assert cancelled["contract_status"] == "CANCELLED"

    replacement = validate_success(api.create_offer(body, TALENT_BUYER), 201)
    assert replacement["replaces_booking_id"] == booking["id"]
    assert replacement["status"] == "DRAFT"

    rows, meta = validate_paginated(
        api.list_offers(TALENT_BUYER, {"replaces_booking_id": booking["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == replacement["id"]


def test_accepting_at_the_exact_expiry_instant_is_refused(api):
    """Expiry is read off the clock, and equality with the expiry instant is expired.

    "Expiry is clock-derived rather than stored: an offer still reads `ISSUED` until a sweep runs, which is why countering, revising and accepting each independently check the clock against `offer_expires_utc` and refuse with `ERR_OFFER_EXPIRED` when the clock has reached it."
    "A clock exactly equal to `offer_expires_utc` is expired, since those operations require the clock to be strictly earlier."
    "The deposit percentage is 0.50 when there are at least 120 days to go — exactly 120 days still earns 0.50 — 0.40 when there are at least 60 but fewer than 120, and 0.25 when there are fewer than 60."

    Design: Corner/validations/offer_accept_at_the_exact_expiry_instant_rejected
    """
    ctx = _edition(api)
    offer = fx.issued_offer(api, ctx)
    assert offer["offer_expires_utc"].startswith("2026-09-15T00:00:00")

    fx.set_clock(api, "2026-09-15T00:00:00Z")
    validate_error(
        api.accept_offer(offer["id"], ctx["artist_headers"]),
        "ERR_OFFER_EXPIRED",
        409,
    )
    still_live = validate_success(api.get_offer(offer["id"], TALENT_BUYER))
    assert still_live["status"] == "ISSUED"

    fx.set_clock(api, "2026-09-14T23:59:59Z")
    booking = _accept(api, offer["id"], ctx["artist"])
    assert booking["contract_status"] == "PENDING_RIDER"
    assert booking["settlement_status"] == "UNFUNDED"

    rows, _ = validate_paginated(
        api.list_payment_installments(booking["id"], FINANCE_CONTROLLER)
    )
    assert rows[0]["installment_type"] == "DEPOSIT"
    assert rows[0]["amount_cents"] == 720000


def test_a_set_ending_exactly_at_the_curfew_minute_passes_and_one_minute_later_fails(api):
    """Curfew equality is allowed; a single minute past it is refused at issuance.

    "The **curfew** rule is evaluated on issuance and on revision: the set's end, measured as minutes from midnight UTC of the date on which the set *starts*, must be no later than the stage's `daily_curfew_minute`."
    "Equality with the curfew minute passes."
    "Exceeding it is `ERR_CURFEW_EXCEEDED`."

    Design: Corner/validations/curfew_equality_passes_and_one_minute_over_rejected
    """
    ctx = _edition(api)
    assert ctx["stage"]["daily_curfew_minute"] == 1380
    other_act = _artist(api, "Vela Roan", "ROCK")

    on_curfew = _draft(api, ctx, slot_start_utc="2026-12-04T21:30:00Z")
    one_minute_over = _draft(
        api, ctx, artist=other_act, slot_start_utc="2026-12-05T21:31:00Z"
    )

    issued = _issue(api, on_curfew["id"])
    assert issued["status"] == "ISSUED"
    assert issued["slot_end_utc"].startswith("2026-12-04T23:00:00")

    validate_error(
        api.issue_offer(one_minute_over["id"], TALENT_BUYER),
        "ERR_CURFEW_EXCEEDED",
        409,
    )
    unchanged = validate_success(api.get_offer(one_minute_over["id"], TALENT_BUYER))
    assert unchanged["status"] == "DRAFT"


def test_an_act_cannot_be_issued_a_second_slot_on_a_date_it_already_plays(api):
    """One act, one UTC date: a second slot on another stage is still double booking.

    "It also re-checks that the set ends within the stage curfew, that no buffered interval collision exists, that the stage day load stays within the cap, that the `billing_position` is unheld on the stage-day, that a top-billed offer sits on a flagship stage, that the act holds no other non-cancelled booking at this edition starting on the same UTC date, that the projected genre share stays within the cap, and that `guarantee_cents` plus `production_fee_cents` stays within the freshly computed ceiling."
    "The act must still hold no other live offer or non-cancelled booking at this edition starting on the same UTC date, or the answer is `ERR_ARTIST_DOUBLE_BOOKED`."

    Design: Corner/validations/artist_double_booked_across_two_stages_on_one_date_rejected
    """
    ctx = _edition(api)
    side = _side_stage(api, ctx["festival"]["id"])

    first = fx.accepted_booking(api, ctx, slot_start_utc="2026-12-04T21:00:00Z")
    assert first["slot_start_utc"].startswith("2026-12-04T21:00:00")

    same_date = _draft(
        api,
        ctx,
        stage=side,
        guarantee_cents=500000,
        billing_position=2,
        set_length_minutes=60,
        slot_start_utc="2026-12-04T15:00:00Z",
    )
    next_date = _draft(
        api,
        ctx,
        stage=side,
        guarantee_cents=500000,
        billing_position=2,
        set_length_minutes=60,
        slot_start_utc="2026-12-05T15:00:00Z",
    )

    validate_error(
        api.issue_offer(same_date["id"], TALENT_BUYER),
        "ERR_ARTIST_DOUBLE_BOOKED",
        409,
    )
    assert validate_success(api.get_offer(same_date["id"], TALENT_BUYER))["status"] == "DRAFT"

    assert _issue(api, next_date["id"])["status"] == "ISSUED"


def test_slot_window_and_radius_window_bounds_are_enforced_when_the_offer_is_drafted(api):
    """Both ends of the slot and both endpoints of the radius window are checked at draft.

    "The dates of both `slot_start_utc` and the derived slot end must lie inside the inclusive window from `event_start_date` to `event_end_date` — a set starting exactly on `event_end_date` is inside, and anything outside is `ERR_SLOT_OUTSIDE_EVENT_WINDOW`."
    "The window must be coherent and near enough to the event: `window_end_date` may not precede `window_start_date`, and neither endpoint may lie more than 365 days from the edition's `event_start_date`, or the offer draft is refused with `ERR_RADIUS_WINDOW_INVALID`."

    Design: Corner/validations/slot_and_radius_window_bounds_rejected_at_creation
    """
    ctx = _edition(api)
    festival = ctx["festival"]
    assert festival["event_start_date"] == "2026-12-04"
    assert festival["event_end_date"] == "2026-12-06"

    def body(**overrides):
        return offer_payload(
            festival["id"],
            ctx["artist"]["id"],
            ctx["tier"]["id"],
            ctx["stage"]["id"],
            **overrides,
        )

    validate_error(
        api.create_offer(body(slot_start_utc="2026-12-07T21:00:00Z"), TALENT_BUYER),
        "ERR_SLOT_OUTSIDE_EVENT_WINDOW",
        422,
    )
    validate_error(
        api.create_offer(body(slot_start_utc="2026-12-06T23:30:00Z"), TALENT_BUYER),
        "ERR_SLOT_OUTSIDE_EVENT_WINDOW",
        422,
    )
    validate_error(
        api.create_offer(
            body(
                slot_start_utc="2026-12-06T21:00:00Z",
                window_start_date="2027-01-04",
                window_end_date="2026-10-05",
            ),
            TALENT_BUYER,
        ),
        "ERR_RADIUS_WINDOW_INVALID",
        422,
    )
    validate_error(
        api.create_offer(
            body(slot_start_utc="2026-12-06T21:00:00Z", window_end_date="2027-12-05"),
            TALENT_BUYER,
        ),
        "ERR_RADIUS_WINDOW_INVALID",
        422,
    )

    accepted = validate_success(
        api.create_offer(
            body(slot_start_utc="2026-12-06T21:00:00Z", window_end_date="2027-12-04"),
            TALENT_BUYER,
        ),
        201,
    )
    assert accepted["slot_start_utc"].startswith("2026-12-06T21:00:00")

    rows, meta = validate_paginated(
        api.list_radius_clauses(BUSINESS_AFFAIRS, {"offer_id": accepted["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["window_end_date"] == "2027-12-04"


def test_a_wave_revealing_at_the_event_start_instant_is_refused(api):
    """Midnight UTC of the first show date is already too late for an announcement.

    "That instant must be strictly before midnight UTC of the edition's `event_start_date`: an announcement that lands after the gates open is not an announcement, and the refusal is `ERR_REVEAL_AFTER_EVENT_START`, checked both when the wave is planned and again when it is locked."
    "A new wave opens with `status` `PLANNED`, `assignment_count` 0, `headliner_count` 0 and `published_at` null."

    Design: Corner/validations/wave_reveal_at_the_event_start_instant_rejected
    """
    ctx = _edition(api)
    festival_id = ctx["festival"]["id"]

    validate_error(
        api.create_announcement_wave(
            announcement_wave_payload(
                festival_id, wave_number=1, scheduled_reveal_utc="2026-12-04T00:00:00Z"
            ),
            TALENT_BUYER,
        ),
        "ERR_REVEAL_AFTER_EVENT_START",
        422,
    )

    wave = validate_success(
        api.create_announcement_wave(
            announcement_wave_payload(
                festival_id, wave_number=1, scheduled_reveal_utc="2026-12-03T23:59:59Z"
            ),
            TALENT_BUYER,
        ),
        201,
    )
    assert wave["status"] == "PLANNED"
    assert wave["assignment_count"] == 0
    assert wave["headliner_count"] == 0
    assert wave["published_at"] is None
    assert wave["version"] == 1


def test_a_billing_ordinal_already_held_on_that_stage_day_is_refused(api):
    """The ordinal key is stage plus date, not the time range, and a free ordinal issues.

    "And a `billing_position`, an integer slot ordinal between 1 and 200 where 1 is the headliner, 2 the sub-headliner and so on, must be unheld on the target stage for the target UTC date: no other offer with `status` `DRAFT`, `ISSUED`, `COUNTERED` or `ACCEPTED`, and no booking whose `contract_status` is not `CANCELLED`, may already hold that ordinal on that stage-day."
    "This uniqueness is *not* enforced when the offer is first drafted; it is enforced at issuance, at revision and again at acceptance, and a clash is `ERR_BILLING_POSITION_TAKEN`."

    Design: Corner/validations/billing_position_taken_on_the_same_stage_day_rejected
    """
    ctx = _edition(api)
    second_act = _artist(api, "Vela Roan", "ROCK")
    third_act = _artist(api, "Cassia Vale", "POP")

    holder = _draft(api, ctx, slot_start_utc="2026-12-04T21:00:00Z")
    _issue(api, holder["id"])

    clashing = _draft(
        api,
        ctx,
        artist=second_act,
        billing_position=1,
        set_length_minutes=60,
        slot_start_utc="2026-12-04T15:00:00Z",
    )
    free_ordinal = _draft(
        api,
        ctx,
        artist=third_act,
        billing_position=2,
        set_length_minutes=60,
        slot_start_utc="2026-12-04T12:00:00Z",
    )

    validate_error(
        api.issue_offer(clashing["id"], TALENT_BUYER),
        "ERR_BILLING_POSITION_TAKEN",
        409,
    )
    assert validate_success(api.get_offer(clashing["id"], TALENT_BUYER))["status"] == "DRAFT"

    issued = _issue(api, free_ordinal["id"])
    assert issued["status"] == "ISSUED"
    assert issued["billing_position"] == 2
    assert issued["guarantee_ceiling_cents"] == 1800000
    assert issued["genre_balance_factor"] == 1.00


def test_the_top_billed_ordinal_requires_a_flagship_stage_and_is_silent_elsewhere(api):
    """Ordinal 1 must sit on a flagship stage; ordinal 2 on the same side stage issues.

    "An offer whose `billing_position` is 1 — the top-billing ordinal — must target a stage whose `is_flagship` is true, whatever tier the guarantee is drawn from; a top-billed offer aimed at a side stage is refused with `ERR_HEADLINER_STAGE_REQUIRED` on issuance and on revision, and the rule is silent for every other ordinal."
    "`headliner_anchor_count` counts the edition's anchors: the number of its bookings drawn from the tier whose `tier_code` is `HEADLINER` whose `contract_status` is not `CANCELLED`."

    Design: Corner/validations/headliner_ordinal_on_a_non_flagship_stage_rejected
    """
    ctx = _edition(api)
    side = _side_stage(api, ctx["festival"]["id"])
    assert side["is_flagship"] is False
    other_act = _artist(api, "Vela Roan", "ROCK")

    top_billed = _draft(
        api,
        ctx,
        stage=side,
        guarantee_cents=500000,
        billing_position=1,
        set_length_minutes=60,
        slot_start_utc="2026-12-04T15:00:00Z",
    )
    sub_billed = _draft(
        api,
        ctx,
        artist=other_act,
        stage=side,
        guarantee_cents=500000,
        billing_position=2,
        set_length_minutes=60,
        slot_start_utc="2026-12-04T12:00:00Z",
    )

    validate_error(
        api.issue_offer(top_billed["id"], TALENT_BUYER),
        "ERR_HEADLINER_STAGE_REQUIRED",
        409,
    )
    assert _issue(api, sub_billed["id"])["status"] == "ISSUED"

    festival = validate_success(api.get_festival(ctx["festival"]["id"], TALENT_BUYER))
    assert festival["headliner_anchor_count"] == 0


def test_a_booking_already_carrying_a_wave_cannot_be_assigned_to_a_second_wave(api):
    """A booking belongs to at most one wave, and the refused call increments nothing.

    "The booking must belong to the same edition as the wave, or the answer is `ERR_FESTIVAL_MISMATCH`, and it must not already carry an `announcement_wave_id`, or the answer is `ERR_BOOKING_ALREADY_ASSIGNED` — a booking belongs to at most one wave, and re-assigning it requires the first wave to have fallen back to `PLANNED`."
    "On success the booking's `announcement_wave_id` is set and its `reveal_order` becomes the wave's `assignment_count` after the increment, so the first booking assigned reveals first."

    Design: Corner/validations/second_wave_assignment_for_one_booking_rejected
    """
    ctx = _edition(api)
    booking = fx.countersigned_booking(api, ctx)["booking"]
    assert booking["contract_status"] == "COUNTERSIGNED"

    festival_id = ctx["festival"]["id"]
    first_wave = fx.planned_wave(
        api, festival_id, wave_number=1, scheduled_reveal_utc="2026-09-10T12:00:00Z"
    )
    second_wave = fx.planned_wave(
        api, festival_id, wave_number=2, scheduled_reveal_utc="2026-09-20T12:00:00Z"
    )
    assert second_wave["version"] == 1

    fx.assign_to_wave(api, first_wave, booking["id"])

    validate_error(
        api.assign_booking_to_wave(
            second_wave["id"],
            {
                "booking_id": booking["id"],
                "expected_announcement_wave_version": second_wave["version"],
            },
            TALENT_BUYER,
        ),
        "ERR_BOOKING_ALREADY_ASSIGNED",
        409,
    )

    untouched = validate_success(api.get_announcement_wave(second_wave["id"], TALENT_BUYER))
    assert untouched["assignment_count"] == 0
    assert untouched["headliner_count"] == 0
    assert untouched["version"] == 1

    stored = validate_success(api.get_booking(booking["id"], TALENT_BUYER))
    assert stored["announcement_wave_id"] == first_wave["id"]
    assert stored["reveal_order"] == 1

    holder = validate_success(api.get_announcement_wave(first_wave["id"], TALENT_BUYER))
    assert holder["assignment_count"] == 1
    assert holder["headliner_count"] == 1
    assert holder["version"] == 2


def test_the_stage_day_channel_hard_maximum_refuses_a_submission_the_advisory_only_reports(api):
    """96 channels is advice stamped on the packet; 112 channels is the gate that refuses.

    "Submission also faces an aggregate production constraint across every packet sharing a stage-day: sum the `input_channel_count` of every advance packet whose `status` is `SUBMITTED` or `APPROVED` and whose booking sits on this same stage and the same UTC slot date, add this packet's own `input_channel_count`, and the total may not exceed the console's hard maximum of 112 channels."
    "Exceeding it is `ERR_STAGE_CHANNEL_CAP_EXCEEDED` — each packet fits the console on its own while the day's total does not."
    "On success `status` moves to `SUBMITTED`, `submission_count` increases by one, `submitted_by_user_id` is overwritten with the submitter's `X-User-ID` on every submission, and `channel_overage` is re-stamped as the amount by which that same stage-day channel total including this packet exceeds the advisory comfort level of 96 channels, or 0 when it does not exceed it."

    Design: Corner/validations/stage_day_channel_hard_max_rejected_while_advisory_overage_is_reported
    """
    ctx = _edition(api)
    second_act = _artist(api, "Vela Roan", "ROCK")
    third_act = _artist(api, "Cassia Vale", "POP", draw_score=40)

    first_booking = fx.accepted_booking(api, ctx, slot_start_utc="2026-12-04T21:00:00Z")
    second_booking = fx.accepted_booking(
        api,
        ctx,
        artist=second_act,
        billing_position=2,
        slot_start_utc="2026-12-04T18:00:00Z",
    )
    third_booking = fx.accepted_booking(
        api,
        ctx,
        artist=third_act,
        guarantee_cents=500000,
        billing_position=3,
        set_length_minutes=60,
        slot_start_utc="2026-12-04T15:00:00Z",
    )

    packet_one = validate_success(
        api.create_advance_packet(
            advance_packet_payload(
                first_booking["id"], stage_plot_ref="SP-AURORA-1", input_channel_count=60
            ),
            ctx["artist_headers"],
        ),
        201,
    )
    packet_two = validate_success(
        api.create_advance_packet(
            advance_packet_payload(
                second_booking["id"], stage_plot_ref="SP-AURORA-2", input_channel_count=40
            ),
            make_artist_rep_headers(second_act["id"]),
        ),
        201,
    )
    packet_three = validate_success(
        api.create_advance_packet(
            advance_packet_payload(
                third_booking["id"], stage_plot_ref="SP-AURORA-3", input_channel_count=20
            ),
            make_artist_rep_headers(third_act["id"]),
        ),
        201,
    )

    submitted_one = validate_success(
        api.submit_advance_packet(packet_one["id"], ctx["artist_headers"])
    )
    assert submitted_one["status"] == "SUBMITTED"
    assert submitted_one["submission_count"] == 1
    assert submitted_one["channel_overage"] == 0

    submitted_two = validate_success(
        api.submit_advance_packet(packet_two["id"], make_artist_rep_headers(second_act["id"]))
    )
    assert submitted_two["status"] == "SUBMITTED"
    assert submitted_two["channel_overage"] == 4

    validate_error(
        api.submit_advance_packet(
            packet_three["id"], make_artist_rep_headers(third_act["id"])
        ),
        "ERR_STAGE_CHANNEL_CAP_EXCEEDED",
        409,
    )

    refused = validate_success(api.get_advance_packet(packet_three["id"], PRODUCTION_MANAGER))
    assert refused["status"] == "DRAFT"
    assert refused["submission_count"] == 0
    assert refused["channel_overage"] == 0

    still_stamped = validate_success(
        api.get_advance_packet(packet_two["id"], PRODUCTION_MANAGER)
    )
    assert still_stamped["channel_overage"] == 4


def test_a_guarantee_equal_to_the_ceiling_passes_and_one_cent_over_is_refused(api):
    """The ceiling is tested against guarantee plus production fee, and equality passes.

    "Step four converts draw into money: the draw component is the greater of a floor of 500000 cents — five thousand dollars, the least the system will ever consider an act worth — and the act's `draw_score` multiplied by 25000 cents, meaning two hundred and fifty dollars of headroom for every point of draw."
    "An offer whose `guarantee_cents` plus `production_fee_cents` exceeds that ceiling is refused with `ERR_GUARANTEE_CEILING_EXCEEDED`; equality with the ceiling passes."

    Design: Corner/validations/guarantee_ceiling_equality_passes_and_one_cent_over_rejected
    """
    ctx = _edition(api)
    assert ctx["artist"]["draw_score"] == 72
    second_act = _artist(api, "Vela Roan", "ROCK")
    third_act = _artist(api, "Cassia Vale", "POP")

    at_ceiling = _draft(
        api, ctx, guarantee_cents=1800000, slot_start_utc="2026-12-04T21:00:00Z"
    )
    one_cent_over = _draft(
        api,
        ctx,
        artist=second_act,
        guarantee_cents=1800001,
        slot_start_utc="2026-12-05T21:00:00Z",
    )
    split_over = _draft(
        api,
        ctx,
        artist=third_act,
        guarantee_cents=1799000,
        production_fee_cents=1001,
        slot_start_utc="2026-12-06T21:00:00Z",
    )

    issued = _issue(api, at_ceiling["id"])
    assert issued["status"] == "ISSUED"
    assert issued["guarantee_ceiling_cents"] == 1800000

    validate_error(
        api.issue_offer(one_cent_over["id"], TALENT_BUYER),
        "ERR_GUARANTEE_CEILING_EXCEEDED",
        422,
    )
    validate_error(
        api.issue_offer(split_over["id"], TALENT_BUYER),
        "ERR_GUARANTEE_CEILING_EXCEEDED",
        422,
    )

    for offer_id in (one_cent_over["id"], split_over["id"]):
        assert validate_success(api.get_offer(offer_id, TALENT_BUYER))["status"] == "DRAFT"

    festival = validate_success(api.get_festival(ctx["festival"]["id"], TALENT_BUYER))
    assert festival["committed_budget_cents"] == 0


def test_a_second_acceptance_overrunning_the_tier_allocation_is_refused(api):
    """Two offers issued against an untouched tier cannot both be accepted into it.

    "Three checks that already passed at issuance are re-run against the world as it now stands, because a sibling acceptance may have overtaken them: the tier's `committed_cents` plus this offer's `guarantee_cents` plus its `production_fee_cents` must still fit inside the tier's `allocation_cents`, or the acceptance is refused with `ERR_TIER_ALLOCATION_EXCEEDED`; no buffered interval collision may have appeared on the stage; and the `billing_position` must still be unheld on that stage-day."
    "It reports `allocatable_budget_cents`, `committed_budget_cents`, `tier_committed_sum_cents`, `booking_committed_sum_cents`, `committed_ratio`, `lineup_posture`, `open_tier_count`, `closed_tier_count` and `headliner_anchor_count`, and asserts that the three committed figures agree."

    Design: Corner/validations/second_accept_exceeding_the_tier_allocation_rejected
    """
    fx.set_clock(api)
    festival = fx.create_festival(api, talent_budget_cents=4000000, contingency_reserve_pct=0.00)
    top_tier = fx.create_tier(
        api,
        festival["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=0.50,
        max_slots=5,
        genre_focus="MIXED",
    )
    fx.create_tier(
        api,
        festival["id"],
        tier_code="MID_CARD",
        tier_rank=2,
        allocation_pct=0.50,
        max_slots=5,
        genre_focus="MIXED",
    )
    festival = validate_success(api.get_festival(festival["id"], TALENT_BUYER))
    fx.allocate(api, festival)
    stage = fx.create_stage(api, festival["id"])
    first_act = _artist(api, "Nova Kade", "ELECTRONIC", draw_score=48)
    second_act = _artist(api, "Vela Roan", "ROCK", draw_score=48)

    ctx = {
        "festival": validate_success(api.get_festival(festival["id"], TALENT_BUYER)),
        "tier": validate_success(api.get_budget_tier(top_tier["id"], TALENT_BUYER)),
        "stage": stage,
        "artist": first_act,
    }
    assert ctx["tier"]["allocation_cents"] == 2000000

    first_offer = _draft(
        api, ctx, guarantee_cents=1200000, slot_start_utc="2026-12-04T21:00:00Z"
    )
    _issue(api, first_offer["id"])
    second_offer = _draft(
        api,
        ctx,
        artist=second_act,
        guarantee_cents=1200000,
        slot_start_utc="2026-12-05T21:00:00Z",
    )
    _issue(api, second_offer["id"])

    booking = _accept(api, first_offer["id"], first_act)
    assert booking["contract_status"] == "PENDING_RIDER"

    validate_error(
        api.accept_offer(second_offer["id"], make_artist_rep_headers(second_act["id"])),
        "ERR_TIER_ALLOCATION_EXCEEDED",
        409,
    )

    tier = validate_success(api.get_budget_tier(top_tier["id"], FINANCE_CONTROLLER))
    assert tier["committed_cents"] == 1200000
    assert tier["slots_committed"] == 1
    assert tier["status"] == "OPEN"

    summary = validate_success(api.get_budget_summary(festival["id"], FINANCE_CONTROLLER))
    assert summary["committed_budget_cents"] == 1200000
    assert summary["tier_committed_sum_cents"] == 1200000
    assert summary["booking_committed_sum_cents"] == 1200000

    assert validate_success(api.get_offer(second_offer["id"], TALENT_BUYER))["status"] == "ISSUED"


def test_a_granted_waiver_priced_below_the_agents_own_ask_is_refused(api):
    """The agent's ask is a floor on the granted fee, and equality with it is granted.

    "A `GRANTED` decision additionally requires the `waiver_fee_cents` it prices to be at least the `waiver_fee_offer_cents` the agent offered — a granted waiver may not be cheaper than the agent's own ask, and undercutting it is `ERR_WAIVER_FEE_BELOW_OFFER`."
    "And the booking's `settlement_status` leaves `WITHHELD` — but the state it returns to is **re-derived from the installments, never remembered**: it becomes `SETTLED` when both installments are `PAID`, otherwise `BALANCE_DUE` when the balance installment is `RELEASED`, otherwise `DEPOSIT_PAID` when the deposit installment is `PAID`, and otherwise `UNFUNDED`."

    Design: Corner/validations/granted_waiver_priced_below_the_artist_ask_rejected
    """
    ctx = _edition(api)
    booking = fx.accepted_booking(api, ctx)
    clause = fx.clause_of_booking(api, booking["id"])
    performance = fx.report_performance(
        api, ctx["artist"]["id"], performance_date="2026-11-15", announced_capacity=4000
    )
    assert performance["conflict_assessment"] == "CONFLICT"
    fx.adjudicate(api, performance["id"], "VIOLATION", "Inside the radius.")

    validate_success(
        api.request_waiver(
            clause["id"],
            {"competing_performance_id": performance["id"], "waiver_fee_offer_cents": 300000},
            ctx["artist_headers"],
        )
    )

    validate_error(
        api.decide_waiver(
            clause["id"], {"decision": "GRANTED", "waiver_fee_cents": 299999}, BUSINESS_AFFAIRS
        ),
        "ERR_WAIVER_FEE_BELOW_OFFER",
        422,
    )

    pending = validate_success(api.get_radius_clause(clause["id"], BUSINESS_AFFAIRS))
    assert pending["enforcement_status"] == "BREACHED"
    assert pending["waiver_status"] == "REQUESTED"
    assert pending["waiver_fee_cents"] == 0

    granted = validate_success(
        api.decide_waiver(
            clause["id"], {"decision": "GRANTED", "waiver_fee_cents": 300000}, BUSINESS_AFFAIRS
        )
    )
    assert granted["waiver_status"] == "GRANTED"
    assert granted["enforcement_status"] == "WAIVED"
    assert granted["waiver_fee_cents"] == 300000

    released = validate_success(api.get_booking(booking["id"], TALENT_BUYER))
    assert released["settlement_status"] == "UNFUNDED"
    assert released["settlement_total_cents"] == 2100000


def test_the_role_check_answers_before_existence_and_before_shape(api):
    """A role that is not on the endpoint gets 403, whatever else the request gets wrong.

    "Many operations in this system can fail for several reasons at once, and the answer the client receives is fully determined: the checks form one strictly ordered ladder, the lowest-ranked failing check is the response, and every check ranked below it is never evaluated at all — so its side effects never happen and its error is never seen."
    "That authorization decision is made against the static endpoint matrix before any path resource is loaded, which means a forbidden role addressing an identifier that does not exist receives 403, never 404."
    "`ArtistRep` is never authorized on festival, budget-tier or stage reads at all; those come back as `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/validations/role_check_precedes_existence_and_shape_checks
    """
    ctx = _edition(api)

    validate_error(
        api.get_festival(NON_EXISTENT_UUID, ctx["artist_headers"]),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.create_offer({"festival_id": ctx["festival"]["id"]}, FINANCE_CONTROLLER),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.get_festival(NON_EXISTENT_UUID, TALENT_BUYER),
        "ERR_FESTIVAL_NOT_FOUND",
        404,
    )


def test_a_stale_version_answers_before_the_terminal_state_of_the_booking(api):
    """A stale expected version reports 412 even on a cancelled booking with a bad figure.

    "Amending an executed guarantee requires `expected_booking_version` to match the target booking's `version`."
    "A mismatch is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412)."
    "This sits above every state, safety and fiscal check, so a stale version on an otherwise-invalid request still reports 412."
    "`version` is an integer that begins at 1 when the row is created and increments by exactly one on every mutation of that row, whether the mutation was requested directly or produced as a side effect of an operation against some other resource."
    "Neither dimension waits on the other, and a transition illegal on either dimension is `ERR_INVALID_BOOKING_STATE`."

    Design: Corner/validations/occ_precedes_state_on_a_cancelled_booking_amendment
    """
    ctx = _edition(api)
    booking = fx.accepted_booking(api, ctx)
    stale_version = validate_success(api.get_booking(booking["id"], TALENT_BUYER))["version"]

    validate_success(
        api.cancel_booking(
            booking["id"],
            cancel_payload(cancelling_party="PROMOTER", cancellation_reason="Stage rebuild."),
            TALENT_BUYER,
        )
    )

    validate_error(
        api.amend_guarantee(
            booking["id"],
            {
                "guarantee_cents": 9000000,
                "expected_booking_version": stale_version,
                "amendment_reason": "Stale and terminal at once.",
            },
            TALENT_BUYER,
        ),
        "ERR_STALE_BOOKING_VERSION",
        412,
    )

    cancelled = validate_success(api.get_booking(booking["id"], TALENT_BUYER))
    assert cancelled["contract_status"] == "CANCELLED"
    assert cancelled["version"] > stale_version

    validate_error(
        api.amend_guarantee(
            booking["id"],
            {
                "guarantee_cents": 9000000,
                "expected_booking_version": cancelled["version"],
                "amendment_reason": "Fresh version, still terminal.",
            },
            TALENT_BUYER,
        ),
        "ERR_INVALID_BOOKING_STATE",
        409,
    )
