"""Assessment billing: dual billing methods, tiered tolls with overage,
pinned rounding order, delinquency sweep, payment ownership, and liens."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_amount,
    assert_assessment_invoice,
    create_account,
    create_allocation,
    create_announced_season,
    create_invoice,
    create_issued_invoice,
    create_open_season,
    create_reach,
    get_account,
    get_allocation,
    get_invoice,
    get_order,
    make_water_user_headers,
    pay_invoice,
    place_order,
    run_sweep,
    schedule_order,
    set_clock,
    setup_open_season_with_allocation,
    start_order,
    submit_measurement,
    validate_error,
    validate_success,
    verify_work_order,
)


def _deliver(account_id, allocation_id, reach_id, cfs, hours, start, end,
             clock_at, rider="rider-1"):
    """Full delivery of `hours` at `cfs` within the given window."""
    order = place_order(account_id, allocation_id, reach_id,
                        requested_cfs=cfs, start=start, end=end)
    order, work_order = schedule_order(order["id"], rider)
    set_clock(clock_at)
    start_order(order["id"], rider)
    submit_measurement(work_order["id"], rider, cfs, hours)
    verify_work_order(work_order["id"])
    return get_order(order["id"])


class TestDualBillingMethods:
    def _setup_dual_billing(self):
        """Account B (40.0 acres) takes one 30.00 af delivery (5.0 cfs x
        72.64 h) in each of two seasons: 2026 PER_ACRE (rate 25.00) and 2027
        PER_AF_DELIVERED (tier1 cap 20, rates 18/30, overage 60)."""
        account = create_account(
            holder_name="Bob B", parcel_number="APN-002", irrigated_acres=40.0,
            water_right_priority_date="1900-01-01T00:00:00Z",
        )
        season_x = create_open_season(
            year=2026, announced_af_per_acre=1.0, billing_method="PER_ACRE",
        )
        season_y = create_open_season(
            year=2027, announced_af_per_acre=1.0, billing_method="PER_AF_DELIVERED",
            start_date="2027-04-01T00:00:00Z", end_date="2027-09-30T00:00:00Z",
        )
        alloc_x = create_allocation(account["id"], season_x["id"])
        alloc_y = create_allocation(account["id"], season_y["id"])
        reach = create_reach(name="Main Canal", max_capacity_cfs=50.0)
        _deliver(account["id"], alloc_x["id"], reach["id"], 5.0, 72.64,
                 "2026-06-01T08:00:00Z", "2026-06-04T20:00:00Z",
                 "2026-06-02T12:00:00Z")
        _deliver(account["id"], alloc_y["id"], reach["id"], 5.0, 72.64,
                 "2027-06-01T08:00:00Z", "2027-06-04T20:00:00Z",
                 "2027-06-02T12:00:00Z")
        return {"account": account, "season_x": season_x, "season_y": season_y}

    def test_per_acre_invoice_amounts(self, api):
        """PRD §3.8: "Under `PER_ACRE` billing, the `acreage_line_amount` is
        the account's `irrigated_acres` multiplied by the season's
        `assessment_rate_per_acre`, rounded half-up to 2 decimal places, and
        the `toll_line_amount` is 0.00."
        40.0 acres x 25.00 = 1000.00, independent of the 30.00 af delivered.

        Design: Difficulty/dual_variant_calc/assessment_per_acre_vs_per_af_delivered
        """
        bundle = self._setup_dual_billing()
        invoice = create_invoice(bundle["account"]["id"], bundle["season_x"]["id"])
        assert_assessment_invoice(invoice)
        assert invoice["billing_method_snapshot"] == "PER_ACRE"
        assert_amount(invoice["acreage_line_amount"], 1000.00, "acreage_line_amount")
        assert_amount(invoice["toll_line_amount"], 0.00, "toll_line_amount")
        assert_amount(invoice["total_amount"], 1000.00, "total_amount")

    def test_per_af_delivered_invoice_amounts_differ(self, api):
        """PRD §3.8: "Under `PER_AF_DELIVERED` billing, the
        `acreage_line_amount` is 0.00 and the `toll_line_amount` is the tiered
        water toll on the allocation's season-to-date `delivered_af`..." and
        "The two methods are mutually exclusive views of the same account:
        identical delivery data yields a different total under `PER_ACRE` than
        under `PER_AF_DELIVERED`."
        The same 30.00 af delivered bills 18x20 + 30x10 = 660.00 under the
        PER_AF_DELIVERED season versus 1000.00 under PER_ACRE.

        Design: Difficulty/dual_variant_calc/assessment_per_acre_vs_per_af_delivered
        """
        bundle = self._setup_dual_billing()
        invoice_x = create_invoice(bundle["account"]["id"], bundle["season_x"]["id"])
        invoice_y = create_invoice(bundle["account"]["id"], bundle["season_y"]["id"])

        assert invoice_y["billing_method_snapshot"] == "PER_AF_DELIVERED"
        assert_amount(invoice_y["acreage_line_amount"], 0.00, "acreage_line_amount")
        assert_amount(invoice_y["toll_line_amount"], 660.00,
                      "toll_line_amount (18x20 + 30x10)")
        assert_amount(invoice_y["total_amount"], 660.00, "total_amount")
        assert abs(invoice_x["total_amount"] - invoice_y["total_amount"]) > 0.001, (
            "Identical delivery data bills differently under the two methods"
        )


class TestTieredTollWithOverage:
    def _setup_overage(self):
        """PER_AF_DELIVERED season (announced 1.0, tier1 cap 20, rates 18/30,
        overage 60); account 40.0 acres -> 40.00 af entitlement; one order
        requested at 39.65 af (7.5 cfs x 64 h) but measured 45.00 af
        (7.5 cfs x 72.64 h) and verified."""
        scenario = setup_open_season_with_allocation(
            irrigated_acres=40.0, holder_name="Toll T", parcel_number="APN-003",
            announced_af_per_acre=1.0, billing_method="PER_AF_DELIVERED",
        )
        order = _deliver(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"], 7.5, 72.64,
            "2026-06-01T08:00:00Z", "2026-06-04T00:00:00Z",
            "2026-06-02T12:00:00Z", rider="rider-2",
        )
        scenario["order"] = order
        return scenario

    def test_tiered_water_toll_with_overage_branch(self, api):
        """PRD §3.8: "Under `PER_AF_DELIVERED` billing, ... the delivered
        volume is split into a tier-1 portion up to the season's
        `toll_tier1_cap_af` billed at `toll_tier1_rate_per_af`, a tier-2
        portion above that cap billed at `toll_tier2_rate_per_af`, and an
        overage portion — the amount by which delivered volume exceeds the
        entitlement pool of effective entitlement plus carryover-in plus
        transfers-in minus transfers-out — billed at `overage_rate_per_af`;
        the three products are summed and the result is rounded half-up to 2
        decimal places."
        45.00 af delivered against a 40.00 af pool bills 18x20 + 30x25 +
        60x5 = 1410.00.

        Design: Difficulty/combinatorial_formula/tiered_water_toll_with_overage_branch
        """
        scenario = self._setup_overage()
        invoice = create_invoice(
            scenario["account"]["id"], scenario["season"]["id"],
        )
        assert_amount(invoice["toll_line_amount"], 1410.00,
                      "toll_line_amount (18*20 + 30*25 + 60*5)")
        assert_amount(invoice["total_amount"], 1410.00, "total_amount")

    def test_overage_marks_allocation_and_order(self, api):
        """PRD §3.2: "`over_allocated_af` is the amount by which
        `delivered_af` exceeds that same entitlement pool (ignoring committed
        water entirely), floored at zero."
        PRD §3.4: "...its `over_delivered` flag is set true exactly when the
        measured volume exceeds the order's `requested_quantity_af`."
        45.00 af delivered against a 40.00 af pool is 5.00 af over; the
        order's 45.00 af measured exceeds its 39.65 af requested.

        Design: Difficulty/combinatorial_formula/tiered_water_toll_with_overage_branch
        """
        scenario = self._setup_overage()
        allocation = get_allocation(scenario["allocation"]["id"])
        assert_amount(allocation["delivered_af"], 45.00, "delivered_af")
        assert_amount(allocation["over_allocated_af"], 5.00, "over_allocated_af")

        order = get_order(scenario["order"]["id"])
        assert order["over_delivered"] is True
        assert_amount(order["actual_delivered_af"], 45.00, "actual_delivered_af")


class TestPenaltyRounding:
    def _setup_delinquent_invoice(self):
        """PER_ACRE season at 12.75 per acre; account 40.5 acres -> raw
        acreage line 516.375; invoice issued with due 2026-08-10 and the clock
        moved past the grace period."""
        season = create_announced_season(assessment_rate_per_acre=12.75)
        account = create_account(
            holder_name="Penny P", parcel_number="APN-004", irrigated_acres=40.5,
            water_right_priority_date="1901-01-01T00:00:00Z",
        )
        invoice = create_issued_invoice(
            account["id"], season["id"], due_date="2026-08-10T00:00:00Z",
        )
        set_clock("2026-08-21T00:00:00Z")
        return {"season": season, "account": account, "invoice": invoice}

    def test_sweep_flips_overdue_invoice(self, api):
        """PRD §3.8: "every invoice of that season still in `ISSUED` whose due
        date plus the 10-day grace period is strictly before the logical clock
        flips to `DELINQUENT`..." and "The sweep's response reports the
        `swept_count` and the list `delinquent_invoice_ids`."

        Design: Difficulty/combinatorial_formula/invoice_penalty_round_per_line_then_sum
        """
        bundle = self._setup_delinquent_invoice()
        sweep = run_sweep(bundle["season"]["id"])
        assert sweep["swept_count"] == 1
        assert bundle["invoice"]["id"] in sweep["delinquent_invoice_ids"]
        assert get_invoice(bundle["invoice"]["id"])["status"] == "DELINQUENT"

    def test_penalty_round_per_line_then_sum(self, api):
        """PRD §2.4: "Invoice totals are built per line: each line item is
        first rounded half-up to cents, and the invoice total is the sum of
        those already-rounded lines, never a single rounding applied to an
        unrounded sum."
        PRD §3.8: "Flipping to `DELINQUENT` recomputes the
        `penalty_line_amount` as 10 percent of the sum of the (already
        rounded) acreage and toll lines, itself rounded half-up to 2 decimal
        places, and `total_amount` is recomputed as the sum of the rounded
        lines including the penalty."
        Raw acreage 516.375 rounds to 516.38 first; the penalty is
        round(0.10 x 516.38) = 51.64; the total is 568.02 (the sum-then-round
        reading 516.375 x 1.1 = 568.01 is wrong).

        Design: Difficulty/combinatorial_formula/invoice_penalty_round_per_line_then_sum
        """
        bundle = self._setup_delinquent_invoice()
        run_sweep(bundle["season"]["id"])
        invoice = get_invoice(bundle["invoice"]["id"])
        assert_amount(invoice["acreage_line_amount"], 516.38,
                      "acreage_line_amount (round-half-up of 516.375)")
        assert_amount(invoice["penalty_line_amount"], 51.64,
                      "penalty_line_amount (round-half-up of 0.10 x 516.38)")
        assert_amount(invoice["total_amount"], 568.02,
                      "total_amount (per-line-then-sum)")


class TestDelinquencyGraceBoundary:
    def _setup_issued_invoice(self):
        season = create_announced_season(assessment_rate_per_acre=25.00)
        account = create_account(
            holder_name="Grace G", parcel_number="APN-013", irrigated_acres=10.0,
        )
        invoice = create_issued_invoice(
            account["id"], season["id"], due_date="2026-08-10T00:00:00Z",
        )
        return {"season": season, "account": account, "invoice": invoice}

    def test_grace_exact_boundary_stays_issued(self, api):
        """PRD §3.8: "an invoice whose grace period expires exactly at the
        current clock instant remains `ISSUED`, since the comparison is
        strict."
        At the clock equal to due_date + 10 days exactly, the sweep flips
        nothing.

        Design: Difficulty/boundary_precision_check/delinquency_grace_exact_boundary
        """
        bundle = self._setup_issued_invoice()
        set_clock("2026-08-20T00:00:00Z")
        sweep = run_sweep(bundle["season"]["id"])
        assert sweep["swept_count"] == 0, "Strict-greater rule: equality stays ISSUED"
        assert get_invoice(bundle["invoice"]["id"])["status"] == "ISSUED"

    def test_one_second_past_grace_flips_delinquent(self, api):
        """PRD §3.8: "every invoice of that season still in `ISSUED` whose due
        date plus the 10-day grace period is strictly before the logical clock
        flips to `DELINQUENT`..." and "Flipping to `DELINQUENT` recomputes the
        `penalty_line_amount` as 10 percent of the sum of the (already
        rounded) acreage and toll lines, itself rounded half-up to 2 decimal
        places, and `total_amount` is recomputed as the sum of the rounded
        lines including the penalty."
        One second past the boundary the invoice flips and totals 275.00
        (250.00 + 25.00 penalty).

        Design: Difficulty/boundary_precision_check/delinquency_grace_exact_boundary
        """
        bundle = self._setup_issued_invoice()
        set_clock("2026-08-20T00:00:01Z")
        sweep = run_sweep(bundle["season"]["id"])
        assert sweep["swept_count"] == 1

        invoice = get_invoice(bundle["invoice"]["id"])
        assert invoice["status"] == "DELINQUENT"
        assert_amount(invoice["penalty_line_amount"], 25.00, "penalty_line_amount")
        assert_amount(invoice["total_amount"], 275.00, "total_amount")


class TestSweepInputSet:
    def test_sweep_only_flips_issued_invoices(self, api):
        """PRD §3.8: "`DRAFT`, `PAID`, and `LIEN_FILED` invoices are never
        touched by the sweep."
        With one PAID, one ISSUED, and one DRAFT invoice all past due, only
        the ISSUED one flips.

        Design: Corner/calculations/sweep_only_flips_issued_invoices
        """
        season = create_announced_season(assessment_rate_per_acre=25.00)
        account_a = create_account(holder_name="Paid P", parcel_number="APN-119",
                                   irrigated_acres=10.0)
        account_b = create_account(holder_name="Issued I", parcel_number="APN-120",
                                   irrigated_acres=10.0)
        account_c = create_account(holder_name="Draft D", parcel_number="APN-121",
                                   irrigated_acres=10.0)
        inv_a = create_issued_invoice(account_a["id"], season["id"])
        inv_b = create_issued_invoice(account_b["id"], season["id"])
        inv_c = create_invoice(account_c["id"], season["id"])
        pay_invoice(inv_a["id"], account_a["id"])

        set_clock("2026-08-21T00:00:00Z")
        sweep = run_sweep(season["id"])
        assert sweep["swept_count"] == 1, "Only the ISSUED invoice flips"
        assert get_invoice(inv_a["id"])["status"] == "PAID", "PAID is untouched"
        assert get_invoice(inv_b["id"])["status"] == "DELINQUENT"
        assert get_invoice(inv_c["id"])["status"] == "DRAFT", "DRAFT is untouched"


class TestInvoicePaymentGates:
    def test_pay_draft_invoice_rejected(self, api):
        """PRD §3.8: "Invoice transitions from wrong from-states — paying a
        `DRAFT` invoice, filing a lien on a merely `ISSUED` one, or paying an
        already `PAID` invoice — are refused with
        `ERR_INVALID_INVOICE_STATE`." and "The `penalty_line_amount` begins at
        0.00, and `issued_at` and `paid_at` are null while the invoice is
        `DRAFT`."

        Design: Corner/state_machines/pay_draft_invoice_rejected
        """
        season = create_announced_season()
        account = create_account(holder_name="Draft D", parcel_number="APN-107",
                                 irrigated_acres=10.0)
        invoice = create_invoice(account["id"], season["id"])

        resp = api.pay_invoice(invoice["id"], make_water_user_headers(account["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_INVOICE_STATE)

        invoice_after = get_invoice(invoice["id"])
        assert invoice_after["status"] == "DRAFT"
        assert invoice_after["paid_at"] is None

    def test_wateruser_cannot_pay_others_invoice_forbidden(self, api):
        """PRD §3.8: "The account owner pays an invoice in full from `ISSUED`,
        `DELINQUENT`, or `LIEN_FILED`; the payment is authorized by matching
        the caller's `X-User-ID` to the invoice's `water_account_id` (else
        `ERR_FORBIDDEN`) and stamps `paid_at` from the logical clock."

        Design: Corner/rbac/wateruser_cannot_pay_others_invoice_forbidden
        """
        season = create_announced_season()
        account_a = create_account(holder_name="Owner A", parcel_number="APN-137",
                                   irrigated_acres=10.0)
        account_b = create_account(holder_name="Caller B", parcel_number="APN-138",
                                   irrigated_acres=10.0,
                                   water_right_priority_date="1890-01-01T00:00:00Z")
        invoice = create_issued_invoice(account_a["id"], season["id"])

        resp = api.pay_invoice(invoice["id"], make_water_user_headers(account_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_invoice(invoice["id"])["status"] == "ISSUED"

    def test_duplicate_invoice_rejected(self, api):
        """PRD §3.8: "The district bills each account once per season. An
        administrator creates an `AssessmentInvoice` naming the
        `water_account_id` and `season_id`; only one invoice may exist per
        account-season pair (a duplicate is refused with
        `ERR_DUPLICATE_INVOICE`)."

        Design: Corner/validations/duplicate_invoice_rejected
        """
        season = create_announced_season()
        account = create_account(holder_name="DupInv D", parcel_number="APN-128",
                                 irrigated_acres=10.0)
        first = create_invoice(account["id"], season["id"])
        assert first["status"] == "DRAFT"

        resp = api.create_assessment_invoice(
            {"water_account_id": account["id"], "season_id": season["id"]}, ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVOICE)


class TestPaymentBranches:
    def _setup_two_invoices(self):
        """Two 10.0-acre accounts with 250.00 invoices issued for the season,
        due 2026-08-10."""
        season = create_announced_season(assessment_rate_per_acre=25.00)
        account1 = create_account(holder_name="Direct D", parcel_number="APN-006",
                                  irrigated_acres=10.0)
        account2 = create_account(holder_name="Late L", parcel_number="APN-007",
                                  irrigated_acres=10.0)
        inv1 = create_issued_invoice(account1["id"], season["id"])
        inv2 = create_issued_invoice(account2["id"], season["id"])
        return {"season": season, "account1": account1, "account2": account2,
                "inv1": inv1, "inv2": inv2}

    def test_direct_pay_branch_leaves_account_untouched(self, api):
        """PRD §3.8: "Paying from `ISSUED` or `DELINQUENT` simply moves the
        invoice to `PAID`." and "`DRAFT`, `PAID`, and `LIEN_FILED` invoices
        are never touched by the sweep."
        The direct ISSUED -> PAID branch never suspends the account, and the
        paid invoice is invisible to the later sweep.

        Design: Difficulty/non_linear_state_machine/invoice_branching_direct_pay_vs_lien_path
        """
        bundle = self._setup_two_invoices()
        paid = pay_invoice(bundle["inv1"]["id"], bundle["account1"]["id"])
        assert paid["status"] == "PAID"
        assert paid["paid_at"] is not None
        assert get_account(bundle["account1"]["id"])["status"] == "ACTIVE", (
            "The direct-pay branch has no suspension side effect"
        )

        set_clock("2026-08-21T00:00:00Z")
        sweep = run_sweep(bundle["season"]["id"])
        assert sweep["swept_count"] == 1, "Only the unpaid ISSUED invoice flips"
        assert get_invoice(bundle["inv1"]["id"])["status"] == "PAID"
        assert get_invoice(bundle["inv2"]["id"])["status"] == "DELINQUENT"

    def test_lien_path_suspends_then_restores_account(self, api):
        """PRD §3.8: "Filing a lien suspends the account: the account's status
        becomes `SUSPENDED` and its `version` increments by 1." and "Paying a
        `LIEN_FILED` invoice additionally releases the lien hold: if no other
        `LIEN_FILED` invoice remains for the account, the account's status
        returns to `ACTIVE` and its `version` increments by 1."
        The liened invoice totals 275.00 (250.00 + 25.00 penalty) when paid.

        Design: Difficulty/non_linear_state_machine/invoice_branching_direct_pay_vs_lien_path
        """
        bundle = self._setup_two_invoices()
        pay_invoice(bundle["inv1"]["id"], bundle["account1"]["id"])
        set_clock("2026-08-21T00:00:00Z")
        run_sweep(bundle["season"]["id"])

        resp = api.file_lien(bundle["inv2"]["id"], ADMIN)
        liened = validate_success(resp, expected_status=200)
        assert liened["status"] == "LIEN_FILED"
        assert get_account(bundle["account2"]["id"])["status"] == "SUSPENDED"

        paid = pay_invoice(bundle["inv2"]["id"], bundle["account2"]["id"])
        assert paid["status"] == "PAID"
        assert_amount(paid["total_amount"], 275.00,
                      "total_amount (250.00 + 25.00 penalty)")
        assert get_account(bundle["account2"]["id"])["status"] == "ACTIVE", (
            "Paying the only liened invoice releases the lien hold"
        )
