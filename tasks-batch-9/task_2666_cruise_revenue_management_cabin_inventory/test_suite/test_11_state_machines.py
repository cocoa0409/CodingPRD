"""
Declared transitions, their preconditions, their side effects and their dead ends.

PRD 2.10 places own-state preconditions at priority 10 and gives each machine its
own conflict code, so a refused transition names the state it expected.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ERR_BOOKING_NOT_AWAITING_SETTLEMENT,
    ERR_GROUP_BLOCK_NOT_TENTATIVE,
    ERR_ITINERARY_CHANGE_NOT_DRAFT,
    ERR_PROMOTION_NOT_SCHEDULED,
    ERR_SAILING_NOT_OPEN,
    ERR_SAILING_NOT_PLANNED,
    ERR_SAILING_NOT_SELLABLE,
    ERR_SAILING_NOT_SUSPENDED,
    GROUP_SALES_AGENT,
    GROUP_SALES_AGENT_2,
    GROUP_SALES_AGENT_2_USER_ID,
    GROUP_SALES_AGENT_3,
    GROUP_SALES_AGENT_USER_ID,
    PORT_OPS_COORDINATOR,
    RESERVATION_AGENT,
    REVENUE_MANAGER,
    assert_capacity_identity,
    factories as f,
    fixtures as fx,
)

FLAT_FARE_50K = {
    "window_open_days_to_sail": 730,
    "window_close_days_to_sail": 0,
    "base_lower_berth_fare_cents": 50000,
    "third_berth_fare_cents": 20000,
    "fourth_berth_fare_cents": 15000,
}


def test_open_for_sale_returns_the_freshly_derived_sailing(api):
    """The transition re-runs both chains and bumps the version exactly once.

    PRD 3.1: "Opening for sale sets the status, recomputes the revenue chain
    (available_lower_berth_days_gross, available_lower_berth_days_net,
    ralbd_gross_cents, ralbd_net_cents, and revenue_alert) and the occupancy chain
    (occupancy_pct, inventory_posture, and final_payment_risk_flag), and increments
    the sailing's version by 1."

    Design: Corner/state_machines/open_for_sale_moves_a_planned_sailing_and_bumps_version
    """
    world = fx.simple_world(api, voyage_code="AUR-2701", open_now=False)
    assert world.sailing["version"] == 1

    opened = validate_success(api.open_for_sale(world.sailing["id"], REVENUE_MANAGER))

    assert opened["id"] == world.sailing["id"]
    assert opened["status"] == "OPEN_FOR_SALE"
    assert opened["version"] == 2
    assert opened["inventory_posture"] == "OPEN"
    assert float(opened["occupancy_pct"]) == 0.0
    assert opened["available_lower_berth_days_gross"] == 1400
    assert opened["available_lower_berth_days_net"] == 1400
    assert opened["ralbd_gross_cents"] == 0
    assert opened["ralbd_net_cents"] == 0
    assert opened["revenue_alert"] is True


def test_both_sellability_preconditions_are_enforced_independently(api):
    """No allotment and no fare rule are separate failures behind the same code.

    PRD 3.1: "the voyage must be sellable in substance: at least one allotment row
    and at least one fare rule must already exist for it, otherwise the request is
    refused with ERR_SAILING_NOT_SELLABLE."

    Design: Corner/state_machines/open_for_sale_without_allotment_or_fare_rule_is_rejected
    """
    fx.set_clock(api)
    category = fx.make_guarantee_category(api)
    bare = fx.make_sailing(api, voyage_code="NOS-2701")
    partial = fx.make_sailing(
        api,
        voyage_code="NOF-2701",
        ship_code="BOREAL",
        embark_date="2027-02-10T17:00:00Z",
        total_lower_berths=100,
    )
    fx.make_inventory(
        api, partial["id"], category["id"], physical_cabins=10, oversell_allowance=0
    )

    validate_error(
        api.open_for_sale(bare["id"], REVENUE_MANAGER), ERR_SAILING_NOT_SELLABLE, 422
    )
    validate_error(
        api.open_for_sale(partial["id"], REVENUE_MANAGER), ERR_SAILING_NOT_SELLABLE, 422
    )

    assert fx.read_sailing(api, bare["id"])["status"] == "PLANNED"
    refused = fx.read_sailing(api, partial["id"])
    assert refused["status"] == "PLANNED"
    assert refused["version"] == partial["version"]

    fx.make_fare_rule(api, partial["id"], category["id"], **FLAT_FARE_50K)
    opened = validate_success(api.open_for_sale(partial["id"], REVENUE_MANAGER))
    assert opened["status"] == "OPEN_FOR_SALE"
    assert opened["version"] == 2
    # 100 lower berths across 7 nights.
    assert opened["available_lower_berth_days_gross"] == 700


def test_closing_inventory_cancels_every_waitlisted_booking(api):
    """Both queued rows go, not merely the head, and the cabin holder is untouched.

    PRD 3.9: "Every booking of that sailing sitting in WAITLISTED is moved to
    CANCELLED with cancel_reason INVENTORY_CLOSED, provisional_penalty_cents 0, and
    cancellation_penalty_cents 0 - a guest who never got a cabin owes nothing - and
    their payment_status is left exactly as it was. Each affected allotment's
    waitlisted_bookings_count is recomputed, and the sailing's version is incremented
    by 1."

    Design: Corner/state_machines/close_inventory_cancels_every_waitlisted_booking
    """
    world = fx.simple_world(
        api,
        voyage_code="WLC-2701",
        nights=4,
        total_lower_berths=40,
        physical_cabins=1,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
    )
    holder_guest = fx.make_guest(api, prior_sailings_count=0)
    holder = fx.make_booking(
        api,
        world.sailing["id"],
        world.category["id"],
        holder_guest["id"],
        occupancy_adults=2,
    )
    queued = []
    for _ in range(2):
        guest = fx.make_guest(api, prior_sailings_count=0)
        queued.append(
            fx.make_booking(
                api,
                world.sailing["id"],
                world.category["id"],
                guest["id"],
                occupancy_adults=2,
                allow_waitlist=True,
            )
        )
    assert [row["booking_status"] for row in queued] == ["WAITLISTED", "WAITLISTED"]
    version_before = fx.read_sailing(api, world.sailing["id"])["version"]

    closed = validate_success(api.close_inventory(world.sailing["id"], REVENUE_MANAGER))

    assert closed["status"] == "INVENTORY_CLOSED"
    assert closed["version"] == version_before + 1

    for row in queued:
        cancelled = fx.read_booking(api, row["id"])
        assert cancelled["booking_status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "INVENTORY_CLOSED"
        assert cancelled["provisional_penalty_cents"] == 0
        assert cancelled["cancellation_penalty_cents"] == 0
        # The money dimension is untouched by a waitlisted cancellation.
        assert cancelled["payment_status"] == "AWAITING_DEPOSIT"

    still_held = fx.read_booking(api, holder["id"])
    assert still_held["booking_status"] == "OPTION"
    assert still_held["net_ticket_cents"] == 100000
    assert still_held["deposit_due_cents"] == 50000

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["waitlisted_bookings_count"] == 0
    assert inventory["booked_cabins"] == 1
    assert inventory["available_cabins"] == 0
    assert_capacity_identity(inventory)

    sailing = fx.read_sailing(api, world.sailing["id"])
    # Waitlisted berths are never counted as sold: 2 of 40 is 5.00 percent.
    assert sailing["lower_berths_sold"] == 2
    assert float(sailing["occupancy_pct"]) == 5.0


def test_four_undeclared_transitions_name_four_different_expected_states(api):
    """Each refusal names the state the endpoint wanted, not a generic conflict.

    PRD 2.10 priority 10: "the target entity must currently be in a state from which
    the requested transition is declared. Depending on the entity and action, the code
    is ERR_SAILING_NOT_PLANNED, ERR_SAILING_NOT_OPEN, ERR_SAILING_NOT_SUSPENDED, ...
    ERR_BOOKING_NOT_AWAITING_SETTLEMENT". PRD 3.9 supplies two of them - "Resuming
    requires status SALES_SUSPENDED - otherwise ERR_SAILING_NOT_SUSPENDED" and
    "Suspending requires status OPEN_FOR_SALE - otherwise ERR_SAILING_NOT_OPEN" - PRD
    3.1 the third, "The sailing must currently be in PLANNED - any other status is
    rejected with ERR_SAILING_NOT_PLANNED", and PRD 3.6 the fourth: settlement
    "requires payment_status to be PENALTY_ASSESSED (otherwise
    ERR_BOOKING_NOT_AWAITING_SETTLEMENT)".

    Design: Corner/state_machines/resume_sales_on_an_open_sailing_is_rejected
    """
    world = fx.simple_world(api, voyage_code="AUR-2701")
    planned = fx.make_sailing(
        api,
        voyage_code="PLN-2701",
        ship_code="BOREAL",
        embark_date="2027-02-10T17:00:00Z",
        total_lower_berths=100,
    )
    guest = fx.make_guest(api, prior_sailings_count=0)
    live = fx.make_booking(
        api, world.sailing["id"], world.category["id"], guest["id"], occupancy_adults=2
    )
    # The sale legitimately cascaded into the sailing - PRD 2.8: "a booking cascade
    # that moves a sailing's aggregates bumps the sailing's version" - so the
    # no-write baseline for the four refusals is read after the sale, not before it.
    open_version = fx.read_sailing(api, world.sailing["id"])["version"]

    validate_error(
        api.resume_sales(world.sailing["id"], REVENUE_MANAGER),
        ERR_SAILING_NOT_SUSPENDED,
        409,
    )
    validate_error(
        api.open_for_sale(world.sailing["id"], REVENUE_MANAGER),
        ERR_SAILING_NOT_PLANNED,
        409,
    )
    validate_error(
        api.suspend_sales(planned["id"], {"reason": "PRICING_REVIEW"}, REVENUE_MANAGER),
        ERR_SAILING_NOT_OPEN,
        409,
    )
    validate_error(
        api.settle_cancellation(live["id"], REVENUE_MANAGER),
        ERR_BOOKING_NOT_AWAITING_SETTLEMENT,
        409,
    )

    unchanged = fx.read_sailing(api, world.sailing["id"])
    assert unchanged["status"] == "OPEN_FOR_SALE"
    assert unchanged["version"] == open_version
    assert unchanged["suspension_count"] == 0
    assert unchanged["suspension_reason"] is None

    still_planned = fx.read_sailing(api, planned["id"])
    assert still_planned["status"] == "PLANNED"
    assert still_planned["suspension_count"] == 0

    still_live = fx.read_booking(api, live["id"])
    assert still_live["booking_status"] == "OPTION"
    assert still_live["payment_status"] == "AWAITING_DEPOSIT"
    assert still_live["settled_at"] is None
    assert still_live["refund_cents"] is None


def test_every_machine_starts_where_it_declares_it_starts(api):
    """Six machines, and the booking's two dimensions both begin at their own value.

    PRD 3.1: "A newly created sailing lands in PLANNED with suspension_count at 0".
    PRD 3.2: a campaign "is created in SCHEDULED with redemption_count at 0". PRD 3.3:
    "A new block is created in TENTATIVE with picked_up_cabins, review_count,
    review_extension_count, and released_cabins_total all at 0, confirmed_by_user_id
    and contract_reference null, and created_by_user_id set to the creating agent's
    X-User-ID." PRD 3.4: "A newly written booking therefore comes back with
    booking_status either OPTION or WAITLISTED, payment_status AWAITING_DEPOSIT".
    PRD 3.7: "A newly submitted bid lands in SUBMITTED with counter_rounds at 0,
    guest_count copied from the booking as the award multiplier, submitted_days_to_sail
    stamped from the bid instant, min_acceptable_per_guest_cents set from the
    derivation above, and countered_min_per_guest_cents, award_amount_cents, and
    decline_reason all null." PRD 3.8: "The change is created in DRAFT with published_at
    null".

    Design: Corner/state_machines/new_entities_start_in_their_declared_initial_states
    """
    fx.set_clock(api)
    ov = fx.make_category(api, f.ocean_view_category_payload())
    ia = fx.make_guarantee_category(api, upgrade_to_category_id=ov["id"])
    sailing = fx.make_sailing(api, voyage_code="INI-2701")
    assert sailing["status"] == "PLANNED"
    assert sailing["version"] == 1
    fx.make_inventory(api, sailing["id"], ia["id"], physical_cabins=60, oversell_allowance=4)
    fx.make_inventory(api, sailing["id"], ov["id"], physical_cabins=20, oversell_allowance=0)
    wide = {"window_open_days_to_sail": 365, "window_close_days_to_sail": 0}
    fx.make_fare_rule(api, sailing["id"], ia["id"], **wide)
    fx.make_fare_rule(
        api,
        sailing["id"],
        ov["id"],
        base_lower_berth_fare_cents=289995,
        third_berth_fare_cents=80000,
        fourth_berth_fare_cents=60000,
        **wide,
    )
    opened = fx.open_sailing(api, sailing["id"])
    guest = fx.make_guest(api, prior_sailings_count=0)

    fresh_sailing = fx.make_sailing(
        api,
        voyage_code="INI-2702",
        ship_code="BOREAL",
        embark_date="2027-03-10T17:00:00Z",
        nights=5,
        total_lower_berths=80,
    )
    assert fresh_sailing["status"] == "PLANNED"
    assert fresh_sailing["version"] == 1

    promotion = fx.make_promotion(
        api,
        sailing["id"],
        opened["version"],
        code="EARLYBIRD",
        starts_on="2026-08-05T00:00:00Z",
        ends_on="2026-08-10T00:00:00Z",
        max_redemptions=5,
    )
    assert promotion["status"] == "SCHEDULED"
    assert promotion["redemption_count"] == 0
    assert promotion["version"] == 1

    block = fx.make_group_block(
        api, sailing["id"], ia["id"], headers=GROUP_SALES_AGENT, cabins_held=3
    )
    assert block["status"] == "TENTATIVE"
    assert block["picked_up_cabins"] == 0
    assert block["released_cabins_total"] == 0
    assert block["review_count"] == 0
    assert block["review_extension_count"] == 0
    assert block["created_by_user_id"] == GROUP_SALES_AGENT_USER_ID
    assert block["confirmed_by_user_id"] is None

    booking = fx.make_booking(api, sailing["id"], ia["id"], guest["id"], occupancy_adults=2)
    # The two dimensions each start at their own initial value.
    assert booking["booking_status"] == "OPTION"
    assert booking["payment_status"] == "AWAITING_DEPOSIT"
    assert booking["net_ticket_cents"] == 379990
    assert booking["deposit_due_cents"] == 75998
    # 162 days to sail is strictly greater than the 75-day final-payment horizon.
    assert booking["payment_terms"] == "STANDARD"
    assert booking["amount_paid_cents"] == 0

    # 2026-11-11 is 60 days before departure, the far edge of the bid window.
    fx.set_clock(api, "2026-11-11T17:00:00Z")
    bid = fx.submit_bid(api, booking, guest["id"], ov["id"], 33000)
    assert bid["status"] == "SUBMITTED"
    assert bid["counter_rounds"] == 0
    assert bid["submitted_days_to_sail"] == 60
    assert bid["guest_count"] == 2
    # round(100000 x 0.40) == 40000 less round(7 x 2 x 1000 / 2) == 7000.
    assert bid["min_acceptable_per_guest_cents"] == 33000
    assert bid["countered_min_per_guest_cents"] is None
    assert bid["award_amount_cents"] is None

    change = fx.make_itinerary_change(api, sailing["id"])
    assert change["status"] == "DRAFT"
    assert change["published_at"] is None
    # PRD 3.8: 2,500 cents of credit under OBC_ONLY, and no cash at all.
    assert change["obc_per_guest_cents"] == 2500
    assert float(change["refund_pct"]) == 0.0
    assert change["affected_bookings_count"] == 0


def test_a_replayed_one_shot_transition_is_a_conflict_and_grants_nothing(api):
    """Publishing, activating and signing a second time all conflict, and nothing doubles.

    PRD 3.8: "a change already published is refused with
    ERR_ITINERARY_CHANGE_NOT_DRAFT". PRD 3.2: activation "requires the promotion to be
    in SCHEDULED (otherwise ERR_PROMOTION_NOT_SCHEDULED)". PRD 3.3: "the block must
    currently be TENTATIVE (otherwise ERR_GROUP_BLOCK_NOT_TENTATIVE)", while the
    four-eyes rule only bites when "the signing X-User-ID must differ from
    created_by_user_id" is violated - so a third operator's replay is decided by the
    state check, not by ERR_SEGREGATION_OF_DUTIES. PRD 2.5: a version "increments by
    exactly 1 on every mutation", and a refused request mutates nothing.

    Design: Corner/state_machines/publishing_or_activating_or_signing_twice_is_rejected
    """
    world = fx.simple_world(api, voyage_code="IDM-2701")
    promotion = fx.make_promotion(
        api, world.sailing["id"], world.sailing["version"], code="SUMMERSALE"
    )
    activated = fx.activate_promotion(api, promotion["id"])
    assert activated["status"] == "ACTIVE"

    block = fx.make_group_block(
        api, world.sailing["id"], world.category["id"], headers=GROUP_SALES_AGENT
    )
    signed = fx.sign_definite(
        api, block["id"], contract_reference="MER-9001", headers=GROUP_SALES_AGENT_2
    )
    assert signed["status"] == "DEFINITE"

    guest = fx.make_guest(api, prior_sailings_count=0)
    booking = fx.make_booking(
        api, world.sailing["id"], world.category["id"], guest["id"], occupancy_adults=2
    )
    change = fx.make_itinerary_change(api, world.sailing["id"])
    published = fx.publish_itinerary_change(api, change["id"])
    assert published["status"] == "PUBLISHED"
    granted = fx.read_booking(api, booking["id"])
    assert granted["itinerary_compensation_obc_cents"] == 5000

    validate_error(
        api.publish_itinerary_change(change["id"], PORT_OPS_COORDINATOR),
        ERR_ITINERARY_CHANGE_NOT_DRAFT,
        409,
    )
    validate_error(
        api.activate_promotion(promotion["id"], REVENUE_MANAGER),
        ERR_PROMOTION_NOT_SCHEDULED,
        409,
    )
    # gsa-003 is neither the creator nor the signer, so priority 8 is satisfied.
    validate_error(
        api.confirm_definite(
            block["id"], {"contract_reference": "MER-9002"}, GROUP_SALES_AGENT_3
        ),
        ERR_GROUP_BLOCK_NOT_TENTATIVE,
        409,
    )

    settled = fx.read_booking(api, booking["id"])
    # 2,500 per guest for two guests, granted once - not 10,000.
    assert settled["itinerary_compensation_obc_cents"] == 5000
    assert settled["itinerary_refund_cents"] == 0
    assert settled["projected_onboard_gross_cents"] == 126000
    assert settled["projected_onboard_net_cents"] == 121000

    final_change = fx.read_itinerary_change(api, change["id"])
    assert final_change["affected_bookings_count"] == 1
    assert final_change["total_obc_granted_cents"] == 5000
    assert final_change["total_refund_granted_cents"] == 0
    assert final_change["version"] == published["version"]

    final_promotion = fx.read_promotion(api, promotion["id"])
    assert final_promotion["status"] == "ACTIVE"
    assert final_promotion["version"] == activated["version"]

    final_block = fx.read_block(api, block["id"])
    assert final_block["status"] == "DEFINITE"
    assert final_block["contract_reference"] == "MER-9001"
    assert final_block["confirmed_by_user_id"] == GROUP_SALES_AGENT_2_USER_ID
    assert final_block["version"] == signed["version"]


def test_guarantee_assignment_moves_the_cabin_without_moving_the_fare(api):
    """Four entities move in one call, and only the onboard side is re-derived.

    PRD 3.7: "On success the guarantee fare is honoured - net_ticket_cents does not
    change - while the cabin count moves between allotments: the guarantee allotment's
    booked_cabins falls by 1, the named allotment's booked_cabins rises by 1, and
    available_cabins is recomputed on both. The booking's
    projected_onboard_gross_cents and projected_onboard_net_cents are recomputed
    against the named category's spend indices, the sailing's
    projected_onboard_revenue_cents, ralbd_gross_cents, ralbd_net_cents, and
    revenue_alert are recomputed, and the booking's version is incremented by 1."

    Design: Corner/state_machines/guarantee_assignment_moves_a_cabin_between_two_allotments
    """
    fx.set_clock(api)
    ov = fx.make_category(api, f.ocean_view_category_payload())
    ia = fx.make_guarantee_category(api, upgrade_to_category_id=ov["id"])
    sailing = fx.make_sailing(api, voyage_code="ASG-2701")
    inv_ia = fx.make_inventory(
        api, sailing["id"], ia["id"], physical_cabins=60, oversell_allowance=4
    )
    inv_ov = fx.make_inventory(
        api, sailing["id"], ov["id"], physical_cabins=20, oversell_allowance=0
    )
    fx.make_fare_rule(api, sailing["id"], ia["id"])
    fx.make_fare_rule(
        api,
        sailing["id"],
        ov["id"],
        base_lower_berth_fare_cents=289995,
        third_berth_fare_cents=80000,
        fourth_berth_fare_cents=60000,
    )
    fx.open_sailing(api, sailing["id"])
    guest = fx.make_guest(api, prior_sailings_count=0)
    booking = fx.make_booking(api, sailing["id"], ia["id"], guest["id"], occupancy_adults=2)

    assigned = validate_success(
        api.assign_guarantee(
            booking["id"], {"assigned_cabin_category_id": ov["id"]}, RESERVATION_AGENT
        )
    )

    assert assigned["assigned_cabin_category_id"] == ov["id"]
    # What was sold is history; only the assignment moved.
    assert assigned["cabin_category_id"] == ia["id"]
    assert assigned["net_ticket_cents"] == 379990
    assert assigned["gross_ticket_cents"] == 379990
    # 7 nights x 2 guests x the OV lower index of 11,000.
    assert assigned["projected_onboard_gross_cents"] == 154000
    assert assigned["projected_onboard_net_cents"] == 154000
    assert assigned["version"] == booking["version"] + 1

    source = fx.read_inventory(api, inv_ia["id"])
    assert source["booked_cabins"] == 0
    assert source["available_cabins"] == 64
    assert_capacity_identity(source)

    target = fx.read_inventory(api, inv_ov["id"])
    assert target["booked_cabins"] == 1
    assert target["available_cabins"] == 19
    assert_capacity_identity(target)

    refreshed = fx.read_sailing(api, sailing["id"])
    assert refreshed["projected_onboard_revenue_cents"] == 154000
    assert refreshed["gross_ticket_revenue_cents"] == 379990
    # (379,990 + 154,000) over 200 x 7 available lower-berth days is 381.42..., so 381.
    assert refreshed["ralbd_gross_cents"] == 381
    assert refreshed["ralbd_net_cents"] == 381
    assert refreshed["revenue_alert"] is True
    # Berths sold do not move when a cabin changes category.
    assert refreshed["lower_berths_sold"] == 2
    assert float(refreshed["occupancy_pct"]) == 1.0


def test_departure_credits_the_confirmed_traveller_and_cancels_the_other(api):
    """The first hop of the sail cascade is conditional, and the tier is re-derived in it.

    PRD 3.9: "The sailing's status becomes SAILED, which is terminal - no transition
    leaves it. Every booking of the sailing in CONFIRMED moves to SAILED; because a
    booking reached SAILED, its guest's prior_sailings_count rises by 1, and because
    that count changed, the guest's loyalty_tier and repeat_guest_offer_pct are
    recomputed against the tier floors. Every booking still in OPTION or WAITLISTED at
    departure is moved to CANCELLED with cancel_reason SAILED_UNCONFIRMED - a guest who
    never confirmed does not sail. A tier promotion earned this way never reprices an
    existing booking: loyalty_discount_cents was pinned when each booking was created."

    Design: Corner/state_machines/ops_run_sails_the_voyage_and_credits_only_confirmed_travellers
    """
    world = fx.simple_world(
        api,
        voyage_code="SLD-2701",
        embark_date="2026-09-01T12:00:00Z",
        nights=4,
        total_lower_berths=40,
        physical_cabins=10,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
    )
    ada = fx.make_guest(api, prior_sailings_count=2)
    # Two prior sailings clear the MEMBER floor of 1 but not the GOLD floor of 3.
    assert ada["loyalty_tier"] == "MEMBER"
    assert float(ada["repeat_guest_offer_pct"]) == 0.0
    bo = fx.make_guest(api, prior_sailings_count=0)

    ada_booking = fx.make_booking(
        api, world.sailing["id"], world.category["id"], ada["id"], occupancy_adults=2
    )
    bo_booking = fx.make_booking(
        api, world.sailing["id"], world.category["id"], bo["id"], occupancy_adults=2
    )
    # 31 days out is inside the 75-day final-payment horizon, so both are payable now.
    assert ada_booking["payment_terms"] == "FULL_AT_BOOKING"
    assert ada_booking["net_ticket_cents"] == 100000
    assert ada_booking["loyalty_discount_cents"] == 0
    fx.pay(api, ada_booking["id"], "DEPOSIT", 100000)
    fx.pay(api, bo_booking["id"], "DEPOSIT", 100000)
    fx.confirm(api, ada_booking["id"])

    fx.set_clock(api, "2026-09-01T12:00:00Z")
    sailed = fx.run_ops(api, world.sailing["id"])
    assert sailed["status"] == "SAILED"

    travelled = fx.read_booking(api, ada_booking["id"])
    assert travelled["booking_status"] == "SAILED"
    assert travelled["payment_status"] == "PAID_IN_FULL"
    # The tier earned at departure does not reach back into the pinned fare.
    assert travelled["loyalty_discount_cents"] == 0
    assert travelled["net_ticket_cents"] == 100000

    credited = fx.read_guest(api, ada["id"])
    assert credited["prior_sailings_count"] == 3
    assert credited["loyalty_tier"] == "GOLD"
    assert float(credited["repeat_guest_offer_pct"]) == 0.03

    dropped = fx.read_booking(api, bo_booking["id"])
    assert dropped["booking_status"] == "CANCELLED"
    assert dropped["cancel_reason"] == "SAILED_UNCONFIRMED"

    uncredited = fx.read_guest(api, bo["id"])
    assert uncredited["prior_sailings_count"] == 0
    assert uncredited["loyalty_tier"] == "NONE"
    assert float(uncredited["repeat_guest_offer_pct"]) == 0.0

    assert sailed["lower_berths_sold"] == 2
    assert float(sailed["occupancy_pct"]) == 5.0
    assert sailed["gross_ticket_revenue_cents"] == 100000
    assert sailed["projected_onboard_revenue_cents"] == 72000
    assert sailed["available_lower_berth_days_gross"] == 160
    assert sailed["available_lower_berth_days_net"] == 160
    # (100,000 + 72,000) over 160 available lower-berth days is exactly 1,075.
    assert sailed["ralbd_gross_cents"] == 1075
    assert sailed["ralbd_net_cents"] == 1075
    assert sailed["revenue_alert"] is True

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["booked_cabins"] == 1
    assert inventory["available_cabins"] == 9
    assert_capacity_identity(inventory)
