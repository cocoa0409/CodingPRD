"""Livestock sales: booked vs settled pricing, channel branches, holiday
premiums, payment/delivery parallel dimensions, cancel compensation."""
from test_helpers import (
    ApiErrorId,
    create_flock,
    create_holiday_window,
    create_sale,
    create_treatment,
    pay_sale,
    set_clock,
    setup_loaded_sale,
    setup_paid_sale,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSalePricingChannels:

    def test_sale_pricing_channel_branch_with_commission_cap(self, api, ranch_manager_headers):
        """PRD §3.6: "The premium applies only to `ETHNIC_MARKET`".
        PRD §3.6: "The commission applies only to `AUCTION`: 3.5 percent of the
        gross, rounded half-up, but capped at 15,000 cents — the commission is
        the lesser of the two figures. The booked total is gross plus premium
        minus commission."

        Design: Difficulty/combinatorial_formula/sale_pricing_channel_branch_with_commission_cap
        """
        flock = create_flock(flock_name="Auction Ranch", species="SHEEP", baseline_headcount=500)
        create_holiday_window(holiday_name="EID_AL_ADHA",
                              window_start="2026-09-01T00:00:00Z",
                              window_end="2026-09-15T00:00:00Z",
                              premium_pct=22.0, min_head=50)
        sale = create_sale(
            flock["id"], sale_type="MEAT", channel="AUCTION", head_count=100,
            avg_weight_lbs=120.0, base_price_per_cwt_cents=28000,
            scheduled_date="2026-09-05T00:00:00Z")
        # gross = 100 * 120.0 * 1 * 28000 / 100 = 3360000
        # raw commission = round_half_up(3360000 * 3.5 / 100) = 117600 -> capped at 15000
        assert sale["booked_price_cents"] == 3345000, "3360000 - 15000 (capped)"
        # AUCTION suppresses the premium branch despite the in-window date.
        assert sale["premium_pct_applied"] == 0
        assert sale["applied_holiday_name"] is None

    def test_auction_commission_below_cap_not_capped(self, api, ranch_manager_headers):
        """PRD §3.6: "The commission applies only to `AUCTION`: 3.5 percent of
        the gross, rounded half-up, but capped at 15,000 cents — the commission
        is the lesser of the two figures."

        Design: Difficulty/combinatorial_formula/sale_pricing_channel_branch_with_commission_cap
        """
        flock = create_flock(flock_name="Auction2 Ranch", species="SHEEP", baseline_headcount=500)
        sale = create_sale(
            flock["id"], sale_type="MEAT", channel="AUCTION", head_count=10,
            avg_weight_lbs=100.0, base_price_per_cwt_cents=20000,
            scheduled_date="2026-09-05T00:00:00Z")
        # gross = 10 * 100 * 20000 / 100 = 200000; commission = 7000 (below the cap)
        assert sale["booked_price_cents"] == 193000, "200000 - 7000"
        assert sale["premium_pct_applied"] == 0
        assert sale["applied_holiday_name"] is None

    def test_meat_sale_booked_vs_settled_price(self, api, ranch_manager_headers, range_hand_headers):
        """PRD §3.6: "Delivery computes `settled_price_cents`, the settled
        variant of the same pricing pipeline run on actuals: for `MEAT`, the
        gross is recomputed from `actual_total_weight_lbs` in place of the
        booked `head_count`-times-`avg_weight_lbs` figure (shrink, premium, and
        commission rules unchanged)".
        PRD §3.6: "The settled price diverges from `booked_price_cents`
        whenever the actuals differ from the booking."
        PRD §3.6: "Delivery also decrements the flock per the headcount ledger
        of §2.10 — by `head_count` for `MEAT`".

        Design: Difficulty/dual_variant_calc/meat_sale_booked_vs_settled_price
        """
        flock = create_flock(flock_name="DV Meats", species="SHEEP", baseline_headcount=500)
        create_holiday_window(holiday_name="EID_AL_ADHA",
                              window_start="2026-09-01T00:00:00Z",
                              window_end="2026-09-15T00:00:00Z",
                              premium_pct=22.0, min_head=50)
        sale = create_sale(
            flock["id"], sale_type="MEAT", channel="ETHNIC_MARKET", head_count=100,
            avg_weight_lbs=120.0, base_price_per_cwt_cents=28000,
            scheduled_date="2026-09-05T00:00:00Z")
        # booked gross = 100 * 120.0 * 28000 / 100 = 3360000; premium 22% = 739200
        assert sale["booked_price_cents"] == 4099200
        assert sale["applied_holiday_name"] == "EID_AL_ADHA"
        assert sale["premium_pct_applied"] == 22.0

        pay_sale(sale["id"], 4099200)
        validate_success(api.load_sale(sale["id"], range_hand_headers))
        sale = validate_success(api.deliver_sale(
            sale["id"], {"actual_total_weight_lbs": 11700.0}, range_hand_headers))
        # settled gross = 11700.0 * 28000 / 100 = 3276000; premium 22% = 720720
        assert sale["settled_price_cents"] == 3996720
        assert sale["settled_price_cents"] != sale["booked_price_cents"]

        flock = validate_success(api.get_flock(flock["id"], ranch_manager_headers))
        assert flock["current_headcount"] == 400, "500 - 100 delivered MEAT head"

    def test_settled_equal_actuals_matches_booked(self, api, ranch_manager_headers, range_hand_headers):
        """PRD §3.6: "The settled price diverges from `booked_price_cents`
        whenever the actuals differ from the booking." Conversely, when the
        actual scale weight equals head_count * avg_weight_lbs, the settled
        pipeline recomputes the identical gross.

        Design: Difficulty/dual_variant_calc/meat_sale_booked_vs_settled_price
        """
        flock = create_flock(flock_name="DV3 Ranch", species="SHEEP", baseline_headcount=500)
        sale = create_sale(
            flock["id"], sale_type="MEAT", channel="DIRECT", head_count=10,
            avg_weight_lbs=100.0, base_price_per_cwt_cents=20000,
            scheduled_date="2026-09-20T00:00:00Z")
        assert sale["booked_price_cents"] == 200000
        pay_sale(sale["id"], 200000)
        validate_success(api.load_sale(sale["id"], range_hand_headers))
        sale = validate_success(api.deliver_sale(
            sale["id"], {"actual_total_weight_lbs": 1000.0}, range_hand_headers))
        assert sale["settled_price_cents"] == 200000, "actuals equal booking -> same price"


class TestHolidayPremiums:

    def test_holiday_premium_selection_and_volume_gate(self, api, ranch_manager_headers):
        """PRD §3.6: "the system selects the holiday window whose half-open
        interval contains `scheduled_date`, ranking eligible windows by highest
        `premium_pct` first and breaking ties by the earliest `window_start`
        and then the earliest `created_at`".
        PRD §3.6: "When a window applies, `premium_pct_applied` is the window's
        full `premium_pct` when `head_count` reaches the window's `min_head`,
        or half of `premium_pct` when it falls short".

        Design: Corner/calculations/holiday_premium_selection_and_volume_gate
        """
        flock = create_flock(flock_name="Holiday Ranch", species="SHEEP", baseline_headcount=500)
        create_holiday_window(holiday_name="EASTER",
                              window_start="2026-03-20T00:00:00Z",
                              window_end="2026-04-05T00:00:00Z",
                              premium_pct=20.0, min_head=100)
        create_holiday_window(holiday_name="ORTHODOX_EASTER",
                              window_start="2026-04-01T00:00:00Z",
                              window_end="2026-04-12T00:00:00Z",
                              premium_pct=26.0, min_head=200)

        # 2026-04-03 sits inside BOTH windows; the higher premium wins.
        s1 = create_sale(
            flock["id"], sale_type="MEAT", channel="ETHNIC_MARKET", head_count=250,
            avg_weight_lbs=100.0, base_price_per_cwt_cents=20000,
            scheduled_date="2026-04-03T00:00:00Z")
        assert s1["applied_holiday_name"] == "ORTHODOX_EASTER"
        assert s1["premium_pct_applied"] == 26.0, "250 >= min_head 200 -> full premium"
        # gross = 250 * 100 * 20000 / 100 = 5000000; premium = 1300000
        assert s1["booked_price_cents"] == 6300000

        # Same date, below the volume gate -> half premium.
        s2 = create_sale(
            flock["id"], sale_type="MEAT", channel="ETHNIC_MARKET", head_count=150,
            avg_weight_lbs=100.0, base_price_per_cwt_cents=20000,
            scheduled_date="2026-04-03T00:00:00Z")
        assert s2["applied_holiday_name"] == "ORTHODOX_EASTER"
        assert s2["premium_pct_applied"] == 13.0, "150 < min_head 200 -> half premium"
        # gross = 3000000; premium = 390000
        assert s2["booked_price_cents"] == 3390000

    def test_holiday_premium_empty_fallback(self, api, ranch_manager_headers):
        """PRD §3.6: "when no window applies, `premium_pct_applied` is 0 and
        `applied_holiday_name` is null."

        Design: Corner/calculations/holiday_premium_empty_fallback
        """
        flock = create_flock(flock_name="NoWindow Ranch", species="SHEEP", baseline_headcount=500)
        sale = create_sale(
            flock["id"], sale_type="MEAT", channel="ETHNIC_MARKET", head_count=50,
            avg_weight_lbs=100.0, base_price_per_cwt_cents=20000,
            scheduled_date="2026-06-01T00:00:00Z")
        assert sale["booked_price_cents"] == 1000000, "50 * 100 * 20000 / 100, no premium"
        assert sale["premium_pct_applied"] == 0
        assert sale["applied_holiday_name"] is None


class TestPaymentDeliveryDimensions:

    def test_livestock_sale_parallel_payment_delivery_dimensions(self, api, ranch_manager_headers, range_hand_headers):
        """PRD §3.6: "A sale carries two independent state dimensions,
        `payment_status` and `delivery_status`, which evolve separately."
        PRD §3.6: "Loading the truck (`PENDING -> LOADED`, manager or hand)
        requires payment to be `PAID`, else `ERR_SALE_UNPAID` (HTTP 409)."
        PRD §3.6: "for `BREEDING`, it is `actual_head_delivered` multiplied by
        `per_head_price_cents`" and "by `actual_head_delivered` for `BREEDING`".

        Design: Difficulty/non_linear_state_machine/livestock_sale_parallel_payment_delivery_dimensions
        """
        flock = create_flock(flock_name="Boer Goats", species="GOAT", baseline_headcount=500)
        sale = create_sale(
            flock["id"], sale_type="BREEDING", channel="DIRECT", head_count=10,
            per_head_price_cents=45000, scheduled_date="2026-09-05T00:00:00Z")
        assert sale["booked_price_cents"] == 450000, "10 * 45000"
        assert sale["payment_status"] == "UNPAID"
        assert sale["delivery_status"] == "PENDING"

        # Load before payment -> rejected; delivery dimension does not move.
        resp = api.load_sale(sale["id"], range_hand_headers)
        validate_error(resp, ApiErrorId.ERR_SALE_UNPAID.value, expected_status=409)
        sale = validate_success(api.get_livestock_sale(sale["id"], ranch_manager_headers))
        assert sale["delivery_status"] == "PENDING"

        # Payment moves only the payment dimension.
        sale = pay_sale(sale["id"], 450000)
        assert sale["payment_status"] == "PAID"
        assert sale["delivery_status"] == "PENDING", "dimensions evolve independently"

        validate_success(api.load_sale(sale["id"], range_hand_headers))
        sale = validate_success(api.deliver_sale(
            sale["id"], {"actual_head_delivered": 9}, range_hand_headers))
        assert sale["delivery_status"] == "DELIVERED"
        assert sale["settled_price_cents"] == 405000, "9 * 45000"
        assert sale["booked_price_cents"] == 450000

        flock = validate_success(api.get_flock(flock["id"], ranch_manager_headers))
        assert flock["current_headcount"] == 491, "500 - 9 delivered BREEDING head"

    def test_load_gate_and_payment_dimension_independence(self, api, ranch_manager_headers, range_hand_headers):
        """PRD §3.6: "Loading the truck (`PENDING -> LOADED`, manager or hand)
        requires payment to be `PAID`, else `ERR_SALE_UNPAID` (HTTP 409)."
        PRD §3.6: "Payment starts `UNPAID` and moves `UNPAID -> PAID` when the
        manager records a payment whose `amount_cents` equals the
        `booked_price_cents` exactly".

        Design: Difficulty/non_linear_state_machine/livestock_sale_parallel_payment_delivery_dimensions
        """
        flock = create_flock(flock_name="Dims Ranch", species="SHEEP", baseline_headcount=500)
        sale = create_sale(
            flock["id"], sale_type="MEAT", channel="DIRECT", head_count=10,
            avg_weight_lbs=100.0, base_price_per_cwt_cents=20000,
            scheduled_date="2026-09-20T00:00:00Z")
        resp = api.load_sale(sale["id"], range_hand_headers)
        validate_error(resp, ApiErrorId.ERR_SALE_UNPAID.value, expected_status=409)
        sale = pay_sale(sale["id"], sale["booked_price_cents"])
        assert sale["payment_status"] == "PAID"
        assert sale["delivery_status"] == "PENDING"

    def test_sale_payment_amount_mismatch_rejected(self, api, ranch_manager_headers):
        """PRD §3.6: "Payment starts `UNPAID` and moves `UNPAID -> PAID` when
        the manager records a payment whose `amount_cents` equals the
        `booked_price_cents` exactly — any other amount is rejected with
        `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422)".

        Design: Corner/validations/sale_payment_amount_mismatch_rejected
        """
        flock = create_flock(flock_name="Pay Ranch", species="GOAT", baseline_headcount=500)
        sale = create_sale(
            flock["id"], sale_type="BREEDING", channel="DIRECT", head_count=10,
            per_head_price_cents=45000, scheduled_date="2026-09-20T00:00:00Z")
        assert sale["booked_price_cents"] == 450000
        resp = api.record_sale_payment(sale["id"], {"amount_cents": 450001}, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value, expected_status=422)
        sale = validate_success(api.get_livestock_sale(sale["id"], ranch_manager_headers))
        assert sale["payment_status"] == "UNPAID"

    def test_sale_cancel_after_load_rejected(self, api, ranch_manager_headers):
        """PRD §3.6: "Cancelling is allowed only from `PENDING` (`PENDING ->
        CANCELLED`, manager)" and "A cancel attempted after loading, or any
        operation that does not match the current dimension states, is rejected
        with `ERR_SALE_INVALID_STATE`."

        Design: Corner/state_machines/sale_cancel_after_load_rejected
        """
        flock = create_flock(flock_name="Cancel Ranch", species="SHEEP", baseline_headcount=500)
        sale = setup_loaded_sale(
            flock["id"], sale_type="MEAT", channel="DIRECT", head_count=10,
            avg_weight_lbs=100.0, base_price_per_cwt_cents=20000,
            scheduled_date="2026-09-20T00:00:00Z")
        assert sale["delivery_status"] == "LOADED"
        assert sale["payment_status"] == "PAID"
        resp = api.cancel_sale(sale["id"], ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_SALE_INVALID_STATE.value, expected_status=409)
        sale = validate_success(api.get_livestock_sale(sale["id"], ranch_manager_headers))
        assert sale["delivery_status"] == "LOADED"
        assert sale["payment_status"] == "PAID"

    def test_sale_cancel_paid_refunds_compensation(self, api, ranch_manager_headers):
        """PRD §3.6: "when the sale is already `PAID`, cancellation refunds it
        in the same step (`PAID -> REFUNDED`) as compensation."
        PRD §2.10: headcount subtracts "the sum of `head_count` over the
        flock's delivered `MEAT` sales" — a cancelled sale never delivered, so
        no decrement.

        Design: Corner/state_machines/sale_cancel_paid_refunds_compensation
        """
        flock = create_flock(flock_name="Refund Ranch", species="GOAT", baseline_headcount=500)
        sale = setup_paid_sale(
            flock["id"], sale_type="BREEDING", channel="DIRECT", head_count=10,
            per_head_price_cents=45000, scheduled_date="2026-09-20T00:00:00Z")
        sale = validate_success(api.cancel_sale(sale["id"], ranch_manager_headers))
        assert sale["delivery_status"] == "CANCELLED"
        assert sale["payment_status"] == "REFUNDED", "compensation fired in the same step"
        flock = validate_success(api.get_flock(flock["id"], ranch_manager_headers))
        assert flock["current_headcount"] == 500, "no decrement — sale never DELIVERED"


class TestSaleCreationGuards:

    def test_retired_flock_state_beats_withdrawal_safety(self, api, ranch_manager_headers, range_hand_headers):
        """PRD §2.8: "Every request passes through a fixed validation pipeline,
        and the first check that fails determines the error returned — a
        request that would fail several checks surfaces the earliest one, never
        a later one." Flock liveness (item 5, `ERR_FLOCK_RETIRED`) precedes the
        business-safety withdrawal gate (item 7).

        Design: Difficulty/priority_pair_validation_conflict/retired_flock_state_beats_withdrawal_safety
        """
        flock = create_flock(flock_name="Retire Ranch", species="SHEEP", baseline_headcount=500)
        create_treatment(flock["id"], product_name="Ivermectin",
                         treatment_date="2026-08-02T00:00:00Z", withdrawal_days=60,
                         fecal_egg_count_before=300)
        set_clock("2026-08-13T00:00:00Z")
        # No busy children -> retirable despite the live withdrawal gate.
        validate_success(api.retire_flock(flock["id"], ranch_manager_headers))

        # Violates BOTH liveness (flock RETIRED) and the withdrawal gate
        # (2026-08-20 < withdrawal_until 2026-10-01): the earlier layer wins.
        resp = api.create_livestock_sale({
            "flock_id": flock["id"], "sale_type": "MEAT", "channel": "DIRECT",
            "head_count": 10, "avg_weight_lbs": 100.0, "base_price_per_cwt_cents": 20000,
            "scheduled_date": "2026-08-20T00:00:00Z",
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FLOCK_RETIRED.value, expected_status=409)
        _, meta = validate_paginated(
            api.list_livestock_sales(ranch_manager_headers, params={"flock_id": flock["id"]}))
        assert meta["total_count"] == 0, "no sale created for the retired flock"

    def test_retired_flock_beats_withdrawal_second_pairing(self, api, ranch_manager_headers):
        """PRD §2.8: "5. Flock liveness — the target flock is still `ACTIVE`
        when any child record is created under it, else `ERR_FLOCK_RETIRED`."
        precedes "7. Business safety rules — the meat-withdrawal gate".

        Design: Difficulty/priority_pair_validation_conflict/retired_flock_state_beats_withdrawal_safety
        """
        flock = create_flock(flock_name="Retire2 Ranch", species="SHEEP", baseline_headcount=500)
        create_treatment(flock["id"], product_name="Ivermectin",
                         treatment_date="2026-08-02T00:00:00Z", withdrawal_days=60,
                         fecal_egg_count_before=300)
        set_clock("2026-08-13T00:00:00Z")
        validate_success(api.retire_flock(flock["id"], ranch_manager_headers))
        # A BREEDING sale carries no withdrawal gate at all; liveness still fires.
        resp = api.create_livestock_sale({
            "flock_id": flock["id"], "sale_type": "BREEDING", "channel": "DIRECT",
            "head_count": 5, "per_head_price_cents": 60000,
            "scheduled_date": "2026-08-20T00:00:00Z",
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FLOCK_RETIRED.value, expected_status=409)

    def test_sale_missing_required_shape_beats_not_found(self, api, ranch_manager_headers):
        """PRD §2.8: "Request shape — required fields present, enum values
        valid, numeric ranges respected (weights and acres strictly positive,
        head counts and `ewes_bred` at least 1, percentages between 0 and 100
        inclusive), start dates strictly before end dates, and conditional
        field shapes satisfied (a `MEAT` sale carries `avg_weight_lbs` and
        `base_price_per_cwt_cents` and must not carry `per_head_price_cents`,
        while a `BREEDING` sale carries `per_head_price_cents` and must not
        carry the meat pair; a grazing move carries exactly one of
        `pasture_id` or `contract_id`), else `ERR_VALIDATION`."
        PRD §2.8: "Existence — path identifiers resolve left-to-right, then
        body foreign-key references (`flock_id`, `season_id`, `clip_id`,
        `lot_id`, `pasture_id`, `contract_id`, `crew_id`) resolve to existing
        rows, else `ERR_NOT_FOUND`."

        Design: Corner/validations/sale_missing_required_shape_beats_not_found
        """
        resp = api.create_livestock_sale({
            "flock_id": "00000000-0000-0000-0000-000000000000",
            "channel": "DIRECT", "head_count": 5,
            "scheduled_date": "2026-09-20T00:00:00Z",
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=400)

    def test_insufficient_head_on_sale_and_propose_rejected(self, api, ranch_manager_headers):
        """PRD §3.6: "a `head_count` of at least 1 and at most the flock's
        `current_headcount` (otherwise `ERR_INSUFFICIENT_HEAD`, HTTP 422)".
        PRD §3.8: "The manager proposes (`DRAFT -> PROPOSED`), which requires
        the flock's `current_headcount` to be at least `min_head`, else
        `ERR_INSUFFICIENT_HEAD` (HTTP 422)."

        Design: Corner/validations/insufficient_head_on_sale_and_propose_rejected
        """
        from test_helpers import create_contract
        flock = create_flock(flock_name="Short Ranch", species="SHEEP", baseline_headcount=100)
        contract = create_contract(
            flock["id"], client_org_name="Big Client", parcel_name="Meadow 2",
            service_window_start="2026-09-01T00:00:00Z",
            service_window_end="2026-09-30T00:00:00Z",
            rate_per_head_day_cents=90, min_head=150, max_head=600,
            target_cover_reduction_pct=60.0)
        resp = api.create_livestock_sale({
            "flock_id": flock["id"], "sale_type": "MEAT", "channel": "DIRECT",
            "head_count": 150, "avg_weight_lbs": 100.0, "base_price_per_cwt_cents": 20000,
            "scheduled_date": "2026-09-20T00:00:00Z",
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_HEAD.value, expected_status=422)
        resp = api.transition_grazing_contract(
            contract["id"], {"to": "PROPOSED"}, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_HEAD.value, expected_status=422)
        contract = validate_success(api.get_grazing_contract(contract["id"], ranch_manager_headers))
        assert contract["contract_status"] == "DRAFT"
