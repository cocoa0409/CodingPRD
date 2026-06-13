"""Tax-rate effective-window overlap, accounting-period contiguity, and auditor
read-only enforcement.

Translates queue-A (Difficulty) resource_temporal_overlap /
tax_rate_window_overlap_same_jurisdiction and resource_temporal_overlap /
accounting_period_non_contiguous_gap_rejected; plus queue-B (Corner) rbac /
auditor_cannot_create_account.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_company_with_accounts,
    create_company_payload, create_account_payload, configure_company_payload,
    create_accounting_period_payload, create_tax_rate_payload,
    checklist_item_payload,
    make_owner_headers, make_accountant_headers, make_auditor_headers,
)

OWNER = make_owner_headers("u_owner")
ACCT = make_accountant_headers("u_acct")
AUDITOR = make_auditor_headers("u_aud")


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / tax_rate_window_overlap_same_jurisdiction
# ---------------------------------------------------------------------------

def _company_with_ca_rate(api):
    """Company with an existing CA TaxRate [2026-01-01, 2026-07-01)."""
    co = validate_success(api.create_company(create_company_payload(), OWNER), 201)
    validate_success(api.create_tax_rate(
        create_tax_rate_payload(co["id"], "CA", 875,
                                effective_from="2026-01-01T00:00:00.000Z",
                                effective_to="2026-07-01T00:00:00.000Z"), ACCT), 201)
    return co["id"]


def test_overlapping_tax_rate_same_jurisdiction_rejected(api):
    """PRD §2.10: "Within one company, the effective windows for a given
    jurisdiction must not overlap; an attempt to create a rate whose window overlaps
    an existing rate for the same jurisdiction is rejected with
    `ERR_TAX_RATE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/tax_rate_window_overlap_same_jurisdiction
    """
    co = _company_with_ca_rate(api)
    # New CA rate [2026-06-01, 2026-08-01) overlaps the existing [2026-01-01, 2026-07-01).
    resp = api.create_tax_rate(
        create_tax_rate_payload(co, "CA", 900,
                                effective_from="2026-06-01T00:00:00.000Z",
                                effective_to="2026-08-01T00:00:00.000Z"), ACCT)
    validate_error(resp, ApiErrorId.ERR_TAX_RATE_OVERLAP.value)


def test_adjacent_tax_rate_window_allowed(api):
    """PRD §2.10: "A `TaxRate` records a `rate_bps` for a `jurisdiction` that
    applies over the half-open window from inclusive `effective_from` to exclusive
    `effective_to`."

    Design: Difficulty/resource_temporal_overlap/tax_rate_window_overlap_same_jurisdiction
    """
    co = _company_with_ca_rate(api)
    # Exactly adjacent: new.effective_from == existing.effective_to -> half-open, no overlap.
    resp = api.create_tax_rate(
        create_tax_rate_payload(co, "CA", 900,
                                effective_from="2026-07-01T00:00:00.000Z",
                                effective_to="2026-10-01T00:00:00.000Z"), ACCT)
    validate_success(resp, 201)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap /
#             accounting_period_non_contiguous_gap_rejected
# ---------------------------------------------------------------------------

def _company_with_first_period(api):
    """Company configured with retained earnings and a first, now-CLOSED period
    [2026-01-01, 2026-02-01). Returns (company_id, current_version).

    The first period is CLOSED so that the contiguity rule — keyed on "the prior
    CLOSED period's end_date" (PRD §3.2 / §2.9) — applies to the next period open.
    """
    company = validate_success(api.create_company(create_company_payload(), OWNER), 201)
    co = company["id"]
    co_v1 = company["version"]
    re = validate_success(api.create_account(
        create_account_payload(co, "3900", "Retained Earnings", "EQUITY"), OWNER), 201)
    company = validate_success(api.configure_company(
        co, configure_company_payload(re["id"], co_v1), OWNER))
    co_v2 = company["version"]
    period = validate_success(api.create_accounting_period(
        create_accounting_period_payload(co, co_v2), OWNER), 201)
    period_id = period["id"]
    # Close the first period (no revenue/expense activity, checklist complete,
    # no draft entries, no in-progress reconciliations, trial balance BALANCED).
    for item in ("BANK_RECONCILED", "AR_REVIEWED", "AP_REVIEWED", "SALES_TAX_REVIEWED"):
        validate_success(api.mark_checklist_item(
            period_id, checklist_item_payload(item, True), ACCT))
    validate_success(api.begin_close_period(period_id, ACCT))
    validate_success(api.post_close_period(period_id, ACCT))
    current = validate_success(api.get_company(co, OWNER))
    return co, current["version"]


def test_non_contiguous_period_with_gap_rejected(api):
    """PRD §3.2: "A subsequent period's `start_date` must equal the prior closed
    period's `end_date`, and a violation is rejected with
    `ERR_PERIOD_NOT_CONTIGUOUS`."

    Design: Difficulty/resource_temporal_overlap/accounting_period_non_contiguous_gap_rejected
    """
    co, current_v = _company_with_first_period(api)
    # First period ends 2026-02-01; a second starting 2026-03-01 leaves a gap.
    resp = api.create_accounting_period(
        create_accounting_period_payload(
            co, current_v, period_label="2026-03",
            start_date="2026-03-01T00:00:00.000Z", end_date="2026-04-01T00:00:00.000Z"), OWNER)
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CONTIGUOUS.value)


def test_period_start_before_prior_end_rejected(api):
    """PRD §3.2: "A subsequent period's `start_date` must equal the prior closed
    period's `end_date`, and a violation is rejected with
    `ERR_PERIOD_NOT_CONTIGUOUS`."

    Design: Difficulty/resource_temporal_overlap/accounting_period_non_contiguous_gap_rejected
    """
    co, current_v = _company_with_first_period(api)
    # First period ends 2026-02-01; a second starting 2026-01-15 does not equal it
    # (a backward/overlapping start), so the contiguity equality is violated.
    resp = api.create_accounting_period(
        create_accounting_period_payload(
            co, current_v, period_label="2026-01b",
            start_date="2026-01-15T00:00:00.000Z", end_date="2026-02-15T00:00:00.000Z"), OWNER)
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CONTIGUOUS.value)


# ---------------------------------------------------------------------------
# Corner: rbac / auditor_cannot_create_account
# ---------------------------------------------------------------------------

def test_auditor_cannot_create_account(api):
    """PRD §2.1: "The `Auditor` has read-only access to every resource, including
    financial statements and 1099 totals, and may not mutate anything."

    Design: Corner/rbac/auditor_cannot_create_account
    """
    co = validate_success(api.create_company(create_company_payload(), OWNER), 201)
    resp = api.create_account(
        create_account_payload(co["id"], "1000", "Cash", "ASSET", is_cash=True), AUDITOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
