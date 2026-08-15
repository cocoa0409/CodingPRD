"""Short-dated stock credits: tiered valuation, adjudication, sweeps
(PRD §3.9, §2.4)."""
from test_helpers import (
    OFFICER,
    ApiErrorId,
    assert_short_date_credit,
    create_active_clinic,
    create_approved_order,
    create_delivered_line,
    create_lot,
    create_product,
    create_short_date_credit,
    get_short_date_credit,
    get_success_data,
    make_clinic_buyer_headers,
    set_clock,
    ship_and_deliver,
    sole_line,
    validate_error,
    validate_success,
)


def _delivered_line(api, *, lot_expiry, unit_price=999, qty=1, lot_qty=5,
                    window_start="2026-08-03T13:00:00Z",
                    window_end="2026-08-03T15:00:00Z",
                    clinic_name="Clinic SDC", license_number="LIC-SDC"):
    return create_delivered_line(
        unit_price=unit_price, qty=qty, lot_qty=lot_qty, lot_expiry=lot_expiry,
        window_start=window_start, window_end=window_end,
        clinic_overrides={"clinic_name": clinic_name,
                          "license_number": license_number,
                          # Low minimum keeps 999-cent lines submittable; the
                          # minimum-order gate is not what these tests exercise.
                          "minimum_order_value_cents": 500,
                          "free_freight_threshold_cents": 75000})


class TestClaimedVsFinalVariants:
    def test_short_date_credit_claimed_variant_at_request(self, api):
        """PRD §3.9: "Eligibility turns on `days_to_expiry_at_request`, computed
        as the lot's `expiry_date` minus the current clock date in whole
        days..."
        PRD §3.9: "The claimed amount uses a tiered per-unit rate keyed to
        `days_to_expiry_at_request`: thirty days or fewer to expiry earns full
        credit — one hundred percent of the line's snapshotted
        `unit_price_cents`; thirty-one to ninety days earns half; ninety-one to
        one hundred eighty days earns a quarter."
        PRD §3.9: "The credit record derives its `clinic_id` from the line's
        order, starts in `REQUESTED`, and computes its `claimed_credit_cents`
        immediately."

        Design: Difficulty/dual_variant_calc/short_date_credit_claimed_vs_final
        """
        ctx = _delivered_line(api, lot_expiry="2026-10-25", qty=3, lot_qty=10,
                              clinic_name="Clinic S", license_number="LIC-S1")
        set_clock("2026-09-20T00:00:00Z")

        credit = create_short_date_credit(ctx["clinic"]["id"], ctx["line"]["id"],
                                          ctx["lot"]["id"], 3)
        assert_short_date_credit(credit)
        # 2026-10-25 minus 2026-09-20 = 35 days -> half-credit tier.
        assert credit["days_to_expiry_at_request"] == 35
        assert credit["claimed_credit_cents"] == 1500, (
            "round_half_up(999 * 0.5) = 500 per unit, * 3 units")
        assert credit["status"] == "REQUESTED"
        assert credit["clinic_id"] == ctx["clinic"]["id"]
        assert credit["final_credit_cents"] is None

    def test_short_date_credit_final_variant_retiers_at_receipt(self, api):
        """PRD §3.9: "Finalization re-evaluates the tier at the receipt clock
        date: the days-to-expiry figure is recomputed against the lot's
        `expiry_date`, the per-unit rate re-selected from the same three tiers,
        and `final_credit_cents` computed as the per-unit credit rounded half up
        to whole cents, multiplied by `received_qty`."
        PRD §3.9: "The credit then moves to its terminal `CREDITED` state..."
        PRD §3.9: "Claimed and final amounts diverge whenever the receipt-date
        tier differs from the request-date tier or fewer units come back than
        were claimed."

        Design: Difficulty/dual_variant_calc/short_date_credit_claimed_vs_final
        """
        ctx = _delivered_line(api, lot_expiry="2026-10-25", qty=3, lot_qty=10,
                              clinic_name="Clinic SF", license_number="LIC-SF")
        set_clock("2026-09-20T00:00:00Z")
        credit = create_short_date_credit(ctx["clinic"]["id"], ctx["line"]["id"],
                                          ctx["lot"]["id"], 3)
        assert credit["claimed_credit_cents"] == 1500  # 35 days -> 50%
        get_success_data(api.approve_short_date_credit(credit["id"], OFFICER))

        # Receipt at 2026-10-10: 15 days to expiry -> full-credit tier.
        set_clock("2026-10-10T00:00:00Z")
        finalized = validate_success(
            api.finalize_short_date_credit(credit["id"], 3, OFFICER))
        assert finalized["status"] == "CREDITED"
        assert finalized["final_credit_cents"] == 2997, (
            "round_half_up(999 * 1.0) = 999 per unit, * 3 received")
        assert finalized["final_credit_cents"] != finalized["claimed_credit_cents"], (
            "The receipt-date tier (100%) differs from the request-date tier (50%)")


