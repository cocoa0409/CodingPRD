"""Composite setup helpers for the IRA & RMD Management benchmark.

Each fixture builds its preconditions from scratch through PRD-declared endpoints
(see PRD §3.x). The runner restarts the API server before every individual pytest
test, so each fixture starts from an empty database — no entities, no clock state.

Fixtures use `get_success_data()` (lenient validator) so setup failures surface
as clear "Setup failed" traces rather than cryptic assertion failures.

Identity threading: the AccountOwner role is entity-backed (PRD §2.1). Any
ownership-gated call against an AccountOwner-owned resource must use
`make_account_owner_headers(owner["id"])`, never the shared
`TEST_USERS["account_owner_headers"]` fallback (which carries a placeholder
X-User-ID that never matches a real owner row).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    set_clock_payload,
    create_owner_payload,
    create_account_payload,
    create_contribution_payload,
    account_version_payload,
    create_distribution_payload,
    create_conversion_payload,
    conversion_version_payload,
    create_beneficiary_designation_payload,
    create_rmd_schedule_payload,
    advance_year_rollover_payload,
    declare_deceased_payload,
)
from .test_users import TEST_USERS, make_account_owner_headers


_ADMIN = TEST_USERS["plan_admin_headers"]


# ─── Tier 0: clock (PRD §2.10) ──────────────────────────────────


def set_clock(iso8601: str) -> dict:
    """Advance the server's explicit logical UTC clock (PRD §2.10)."""
    return get_success_data(api_client.set_clock(set_clock_payload(iso8601), _ADMIN))


def advance_year_rollover(new_tax_year: int) -> dict:
    """Run the ops year-rollover capability (PRD §3.7)."""
    return get_success_data(
        api_client.advance_year_rollover(
            advance_year_rollover_payload(new_tax_year), _ADMIN
        )
    )


def get_clock_state() -> dict:
    return get_success_data(api_client.get_clock(_ADMIN))


# ─── Tier 1: leaf creators (PRD §3.1, §3.2) ─────────────────────


def create_owner(
    full_name: str = "Test Owner",
    date_of_birth: str = "1980-01-01",
    tax_id_last4: str = "1234",
    filing_status: str = "SINGLE",
    modified_agi_cents: int = 0,
    **overrides,
) -> dict:
    """Register a new AccountOwner via POST /ira/owners (PRD §3.1)."""
    res = api_client.create_owner(
        create_owner_payload(
            full_name=full_name,
            date_of_birth=date_of_birth,
            tax_id_last4=tax_id_last4,
            filing_status=filing_status,
            modified_agi_cents=modified_agi_cents,
            **overrides,
        ),
        _ADMIN,
    )
    return get_success_data(res)


def create_account(owner_id: str, account_type: str = "TRADITIONAL") -> dict:
    """Open an IRA account for an owner via POST /ira/accounts (PRD §3.2)."""
    res = api_client.create_account(
        create_account_payload(owner_id=owner_id, account_type=account_type),
        _ADMIN,
    )
    return get_success_data(res)


def get_account(account_id: str, headers: dict = None) -> dict:
    res = api_client.get_account(account_id, headers or _ADMIN)
    return get_success_data(res)


def get_owner(owner_id: str, headers: dict = None) -> dict:
    res = api_client.get_owner(owner_id, headers or _ADMIN)
    return get_success_data(res)


# ─── Tier 2: contribution lifecycle (PRD §3.3) ──────────────────


def create_pending_contribution(
    account_id: str,
    owner_id: str,
    tax_year: int,
    amount_cents: int,
    contribution_kind: str,
) -> dict:
    """Create a PENDING contribution as the AccountOwner (PRD §3.3)."""
    owner_headers = make_account_owner_headers(owner_id)
    res = api_client.create_contribution(
        create_contribution_payload(
            account_id=account_id,
            tax_year=tax_year,
            amount_cents=amount_cents,
            contribution_kind=contribution_kind,
        ),
        owner_headers,
    )
    return get_success_data(res)


