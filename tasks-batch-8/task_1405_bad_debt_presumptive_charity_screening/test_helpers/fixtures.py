"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly started server). Setup calls use
the lenient get_success_data() so failures surface as clear "Setup failed"
errors rather than confusing assertion failures.
"""
from datetime import date, datetime, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import LOGICAL_CLOCK_START_DATE, TEST_DEFAULTS, THRESHOLDS
from .factories import (
    create_account_payload,
    create_agency_placement_payload,
    create_early_out_placement_payload,
    create_payment_plan_payload,
    create_screening_payload,
    create_vendor_snapshot_payload,
    create_write_off_payload,
    approve_write_off_payload,
    file_dispute_payload,
    post_recovery_payload,
)
from .test_users import (
    TEST_USERS,
    make_collector_headers,
    make_counselor_headers,
    make_officer_headers,
)

COLLECTOR = TEST_USERS["collector_headers"]
COUNSELOR = TEST_USERS["counselor_headers"]
OFFICER = TEST_USERS["officer_headers"]


# ---------------------------------------------------------------------------
# Date arithmetic (whole-day granularity, PRD §2.6)
# ---------------------------------------------------------------------------

def parse_date(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def add_days(date_str: str, days: int) -> str:
    return (parse_date(date_str) + timedelta(days=days)).isoformat()


def days_between(earlier: str, later: str) -> int:
    return (parse_date(later) - parse_date(earlier)).days


def iso_at_start_of(date_str: str) -> str:
    return f"{date_str}T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: accounts and statements
# ---------------------------------------------------------------------------

def create_account(balance_cents=TEST_DEFAULTS["BALANCE_CENTS"],
                   guarantor_liability_date=TEST_DEFAULTS["GUARANTOR_LIABILITY_DATE"],
                   headers=None, **overrides):
    """Register a self-pay account. Returns the created account."""
    payload = create_account_payload(
        original_balance_cents=balance_cents,
        guarantor_liability_date=guarantor_liability_date,
        **overrides,
    )
    return get_success_data(api_client.create_account(payload, headers or COLLECTOR))


def read_account(account_id, headers=None):
    return get_success_data(api_client.get_account(account_id, headers or COLLECTOR))


def issue_statements(account_id, count=THRESHOLDS["REQUIRED_STATEMENTS"], headers=None):
    """Issue `count` statements against an account. Returns the statements."""
    statements = []
    for _ in range(count):
        statements.append(get_success_data(
            api_client.issue_statement(account_id, headers or COLLECTOR)))
    return statements


def advance_clock(to_iso8601, headers=None):
    """Advance the logical clock; returns the sweep-result payload."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or COLLECTOR))


# ---------------------------------------------------------------------------
# Tier 2: screenings (OCC-guarded creation → evaluate)
# ---------------------------------------------------------------------------

