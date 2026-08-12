"""Composite setup helpers for the recovery-lifecycle scenarios.

Every helper builds its preconditions from scratch via PRD-declared
endpoints (the harness restarts the server before each test, so each test
starts against an empty database). Setup calls use get_success_data() so a
failed precondition surfaces as a clear "Setup failed" error.

Standard pipeline (defaults reproduce the canonical scenario numbers):
  borrower -> loan (2,000,000c principal, 1200bps, 45,000c/mo, 3 missed,
  60,000c accrued, 12,000c late fees) -> case OPENED (by rm_1) -> costs
  35,000c + 4,500c -> cure notice (cure amount 186,500c, deadline +14d)
  -> clock 2026-05-16 (CURE_EXPIRED) -> agent -> assignment ACCEPTED ->
  report-secured (GOOD, trade-in 1,500,000c, guide 900,000c)
  -> REDEMPTION quote (2,127,950c, valid_until 2026-05-26)
  -> clock 2026-05-27 (CONSIGNMENT_PENDING) -> auction house (500bps,
  15,000c transport) -> consignment DRAFT (reserve 1,055,750c)
  -> list [05-28, 05-30] (IN_AUCTION) -> clock 2026-06-05 ->
  report-sale 1,200,000c -> certify (SALE_CONFIRMED, net 1,125,000c)
  -> deficiency notice (1,009,530c) -> send (DEFICIENCY_NOTICED).
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CO_OPERATOR_ID,
    LISTING_END,
    LISTING_START,
    RM_OPERATOR_ID,
    T_CONSIGN,
    T_SALE,
    T_SECURE,
)
from .factories import (
    accept_quote_payload,
    create_auction_house_payload,
    create_borrower_payload,
    create_complaint_payload,
    create_consignment_payload,
    create_cure_notice_payload,
    create_cure_payment_payload,
    create_ledger_entry_payload,
    create_loan_account_payload,
    create_property_item_payload,
    create_recovery_case_payload,
    create_redemption_quote_payload,
    create_repo_agent_payload,
    create_repo_assignment_payload,
    listing_window_payload,
    record_deficiency_payment_payload,
    report_sale_payload,
    report_secured_payload,
    resolve_complaint_payload,
    revise_deficiency_payload,
)
from .test_users import (
    make_agent_headers,
    make_auctioneer_headers,
    make_borrower_headers,
    make_compliance_officer_headers,
    make_recovery_manager_headers,
)

# Standard costs posted before the cure notice in most scenarios.
STANDARD_COSTS = [("COST_REPO_FEE", 35_000), ("COST_STORAGE", 4_500)]


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _advance_clock_past(floor_iso: str, deadline_iso: str, margin: timedelta) -> str:
    """Advance the logical clock past ``deadline_iso`` without ever moving it
    below ``floor_iso``. Composite fixtures are reusable within one test: when
    a second pipeline starts at an already-advanced clock, its freshly issued
    notice/quote carries a later deadline, so the fixed anchor alone would no
    longer fire the automatic expiry. The clock target is therefore the later
    of the caller's anchor and ``deadline + margin``."""
    target = max(_parse_ts(floor_iso), _parse_ts(deadline_iso) + margin)
    set_clock(_fmt_ts(target))
    return _fmt_ts(target)


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------

def rm_headers(user_id: str = RM_OPERATOR_ID) -> dict:
    return make_recovery_manager_headers(user_id)


def co_headers(user_id: str = CO_OPERATOR_ID) -> dict:
    return make_compliance_officer_headers(user_id)


def set_clock(to_iso8601: str, headers: dict = None) -> dict:
    resp = api_client.set_clock(to_iso8601, headers or rm_headers())
    return get_success_data(resp)


def create_borrower(**overrides) -> dict:
    resp = api_client.create_borrower(create_borrower_payload(**overrides), rm_headers())
    return get_success_data(resp)


def create_loan(borrower_id: str, **overrides) -> dict:
    resp = api_client.create_loan_account(
        create_loan_account_payload(borrower_id, **overrides), rm_headers())
    return get_success_data(resp)


