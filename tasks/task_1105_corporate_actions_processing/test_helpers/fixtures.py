"""Composite setup helpers for corporate-actions tests (PRD §3).

Every test runs against a freshly restarted server, so each fixture builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use
the lenient get_success_data so a setup failure surfaces as a clear error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_security_payload,
    create_account_payload,
    create_position_lot_payload,
    create_event_source_payload,
    create_source_notification_payload,
    split_terms,
    merger_terms,
    rights_terms,
    cash_dividend_terms,
    spinoff_terms,
)
from .test_users import TEST_USERS, make_account_holder_headers, make_analyst_headers

ADMIN = TEST_USERS["desk_admin_headers"]
VENDOR = TEST_USERS["vendor_feed_headers"]
ANALYST_1 = TEST_USERS["analyst_1_headers"]
ANALYST_2 = TEST_USERS["analyst_2_headers"]
OPS = TEST_USERS["ops_headers"]
EXAMINER = TEST_USERS["examiner_1_headers"]
CUSTODIAN = TEST_USERS["custodian_feed_headers"]


# --- Tier 1: single-entity creation ---

def make_security(ticker=None, cusip=None, name=None):
    # PRD §3: ticker and CUSIP are unique across all securities. Default to
    # the auto-generated unique values from the factory when not supplied,
    # so composite fixtures may safely create multiple securities per test.
    overrides = {}
    if ticker is not None:
        overrides["ticker"] = ticker
    if cusip is not None:
        overrides["cusip"] = cusip
    if name is not None:
        overrides["name"] = name
    resp = api_client.create_security(
        create_security_payload(**overrides), ADMIN)
    return get_success_data(resp)


def make_account(account_number=None, holder_name=None, opening_cash_cents=None):
    overrides = {}
    if account_number is not None:
        overrides["account_number"] = account_number
    if holder_name is not None:
        overrides["holder_name"] = holder_name
    payload = create_account_payload(**overrides)
    if opening_cash_cents is not None:
        payload["opening_cash_cents"] = opening_cash_cents
    resp = api_client.create_account(payload, ADMIN)
    return get_success_data(resp)


def make_lot(account_id, security_id, quantity=100, acquisition_date="2026-04-01",
             cost_basis_total_cents=500000):
    resp = api_client.create_position_lot(
        create_position_lot_payload(
            account_id=account_id, security_id=security_id, quantity=quantity,
            acquisition_date=acquisition_date,
            cost_basis_total_cents=cost_basis_total_cents),
        ADMIN)
    return get_success_data(resp)


def make_event_source(name="Vendor Alpha", source_type="VENDOR", reliability_weight=10):
    resp = api_client.create_event_source(
        create_event_source_payload(
            name=name, source_type=source_type,
            reliability_weight=reliability_weight),
        ADMIN)
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


# --- Tier 2: scrub-set + golden event ---

def make_scrubbed_event(security_id, event_type, terms, record_date="2026-05-15",
                        payable_date="2026-05-29", source_a=None, source_b=None,
                        scrubber=ANALYST_1, **event_overrides):
    """Create two vendor sources (unless supplied), push one matching notification
    per source, then scrub them into a DRAFT event. Returns (event, n1, n2)."""
    src_a = source_a or make_event_source(
        name="Vendor Alpha", source_type="VENDOR", reliability_weight=10)
    src_b = source_b or make_event_source(
        name="Vendor Beta", source_type="VENDOR", reliability_weight=5)
    n1 = get_success_data(api_client.create_source_notification(
        create_source_notification_payload(
            source_id=src_a["id"], security_id=security_id,
            event_type=event_type, record_date=record_date,
            announced_terms=terms),
        VENDOR))
    n2 = get_success_data(api_client.create_source_notification(
        create_source_notification_payload(
            source_id=src_b["id"], security_id=security_id,
            event_type=event_type, record_date=record_date,
            announced_terms=terms),
        VENDOR))
    payload = {
        "security_id": security_id,
        "event_type": event_type,
        "terms": terms,
        "record_date": record_date,
        "payable_date": payable_date,
        "source_notification_ids": [n1["id"], n2["id"]],
    }
    payload.update(event_overrides)
    event = get_success_data(api_client.create_event(payload, scrubber))
    return event, n1, n2


def make_confirmed_event(security_id, event_type, terms, confirmer=ANALYST_2, **kw):
    """Scrub + confirm. Returns (event_after_confirm, n1, n2)."""
    event, n1, n2 = make_scrubbed_event(security_id, event_type, terms, **kw)
    confirmed = get_success_data(api_client.confirm_event(event["id"], confirmer))
    return confirmed, n1, n2


# --- Tier 3: full booking lifecycles ---

def make_split_event_booked(account_shares=1000, ratio_num=2, ratio_den=1,
                            price_per_share_cents=3333,
                            fractional_policy="ROUND_HALF_UP",
                            opening_cash_cents=None,
                            acquisition_date="2026-04-01",
                            lot_basis_cents=10000000,
                            freeze_before_book=False):
    """Full SPLIT lifecycle: security, account, lot, scrub, confirm, capture
    at record date, optionally freeze account, book. Returns a context dict."""
    sec = make_security()
    acct = make_account(opening_cash_cents=opening_cash_cents)
    lot = make_lot(acct["id"], sec["id"], quantity=account_shares,
                   acquisition_date=acquisition_date,
                   cost_basis_total_cents=lot_basis_cents)
    terms = split_terms(ratio_num=ratio_num, ratio_den=ratio_den,
                        price_per_share_cents=price_per_share_cents,
                        fractional_policy=fractional_policy)
    event, _, _ = make_confirmed_event(sec["id"], "SPLIT", terms)
    set_clock("2026-05-15T00:00:00Z")
    get_success_data(api_client.capture_record_position(event["id"], OPS))
    if freeze_before_book:
        get_success_data(api_client.update_account(acct["id"], {"status": "FROZEN"}, OPS))
    booking = get_success_data(api_client.book_event(event["id"], OPS))
    return {"security": sec, "account": acct, "lot": lot, "event": event,
            "booking": booking}


def get_entitlement_for(event_id, account_id):
    """Fetch the single entitlement row for (event, account)."""
    resp = api_client.list_entitlements(
        OPS, params={"event_id": event_id, "account_id": account_id})
    body = resp.json()
    rows = body.get("data", [])
    assert rows, f"no entitlement found for event={event_id} account={account_id}"
    return rows[0]


def get_event_version(event_id):
    return get_success_data(api_client.get_event(event_id, OPS))["version"]


def make_merger_event_confirmed(account_shares=10, with_lot=True,
                                election_deadline="2026-05-20T16:00:00Z",
                                cash_per_share_cents=5000,
                                cash_pool_cents=900000,
                                default_option="STOCK",
                                record_date="2026-05-15",
                                payable_date="2026-05-29"):
    """ACME + NEWCO securities, one account with a lot, voluntary MERGER event
    scrubbed and confirmed. Returns context dict."""
    sec = make_security(ticker="ACME")
    newco = make_security(ticker="NWC", name="Newco Inc")
    acct = make_account()
    lot = None
    if with_lot:
        lot = make_lot(acct["id"], sec["id"], quantity=account_shares)
    terms = merger_terms(newco["id"],
                         cash_per_share_cents=cash_per_share_cents,
                         cash_pool_cents=cash_pool_cents,
                         default_option=default_option)
    event, _, _ = make_confirmed_event(
        sec["id"], "MERGER", terms, record_date=record_date,
        payable_date=payable_date, election_required=True,
        election_deadline=election_deadline)
    return {"security": sec, "newco": newco, "account": acct, "lot": lot,
            "event": event, "terms": terms}


def make_rights_event_confirmed(account_shares=100, oversubscription_allowed=True,
                                shares_offered=1000, subscription_price_cents=400,
                                election_deadline="2026-05-20T16:00:00Z"):
    """RIGHTS_OFFERING event scrubbed + confirmed for one account."""
    sec = make_security()
    acct = make_account()
    lot = make_lot(acct["id"], sec["id"], quantity=account_shares,
                   cost_basis_total_cents=400000)
    terms = rights_terms(shares_offered=shares_offered,
                         subscription_price_cents=subscription_price_cents,
                         oversubscription_allowed=oversubscription_allowed)
    event, _, _ = make_confirmed_event(
        sec["id"], "RIGHTS_OFFERING", terms, election_required=True,
        election_deadline=election_deadline)
    return {"security": sec, "account": acct, "lot": lot, "event": event,
            "terms": terms}


def submit_cash_election(event_id, account_id, expected_event_version):
    """Ownership-gated: headers carry the account id as X-User-ID."""
    resp = api_client.submit_election(
        event_id,
        {"account_id": account_id, "option_code": "CASH",
         "expected_event_version": expected_event_version},
        make_account_holder_headers(account_id))
    return get_success_data(resp)


# --- Tier 4: missed-entitlement + claim scenarios ---

def make_missed_entitlement_context(price_per_share_cents=5000,
                                    compensation_pool_cents=100000,
                                    claim_basis=None,
                                    account_shares=5,
                                    claim_clock="2026-06-01T00:00:00Z"):
    """SPLIT event booked while the account is FROZEN, so the entitlement goes
    MISSED; clock advanced into the claim window. Returns context dict."""
    sec = make_security()
    acct = make_account()
    lot = make_lot(acct["id"], sec["id"], quantity=account_shares,
                   cost_basis_total_cents=25000)
    terms = split_terms(price_per_share_cents=price_per_share_cents)
    overrides = {"compensation_pool_cents": compensation_pool_cents}
    if claim_basis:
        overrides["claim_compensation_basis"] = claim_basis
    event, _, _ = make_confirmed_event(sec["id"], "SPLIT", terms, **overrides)
    set_clock("2026-05-15T00:00:00Z")
    get_success_data(api_client.capture_record_position(event["id"], OPS))
    get_success_data(api_client.update_account(acct["id"], {"status": "FROZEN"}, OPS))
    booking = get_success_data(api_client.book_event(event["id"], OPS))
    ent = get_entitlement_for(event["id"], acct["id"])
    set_clock(claim_clock)
    return {"security": sec, "account": acct, "lot": lot, "event": event,
            "booking": booking, "entitlement": ent}


def file_claim(event_id, entitlement_id, account_id, claimed_amount_cents=50000,
               reason="MISSED_ENTITLEMENT", market_price_cents=None):
    payload = {
        "event_id": event_id, "entitlement_id": entitlement_id,
        "account_id": account_id, "reason": reason,
        "claimed_amount_cents": claimed_amount_cents,
    }
    if market_price_cents is not None:
        payload["market_price_cents"] = market_price_cents
    resp = api_client.create_claim(payload, make_account_holder_headers(account_id))
    return get_success_data(resp)


# --- Tier 5: custodian statement / recon break scenarios ---

def make_custodian_source(name="Custodian Prime", reliability_weight=20):
    return make_event_source(name=name, source_type="CUSTODIAN",
                             reliability_weight=reliability_weight)


def submit_statement(source_id, coverage_start_date, coverage_end_date, lines):
    resp = api_client.create_custodian_statement(
        {"source_id": source_id, "coverage_start_date": coverage_start_date,
         "coverage_end_date": coverage_end_date, "lines": lines},
        CUSTODIAN)
    return get_success_data(resp)


def make_open_position_break(account_shares=1000, reported_quantity=900):
    """Account with a lot plus a custodian statement that disagrees -> OPEN
    POSITION_MISMATCH break. Returns (sec, acct, lot, statement, break)."""
    sec = make_security()
    acct = make_account()
    lot = make_lot(acct["id"], sec["id"], quantity=account_shares,
                   cost_basis_total_cents=10000000)
    cust = make_custodian_source()
    stmt = submit_statement(
        cust["id"], "2026-05-01", "2026-05-14",
        [{"account_id": acct["id"], "security_id": sec["id"],
          "quantity": reported_quantity}])
    resp = api_client.list_recon_breaks(OPS, params={"statement_id": stmt["id"]})
    rows = resp.json().get("data", [])
    assert rows, "expected a POSITION_MISMATCH break"
    return sec, acct, lot, stmt, rows[0]
