"""Paying the charity: batch membership, the two fee roundings and the payout gate."""
from test_helpers import (
    ApiErrorId,
    assert_remittance_batch,
    create_charity_payload,
    create_remittance_batch_payload,
    make_charity_admin_headers,
    make_finance_officer_headers,
    new_charity,
    new_donor,
    new_venue,
    read_batch,
    read_charity,
    read_donation,
    read_lot,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    batch_ledger,
    close_batch,
    donation_ledger,
    donation_tasks,
    open_batch,
    sell_lot,
    set_clock,
    setup_closed_batch,
    setup_dropoff_in_custody,
    setup_listed_lot,
    setup_multi_member_batch,
    setup_sold_donation,
)

MEMBER_SALE_PRICES = [19_846, 14_286, 10_836]


class TestFeeRoundingVariants:
    def test_open_batch_reports_the_batch_rounded_provisional_fee(self, api,
                                                                  finance_officer_headers):
        """PRD §3.9: "The **provisional** figure, exposed as `provisional_fee_cents`, uses
        batch rounding: multiply the summed gross by the rate and round that single
        product half up to whole cents. It is recomputed on every read of an `OPEN` batch,
        alongside `gross_cents`, so the officer always sees a live estimate."

        Design: Difficulty/dual_variant_calc/remittance_fee_batch_rounding_vs_per_line_rounding
        """
        bundle = setup_multi_member_batch(MEMBER_SALE_PRICES, remittance_fee_pct=0.10)

        nets = [read_donation(d["id"])["net_to_charity_cents"] for d in bundle["donations"]]
        assert nets == [12_346, 6_786, 3_336]

        batch = validate_success(
            api.get_remittance_batch(bundle["batch"]["id"], finance_officer_headers), 200
        )
        assert_remittance_batch(batch)
        assert batch["status"] == "OPEN"
        assert batch["provisional_fee_cents"] == 2_247, "round_half_up(0.10 x 22468)"

    def test_closing_freezes_the_per_line_rounded_fee(self, api):
        """PRD §3.9: "The **final** figure, written into `fee_cents`, uses per-line
        rounding: multiply each member's `net_to_charity_cents` by the rate, round each of
        those products half up to whole cents, and sum the rounded lines."
        PRD §3.9: "On close the member set is frozen, `donation_count` is written as the
        number of frozen members, `gross_cents` as their summed nets, `fee_cents` as the
        per-line figure, and `net_cents` as the gross less that final fee."

        Design: Difficulty/dual_variant_calc/remittance_fee_batch_rounding_vs_per_line_rounding
        """
        bundle = setup_multi_member_batch(MEMBER_SALE_PRICES, remittance_fee_pct=0.10)
        provisional = read_batch(bundle["batch"]["id"])["provisional_fee_cents"]

        closed = close_batch(bundle["batch"]["id"])

        assert closed["status"] == "CLOSED"
        assert closed["gross_cents"] == 22_468
        assert closed["fee_cents"] == 2_248, "1235 + 679 + 334, each line rounded first"
        assert closed["net_cents"] == 20_220
        assert closed["donation_count"] == 3
        assert closed["fee_cents"] - provisional == 1, (
            "per-line rounding exceeds batch rounding by one cent for this member set"
        )


