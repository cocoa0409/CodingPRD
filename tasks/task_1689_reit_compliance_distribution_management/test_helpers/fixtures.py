"""Composite setup helpers for multi-step test prerequisites.

Setup calls use get_success_data() so a failed precondition surfaces as a
clear "Setup step failed" message instead of a confusing assertion error.

OCC note (PRD §2.6): drafting an E&P adjustment or a dividend declaration
requires expected_reit_version equal to the REIT's current version, and many
transitions advance that version (PRD §3.5-§3.7). Helpers therefore re-read
the REIT immediately before every OCC-guarded create.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_asset_holding_payload,
    create_asset_sale_payload,
    create_asset_test_report_payload,
    create_compliance_disclosure_payload,
    create_distribution_requirement_payload,
    create_dividend_declaration_payload,
    create_ep_adjustment_payload,
    create_income_item_payload,
    create_income_test_report_payload,
    create_quarter_payload,
    create_reit_payload,
    create_shareholder_payload,
    create_shareholder_position_payload,
    create_shareholder_snapshot_payload,
)
from .test_users import (
    TEST_USERS,
    make_board_director_headers,
    make_compliance_officer_headers,
)

OFFICER = TEST_USERS["compliance_officer_headers"]
TAX = TEST_USERS["tax_director_headers"]
DIRECTOR = TEST_USERS["board_director_headers"]


# ─── Tier 1: single-entity creation / reads ───────────

def create_reit(**overrides) -> dict:
    """Register a REIT (TaxDirector). Returns the created REIT."""
    res = api_client.create_reit(create_reit_payload(**overrides), TAX)
    return get_success_data(res)


def get_reit(reit_id: str) -> dict:
    return get_success_data(api_client.get_reit(reit_id, OFFICER))


def current_reit_version(reit_id: str) -> int:
    return get_reit(reit_id)["version"]


def create_quarter(reit_id: str, label: str = "2026-Q1",
                   period_start: str = "2026-01-01",
                   period_end: str = "2026-03-31", **overrides) -> dict:
    payload = create_quarter_payload(
        reit_id, label=label, period_start=period_start,
        period_end=period_end, **overrides,
    )
    return get_success_data(api_client.create_quarter(payload, OFFICER))


def create_asset_holding(reit_id: str, **overrides) -> dict:
    payload = create_asset_holding_payload(reit_id, **overrides)
    return get_success_data(api_client.create_asset_holding(payload, OFFICER))


def create_income_item(reit_id: str, quarter_id: str, **overrides) -> dict:
    payload = create_income_item_payload(reit_id, quarter_id, **overrides)
    return get_success_data(api_client.create_income_item(payload, OFFICER))


def create_shareholder(reit_id: str, display_name: str,
                       holder_type: str = "INDIVIDUAL") -> dict:
    payload = create_shareholder_payload(reit_id, display_name, holder_type)
    return get_success_data(api_client.create_shareholder(payload, OFFICER))


def create_snapshot(reit_id: str, snapshot_date: str = "2026-06-30",
                    total_shares_outstanding: int = 1000) -> dict:
    payload = create_shareholder_snapshot_payload(
        reit_id, snapshot_date=snapshot_date,
        total_shares_outstanding=total_shares_outstanding,
    )
    return get_success_data(
        api_client.create_shareholder_snapshot(payload, OFFICER)
    )


def add_position(snapshot_id: str, shareholder_id: str, shares_held: int) -> dict:
    payload = create_shareholder_position_payload(
        snapshot_id, shareholder_id, shares_held
    )
    return get_success_data(
        api_client.create_shareholder_position(payload, OFFICER)
    )


def finalize_snapshot(snapshot_id: str) -> dict:
    return get_success_data(
        api_client.finalize_shareholder_snapshot(snapshot_id, OFFICER)
    )


def create_asset_test_report(reit_id: str, quarter_id: str) -> dict:
    payload = create_asset_test_report_payload(reit_id, quarter_id)
    return get_success_data(api_client.create_asset_test_report(payload, OFFICER))


def create_income_test_report(reit_id: str, quarter_id: str) -> dict:
    payload = create_income_test_report_payload(reit_id, quarter_id)
    return get_success_data(api_client.create_income_test_report(payload, OFFICER))


def lock_asset_test_report(report_id: str) -> dict:
    return get_success_data(api_client.lock_asset_test_report(report_id, OFFICER))


def lock_income_test_report(report_id: str) -> dict:
    return get_success_data(api_client.lock_income_test_report(report_id, OFFICER))


def create_ep_adjustment(reit_id: str, quarter_id: str, kind: str,
                         amount_cents: int, effective_date: str) -> dict:
    """Draft an E&P adjustment with a fresh OCC version (PRD §2.6)."""
    version = current_reit_version(reit_id)
    payload = create_ep_adjustment_payload(
        reit_id, quarter_id, expected_reit_version=version,
        kind=kind, amount_cents=amount_cents, effective_date=effective_date,
    )
    return get_success_data(api_client.create_ep_adjustment(payload, TAX))


def create_posted_ep_adjustment(reit_id: str, quarter_id: str,
                                kind: str = "TAXABLE_INCOME",
                                amount_cents: int = 100_000,
                                effective_date: str = "2026-01-15") -> dict:
    """Draft + post an E&P adjustment. Returns the POSTED adjustment."""
    adj = create_ep_adjustment(reit_id, quarter_id, kind, amount_cents,
                               effective_date)
    return get_success_data(api_client.post_ep_adjustment(adj["id"], TAX))


def create_posted_requirement(reit_id: str, taxable_year: int = 2026,
                              taxable_income_cents: int = 500_000,
                              net_capital_gain_cents: int = 0) -> dict:
    """Create + post a distribution requirement. Returns the POSTED row."""
    payload = create_distribution_requirement_payload(
        reit_id, taxable_year=taxable_year,
        taxable_income_cents=taxable_income_cents,
        net_capital_gain_cents=net_capital_gain_cents,
    )
    req = get_success_data(
        api_client.create_distribution_requirement(payload, OFFICER)
    )
    return get_success_data(
        api_client.post_distribution_requirement(req["id"], OFFICER)
    )


# ─── Tier 2/3: dividend lifecycle shortcuts ───────────

def create_dividend(reit_id: str, taxable_year: int = 2026,
                    amount_cents: int = 10_000,
                    declaration_date: str = "2026-03-01",
                    record_date: str = "2026-03-10",
                    payable_date: str = "2026-03-20") -> dict:
    """Draft a dividend (PENDING_APPROVAL) with a fresh OCC version."""
    version = current_reit_version(reit_id)
    payload = create_dividend_declaration_payload(
        reit_id, expected_reit_version=version, taxable_year=taxable_year,
        amount_cents=amount_cents, declaration_date=declaration_date,
        record_date=record_date, payable_date=payable_date,
    )
    return get_success_data(api_client.create_dividend_declaration(payload, OFFICER))


def approve_dividend(declaration_id: str, director_id: str = "director-1") -> dict:
    return get_success_data(
        api_client.approve_dividend_declaration(
            declaration_id, make_board_director_headers(director_id)
        )
    )


def declare_dividend(declaration_id: str, officer_id: str = "officer-1") -> dict:
    return get_success_data(
        api_client.declare_dividend_declaration(
            declaration_id, make_compliance_officer_headers(officer_id)
        )
    )


def create_approved_dividend(reit_id: str, taxable_year: int = 2026,
                             amount_cents: int = 10_000,
                             director_id: str = "director-1", **kw) -> dict:
    """Create + board-approve a dividend. Returns the APPROVED declaration."""
    div = create_dividend(reit_id, taxable_year, amount_cents, **kw)
    return approve_dividend(div["id"], director_id)


def create_declared_dividend(reit_id: str, taxable_year: int = 2026,
                             amount_cents: int = 10_000,
                             director_id: str = "director-1",
                             officer_id: str = "officer-1", **kw) -> dict:
    """Create + approve + declare. Approver and declarer differ so the
    segregation-of-duties gate of PRD §3.6 is satisfied."""
    div = create_approved_dividend(
        reit_id, taxable_year, amount_cents, director_id=director_id, **kw
    )
    return declare_dividend(div["id"], officer_id)


# ─── Tier 2: quarterly report setups ──────────────────

def setup_reit_with_open_quarter(ticker_label: str = "2026-Q1") -> tuple:
    """REIT + one OPEN quarter 2026-Q1. Returns (reit, quarter)."""
    reit = create_reit()
    quarter = create_quarter(reit["id"], label=ticker_label)
    return reit, quarter


def create_locked_quarter_via_asset_test(reit_id: str,
                                         quarter_id: str | None = None) -> tuple:
    """Give the REIT a single 100% REAL_ESTATE asset, then create + lock an
    asset test report so the quarter ends LOCKED with passing ratios.
    Returns (quarter, locked_report)."""
    if quarter_id is None:
        quarter_id = create_quarter(reit_id)["id"]
    create_asset_holding(reit_id, asset_name="Passing Tower",
                         asset_class="REAL_ESTATE", value_cents=100_000_000)
    report = create_asset_test_report(reit_id, quarter_id)
    locked = lock_asset_test_report(report["id"])
    quarter = get_success_data(api_client.get_quarter(quarter_id, OFFICER))
    return quarter, locked


def setup_reit_with_ep_balance(ep_amount_cents: int,
                               effective_date: str = "2026-01-15") -> tuple:
    """REIT + OPEN quarter + one POSTED TAXABLE_INCOME adjustment, so the
    REIT's current_ep_balance_cents equals ep_amount_cents.
    Returns (reit, quarter)."""
    reit, quarter = setup_reit_with_open_quarter()
    if ep_amount_cents != 0:
        create_posted_ep_adjustment(
            reit["id"], quarter["id"], kind="TAXABLE_INCOME",
            amount_cents=ep_amount_cents, effective_date=effective_date,
        )
    return get_reit(reit["id"]), quarter


# ─── Tier 4: shareholder-concentration targeting ──────

def setup_snapshot_with_positions(reit_id: str, positions: list,
                                  snapshot_date: str = "2026-06-30",
                                  total_shares_outstanding: int = 1000) -> dict:
    """Create a DRAFT snapshot and add one position per (shareholder, shares)
    pair. ``positions`` is a list of (shareholder_id, shares_held).
    Returns the snapshot row (still DRAFT)."""
    snapshot = create_snapshot(reit_id, snapshot_date, total_shares_outstanding)
    for shareholder_id, shares_held in positions:
        add_position(snapshot["id"], shareholder_id, shares_held)
    return snapshot


def finalize_failing_snapshot(reit_id: str, snapshot_date: str = "2026-06-30") -> dict:
    """Finalize a snapshot that fails the 5/50 test: one INDIVIDUAL holder at
    60.0000% (top-5 = 60.0000 > 50.0000) and one ENTITY holder at 40.0000%.
    Returns {"snapshot": finalized, "individual": dom, "entity": pub}."""
    dom = create_shareholder(reit_id, "Dominant Holder", "INDIVIDUAL")
    pub = create_shareholder(reit_id, "Public Fund", "ENTITY")
    snapshot = setup_snapshot_with_positions(
        reit_id, [(dom["id"], 600), (pub["id"], 400)],
        snapshot_date=snapshot_date, total_shares_outstanding=1000,
    )
    finalized = finalize_snapshot(snapshot["id"])
    return {"snapshot": finalized, "individual": dom, "entity": pub}


# ─── Tier 2/3: asset sales and disclosures ────────────

def create_asset_sale(reit_id: str, asset_holding_id: str, **overrides) -> dict:
    payload = create_asset_sale_payload(reit_id, asset_holding_id, **overrides)
    return get_success_data(api_client.create_asset_sale(payload, OFFICER))


def analyze_sale(sale_id: str) -> dict:
    return get_success_data(api_client.analyze_asset_sale(sale_id, OFFICER))


def confirm_sale(sale_id: str) -> dict:
    return get_success_data(api_client.confirm_asset_sale(sale_id, TAX))


def create_analyzed_sale(reit_id: str, asset_holding_id: str, **overrides) -> dict:
    sale = create_asset_sale(reit_id, asset_holding_id, **overrides)
    return analyze_sale(sale["id"])


def create_disclosure(reit_id: str, disclosure_type: str, reference_id: str,
                      **overrides) -> dict:
    payload = create_compliance_disclosure_payload(
        reit_id, disclosure_type, reference_id, **overrides
    )
    return get_success_data(
        api_client.create_compliance_disclosure(payload, OFFICER)
    )


def submit_disclosure(disclosure_id: str, officer_id: str = "officer-1") -> dict:
    return get_success_data(
        api_client.submit_compliance_disclosure(
            disclosure_id, make_compliance_officer_headers(officer_id)
        )
    )


def setup_locked_income_test_report(reit_id: str, quarter_id: str) -> dict:
    """Post passing income (RENTS 800000 / MORTGAGE_INTEREST 150000 /
    NON_QUALIFYING 50000 -> 80.0000% and 95.0000%) and lock an income test
    report. Returns the LOCKED report."""
    create_income_item(reit_id, quarter_id, income_class="RENTS",
                       amount_cents=800_000, accrued_at="2026-02-01")
    create_income_item(reit_id, quarter_id, income_class="MORTGAGE_INTEREST",
                       amount_cents=150_000, accrued_at="2026-02-15")
    create_income_item(reit_id, quarter_id, income_class="NON_QUALIFYING",
                       amount_cents=50_000, accrued_at="2026-03-01")
    report = create_income_test_report(reit_id, quarter_id)
    return lock_income_test_report(report["id"])