def open_case(loan_account_id: str, opener_id: str = RM_OPERATOR_ID, **overrides) -> dict:
    resp = api_client.create_recovery_case(
        create_recovery_case_payload(loan_account_id, **overrides), rm_headers(opener_id))
    return get_success_data(resp)


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_recovery_case(case_id, rm_headers()))


def get_loan(loan_id: str) -> dict:
    return get_success_data(api_client.get_loan_account(loan_id, rm_headers()))


def get_agent(agent_id: str) -> dict:
    return get_success_data(api_client.get_repo_agent(agent_id, rm_headers()))


def get_consignment(consignment_id: str) -> dict:
    return get_success_data(api_client.get_consignment(consignment_id, rm_headers()))


def fresh_case_version(case_id: str) -> int:
    return get_case(case_id)["version"]


def post_cost(case_id: str, kind: str, amount_cents: int, memo: str = None) -> dict:
    payload = create_ledger_entry_payload(kind, amount_cents)
    if memo is not None:
        payload["memo"] = memo
    return get_success_data(api_client.create_ledger_entry(case_id, payload, rm_headers()))


def issue_cure_notice(case_id: str, expected_version: int = None) -> dict:
    if expected_version is None:
        expected_version = fresh_case_version(case_id)
    resp = api_client.create_cure_notice(
        case_id, create_cure_notice_payload(expected_version), rm_headers())
    return get_success_data(resp)


def list_cure_notices(case_id: str) -> list:
    return get_success_data(api_client.list_cure_notices(case_id, rm_headers()))


def list_ledger_entries(case_id: str) -> list:
    return get_success_data(api_client.list_ledger_entries(case_id, rm_headers()))


def list_quotes(case_id: str) -> list:
    return get_success_data(api_client.list_redemption_quotes(case_id, rm_headers()))


def list_case_assignments(case_id: str) -> list:
    return get_success_data(api_client.list_case_assignments(case_id, rm_headers()))


def list_property_items(case_id: str) -> list:
    return get_success_data(api_client.list_property_items(case_id, rm_headers()))


def list_deficiency_notices(case_id: str) -> list:
    return get_success_data(api_client.list_deficiency_notices(case_id, rm_headers()))


def list_sale_records(consignment_id: str) -> list:
    return get_success_data(api_client.list_sale_records(consignment_id, rm_headers()))


def list_case_complaints(case_id: str) -> list:
    return get_success_data(api_client.list_case_complaints(case_id, rm_headers()))


def create_agent(**overrides) -> dict:
    resp = api_client.create_repo_agent(create_repo_agent_payload(**overrides), rm_headers())
    return get_success_data(resp)


def assign_agent(case_id: str, agent_id: str = None,
                 field_window_start: str = "2026-05-16T00:00:00Z",
                 field_window_end: str = "2026-05-18T00:00:00Z") -> dict:
    payload = create_repo_assignment_payload(
        field_window_start=field_window_start, field_window_end=field_window_end)
    if agent_id is not None:
        payload["agent_id"] = agent_id
    resp = api_client.create_repo_assignment(case_id, payload, rm_headers())
    return get_success_data(resp)


def accept_assignment(assignment_id: str, agent_id: str) -> dict:
    resp = api_client.accept_assignment(assignment_id, make_agent_headers(agent_id))
    return get_success_data(resp)


def report_secured(assignment_id: str, agent_id: str, **appraisal) -> dict:
    resp = api_client.report_secured(
        assignment_id, report_secured_payload(**appraisal), make_agent_headers(agent_id))
    return get_success_data(resp)


def issue_quote(case_id: str, quote_type: str = "REDEMPTION", expected_version: int = None) -> dict:
    if expected_version is None:
        expected_version = fresh_case_version(case_id)
    resp = api_client.create_redemption_quote(
        case_id, create_redemption_quote_payload(quote_type, expected_version), rm_headers())
    return get_success_data(resp)


