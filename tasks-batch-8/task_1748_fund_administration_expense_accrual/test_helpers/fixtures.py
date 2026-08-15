"""Composite setup helpers.

The interesting claims in this PRD require the system to be in a specific
state that takes many API calls to reach (a fund with a class, shares, a
position, prices, an accounting record, possibly finalized, possibly with a
waiver agreement and a breach-triggering cap test). These helpers encapsulate
those multi-step preambles so tests can focus on assertions.

Every helper uses the lenient setup validator so a setup failure surfaces as
a clear "Setup step failed" error rather than a confusing assertion mismatch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    D_NAV,
    D_NAV_NEXT,
    D_OPEN,
    D_PAYABLE,
    T_NAV,
    T_NAV_NEXT,
    T_PAYABLE,
)
from .factories import (
    create_distribution_payload,
    create_expense_accrual_payload,
    create_fee_invoice_payload,
    create_fund_payload,
    create_nav_record_payload,
    create_position_payload,
    create_price_observation_payload,
    create_reconciliation_break_payload,
    create_regulatory_filing_payload,
    create_security_payload,
    create_share_class_payload,
    create_waiver_agreement_payload,
)
from .test_users import (
    TEST_USERS,
    make_fund_accountant_headers,
    make_fund_controller_headers,
    make_compliance_officer_headers,
)

ACCT = TEST_USERS["fund_accountant_headers"]
CTRL = TEST_USERS["fund_controller_headers"]
PC = TEST_USERS["pricing_committee_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# --- Atomic steps ------------------------------------------------------------


def set_logical_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.4)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, CTRL)
    )


def create_fund(**overrides) -> dict:
    """Create a fund (FundController). Returns the fund."""
    return get_success_data(
        api_client.create_fund(create_fund_payload(**overrides), CTRL)
    )


def create_share_class(fund_id: str, **overrides) -> dict:
    """Create a share class (FundController). Returns the class."""
    return get_success_data(
        api_client.create_share_class(create_share_class_payload(fund_id, **overrides), CTRL)
    )


def create_security(**overrides) -> dict:
    """Register a security (FundAccountant). Returns the security."""
    return get_success_data(
        api_client.create_security(create_security_payload(**overrides), ACCT)
    )


def subscribe_shares(share_class_id: str, shares, activity_date: str = D_OPEN,
                     user_id: str = None) -> dict:
    """Record a SUBSCRIPTION capital activity. Returns the updated class."""
    headers = make_fund_accountant_headers(user_id) if user_id else ACCT
    return get_success_data(
        api_client.post_capital_activity(
            share_class_id,
            {"activity_type": "SUBSCRIPTION", "activity_date": activity_date,
             "shares": shares},
            headers,
        )
    )


def post_income(share_class_id: str, amount, activity_date: str = D_NAV_NEXT) -> dict:
    """Record an INCOME_POSTING capital activity. Returns the updated class."""
    return get_success_data(
        api_client.post_capital_activity(
            share_class_id,
            {"activity_type": "INCOME_POSTING", "activity_date": activity_date,
             "amount": amount},
            ACCT,
        )
    )


def open_position(share_class_id: str, security_id: str, quantity=1000,
                  cost_basis_total=50000, opened_date: str = D_OPEN,
                  user_id: str = None) -> dict:
    """Open a position (FundAccountant). Returns the position."""
    headers = make_fund_accountant_headers(user_id) if user_id else ACCT
    return get_success_data(
        api_client.create_position(
            create_position_payload(
                share_class_id, security_id, quantity=quantity,
                cost_basis_total=cost_basis_total, opened_date=opened_date,
            ),
            headers,
        )
    )


def submit_price(security_id: str, price_date: str = D_NAV, price=100.00,
                 source: str = "EXCHANGE_CLOSE", pricing_level: str = "LEVEL_1",
                 user_id: str = None) -> dict:
    """Submit a price observation (lands SUBMITTED). Returns the observation."""
    headers = make_fund_accountant_headers(user_id) if user_id else ACCT
    return get_success_data(
        api_client.create_price_observation(
            create_price_observation_payload(
                security_id, price_date=price_date, price=price, source=source,
                pricing_level=pricing_level,
            ),
            headers,
        )
    )


def approve_price(price_observation_id: str) -> dict:
    """Approve a SUBMITTED observation (PricingCommittee)."""
    return get_success_data(
        api_client.approve_price_observation(price_observation_id, PC)
    )


def create_nav(share_class_id: str, accounting_date: str = D_NAV,
               user_id: str = "acct_1") -> dict:
    """Create the daily accounting record (FundAccountant, ESTIMATED).

    A distinct user id is the default because only the record's creator is
    barred from finalizing it (segregation of duties, PRD §2.7)."""
    return get_success_data(
        api_client.create_nav_record(
            create_nav_record_payload(share_class_id, accounting_date=accounting_date),
            make_fund_accountant_headers(user_id),
        )
    )


def finalize_nav(nav_record_id: str, expected_version=None,
                 user_id: str = "ctl_1") -> dict:
    """Finalize a record (FundController). When expected_version is None the
    record is re-read first so the OCC field is current (PRD §2.8)."""
    if expected_version is None:
        expected_version = get_success_data(
            api_client.get_nav_record(nav_record_id, CTRL)
        )["version"]
    return get_success_data(
        api_client.finalize_nav_record(
            nav_record_id,
            {"expected_nav_record_version": expected_version},
            make_fund_controller_headers(user_id),
        )
    )


def reopen_nav(nav_record_id: str, user_id: str = "ctl_1") -> dict:
    """Reopen the latest FINAL record (FundController)."""
    return get_success_data(
        api_client.reopen_nav_record(
            nav_record_id, make_fund_controller_headers(user_id)
        )
    )


def create_manual_accrual(share_class_id: str, accrual_date: str,
                          category: str = "OTHER", annual_rate_bps=0.1) -> dict:
    """Book a manual (non-ADMIN_FEE) accrual onto an ESTIMATED record's date."""
    return get_success_data(
        api_client.create_expense_accrual(
            create_expense_accrual_payload(
                share_class_id, accrual_date, category=category,
                annual_rate_bps=annual_rate_bps,
            ),
            ACCT,
        )
    )


