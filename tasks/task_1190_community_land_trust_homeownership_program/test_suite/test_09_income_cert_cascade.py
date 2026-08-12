"""Income cert approval cascade — Household.ami_pct refresh + GroundLease.monthly_fee_cents recompute."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_income_certification_payload,
    get_success_data,
    setup_active_lease,
    setup_program,
)


def _co():
    return TEST_USERS["compliance_officer_headers"]


def _is():
    return TEST_USERS["intake_specialist_headers"]


def _lm():
    return TEST_USERS["lease_manager_headers"]


def test_approval_recomputes_household_ami_pct():
    """PRD §3.2: "The household's `ami_pct` is replaced with the latest
    approved certification's `ami_pct_at_cert`."

    Design: Difficulty/transitive_cascade/income_cert_approval_cascade_to_fee_and_eligibility
    """
    prog = setup_program(
        name="P-CAS3", low_income_fee_reduction_pct=0.5
    )
    # Household at 0.70 AMI initially.
    _, _, hh, _ = setup_active_lease(prog["id"], household_income_cents=7_000_000)

    # Submit a second cert with lower income (0.50 AMI).
    cert2 = get_success_data(
        api_client.create_income_certification(
            prog["id"],
            hh["id"],
            create_income_certification_payload(
                tax_year=2026,
                reported_annual_income_cents=5_000_000,
                verified_annual_income_cents=5_000_000,
                household_size_at_cert=4,
            ),
            _is(),
        )
    )
    get_success_data(
        api_client.start_review_income_certification(prog["id"], hh["id"], cert2["id"], _co())
    )
    get_success_data(
        api_client.approve_income_certification(prog["id"], hh["id"], cert2["id"], _co())
    )

    hh_after = get_success_data(api_client.get_household(prog["id"], hh["id"], _co()))
    assert hh_after["ami_pct"] == pytest.approx(0.5000, abs=1e-9)


def test_approval_recomputes_active_lease_monthly_fee():
    """PRD §3.2: "If the household currently holds an active lease, its
    lease's `monthly_fee_cents` is recomputed under the tiered formula
    described in §3.3, and every `PENDING` `LeaseFee` row for that lease
    whose `due_date` is in the future is re-amounted to the new fee."

    Design: Difficulty/transitive_cascade/income_cert_approval_cascade_to_fee_and_eligibility
    """
    prog = setup_program(
        name="P-CAS4", low_income_fee_reduction_pct=0.5
    )
    # Setup: 0.70 AMI → fee should initially be 41667 (middle tier with base=50000, reduction=0.5).
    _, unit, hh, lease = setup_active_lease(
        prog["id"], household_income_cents=7_000_000
    )
    initial = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease["id"], _lm())
    )
    assert initial["monthly_fee_cents"] == 41_667

    # New cert at 0.50 AMI (low-income tier).
    cert2 = get_success_data(
        api_client.create_income_certification(
            prog["id"],
            hh["id"],
            create_income_certification_payload(
                tax_year=2026,
                reported_annual_income_cents=5_000_000,
                verified_annual_income_cents=5_000_000,
                household_size_at_cert=4,
            ),
            _is(),
        )
    )
    get_success_data(
        api_client.start_review_income_certification(prog["id"], hh["id"], cert2["id"], _co())
    )
    get_success_data(
        api_client.approve_income_certification(prog["id"], hh["id"], cert2["id"], _co())
    )

    lease_after = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease["id"], _lm())
    )
    # 0.50 AMI → low tier: 50000 * (1 - 0.5) = 25000.
    assert lease_after["monthly_fee_cents"] == 25_000
