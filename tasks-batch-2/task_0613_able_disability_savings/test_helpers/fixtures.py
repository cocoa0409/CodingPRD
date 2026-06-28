"""Composite setup helpers for the ABLE program API.

Each test runs against a fresh, empty database (the harness restarts the server
before every test), so every fixture builds its preconditions from scratch using
only PRD-declared endpoints. Fixtures use the lenient get_success_data() validator
so setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_program_payload,
    create_investment_option_payload,
    create_beneficiary_payload,
    create_certification_payload,
    create_account_payload,
    create_representative_payload,
    create_contribution_payload,
    create_distribution_payload,
    create_qde_record_payload,
    create_medicaid_claim_payload,
)
from .test_users import (
    make_program_admin_headers,
    make_beneficiary_headers,
    make_medicaid_agency_headers,
)

ADMIN = make_program_admin_headers()


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2: base entity hierarchy
# ---------------------------------------------------------------------------
def create_program(**program_overrides) -> dict:
    """Create a Program with the standard configuration; returns the Program."""
    resp = api_client.create_program(create_program_payload(**program_overrides), ADMIN)
    return get_success_data(resp)


def create_investment_option(program_id, **overrides) -> dict:
    resp = api_client.create_investment_option(
        create_investment_option_payload(program_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_beneficiary(program_id, **overrides) -> dict:
    resp = api_client.create_beneficiary(create_beneficiary_payload(program_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_pending_certification(beneficiary_id, **overrides) -> dict:
    resp = api_client.create_certification(
        beneficiary_id, create_certification_payload(**overrides), ADMIN
    )
    return get_success_data(resp)


def certify_beneficiary(beneficiary_id, **cert_overrides) -> dict:
    """Create a certification and approve it; returns the CERTIFIED Certification."""
    cert = create_pending_certification(beneficiary_id, **cert_overrides)
    resp = api_client.decide_certification(cert["id"], {"decision": "APPROVE"}, ADMIN)
    return get_success_data(resp)


def setup_program_and_option(**program_overrides):
    """Returns (program, investment_option)."""
    program = create_program(**program_overrides)
    option = create_investment_option(program["id"])
    return program, option


def setup_certified_beneficiary(program_overrides=None, beneficiary_overrides=None,
                                cert_overrides=None):
    """Active program + option + a CERTIFIED beneficiary.
    Returns (program, option, beneficiary)."""
    program, option = setup_program_and_option(**(program_overrides or {}))
    beneficiary = create_beneficiary(program["id"], **(beneficiary_overrides or {}))
    certify_beneficiary(beneficiary["id"], **(cert_overrides or {}))
    # Re-fetch so eligibility_status reflects the approval.
    beneficiary = get_success_data(api_client.get_beneficiary(beneficiary["id"], ADMIN))
    return program, option, beneficiary


def setup_open_account(program_overrides=None, beneficiary_overrides=None,
                       cert_overrides=None, account_overrides=None):
    """Full chain to an OPEN account for a CERTIFIED beneficiary.
    Returns (program, option, beneficiary, account)."""
    program, option, beneficiary = setup_certified_beneficiary(
        program_overrides, beneficiary_overrides, cert_overrides
    )
    resp = api_client.create_account(
        create_account_payload(beneficiary["id"], option["id"], **(account_overrides or {})), ADMIN
    )
    account = get_success_data(resp)
    return program, option, beneficiary, account


# ---------------------------------------------------------------------------
# Tier 4: accumulation / balance targeting
# ---------------------------------------------------------------------------
def post_contribution(account_id, amount_cents, expected_account_version, headers=None,
                      **overrides):
    """Post a contribution; returns the Contribution data."""
    resp = api_client.create_contribution(
        account_id,
        create_contribution_payload(amount_cents, expected_account_version, **overrides),
        headers or ADMIN,
    )
    return get_success_data(resp)


def credit_earnings(account_id, earnings_delta_cents) -> dict:
    """Credit (or debit) earnings; returns the updated Account."""
    resp = api_client.credit_earnings(account_id, earnings_delta_cents, ADMIN)
    return get_success_data(resp)


def setup_account_with_balance(target_basis_cents, earnings_delta_cents=0,
                               program_overrides=None, beneficiary_overrides=None,
                               account_overrides=None, contributor_is_beneficiary=False):
    """Open account, post one REGULAR contribution of target_basis_cents, then
    optionally credit earnings. Returns (program, option, beneficiary, account)
    where account is re-fetched to reflect the final ledger.
    """
    program, option, beneficiary, account = setup_open_account(
        program_overrides, beneficiary_overrides, None, account_overrides
    )
    if target_basis_cents > 0:
        headers = (
            make_beneficiary_headers(beneficiary["id"]) if contributor_is_beneficiary else ADMIN
        )
        post_contribution(account["id"], target_basis_cents, account["version"], headers=headers)
    if earnings_delta_cents:
        credit_earnings(account["id"], earnings_delta_cents)
    account = get_success_data(api_client.get_account(account["id"], ADMIN))
    return program, option, beneficiary, account


# ---------------------------------------------------------------------------
# Tier 3: distribution lifecycle shortcuts
# ---------------------------------------------------------------------------
def request_distribution(account_id, amount_cents, beneficiary_id, **overrides) -> dict:
    """Request a distribution as the owning beneficiary; returns the Distribution."""
    resp = api_client.create_distribution(
        account_id,
        create_distribution_payload(amount_cents, **overrides),
        make_beneficiary_headers(beneficiary_id),
    )
    return get_success_data(resp)


def approve_distribution(distribution_id, beneficiary_id) -> dict:
    resp = api_client.approve_distribution(distribution_id, make_beneficiary_headers(beneficiary_id))
    return get_success_data(resp)


def disburse_distribution(distribution_id, expected_account_version, beneficiary_id) -> dict:
    resp = api_client.disburse_distribution(
        distribution_id,
        {"expected_account_version": expected_account_version},
        make_beneficiary_headers(beneficiary_id),
    )
    return get_success_data(resp)


def setup_disbursed_distribution(distribution_amount_cents, basis_cents, earnings_delta_cents,
                                 category="HEALTH", program_overrides=None):
    """OPEN account funded (REGULAR basis_cents + credited earnings), one distribution
    requested, approved, and disbursed. Returns
    (program, option, beneficiary, account, distribution) where distribution is
    re-fetched post-disbursement to expose earnings_portion_cents.
    """
    program, option, beneficiary, account = setup_open_account(program_overrides=program_overrides)
    ben_headers = make_beneficiary_headers(beneficiary["id"])
    post_contribution(account["id"], basis_cents, account["version"], headers=ben_headers)
    if earnings_delta_cents:
        credit_earnings(account["id"], earnings_delta_cents)
    account = get_success_data(api_client.get_account(account["id"], ADMIN))
    dist = request_distribution(account["id"], distribution_amount_cents, beneficiary["id"],
                                category=category)
    approve_distribution(dist["id"], beneficiary["id"])
    disburse_distribution(dist["id"], account["version"], beneficiary["id"])
    dist = get_success_data(api_client.get_distribution(dist["id"], ben_headers))
    account = get_success_data(api_client.get_account(account["id"], ADMIN))
    return program, option, beneficiary, account, dist


def attach_qde_record(distribution_id, amount_cents, beneficiary_id, **overrides) -> dict:
    resp = api_client.create_qde_record(
        distribution_id,
        create_qde_record_payload(amount_cents, **overrides),
        make_beneficiary_headers(beneficiary_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: representatives
# ---------------------------------------------------------------------------
def add_representative(account_id, beneficiary_id, **overrides) -> dict:
    """Add an ACTIVE representative as the owning beneficiary; returns the rep."""
    resp = api_client.create_representative(
        account_id,
        create_representative_payload(**overrides),
        make_beneficiary_headers(beneficiary_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: death / Medicaid payback terminal lifecycle
# ---------------------------------------------------------------------------
def record_death(beneficiary_id) -> dict:
    resp = api_client.record_death(beneficiary_id, ADMIN)
    return get_success_data(resp)


def setup_frozen_account(basis_cents, earnings_delta_cents=0, account_overrides=None,
                         program_overrides=None):
    """OPEN account funded, then death recorded -> FROZEN_DEATH. No pending APPROVED
    distributions. Returns (program, option, beneficiary, account) with account
    re-fetched in FROZEN_DEATH state.
    """
    program, option, beneficiary, account = setup_open_account(
        program_overrides=program_overrides, account_overrides=account_overrides
    )
    if basis_cents > 0:
        post_contribution(account["id"], basis_cents, account["version"])
    if earnings_delta_cents:
        credit_earnings(account["id"], earnings_delta_cents)
    record_death(beneficiary["id"])
    account = get_success_data(api_client.get_account(account["id"], ADMIN))
    return program, option, beneficiary, account


def file_medicaid_claim(account_id, claimed_amount_cents) -> dict:
    resp = api_client.file_medicaid_claim(
        account_id, create_medicaid_claim_payload(claimed_amount_cents), make_medicaid_agency_headers()
    )
    return get_success_data(resp)


def setup_filed_medicaid_claim(basis_cents, earnings_delta_cents, claimed_amount_cents,
                               account_overrides=None):
    """FROZEN_DEATH account with a FILED Medicaid claim.
    Returns (program, option, beneficiary, account, claim)."""
    program, option, beneficiary, account = setup_frozen_account(
        basis_cents, earnings_delta_cents, account_overrides=account_overrides
    )
    claim = file_medicaid_claim(account["id"], claimed_amount_cents)
    return program, option, beneficiary, account, claim


# ---------------------------------------------------------------------------
# Convenience: re-fetch helpers (used by assertions in tests)
# ---------------------------------------------------------------------------
def get_account(account_id, headers=None) -> dict:
    return get_success_data(api_client.get_account(account_id, headers or ADMIN))


def get_distribution(distribution_id, headers=None) -> dict:
    return get_success_data(api_client.get_distribution(distribution_id, headers or ADMIN))


def get_beneficiary(beneficiary_id, headers=None) -> dict:
    return get_success_data(api_client.get_beneficiary(beneficiary_id, headers or ADMIN))


def get_certification(certification_id, headers=None) -> dict:
    return get_success_data(api_client.get_certification(certification_id, headers or ADMIN))


def get_representative(representative_id, headers=None) -> dict:
    return get_success_data(api_client.get_representative(representative_id, headers or ADMIN))


def get_contribution(contribution_id, headers=None) -> dict:
    return get_success_data(api_client.get_contribution(contribution_id, headers or ADMIN))


def get_medicaid_claim(claim_id, headers=None) -> dict:
    return get_success_data(api_client.get_medicaid_claim(claim_id, headers or ADMIN))
