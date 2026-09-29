"""
Payloads that fail two validation tiers at once, where only the earlier one may surface.

PRD 2.10: "Every request is validated in one fixed order, and the **first**
failure encountered is the response. The order matters because several checks can
fail simultaneously on the same payload, and only the highest-priority code may
surface."
"""

from types import SimpleNamespace

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ERR_GROUP_BLOCK_NOT_TENTATIVE,
    ERR_MAX_OCCUPANCY_EXCEEDED,
    ERR_NO_FARE_RULE_FOR_WINDOW,
    ERR_OVERSELL_NOT_PERMITTED,
    ERR_PROMOTION_NOT_ACTIVE,
    ERR_PROMO_AUDIENCE_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_INVENTORY_VERSION,
    GROUP_SALES_AGENT,
    GROUP_SALES_AGENT_2,
    GROUP_SALES_AGENT_3,
    GROUP_SALES_AGENT_USER_ID,
    GROUP_SALES_AGENT_2_USER_ID,
    RESERVATION_AGENT,
    REVENUE_MANAGER,
    factories as f,
    fixtures as fx,
)

FLAT_FARE_150K = {
    "window_open_days_to_sail": 730,
    "window_close_days_to_sail": 0,
    "base_lower_berth_fare_cents": 150000,
    "third_berth_fare_cents": 50000,
    "fourth_berth_fare_cents": 40000,
}


# ==========================================================================
# tier 8 (segregation of duties) versus tier 10 (own-state precondition)
# ==========================================================================


def _block_already_signed_definite(api):
    """A block created by gsa-001 and signed DEFINITE by gsa-002 under CT-9001."""
    world = fx.simple_world(
        api,
        voyage_code="SOD-2701",
        nights=4,
        total_lower_berths=20,
        physical_cabins=4,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_150K,
    )
    world.block = fx.make_group_block(
        api,
        world.sailing["id"],
        world.category["id"],
        headers=GROUP_SALES_AGENT,
        cabins_held=2,
        review_date="2026-09-01T00:00:00Z",
        release_policy="ATTRITION_50",
    )
    world.signed = fx.sign_definite(
        api, world.block["id"], contract_reference="CT-9001", headers=GROUP_SALES_AGENT_2
    )
    return world


def test_four_eyes_refusal_outranks_the_already_definite_precondition(api):
    """The creator re-signing a DEFINITE block sees 403, not the 409 state code.

    PRD 2.10 places segregation of duties at priority 8: "on group-block definite
    signature only, X-User-ID must differ from created_by_user_id:
    ERR_SEGREGATION_OF_DUTIES at HTTP 403", while own-state preconditions sit at
    priority 10: "the target entity must currently be in a state from which the
    requested transition is declared ... ERR_GROUP_BLOCK_NOT_TENTATIVE ... All
    carry HTTP 409."

    Design: Difficulty/priority_pair_validation_conflict/sod_auth_beats_group_block_state_precondition
    """
    world = _block_already_signed_definite(api)

    response = api.confirm_definite(
        world.block["id"], {"contract_reference": "CT-9002"}, GROUP_SALES_AGENT
    )
    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)

    block = fx.read_block(api, world.block["id"])
    assert block["status"] == "DEFINITE"
    assert block["created_by_user_id"] == GROUP_SALES_AGENT_USER_ID
    assert block["confirmed_by_user_id"] == GROUP_SALES_AGENT_2_USER_ID
    # PRD 3.3: the refused call stored nothing, so the first contract stands.
    assert block["contract_reference"] == "CT-9001"

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["group_held_cabins"] == 2
    assert inventory["available_cabins"] == 2


def test_a_third_agent_on_the_same_block_reaches_the_state_precondition(api):
    """With four eyes satisfied, the later tier is the one that refuses.

    PRD 3.3: "the block must currently be TENTATIVE (otherwise
    ERR_GROUP_BLOCK_NOT_TENTATIVE) ... and the four-eyes rule of 2.1 applies: the
    signing X-User-ID must differ from created_by_user_id, or the request is
    refused with ERR_SEGREGATION_OF_DUTIES." A signer who is not the creator
    clears priority 8 and therefore surfaces the priority 10 code instead.

    Design: Difficulty/priority_pair_validation_conflict/sod_auth_beats_group_block_state_precondition
    """
    world = _block_already_signed_definite(api)

    response = api.confirm_definite(
        world.block["id"], {"contract_reference": "CT-9003"}, GROUP_SALES_AGENT_3
    )
    validate_error(response, ERR_GROUP_BLOCK_NOT_TENTATIVE, 409)

    block = fx.read_block(api, world.block["id"])
    assert block["status"] == "DEFINITE"
    assert block["confirmed_by_user_id"] == GROUP_SALES_AGENT_2_USER_ID
    assert block["contract_reference"] == "CT-9001"