def create_waiver_agreement(share_class_id: str, cap_bps=10,
                            effective_from: str = "2026-08-01",
                            effective_to: str = "2026-12-31",
                            recovery_window_months: int = 3) -> dict:
    """Create an expense-cap agreement (FundController)."""
    return get_success_data(
        api_client.create_waiver_agreement(
            create_waiver_agreement_payload(
                share_class_id, cap_bps=cap_bps, effective_from=effective_from,
                effective_to=effective_to,
                recovery_window_months=recovery_window_months,
            ),
            CTRL,
        )
    )


def get_agreement(waiver_agreement_id: str) -> dict:
    return get_success_data(
        api_client.get_waiver_agreement(waiver_agreement_id, CTRL)
    )


def create_break(fund_id: str, position_id: str, counterparty_quantity=900,
                 break_type: str = "CUSTODIAN_POSITION",
                 break_date: str = D_NAV) -> dict:
    """Record a reconciliation break (FundAccountant). Returns the break."""
    return get_success_data(
        api_client.create_reconciliation_break(
            create_reconciliation_break_payload(
                fund_id, position_id, break_type=break_type,
                break_date=break_date, counterparty_quantity=counterparty_quantity,
            ),
            ACCT,
        )
    )


def create_filing(fund_id: str, filing_type: str = "N_PORT",
                  period_end: str = "2026-07-31",
                  user_id: str = "comp_1") -> dict:
    """Create a regulatory filing (ComplianceOfficer, DRAFT)."""
    return get_success_data(
        api_client.create_regulatory_filing(
            create_regulatory_filing_payload(
                fund_id, filing_type=filing_type, period_end=period_end
            ),
            make_compliance_officer_headers(user_id),
        )
    )


def submit_filing(filing_id: str, user_id: str = "comp_1") -> dict:
    return get_success_data(
        api_client.submit_filing_review(
            filing_id, make_compliance_officer_headers(user_id)
        )
    )


def approve_filing(filing_id: str, user_id: str = "ctl_1") -> dict:
    return get_success_data(
        api_client.approve_regulatory_filing(
            filing_id, make_fund_controller_headers(user_id)
        )
    )


def file_filing(filing_id: str, user_id: str = "comp_1") -> dict:
    return get_success_data(
        api_client.file_regulatory_filing(
            filing_id, make_compliance_officer_headers(user_id)
        )
    )


# --- Composite kits ----------------------------------------------------------


