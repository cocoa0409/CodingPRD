"""Booking calculation rules (PRD §3.6): merger proration waterfall,
per-lot floor-then-sum cash-in-lieu, and rights oversubscription single pass.
"""
from test_helpers import (
    validate_success, get_success_data,
    make_security, make_account, make_lot, set_clock,
    make_confirmed_event, make_account_holder_headers,
    merger_terms, split_terms, rights_terms, get_event_version,
)
from test_helpers.fixtures import ADMIN, OPS, ANALYST_2
from test_helpers import api_client


def _merger_three_accounts(shares_list, pool=900000):
    """Create ACME + NEWCO, one account per share count, voluntary MERGER
    confirmed and captured at 2026-05-15; all accounts elect CASH."""
    sec = make_security(ticker="ACME")
    newco = make_security(ticker="NWC", name="Newco Inc")
    accounts = []
    for i, sh in enumerate(shares_list, start=1):
        acct = make_account(account_number=f"A-{i}", holder_name=f"H{i}")
        make_lot(acct["id"], sec["id"], quantity=sh,
                 acquisition_date="2026-04-01",
                 cost_basis_total_cents=sh * 5000)
        accounts.append(acct)
    terms = merger_terms(newco["id"], cash_per_share_cents=5000,
                         cash_pool_cents=pool, default_option="STOCK")
    event, _, _ = make_confirmed_event(
        sec["id"], "MERGER", terms, record_date="2026-05-15",
        payable_date="2026-05-29", election_required=True,
        election_deadline="2026-05-20T16:00:00Z")
    set_clock("2026-05-15T00:00:00Z")
    get_success_data(api_client.capture_record_position(event["id"], OPS))
    for acct in accounts:
        v = get_event_version(event["id"])
        get_success_data(api_client.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "CASH",
             "expected_event_version": v},
            make_account_holder_headers(acct["id"])))
    set_clock("2026-05-21T00:00:00Z")
    return sec, newco, accounts, event


class TestMergerProrationOddLotWaterfall:
    def test_odd_lot_paid_in_full_round_lots_prorated(self, api):
        """PRD §3.6: "Odd-lot accounts that elected `CASH` are honored in full first, at their shares multiplied by the terms' `cash_per_share_cents"
        and "Each round-lot cash elector then receives cash for its shares multiplied by the factor, rounded down to whole shares, paid at `cash_per_share_cents`; its remaining shares convert into the new security at the terms' ratio".

        Design: Difficulty/combinatorial_formula/merger_proration_odd_lot_waterfall
        """
        sec, newco, accounts, event = _merger_three_accounts([120, 120, 99])
        booking = validate_success(api.book_event(event["id"], OPS), 201)
        a1, a2, a3 = accounts
        a3_after = get_success_data(api.get_account(a3["id"], OPS))
        assert a3_after["cash_balance_cents"] == 495000  # 99 x 5000, in full
        a1_after = get_success_data(api.get_account(a1["id"], OPS))
        # factor = floor4((900000-495000)/1200000) = floor4(0.3375) = 0.3375
        # cash shares = floor(120 x 0.3375) = 40 -> 200000 cents
        assert a1_after["cash_balance_cents"] == 200000

    def test_proration_booking_totals_and_stock_conversion(self, api):
        """PRD §3.6: "The booking's three totals summarize the cascade: `total_whole_shares_credited` is the sum of whole shares credited across all `SETTLED` entitlements in the booking; `total_cash_credited_cents` is the sum of every cash credit — dividends and merger cash legs — with rights debits excluded" and "Any pool left over is retained by the
        desk; there is no redistribution pass."

        Design: Difficulty/combinatorial_formula/merger_proration_odd_lot_waterfall
        """
        sec, newco, accounts, event = _merger_three_accounts([120, 120, 99])
        booking = validate_success(api.book_event(event["id"], OPS), 201)
        a1 = accounts[0]
        assert booking["total_cash_credited_cents"] == 895000
        assert booking["total_whole_shares_credited"] == 160
        # A1 converts remaining 80 shares to NEWCO 1:1
        resp = api.list_position_lots(
            OPS, params={"account_id": a1["id"], "security_id": newco["id"]})
        rows = resp.json()["data"]
        assert len(rows) == 1
        assert rows[0]["quantity"] == 80