# ==========================================================================
# tier 12 (berth capacity) versus tier 20 (money gates)
# ==========================================================================


def _sailing_with_an_exhausted_campaign(api):
    """A 3-berth named category whose only campaign has already been exhausted.

    FLASH1 allows a single redemption; the first sale takes it, so the campaign
    is sitting in EXHAUSTED when the oversized party arrives.
    """
    named = fx.make_category(
        api,
        code="OVS",
        tier_rank=2,
        max_occupancy=3,
        lower_berths=2,
        onboard_spend_lower_per_night_cents=11000,
        onboard_spend_upper_per_night_cents=7000,
    )
    world = fx.simple_world(
        api,
        voyage_code="PRM-2701",
        nights=4,
        total_lower_berths=20,
        category=named,
        physical_cabins=10,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_150K,
    )
    world.promo = fx.make_promotion(
        api,
        world.sailing["id"],
        world.sailing["version"],
        code="FLASH1",
        audience="GENERAL",
        discount_pct=0.1,
        starts_on="2026-08-01T00:00:00Z",
        ends_on="2026-08-31T00:00:00Z",
        max_redemptions=1,
    )
    fx.activate_promotion(api, world.promo["id"])
    world.first = fx.guest_with_booking(api, world, promotion_id=world.promo["id"])
    assert fx.read_promotion(api, world.promo["id"])["status"] == "EXHAUSTED"
    return world


def test_berth_capacity_refusal_outranks_the_exhausted_campaign(api):
    """A party of 4 in a 3-berth cabin sees the capacity code, not a money code.

    PRD 2.10 places berth capacity at priority 12 and money gates at priority 20,
    and states the consequence outright: "Because money is last, a payload that is
    both sold out and underfunded reports the capacity failure, not the money
    failure." PRD 3.4 agrees: "Both checks run before the fare is derived, so a
    nonsensical party never produces a price."

    Design: Difficulty/priority_pair_validation_conflict/berth_safety_beats_exhausted_promotion_fiscal_check
    """
    world = _sailing_with_an_exhausted_campaign(api)
    guest = fx.make_guest(api)

    response = api.create_booking(
        f.booking_payload(
            world.sailing["id"],
            world.category["id"],
            guest["id"],
            occupancy_adults=2,
            third_berth_guests=1,
            fourth_berth_guests=1,
            promotion_id=world.promo["id"],
        ),
        RESERVATION_AGENT,
    )
    validate_error(response, ERR_MAX_OCCUPANCY_EXCEEDED, 422)

    promo = fx.read_promotion(api, world.promo["id"])
    # PRD 3.4: only "a successful quote raises the campaign's redemption_count".
    assert promo["status"] == "EXHAUSTED"
    assert promo["redemption_count"] == 1

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["booked_cabins"] == 1
    assert inventory["available_cabins"] == 9

    _, meta = validate_paginated(
        api.list_bookings(REVENUE_MANAGER, params={"guest_id": guest["id"]})
    )
    assert meta["total_count"] == 0


def test_a_party_that_fits_reaches_the_campaign_state_gate(api):
    """With the berth check cleared, the later money tier is what refuses.

    PRD 3.4: "The promotion must be ACTIVE and the current instant must lie
    inside its inclusive starts_on-to-ends_on interval, or the sale is refused
    with ERR_PROMOTION_NOT_ACTIVE." A three-guest party fits the 3-berth
    category, so priority 12 passes and priority 20 is reached.

    Design: Difficulty/priority_pair_validation_conflict/berth_safety_beats_exhausted_promotion_fiscal_check
    """
    world = _sailing_with_an_exhausted_campaign(api)
    guest = fx.make_guest(api)

    response = api.create_booking(
        f.booking_payload(
            world.sailing["id"],
            world.category["id"],
            guest["id"],
            occupancy_adults=2,
            third_berth_guests=1,
            promotion_id=world.promo["id"],
        ),
        RESERVATION_AGENT,
    )
    validate_error(response, ERR_PROMOTION_NOT_ACTIVE, 422)

    promo = fx.read_promotion(api, world.promo["id"])
    assert promo["status"] == "EXHAUSTED"
    assert promo["redemption_count"] == 1

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["booked_cabins"] == 1