def create_pending_screening(account_id, headers=None, **overrides):
    """Create a PENDING screening with a fresh expected_account_version.

    Overrides set to None are omitted from the payload entirely, so a
    SCORE_BASED screening can drop the FPL-only household fields.
    """
    version = read_account(account_id)["version"]
    payload = create_screening_payload(account_id, version, **overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    return get_success_data(api_client.create_screening(payload, headers or COUNSELOR))


def create_evaluated_screening(account_id, headers=None, **overrides):
    """Create + evaluate a screening. Returns the EVALUATED screening."""
    screening = create_pending_screening(account_id, headers=headers, **overrides)
    return get_success_data(
        api_client.evaluate_screening(screening["id"], headers or COUNSELOR))


# ---------------------------------------------------------------------------
# Tier 3: placements
# ---------------------------------------------------------------------------

def setup_early_out_placement(balance_cents=80000,
                              guarantor_liability_date="2026-06-01",
                              vendor_name="VENDOR_A",
                              contingency_fee_bps=TEST_DEFAULTS["EARLY_OUT_FEE_BPS"],
                              headers=None):
    """OPEN account in the early-out band + ACTIVE early-out placement.

    Default liability date 2026-06-01 is 61 days before the boot clock
    (2026-08-01), i.e. BUCKET_60. Returns (account, placement).
    """
    headers = headers or COLLECTOR
    account = create_account(balance_cents, guarantor_liability_date)
    placement = get_success_data(api_client.create_early_out_placement(
        create_early_out_placement_payload(
            account["id"], vendor_name=vendor_name,
            contingency_fee_bps=contingency_fee_bps),
        headers))
    return read_account(account["id"]), placement


def setup_agency_placement_direct(balance_cents=90000,
                                  guarantor_liability_date="2026-01-01",
                                  agency_name="AGENCY_X",
                                  contingency_fee_bps=TEST_DEFAULTS["AGENCY_FEE_BPS"],
                                  statement_count=THRESHOLDS["REQUIRED_STATEMENTS"],
                                  headers=None):
    """OPEN account in BUCKET_120_PLUS with the statement-cycle minimum met,
    placed directly with a collection agency. Returns (account, placement)."""
    headers = headers or COLLECTOR
    account = create_account(balance_cents, guarantor_liability_date)
    issue_statements(account["id"], count=statement_count)
    placement = get_success_data(api_client.create_agency_placement(
        create_agency_placement_payload(
            account["id"], agency_name=agency_name,
            contingency_fee_bps=contingency_fee_bps),
        headers))
    return read_account(account["id"]), placement


# ---------------------------------------------------------------------------
# Tier 4: write-offs (two-person approval — creator and approver differ)
# ---------------------------------------------------------------------------

def create_pending_write_off(account_id, creator_headers=None, **overrides):
    """Create a PENDING_APPROVAL write-off as the given creator."""
    return get_success_data(api_client.create_write_off(
        create_write_off_payload(account_id, **overrides),
        creator_headers or make_collector_headers("collector-1")))


def approve_write_off_fresh(write_off_id, account_id, approver_headers=None):
    """Approve a pending write-off with a freshly read account version."""
    version = read_account(account_id)["version"]
    return get_success_data(api_client.approve_write_off(
        write_off_id, approve_write_off_payload(version),
        approver_headers or make_officer_headers("officer-1")))


def setup_posted_bad_debt_writeoff(balance_cents=80000,
                                   guarantor_liability_date="2026-01-01",
                                   cost_report_year=TEST_DEFAULTS["COST_REPORT_YEAR"],
                                   creator_id="collector-1",
                                   approver_id="officer-1",
                                   statement_count=THRESHOLDS["REQUIRED_STATEMENTS"]):
    """Account with a POSTED BAD_DEBT write-off (status WRITTEN_OFF).

    Returns (account_after_posting, write_off).
    """
    account = create_account(balance_cents, guarantor_liability_date)
    issue_statements(account["id"], count=statement_count)
    write_off = create_pending_write_off(
        account["id"], creator_headers=make_collector_headers(creator_id),
        write_off_kind="BAD_DEBT", medicare_cost_report_year=cost_report_year)
    posted = approve_write_off_fresh(
        write_off["id"], account["id"],
        approver_headers=make_officer_headers(approver_id))
    return read_account(account["id"]), posted


def setup_posted_charity_writeoff(balance_cents=120000,
                                  guarantor_liability_date="2026-06-01",
                                  screening_overrides=None,
                                  creator_id="collector-1",
                                  approver_id="officer-1"):
    """Account with a POSTED CHARITY_CARE write-off (status CLOSED_CHARITY).

    Default screening: FPL_TIERED household 1, income 1500000 → fpl_percent 99
    → FULL_CHARITY. Returns (account_after_posting, screening, write_off).
    """
    account = create_account(balance_cents, guarantor_liability_date)
    screening = create_evaluated_screening(
        account["id"], **(screening_overrides or {}))
    write_off = create_pending_write_off(
        account["id"], creator_headers=make_collector_headers(creator_id),
        write_off_kind="CHARITY_CARE", screening_id=screening["id"])
    posted = approve_write_off_fresh(
        write_off["id"], account["id"],
        approver_headers=make_officer_headers(approver_id))
    return read_account(account["id"]), screening, posted


# ---------------------------------------------------------------------------
# Tier 5: payment plans and the default sweep
# ---------------------------------------------------------------------------

def create_plan(account_id, headers=None, **overrides):
    return get_success_data(api_client.create_payment_plan(
        create_payment_plan_payload(account_id, **overrides), headers or COLLECTOR))


def setup_plan_in_default(balance_cents=300000,
                          guarantor_liability_date="2026-01-01",
                          installment_amount_cents=50000,
                          installment_count=6,
                          first_installment_due="2026-02-01",
                          clock_to="2026-05-01T00:00:00Z"):
    """Account + ACTIVE plan walked into IN_DEFAULT by a clock advance.

    Default: installments due 2026-02-01 / 2026-03-03 / 2026-04-02 are all due
    by 2026-05-01 → missed=3 ≥ 2 → IN_DEFAULT. Returns (account, plan).
    """
    account = create_account(balance_cents, guarantor_liability_date)
    plan = create_plan(
        account["id"],
        installment_amount_cents=installment_amount_cents,
        installment_count=installment_count,
        first_installment_due=first_installment_due,
    )
    advance_clock(clock_to)
    return read_account(account["id"]), get_success_data(
        api_client.get_payment_plan(plan["id"], COLLECTOR))


# ---------------------------------------------------------------------------
# Tier 6: recovery postings
# ---------------------------------------------------------------------------

def post_recovery(account_id, headers=None, **overrides):
    return get_success_data(api_client.post_recovery_transaction(
        post_recovery_payload(account_id, **overrides), headers or COLLECTOR))


def create_vendor_snapshot(headers=None, **overrides):
    return get_success_data(api_client.create_vendor_snapshot(
        create_vendor_snapshot_payload(**overrides), headers or OFFICER))


# ---------------------------------------------------------------------------
# Tier 7: disputes
# ---------------------------------------------------------------------------

def file_open_dispute(account_id, headers=None, **overrides):
    return get_success_data(api_client.file_dispute(
        file_dispute_payload(account_id, **overrides), headers or COLLECTOR))