def confirm_contribution(
    contribution_id: str, owner_id: str, expected_account_version: int
) -> dict:
    """Confirm a PENDING contribution as the AccountOwner (PRD §3.3)."""
    owner_headers = make_account_owner_headers(owner_id)
    res = api_client.confirm_contribution(
        contribution_id,
        account_version_payload(expected_account_version),
        owner_headers,
    )
    return get_success_data(res)


def fund_account_with_contribution(
    account_id: str,
    owner_id: str,
    tax_year: int,
    amount_cents: int,
    contribution_kind: str,
) -> dict:
    """Create a contribution and immediately confirm it. Returns the confirmed contribution.

    Captures the account's current version via GET before confirming so the
    confirm carries an OCC-fresh expected_account_version (PRD §2.7).
    """
    account = get_account(account_id, make_account_owner_headers(owner_id))
    contribution = create_pending_contribution(
        account_id=account_id,
        owner_id=owner_id,
        tax_year=tax_year,
        amount_cents=amount_cents,
        contribution_kind=contribution_kind,
    )
    return confirm_contribution(
        contribution["id"], owner_id, account["version"]
    )


# ─── Tier 3: distributions (PRD §3.4) ───────────────────────────


def create_pending_distribution(
    account_id: str,
    owner_id: str,
    amount_cents: int,
    distribution_reason: str,
    tax_year: int,
    federal_withholding_cents: int = 0,
) -> dict:
    owner_headers = make_account_owner_headers(owner_id)
    res = api_client.create_distribution(
        create_distribution_payload(
            account_id=account_id,
            amount_cents=amount_cents,
            distribution_reason=distribution_reason,
            tax_year=tax_year,
            federal_withholding_cents=federal_withholding_cents,
        ),
        owner_headers,
    )
    return get_success_data(res)


def confirm_distribution(
    distribution_id: str, owner_id: str, expected_account_version: int
) -> dict:
    owner_headers = make_account_owner_headers(owner_id)
    res = api_client.confirm_distribution(
        distribution_id,
        account_version_payload(expected_account_version),
        owner_headers,
    )
    return get_success_data(res)


# ─── Tier 4: conversions (PRD §3.5) ─────────────────────────────


def initiate_conversion(
    source_account_id: str,
    target_account_id: str,
    owner_id: str,
    gross_amount_cents: int,
    aggregate_basis: bool = None,
) -> dict:
    owner_headers = make_account_owner_headers(owner_id)
    res = api_client.create_conversion(
        create_conversion_payload(
            source_account_id=source_account_id,
            target_account_id=target_account_id,
            gross_amount_cents=gross_amount_cents,
            aggregate_basis=aggregate_basis,
        ),
        owner_headers,
    )
    return get_success_data(res)


def complete_conversion(
    conversion_id: str, owner_id: str, expected_source_account_version: int
) -> dict:
    owner_headers = make_account_owner_headers(owner_id)
    res = api_client.complete_conversion(
        conversion_id,
        conversion_version_payload(expected_source_account_version),
        owner_headers,
    )
    return get_success_data(res)


# ─── Tier 5: beneficiary designations (PRD §3.6) ────────────────


def create_beneficiary(
    account_id: str,
    owner_id: str,
    beneficiary_full_name: str,
    relationship: str,
    percentage_bps: int,
) -> dict:
    owner_headers = make_account_owner_headers(owner_id)
    res = api_client.create_beneficiary_designation(
        create_beneficiary_designation_payload(
            account_id=account_id,
            beneficiary_full_name=beneficiary_full_name,
            relationship=relationship,
            percentage_bps=percentage_bps,
        ),
        owner_headers,
    )
    return get_success_data(res)


def activate_beneficiary(designation_id: str, owner_id: str) -> dict:
    owner_headers = make_account_owner_headers(owner_id)
    res = api_client.activate_beneficiary_designation(designation_id, owner_headers)
    return get_success_data(res)


def add_active_beneficiary(
    account_id: str,
    owner_id: str,
    beneficiary_full_name: str,
    relationship: str,
    percentage_bps: int,
) -> dict:
    designation = create_beneficiary(
        account_id=account_id,
        owner_id=owner_id,
        beneficiary_full_name=beneficiary_full_name,
        relationship=relationship,
        percentage_bps=percentage_bps,
    )
    return activate_beneficiary(designation["id"], owner_id)