def base_kit(shares=10000, quantity=1000, price=100.00, price_date: str = D_NAV,
             approve: bool = False, fund_overrides=None, clock: str = T_NAV,
             ticker: str = "ALPHX", class_ticker: str = "ALPHXI",
             security_identifier: str = "CUSIP0001",
             price_source: str = "EXCHANGE_CLOSE",
             pricing_level: str = "LEVEL_1") -> dict:
    """Fund + class + subscription + security + position + one observation.

    Returns dict(fund, share_class, security, position, observation).
    The observation stays SUBMITTED unless approve=True.
    """
    if clock:
        set_logical_clock(clock)
    fund = create_fund(ticker=ticker, **(fund_overrides or {}))
    share_class = create_share_class(fund["id"], class_ticker=class_ticker)
    if shares:
        subscribe_shares(share_class["id"], shares)
    security = create_security(security_identifier=security_identifier)
    position = open_position(share_class["id"], security["id"], quantity=quantity,
                             cost_basis_total=quantity * 50)
    observation = submit_price(
        security["id"], price_date=price_date, price=price,
        source=price_source, pricing_level=pricing_level,
    )
    if approve:
        observation = approve_price(observation["id"])
    return {
        "fund": fund,
        "share_class": share_class,
        "security": security,
        "position": position,
        "observation": observation,
    }


def base_kit_with_nav(approve: bool = True, nav_user_id: str = "acct_1",
                      **kit_kwargs) -> dict:
    """base_kit plus the ESTIMATED accounting record for the price date."""
    kit = base_kit(approve=approve, **kit_kwargs)
    kit["nav"] = create_nav(
        kit["share_class"]["id"],
        accounting_date=kit_kwargs.get("price_date", D_NAV),
        user_id=nav_user_id,
    )
    return kit


def base_kit_with_final_nav(approve: bool = True, nav_user_id: str = "acct_1",
                            finalize_user_id: str = "ctl_1", **kit_kwargs) -> dict:
    """base_kit plus a FINAL accounting record (version re-read before finalize)."""
    kit = base_kit_with_nav(approve=approve, nav_user_id=nav_user_id, **kit_kwargs)
    kit["nav"] = finalize_nav(kit["nav"]["id"], user_id=finalize_user_id)
    return kit


def declared_distribution_kit(income=51.00, income_date: str = D_NAV_NEXT,
                              payable_date: str = D_PAYABLE,
                              distribution_overrides=None,
                              **kit_kwargs) -> dict:
    """FINAL record + income posting + DECLARED distribution.

    Returns the base-kit dict with extra keys: nav (FINAL), distribution.
    """
    kit = base_kit_with_final_nav(**kit_kwargs)
    post_income(kit["share_class"]["id"], income, activity_date=income_date)
    payload_overrides = {"payable_date": payable_date}
    payload_overrides.update(distribution_overrides or {})
    kit["distribution"] = get_success_data(
        api_client.create_distribution(
            create_distribution_payload(kit["share_class"]["id"], **payload_overrides),
            ACCT,
        )
    )
    return kit


def cap_breach_kit(other_rate_bps=0.1, cap_bps=10, recovery_window_months=3,
                   effective_from: str = "2026-08-01",
                   effective_to: str = "2026-12-31",
                   quantity=3650, price=100.00) -> dict:
    """Agreement + FINAL record whose cap test breaches and books a WAIVER.

    With quantity 3650 @ 100.00 the first record's accrual base is its own
    GAV (365000.00): the automatic ADMIN_FEE row accrues 1.00 and the manual
    OTHER row at `other_rate_bps` pushes the annualized ratio strictly above
    `cap_bps`, so finalization books a WAIVER ledger entry.
    Returns dict with keys of base_kit plus agreement, nav, manual_accrual.
    """
    kit = base_kit_with_nav(
        quantity=quantity, price=price, approve=True,
    )
    kit["agreement"] = create_waiver_agreement(
        kit["share_class"]["id"], cap_bps=cap_bps,
        effective_from=effective_from, effective_to=effective_to,
        recovery_window_months=recovery_window_months,
    )
    # The agreement must exist before finalization for the cap test to apply;
    # base_kit_with_nav already created the record ESTIMATED.
    kit["manual_accrual"] = create_manual_accrual(
        kit["share_class"]["id"], kit["nav"]["accounting_date"],
        category="OTHER", annual_rate_bps=other_rate_bps,
    )
    kit["nav"] = finalize_nav(kit["nav"]["id"])
    return kit