class TestCashInLieuPerLotFloorThenSum:
    def _setup(self):
        sec = make_security(ticker="ACME")
        acct = make_account(account_number="A-1", holder_name="One")
        l1 = make_lot(acct["id"], sec["id"], quantity=10.5,
                      acquisition_date="2026-04-01", cost_basis_total_cents=105000)
        l2 = make_lot(acct["id"], sec["id"], quantity=10.6,
                      acquisition_date="2026-04-02", cost_basis_total_cents=106000)
        terms = split_terms(ratio_num=3, ratio_den=2, price_per_share_cents=3333,
                            fractional_policy="ROUND_HALF_UP")
        event, _, _ = make_confirmed_event(sec["id"], "SPLIT", terms)
        resp = api_client.list_entitlements(
            OPS, params={"event_id": event["id"], "account_id": acct["id"]})
        projected = resp.json()["data"][0]
        set_clock("2026-05-15T00:00:00Z")
        get_success_data(api_client.capture_record_position(event["id"], OPS))
        return sec, acct, l1, l2, event, projected

    def test_aggregate_projection_floors_the_sum(self, api):
        """PRD §3.4: "the gross entitlement is the record position quantity multiplied by that ratio; `entitled_shares` is the gross rounded down to a whole share; `fractional_shares` is the remainder after removing that whole-share floor, rounded half-up to four decimal places; and `cash_in_lieu_cents` is the fractional shares multiplied by the terms' `price_per_share_cents`, rounded per the event's `fractional_policy`."
        PRD §2.6: "the desk computes per lot first and sums second, and a sum
        of per-lot floors is not the same as the floor of the sum."

        Design: Difficulty/combinatorial_formula/cash_in_lieu_per_lot_floor_then_sum
        """
        _, _, _, _, _, projected = self._setup()
        # aggregate: 21.1 x 1.5 = 31.65 -> floor 31, frac 0.65 -> 2166 cents
        assert projected["entitled_shares"] == 31
        assert projected["cash_in_lieu_cents"] == 2166

    def test_booked_actuals_floor_per_lot_then_sum(self, api):
        """PRD §3.6: "For each lot in order: the exact entitlement is the lot's quantity multiplied by the ratio (`ratio_num` divided by `ratio_den`); the whole-share part is that exact value rounded down; the lot's fractional part is the exact value minus that floor; and the lot's quantity is set to the whole-share part at four decimal places. After all lots are processed, the account's fractional position is the sum of the per-lot fractional parts, rounded half-up to four decimal places; the entitlement's `booked_whole_shares` is the sum of the per-lot whole-share floors; and its `booked_cash_in_lieu_cents` is the account fractional position multiplied by the terms' `price_per_share_cents`, rounded per the event's `fractional_policy` as defined in §2.6."
        PRD §3.6: "a split or stock dividend leaves each lot's `cost_basis_total_cents` unchanged, because per-share basis is derived and never stored."

        Design: Difficulty/combinatorial_formula/cash_in_lieu_per_lot_floor_then_sum
        """
        _, acct, l1, l2, event, projected = self._setup()
        validate_success(api.book_event(event["id"], OPS), 201)
        ent = get_success_data(api.get_entitlement(projected["id"], OPS))
        # per-lot: 10.5x1.5=15.75->15 (frac .75); 10.6x1.5=15.9->15 (frac .9)
        # frac sum 1.65 -> 1.65 x 3333 = 5499.45 -> 5499 ROUND_HALF_UP
        assert ent["booked_whole_shares"] == 30
        assert ent["booked_cash_in_lieu_cents"] == 5499
        l1_after = get_success_data(api.get_position_lot(l1["id"], OPS))
        l2_after = get_success_data(api.get_position_lot(l2["id"], OPS))
        assert l1_after["quantity"] == 15
        assert l2_after["quantity"] == 15
        assert l1_after["cost_basis_total_cents"] == 105000
        assert l2_after["cost_basis_total_cents"] == 106000
        acct_after = get_success_data(api.get_account(acct["id"], OPS))
        assert acct_after["cash_balance_cents"] == 5499