class TestPerUnitRoundingOrder:
    def test_per_unit_rounding_qty_three(self, api):
        """PRD §3.9: "The per-unit credit — the snapshot price multiplied by the
        tier rate — is rounded half up to whole cents first and only then
        multiplied by `qty` to produce `claimed_credit_cents`; rounding after
        multiplying is the forbidden alternative. By way of example, a 999-cent
        unit at the half-credit tier with a quantity of three credits 500 cents
        per unit for a 1,500-cent total — not 1,499, which is what rounding the
        un-rounded product would give."

        Design: Difficulty/combinatorial_formula/short_date_credit_per_unit_rounding
        """
        ctx = _delivered_line(api, lot_expiry="2026-10-25", qty=3, lot_qty=10,
                              clinic_name="Clinic R2", license_number="LIC-R2")
        set_clock("2026-09-20T00:00:00Z")

        credit = create_short_date_credit(ctx["clinic"]["id"], ctx["line"]["id"],
                                          ctx["lot"]["id"], 3)
        assert credit["days_to_expiry_at_request"] == 35
        assert credit["claimed_credit_cents"] == 1500, (
            "Per-unit first: round_half_up(499.5) = 500, then * 3 = 1500; "
            "sum-then-round would give 1499")

    def test_per_unit_rounding_qty_two(self, api):
        """PRD §3.9: "The per-unit credit — the snapshot price multiplied by the
        tier rate — is rounded half up to whole cents first and only then
        multiplied by `qty` to produce `claimed_credit_cents`; rounding after
        multiplying is the forbidden alternative."

        Design: Difficulty/combinatorial_formula/short_date_credit_per_unit_rounding
        """
        ctx = _delivered_line(api, lot_expiry="2026-10-25", qty=2, lot_qty=10,
                              clinic_name="Clinic R3", license_number="LIC-R3")
        set_clock("2026-09-20T00:00:00Z")

        credit = create_short_date_credit(ctx["clinic"]["id"], ctx["line"]["id"],
                                          ctx["lot"]["id"], 2)
        assert credit["claimed_credit_cents"] == 1000, (
            "500 per unit * 2 = 1000; sum-then-round of 999 would give 999")