def accept_quote(quote_id: str, borrower_id: str, payment_amount_cents: int) -> dict:
    resp = api_client.accept_redemption_quote(
        quote_id, accept_quote_payload(payment_amount_cents), make_borrower_headers(borrower_id))
    return get_success_data(resp)


def create_auction_house(**overrides) -> dict:
    resp = api_client.create_auction_house(create_auction_house_payload(**overrides), rm_headers())
    return get_success_data(resp)


def consign(case_id: str, auction_house_id: str) -> dict:
    resp = api_client.create_consignment(
        case_id, create_consignment_payload(auction_house_id), rm_headers())
    return get_success_data(resp)


def list_consignment(consignment_id: str, auction_house_id: str,
                     listing_start: str = LISTING_START, listing_end: str = LISTING_END) -> dict:
    resp = api_client.list_consignment(
        consignment_id, listing_window_payload(listing_start, listing_end),
        make_auctioneer_headers(auction_house_id))
    return get_success_data(resp)


def report_sale(consignment_id: str, auction_house_id: str, gross_sale_cents: int) -> dict:
    resp = api_client.report_sale(
        consignment_id, report_sale_payload(gross_sale_cents),
        make_auctioneer_headers(auction_house_id))
    return get_success_data(resp)


def certify_sale(sale_id: str, officer_id: str = CO_OPERATOR_ID) -> dict:
    resp = api_client.certify_sale(sale_id, co_headers(officer_id))
    return get_success_data(resp)


def create_deficiency_notice(case_id: str) -> dict:
    resp = api_client.create_deficiency_notice(case_id, rm_headers())
    return get_success_data(resp)


def send_deficiency_notice(notice_id: str) -> dict:
    return get_success_data(api_client.send_deficiency_notice(notice_id, rm_headers()))


def file_complaint(case_id: str, borrower_id: str, **overrides) -> dict:
    resp = api_client.create_complaint(
        case_id, create_complaint_payload(**overrides), make_borrower_headers(borrower_id))
    return get_success_data(resp)


