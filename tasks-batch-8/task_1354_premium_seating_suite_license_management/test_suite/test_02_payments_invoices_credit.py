"""Invoices, payments, late fees, credit standing, and the collection cascade."""
from test_helpers import (
    ESM, FIN, REP,
    ApiClient, ApiErrorId, EVENT_E1,
    activate_account, complete_event, get_license_fee_invoice, get_single_invoice,
    list_invoice_rows, make_account, make_account_holder_headers, make_active_account,
    make_event, make_issued_invoice, make_season, make_venue, pay_invoice_in_full,
    set_clock, setup_active_agreement, settle_season,
    validate_error, validate_paginated, validate_success,
)

GOLD_SUITE = dict(suite_code="G-101", tier="GOLD", capacity_seats=20,
                  base_annual_fee_cents=12000000, f_b_minimum_cents=4000000)


def _settled_account_in_default(api: ApiClient):
    """Account suspended by the settle sweep with two open invoices:
    manual M (subtotal 100000, due 2026-08-20 -> 109000 with late fee at settle)
    and F_B_SHORTFALL S (4000000, no catering accruals)."""
    s = setup_active_agreement(num_seasons=2, events_spec=[EVENT_E1],
                               execute_clock="2026-08-10T00:00:00Z",
                               agreement_over=dict(term_seasons=2))
    ac, ag, season, event = s["account"], s["agreement"], s["seasons"][0], s["events"][0]
    pay_invoice_in_full(ac["id"], get_license_fee_invoice(ag["id"]))
    invm = make_issued_invoice(ac["id"], lines=[{"description": "Suite signage",
                                                 "quantity": 1,
                                                 "unit_price_cents": 100000}],
                               due_on="2026-08-20T00:00:00Z")
    complete_event(event["id"], "2027-02-16T00:00:00Z")
    settle_season(season["id"], "2027-02-20T00:00:00Z")
    invs = get_single_invoice({"agreement_id": ag["id"], "invoice_type": "F_B_SHORTFALL"})
    return s, invm, invs


def _pay_both(api: ApiClient, account_id, invm, invs):
    resp = api.create_payment(
        {"account_id": account_id, "amount_cents": 4109000, "method": "WIRE",
         "allocations": [{"invoice_id": invm["id"], "amount_cents": 109000},
                         {"invoice_id": invs["id"], "amount_cents": 4000000}]}, FIN)
    payment = validate_success(resp, expected_status=201)
    validate_success(api.set_payment_status(payment["id"], {"target_status": "CLEARED"}, FIN))
    return payment


class TestPaymentClearFourLinkCascade:
    def test_clear_reinstates_account_and_cures_agreement(self, api: ApiClient):
        """PRD §3.4: "Link three: if the balance has reached zero, no invoice of the
        account is past due, and the account was `SUSPENDED`, the account
        auto-reinstates to `ACTIVE`. Link four: a reinstated `ACTIVE` account's
        agreements that were suspended with reason `ACCOUNT_DEFAULT` auto-cure back to
        `ACTIVE`."
        Design: Difficulty/transitive_cascade/payment_clear_four_link_cascade_reinstates_account_and_agreement
        """
        s, invm, invs = _settled_account_in_default(api)
        ac, ag = s["account"], s["agreement"]
        # Precondition: the settle sweep suspended both (ACCOUNT_DEFAULT).
        assert validate_success(api.get_account(ac["id"], FIN))["status"] == "SUSPENDED"
        mid = validate_success(api.get_agreement(ag["id"], REP))
        assert mid["status"] == "SUSPENDED" and mid["suspension_reason"] == "ACCOUNT_DEFAULT"
        _pay_both(api, ac["id"], invm, invs)
        m = validate_success(api.get_invoice(invm["id"], FIN))
        sh = validate_success(api.get_invoice(invs["id"], FIN))
        assert m["status"] == "PAID", "link 1: 109000 allocation covers amount_due incl. late fee"
        assert sh["status"] == "PAID"
        account = validate_success(api.get_account(ac["id"], FIN))
        assert account["balance_due_cents"] == 0, "link 2: ledger recompute"
        assert account["status"] == "ACTIVE", "link 3: auto-reinstate on zero balance"
        agreement = validate_success(api.get_agreement(ag["id"], REP))
        assert agreement["status"] == "ACTIVE", "link 4: auto-cure of ACCOUNT_DEFAULT"
        assert agreement["suspension_reason"] is None
        assert agreement["suspension_count"] == 1

    def test_lifetime_spend_accumulates_cleared_amounts(self, api: ApiClient):
        """PRD §3.4: "Link two: the account's `balance_due_cents` recomputes downward
        and `lifetime_spend_cents` grows by the payment's `amount_cents`."
        Design: Difficulty/transitive_cascade/payment_clear_four_link_cascade_reinstates_account_and_agreement
        """
        s, invm, invs = _settled_account_in_default(api)
        _pay_both(api, s["account"]["id"], invm, invs)
        account = validate_success(api.get_account(s["account"]["id"], FIN))
        assert account["lifetime_spend_cents"] == 16109000, (
            f"12000000 license fee + 4109000 settlement payment, got "
            f"{account['lifetime_spend_cents']}")


