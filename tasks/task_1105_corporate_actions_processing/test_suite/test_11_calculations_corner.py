"""Calculation corner claims (PRD §3.4, §3.6, §3.9): dividend firm amounts,
spin-off basis precision, zero-tolerance reconciliation, entitlement input set.
"""
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    make_security, make_account, make_lot, set_clock,
    make_confirmed_event, make_custodian_source, submit_statement,
    make_scrubbed_event, split_terms, cash_dividend_terms, spinoff_terms,
)
from test_helpers.fixtures import OPS
from test_helpers import api_client


class TestCashDividendFirmAmount:
    def test_firm_dividend_entitlement_amounts(self, api):
        """PRD §3.4: "For a `CASH_DIVIDEND`, `entitled_shares` and `fractional_shares` are both zero, and `cash_amount_cents` is the record position quantity rounded down to a whole share and multiplied by the terms' `cash_per_share_cents`." PRD §3.6: "the entitlement moves `PROJECTED` → `FIRM` with its `version` incremented".

        Design: Corner/calculations/cash_dividend_firm_amount_literal
        """
        sec = make_security(ticker="ACME", cusip="CUSPC00001")
        acct = make_account(account_number="A-1", holder_name="One")
        make_lot(acct["id"], sec["id"], quantity=1000,
                 acquisition_date="2026-04-01", cost_basis_total_cents=10000000)
        event, _, _ = make_confirmed_event(
            sec["id"], "CASH_DIVIDEND",
            cash_dividend_terms(cash_per_share_cents=250))
        set_clock("2026-05-15T00:00:00Z")
        validate_success(api.capture_record_position(event["id"], OPS))
        ent = api_client.list_entitlements(
            OPS, params={"event_id": event["id"], "account_id": acct["id"]}
        ).json()["data"][0]
        assert ent["status"] == "FIRM"
        assert ent["cash_amount_cents"] == 250000  # 1000 x 250
        assert ent["entitled_shares"] == 0
        assert ent["fractional_shares"] == 0


class TestSpinoffBasisAllocation:
    def test_spinoff_basis_split_four_dp_precision(self, api):
        """PRD §3.6: "The basis split percentage is the terms' `fmv_spin_cents` divided by the sum of `fmv_parent_cents` and `fmv_spin_cents`, rounded half-up to four decimal places before any lot is touched. Then, per lot in the pinned order: the spin lot's basis is the parent lot's `cost_basis_total_cents` multiplied by that percentage, rounded half-up to whole cents; the parent keeps the remainder, so the parent lot's basis becomes its old basis minus the spin lot's basis — conservation is exact per lot, with no drift. A new spin-co lot is created whose quantity is the parent lot's quantity multiplied by the ratio, rounded down to a whole share, whose `cost_basis_total_cents` is the spin basis just computed, whose `acquisition_date` is inherited from the parent lot, and whose `origin_booking_id` points to this booking."

        Design: Corner/calculations/spinoff_basis_allocation_four_dp
        """
        sec = make_security(ticker="ACME", cusip="CUSPC00002")
        spn = make_security(ticker="SPN", cusip="CUSPC00003", name="Spinco Ltd")
        acct = make_account(account_number="A-1", holder_name="One")
        parent_lot = make_lot(acct["id"], sec["id"], quantity=1000,
                              acquisition_date="2026-04-01",
                              cost_basis_total_cents=10000000)
        terms = spinoff_terms(spn["id"])
        event, _, _ = make_confirmed_event(sec["id"], "SPIN_OFF", terms)
        set_clock("2026-05-15T00:00:00Z")
        get_success_data(api_client.capture_record_position(event["id"], OPS))
        booking = validate_success(api.book_event(event["id"], OPS), 201)
        parent_after = get_success_data(api.get_position_lot(parent_lot["id"], OPS))
        # pct = round4(1234/11011) = 0.1121; spin basis = 10000000 x 0.1121 = 1121000
        assert parent_after["quantity"] == 1000
        assert parent_after["cost_basis_total_cents"] == 8879000
        resp = api.list_position_lots(
            OPS, params={"account_id": acct["id"], "security_id": spn["id"]})
        spn_lots = resp.json()["data"]
        assert len(spn_lots) == 1
        spn_lot = spn_lots[0]
        assert spn_lot["quantity"] == 200  # floor(1000 x 1/5)
        assert spn_lot["cost_basis_total_cents"] == 1121000
        assert spn_lot["origin_booking_id"] == booking["id"]
        assert spn_lot["acquisition_date"] == "2026-04-01"
        # Per-lot conservation: exact, no drift.
        assert (parent_after["cost_basis_total_cents"]
                + spn_lot["cost_basis_total_cents"]) == 10000000


class TestExactPositionMatchNoBreak:
    def test_zero_difference_creates_no_break(self, api):
        """PRD §3.9: "The comparison is zero-tolerance — exact equality is the only outcome that raises no break." and "the create response already shows the statement `RECONCILED` (having briefly been `RECEIVED`)".

        Design: Corner/calculations/exact_position_match_creates_no_break
        """
        sec = make_security(ticker="ACME", cusip="CUSPC00004")
        acct = make_account(account_number="A-1", holder_name="One")
        make_lot(acct["id"], sec["id"], quantity=1000,
                 acquisition_date="2026-04-01", cost_basis_total_cents=10000000)
        cust = make_custodian_source()
        stmt = submit_statement(
            cust["id"], "2026-05-01", "2026-05-14",
            [{"account_id": acct["id"], "security_id": sec["id"],
              "quantity": 1000}])
        assert stmt["status"] == "RECONCILED"
        _, meta = validate_paginated(
            api.list_recon_breaks(OPS, params={"statement_id": stmt["id"]}))
        assert meta["total_count"] == 0


class TestConfirmExcludesLotlessAccounts:
    def test_only_accounts_with_open_lots_get_entitlements(self, api):
        """PRD §3.4: "The moment an event is first confirmed, the system projects its entitlements: for every account holding at least one `OPEN` position lot in the event's security whose included position is greater than zero, a `PROJECTED` entitlement is created".

        Design: Corner/calculations/confirm_excludes_lotless_accounts
        """
        sec = make_security(ticker="ACME", cusip="CUSPC00005")
        aw = make_account(account_number="AW-1", holder_name="With")
        ax = make_account(account_number="AX-1", holder_name="Without")
        make_lot(aw["id"], sec["id"], quantity=100,
                 acquisition_date="2026-04-01", cost_basis_total_cents=500000)
        event, _, _ = make_scrubbed_event(sec["id"], "SPLIT", split_terms())
        from test_helpers.fixtures import ANALYST_2
        validate_success(api.confirm_event(event["id"], ANALYST_2))
        data, meta = validate_paginated(
            api.list_entitlements(OPS, params={"event_id": event["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["account_id"] == aw["id"]
        assert data[0]["entitled_shares"] == 200
        _, meta_ax = validate_paginated(
            api.list_entitlements(
                OPS, params={"event_id": event["id"], "account_id": ax["id"]}))
        assert meta_ax["total_count"] == 0