# ─── Tier 6: RMD schedules (PRD §3.7) ───────────────────────────


def create_rmd_schedule(owner_id: str, tax_year: int) -> dict:
    res = api_client.create_rmd_schedule(
        create_rmd_schedule_payload(owner_id=owner_id, tax_year=tax_year),
        _ADMIN,
    )
    return get_success_data(res)


def get_rmd_schedule(schedule_id: str, headers: dict = None) -> dict:
    res = api_client.get_rmd_schedule(schedule_id, headers or _ADMIN)
    return get_success_data(res)


# ─── Tier 7: deceased-owner cascade (PRD §3.6) ──────────────────


def declare_deceased(owner_id: str, deceased_at: str, expected_owner_version: int) -> dict:
    res = api_client.declare_owner_deceased(
        owner_id,
        declare_deceased_payload(
            deceased_at=deceased_at,
            expected_owner_version=expected_owner_version,
        ),
        _ADMIN,
    )
    return get_success_data(res)


# ─── Tier 8: composite scenarios commonly required by tests ─────


def setup_clock_and_owner(
    iso8601: str = "2026-06-01T00:00:00Z",
    full_name: str = "Test Owner",
    date_of_birth: str = "1980-01-01",
    tax_id_last4: str = "1234",
    filing_status: str = "SINGLE",
    modified_agi_cents: int = 0,
) -> dict:
    """Set the explicit clock and register one owner (PRD §2.10, §3.1)."""
    set_clock(iso8601)
    return create_owner(
        full_name=full_name,
        date_of_birth=date_of_birth,
        tax_id_last4=tax_id_last4,
        filing_status=filing_status,
        modified_agi_cents=modified_agi_cents,
    )


def setup_owner_with_traditional_account(
    iso8601: str = "2026-06-01T00:00:00Z",
    date_of_birth: str = "1980-01-01",
    modified_agi_cents: int = 12_000_000,
    filing_status: str = "SINGLE",
    tax_id_last4: str = "1234",
    full_name: str = "Test Owner",
) -> tuple:
    """Returns (owner, traditional_account) — clock set, owner registered, one
    TRADITIONAL account opened (PRD §3.1, §3.2)."""
    owner = setup_clock_and_owner(
        iso8601=iso8601,
        full_name=full_name,
        date_of_birth=date_of_birth,
        tax_id_last4=tax_id_last4,
        filing_status=filing_status,
        modified_agi_cents=modified_agi_cents,
    )
    account = create_account(owner["id"], "TRADITIONAL")
    return owner, account


def setup_owner_with_roth_account(
    iso8601: str = "2026-06-01T00:00:00Z",
    date_of_birth: str = "1980-01-01",
    modified_agi_cents: int = 12_000_000,
    filing_status: str = "SINGLE",
) -> tuple:
    """Returns (owner, roth_account) — clock set, owner registered, one ROTH
    account opened (PRD §3.1, §3.2)."""
    owner = setup_clock_and_owner(
        iso8601=iso8601,
        date_of_birth=date_of_birth,
        filing_status=filing_status,
        modified_agi_cents=modified_agi_cents,
    )
    account = create_account(owner["id"], "ROTH")
    return owner, account


def setup_owner_with_trad_and_roth(
    iso8601: str = "2026-06-01T00:00:00Z",
    date_of_birth: str = "1980-01-01",
    modified_agi_cents: int = 12_000_000,
    filing_status: str = "SINGLE",
) -> tuple:
    """Returns (owner, trad_account, roth_account) — common Backdoor-Roth
    scaffold (PRD §3.5)."""
    owner = setup_clock_and_owner(
        iso8601=iso8601,
        date_of_birth=date_of_birth,
        filing_status=filing_status,
        modified_agi_cents=modified_agi_cents,
    )
    trad = create_account(owner["id"], "TRADITIONAL")
    roth = create_account(owner["id"], "ROTH")
    return owner, trad, roth


