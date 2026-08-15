"""Composite setup helpers.

The harness restarts the server before every test, so every fixture builds its
preconditions from scratch against an empty database using only PRD-declared
endpoints. All helpers use the lenient get_success_data() so a setup failure
surfaces as a clear "Setup failed" message rather than a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_T0, EVENT_E1, SEASON1, SEASON2
from .factories import (
    create_account_payload, create_agreement_payload, create_assessment_payload,
    create_catering_order_payload, create_credential_payload, create_event_payload,
    create_invoice_payload, create_payment_payload, create_rental_payload,
    create_renewal_offer_payload, create_season_payload, create_suite_payload,
    create_transfer_request_payload, create_venue_payload,
    create_waitlist_entry_payload,
)
from .test_users import TEST_USERS, make_account_holder_headers

ADMIN = TEST_USERS["admin_headers"]
REP = TEST_USERS["rep_headers"]
FIN = TEST_USERS["finance_headers"]
ESM = TEST_USERS["event_services_headers"]


def _ok(resp, what):
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), \
        f"Setup failed: {what}: {resp.status_code} {resp.text}"
    return data


# --- Clock ---------------------------------------------------------------

def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    assert resp.status_code == 200, f"Setup failed: set_clock: {resp.text}"
    return get_success_data(resp)


# --- Atomic creators -----------------------------------------------------

def make_venue(**overrides):
    return _ok(api_client.create_venue(create_venue_payload(**overrides), ADMIN),
               "create venue")


def make_suite(venue_id, **overrides):
    return _ok(api_client.create_suite(create_suite_payload(venue_id, **overrides), ADMIN),
               "create suite")


def make_season(venue_id, publish=True, **overrides):
    season = _ok(api_client.create_season(create_season_payload(venue_id, **overrides), ADMIN),
                 "create season")
    if publish:
        season = _ok(api_client.publish_season(season["id"], ADMIN), "publish season")
    return season


def make_event(season_id, **overrides):
    return _ok(api_client.create_event(create_event_payload(season_id, **overrides), ADMIN),
               "create event")


def make_account(**overrides):
    return _ok(api_client.create_account(create_account_payload(**overrides), REP),
               "create account")


def activate_account(account_id):
    return _ok(api_client.set_account_status(account_id, {"target_status": "ACTIVE"}, FIN),
               "activate account")


def make_active_account(**overrides):
    account = make_account(**overrides)
    return activate_account(account["id"])


def make_draft_agreement(suite_id, account_id, season_id, **overrides):
    return _ok(api_client.create_agreement(
        create_agreement_payload(suite_id, account_id, season_id, **overrides), REP),
        "create agreement")


def submit_agreement(agreement_id):
    return _ok(api_client.submit_agreement(agreement_id, REP), "submit agreement")


def execute_agreement(agreement_id, account_id):
    """Holder executes its own agreement (PRD §3.3)."""
    return _ok(api_client.execute_agreement(
        agreement_id, make_account_holder_headers(account_id)), "execute agreement")


def make_executed_agreement(suite, account, season, execute_clock=None, **overrides):
    ag = make_draft_agreement(suite["id"], account["id"], season["id"], **overrides)
    submit_agreement(ag["id"])
    if execute_clock is not None:
        set_clock(execute_clock)
    return execute_agreement(ag["id"], account["id"])


# --- Composite: venue + suite + seasons + account + ACTIVE agreement -----

def setup_active_agreement(num_seasons=1, events_spec=None, execute_clock=None,
                           initial_clock=CLOCK_T0, suite_over=None, agreement_over=None,
                           account_over=None):
    """Venue + GOLD suite + num_seasons PUBLISHED seasons + ACTIVE account +
    ACTIVE agreement (DRAFT -> PENDING_EXECUTION -> ACTIVE).

    events_spec: list of event override dicts created in season 1.
    execute_clock: logical clock at execution (None -> leave at initial_clock).
    Returns dict(venue, suite, seasons, events, account, agreement).
    """
    suite_over = dict(suite_over or {})
    agreement_over = dict(agreement_over or {})
    set_clock(initial_clock)
    venue = make_venue()
    suite = make_suite(venue["id"], **suite_over)
    season_consts = [SEASON1, SEASON2] + [
        {"label": f"{2028 + i}-{(2029 + i) % 100:02d}",
         "starts_on": f"{2028 + i}-09-01T00:00:00Z",
         "ends_on": f"{2029 + i}-02-15T00:00:00Z",
         "renewal_window_opens_on": f"{2028 + i}-12-01T00:00:00Z",
         "renewal_window_closes_on": f"{2029 + i}-01-15T00:00:00Z"}
        for i in range(max(0, num_seasons - 2))]
    seasons = [make_season(venue["id"], **season_consts[i]) for i in range(num_seasons)]
    events = [make_event(seasons[0]["id"], **ev) for ev in (events_spec or [])]
    account = make_active_account(**(account_over or {}))
    agreement = make_executed_agreement(
        suite, account, seasons[0],
        execute_clock=execute_clock,
        term_seasons=agreement_over.pop("term_seasons", num_seasons),
        **agreement_over)
    return {"venue": venue, "suite": suite, "seasons": seasons, "events": events,
            "account": account, "agreement": agreement}


# --- Invoices / payments -------------------------------------------------

def list_invoice_rows(params):
    resp = api_client.list_invoices(FIN, params=params)
    assert resp.status_code == 200, f"Setup failed: list invoices: {resp.text}"
    return resp.json()["data"]


def get_single_invoice(params):
    rows = list_invoice_rows(params)
    assert len(rows) == 1, f"Setup failed: expected 1 invoice for {params}, got {len(rows)}"
    return rows[0]


def get_license_fee_invoice(agreement_id):
    return get_single_invoice({"agreement_id": agreement_id, "invoice_type": "LICENSE_FEE"})


def make_issued_invoice(account_id, issue_clock=None, **overrides):
    if issue_clock is not None:
        set_clock(issue_clock)
    inv = _ok(api_client.create_invoice(create_invoice_payload(account_id, **overrides), FIN),
              "create manual invoice")
    return _ok(api_client.issue_invoice(inv["id"], FIN), "issue invoice")


def pay_invoice_in_full(account_id, invoice, method="ACH", amount_cents=None):
    """Create a payment covering the invoice's current amount_due and clear it."""
    if amount_cents is None:
        amount_cents = invoice["amount_due_cents"]
    p = _ok(api_client.create_payment(
        create_payment_payload(account_id, amount_cents, invoice["id"], method=method), FIN),
        "create payment")
    _ok(api_client.set_payment_status(p["id"], {"target_status": "CLEARED"}, FIN),
        "clear payment")
    return p


