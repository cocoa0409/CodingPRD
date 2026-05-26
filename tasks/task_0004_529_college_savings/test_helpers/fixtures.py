"""Composite setup helpers.

Each test creates its own world (the server is restarted before every test —
the database is empty). These helpers chain primitive endpoints so that test
bodies can focus on the assertion under examination.

Identity threading rule: AccountOwner is `entity_backed:Donor`. Whenever a
fixture creates a donor and then needs to act as that donor's AccountOwner,
it uses `make_account_owner_headers(donor['id'])`.
"""
from typing import Any, Dict, Optional, Tuple
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_donor_payload,
    create_beneficiary_payload,
    create_account_payload,
    create_contribution_payload,
    create_withdrawal_payload,
    create_beneficiary_change_payload,
    create_state_tax_incentive_payload,
    create_form_1099q_payload,
    create_scheduled_contribution_payload,
    approve_withdrawal_payload,
    approve_beneficiary_change_payload,
)
from .test_users import (
    make_account_owner_headers,
    make_custodian_headers,
    make_compliance_headers,
    make_tax_authority_headers,
)


# ---------------------------------------------------------------------------
# Tier 0: clock
# ---------------------------------------------------------------------------

def set_clock(iso_utc: str) -> None:
    resp = api_client.set_clock(iso_utc, make_custodian_headers())
    get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: primitive entity creation
# ---------------------------------------------------------------------------

def create_donor(
    full_name: str = "Test Donor",
    state_code: str = "CA",
    federal_tax_id_last4: str = "1111",
    email: str = "donor@x.com",
) -> Dict[str, Any]:
    resp = api_client.create_donor(
        create_donor_payload(
            full_name=full_name,
            state_code=state_code,
            federal_tax_id_last4=federal_tax_id_last4,
            email=email,
        ),
        make_custodian_headers(),
    )
    return get_success_data(resp)


def create_beneficiary(
    full_name: str = "Test Beneficiary",
    date_of_birth: str = "2008-06-01",
    relationship_class: str = "CHILD",
    federal_tax_id_last4: str = "2222",
) -> Dict[str, Any]:
    resp = api_client.create_beneficiary(
        create_beneficiary_payload(
            full_name=full_name,
            date_of_birth=date_of_birth,
            relationship_class=relationship_class,
            federal_tax_id_last4=federal_tax_id_last4,
        ),
        make_custodian_headers(),
    )
    return get_success_data(resp)