class TestShortDateWindowBoundary:
    def test_181_days_to_expiry_rejected_not_short_dated(self, api):
        """PRD §3.9: "Eligibility turns on `days_to_expiry_at_request`, computed
        as the lot's `expiry_date` minus the current clock date in whole days: a
        line whose lot still has more than 180 days to run is not short-dated at
        all and is rejected with `ERR_NOT_SHORT_DATED`, while exactly 180 days
        is eligible."

        Design: Difficulty/boundary_precision_check/short_date_window_180_day_boundary
        """
        ctx = _delivered_line(api, lot_expiry="2027-02-07", lot_qty=1,
                              clinic_name="Clinic D181", license_number="LIC-D181")
        set_clock("2026-08-10T00:00:00Z")
        # 2027-02-07 minus 2026-08-10 = 181 days.
        resp = api.create_short_date_credit(
            {"order_line_id": ctx["line"]["id"], "lot_id": ctx["lot"]["id"],
             "qty": 1},
            make_clinic_buyer_headers(ctx["clinic"]["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_SHORT_DATED)

    def test_180_days_to_expiry_eligible_at_quarter_tier(self, api):
        """PRD §3.9: "...a line whose lot still has more than 180 days to run is
        not short-dated at all and is rejected with `ERR_NOT_SHORT_DATED`, while
        exactly 180 days is eligible."
        PRD §3.9: "thirty days or fewer to expiry earns full credit — one
        hundred percent of the line's snapshotted `unit_price_cents`;
        thirty-one to ninety days earns half; ninety-one to one hundred eighty
        days earns a quarter."

        Design: Difficulty/boundary_precision_check/short_date_window_180_day_boundary
        """
        ctx = _delivered_line(api, lot_expiry="2027-02-06", lot_qty=1,
                              clinic_name="Clinic D180", license_number="LIC-D180")
        set_clock("2026-08-10T00:00:00Z")
        # 2027-02-06 minus 2026-08-10 = exactly 180 days -> eligible, 25% tier.
        credit = create_short_date_credit(ctx["clinic"]["id"], ctx["line"]["id"],
                                          ctx["lot"]["id"], 1)
        assert credit["days_to_expiry_at_request"] == 180
        assert credit["claimed_credit_cents"] == 250, (
            "round_half_up(999 * 0.25) = 250 per unit, * 1")
        assert credit["status"] == "REQUESTED"


class TestCreditCreateStructuralGates:
    def test_lot_line_mismatch_and_undelivered_line(self, api):
        """PRD §3.9: "The line must be `DELIVERED` — requesting against a line
        in any other state fails with `ERR_ORDER_LINE_INVALID_STATE` — and the
        named lot must be the very lot that covered the line, otherwise
        `ERR_LOT_LINE_MISMATCH`."

        Design: Corner/validations/short_date_credit_lot_line_mismatch_and_undelivered_line
        """
        clinic = create_active_clinic(clinic_name="Clinic MM",
                                      license_number="LIC-MM",
                                      ship_to_address="50 Match Mews",
                                      minimum_order_value_cents=500)
        product = create_product(sku="CONS-MM", product_name="Gauze 4x4",
                                 unit_price_cents=999)
        lot_a = create_lot(product["id"], lot_number="LOT-MM-A",
                           expiry_date="2027-02-06", qty_on_hand=1)
        lot_b = create_lot(product["id"], lot_number="LOT-MM-B",
                           expiry_date="2027-02-06", qty_on_hand=5)
        order1 = create_approved_order(
            clinic["id"], product["id"], 1,
            window_start="2026-08-03T13:00:00Z",
            window_end="2026-08-03T15:00:00Z")
        ship_and_deliver(order1["id"])
        # Lot A is drained by order 1; order 2 allocates from lot B and stays
        # APPROVED (never shipped, so its line is ALLOCATED, not DELIVERED).
        order2 = create_approved_order(
            clinic["id"], product["id"], 1,
            window_start="2026-08-04T13:00:00Z",
            window_end="2026-08-04T15:00:00Z")
        assert order2["status"] == "APPROVED"
        line1 = sole_line(order1["id"])
        line2 = sole_line(order2["id"])
        assert line1["lot_id"] == lot_a["id"], (
            "FEFO tie-break by earliest created_at assigns the first lot")
        assert line2["lot_id"] == lot_b["id"]

        set_clock("2026-08-10T00:00:00Z")

        # Delivered line but the WRONG lot (lot B did not cover line 1).
        resp = api.create_short_date_credit(
            {"order_line_id": line1["id"], "lot_id": lot_b["id"], "qty": 1},
            make_clinic_buyer_headers(clinic["id"]))
        validate_error(resp, ApiErrorId.ERR_LOT_LINE_MISMATCH)

        # The right lot for line 2, but line 2 was never delivered.
        resp = api.create_short_date_credit(
            {"order_line_id": line2["id"], "lot_id": lot_b["id"], "qty": 1},
            make_clinic_buyer_headers(clinic["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_LINE_INVALID_STATE)


class TestCreditAdjudication:
    def _requested_credit(self, api, *, qty=2, clinic_name="Clinic RQ",
                          license_number="LIC-RQ"):
        ctx = _delivered_line(api, lot_expiry="2027-02-06", qty=qty, lot_qty=5,
                              clinic_name=clinic_name, license_number=license_number)
        set_clock("2026-08-10T00:00:00Z")
        credit = create_short_date_credit(ctx["clinic"]["id"], ctx["line"]["id"],
                                          ctx["lot"]["id"], qty)
        return ctx, credit

    def test_finalize_received_qty_exceeds_claimed(self, api):
        """PRD §3.9: "Once the returned goods physically arrive, the officer
        finalizes an `APPROVED` credit by supplying the `received_qty`, which
        must fall between one and the originally claimed `qty` inclusive — a
        count outside that band is rejected with
        `ERR_RECEIVED_QTY_EXCEEDS_CLAIMED`."
        PRD §3.9: "Finalization re-evaluates the tier at the receipt clock
        date..."

        Design: Corner/validations/finalize_received_qty_exceeds_claimed
        """
        _ctx, credit = self._requested_credit(api, qty=2)
        assert credit["claimed_credit_cents"] == 500, (
            "180 days -> 25% tier: round_half_up(999*0.25) = 250 per unit, * 2")
        get_success_data(api.approve_short_date_credit(credit["id"], OFFICER))

        # received_qty 3 exceeds the claimed 2.
        resp = api.finalize_short_date_credit(credit["id"], 3, OFFICER)
        validate_error(resp, ApiErrorId.ERR_RECEIVED_QTY_EXCEEDS_CLAIMED)
        assert get_short_date_credit(credit["id"])["status"] == "APPROVED"

        # received_qty equal to claimed (2) is inside the inclusive band.
        finalized = validate_success(
            api.finalize_short_date_credit(credit["id"], 2, OFFICER))
        assert finalized["status"] == "CREDITED"
        assert finalized["final_credit_cents"] == 500, (
            "Same clock date, same tier: 250 per unit * 2 received")

    def test_credit_denied_terminal_lockdown(self, api):
        """PRD §3.9: "A `REQUESTED` credit may be approved, moving it to
        `APPROVED`, or denied, moving it to terminal `DENIED`; either action
        from the wrong state fails with `ERR_CREDIT_INVALID_STATE`."

        Design: Corner/state_machines/credit_denied_terminal_lockdown
        """
        _ctx, credit = self._requested_credit(
            api, qty=1, clinic_name="Clinic CD", license_number="LIC-CD")
        denied = get_success_data(api.deny_short_date_credit(credit["id"], OFFICER))
        assert denied["status"] == "DENIED"

        resp = api.approve_short_date_credit(credit["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_CREDIT_INVALID_STATE)
        assert get_short_date_credit(credit["id"])["status"] == "DENIED"

    def test_short_date_credit_expiry_via_clock_sweep(self, api):
        """PRD §3.9: "An approved credit left unfinalized too long dies on the
        vine: the clock sweep of §2.4 moves it from `APPROVED` to `EXPIRED` once
        the current date runs more than thirty days past its approval date."
        PRD §3.9: "...the officer finalizes an `APPROVED` credit..." —
        finalization from any other state fails with `ERR_CREDIT_INVALID_STATE`.

        Design: Corner/cross_cutting_complexity_layers/short_date_credit_expiry_via_clock_sweep
        """
        _ctx, credit = self._requested_credit(
            api, qty=1, clinic_name="Clinic SW", license_number="LIC-SW")
        get_success_data(api.approve_short_date_credit(credit["id"], OFFICER))

        # Approved at clock 2026-08-10; 2026-09-15 is 36 days later (> 30).
        set_clock("2026-09-15T00:00:00Z")

        swept = get_short_date_credit(credit["id"])
        assert swept["status"] == "EXPIRED", (
            "The sweep expires an approved credit more than 30 days past "
            "approval that was never finalized")

        resp = api.finalize_short_date_credit(credit["id"], 1, OFFICER)
        validate_error(resp, ApiErrorId.ERR_CREDIT_INVALID_STATE)