# --- Events / seasons lifecycle ------------------------------------------

def complete_event(event_id, at_clock):
    set_clock(at_clock)
    return _ok(api_client.set_event_status(event_id, {"target_status": "COMPLETED"}, ADMIN),
               "complete event")


def settle_season(season_id, at_clock):
    set_clock(at_clock)
    return _ok(api_client.settle_season(season_id, FIN), "settle season")


# --- Catering ------------------------------------------------------------

def place_catering_order(event_id, suite_id, account_id=None, agreement_id=None,
                         rental_id=None, headers=None, **overrides):
    payload = create_catering_order_payload(event_id, suite_id, **overrides)
    if agreement_id is not None:
        payload["agreement_id"] = agreement_id
    if rental_id is not None:
        payload["rental_id"] = rental_id
    if headers is None:
        headers = make_account_holder_headers(account_id) if account_id else ESM
    resp = api_client.create_catering_order(payload, headers)
    return resp


def place_catering_order_ok(event_id, suite_id, **kwargs):
    return _ok(place_catering_order(event_id, suite_id, **kwargs), "place catering order")


def confirm_catering_order(order_id):
    return _ok(api_client.set_catering_order_status(
        order_id, {"target_status": "CONFIRMED"}, ESM), "confirm catering order")


# --- Credentials ---------------------------------------------------------

def issue_credential(event_id, suite_id, headers=None, **overrides):
    payload = create_credential_payload(event_id, suite_id, **overrides)
    return api_client.create_credential(payload, headers or ESM)


def issue_credential_ok(event_id, suite_id, **overrides):
    return _ok(issue_credential(event_id, suite_id, **overrides), "issue credential")


# --- Rentals -------------------------------------------------------------

def make_rental(event_id, suite_id, account_id, **overrides):
    return _ok(api_client.create_rental(
        create_rental_payload(event_id, suite_id, account_id, **overrides), REP),
        "create rental")


def transition_rental(rental_id, target_status, headers=None):
    return _ok(api_client.set_rental_status(
        rental_id, {"target_status": target_status}, headers or REP),
        f"rental -> {target_status}")


def setup_confirmed_rental(event, suite, account, hold_clock=None, **overrides):
    """QUOTED -> HELD -> CONFIRMED. Returns the CONFIRMED rental."""
    if hold_clock is not None:
        set_clock(hold_clock)
    rental = make_rental(event["id"], suite["id"], account["id"], **overrides)
    transition_rental(rental["id"], "HELD")
    return transition_rental(rental["id"], "CONFIRMED")