def create_account(donor_id: str, beneficiary_id: str) -> Dict[str, Any]:
    resp = api_client.create_account(
        create_account_payload(donor_id, beneficiary_id),
        make_custodian_headers(),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: setup helpers that combine donor + beneficiary + account
# ---------------------------------------------------------------------------

def setup_donor_beneficiary_account(
    *,
    donor_state: str = "CA",
    donor_email: str = "donor@x.com",
    donor_full_name: str = "Test Donor",
    donor_tax_id: str = "1111",
    beneficiary_full_name: str = "Test Beneficiary",
    beneficiary_dob: str = "2008-06-01",
    beneficiary_relationship: str = "CHILD",
    beneficiary_tax_id: str = "2222",
    clock_iso: Optional[str] = "2026-03-01T00:00:00.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Return (donor, beneficiary, account)."""
    if clock_iso is not None:
        set_clock(clock_iso)
    donor = create_donor(
        full_name=donor_full_name,
        state_code=donor_state,
        federal_tax_id_last4=donor_tax_id,
        email=donor_email,
    )
    beneficiary = create_beneficiary(
        full_name=beneficiary_full_name,
        date_of_birth=beneficiary_dob,
        relationship_class=beneficiary_relationship,
        federal_tax_id_last4=beneficiary_tax_id,
    )
    account = create_account(donor["id"], beneficiary["id"])
    return donor, beneficiary, account


# ---------------------------------------------------------------------------
# Tier 3: posting contributions
# ---------------------------------------------------------------------------

def create_and_post_contribution(
    account_id: str,
    amount_cents: int,
    contribution_kind: str = "LUMP_SUM",
    scheduled_contribution_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a DRAFT contribution then POST it. Returns the POSTED row."""
    create_resp = api_client.create_contribution(
        create_contribution_payload(
            account_id,
            amount_cents=amount_cents,
            contribution_kind=contribution_kind,
            scheduled_contribution_id=scheduled_contribution_id,
        ),
        make_custodian_headers(),
    )
    contribution = get_success_data(create_resp)
    post_resp = api_client.post_contribution(contribution["id"], make_custodian_headers())
    return get_success_data(post_resp)


def credit_market_earnings(account_id: str, delta_cents: int) -> Dict[str, Any]:
    resp = api_client.credit_earnings(account_id, delta_cents, make_custodian_headers())
    return get_success_data(resp)


def get_account(account_id: str) -> Dict[str, Any]:
    resp = api_client.get_account(account_id, make_custodian_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: withdrawal lifecycle
# ---------------------------------------------------------------------------

def create_draft_withdrawal(
    account_id: str,
    donor_id: str,
    amount_cents: int,
    expense_class: str = "HIGHER_ED_TUITION",
) -> Dict[str, Any]:
    resp = api_client.create_withdrawal(
        create_withdrawal_payload(account_id, amount_cents=amount_cents, expense_class=expense_class),
        make_account_owner_headers(donor_id),
    )
    return get_success_data(resp)


def submit_withdrawal(withdrawal_id: str, donor_id: str) -> Dict[str, Any]:
    resp = api_client.submit_withdrawal(withdrawal_id, make_account_owner_headers(donor_id))
    return get_success_data(resp)


def approve_withdrawal(withdrawal_id: str, expected_account_version: int) -> Dict[str, Any]:
    resp = api_client.approve_withdrawal(
        withdrawal_id,
        approve_withdrawal_payload(expected_account_version),
        make_compliance_headers(),
    )
    return get_success_data(resp)


def disburse_withdrawal(withdrawal_id: str) -> Dict[str, Any]:
    resp = api_client.disburse_withdrawal(withdrawal_id, make_custodian_headers())
    return get_success_data(resp)


def submit_approve_disburse_withdrawal(
    account_id: str,
    donor_id: str,
    amount_cents: int,
    expected_account_version: int,
    expense_class: str = "HIGHER_ED_TUITION",
) -> Dict[str, Any]:
    """Create -> submit -> approve -> disburse a withdrawal in one shot.
    Returns the DISBURSED withdrawal row."""
    w = create_draft_withdrawal(account_id, donor_id, amount_cents, expense_class)
    submit_withdrawal(w["id"], donor_id)
    approved = approve_withdrawal(w["id"], expected_account_version)
    disbursed = disburse_withdrawal(approved["id"])
    return disbursed


# ---------------------------------------------------------------------------
# Tier 5: beneficiary changes
# ---------------------------------------------------------------------------

def create_beneficiary_change(
    account_id: str, donor_id: str, to_beneficiary_id: str
) -> Dict[str, Any]:
    resp = api_client.create_beneficiary_change(
        create_beneficiary_change_payload(account_id, to_beneficiary_id),
        make_account_owner_headers(donor_id),
    )
    return get_success_data(resp)


def approve_beneficiary_change(change_id: str, expected_account_version: int) -> Dict[str, Any]:
    resp = api_client.approve_beneficiary_change(
        change_id,
        approve_beneficiary_change_payload(expected_account_version),
        make_compliance_headers(),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 6: state tax incentives & forms
# ---------------------------------------------------------------------------

def create_state_tax_incentive(donor_id: str, tax_year: int) -> Dict[str, Any]:
    resp = api_client.create_state_tax_incentive(
        create_state_tax_incentive_payload(donor_id, tax_year),
        make_custodian_headers(),
    )
    return get_success_data(resp)


def calculate_state_tax_incentive(incentive_id: str) -> Dict[str, Any]:
    resp = api_client.calculate_state_tax_incentive(incentive_id, make_custodian_headers())
    return get_success_data(resp)


def create_form_1099q(account_id: str, tax_year: int) -> Dict[str, Any]:
    resp = api_client.create_form_1099q(
        create_form_1099q_payload(account_id, tax_year),
        make_tax_authority_headers(),
    )
    return get_success_data(resp)


def issue_form_1099q(form_id: str) -> Dict[str, Any]:
    resp = api_client.issue_form_1099q(form_id, make_tax_authority_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 7: scheduled contributions
# ---------------------------------------------------------------------------

def create_scheduled_contribution(
    account_id: str, donor_id: str, amount_cents: int = 50_000, cadence: str = "MONTHLY"
) -> Dict[str, Any]:
    resp = api_client.create_scheduled_contribution(
        create_scheduled_contribution_payload(account_id, amount_cents=amount_cents, cadence=cadence),
        make_account_owner_headers(donor_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 8: composite scenarios used by ≥1 difficulty instance
# ---------------------------------------------------------------------------

def setup_account_with_earnings(
    *,
    contribution_cents: int,
    market_credit_cents: int,
    clock_iso: str = "2026-03-01T00:00:00.000Z",
    donor_email: str = "donor@x.com",
    donor_state: str = "CA",
    donor_tax_id: str = "1111",
    beneficiary_tax_id: str = "2222",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], int]:
    """Donor + Beneficiary + Account + one POSTED contribution + market earnings credit.

    Returns (donor, beneficiary, account_after_credit, account_version_after_credit).
    """
    donor, beneficiary, account = setup_donor_beneficiary_account(
        clock_iso=clock_iso,
        donor_state=donor_state,
        donor_email=donor_email,
        donor_tax_id=donor_tax_id,
        beneficiary_tax_id=beneficiary_tax_id,
    )
    create_and_post_contribution(account["id"], contribution_cents)
    account_after_credit = credit_market_earnings(account["id"], market_credit_cents)
    return donor, beneficiary, account_after_credit, account_after_credit["version"]