# ==========================================================================
# tier 15 (fare-window coverage) versus tier 17 (referential integrity)
# ==========================================================================


def _repeat_guest_campaign_outside_every_fare_window(api, *, cover_the_window=False):
    """A sailing whose fare calendar has a hole where the campaign is live.

    The only fare window is the far-out [120, 365) one, and the clock is moved to
    100 days out, which no window covers. The REPEAT_GUEST campaign is live at
    that instant, and the buyer has no prior sailings, so both tiers are armed.
    """
    world = fx.simple_world(
        api,
        voyage_code="FWG-2701",
        nights=7,
        total_lower_berths=20,
        physical_cabins=10,
        oversell_allowance=2,
    )
    world.promo = fx.make_promotion(
        api,
        world.sailing["id"],
        world.sailing["version"],
        code="LOYAL10",
        audience="REPEAT_GUEST",
        discount_pct=0.1,
        starts_on="2026-09-20T00:00:00Z",
        ends_on="2026-10-31T00:00:00Z",
        max_redemptions=5,
    )
    if cover_the_window:
        # A second, non-overlapping window that does contain 100 days to sail.
        fx.make_fare_rule(
            api,
            world.sailing["id"],
            world.category["id"],
            window_open_days_to_sail=120,
            window_close_days_to_sail=60,
            base_lower_berth_fare_cents=219995,
            third_berth_fare_cents=74997,
            fourth_berth_fare_cents=59997,
        )
    fx.set_clock(api, "2026-10-02T00:00:00Z")
    fx.activate_promotion(api, world.promo["id"])
    world.guest = fx.make_guest(api, prior_sailings_count=0)
    return world


def test_missing_fare_window_outranks_the_audience_mismatch(api):
    """No priceable window at 100 days out beats the ineligible audience.

    PRD 2.10 places fare-window coverage at priority 15: "a fare rule must exist
    whose half-open window contains the relevant days-to-sail figure for the
    required cabin category ... ERR_NO_FARE_RULE_FOR_WINDOW at HTTP 422", and
    referential integrity - including "a quoted promotion's audience must match
    the booking (ERR_PROMO_AUDIENCE_MISMATCH)" - at priority 17.

    Design: Difficulty/priority_pair_validation_conflict/missing_fare_window_temporal_beats_promo_audience_referential
    """
    world = _repeat_guest_campaign_outside_every_fare_window(api)

    response = api.create_booking(
        f.booking_payload(
            world.sailing["id"],
            world.category["id"],
            world.guest["id"],
            occupancy_adults=2,
            promotion_id=world.promo["id"],
        ),
        RESERVATION_AGENT,
    )
    validate_error(response, ERR_NO_FARE_RULE_FOR_WINDOW, 422)

    guest = fx.read_guest(api, world.guest["id"])
    # PRD 3.4: fewer than 1 prior sailing gives NONE, which no REPEAT_GUEST
    # campaign accepts - but that failure never got to run.
    assert guest["loyalty_tier"] == "NONE"
    assert guest["bookings_count"] == 0

    promo = fx.read_promotion(api, world.promo["id"])
    assert promo["status"] == "ACTIVE"
    assert promo["redemption_count"] == 0

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["booked_cabins"] == 0
    assert inventory["waitlisted_bookings_count"] == 0