class TestEmptyBatch:
    def test_closing_a_batch_with_no_eligible_members_is_refused(self, api,
                                                                 finance_officer_headers):
        """PRD §3.9: "Closing requires the batch to be `OPEN`, the affiliate to be
        `ACTIVE`, and the eligible member set to be non-empty — an empty set is refused
        with `ERR_BATCH_EMPTY`."

        Design: Difficulty/boundary_precision_check/close_batch_with_empty_member_set_is_refused
        """
        set_clock("2026-07-10T00:00:00Z")
        charity = new_charity(name="Empty Trust", remittance_fee_pct=0.10)
        batch = open_batch(charity["id"])

        read = validate_success(
            api.get_remittance_batch(batch["id"], finance_officer_headers), 200
        )
        assert read["gross_cents"] == 0
        assert read["provisional_fee_cents"] == 0

        response = api.close_batch(batch["id"], finance_officer_headers)
        validate_error(response, ApiErrorId.ERR_BATCH_EMPTY.value)

    def test_the_refused_close_leaves_the_batch_open_and_unjournalled(
        self, api, finance_officer_headers
    ):
        """PRD §3.9: "On close the member set is frozen, `donation_count` is written as the
        number of frozen members, `gross_cents` as their summed nets, `fee_cents` as the
        per-line figure, and `net_cents` as the gross less that final fee."
        PRD §3.9: "The acting officer's `X-User-ID` is stored in `closed_by_user_id`, and
        the batch moves `OPEN → CLOSED`."

        Design: Difficulty/boundary_precision_check/close_batch_with_empty_member_set_is_refused
        """
        set_clock("2026-07-10T00:00:00Z")
        charity = new_charity(name="Empty Trust", remittance_fee_pct=0.10)
        batch = open_batch(charity["id"])

        refused = api.close_batch(batch["id"], finance_officer_headers)
        validate_error(refused, ApiErrorId.ERR_BATCH_EMPTY.value)

        after = read_batch(batch["id"])
        assert after["status"] == "OPEN"
        assert after["closed_by_user_id"] is None
        entries, meta = validate_paginated(
            api.list_batch_ledger_entries(batch["id"], finance_officer_headers)
        )
        assert entries == [] and meta["total_count"] == 0