class TestSeasonSettleShortfallCascade:
    def _setup(self, api: ApiClient):
        s = setup_active_agreement(num_seasons=2, events_spec=[EVENT_E1],
                                   agreement_over=dict(term_seasons=2))
        ac, ag, event = s["account"], s["agreement"], s["events"][0]
        pay_invoice_in_full(ac["id"], get_license_fee_invoice(ag["id"]))
        set_clock("2026-08-20T00:00:00Z")
        order = validate_success(api.create_catering_order(
            {"event_id": event["id"], "suite_id": s["suite"]["id"],
             "agreement_id": ag["id"], "package_tier": "PREMIUM", "guest_count": 12,
             "lines": [
                 {"item_code": "APP", "description": "Sliders", "quantity": 2,
                  "unit_price_cents": 1250, "discount_pct": 0.10},
                 {"item_code": "PLT", "description": "Carving station", "quantity": 1,
                  "unit_price_cents": 4750},
                 {"item_code": "DES", "description": "Dessert bites", "quantity": 5,
                  "unit_price_cents": 640, "discount_pct": 0.25}]},
            make_account_holder_headers(ac["id"])),
            expected_status=201)
        validate_success(api.set_catering_order_status(
            order["id"], {"target_status": "CONFIRMED"}, ESM))
        complete_event(event["id"], "2027-02-16T00:00:00Z")
        return s

    def test_settle_creates_net_shortfall_invoice(self, api: ApiClient):
        """PRD §3.5: "when the accrued total falls short of that minimum, the
        difference — the shortfall, never negative — becomes an `F_B_SHORTFALL`
        invoice, created already `ISSUED` with `due_on` thirty days after the clock,
        and the account's `balance_due_cents` recomputes upward."
        Design: Difficulty/transitive_cascade/season_settle_shortfall_invoice_balance_standing_cascade
        """
        s = self._setup(api)
        settle_season(s["seasons"][0]["id"], "2027-02-20T00:00:00Z")
        sh = get_single_invoice({"agreement_id": s["agreement"]["id"],
                                 "invoice_type": "F_B_SHORTFALL"})
        assert sh["subtotal_cents"] == 3990600, "minimum 4000000 - net accrual 9400"
        assert sh["status"] == "ISSUED"
        account = validate_success(api.get_account(s["account"]["id"], FIN))
        assert account["balance_due_cents"] == 3990600

    def test_settle_keeps_good_standing_and_moves_agreement_to_expiring(self, api: ApiClient):
        """PRD §3.5: "an agreement whose last covered season is the one being settled
        becomes `RENEWED` when its `renewal_agreement_id` is set and `EXPIRED` otherwise
        ... while an agreement whose next covered season is its last becomes
        `EXPIRING`." PRD §3.2: "`credit_standing` is `HOLD` when any non-void invoice
        of the account is 30 or more days past due ... and otherwise `GOOD`."
        Design: Difficulty/transitive_cascade/season_settle_shortfall_invoice_balance_standing_cascade
        """
        s = self._setup(api)
        settle_season(s["seasons"][0]["id"], "2027-02-20T00:00:00Z")
        account = validate_success(api.get_account(s["account"]["id"], FIN))
        assert account["credit_standing"] == "GOOD", (
            "the fresh shortfall invoice (due 2027-03-22) is not yet past due")
        assert account["status"] == "ACTIVE"
        agreement = validate_success(api.get_agreement(s["agreement"]["id"], REP))
        assert agreement["status"] == "EXPIRING", "S2 is the last covered season"