def setup_funded_traditional(
    iso8601: str = "2026-06-01T00:00:00Z",
    date_of_birth: str = "1980-01-01",
    modified_agi_cents: int = 12_000_000,
    filing_status: str = "SINGLE",
    amount_cents: int = 700_000,
    contribution_kind: str = "PRETAX",
    tax_year: int = 2026,
) -> tuple:
    """Returns (owner, account) — TRADITIONAL account funded by a single
    CONFIRMED contribution (PRD §3.3)."""
    owner, account = setup_owner_with_traditional_account(
        iso8601=iso8601,
        date_of_birth=date_of_birth,
        modified_agi_cents=modified_agi_cents,
        filing_status=filing_status,
    )
    fund_account_with_contribution(
        account_id=account["id"],
        owner_id=owner["id"],
        tax_year=tax_year,
        amount_cents=amount_cents,
        contribution_kind=contribution_kind,
    )
    refreshed = get_account(account["id"], make_account_owner_headers(owner["id"]))
    return owner, refreshed


def setup_funded_traditional_with_open_rmd(
    iso8601: str = "2026-06-01T00:00:00Z",
    date_of_birth: str = "1953-01-15",  # age 73 in 2026 EOY
    cash_cents: int = 700_000,
    tax_year: int = 2026,
) -> tuple:
    """Returns (owner, account, schedule). Owner age-at-EOY of 73, TRADITIONAL
    account holding cash_cents via one PRETAX CONFIRMED contribution, and one
    OPEN RMDSchedule created for the tax_year (PRD §3.3, §3.7)."""
    owner, account = setup_funded_traditional(
        iso8601=iso8601,
        date_of_birth=date_of_birth,
        modified_agi_cents=5_000_000,
        amount_cents=cash_cents,
        contribution_kind="PRETAX",
        tax_year=tax_year,
    )
    schedule = create_rmd_schedule(owner["id"], tax_year)
    return owner, account, schedule


def setup_inherited_traditional_with_secure_deadline(
    iso8601_alive: str = "2026-06-01T00:00:00Z",
    deceased_at: str = "2026-06-01T12:00:00Z",
    date_of_birth: str = "1953-07-07",
    cash_cents: int = 700_000,
    funding_tax_year: int = 2026,
    full_name: str = "Test Owner",
    tax_id_last4: str = "1717",
) -> tuple:
    """Returns (owner_after_death, inherited_account, beneficiary). Owner is
    funded with cash_cents in a TRADITIONAL account, has an ACTIVE
    NON_ELIGIBLE_INDIVIDUAL beneficiary, then is declared deceased, which
    cascades the account to INHERITED and stamps secure_deadline_at = deceased_at
    + 10 years (PRD §3.6)."""
    owner, account = setup_funded_traditional(
        iso8601=iso8601_alive,
        date_of_birth=date_of_birth,
        modified_agi_cents=5_000_000,
        amount_cents=cash_cents,
        contribution_kind="PRETAX",
        tax_year=funding_tax_year,
    )
    beneficiary = add_active_beneficiary(
        account_id=account["id"],
        owner_id=owner["id"],
        beneficiary_full_name="Test Beneficiary",
        relationship="NON_ELIGIBLE_INDIVIDUAL",
        percentage_bps=10000,
    )
    refreshed_owner = get_owner(owner["id"], _ADMIN)
    declare_deceased(
        owner_id=owner["id"],
        deceased_at=deceased_at,
        expected_owner_version=refreshed_owner["version"],
    )
    inherited_account = get_account(account["id"], _ADMIN)
    inherited_beneficiary = get_success_data(
        api_client.get_beneficiary_designation(beneficiary["id"], _ADMIN)
    )
    final_owner = get_owner(owner["id"], _ADMIN)
    return final_owner, inherited_account, inherited_beneficiary


def open_n_accounts(owner_id: str, n: int, account_type: str = "TRADITIONAL") -> list:
    """Open N accounts of the given type for an existing owner (PRD §3.2)."""
    return [create_account(owner_id, account_type) for _ in range(n)]