def resolve_complaint(complaint_id: str, outcome: str, officer_id: str = CO_OPERATOR_ID) -> dict:
    resp = api_client.resolve_complaint(
        complaint_id, resolve_complaint_payload(outcome), co_headers(officer_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Composite pipeline fixtures
# ---------------------------------------------------------------------------

def setup_case_cure_pending(costs=None, loan_overrides=None, borrower_overrides=None,
                            default_reason="delinquent") -> dict:
    """borrower + loan + OPENED case + cost entries + first cure notice.
    Case is CURE_PENDING with cure_deadline = sent_at + 14 days."""
    borrower = create_borrower(**(borrower_overrides or {}))
    loan = create_loan(borrower["id"], **(loan_overrides or {}))
    case = open_case(loan["id"], default_reason=default_reason)
    entries = [post_cost(case["id"], kind, amount) for kind, amount in (costs or [])]
    notice = issue_cure_notice(case["id"])
    return {
        "borrower": borrower, "loan": loan, "case": get_case(case["id"]),
        "notice": notice, "ledger_entries": entries,
    }


def setup_case_cure_expired(clock_to: str = T_SECURE, costs=None,
                            loan_overrides=None, borrower_overrides=None) -> dict:
    """CURE_PENDING setup, then the clock advances past the cure deadline so
    the case stands CURE_EXPIRED."""
    ctx = setup_case_cure_pending(
        costs=STANDARD_COSTS if costs is None else costs,
        loan_overrides=loan_overrides, borrower_overrides=borrower_overrides)
    # cure_deadline = notice sent_at + 14 days; land one day beyond it (and
    # never below the caller's anchor) so reused pipelines still expire.
    _advance_clock_past(clock_to, ctx["notice"]["sent_at"], timedelta(days=15))
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def setup_case_collateral_secured(clock_to: str = T_SECURE, costs=None,
                                  loan_overrides=None, borrower_overrides=None,
                                  agent_overrides=None, appraisal_overrides=None,
                                  field_window_start: str = "2026-05-16T00:00:00Z",
                                  field_window_end: str = "2026-05-18T00:00:00Z") -> dict:
    """Full field pipeline: CURE_EXPIRED case + agent + assignment ACCEPTED +
    report-secured. Case stands COLLATERAL_SECURED."""
    ctx = setup_case_cure_expired(
        clock_to=clock_to, costs=costs, loan_overrides=loan_overrides,
        borrower_overrides=borrower_overrides)
    agent = create_agent(**(agent_overrides or {}))
    assignment = assign_agent(ctx["case"]["id"], agent["id"],
                              field_window_start=field_window_start,
                              field_window_end=field_window_end)
    assignment = accept_assignment(assignment["id"], agent["id"])
    assignment = report_secured(assignment["id"], agent["id"], **(appraisal_overrides or {}))
    ctx.update({
        "agent": agent,
        "assignment": assignment,
        "case": get_case(ctx["case"]["id"]),
    })
    return ctx


def setup_case_redemption_open(quote_type: str = "REDEMPTION", **kwargs) -> dict:
    """COLLATERAL_SECURED setup + first redemption quote. Case stands
    REDEMPTION_OPEN with redemption_deadline = issued_at + 10 days."""
    ctx = setup_case_collateral_secured(**kwargs)
    quote = issue_quote(ctx["case"]["id"], quote_type)
    ctx.update({"quote": quote, "case": get_case(ctx["case"]["id"])})
    return ctx


def setup_case_consign_pending(clock_to: str = T_CONSIGN, **kwargs) -> dict:
    """REDEMPTION_OPEN setup, then clock past the redemption deadline so the
    quote EXPIRES and the case moves to CONSIGNMENT_PENDING."""
    ctx = setup_case_redemption_open(**kwargs)
    # redemption deadline = quote valid_until; land one day beyond it (and
    # never below the caller's anchor) so reused pipelines still expire.
    _advance_clock_past(clock_to, ctx["quote"]["valid_until"], timedelta(days=1))
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def setup_case_in_auction(auction_house_overrides=None, listing_start: str = LISTING_START,
                          listing_end: str = LISTING_END, **kwargs) -> dict:
    """CONSIGNMENT_PENDING setup + auction house + consignment DRAFT + listed
    window. Case stands IN_AUCTION."""
    ctx = setup_case_consign_pending(**kwargs)
    house = create_auction_house(**(auction_house_overrides or {}))
    consignment = consign(ctx["case"]["id"], house["id"])
    consignment = list_consignment(consignment["id"], house["id"],
                                   listing_start=listing_start, listing_end=listing_end)
    ctx.update({
        "auction_house": house,
        "consignment": get_consignment(consignment["id"]),
        "case": get_case(ctx["case"]["id"]),
    })
    return ctx


def setup_case_sale_confirmed(gross_sale_cents: int = 1_200_000, clock_to: str = T_SALE,
                              certifying_officer: str = CO_OPERATOR_ID, **kwargs) -> dict:
    """IN_AUCTION setup + hammer report + compliance certification. Case
    stands SALE_CONFIRMED with sold_at stamped; consignment SOLD; sale
    record CERTIFIED."""
    ctx = setup_case_in_auction(**kwargs)
    set_clock(clock_to)
    sale = report_sale(ctx["consignment"]["id"], ctx["auction_house"]["id"], gross_sale_cents)
    sale = certify_sale(sale["id"], officer_id=certifying_officer)
    ctx.update({
        "sale": sale,
        "consignment": get_consignment(ctx["consignment"]["id"]),
        "case": get_case(ctx["case"]["id"]),
    })
    return ctx


def setup_case_deficiency_noticed(**kwargs) -> dict:
    """SALE_CONFIRMED setup + deficiency notice created and sent. Case stands
    DEFICIENCY_NOTICED; notice is SENT with the FINAL deficiency snapshot."""
    ctx = setup_case_sale_confirmed(**kwargs)
    notice = create_deficiency_notice(ctx["case"]["id"])
    notice = send_deficiency_notice(notice["id"])
    ctx.update({"notice": notice, "case": get_case(ctx["case"]["id"])})
    return ctx