def test_with_the_window_covered_the_audience_mismatch_surfaces(api):
    """Filling the fare-calendar hole lets the priority 17 code through.

    PRD 3.4: "a REPEAT_GUEST campaign requires the guest's loyalty_tier to be
    anything other than NONE". PRD 3.2 permits the second window because "windows
    that merely touch at a shared endpoint do not overlap and are accepted".

    Design: Difficulty/priority_pair_validation_conflict/missing_fare_window_temporal_beats_promo_audience_referential
    """
    world = _repeat_guest_campaign_outside_every_fare_window(api, cover_the_window=True)

    response = api.create_booking(
        f.booking_payload(
            world.sailing["id"],
            world.category["id"],
            world.guest["id"],
            occupancy_adults=2,
            promotion_id=world.promo["id"],
        ),
        RESERVATION_AGENT,
    )
    validate_error(response, ERR_PROMO_AUDIENCE_MISMATCH, 422)

    promo = fx.read_promotion(api, world.promo["id"])
    assert promo["status"] == "ACTIVE"
    assert promo["redemption_count"] == 0

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["booked_cabins"] == 0


# ==========================================================================
# tier 9 (optimistic concurrency) versus tier 14 (oversell eligibility)
# ==========================================================================


def _allotment_written_once_already(api):
    """A named-category allotment whose version has already moved past the read.

    ``stale_version`` is the version the client observed; a legal no-op write of
    the same allowance value then advances the row past it.
    """
    fx.set_clock(api)
    named = fx.make_category(api, code="OV", tier_rank=2, max_occupancy=4)
    sailing = fx.make_sailing(
        api, voyage_code="OCC-2701", nights=4, total_lower_berths=20
    )
    inventory = fx.make_inventory(
        api, sailing["id"], named["id"], physical_cabins=10, oversell_allowance=0
    )
    stale_version = inventory["version"]

    rewritten = validate_success(
        api.patch_sailing_inventory(
            inventory["id"],
            {"oversell_allowance": 0, "expected_inventory_version": stale_version},
            REVENUE_MANAGER,
        )
    )
    assert rewritten["version"] == stale_version + 1

    return SimpleNamespace(
        category=named,
        sailing=sailing,
        inventory=inventory,
        stale_version=stale_version,
        current_version=rewritten["version"],
    )


def test_stale_inventory_version_outranks_the_oversell_eligibility_check(api):
    """A stale guard on an illegal oversell write reports 412, not 422.

    PRD 2.10 places optimistic concurrency at priority 9:
    "expected_inventory_version must equal the allotment's version on the
    oversell-allowance write ... ERR_STALE_INVENTORY_VERSION ... at HTTP 412",
    and oversell eligibility at priority 14: "an oversell_allowance greater than 0
    is accepted only when the allotment's cabin category has is_guarantee true; a
    named category may never be oversold: ERR_OVERSELL_NOT_PERMITTED at HTTP 422."

    Design: Difficulty/priority_pair_validation_conflict/stale_inventory_version_beats_oversell_safety_check
    """
    world = _allotment_written_once_already(api)

    response = api.patch_sailing_inventory(
        world.inventory["id"],
        {"oversell_allowance": 3, "expected_inventory_version": world.stale_version},
        REVENUE_MANAGER,
    )
    validate_error(response, ERR_STALE_INVENTORY_VERSION, 412)

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["oversell_allowance"] == 0
    assert inventory["effective_oversell_cabins"] == 0
    assert inventory["available_cabins"] == 10
    # PRD 2.9: a refused write never advances the row it guarded.
    assert inventory["version"] == world.current_version


def test_with_a_fresh_version_the_oversell_eligibility_check_surfaces(api):
    """Re-reading the row lets the priority 14 code through.

    PRD 2.9: the stale-version check "forces the second writer to re-read the
    allotment - whose booked_cabins, group_held_cabins, and
    effective_oversell_cabins may have moved - before re-committing an oversell
    decision." PRD 3.1: "A non-zero oversell_allowance on a category whose
    is_guarantee is false is rejected with ERR_OVERSELL_NOT_PERMITTED, both at
    creation and on any later re-set."

    Design: Difficulty/priority_pair_validation_conflict/stale_inventory_version_beats_oversell_safety_check
    """
    world = _allotment_written_once_already(api)

    response = api.patch_sailing_inventory(
        world.inventory["id"],
        {"oversell_allowance": 3, "expected_inventory_version": world.current_version},
        REVENUE_MANAGER,
    )
    validate_error(response, ERR_OVERSELL_NOT_PERMITTED, 422)

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["oversell_allowance"] == 0
    assert inventory["effective_oversell_cabins"] == 0
    assert inventory["version"] == world.current_version