# --- Transfers -----------------------------------------------------------

def setup_transfer(agreement, from_account, to_account, walk_to="UNDER_REVIEW", **overrides):
    tr = _ok(api_client.create_transfer_request(
        create_transfer_request_payload(agreement["id"], from_account["id"],
                                        to_account["id"], **overrides),
        make_account_holder_headers(from_account["id"])), "create transfer request")
    if walk_to in ("UNDER_REVIEW", "INFO_REQUESTED", "APPROVED"):
        tr = _ok(api_client.set_transfer_status(tr["id"], {"target_status": "UNDER_REVIEW"}, REP),
                 "transfer -> UNDER_REVIEW")
    if walk_to == "INFO_REQUESTED":
        tr = _ok(api_client.set_transfer_status(tr["id"], {"target_status": "INFO_REQUESTED"}, REP),
                 "transfer -> INFO_REQUESTED")
    if walk_to == "APPROVED":
        tr = _ok(api_client.set_transfer_status(tr["id"], {"target_status": "APPROVED"}, REP),
                 "transfer -> APPROVED")
    return tr


def pay_transfer_fee(transfer, from_account):
    inv = get_single_invoice({"account_id": from_account["id"], "invoice_type": "TRANSFER_FEE"})
    pay_invoice_in_full(from_account["id"], inv, method="WIRE")
    return inv


# --- Renewal offers ------------------------------------------------------

def setup_renewal_offer(agreement_id, season_id, at_clock=None, **overrides):
    if at_clock is not None:
        set_clock(at_clock)
    ag = _ok(api_client.get_agreement(agreement_id, REP), "read agreement version")
    return _ok(api_client.create_renewal_offer(
        create_renewal_offer_payload(agreement_id, season_id, ag["version"], **overrides), REP),
        "create renewal offer")


# --- Waitlist ------------------------------------------------------------

def make_waitlist_entry(account_id, **overrides):
    return _ok(api_client.create_waitlist_entry(
        create_waitlist_entry_payload(account_id, **overrides), REP),
        "create waitlist entry")


# --- Assessments ---------------------------------------------------------

def make_approved_assessment(venue_id, **overrides):
    asm = _ok(api_client.create_assessment(
        create_assessment_payload(venue_id, **overrides), ADMIN), "create assessment")
    _ok(api_client.set_assessment_status(asm["id"], {"target_status": "PROPOSED"}, ADMIN),
        "assessment -> PROPOSED")
    return _ok(api_client.set_assessment_status(asm["id"], {"target_status": "APPROVED"}, ADMIN),
               "assessment -> APPROVED")


def setup_three_licensed_suites(allocation_method="PER_SUITE_EQUAL", total_cost_cents=1000000):
    """Venue with three LICENSED suites (GOLD cap 20 first, SILVER cap 10 second,
    PLATINUM cap 12 third), each under an ACTIVE term-1 agreement (escalator 0)
    held by a distinct ACTIVE account, plus an APPROVED assessment.

    Returns dict(venue, season, suites, accounts, agreements, assessment).
    """
    set_clock(CLOCK_T0)
    venue = make_venue()
    suite_g = make_suite(venue["id"], suite_code="G-101", tier="GOLD", capacity_seats=20)
    suite_s = make_suite(venue["id"], suite_code="S-102", tier="SILVER", capacity_seats=10,
                         base_annual_fee_cents=6000000, f_b_minimum_cents=2000000)
    suite_p = make_suite(venue["id"], suite_code="P-103", tier="PLATINUM", capacity_seats=12,
                         base_annual_fee_cents=20000000, f_b_minimum_cents=6000000)
    season = make_season(venue["id"])
    accounts, agreements = [], []
    for suite, fee, fb in ((suite_g, 12000000, 4000000),
                           (suite_s, 6000000, 2000000),
                           (suite_p, 20000000, 6000000)):
        acct = make_active_account()
        ag = make_executed_agreement(suite, acct, season, term_seasons=1,
                                     base_annual_fee_cents=fee, escalator_bp=0,
                                     f_b_minimum_cents=fb)
        accounts.append(acct)
        agreements.append(ag)
    asm = make_approved_assessment(venue["id"], total_cost_cents=total_cost_cents,
                                   allocation_method=allocation_method)
    return {"venue": venue, "season": season,
            "suites": [suite_g, suite_s, suite_p],
            "accounts": accounts, "agreements": agreements, "assessment": asm}
