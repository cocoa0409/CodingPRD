"""Transitive cascades (PRD §3.6, §3.9): the booking cascade settling lots,
accounts and recon breaks; statement ingestion auto-filing claims.
"""
from test_helpers import (
    validate_success, get_success_data,
    make_security, make_account, make_lot, set_clock,
    make_confirmed_event, make_custodian_source, submit_statement,
    split_terms,
)
from test_helpers.fixtures import OPS
from test_helpers import api_client


def _booked_split_with_break():
    """ACME; A1 holds 1000 sh; SPLIT 2:1 confirmed; custodian reports 2000
    against books of 1000 -> OPEN POSITION_MISMATCH break; captured."""
    sec = make_security(ticker="ACME")
    acct = make_account(account_number="A-1", holder_name="One")
    lot = make_lot(acct["id"], sec["id"], quantity=1000,
                   acquisition_date="2026-04-01", cost_basis_total_cents=10000000)
    event, _, _ = make_confirmed_event(sec["id"], "SPLIT", split_terms())
    cust = make_custodian_source()
    stmt = submit_statement(
        cust["id"], "2026-05-01", "2026-05-14",
        [{"account_id": acct["id"], "security_id": sec["id"], "quantity": 2000}])
    resp = api_client.list_recon_breaks(OPS, params={"statement_id": stmt["id"]})
    brk = resp.json()["data"][0]
    set_clock("2026-05-15T00:00:00Z")
    get_success_data(api_client.capture_record_position(event["id"], OPS))
    return sec, acct, lot, event, stmt, brk


class TestBookingCascadeSettlesLotsAccountsBreaks:
    def test_booking_mutates_lot_and_recomputes_account(self, api):
        """PRD §3.6: "each settled entitlement drives the per-type booking algorithm below, mutating or creating position lots and posting immutable `BookingLine` ledger records. Fourth, every affected account's `cash_balance_cents`, `total_cost_basis_cents`, and `pending_entitlement_count` are recomputed per §2.9."
        PRD §2.9: "An account's `total_cost_basis_cents` is the sum of `cost_basis_total_cents` over its `OPEN` position lots only".

        Design: Difficulty/transitive_cascade/booking_cascade_settles_lots_accounts_breaks
        """
        _, acct, lot, event, _, brk = _booked_split_with_break()
        assert brk["break_type"] == "POSITION_MISMATCH"
        assert brk["expected_quantity"] == 1000
        assert brk["reported_quantity"] == 2000
        assert brk["status"] == "OPEN"
        booking = validate_success(api.book_event(event["id"], OPS), 201)
        assert booking["total_whole_shares_credited"] == 2000
        lot_after = get_success_data(api.get_position_lot(lot["id"], OPS))
        assert lot_after["quantity"] == 2000
        acct_after = get_success_data(api.get_account(acct["id"], OPS))
        assert acct_after["total_cost_basis_cents"] == 10000000
        assert acct_after["pending_entitlement_count"] == 0

    def test_booking_auto_resolves_matching_position_break(self, api):
        """PRD §3.6: "Fifth, every `OPEN` reconciliation break of type `POSITION_MISMATCH` whose account and security now match the internal books is automatically resolved with `resolution` `AUTO_BOOKING`."
        PRD §3.6: "when its account is `ACTIVE` the entitlement moves `FIRM` → `SETTLED".

        Design: Difficulty/transitive_cascade/booking_cascade_settles_lots_accounts_breaks
        """
        _, acct, _, event, _, brk = _booked_split_with_break()
        validate_success(api.book_event(event["id"], OPS), 201)
        ent = api_client.list_entitlements(
            OPS, params={"event_id": event["id"], "account_id": acct["id"]}
        ).json()["data"][0]
        assert ent["status"] == "SETTLED"
        brk_after = get_success_data(api.get_recon_break(brk["id"], OPS))
        assert brk_after["status"] == "RESOLVED"
        assert brk_after["resolution"] == "AUTO_BOOKING"


def _booked_split_then_statement():
    """SPLIT 2:1 fully BOOKED at record date for a 1000-share account;
    clock advanced to 2026-06-10 (inside the claim window)."""
    sec = make_security(ticker="ACME")
    acct = make_account(account_number="A-1", holder_name="One")
    make_lot(acct["id"], sec["id"], quantity=1000,
             acquisition_date="2026-04-01", cost_basis_total_cents=10000000)
    event, _, _ = make_confirmed_event(sec["id"], "SPLIT", split_terms())
    set_clock("2026-05-15T00:00:00Z")
    get_success_data(api_client.capture_record_position(event["id"], OPS))
    get_success_data(api_client.book_event(event["id"], OPS))
    cust = make_custodian_source()
    set_clock("2026-06-10T00:00:00Z")
    return sec, acct, event, cust


class TestStatementIngestBreakAutofilesClaim:
    def test_missed_entitlement_break_auto_files_claim(self, api):
        """PRD §3.9: "An entitlement line is compared against the `entitled_shares` of the non-`SUPERSEDED` entitlement for that event and account; any difference creates a `MISSED_ENTITLEMENT` break — and when that entitlement is `MISSED` or `SETTLED` and no `FILED` claim exists for it, the engine automatically files a claim on the client's behalf, with `filed_by_user_id` recorded as"system"and a `claimed_amount_cents` equal to the absolute difference between expected and reported shares, valued under the event's `EVENT_TERMS` compensation basis."

        Design: Difficulty/transitive_cascade/statement_ingest_break_autofiles_claim
        """
        sec, acct, event, cust = _booked_split_then_statement()
        stmt = submit_statement(
            cust["id"], "2026-06-01", "2026-06-15",
            [{"account_id": acct["id"], "security_id": sec["id"],
              "event_id": event["id"], "quantity": 2050}])
        assert stmt["status"] == "RECONCILED"
        resp = api.list_recon_breaks(
            OPS, params={"statement_id": stmt["id"],
                         "break_type": "MISSED_ENTITLEMENT"})
        brks = resp.json()["data"]
        assert len(brks) == 1
        brk = brks[0]
        assert brk["expected_quantity"] == 2000
        assert brk["reported_quantity"] == 2050
        assert brk["status"] == "OPEN"
        assert brk["auto_claim_id"]
        claim = get_success_data(api.get_claim(brk["auto_claim_id"], OPS))
        assert claim["review_status"] == "FILED"
        # 50 missing shares x 3333 terms price = 166650
        assert claim["claimed_amount_cents"] == 166650
        assert claim["filed_by_user_id"] == "system"

    def test_statement_response_shows_reconciled_synchronously(self, api):
        """PRD §3.9: "Reconciliation runs synchronously inside ingestion: the statement is created, every line is checked top-to-bottom in the order submitted, breaks are created, and the create response already shows the statement `RECONCILED` (having briefly been `RECEIVED`)."

        Design: Difficulty/transitive_cascade/statement_ingest_break_autofiles_claim
        """
        sec, acct, event, cust = _booked_split_then_statement()
        stmt = submit_statement(
            cust["id"], "2026-06-01", "2026-06-15",
            [{"account_id": acct["id"], "security_id": sec["id"],
              "event_id": event["id"], "quantity": 1999}])
        assert stmt["status"] == "RECONCILED"
        resp = api.list_recon_breaks(
            OPS, params={"statement_id": stmt["id"],
                         "break_type": "MISSED_ENTITLEMENT"})
        brk = resp.json()["data"][0]
        assert brk["expected_quantity"] == 2000
        assert brk["reported_quantity"] == 1999