class TestLateFees:
    def test_late_fee_boundary_29_vs_30_days(self, api: ApiClient):
        """PRD §3.4: "Late fees charge in thirty-day periods and only once at least
        thirty days have elapsed: at day 29 the fee is zero, and at exactly day 30 one
        full period has accrued. Each period contributes one and a half percent of the
        invoice's `subtotal_cents`."
        Design: Corner/calculations/late_fee_boundary_29_vs_30_days
        """
        set_clock("2026-08-01T00:00:00Z")
        account = make_active_account()
        inv = make_issued_invoice(account["id"], lines=[{"description": "Club deposit",
                                                         "quantity": 1,
                                                         "unit_price_cents": 1000000}],
                                  due_on="2026-08-20T00:00:00Z")
        set_clock("2026-09-18T00:00:00Z")
        d29 = validate_success(api.get_invoice(inv["id"], FIN))
        assert d29["late_fee_cents"] == 0 and d29["amount_due_cents"] == 1000000
        set_clock("2026-09-19T00:00:00Z")
        d30 = validate_success(api.get_invoice(inv["id"], FIN))
        assert d30["late_fee_cents"] == 15000, "one 1.5% period on 1000000"
        assert d30["amount_due_cents"] == 1015000

    def test_late_fee_floor_and_cap(self, api: ApiClient):
        """PRD §3.4: "The resulting `late_fee_cents` is zero while no full period has
        elapsed; otherwise it is the greater of a 2,500-cent floor and the raw accrual,
        but never more than a cap of fifteen percent of the subtotal rounded half-up."
        Design: Corner/calculations/late_fee_floor_and_cap
        """
        set_clock("2026-08-01T00:00:00Z")
        account = make_active_account()
        inv_a = make_issued_invoice(account["id"], lines=[{"description": "Small",
                                                           "quantity": 1,
                                                           "unit_price_cents": 100000}],
                                    due_on="2026-08-20T00:00:00Z")
        inv_b = make_issued_invoice(account["id"], lines=[{"description": "Big",
                                                           "quantity": 1,
                                                           "unit_price_cents": 1000000}],
                                    due_on="2026-08-20T00:00:00Z")
        set_clock("2026-09-19T00:00:00Z")  # 30 days past due: raw 1500 on 100000
        a = validate_success(api.get_invoice(inv_a["id"], FIN))
        assert a["late_fee_cents"] == 2500, "raw 1500 floored to the 2500 minimum"
        set_clock("2027-06-16T00:00:00Z")  # 300 days: 10 periods -> raw 150000 == 15% cap
        b = validate_success(api.get_invoice(inv_b["id"], FIN))
        assert b["late_fee_cents"] == 150000, "ten periods would give 150000; the cap binds here"

    def test_late_fee_not_charged_on_draft(self, api: ApiClient):
        """PRD §3.4: "For an invoice in `ISSUED` or `PARTIALLY_PAID`, days overdue is
        the number of whole days between `due_on` and the logical clock, clamped at
        zero so an invoice never accrues before its due date."
        Design: Corner/calculations/late_fee_not_charged_on_draft
        """
        account = make_account()
        inv = validate_success(api.create_invoice(
            {"account_id": account["id"],
             "lines": [{"description": "Misc", "quantity": 1, "unit_price_cents": 100000}],
             "due_on": "2026-08-20T00:00:00Z"}, FIN), expected_status=201)
        set_clock("2026-12-01T00:00:00Z")  # 103 days past due, but never ISSUED
        draft = validate_success(api.get_invoice(inv["id"], FIN))
        assert draft["status"] == "DRAFT"
        assert draft["late_fee_cents"] == 0
        assert draft["amount_due_cents"] == 100000


