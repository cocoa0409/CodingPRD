"""Credit limits, account standing, purchase orders, and cascade propagation."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    check_in_order,
    confirm_order,
    create_account,
    create_approved_po,
    create_damage_invoice_payload,
    create_order,
    create_publisher,
    create_rental_set,
    create_work,
    dispatch_order,
    fetch_account,
    fetch_order,
    fetch_po,
    get_success_data,
    order_lines,
    reports_for_line,
    reserve_order,
    run_sweep,
    settle_order,
    setup_order_on_loan,
    validate_error,
    validate_success,
)

from test_helpers import BILLING, CLERK


class TestCreditLimitBoundary:
    def _setup_credit_boundary(self, api):
        """Account limit 70000 with a DISPATCHED 20000-cent order (the settled
        component), ready for a second 50000-cent reserve."""
        publisher = create_publisher("Pub Eleven")
        work = create_work(publisher["id"], title="Preludes", catalog_number="P11-001")
        rental_set = create_rental_set(work["id"], set_code="SET-901", copy_count=30,
                                       replacement_value_cents=240000)
        account = create_account("Valley HS", credit_tier="STANDARD",
                                 credit_limit_cents=70000)
        advance_clock()
        first = create_order(account["id"], rental_set["id"], copies=2)
        reserve_order(first["id"])
        dispatch_order(first["id"])
        return account, rental_set

    def test_reserve_at_exact_credit_limit_allowed(self, api):
        """PRD §3.5: "for accounts that are not `PREPAY`, `settled_exposure_cents`
        plus the new `estimated_fee_cents` must not exceed `credit_limit_cents` —
        a credit limit of 0 is treated as uncapped — with breaches returned as
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)".

        Design: Difficulty/boundary_precision_check/credit_limit_exact_boundary_on_reserve
        """
        account, rental_set = self._setup_credit_boundary(api)
        # Settled exposure 20000 + new estimate 50000 == limit 70000 exactly.
        order = create_order(account["id"], rental_set["id"], copies=5)
        reserved = validate_success(api.reserve_rental_order(order["id"], CLERK))
        assert reserved["status"] == "RESERVED"
        assert reserved["estimated_fee_cents"] == 50000

    def test_reserve_one_cent_over_limit_rejected(self, api):
        """PRD §3.5: "for accounts that are not `PREPAY`, `settled_exposure_cents`
        plus the new `estimated_fee_cents` must not exceed `credit_limit_cents` —
        a credit limit of 0 is treated as uncapped — with breaches returned as
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)".

        Design: Difficulty/boundary_precision_check/credit_limit_exact_boundary_on_reserve
        """
        account, rental_set = self._setup_credit_boundary(api)
        order_at_limit = create_order(account["id"], rental_set["id"], copies=5)
        reserve_order(order_at_limit["id"])

        # Lower the ceiling one cent below the 70000 the next reserve would need.
        current = fetch_account(account["id"])
        get_success_data(api.create_credit_adjustment(
            account["id"],
            {"new_credit_limit_cents": 69999,
             "expected_customer_account_version": current["version"]},
            BILLING,
        ))

        order_over = create_order(account["id"], rental_set["id"], copies=5)
        resp = api.reserve_rental_order(order_over["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


class TestOverdueSweepCascade:
    def _setup_po_backed_loan(self, api, base_rate=8000, tier="BAND", copies=4,
                              limit=0):
        publisher = create_publisher("Pub Seven")
        work = create_work(publisher["id"], title="March", catalog_number="P7-001",
                           ensemble_tier=tier, base_rental_rate_cents=base_rate,
                           sale_price_cents=1200)
        rental_set = create_rental_set(work["id"], set_code="SET-501", copy_count=20,
                                       replacement_value_cents=160000)
        account = create_account("North HS", credit_tier="STANDARD",
                                 credit_limit_cents=limit,
                                 requires_purchase_order=True)
        advance_clock()
        po = create_approved_po(account["id"], po_number="PO-9001",
                                authorized_amount_cents=500000)
        order = create_order(account["id"], rental_set["id"], copies=copies,
                             purchase_order_id=po["id"])
        reserve_order(order["id"])
        dispatch_order(order["id"])
        confirm_order(order["id"], account["id"])
        advance_clock("2026-09-05T00:00:00Z")  # one day past the 2026-09-04 due date
        return account, po, order

    def test_sweep_flips_order_overdue_account_hold_po_suspended(self, api):
        """PRD §3.5: "When the clock passes an order's `due_date`, the daily sweep
        moves the order from `ON_LOAN` to `OVERDUE` and every line with it, flips
        a `GOOD` account to `HOLD` (incrementing the account's `version`), and —
        when the order references a purchase order — lets the standing flip
        cascade that purchase order into `SUSPENDED`, incrementing its `version`
        as well."

        Design: Difficulty/transitive_cascade/overdue_sweep_cascade_order_account_po
        """
        account, po, order = self._setup_po_backed_loan(api)

        run_sweep()

        assert fetch_order(order["id"])["status"] == "OVERDUE"
        assert fetch_account(account["id"])["standing"] == "HOLD"
        assert fetch_po(po["id"])["status"] == "SUSPENDED"

    def test_sweep_tallies_report_the_work_done(self, api):
        """PRD §2.6: "The sweep responds with tallies of its work:
        `swept_rentals`, `swept_perusals`, `swept_pos`, and `standing_flips`."

        Design: Difficulty/transitive_cascade/overdue_sweep_cascade_order_account_po
        """
        account, po, order = self._setup_po_backed_loan(api)

        tallies = run_sweep()
        assert tallies["swept_rentals"] == 1
        assert tallies["standing_flips"] == 1
        # The purchase order is valid until 2027-06-30: nothing expires.
        assert tallies["swept_pos"] == 0


class TestInvoiceIssueCreditBreachCascade:
    def _setup_invoice_at_limit(self, api):
        """Account limit 7000 with an APPROVED PO; a returned order (final 6000)
        and a DRAFT 2400 invoice ready to issue."""
        publisher = create_publisher("Pub Eight")
        work = create_work(publisher["id"], title="Sonatina", catalog_number="P8-001",
                           base_rental_rate_cents=6000, sale_price_cents=900)
        rental_set = create_rental_set(work["id"], set_code="SET-601", copy_count=30,
                                       replacement_value_cents=240000)
        account = create_account("South MS", credit_tier="STANDARD",
                                 credit_limit_cents=7000)
        advance_clock()
        po = create_approved_po(account["id"], po_number="PO-9100",
                                authorized_amount_cents=100000)
        order = create_order(account["id"], rental_set["id"], copies=1)
        reserve_order(order["id"])
        dispatch_order(order["id"])
        confirm_order(order["id"], account["id"])
        check_in_order(order["id"], "C")
        line = order_lines(order["id"])[0]
        report = reports_for_line(line["id"])[0]
        invoice = get_success_data(api.create_damage_invoice(
            create_damage_invoice_payload(line["id"], report["id"]), BILLING,
        ))
        return account, po, invoice

    def test_invoice_issue_pushes_settled_exposure_to_limit(self, api):
        """PRD §3.6: "Issuing moves the supporting report to `INVOICED`,
        recomputes both exposures — the invoice now counts in each".
        PRD §3.3: "The enforcement measure, `settled_exposure_cents`, uses
        narrower sets: damage invoices count only when `ISSUED` or `DISPUTED`
        (drafts are excluded)".

        Design: Difficulty/transitive_cascade/invoice_issue_credit_breach_cascade
        """
        account, _po, invoice = self._setup_invoice_at_limit(api)
        # Before issuance the draft counts nowhere in settled: only the
        # returned order's 6000 final fee is there.
        assert fetch_account(account["id"])["settled_exposure_cents"] == 6000

        issued = validate_success(api.issue_damage_invoice(invoice["id"], BILLING))
        assert issued["status"] == "ISSUED"
        account_after = fetch_account(account["id"])
        assert account_after["settled_exposure_cents"] == 8400

    def test_invoice_issue_flips_standing_and_suspends_po(self, api):
        """PRD §3.6: "if settled exposure has reached or exceeded a positive
        credit limit, flips the account's standing to `HOLD` with the
        purchase-order suspension cascade of §3.3".
        PRD §3.3: "That flip suspends every `APPROVED` purchase order on the
        account".

        Design: Difficulty/transitive_cascade/invoice_issue_credit_breach_cascade
        """
        account, po, invoice = self._setup_invoice_at_limit(api)

        validate_success(api.issue_damage_invoice(invoice["id"], BILLING))

        # 8400 settled >= 7000 limit: the flip cascades to the APPROVED PO.
        assert fetch_account(account["id"])["standing"] == "HOLD"
        assert fetch_po(po["id"])["status"] == "SUSPENDED"


class TestPurchaseOrderBoundaries:
    def _setup_boundary_po(self, api):
        account = create_account("Boundary HS", credit_tier="STANDARD",
                                 credit_limit_cents=0)
        advance_clock()
        po = create_approved_po(account["id"], po_number="PO-BND",
                                authorized_amount_cents=50000,
                                valid_from="2026-08-01", valid_until="2026-08-31")
        return account, po

    def test_sweep_at_valid_until_keeps_approved(self, api):
        """PRD §3.4: "The daily sweep moves an `APPROVED` purchase order past its
        `valid_until` to `EXPIRED`, but only when no non-terminal rental orders
        still reference it."

        Design: Difficulty/boundary_precision_check/po_valid_until_date_threshold_boundary
        """
        _account, po = self._setup_boundary_po(api)

        advance_clock("2026-08-31T00:00:00Z")
        run_sweep()
        # "Past its valid_until" is strict: on the final valid day nothing expires.
        assert fetch_po(po["id"])["status"] == "APPROVED"

    def test_sweep_day_after_valid_until_expires(self, api):
        """PRD §3.4: "The daily sweep moves an `APPROVED` purchase order past its
        `valid_until` to `EXPIRED`, but only when no non-terminal rental orders
        still reference it."

        Design: Difficulty/boundary_precision_check/po_valid_until_date_threshold_boundary
        """
        _account, po = self._setup_boundary_po(api)

        advance_clock("2026-09-01T00:00:00Z")
        run_sweep()
        assert fetch_po(po["id"])["status"] == "EXPIRED"

    def test_po_amount_boundary_equal_allowed_exceeded_rejected(self, api):
        """PRD §3.4: "At reservation and at renewal, `encumbered_cents` plus the
        order's `estimated_fee_cents` must not exceed `authorized_amount_cents`;
        a breach is rejected with `ERR_PO_AMOUNT_EXCEEDED` (HTTP 402)."

        Design: Corner/validations/po_amount_boundary_equal_allowed_exceeded_rejected
        """
        publisher = create_publisher("PB Pub")
        work = create_work(publisher["id"], title="PB Work", catalog_number="PB-1")
        rental_set = create_rental_set(work["id"], set_code="PB-SET", copy_count=30,
                                       replacement_value_cents=240000)
        account = create_account("PB HS", credit_tier="STANDARD", credit_limit_cents=0,
                                 requires_purchase_order=True)
        advance_clock()
        po = create_approved_po(account["id"], po_number="PO-B1",
                                authorized_amount_cents=30000)

        first = create_order(account["id"], rental_set["id"], copies=1,
                             purchase_order_id=po["id"])
        reserve_order(first["id"])
        second = create_order(account["id"], rental_set["id"], copies=2,
                              purchase_order_id=po["id"])
        # 10000 + 20000 hits the 30000 ceiling exactly: allowed.
        reserved_second = validate_success(api.reserve_rental_order(second["id"], CLERK))
        assert reserved_second["status"] == "RESERVED"
        assert fetch_po(po["id"])["encumbered_cents"] == 30000

        third = create_order(account["id"], rental_set["id"], copies=1,
                             purchase_order_id=po["id"])
        resp = api.reserve_rental_order(third["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_PO_AMOUNT_EXCEEDED)
        assert fetch_po(po["id"])["encumbered_cents"] == 30000


class TestPurchaseOrderStateGate:
    def _setup_po_gated_account(self, api):
        publisher = create_publisher("Pub Thirteen")
        work = create_work(publisher["id"], title="Rondo", catalog_number="P13-001")
        rental_set = create_rental_set(work["id"], set_code="SET-1101", copy_count=30,
                                       replacement_value_cents=240000)
        account = create_account("Cedar HS", credit_tier="STANDARD",
                                 credit_limit_cents=0, requires_purchase_order=True)
        advance_clock()
        po = get_success_data(api.create_purchase_order(
            {
                "account_id": account["id"],
                "po_number": "PO-777",
                "authorized_amount_cents": 500000,
                "valid_from": "2026-08-01",
                "valid_until": "2027-06-30",
            },
            BILLING,
        ))
        order = create_order(account["id"], rental_set["id"], copies=1,
                             purchase_order_id=po["id"])
        return account, po, order

    def test_reserve_rejected_while_po_submitted(self, api):
        """PRD §3.4: "at both reservation and dispatch the referenced purchase
        order must be `APPROVED` with the current date inside its validity window,
        otherwise `ERR_PO_NOT_USABLE`."

        Design: Difficulty/cross_entity_state_dependency/dispatch_gated_by_purchase_order_state
        """
        _account, po, order = self._setup_po_gated_account(api)
        assert po["status"] == "SUBMITTED"

        resp = api.reserve_rental_order(order["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_PO_NOT_USABLE)

    def test_reserve_succeeds_after_po_approval_and_encumbers(self, api):
        """PRD §3.4: "Encumbrance accrues at reservation — the order's estimated
        fee is added and the purchase order's `version` increments — adjusts by
        the fee delta at renewal, and is released at settlement or cancellation."

        Design: Difficulty/cross_entity_state_dependency/dispatch_gated_by_purchase_order_state
        """
        _account, po, order = self._setup_po_gated_account(api)
        get_success_data(api.approve_purchase_order(po["id"], BILLING))

        reserved = validate_success(api.reserve_rental_order(order["id"], CLERK))
        assert reserved["status"] == "RESERVED"
        assert reserved["estimated_fee_cents"] == 10000
        assert fetch_po(po["id"])["encumbered_cents"] == 10000


class TestStandingCycles:
    def test_purchase_order_suspend_reapprove_cycle_via_account_flip(self, api):
        """PRD §3.4: "when an account's standing flips from `GOOD` to `HOLD` or
        `BARRED`, each of its `APPROVED` purchase orders moves to `SUSPENDED`, and
        when standing returns to `GOOD` each returns to `APPROVED`".
        PRD §3.3: "Standing returns from `HOLD` to `GOOD` automatically once no
        `OVERDUE` rentals and no `OVERDUE_PERUSAL` perusals remain and settled
        exposure sits below the credit limit".

        Design: Corner/state_machines/purchase_order_suspend_reapprove_cycle_via_account_flip
        """
        publisher = create_publisher("Cyc Pub")
        work = create_work(publisher["id"], title="Cyc Work", catalog_number="CYC-1")
        rental_set = create_rental_set(work["id"], set_code="CYC-SET", copy_count=10,
                                       replacement_value_cents=80000)
        account = create_account("Cyc HS", credit_tier="STANDARD", credit_limit_cents=0,
                                 requires_purchase_order=True)
        advance_clock()
        po = create_approved_po(account["id"], po_number="PO-CYC",
                                authorized_amount_cents=300000)
        order = create_order(account["id"], rental_set["id"], copies=1,
                             purchase_order_id=po["id"])
        reserve_order(order["id"])
        dispatch_order(order["id"])
        confirm_order(order["id"], account["id"])

        # Two days past due: the sweep flips order -> OVERDUE, account -> HOLD,
        # purchase order -> SUSPENDED.
        advance_clock("2026-09-06T00:00:00Z")
        run_sweep()
        assert fetch_po(po["id"])["status"] == "SUSPENDED"
        assert fetch_account(account["id"])["standing"] == "HOLD"

        returned = check_in_order(order["id"], "A")
        # 2 late days: daily_base rhu(10000/30)=333, tier-1 rate rhu(333x0.10)=33.
        assert returned["final_fee_cents"] == 10066
        settle_order(order["id"])

        run_sweep()
        assert fetch_account(account["id"])["standing"] == "GOOD"
        assert fetch_po(po["id"])["status"] == "APPROVED", (
            "the SUSPENDED -> APPROVED cyclic edge must fire once standing is GOOD"
        )

    def test_po_expiry_blocked_by_open_orders(self, api):
        """PRD §3.4: "The daily sweep moves an `APPROVED` purchase order past its
        `valid_until` to `EXPIRED`, but only when no non-terminal rental orders
        still reference it. A `BillingManager` may close an `APPROVED` purchase
        order under the same guard — when open orders still reference it the close
        is refused with `ERR_PO_HAS_OPEN_ORDERS`".

        Design: Corner/validations/po_expiry_blocked_by_open_orders
        """
        publisher = create_publisher("PE Pub")
        work = create_work(publisher["id"], title="PE Work", catalog_number="PE-1")
        rental_set = create_rental_set(work["id"], set_code="PE-SET", copy_count=5,
                                       replacement_value_cents=40000)
        account = create_account("PE HS", credit_tier="STANDARD", credit_limit_cents=0,
                                 requires_purchase_order=True)
        advance_clock()
        po = create_approved_po(account["id"], po_number="PO-EXP",
                                authorized_amount_cents=100000,
                                valid_from="2026-08-01", valid_until="2026-08-31")
        order = create_order(account["id"], rental_set["id"], copies=1,
                             purchase_order_id=po["id"])
        reserve_order(order["id"])
        dispatch_order(order["id"])
        confirm_order(order["id"], account["id"])

        advance_clock("2026-09-01T00:00:00Z")  # past valid_until, order still out
        run_sweep()
        assert fetch_po(po["id"])["status"] == "APPROVED", (
            "expiry is blocked while a non-terminal rental references the PO"
        )
        resp = api.close_purchase_order(po["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_PO_HAS_OPEN_ORDERS)

    def test_encumbrance_reconciliation_on_settle(self, api):
        """PRD §3.4: "Encumbrance accrues at reservation — the order's estimated
        fee is added and the purchase order's `version` increments — adjusts by
        the fee delta at renewal, and is released at settlement or cancellation."

        Design: Corner/cross_cutting_layers/encumbrance_reconciliation_on_settle
        """
        publisher = create_publisher("ER Pub")
        work = create_work(publisher["id"], title="ER Work", catalog_number="ER-1")
        rental_set = create_rental_set(work["id"], set_code="ER-SET", copy_count=5,
                                       replacement_value_cents=40000)
        account = create_account("ER HS", credit_tier="STANDARD", credit_limit_cents=0,
                                 requires_purchase_order=True)
        advance_clock()
        po = create_approved_po(account["id"], po_number="PO-ER",
                                authorized_amount_cents=100000)
        order = create_order(account["id"], rental_set["id"], copies=1,
                             purchase_order_id=po["id"])
        reserve_order(order["id"])
        assert fetch_po(po["id"])["encumbered_cents"] == 10000

        dispatch_order(order["id"])
        confirm_order(order["id"], account["id"])
        check_in_order(order["id"], "A")
        settle_order(order["id"])

        assert fetch_po(po["id"])["encumbered_cents"] == 0, (
            "settlement must release the encumbrance exactly — no ledger drift"
        )


class TestExposureVariants:
    def _setup_divergent_exposure(self, api):
        """One RESERVED order (50000, open-only), one RETURNED order (final 20000,
        both variants), and one DRAFT damage invoice (2400, open-only)."""
        publisher = create_publisher("Pub Two")
        work = create_work(publisher["id"], title="Etudes", catalog_number="P2-001",
                           license_format="PRINT_ONLY")
        rental_set = create_rental_set(work["id"], set_code="SET-101", copy_count=30,
                                       replacement_value_cents=240000)
        account = create_account("City Conservatory", account_kind="INSTITUTION",
                                 credit_tier="STANDARD", credit_limit_cents=0)
        advance_clock()
        reserved_order = create_order(account["id"], rental_set["id"], copies=5)
        reserve_order(reserved_order["id"])

        returned_order = create_order(account["id"], rental_set["id"], copies=2)
        reserve_order(returned_order["id"])
        dispatch_order(returned_order["id"])
        confirm_order(returned_order["id"], account["id"])
        check_in_order(returned_order["id"], "C,A")
        line = [l for l in order_lines(returned_order["id"])
                if l.get("return_condition") == "C"][0]
        report = reports_for_line(line["id"])[0]
        invoice = get_success_data(api.create_damage_invoice(
            create_damage_invoice_payload(line["id"], report["id"]), BILLING,
        ))
        assert invoice["status"] == "DRAFT"
        return account, invoice

    def test_open_exposure_includes_reserved_estimates_and_draft_invoices(self, api):
        """PRD §3.3: "The informational measure, `open_exposure_cents`, sums four
        components: the `amount_cents` of the account's damage invoices in
        `DRAFT`, `ISSUED`, or `DISPUTED`; the `estimated_fee_cents` of its rental
        orders in `RESERVED`, `DISPATCHED`, `ON_LOAN`, or `OVERDUE`; the
        `final_fee_cents` of its orders in `RETURNED` or `DISPUTED` once that
        final fee is set; and the `balance_due_cents` of its `INVOICED` sale
        records."

        Design: Difficulty/dual_variant_calc/account_exposure_open_vs_settled_divergence
        """
        account, _invoice = self._setup_divergent_exposure(api)
        # 50000 (RESERVED estimate) + 20000 (RETURNED final) + 2400 (DRAFT invoice).
        assert fetch_account(account["id"])["open_exposure_cents"] == 72400

    def test_settled_exposure_excludes_reserved_and_drafts(self, api):
        """PRD §3.3: "The enforcement measure, `settled_exposure_cents`, uses
        narrower sets: damage invoices count only when `ISSUED` or `DISPUTED`
        (drafts are excluded), and rental estimates count only once an order has
        been dispatched — `DISPATCHED`, `ON_LOAN`, or `OVERDUE` — because a
        reserved order has not yet created an obligation".

        Design: Difficulty/dual_variant_calc/account_exposure_open_vs_settled_divergence
        """
        account, invoice = self._setup_divergent_exposure(api)
        # Only the RETURNED order's 20000 final fee counts.
        assert fetch_account(account["id"])["settled_exposure_cents"] == 20000

        # Issuing moves the invoice into the settled set too.
        validate_success(api.issue_damage_invoice(invoice["id"], BILLING))
        assert fetch_account(account["id"])["settled_exposure_cents"] == 22400


class TestStandingEnforcement:
    def test_error_account_still_delinquent_on_reinstate(self, api):
        """PRD §3.3: "may later reinstate a `BARRED` one, provided no overdue
        rentals or overdue perusals remain (otherwise
        `ERR_ACCOUNT_STILL_DELINQUENT`)".

        Design: Corner/errors/error_account_still_delinquent_on_reinstate
        """
        ws = setup_order_on_loan(order_copies=1, publisher_name="AD Pub",
                                 work_title="AD Work", catalog_number="AD-1",
                                 set_code="AD-SET", replacement=40000,
                                 account_overrides={"account_name": "AD Acct",
                                                    "credit_tier": "STANDARD",
                                                    "credit_limit_cents": 0})
        advance_clock("2026-09-10T00:00:00Z")
        run_sweep()
        assert fetch_account(ws["account"]["id"])["standing"] == "HOLD"
        barred = validate_success(api.bar_account(ws["account"]["id"], BILLING))
        assert barred["standing"] == "BARRED"

        resp = api.reinstate_account(ws["account"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_STILL_DELINQUENT)
        assert fetch_account(ws["account"]["id"])["standing"] == "BARRED"


class TestCreditAdjustmentOcc:
    def test_error_stale_version_on_credit_adjustment(self, api):
        """PRD §2.7: "Applying a manual credit-limit adjustment to a customer
        account likewise requires a non-optional `expected_customer_account_version`;
        if a cascade such as an invoice issuance, a sweep-driven standing flip, or
        an exposure recompute has advanced the account's `version` since the client
        last read it, the adjustment is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/errors/error_stale_version_on_credit_adjustment
        """
        account = create_account("OCC Acct", credit_tier="STANDARD",
                                 credit_limit_cents=1000)
        observed_version = account["version"]

        adjusted = validate_success(api.create_credit_adjustment(
            account["id"],
            {"new_credit_limit_cents": 2000,
             "expected_customer_account_version": observed_version},
            BILLING,
        ))
        assert adjusted["version"] == observed_version + 1
        assert adjusted["credit_limit_cents"] == 2000

        # Replaying the stale observation must be rejected.
        resp = api.create_credit_adjustment(
            account["id"],
            {"new_credit_limit_cents": 3000,
             "expected_customer_account_version": observed_version},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert fetch_account(account["id"])["credit_limit_cents"] == 2000
