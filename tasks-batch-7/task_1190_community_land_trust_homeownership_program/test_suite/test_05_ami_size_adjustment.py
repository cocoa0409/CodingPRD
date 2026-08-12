"""AMI percentage — tiered household-size adjustment lookup."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_household_payload,
    create_income_certification_payload,
    create_program_payload,
    get_success_data,
)


def _pa():
    return TEST_USERS["platform_admin_headers"]


def _is():
    return TEST_USERS["intake_specialist_headers"]


def _co():
    return TEST_USERS["compliance_officer_headers"]


def _submit_cert(prog_id: str, hh_id: str, income_cents: int, size: int) -> dict:
    cert = get_success_data(
        api_client.create_income_certification(
            prog_id,
            hh_id,
            create_income_certification_payload(
                reported_annual_income_cents=income_cents,
                verified_annual_income_cents=income_cents,
                household_size_at_cert=size,
            ),
            _is(),
        )
    )
    return get_success_data(
        api_client.get_income_certification(prog_id, hh_id, cert["id"], _co())
    )


def test_ami_pct_size_1_uses_070_adjustment():
    """PRD §3.2: "The size adjustment is a fixed lookup table: a household of
    1 uses 0.70; 2 uses 0.80; 3 uses 0.90; 4 uses 1.00; 5 uses 1.08; 6 uses
    1.16; 7 uses 1.24; 8 or more uses 1.32."
    PRD §3.2: "...the ratio of `verified_annual_income_cents` to the product of
    the program's `area_median_income_cents` and a household-size adjustment
    factor, rounded half-up to 4 decimal places."

    Design: Difficulty/combinatorial_formula/ami_pct_size_adjustment_tiered_lookup
    """
    prog = get_success_data(
        api_client.create_program(create_program_payload(name="P-A1"), _pa())
    )
    hh = get_success_data(
        api_client.create_household(
            prog["id"],
            create_household_payload(household_size=1, annual_gross_income_cents=5_000_000),
            _is(),
        )
    )
    cert = _submit_cert(prog["id"], hh["id"], 5_000_000, 1)
    # ami = 5_000_000 / (10_000_000 * 0.70) = 5/7 = 0.7142857... → 0.7143
    assert cert["ami_pct_at_cert"] == pytest.approx(0.7143, abs=1e-9)


def test_ami_pct_size_4_uses_100_adjustment():
    """PRD §3.2: "The size adjustment is a fixed lookup table: a household of
    1 uses 0.70; 2 uses 0.80; 3 uses 0.90; 4 uses 1.00; 5 uses 1.08; 6 uses
    1.16; 7 uses 1.24; 8 or more uses 1.32."

    Design: Difficulty/combinatorial_formula/ami_pct_size_adjustment_tiered_lookup
    """
    prog = get_success_data(
        api_client.create_program(create_program_payload(name="P-A4"), _pa())
    )
    hh = get_success_data(
        api_client.create_household(
            prog["id"],
            create_household_payload(household_size=4, annual_gross_income_cents=5_000_000),
            _is(),
        )
    )
    cert = _submit_cert(prog["id"], hh["id"], 5_000_000, 4)
    # ami = 5_000_000 / (10_000_000 * 1.00) = 0.5000
    assert cert["ami_pct_at_cert"] == pytest.approx(0.5000, abs=1e-9)


def test_ami_pct_size_8_uses_132_adjustment():
    """PRD §3.2: "The size adjustment is a fixed lookup table: a household of
    1 uses 0.70; 2 uses 0.80; 3 uses 0.90; 4 uses 1.00; 5 uses 1.08; 6 uses
    1.16; 7 uses 1.24; 8 or more uses 1.32."

    Design: Difficulty/combinatorial_formula/ami_pct_size_adjustment_tiered_lookup
    """
    prog = get_success_data(
        api_client.create_program(create_program_payload(name="P-A8"), _pa())
    )
    hh = get_success_data(
        api_client.create_household(
            prog["id"],
            create_household_payload(household_size=8, annual_gross_income_cents=5_000_000),
            _is(),
        )
    )
    cert = _submit_cert(prog["id"], hh["id"], 5_000_000, 8)
    # ami = 5_000_000 / (10_000_000 * 1.32) = 5/13.2 = 0.3787878... → 0.3788
    assert cert["ami_pct_at_cert"] == pytest.approx(0.3788, abs=1e-9)