class TestMembership:
    def test_membership_window_is_half_open_on_the_sale_instant(self, api,
                                                                finance_officer_headers):
        """PRD §3.9: "A donation is a member when its `charity_id` matches the batch's, its
        `payout_status` is `ACCRUED`, its `net_to_charity_cents` is greater than zero, the
        auction lot for that donation whose `status` is `SOLD` has a `sold_at_utc` falling
        in the half-open window — at or after `period_start_utc` and strictly before
        `period_end_utc` — and the donation is not already frozen into another batch that
        is `CLOSED` or `PAID`."

        Design: Corner/calculations/corner_remittance_membership_excludes_sales_outside_the_period
        """
        set_clock("2026-07-10T00:00:00Z")
        charity = new_charity(name="Window Trust", remittance_fee_pct=0.10)
        donor = new_donor()
        venue = new_venue()
        inside = setup_sold_donation(
            sale_price_cents=60_000, charity=charity, donor=donor, venue=venue
        )
        outside = setup_listed_lot(charity=charity, donor=donor, venue=venue)
        set_clock("2026-08-01T00:00:00Z")
        sell_lot(outside["lot"]["id"], outside["donation"]["id"], 60_000)
        batch = open_batch(charity["id"])

        closed = close_batch(batch["id"])

        assert closed["donation_count"] == 1
        assert closed["gross_cents"] == 48_500
        assert closed["fee_cents"] == 4_850
        assert closed["net_cents"] == 43_650
        entries, _ = validate_paginated(
            api.list_batch_ledger_entries(batch["id"], finance_officer_headers)
        )
        assert len(entries) == 2
        by_type = {entry["entry_type"]: entry["amount_cents"] for entry in entries}
        assert by_type["REMITTANCE_SETTLEMENT"] == 48_500
        assert by_type["CHARITY_FEE_DEBIT"] == 4_850
        assert read_donation(outside["donation"]["id"])["payout_status"] == "ACCRUED"
        assert read_donation(inside["donation"]["id"])["payout_status"] == "ACCRUED"
        assert read_charity(charity["id"])["pledged_balance_cents"] == 97_000

    def test_dispute_and_reopen_unfreeze_the_member_set(self, api, finance_officer_headers):
        """PRD §3.9: "A `CharityAdmin` whose `X-User-ID` equals the batch's `charity_id`
        may dispute a `CLOSED` batch by supplying a `dispute_reason`, moving it
        `CLOSED → DISPUTED` and blocking payment."
        PRD §3.9: "Supplied with a `reason`, it moves the batch `DISPUTED → OPEN`, deletes
        every `REMITTANCE_SETTLEMENT` and `CHARITY_FEE_DEBIT` entry bound to this batch —
        thereby unfreezing the member set, which will be recomputed live from the
        eligibility filter again — and resets `donation_count`, `gross_cents`, `fee_cents`,
        and `net_cents` to 0 and `closed_by_user_id` to empty."

        Design: Corner/state_machines/corner_batch_dispute_and_reopen_cycle_unfreezes_the_member_set
        """
        bundle = setup_closed_batch(sale_price_cents=60_000)
        batch = bundle["batch"]
        assert batch["gross_cents"] == 48_500
        assert batch["fee_cents"] == 4_850
        assert batch["net_cents"] == 43_650
        assert batch["donation_count"] == 1

        disputed = validate_success(
            api.dispute_batch(
                batch["id"],
                {"dispute_reason": "fee schedule disagreement"},
                make_charity_admin_headers(bundle["charity"]["id"]),
            ),
            200,
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason"] == "fee schedule disagreement"

        reopened = validate_success(
            api.reopen_batch(
                batch["id"], {"reason": "renegotiated fee"}, make_finance_officer_headers("fo-alice")
            ),
            200,
        )

        assert reopened["status"] == "OPEN"
        assert reopened["donation_count"] == 0
        assert reopened["fee_cents"] == 0
        assert reopened["net_cents"] == 0
        assert reopened["closed_by_user_id"] is None
        entries, meta = validate_paginated(
            api.list_batch_ledger_entries(batch["id"], finance_officer_headers)
        )
        assert entries == [] and meta["total_count"] == 0
        assert read_donation(bundle["donation"]["id"])["payout_status"] == "ACCRUED"
        assert read_charity(bundle["charity"]["id"])["pledged_balance_cents"] == 48_500


class TestPayout:
    def test_the_officer_who_closed_a_batch_may_not_pay_it(self, api):
        """PRD §3.9: "**Paying** the batch is the segregation-of-duties gate. It requires
        the batch to be `CLOSED`, the acting officer's `X-User-ID` to differ from the
        `closed_by_user_id` recorded at close — the officer who prepared a payout may never
        authorise it, and an attempt is refused with `ERR_SEGREGATION_OF_DUTIES` — and the
        `expected_batch_version` to match."
        PRD §3.9: "Payment then cascades: every member donation moves `ACCRUED → REMITTED`
        on the money axis; for each such donation the affiliate's `pledged_balance_cents`
        falls by that donation's `net_to_charity_cents` while its `remitted_balance_cents`
        rises by that donation's net share — its `net_to_charity_cents` less the per-line
        rounded fee computed for that same donation; and every `REMITTANCE_PENDING`
        follow-up on each of those donations still `OPEN` or `ESCALATED` is marked `DONE`
        with a `resolution_note` of exactly `batch paid`."

        Design: Corner/rbac/corner_same_finance_officer_cannot_close_and_pay_a_batch
        """
        bundle = setup_closed_batch(sale_price_cents=60_000, officer="fo-alice")
        batch = bundle["batch"]
        payload = {"payment_reference": "ACH-1001", "expected_batch_version": batch["version"]}

        refused = api.pay_batch(batch["id"], payload, make_finance_officer_headers("fo-alice"))
        validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        after_refusal = read_batch(batch["id"])
        assert after_refusal["status"] == "CLOSED"
        assert after_refusal["paid_by_user_id"] is None

        paid = validate_success(
            api.pay_batch(batch["id"], payload, make_finance_officer_headers("fo-bob")), 200
        )

        assert paid["status"] == "PAID"
        assert paid["paid_by_user_id"] == "fo-bob"
        assert paid["payment_reference"] == "ACH-1001"
        assert read_donation(bundle["donation"]["id"])["payout_status"] == "REMITTED"
        charity = read_charity(bundle["charity"]["id"])
        assert charity["pledged_balance_cents"] == 0
        assert charity["remitted_balance_cents"] == 43_650

    def test_paying_with_a_pre_close_batch_version_is_refused(self, api):
        """PRD §2.7: "**Paying a remittance batch.** Paying a closed batch requires
        `expected_batch_version` matching the batch's current `version`; a mismatch is
        rejected with `ERR_STALE_BATCH_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/corner_occ_stale_batch_version_on_pay
        """
        set_clock("2026-07-10T00:00:00Z")
        charity = new_charity(name="OCC Batch Trust", remittance_fee_pct=0.10)
        bundle = setup_sold_donation(sale_price_cents=60_000, charity=charity)
        batch = open_batch(charity["id"])
        stale_version = batch["version"]
        closed = close_batch(batch["id"])

        refused = api.pay_batch(
            batch["id"],
            {"payment_reference": "ACH-2001", "expected_batch_version": stale_version},
            make_finance_officer_headers("fo-bob"),
        )
        validate_error(refused, ApiErrorId.ERR_STALE_BATCH_VERSION.value)
        assert read_batch(batch["id"])["status"] == "CLOSED"
        assert read_donation(bundle["donation"]["id"])["payout_status"] == "ACCRUED"

        paid = validate_success(
            api.pay_batch(
                batch["id"],
                {"payment_reference": "ACH-2001", "expected_batch_version": closed["version"]},
                make_finance_officer_headers("fo-bob"),
            ),
            200,
        )
        assert paid["status"] == "PAID"
        charity_after = read_charity(charity["id"])
        assert charity_after["pledged_balance_cents"] == 0
        assert charity_after["remitted_balance_cents"] == 43_650

    def test_pay_response_already_reflects_the_whole_cascade(self, api, finance_officer_headers):
        """PRD §3.9: "Payment then cascades: every member donation moves
        `ACCRUED → REMITTED` on the money axis; for each such donation the affiliate's
        `pledged_balance_cents` falls by that donation's `net_to_charity_cents` while its
        `remitted_balance_cents` rises by that donation's net share — its
        `net_to_charity_cents` less the per-line rounded fee computed for that same
        donation; and every `REMITTANCE_PENDING` follow-up on each of those donations still
        `OPEN` or `ESCALATED` is marked `DONE` with a `resolution_note` of exactly
        `batch paid`."
        PRD §3.9: "The close also journals: one `REMITTANCE_SETTLEMENT` entry is appended
        per member donation with its `remittance_batch_id` bound to this batch, plus a
        single batch-level `CHARITY_FEE_DEBIT` entry carrying no donation and an
        `amount_cents` equal to `fee_cents`."

        Design: Corner/consistency_model/corner_pay_response_reflects_every_cascade_in_the_same_request
        """
        set_clock("2026-07-10T00:00:00Z")
        charity = new_charity(name="Immediate Trust", remittance_fee_pct=0.10)
        bundle = setup_sold_donation(
            sale_price_cents=1_000_000,
            charity=charity,
            reserve_price_cents=100_000,
            intake_channel="PARTNER",
            declared_condition="EXCELLENT",
        )
        batches, _ = validate_paginated(
            api.list_remittance_batches(
                finance_officer_headers, params={"charity_id": charity["id"]}
            )
        )
        assert len(batches) == 1, "the sale crossed the auto-batch threshold"
        closed = close_batch(batches[0]["id"])

        paid = validate_success(
            api.pay_batch(
                batches[0]["id"],
                {"payment_reference": "ACH-3001", "expected_batch_version": closed["version"]},
                make_finance_officer_headers("fo-bob"),
            ),
            200,
        )

        assert paid["status"] == "PAID"
        assert paid["gross_cents"] == 897_500
        assert paid["fee_cents"] == 89_750
        assert paid["net_cents"] == 807_750

        donation = read_donation(bundle["donation"]["id"])
        assert donation["payout_status"] == "REMITTED"
        assert donation["status"] == "SOLD"
        charity_after = read_charity(charity["id"])
        assert charity_after["pledged_balance_cents"] == 0
        assert charity_after["remitted_balance_cents"] == 807_750
        tasks = [
            task
            for task in donation_tasks(bundle["donation"]["id"])
            if task["task_type"] == "REMITTANCE_PENDING"
        ]
        assert tasks and all(task["status"] == "DONE" for task in tasks)
        assert all(task["resolution_note"] == "batch paid" for task in tasks)
        entries = batch_ledger(batches[0]["id"])
        assert len(entries) == 2
        by_type = {entry["entry_type"]: entry["amount_cents"] for entry in entries}
        assert by_type["REMITTANCE_SETTLEMENT"] == 897_500
        assert by_type["CHARITY_FEE_DEBIT"] == 89_750


class TestSettlementImmutability:
    def test_void_sale_after_the_batch_closes_is_refused(self, api, auction_manager_headers,
                                                         finance_officer_headers):
        """PRD §3.7: "A void is refused when any batch that is `CLOSED` or `PAID` already
        holds a `REMITTANCE_SETTLEMENT` entry for that donation."
        PRD §2.8: "**Settlement immutability.** The donation is not frozen into a batch
        whose `status` is `CLOSED` or `PAID` — otherwise `ERR_DONATION_SETTLED` (HTTP 409).
        This guards voiding a sale and withholding a payout."

        Design: Corner/errors/corner_void_sale_after_batch_close_returns_donation_settled
        """
        bundle = setup_closed_batch(sale_price_cents=60_000)

        response = api.void_sale(
            bundle["lot"]["id"], {"void_reason": "buyer defaulted"}, auction_manager_headers
        )

        validate_error(response, ApiErrorId.ERR_DONATION_SETTLED.value)
        assert read_lot(bundle["lot"]["id"])["status"] == "SOLD"
        assert read_donation(bundle["donation"]["id"])["payout_status"] == "ACCRUED"
        assert read_charity(bundle["charity"]["id"])["pledged_balance_cents"] == 48_500
        entries = donation_ledger(bundle["donation"]["id"])
        proceeds_entries = [
            entry for entry in entries if entry["entry_type"] != "REMITTANCE_SETTLEMENT"
        ]
        assert len(proceeds_entries) == 3
        assert all(entry["entry_type"] != "REVERSAL" for entry in entries)


class TestBatchGuards:
    def test_batch_period_ending_before_it_starts_is_refused(self, api, finance_officer_headers):
        """PRD §2.8: "**Interval sanity.** The end of an interval is strictly after its
        start. Pickup-order creation reports `ERR_PICKUP_WINDOW_INVALID`; remittance-batch
        creation reports `ERR_BATCH_PERIOD_INVALID`. Both are HTTP 422."

        Design: Corner/validations/corner_batch_period_with_end_before_start_returns_period_invalid
        """
        charity = new_charity(name="Period Trust", remittance_fee_pct=0.10)

        response = api.create_remittance_batch(
            create_remittance_batch_payload(
                charity["id"],
                period_start_utc="2026-08-01T00:00:00Z",
                period_end_utc="2026-07-01T00:00:00Z",
            ),
            finance_officer_headers,
        )

        validate_error(response, ApiErrorId.ERR_BATCH_PERIOD_INVALID.value)
        rows, meta = validate_paginated(
            api.list_remittance_batches(
                finance_officer_headers, params={"charity_id": charity["id"]}
            )
        )
        assert rows == [] and meta["total_count"] == 0

    def test_remittance_fee_pct_above_the_ceiling_is_refused(self, api, program_admin_headers):
        """PRD §3.1: "The affiliate may optionally declare `remittance_fee_pct`, the
        fraction of a remittance batch's gross that the program retains at payout time;
        when omitted it defaults to 0.10, and any supplied value must be at least 0 and at
        most 0.30, a ceiling the program's board has fixed."
        PRD §2.8: "**Fee range.** The charity's `remittance_fee_pct` is at least 0 and at
        most 0.30 — otherwise `ERR_FEE_PCT_OUT_OF_RANGE` (HTTP 422). This guards charity
        registration."

        Design: Corner/validations/corner_charity_fee_pct_above_the_cap_returns_fee_pct_out_of_range
        """
        over = api.create_charity(
            create_charity_payload(name="Greedy Trust", remittance_fee_pct=0.31),
            program_admin_headers,
        )
        validate_error(over, ApiErrorId.ERR_FEE_PCT_OUT_OF_RANGE.value)

        at_ceiling = validate_success(
            api.create_charity(
                create_charity_payload(name="Capped Trust", remittance_fee_pct=0.30),
                program_admin_headers,
            ),
            201,
        )
        assert at_ceiling["remittance_fee_pct"] == 0.30
        assert at_ceiling["status"] == "ACTIVE"
        assert at_ceiling["pledged_balance_cents"] == 0

    def test_charity_admin_may_not_close_its_own_batch(self, api):
        """PRD §2.1: "When the headers are well-formed but the named role is not among the
        roles authorised for the requested operation (see the endpoint table in §4), the
        request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/corner_charity_admin_cannot_close_a_remittance_batch
        """
        charity = new_charity(name="CA Trust", remittance_fee_pct=0.10)
        batch = open_batch(charity["id"])

        response = api.close_batch(batch["id"], make_charity_admin_headers(charity["id"]))

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
        after = read_batch(batch["id"])
        assert after["status"] == "OPEN"
        assert after["closed_by_user_id"] is None

    def test_batch_payout_and_venue_state_errors_each_name_their_own_entity(
        self, api, program_admin_headers, auction_manager_headers
    ):
        """PRD §3.9: "Any batch act from a state that does not admit it is refused with
        `ERR_INVALID_BATCH_STATE`."
        PRD §3.7: "**Withholding a payout**, supplied with a `reason`, drives the money
        axis to `WITHHELD` and is permitted while `payout_status` is either `PENDING` or
        `ACCRUED`; from any other value it is refused with `ERR_INVALID_PAYOUT_STATE`."
        PRD §3.1: "Venues begin `ACTIVE` and may be moved to `SUSPENDED`, blocking new
        listings, sales, and relists with `ERR_VENUE_SUSPENDED`."

        Design: Corner/errors/corner_batch_and_payout_state_errors_and_suspended_venue
        """
        charity = new_charity(name="Batch State Trust", remittance_fee_pct=0.10)
        suspended_venue = new_venue(name="Closed Yard", venue_type="SALVAGE")
        validate_success(api.suspend_venue(suspended_venue["id"], program_admin_headers), 200)
        bundle = setup_dropoff_in_custody(charity=charity)
        batch = open_batch(charity["id"])

        pay_open = api.pay_batch(
            batch["id"],
            {"payment_reference": "ACH-9001", "expected_batch_version": batch["version"]},
            make_finance_officer_headers("fo-bob"),
        )
        validate_error(pay_open, ApiErrorId.ERR_INVALID_BATCH_STATE.value)
        after = read_batch(batch["id"])
        assert after["status"] == "OPEN"
        assert after["paid_by_user_id"] is None

        withheld = validate_success(
            api.withhold_payout(
                bundle["donation"]["id"],
                {"reason": "donor under investigation"},
                program_admin_headers,
            ),
            200,
        )
        assert withheld["payout_status"] == "WITHHELD"
        second = api.withhold_payout(
            bundle["donation"]["id"],
            {"reason": "still under investigation"},
            program_admin_headers,
        )
        validate_error(second, ApiErrorId.ERR_INVALID_PAYOUT_STATE.value)
        assert donation_ledger(bundle["donation"]["id"]) == [], (
            "nothing had accrued, so withholding moved no money"
        )

        listing = api.create_auction_lot(
            {
                "donation_id": bundle["donation"]["id"],
                "venue_id": suspended_venue["id"],
                "lot_number": "L-BS",
                "reserve_price_cents": 1_000,
            },
            auction_manager_headers,
        )
        validate_error(listing, ApiErrorId.ERR_VENUE_SUSPENDED.value)
        rows, _ = validate_paginated(
            api.list_auction_lots(
                auction_manager_headers, params={"venue_id": suspended_venue["id"]}
            )
        )
        assert rows == []
