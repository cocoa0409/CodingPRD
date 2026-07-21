"""The sale floor: listing, capacity, the title gate and check ordering."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_auction_lot,
    create_auction_lot_payload,
    new_charity,
    new_donor,
    new_venue,
    read_charity,
    read_donation,
    read_lot,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    donation_version,
    new_lot,
    read_title,
    reject_title,
    set_clock,
    setup_dropoff_in_custody,
    setup_listed_lot,
    setup_sold_donation,
)


class TestVenueDailyCapacity:
    def test_sixth_lot_on_the_same_calendar_day_is_refused(self, api, auction_manager_headers):
        """PRD §3.6: "Venues also have a physical constraint on how many cars they can put
        through the block in a day: a venue may host at most five lots whose listing
        instant falls on the same UTC calendar day — the day running from midnight
        inclusive to the next midnight exclusive — as the current logical clock, counting
        only lots whose `status` is not `WITHDRAWN`. A sixth is refused with
        `ERR_VENUE_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/venue_daily_lot_capacity_is_a_calendar_day_bucket
        """
        set_clock("2026-07-10T08:00:00Z")
        charity = new_charity()
        donor = new_donor()
        venue = new_venue()
        for _ in range(5):
            bundle = setup_dropoff_in_custody(
                charity=charity, donor=donor, declared_condition="FAIR"
            )
            new_lot(bundle["donation"]["id"], venue["id"], reserve_price_cents=10_000)
        sixth = setup_dropoff_in_custody(charity=charity, donor=donor, declared_condition="FAIR")

        response = api.create_auction_lot(
            create_auction_lot_payload(
                sixth["donation"]["id"], venue["id"], reserve_price_cents=10_000
            ),
            auction_manager_headers,
        )

        validate_error(response, ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED.value)
        rows, _ = validate_paginated(
            api.list_auction_lots(auction_manager_headers, params={"venue_id": venue["id"]})
        )
        assert len(rows) == 5
        assert read_donation(sixth["donation"]["id"])["status"] == "IN_CUSTODY"

    def test_the_same_listing_is_accepted_once_the_clock_reaches_the_next_day(
        self, api, auction_manager_headers
    ):
        """PRD §3.6: "Venues also have a physical constraint on how many cars they can put
        through the block in a day: a venue may host at most five lots whose listing
        instant falls on the same UTC calendar day — the day running from midnight
        inclusive to the next midnight exclusive — as the current logical clock, counting
        only lots whose `status` is not `WITHDRAWN`. A sixth is refused with
        `ERR_VENUE_CAPACITY_EXCEEDED`."
        PRD §3.6: "A new lot opens in `status` of `LISTED` with `listed_at_utc` stamped
        from the logical clock, `relist_count` at 0, and `sale_price_cents`, `sold_at_utc`,
        and `void_reason` all empty."

        Design: Difficulty/resource_temporal_overlap/venue_daily_lot_capacity_is_a_calendar_day_bucket
        """
        set_clock("2026-07-10T08:00:00Z")
        charity = new_charity()
        donor = new_donor()
        venue = new_venue()
        for _ in range(5):
            bundle = setup_dropoff_in_custody(
                charity=charity, donor=donor, declared_condition="FAIR"
            )
            new_lot(bundle["donation"]["id"], venue["id"], reserve_price_cents=10_000)
        sixth = setup_dropoff_in_custody(charity=charity, donor=donor, declared_condition="FAIR")
        refused = api.create_auction_lot(
            create_auction_lot_payload(
                sixth["donation"]["id"], venue["id"], reserve_price_cents=10_000
            ),
            auction_manager_headers,
        )
        validate_error(refused, ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED.value)

        set_clock("2026-07-11T00:00:00Z")
        accepted = validate_success(
            api.create_auction_lot(
                create_auction_lot_payload(
                    sixth["donation"]["id"], venue["id"], reserve_price_cents=10_000
                ),
                auction_manager_headers,
            ),
            201,
        )

        assert_auction_lot(accepted)
        assert accepted["status"] == "LISTED"
        assert accepted["listed_at_utc"].startswith("2026-07-11T00:00:00")
        assert accepted["relist_count"] == 0
        rows, _ = validate_paginated(
            api.list_auction_lots(auction_manager_headers, params={"venue_id": venue["id"]})
        )
        assert len(rows) == 6
        assert read_donation(sixth["donation"]["id"])["status"] == "IN_CUSTODY"


class TestCheckOrderingOnRecordSale:
    def test_state_check_beats_the_reserve_price_check(self, api, auction_manager_headers):
        """PRD §2.8: "Checks are evaluated in the fixed order below, and the **first**
        check that fails determines the response; later checks are not evaluated at all."
        PRD §2.8: "The practical consequence worth internalising: a suspended venue
        surfaces before a missing title, a missing title surfaces before an unmet reserve,
        and a stale version surfaces before any state check at all."

        Design: Difficulty/priority_pair_validation_conflict/lot_state_error_beats_reserve_price_fiscal_error
        """
        bundle = setup_sold_donation(sale_price_cents=120_000, reserve_price_cents=50_000)

        response = api.record_sale(
            bundle["lot"]["id"],
            {
                "sale_price_cents": 100,
                "expected_donation_version": donation_version(bundle["donation"]["id"]),
            },
            auction_manager_headers,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_LOT_STATE.value)

    def test_the_refused_second_sale_changes_no_money(self, api, auction_manager_headers):
        """PRD §3.6: "Any of these acts against a lot in a state that does not admit it is
        refused with `ERR_INVALID_LOT_STATE`; where the donation's own disposition is the
        obstacle, the refusal is `ERR_INVALID_DONATION_STATE`."
        PRD §3.7: "*Step four — the charity's net.* From the provisional balance subtract
        the tow allowance and subtract a flat administrative fee of twenty-five dollars
        (two thousand five hundred cents)."

        Design: Difficulty/priority_pair_validation_conflict/lot_state_error_beats_reserve_price_fiscal_error
        """
        bundle = setup_sold_donation(sale_price_cents=120_000, reserve_price_cents=50_000)

        refused = api.record_sale(
            bundle["lot"]["id"],
            {
                "sale_price_cents": 100,
                "expected_donation_version": donation_version(bundle["donation"]["id"]),
            },
            auction_manager_headers,
        )
        validate_error(refused, ApiErrorId.ERR_INVALID_LOT_STATE.value)

        lot = read_lot(bundle["lot"]["id"])
        assert lot["status"] == "SOLD"
        assert lot["sale_price_cents"] == 120_000
        donation = read_donation(bundle["donation"]["id"])
        assert donation["gross_proceeds_cents"] == 120_000
        assert donation["net_to_charity_cents"] == 103_100
        assert read_charity(bundle["charity"]["id"])["pledged_balance_cents"] == 103_100, (
            "the refused call books no second accrual"
        )


class TestTitleGateOnRecordSale:
    def test_sale_is_refused_while_the_title_is_rejected(self, api, auction_manager_headers):
        """PRD §3.6: "The sale is permitted only when the lot is `LISTED`, the venue is
        `ACTIVE`, a title record exists for the donation with `state` of `CLEARED`
        (otherwise `ERR_TITLE_NOT_CLEARED`), the donation is `IN_CUSTODY`, the echoed
        version matches, and the hammer price is at least the lot's `reserve_price_cents`
        (otherwise `ERR_RESERVE_NOT_MET`)."

        Design: Difficulty/cross_entity_state_dependency/lot_sale_blocked_until_title_record_reaches_cleared
        """
        bundle = setup_dropoff_in_custody()
        title = reject_title(bundle["donation"]["id"], reason="owner name mismatch")
        venue = new_venue()
        lot = new_lot(bundle["donation"]["id"], venue["id"], reserve_price_cents=10_000)
        version_before = donation_version(bundle["donation"]["id"])

        response = api.record_sale(
            lot["id"],
            {"sale_price_cents": 60_000, "expected_donation_version": version_before},
            auction_manager_headers,
        )

        validate_error(response, ApiErrorId.ERR_TITLE_NOT_CLEARED.value)
        assert read_lot(lot["id"])["status"] == "LISTED"
        donation = read_donation(bundle["donation"]["id"])
        assert donation["status"] == "IN_CUSTODY"
        assert donation["version"] == version_before, "the refused sale mutates nothing"
        assert read_title(title["id"])["state"] == "REJECTED"

    def test_the_identical_sale_succeeds_once_the_title_clears(self, api, auction_manager_headers):
        """PRD §2.8: "A title record exists for the donation and its `state` is `CLEARED` —
        otherwise `ERR_TITLE_NOT_CLEARED` (HTTP 409). This guards sale recording, receipt
        drafting, and receipt issue."
        PRD §3.6: "The lot moves `LISTED → SOLD` with `sale_price_cents` and `sold_at_utc`
        recorded, the donation moves `IN_CUSTODY → SOLD`, and the proceeds waterfall of
        §3.7 runs."

        Design: Difficulty/cross_entity_state_dependency/lot_sale_blocked_until_title_record_reaches_cleared
        """
        bundle = setup_dropoff_in_custody()
        title = reject_title(bundle["donation"]["id"], reason="owner name mismatch")
        venue = new_venue()
        lot = new_lot(bundle["donation"]["id"], venue["id"], reserve_price_cents=10_000)
        version_before = donation_version(bundle["donation"]["id"])
        refused = api.record_sale(
            lot["id"],
            {"sale_price_cents": 60_000, "expected_donation_version": version_before},
            auction_manager_headers,
        )
        validate_error(refused, ApiErrorId.ERR_TITLE_NOT_CLEARED.value)

        clerk = TEST_USERS["title_clerk_headers"]
        validate_success(api.resubmit_title(title["id"], {"owner_name": "Cro Ss"}, clerk), 200)
        cleared = validate_success(
            api.record_dmv_decision(title["id"], {"outcome": "CLEARED"}, clerk), 200
        )
        assert cleared["state"] == "CLEARED"
        assert cleared["rejection_count"] == 1

        sold = validate_success(
            api.record_sale(
                lot["id"],
                {"sale_price_cents": 60_000, "expected_donation_version": version_before},
                auction_manager_headers,
            ),
            200,
        )

        assert sold["status"] == "SOLD"
        donation = read_donation(bundle["donation"]["id"])
        assert donation["gross_proceeds_cents"] == 60_000
        assert donation["net_to_charity_cents"] == 48_500
        assert read_charity(bundle["charity"]["id"])["pledged_balance_cents"] == 48_500


class TestLotLifecycle:
    def test_relist_returns_a_no_sale_lot_to_the_block(self, api, auction_manager_headers):
        """PRD §3.6: "**Recording a no-sale.** When the block passes on a lot, the manager
        records the outcome with an optional `reason`. The lot moves `LISTED → NO_SALE`
        and the donation moves `IN_CUSTODY → UNSOLD`. Nothing financial happens: the
        donation's `payout_status` stays `PENDING` and `relist_count` is unchanged."
        PRD §3.6: "The lot moves back to `LISTED`, `listed_at_utc` is restamped from the
        logical clock, `relist_count` rises by one, and the donation moves
        `UNSOLD → IN_CUSTODY`."

        Design: Corner/state_machines/corner_relist_cycle_returns_no_sale_lot_to_listed
        """
        set_clock("2026-07-10T08:00:00Z")
        bundle = setup_listed_lot(
            reserve_price_cents=90_000, clear_the_title=False, declared_condition="FAIR"
        )
        no_sale = validate_success(
            api.record_no_sale(bundle["lot"]["id"], {"reason": "reserve not met"},
                               auction_manager_headers),
            200,
        )
        assert no_sale["status"] == "NO_SALE"
        assert read_donation(bundle["donation"]["id"])["status"] == "UNSOLD"

        set_clock("2026-07-11T08:00:00Z")
        relisted = validate_success(
            api.relist_lot(
                bundle["lot"]["id"], {"reserve_price_cents": 40_000}, auction_manager_headers
            ),
            200,
        )

        assert relisted["status"] == "LISTED"
        assert relisted["relist_count"] == 1
        assert relisted["reserve_price_cents"] == 40_000
        assert relisted["listed_at_utc"].startswith("2026-07-11T08:00:00")
        donation = read_donation(bundle["donation"]["id"])
        assert donation["status"] == "IN_CUSTODY"
        assert donation["payout_status"] == "PENDING"

    def test_stale_donation_version_blocks_recording_a_sale(self, api, auction_manager_headers,
                                                            program_admin_headers):
        """PRD §2.7: "**Recording a sale.** Recording the hammer price on an auction lot
        likewise requires `expected_donation_version` matching the donation's current
        `version`, and a mismatch is rejected with `ERR_STALE_DONATION_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/corner_occ_stale_donation_version_on_record_sale
        """
        bundle = setup_listed_lot(with_vehicle=True)
        stale_version = donation_version(bundle["donation"]["id"])
        validate_success(
            api.record_exception(
                bundle["donation"]["id"], {"exception_type": "SIGNIFICANT_USE"},
                program_admin_headers,
            ),
            200,
        )

        refused = api.record_sale(
            bundle["lot"]["id"],
            {"sale_price_cents": 60_000, "expected_donation_version": stale_version},
            auction_manager_headers,
        )
        validate_error(refused, ApiErrorId.ERR_STALE_DONATION_VERSION.value)
        assert read_lot(bundle["lot"]["id"])["status"] == "LISTED"
        assert read_charity(bundle["charity"]["id"])["pledged_balance_cents"] == 0

        fresh_version = donation_version(bundle["donation"]["id"])
        sold = validate_success(
            api.record_sale(
                bundle["lot"]["id"],
                {"sale_price_cents": 60_000, "expected_donation_version": fresh_version},
                auction_manager_headers,
            ),
            200,
        )
        assert sold["status"] == "SOLD"
        donation = read_donation(bundle["donation"]["id"])
        assert donation["exception_type"] == "SIGNIFICANT_USE"
        assert donation["net_to_charity_cents"] == 48_500

    def test_logical_clock_reads_the_declared_default_before_any_administrator_moves_it(
        self, api, auction_manager_headers, program_admin_headers
    ):
        """PRD §2.5: "It maintains a **logical clock** whose value is exactly
        `2026-07-01T00:00:00Z` until an administrator moves it, and which never falls back
        to real time. An administrator moves the clock by supplying a `to_iso8601` instant
        to the clock-setting capability, which answers with the resulting `current_utc`
        value."

        Design: Corner/endpoints/corner_logical_clock_defaults_to_2026_07_01_before_any_set
        """
        bundle = setup_dropoff_in_custody()
        venue = new_venue()

        lot = validate_success(
            api.create_auction_lot(
                create_auction_lot_payload(
                    bundle["donation"]["id"], venue["id"], reserve_price_cents=10_000
                ),
                auction_manager_headers,
            ),
            201,
        )
        assert lot["listed_at_utc"].startswith("2026-07-01T00:00:00"), (
            "the clock reads exactly 2026-07-01T00:00:00Z until an administrator moves it"
        )

        moved = validate_success(
            api.set_clock("2026-09-01T00:00:00Z", program_admin_headers), 200
        )
        assert moved["current_utc"].startswith("2026-09-01T00:00:00")
        assert read_lot(lot["id"])["listed_at_utc"].startswith("2026-07-01T00:00:00"), (
            "moving the clock does not restamp an existing listing instant"
        )
