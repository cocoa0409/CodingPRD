"""
The endpoint surface: round trips, action verbs, the computed read, the sweep.

Every scenario drives one endpoint shape end to end and checks the envelope the
PRD promises around it - pagination meta, version movement, and the filters that
make a child reachable from any parent id.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ERR_BOOKING_NOT_FOUND,
    ERR_CABIN_CATEGORY_NOT_FOUND,
    ERR_POSTURE_FROZEN,
    ERR_PROMOTION_ALREADY_CLOSED,
    ERR_PROMOTION_NOT_ACTIVE,
    ERR_PROMOTION_NOT_SCHEDULED,
    ERR_UPGRADE_PATH_INVALID,
    GROUP_SALES_AGENT,
    PORT_OPS_COORDINATOR,
    RESERVATION_AGENT,
    REVENUE_MANAGER,
    assert_common_fields,
    assert_capacity_identity,
    assert_two_decimal_pct,
    assert_version_is,
    factories as f,
    fixtures as fx,
    ids_of,
    make_guest_headers,
)

FLAT_FARE_50K = {
    "window_open_days_to_sail": 730,
    "window_close_days_to_sail": 0,
    "base_lower_berth_fare_cents": 50000,
    "third_berth_fare_cents": 20000,
    "fourth_berth_fare_cents": 15000,
}


def test_the_catalogue_reads_back_whole_and_pages_without_loss(api):
    """Create, read one, filter three ways, and split the collection into two pages.

    PRD 2.3: "Every list response carries limit, offset, total_count, and has_more
    inside the envelope's meta object, where total_count is the number of rows matching
    the filters before pagination is applied and has_more indicates whether rows remain
    beyond the current page", and "list results are sorted by created_at ascending."
    PRD 3.9 names the catalogue's filters: "cabin categories by is_guarantee,
    upgrade_to_category_id, and code". PRD 4 opens both reads to every role.

    Design: Corner/endpoints/cabin_category_create_read_list_round_trip
    """
    fx.set_clock(api)
    balcony = validate_success(
        api.create_cabin_category(
            f.cabin_category_payload(
                code="BALCONY",
                tier_rank=3,
                max_occupancy=4,
                onboard_spend_lower_per_night_cents=13000,
                onboard_spend_upper_per_night_cents=8000,
            ),
            REVENUE_MANAGER,
        ),
        201,
    )
    ocean_view = validate_success(
        api.create_cabin_category(
            f.cabin_category_payload(
                code="OV",
                tier_rank=2,
                max_occupancy=4,
                onboard_spend_lower_per_night_cents=11000,
                onboard_spend_upper_per_night_cents=7000,
                upgrade_to_category_id=balcony["id"],
            ),
            REVENUE_MANAGER,
        ),
        201,
    )
    inside = validate_success(
        api.create_cabin_category(
            f.cabin_category_payload(
                code="IA",
                tier_rank=1,
                max_occupancy=4,
                lower_berths=2,
                is_guarantee=True,
                onboard_spend_lower_per_night_cents=9000,
                onboard_spend_upper_per_night_cents=6000,
                upgrade_to_category_id=ocean_view["id"],
            ),
            REVENUE_MANAGER,
        ),
        201,
    )
    for created in (balcony, ocean_view, inside):
        assert_common_fields(created)
        assert_version_is(created, 1)

    # The catalogue is readable by a selling agent, not only by its author.
    read_back = validate_success(api.get_cabin_category(inside["id"], RESERVATION_AGENT))
    assert read_back["code"] == "IA"
    assert read_back["tier_rank"] == 1
    assert read_back["is_guarantee"] is True
    assert read_back["lower_berths"] == 2
    assert read_back["max_occupancy"] == 4
    assert read_back["onboard_spend_lower_per_night_cents"] == 9000
    assert read_back["onboard_spend_upper_per_night_cents"] == 6000
    assert read_back["upgrade_to_category_id"] == ocean_view["id"]
    assert read_back["upgrade_chain_length"] == inside["upgrade_chain_length"]

    reader = fx.make_guest(api, prior_sailings_count=0)
    guarantees, guarantee_meta = validate_paginated(
        api.list_cabin_categories(
            make_guest_headers(reader["id"]), params={"is_guarantee": True}
        )
    )
    assert guarantee_meta["total_count"] == 1
    assert ids_of(guarantees) == [inside["id"]]

    pointing, pointing_meta = validate_paginated(
        api.list_cabin_categories(
            GROUP_SALES_AGENT, params={"upgrade_to_category_id": ocean_view["id"]}
        )
    )
    # The filter matches the edge, not the node it names.
    assert pointing_meta["total_count"] == 1
    assert ids_of(pointing) == [inside["id"]]

    by_code, code_meta = validate_paginated(
        api.list_cabin_categories(PORT_OPS_COORDINATOR, params={"code": "OV"})
    )
    assert code_meta["total_count"] == 1
    assert ids_of(by_code) == [ocean_view["id"]]

    first_page, first_meta = validate_paginated(
        api.list_cabin_categories(REVENUE_MANAGER, params={"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_cabin_categories(REVENUE_MANAGER, params={"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    # The two pages partition the collection: no duplicate and no omission.
    assert ids_of(first_page) + ids_of(second_page) == [
        balcony["id"],
        ocean_view["id"],
        inside["id"],
    ]


def test_one_withdraw_verb_closes_a_scheduled_and_an_active_campaign(api):
    """Both source states take the same edge, and neither reprices what it discounted.

    PRD 3.2: "a RevenueManager pulls a campaign in SCHEDULED or ACTIVE to WITHDRAWN,
    supplying a reason that is stored as withdraw_reason, incrementing version by 1,
    and - importantly - leaving every booking that already quoted the campaign with its
    pinned promo_discount_cents untouched. Withdrawal is not a repricing event.
    Attempting to withdraw a campaign already in EXHAUSTED, EXPIRED, or WITHDRAWN is
    rejected with ERR_PROMOTION_ALREADY_CLOSED." Activation "requires the promotion to
    be in SCHEDULED (otherwise ERR_PROMOTION_NOT_SCHEDULED)", and PRD 3.4 refuses a
    quote of a dead campaign with ERR_PROMOTION_NOT_ACTIVE.

    Design: Corner/endpoints/withdraw_closes_a_promotion_on_both_paths
    """
    world = fx.simple_world(api, clock="2026-08-13T00:00:00Z", voyage_code="WDR-2701")
    early = fx.make_promotion(
        api,
        world.sailing["id"],
        world.sailing["version"],
        code="EARLYBIRD",
        discount_pct=0.15,
        starts_on="2026-08-01T00:00:00Z",
        ends_on="2026-08-05T00:00:00Z",
        max_redemptions=10,
    )
    assert early["status"] == "SCHEDULED"
    early_version = early["version"]

    # Creating the first campaign bumped the sailing, so the guard is re-read.
    bumped = fx.read_sailing(api, world.sailing["id"])
    august = fx.make_promotion(
        api,
        world.sailing["id"],
        bumped["version"],
        code="AUGUSTGA",
        starts_on="2026-08-13T00:00:00Z",
        ends_on="2026-08-20T00:00:00Z",
    )
    activated = fx.activate_promotion(api, august["id"])
    assert activated["status"] == "ACTIVE"

    quoted_pair = fx.guest_with_booking(
        api, world, occupancy_adults=2, promotion_id=august["id"]
    )
    # round(379,990 x 0.10) taken off a 379,990 gross.
    assert quoted_pair.booking["promo_discount_cents"] == 37999
    assert quoted_pair.booking["net_ticket_cents"] == 341991
    # The quote raised redemption_count on the campaign row, and PRD 2.5 increments
    # version "on every mutation of that row ... including mutations that only touch
    # derived fields" - so the withdraw baseline is re-read after the redemption.
    august_version = fx.read_promotion(api, august["id"])["version"]

    withdrawn_early = validate_success(
        api.withdraw_promotion(
            early["id"], {"reason": "CALENDAR_REPLACED"}, REVENUE_MANAGER
        )
    )
    # The SCHEDULED -> WITHDRAWN edge needs no activation first.
    assert withdrawn_early["status"] == "WITHDRAWN"
    assert withdrawn_early["withdraw_reason"] == "CALENDAR_REPLACED"
    assert withdrawn_early["redemption_count"] == 0
    assert_version_is(withdrawn_early, early_version + 1)

    withdrawn_august = validate_success(
        api.withdraw_promotion(
            august["id"], {"reason": "MARGIN_PROTECTION"}, REVENUE_MANAGER
        )
    )
    assert withdrawn_august["status"] == "WITHDRAWN"
    assert withdrawn_august["withdraw_reason"] == "MARGIN_PROTECTION"
    assert withdrawn_august["redemption_count"] == 1
    assert_version_is(withdrawn_august, august_version + 1)

    pinned = fx.read_booking(api, quoted_pair.booking["id"])
    assert pinned["promo_discount_cents"] == 37999
    assert pinned["net_ticket_cents"] == 341991
    # round(341,991 / 5) beats the 25,000-per-guest floor of 50,000.
    assert pinned["deposit_due_cents"] == 68398

    latecomer = fx.make_guest(api, prior_sailings_count=0)
    # The fiscal gate answers first: not a 404 on the promotion and not a 409.
    validate_error(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                latecomer["id"],
                occupancy_adults=2,
                promotion_id=august["id"],
            ),
            RESERVATION_AGENT,
        ),
        ERR_PROMOTION_NOT_ACTIVE,
        422,
    )
    assert fx.read_promotion(api, august["id"])["redemption_count"] == 1
    assert fx.read_guest(api, latecomer["id"])["bookings_count"] == 0

    validate_error(
        api.activate_promotion(august["id"], REVENUE_MANAGER),
        ERR_PROMOTION_NOT_SCHEDULED,
        409,
    )
    validate_error(
        api.withdraw_promotion(
            august["id"], {"reason": "DOUBLE_WITHDRAW"}, REVENUE_MANAGER
        ),
        ERR_PROMOTION_ALREADY_CLOSED,
        409,
    )
    # The first reason stands; the refused second withdrawal wrote nothing.
    assert fx.read_promotion(api, august["id"])["withdraw_reason"] == "MARGIN_PROTECTION"

    _, meta = validate_paginated(
        api.list_promotions(
            REVENUE_MANAGER,
            params={"sailing_id": world.sailing["id"], "status": "WITHDRAWN"},
        )
    )
    assert meta["total_count"] == 2


def test_the_summary_refreshes_the_numbers_and_leaves_the_version_alone(api):
    """Two consecutive summaries agree with each other and with the plain read.

    PRD 2.8: "One read is deliberately exempt: the sailing revenue-summary read
    recomputes the occupancy and revenue chains and returns the refreshed figures, but it
    does not increment the sailing's version." PRD 3.9: "That read is a computed
    read-through: it recomputes occupancy, posture, both RALBD variants,
    compensation_liability_cents, and revenue_alert from current child state and returns
    the refreshed sailing."

    Design: Corner/endpoints/revenue_summary_refreshes_without_bumping_version
    """
    world = fx.simple_world(api, voyage_code="RVS-2701")
    fx.guest_with_booking(api, world, occupancy_adults=2)
    after_booking = fx.read_sailing(api, world.sailing["id"])
    settled_version = after_booking["version"]

    first = validate_success(api.revenue_summary(world.sailing["id"], REVENUE_MANAGER))
    second = validate_success(api.revenue_summary(world.sailing["id"], REVENUE_MANAGER))

    for summary in (first, second):
        assert summary["gross_ticket_revenue_cents"] == 379990
        assert summary["projected_onboard_revenue_cents"] == 126000
        assert summary["compensation_liability_cents"] == 0
        # Nothing is fenced in a group hold, so both bases are 200 x 7.
        assert summary["available_lower_berth_days_gross"] == 1400
        assert summary["available_lower_berth_days_net"] == 1400
        # 505,990 over 1,400 is 361.42...
        assert summary["ralbd_gross_cents"] == 361
        assert summary["ralbd_net_cents"] == 361
        # 361 is strictly below the 20,000-cent floor, read off the net variant.
        assert summary["revenue_alert"] is True
        assert float(summary["occupancy_pct"]) == 1.0
        assert_two_decimal_pct(summary["occupancy_pct"], "occupancy_pct")
        assert summary["lower_berths_sold"] == 2
        assert summary["inventory_posture"] == "OPEN"
        assert summary["confirmed_bookings_count"] == 0
        assert summary["final_payment_risk_flag"] is False
        # The refresh is not a write, unlike the operations sweep.
        assert_version_is(summary, settled_version)

    # A refresh is deterministic rather than incremental.
    assert first == second

    plain = fx.read_sailing(api, world.sailing["id"])
    assert plain["ralbd_gross_cents"] == 361
    assert plain["ralbd_net_cents"] == 361
    assert plain["gross_ticket_revenue_cents"] == 379990
    assert plain["projected_onboard_revenue_cents"] == 126000
    assert_version_is(plain, settled_version)


def test_a_frozen_sailing_turns_a_refusal_into_a_waitlisted_row(api):
    """The posture gate bites while three physical cabins are still free.

    PRD 2.11: "Under FROZEN, group-block creation and promotion activation remain refused
    and booking creation is refused as well - unless the request sets allow_waitlist to
    true, in which case the booking is accepted as a waitlisted one instead", and the
    posture is derived "at 100.00 percent or above ... FROZEN". PRD 2.10 puts the posture
    gate at priority 18 and capacity at 19. PRD 3.4: bookings that are WAITLISTED
    "contribute 0 to the sailing's projected_onboard_revenue_cents."

    Design: Corner/endpoints/a_frozen_sailing_accepts_a_booking_only_as_waitlisted
    """
    world = fx.simple_world(
        api,
        voyage_code="FRZ-2701",
        nights=4,
        total_lower_berths=4,
        category_overrides={"lower_berths": 2},
        physical_cabins=5,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
    )
    fx.guest_with_booking(api, world, occupancy_adults=2)
    fx.guest_with_booking(api, world, occupancy_adults=2)

    frozen = fx.read_sailing(api, world.sailing["id"])
    assert frozen["lower_berths_sold"] == 4
    assert float(frozen["occupancy_pct"]) == 100.0
    # Exactly on the inclusive 100.00 floor.
    assert frozen["inventory_posture"] == "FROZEN"

    fenced = fx.read_inventory(api, world.inventory["id"])
    # Cabins are not the binding constraint: 5 physical, 2 sold.
    assert fenced["booked_cabins"] == 2
    assert fenced["available_cabins"] == 3

    third = fx.make_guest(api, prior_sailings_count=0)
    # Priority 18 answers before priority 19, so this is not ERR_CATEGORY_SOLD_OUT.
    validate_error(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                third["id"],
                occupancy_adults=2,
                allow_waitlist=False,
            ),
            RESERVATION_AGENT,
        ),
        ERR_POSTURE_FROZEN,
        422,
    )

    queued = validate_success(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                third["id"],
                occupancy_adults=2,
                allow_waitlist=True,
            ),
            RESERVATION_AGENT,
        ),
        201,
    )
    assert queued["booking_status"] == "WAITLISTED"
    assert queued["payment_status"] == "AWAITING_DEPOSIT"
    # The refusal and the acceptance carried the same money.
    assert queued["net_ticket_cents"] == 100000
    assert queued["deposit_due_cents"] == 50000
    assert queued["projected_onboard_gross_cents"] == 72000
    assert queued["fare_rule_id"] == world.fare_rule["id"]

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["waitlisted_bookings_count"] == 1
    # A waitlisted booking consumes no cabin.
    assert inventory["booked_cabins"] == 2
    assert inventory["available_cabins"] == 3
    assert_capacity_identity(inventory)

    sailing = fx.read_sailing(api, world.sailing["id"])
    assert sailing["lower_berths_sold"] == 4
    assert float(sailing["occupancy_pct"]) == 100.0
    assert sailing["gross_ticket_revenue_cents"] == 200000
    assert sailing["projected_onboard_revenue_cents"] == 144000
    # (200,000 + 144,000) over 4 berths x 4 nights.
    assert sailing["ralbd_gross_cents"] == 21500
    assert sailing["ralbd_net_cents"] == 21500
    assert sailing["revenue_alert"] is False

    # Only the accepted call counted against the guest.
    assert fx.read_guest(api, third["id"])["bookings_count"] == 1


def test_a_bid_joins_a_booking_to_a_category_only_along_the_upgrade_chain(api):
    """Path id, body id, then reachability - three refusals before the one link.

    PRD 3.7: "The target must be reachable from the booking's current
    assigned_cabin_category_id by following upgrade_to_category_id one or more times; a
    target that is not on that chain, or that sits below the booking's own category, is
    refused with ERR_UPGRADE_PATH_INVALID." The floor "is the fare gap multiplied by 0.40
    (two fifths) and rounded half up, less the onboard uplift divided by guest_count and
    rounded half up", and a new bid "lands in SUBMITTED with counter_rounds at 0,
    guest_count copied from the booking as the award multiplier, submitted_days_to_sail
    stamped from the bid instant ... and countered_min_per_guest_cents,
    award_amount_cents, and decline_reason all null."

    Design: Corner/endpoints/an_upgrade_bid_links_its_booking_to_a_target_category
    """
    clock = "2026-11-26T17:00:00Z"
    fx.set_clock(api, clock)
    spa = fx.make_category(
        api,
        f.cabin_category_payload(
            code="SPA",
            tier_rank=3,
            max_occupancy=4,
            onboard_spend_lower_per_night_cents=12000,
            onboard_spend_upper_per_night_cents=7500,
        ),
    )
    ocean_view = fx.make_category(api, f.ocean_view_category_payload())
    inside = fx.make_category(
        api, f.guarantee_category_payload(upgrade_to_category_id=ocean_view["id"])
    )

    world = fx.simple_world(
        api,
        clock=clock,
        voyage_code="LNK-2701",
        category=inside,
        final_payment_days_before=30,
        physical_cabins=60,
        oversell_allowance=4,
        fare_overrides={
            "window_open_days_to_sail": 730,
            "window_close_days_to_sail": 0,
        },
        open_now=False,
    )
    ov_leg = fx.add_allotment_and_fare(
        api,
        world,
        ocean_view,
        physical_cabins=30,
        oversell_allowance=0,
        fare_overrides={
            "window_open_days_to_sail": 730,
            "window_close_days_to_sail": 0,
            "base_lower_berth_fare_cents": 289995,
            "third_berth_fare_cents": 90000,
            "fourth_berth_fare_cents": 70000,
        },
    )
    fx.add_allotment_and_fare(
        api,
        world,
        spa,
        physical_cabins=10,
        oversell_allowance=0,
        fare_overrides={
            "window_open_days_to_sail": 730,
            "window_close_days_to_sail": 0,
            "base_lower_berth_fare_cents": 249995,
            "third_berth_fare_cents": 80000,
            "fourth_berth_fare_cents": 60000,
        },
    )
    fx.open_sailing(api, world.sailing["id"])

    pair = fx.guest_with_booking(api, world, occupancy_adults=2)
    owner = make_guest_headers(pair.guest["id"])

    # The path id is resolved before anything in the body is looked at.
    validate_error(
        api.submit_upgrade_bid(
            NON_EXISTENT_UUID,
            f.upgrade_bid_payload(ocean_view["id"], 40000),
            owner,
        ),
        ERR_BOOKING_NOT_FOUND,
        404,
    )
    validate_error(
        api.submit_upgrade_bid(
            pair.booking["id"],
            f.upgrade_bid_payload(NON_EXISTENT_UUID, 40000),
            owner,
        ),
        ERR_CABIN_CATEGORY_NOT_FOUND,
        404,
    )
    # SPA has an allotment and a live fare rule, but IA points only at OV.
    validate_error(
        api.submit_upgrade_bid(
            pair.booking["id"], f.upgrade_bid_payload(spa["id"], 40000), owner
        ),
        ERR_UPGRADE_PATH_INVALID,
        422,
    )

    bid = validate_success(
        api.submit_upgrade_bid(
            pair.booking["id"], f.upgrade_bid_payload(ocean_view["id"], 40000), owner
        ),
        201,
    )
    assert bid["status"] == "SUBMITTED"
    assert bid["counter_rounds"] == 0
    assert bid["countered_min_per_guest_cents"] is None
    assert bid["award_amount_cents"] is None
    assert bid["decline_reason"] is None
    # The join is stored on both ends.
    assert bid["booking_id"] == pair.booking["id"]
    assert bid["target_cabin_category_id"] == ocean_view["id"]
    assert bid["guest_count"] == 2
    # 2026-11-26T17:00:00Z is 45 days before the 2027-01-10T17:00:00Z embarkation.
    assert bid["submitted_days_to_sail"] == 45
    # round((289,995 - 189,995) x 0.40) less round(7 x 2 x 1,000 / 2).
    assert bid["min_acceptable_per_guest_cents"] == 33000

    # A bid moves neither a cabin nor the booking's assignment.
    assert fx.read_inventory(api, ov_leg.inventory["id"])["available_cabins"] == 30
    assert (
        fx.read_booking(api, pair.booking["id"])["assigned_cabin_category_id"]
        == inside["id"]
    )

    mine, mine_meta = validate_paginated(
        api.list_upgrade_bids(REVENUE_MANAGER, params={"booking_id": pair.booking["id"]})
    )
    assert mine_meta["total_count"] == 1
    assert ids_of(mine) == [bid["id"]]
    # No refused call was stored.
    _, spa_meta = validate_paginated(
        api.list_upgrade_bids(
            REVENUE_MANAGER, params={"target_cabin_category_id": spa["id"]}
        )
    )
    assert spa_meta["total_count"] == 0


def test_the_sweep_writes_once_when_only_one_of_nine_steps_has_work(api):
    """Eight empty candidate sets, one overdue deposit, and two clean version bumps.

    PRD 3.9: the sweep "executes these nine steps in this fixed order against the current
    logical clock", where step 5 is "Every booking whose deposit or final payment is
    overdue is marked DELINQUENT" and step 6 is "Every booking whose seven-day
    delinquency grace period has elapsed is auto-cancelled". And: "A step whose candidate
    set is empty is a silent no-op, never an error. The sweep increments the sailing's
    version by 1."

    Design: Corner/endpoints/ops_run_steps_with_empty_candidate_sets_are_silent_no_ops
    """
    world = fx.simple_world(
        api,
        voyage_code="NOP-2701",
        nights=4,
        total_lower_berths=40,
        physical_cabins=10,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
    )
    pair = fx.guest_with_booking(api, world, occupancy_adults=2)
    before = fx.read_sailing(api, world.sailing["id"])
    quiet_version = before["version"]

    # The deposit fell due on 2026-08-08; the grace runs out on 2026-08-15.
    fx.set_clock(api, "2026-08-09T00:00:00Z")
    first_run = validate_success(api.ops_run(world.sailing["id"], REVENUE_MANAGER))
    # A sweep is a write even when eight of the nine steps did nothing.
    assert_version_is(first_run, quiet_version + 1)
    assert first_run["id"] == world.sailing["id"]

    delinquent = fx.read_booking(api, pair.booking["id"])
    assert delinquent["payment_status"] == "DELINQUENT"
    # Step 6 did not fire: the seven-day grace has not elapsed.
    assert delinquent["booking_status"] == "OPTION"
    assert delinquent["cancelled_at"] is None

    # Step 8 did not sail the voyage: the clock is far before embarkation.
    assert first_run["status"] == "OPEN_FOR_SALE"
    assert first_run["lower_berths_sold"] == 2
    assert float(first_run["occupancy_pct"]) == 5.0
    assert first_run["inventory_posture"] == "OPEN"
    assert first_run["gross_ticket_revenue_cents"] == 100000
    assert first_run["projected_onboard_revenue_cents"] == 72000
    # (100,000 + 72,000) over 40 berths x 4 nights.
    assert first_run["ralbd_gross_cents"] == 1075
    assert first_run["ralbd_net_cents"] == 1075
    assert first_run["confirmed_bookings_count"] == 0
    # The risk flag needs at least one confirmed booking.
    assert first_run["final_payment_risk_flag"] is False

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["booked_cabins"] == 1
    assert inventory["group_held_cabins"] == 0
    assert inventory["waitlisted_bookings_count"] == 0
    assert inventory["available_cabins"] == 9
    assert_capacity_identity(inventory)

    second_run = validate_success(api.ops_run(world.sailing["id"], REVENUE_MANAGER))
    assert_version_is(second_run, quiet_version + 2)
    # A booking already DELINQUENT is no longer a candidate for step 5.
    unchanged = fx.read_booking(api, pair.booking["id"])
    assert unchanged["payment_status"] == "DELINQUENT"
    assert unchanged["booking_status"] == "OPTION"
    assert unchanged["version"] == delinquent["version"]

    # Marking delinquency posts no money.
    _, ledger_meta = validate_paginated(
        api.list_payment_events(pair.booking["id"], REVENUE_MANAGER)
    )
    assert ledger_meta["total_count"] == 0
