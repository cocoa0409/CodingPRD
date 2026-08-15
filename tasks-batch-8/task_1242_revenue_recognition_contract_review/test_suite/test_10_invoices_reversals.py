"""Billing, invoice voiding, reversals, and the dual-ledger identity
(PRD §2.11, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    create_invoice_payload,
    create_period, set_clock, get_contract, get_pob,
    setup_active_contract_with_pob,
    assert_invoice, assert_revenue_entry, assert_contract_ledger_identity,
)

CLOCK = "2026-06-15T00:00:00Z"


def _active_pit(fixed=500000):
    return setup_active_contract_with_pob(fixed=fixed)


class TestBillingCap:
    def _setup(self):
        return setup_active_contract_with_pob(fixed=500000)

    def test_billing_at_price_allowed(self, api, accountant_headers):
        """PRD §3.7: "the cumulative total of issued, non-voided billings may
        not exceed the contract's current `transaction_price_cents`, and an
        invoice that would push billings past the price is rejected with
        `ERR_BILLING_EXCEEDS_PRICE` (HTTP 422)."

        Design: Corner/validations/billing_at_price_allowed_beyond_rejected
        """
        setup = self._setup()
        resp = api.create_invoice(
            setup["contract"]["id"],
            create_invoice_payload(invoice_ref="INV-FULL", amount_cents=500000),
            accountant_headers,
        )
        invoice = validate_success(resp, 201)
        assert_invoice(invoice)
        assert invoice["status"] == "ISSUED"
        contract = get_contract(setup["contract"]["id"])
        assert contract["billed_to_date_cents"] == 500000
        assert contract["deferred_revenue_balance_cents"] == 500000
        assert_contract_ledger_identity(contract)

    def test_billing_one_cent_beyond_rejected(self, api, accountant_headers):
        """PRD §3.7: "the cumulative total of issued, non-voided billings may
        not exceed the contract's current `transaction_price_cents`, and an
        invoice that would push billings past the price is rejected with
        `ERR_BILLING_EXCEEDS_PRICE` (HTTP 422)."

        Design: Corner/validations/billing_at_price_allowed_beyond_rejected
        """
        setup = self._setup()
        validate_success(api.create_invoice(
            setup["contract"]["id"],
            create_invoice_payload(invoice_ref="INV-FULL", amount_cents=500000),
            accountant_headers,
        ), 201)
        resp = api.create_invoice(
            setup["contract"]["id"],
            create_invoice_payload(invoice_ref="INV-OVER", amount_cents=1,
                                   invoice_date="2026-06-06"),
            accountant_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BILLING_EXCEEDS_PRICE, 422)
        assert get_contract(setup["contract"]["id"])["billed_to_date_cents"] == 500000


class TestInvoiceAmounts:
    def test_zero_amount_rejected(self, api, accountant_headers):
        """PRD §3.7: "a `RevenueAccountant` issues an invoice against an
        `ACTIVE` contract — any other contract state fails with
        `ERR_CONTRACT_NOT_ACTIVE` — supplying an `invoice_ref` unique per
        invoice, an `amount_cents` greater than zero, and an `invoice_date` that
        must fall inside an `OPEN` or `REOPENED` accounting period, failing with
        `ERR_PERIOD_CLOSED` otherwise. Non-positive amounts fail with
        `ERR_INVALID_AMOUNT`."

        Design: Corner/errors/invoice_non_positive_amount_returns_invalid_amount
        """
        setup = setup_active_contract_with_pob(fixed=500000)
        resp = api.create_invoice(
            setup["contract"]["id"],
            create_invoice_payload(invoice_ref="INV-ZERO", amount_cents=0),
            accountant_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT, 422)

    def test_zero_amount_leaves_billings_untouched(self, api, accountant_headers):
        """PRD §3.7: "Non-positive amounts fail with `ERR_INVALID_AMOUNT`."
        PRD §2.11: "`billed_to_date_cents` is the sum of `amount_cents` over the
        contract's `ISSUED` invoices minus the amounts of its `VOIDED`
        invoices."

        Design: Corner/errors/invoice_non_positive_amount_returns_invalid_amount
        """
        setup = setup_active_contract_with_pob(fixed=500000)
        validate_error(api.create_invoice(
            setup["contract"]["id"],
            create_invoice_payload(invoice_ref="INV-ZERO", amount_cents=0),
            accountant_headers,
        ), ApiErrorId.ERR_INVALID_AMOUNT, 422)
        assert get_contract(setup["contract"]["id"])["billed_to_date_cents"] == 0


class TestInvoiceVoid:
    def _setup_voided(self, api, accountant_headers, manager_headers):
        setup = setup_active_contract_with_pob(fixed=500000)
        invoice = validate_success(api.create_invoice(
            setup["contract"]["id"],
            create_invoice_payload(invoice_ref="INV-V", amount_cents=100000),
            accountant_headers,
        ), 201)
        validate_success(api.void_invoice(invoice["id"], manager_headers))
        return setup, invoice

    def test_second_void_rejected(self, api, accountant_headers, manager_headers):
        """PRD §3.7: "A `RevenueManager` voids an `ISSUED` invoice, moving it to
        the terminal `VOIDED` state".
        PRD §3.4: "Any attempt to drive a contract through a transition that
        does not exist from its current state is rejected with
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/invoice_double_void_returns_invalid_state_transition
        """
        _, invoice = self._setup_voided(api, accountant_headers, manager_headers)
        resp = api.void_invoice(invoice["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    def test_void_applied_exactly_once(self, api, accountant_headers, manager_headers):
        """PRD §3.7: "Voiding subtracts the invoice's amount from
        `billed_to_date_cents`, recomputes both balances, records
        `voided_by_user_id` from the caller's `X-User-ID`, re-evaluates
        auto-completion, and bumps the contract's `version`."

        Design: Corner/state_machines/invoice_double_void_returns_invalid_state_transition
        """
        setup, invoice = self._setup_voided(api, accountant_headers, manager_headers)
        validate_error(api.void_invoice(invoice["id"], manager_headers),
                       ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        contract = get_contract(setup["contract"]["id"])
        assert contract["billed_to_date_cents"] == 0
        assert_contract_ledger_identity(contract)


class TestLedgerIdentityAcrossVoid:
    def _setup(self, api, accountant_headers):
        setup = setup_active_contract_with_pob(
            ssp_cents=500000, fixed=500000,
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 100000},
        )
        invoice = validate_success(api.create_invoice(
            setup["contract"]["id"],
            create_invoice_payload(invoice_ref="INV-1", amount_cents=400000),
            accountant_headers,
        ), 201)
        return setup, invoice

    def test_identity_after_issue(self, api, accountant_headers):
        """PRD §2.11: "An identity follows and holds after every event —
        invoice issue, invoice void, entry posting of any origin, and reversal
        alike: billings minus recognition always equals deferred revenue minus
        contract asset."

        Design: Difficulty/compensating_invariant/invariant_billed_recognized_identity_across_invoice_void
        """
        setup, _ = self._setup(api, accountant_headers)
        contract = get_contract(setup["contract"]["id"])
        assert contract["billed_to_date_cents"] == 400000
        assert contract["recognized_to_date_cents"] == 0
        assert contract["deferred_revenue_balance_cents"] == 400000
        assert contract["contract_asset_balance_cents"] == 0
        assert_contract_ledger_identity(contract)

    def test_identity_after_recognition(self, api, accountant_headers):
        """PRD §2.11: "An identity follows and holds after every event —
        invoice issue, invoice void, entry posting of any origin, and reversal
        alike: billings minus recognition always equals deferred revenue minus
        contract asset."

        Design: Difficulty/compensating_invariant/invariant_billed_recognized_identity_across_invoice_void
        """
        setup, _ = self._setup(api, accountant_headers)
        validate_success(api.create_cost_entry(
            setup["pob"]["id"], {"amount_cents": 30000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        contract = get_contract(setup["contract"]["id"])
        # 30% of 500000 = 150000 recognized; billed still 400000.
        assert contract["billed_to_date_cents"] == 400000
        assert contract["recognized_to_date_cents"] == 150000
        assert contract["deferred_revenue_balance_cents"] == 250000
        assert contract["contract_asset_balance_cents"] == 0
        assert_contract_ledger_identity(contract)

    def test_identity_after_void_compensates_issue(self, api, accountant_headers, manager_headers):
        """PRD §2.11: "billings minus recognition always equals deferred revenue
        minus contract asset. Both balances can never be positive at once, and
        neither can ever be negative."
        PRD §3.7: "Voiding subtracts the invoice's amount from
        `billed_to_date_cents`".

        Design: Difficulty/compensating_invariant/invariant_billed_recognized_identity_across_invoice_void
        """
        setup, invoice = self._setup(api, accountant_headers)
        validate_success(api.create_cost_entry(
            setup["pob"]["id"], {"amount_cents": 30000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        validate_success(api.void_invoice(invoice["id"], manager_headers))
        contract = get_contract(setup["contract"]["id"])
        assert contract["billed_to_date_cents"] == 0
        assert contract["recognized_to_date_cents"] == 150000
        assert contract["deferred_revenue_balance_cents"] == 0
        assert contract["contract_asset_balance_cents"] == 150000
        assert_contract_ledger_identity(contract)


class TestReversals:
    def _setup_locked_and_posted(self, api, accountant_headers, controller_headers):
        """E1 LOCKED in closed May; then a June cost entry E2 POSTED."""
        may = create_period(period_code="2026-05", start_date="2026-05-01", end_date="2026-06-01")
        june = create_period(period_code="2026-06", start_date="2026-06-01", end_date="2026-07-01")
        set_clock("2026-05-15T00:00:00Z")
        setup = setup_active_contract_with_pob(
            product_code="ICA", signed_date="2026-05-05", with_period=False, clock=None,
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 40000},
        )
        pob = setup["pob"]
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 10000, "incurred_date": "2026-05-10"},
            accountant_headers,
        ), 201)
        e1 = validate_paginated(api.list_revenue_entries(
            accountant_headers, params={"pob_id": pob["id"]}))[0][0]
        validate_success(api.close_accounting_period(may["id"], controller_headers))
        set_clock(CLOCK)
        return setup, may, june, pob, e1

    def test_locked_entry_reversal_rejected(self, api, accountant_headers, controller_headers):
        """PRD §3.7: "reversing an entry whose period has already closed — and
        whose status is therefore `LOCKED` — is rejected with `ERR_ENTRY_LOCKED`
        (HTTP 409)."

        Design: Corner/validations/locked_entry_reversal_rejected
        """
        _, _, _, _, e1 = self._setup_locked_and_posted(api, accountant_headers, controller_headers)
        resp = api.reverse_revenue_entry(e1["id"], {}, accountant_headers)
        validate_error(resp, ApiErrorId.ERR_ENTRY_LOCKED, 409)

    def test_posted_entry_reversal_posts_negated_entry(self, api, accountant_headers, controller_headers):
        """PRD §3.7: "The reversal takes an optional `reason` and creates a new
        revenue entry with `entry_type` `REVERSAL`: its `amount_cents` is the
        exact negation of the reversed entry's amount, its `reversed_entry_id`
        points at the reversed entry, its `posting_date` is the current clock
        date, and its `origin` is `REVERSAL`."

        Design: Corner/validations/locked_entry_reversal_rejected
        """
        setup, _, june, pob, _ = self._setup_locked_and_posted(api, accountant_headers, controller_headers)
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 5000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        e2 = validate_paginated(api.list_revenue_entries(
            accountant_headers,
            params={"pob_id": pob["id"], "accounting_period_id": june["id"]},
        ))[0][0]
        assert e2["amount_cents"] == 12500, (
            "target at 15000/40000 of 100000 = 37500; already posted 25000 -> 12500"
        )
        reversal = validate_success(api.reverse_revenue_entry(
            e2["id"], {"reason": "correction"}, accountant_headers,
        ), 201)
        assert_revenue_entry(reversal)
        assert reversal["entry_type"] == "REVERSAL"
        assert reversal["amount_cents"] == -12500
        assert reversal["reversed_entry_id"] == e2["id"]
        assert reversal["origin"] == "REVERSAL"

    def test_reversal_recomputes_recognized_total(self, api, accountant_headers, controller_headers):
        """PRD §3.7: "Posting a reversal recomputes the contract and period
        aggregates, re-evaluates auto-completion, and bumps the contract's
        `version`."

        Design: Corner/validations/locked_entry_reversal_rejected
        """
        setup, _, june, pob, _ = self._setup_locked_and_posted(api, accountant_headers, controller_headers)
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 5000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        e2 = validate_paginated(api.list_revenue_entries(
            accountant_headers,
            params={"pob_id": pob["id"], "accounting_period_id": june["id"]},
        ))[0][0]
        validate_success(api.reverse_revenue_entry(e2["id"], {"reason": "correction"}, accountant_headers), 201)
        # 25000 (May, LOCKED) + 12500 - 12500 = 25000 recognized on the POB.
        assert get_pob(pob["id"])["recognized_revenue_cents"] == 25000