class TestRightsOversubscriptionSinglePass:
    def _setup(self):
        sec = make_security(ticker="ACME")
        a1 = make_account(account_number="A-1", holder_name="One")
        a2 = make_account(account_number="A-2", holder_name="Two")
        make_lot(a1["id"], sec["id"], quantity=100,
                 acquisition_date="2026-04-01", cost_basis_total_cents=400000)
        make_lot(a2["id"], sec["id"], quantity=100,
                 acquisition_date="2026-04-01", cost_basis_total_cents=400000)
        terms = rights_terms(shares_offered=1000, subscription_price_cents=400,
                             oversubscription_allowed=True)
        event, _, _ = make_confirmed_event(
            sec["id"], "RIGHTS_OFFERING", terms, election_required=True,
            election_deadline="2026-05-20T16:00:00Z")
        set_clock("2026-05-15T00:00:00Z")
        get_success_data(api_client.capture_record_position(event["id"], OPS))
        for acct, qty in ((a1, 150), (a2, 250)):
            v = get_event_version(event["id"])
            get_success_data(api_client.submit_election(
                event["id"],
                {"account_id": acct["id"], "option_code": "EXERCISE",
                 "quantity": qty, "expected_event_version": v},
                make_account_holder_headers(acct["id"])))
        set_clock("2026-05-21T00:00:00Z")
        return sec, a1, a2, event

    def test_oversubscription_allocations_and_debits(self, api):
        """PRD §3.6: "Each `EXERCISE` election first receives its basic allocation: the smaller of its requested `quantity` and its entitled rights. The exercised total is the sum of those basics, and the remainder is the terms' `shares_offered` minus the exercised total, floored at zero." and "Each oversubscriber's excess allocation is the
        smaller of its requested excess and its proportional share of the
        remainder — the remainder multiplied by its entitled rights and divided
        by the total entitled rights across all oversubscribers — rounded down
        to whole shares".

        Design: Difficulty/combinatorial_formula/rights_oversubscription_single_pass
        """
        sec, a1, a2, event = self._setup()
        validate_success(api.book_event(event["id"], OPS), 201)
        # remainder = 1000 - 200 = 800; each over share = 800 x 100/200 = 400
        # A1 over = min(50, 400) = 50 -> 150 x 400 = 60000 debit
        a1_after = get_success_data(api.get_account(a1["id"], OPS))
        assert a1_after["cash_balance_cents"] == -60000
        # A2 over = min(150, 400) = 150 -> 250 x 400 = 100000 debit
        a2_after = get_success_data(api.get_account(a2["id"], OPS))
        assert a2_after["cash_balance_cents"] == -100000

    def test_single_pass_leaves_remainder_with_issuer(self, api):
        """PRD §3.6: "Exactly one proration pass runs — whatever remains unallocated after it is retained by the issuer." and "The final allocation is basic plus excess, and the account is debited its allocation multiplied by the terms' `subscription_price_cents`".

        Design: Difficulty/combinatorial_formula/rights_oversubscription_single_pass
        """
        sec, a1, a2, event = self._setup()
        booking = validate_success(api.book_event(event["id"], OPS), 201)
        # 150 + 250 = 400 allocated of 1000 offered; 600 retained by issuer
        assert booking["total_whole_shares_credited"] == 400
        # A2's new lot: 250 shares, basis 250 x 400 = 100000
        resp = api.list_position_lots(
            OPS, params={"account_id": a2["id"], "security_id": sec["id"],
                         "status": "OPEN"})
        rows = resp.json()["data"]
        new_lots = [r for r in rows if r["quantity"] == 250]
        assert len(new_lots) == 1
        assert new_lots[0]["cost_basis_total_cents"] == 100000