class TestPaymentValidationAndLifecycle:
    def test_payment_amount_must_equal_allocation_sum(self, api: ApiClient):
        """PRD §3.4: "a total that does not match the sum of allocations is
        `ERR_INVALID_REQUEST`."
        Design: Corner/validations/payment_amount_must_equal_allocation_sum
        """
        account = make_active_account()
        inv = make_issued_invoice(account["id"])
        resp = api.create_payment(
            {"account_id": account["id"], "amount_cents": 5000, "method": "ACH",
             "allocations": [{"invoice_id": inv["id"], "amount_cents": 4000}]}, FIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows = validate_paginated(api.list_payments(FIN, params={"account_id": account["id"]}))[0]
        assert rows == [], "a rejected payment must not persist"
        assert validate_success(api.get_invoice(inv["id"], FIN))["amount_paid_cents"] == 0

    def test_allocation_exceeds_invoice_due_rejected(self, api: ApiClient):
        """PRD §3.4: "no allocation may exceed its invoice's `amount_due_cents` (else
        `ERR_ALLOCATION_EXCEEDS_DUE`)".
        Design: Corner/validations/allocation_exceeds_invoice_due_rejected
        """
        account = make_active_account()
        inv = make_issued_invoice(account["id"])  # 5000 due
        resp = api.create_payment(
            {"account_id": account["id"], "amount_cents": 6000, "method": "ACH",
             "allocations": [{"invoice_id": inv["id"], "amount_cents": 6000}]}, FIN)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_EXCEEDS_DUE)

    def test_allocation_to_foreign_invoice_rejected(self, api: ApiClient):
        """PRD §3.4: "Every allocated invoice must belong to the payment's account
        (else `ERR_ALLOCATION_ACCOUNT_MISMATCH`)".
        Design: Corner/validations/allocation_to_foreign_invoice_rejected
        """
        ac_a = make_active_account()
        ac_b = make_active_account()
        inv_b = make_issued_invoice(ac_b["id"])
        resp = api.create_payment(
            {"account_id": ac_a["id"], "amount_cents": 5000, "method": "ACH",
             "allocations": [{"invoice_id": inv_b["id"], "amount_cents": 5000}]}, FIN)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_ACCOUNT_MISMATCH)

    def test_invoice_void_with_initiated_payment_rejected(self, api: ApiClient):
        """PRD §3.4: "Voiding is available from `DRAFT` or `ISSUED` to finance and
        admin, provided no payment in `INITIATED` or `CLEARED` allocates to the invoice
        (else `ERR_INVOICE_HAS_PAYMENTS`)".
        Design: Corner/validations/invoice_void_with_initiated_payment_rejected
        """
        account = make_active_account()
        inv = make_issued_invoice(account["id"])
        p = validate_success(api.create_payment(
            {"account_id": account["id"], "amount_cents": 5000, "method": "WIRE",
             "allocations": [{"invoice_id": inv["id"], "amount_cents": 5000}]}, FIN),
            expected_status=201)
        assert p["status"] == "INITIATED"
        resp = api.void_invoice(inv["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_INVOICE_HAS_PAYMENTS)
        assert validate_success(api.get_invoice(inv["id"], FIN))["status"] == "ISSUED"

    def test_invoice_void_terminal_lockdown(self, api: ApiClient):
        """PRD §3.4: "`PAID` and `VOID` are terminal for an invoice".
        Design: Corner/state_machines/invoice_void_terminal_lockdown
        """
        account = make_account()
        inv = validate_success(api.create_invoice(
            {"account_id": account["id"],
             "lines": [{"description": "Misc", "quantity": 1, "unit_price_cents": 5000}],
             "due_on": "2026-09-01T00:00:00Z"}, FIN), expected_status=201)
        validate_success(api.void_invoice(inv["id"], FIN))
        validate_error(api.void_invoice(inv["id"], FIN), ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        validate_error(api.issue_invoice(inv["id"], FIN), ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_payment_failed_terminal_lockdown(self, api: ApiClient):
        """PRD §3.4: "Marking `INITIATED` to `FAILED` simply records the failure with
        no ledger effects." and "`FAILED` and `REFUNDED` are terminal."
        Design: Corner/state_machines/payment_failed_terminal_lockdown
        """
        account = make_active_account()
        inv = make_issued_invoice(account["id"])
        p = validate_success(api.create_payment(
            {"account_id": account["id"], "amount_cents": 5000, "method": "CARD",
             "allocations": [{"invoice_id": inv["id"], "amount_cents": 5000}]}, FIN),
            expected_status=201)
        validate_success(api.set_payment_status(p["id"], {"target_status": "FAILED"}, FIN))
        resp = api.set_payment_status(p["id"], {"target_status": "CLEARED"}, FIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        invoice = validate_success(api.get_invoice(inv["id"], FIN))
        assert invoice["status"] == "ISSUED"
        assert invoice["amount_paid_cents"] == 0

    def test_invoice_void_locked_after_season_settled(self, api: ApiClient):
        """PRD §3.4: "Voiding is available from `DRAFT` or `ISSUED` to finance and
        admin, provided no payment in `INITIATED` or `CLEARED` allocates to the invoice
        (else `ERR_INVOICE_HAS_PAYMENTS`) and, when the invoice carries a `season_id`,
        that season is not `SETTLED` (else `ERR_SEASON_LOCKED`)".
        Design: Corner/validations/invoice_void_locked_after_season_settled
        """
        set_clock("2026-08-01T00:00:00Z")
        venue = make_venue()
        season = make_season(venue["id"])
        event = make_event(season["id"], **EVENT_E1)
        account = make_active_account()
        inv = validate_success(api.create_invoice(
            {"account_id": account["id"], "season_id": season["id"],
             "lines": [{"description": "Season-tagged", "quantity": 1,
                        "unit_price_cents": 5000}],
             "due_on": "2026-09-01T00:00:00Z"}, FIN), expected_status=201)
        validate_success(api.issue_invoice(inv["id"], FIN))
        complete_event(event["id"], "2027-02-16T00:00:00Z")
        settle_season(season["id"], "2027-02-16T00:00:00Z")
        resp = api.void_invoice(inv["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_SEASON_LOCKED)

    def test_derived_balance_reconciles_on_void(self, api: ApiClient):
        """PRD §3.4: "voiding recomputes the account balance downward"; §2.9: "no
        intermediate state is observable between a trigger and its cascaded effects."
        Design: Corner/cross_cutting_layers/derived_balance_reconciles_on_void
        """
        account = make_active_account()
        inv = make_issued_invoice(account["id"])
        before = validate_success(api.get_account(account["id"], FIN))
        assert before["balance_due_cents"] == 5000
        validate_success(api.void_invoice(inv["id"], FIN))
        after = validate_success(api.get_account(account["id"], FIN))
        assert after["balance_due_cents"] == 0


class TestRefundCompensation:
    def _setup_paid(self, api: ApiClient):
        set_clock("2026-08-01T00:00:00Z")
        make_venue()
        account = make_active_account()
        inv = make_issued_invoice(account["id"], lines=[{"description": "Club seat deposit",
                                                         "quantity": 1,
                                                         "unit_price_cents": 500000}],
                                  due_on="2026-08-20T00:00:00Z")
        return account, inv

    def test_clear_then_refund_restores_balance_exactly(self, api: ApiClient):
        """PRD §3.4: "Marking a `CLEARED` payment `REFUNDED` runs the compensation in
        reverse: each allocated invoice's `amount_paid_cents` falls by its allocation
        and re-opens as described above, the account's `balance_due_cents` recomputes
        upward by exactly the payment's `amount_cents` — so a clear followed by a
        refund nets the balance to zero".
        Design: Difficulty/compensating_invariant/payment_clear_then_refund_restores_balance_exactly
        """
        account, inv = self._setup_paid(api)
        assert validate_success(api.get_account(account["id"], FIN))["balance_due_cents"] == 500000
        p = pay_invoice_in_full(account["id"], inv)
        mid = validate_success(api.get_account(account["id"], FIN))
        assert mid["balance_due_cents"] == 0
        validate_success(api.set_payment_status(p["id"], {"target_status": "REFUNDED"}, FIN))
        final = validate_success(api.get_account(account["id"], FIN))
        assert final["balance_due_cents"] == 500000, "clear+refund must net to zero drift"
        invoice = validate_success(api.get_invoice(inv["id"], FIN))
        assert invoice["status"] == "ISSUED", "a fully refunded PAID invoice returns to ISSUED"
        assert invoice["amount_paid_cents"] == 0

    def test_refund_does_not_decrement_lifetime_spend(self, api: ApiClient):
        """PRD §3.4: "`lifetime_spend_cents` is the sum of `amount_cents` across the
        account's payments that have ever reached `CLEARED`; refunds do not decrement
        it, so the figure measures gross historical spend."
        Design: Difficulty/compensating_invariant/payment_clear_then_refund_restores_balance_exactly
        """
        account, inv = self._setup_paid(api)
        p = pay_invoice_in_full(account["id"], inv)
        cleared = validate_success(api.get_account(account["id"], FIN))
        assert cleared["lifetime_spend_cents"] == 500000
        validate_success(api.set_payment_status(p["id"], {"target_status": "REFUNDED"}, FIN))
        refunded = validate_success(api.get_account(account["id"], FIN))
        assert refunded["lifetime_spend_cents"] == 500000


class TestCreditStandingAndOcc:
    def test_manual_reinstate_blocked_while_credit_watch(self, api: ApiClient):
        """PRD §3.2: "A manual reinstate by finance or admin requires the account's
        `credit_standing` to be `GOOD` — meaning no invoice even a single day past due
        — and is otherwise rejected with `ERR_ACCOUNT_CREDIT_HOLD`."
        Design: Corner/validations/manual_reinstate_blocked_while_credit_watch
        """
        set_clock("2026-08-01T00:00:00Z")
        account = make_active_account()
        make_issued_invoice(account["id"], due_on="2026-08-20T00:00:00Z")
        validate_success(api.set_account_status(account["id"], {"target_status": "SUSPENDED"}, FIN))
        set_clock("2026-08-30T00:00:00Z")  # 10 days past due -> WATCH, not GOOD
        resp = api.set_account_status(account["id"], {"target_status": "ACTIVE"}, FIN)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_CREDIT_HOLD)
        assert validate_success(api.get_account(account["id"], FIN))["status"] == "SUSPENDED"

    def test_occ_account_profile_update_stale_version(self, api: ApiClient):
        """PRD §2.7: "Updating an account profile (`PATCH /api/accounts/{id}`) requires
        `expected_account_version`, the client last observed `version` of the Account.
        ... a profile edit carrying an older version is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        Design: Corner/cross_cutting_layers/occ_account_profile_update_stale_version
        """
        account = make_account()
        v1 = account["version"]
        updated = validate_success(api.update_account(
            account["id"], {"billing_email": "new@acme.example",
                            "expected_account_version": v1}, REP))
        assert updated["billing_email"] == "new@acme.example"
        assert updated["version"] == v1 + 1
        stale = api.update_account(
            account["id"], {"billing_email": "other@acme.example",
                            "expected_account_version": v1}, REP)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        final = validate_success(api.get_account(account["id"], FIN))
        assert final["billing_email"] == "new@acme.example"


class TestMidSeasonProration:
    def test_first_season_proration_mid_season_execute(self, api: ApiClient):
        """PRD §3.3: "The proration ratio is the number of covered events whose
        `starts_at` falls at or after `executed_on`, divided by the total number of
        covered events in the start season. The season-one invoice charges
        `fee_schedule_cents` entry one multiplied by that ratio, rounded half-up";
        covered events are "its events of type `REGULAR` or `RIVALRY` that are not
        `CANCELLED`".
        Design: Corner/calculations/first_season_proration_mid_season_execute
        """
        events = [
            dict(name="G1", event_type="REGULAR", starts_at="2026-09-10T17:00:00Z"),
            dict(name="G2", event_type="RIVALRY", starts_at="2026-10-05T17:00:00Z",
                 rental_base_price_cents=650000),
            dict(name="G3", event_type="REGULAR", starts_at="2026-11-12T18:00:00Z"),
            dict(name="G4", event_type="RIVALRY", starts_at="2026-12-20T17:00:00Z",
                 rental_base_price_cents=700000),
            dict(name="P1", event_type="PLAYOFF", starts_at="2027-01-10T20:00:00Z",
                 duration_hours=5, rental_base_price_cents=1200000),
        ]
        s = setup_active_agreement(num_seasons=1, events_spec=events,
                                   execute_clock="2026-10-20T00:00:00Z")
        inv = get_license_fee_invoice(s["agreement"]["id"])
        assert inv["subtotal_cents"] == 6000000, (
            f"2 of 4 covered events remain (PLAYOFF excluded from both counts), got "
            f"{inv['subtotal_cents']}")
        ag = validate_success(api.get_agreement(s["agreement"]["id"], REP))
        assert ag["fee_schedule_cents"] == [12000000], (
            "the schedule itself is not prorated; only the first-season invoice is")
