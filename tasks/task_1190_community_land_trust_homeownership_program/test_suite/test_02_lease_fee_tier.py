"""Ground-lease monthly fee tier formula — low-income vs middle tier divergence."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_lease_payload,
    create_program_payload,
    create_unit_payload,
    get_success_data,
    setup_eligible_household,
)


def _pa():
    return TEST_USERS["platform_admin_headers"]


def _pga():
    return TEST_USERS["program_admin_headers"]


def _lm():
    return TEST_USERS["lease_manager_headers"]


def _activate_and_get_fee(prog_id: str, unit_id: str, lease_id: str) -> int:
    unit_now = get_success_data(api_client.get_unit(prog_id, unit_id, _lm()))
    lease = get_success_data(
        api_client.activate_lease(
            prog_id,
            unit_id,
            lease_id,
            {"expected_unit_version": unit_now["version"]},
            _lm(),
        )
    )
    return lease["monthly_fee_cents"]


def test_lease_fee_low_income_tier_at_050_gets_half_off():
    """PRD §3.3: "If the household's `ami_pct` is at most 0.50 (boundary
    inclusive — an `ami_pct` of exactly 0.50 lands in this tier), the monthly
    fee is the base multiplied by one minus `low_income_fee_reduction_pct`,
    rounded half-up to integer cents."

    Design: Difficulty/dual_variant_calc/lease_fee_tier_low_income_vs_middle_boundary
    """
    pa = _pa()
    prog = get_success_data(
        api_client.create_program(
            create_program_payload(
                name="P-LOW",
                area_median_income_cents=10_000_000,
                ground_lease_base_fee_cents=50_000,
                low_income_fee_reduction_pct=0.5,
            ),
            pa,
        )
    )
    # Household size 4, income = 0.50 * 10_000_000 * 1.00 = 5_000_000 cents
    hh, _, _ = setup_eligible_household(
        prog["id"], verified_income_cents=5_000_000, household_size=4
    )
    unit = get_success_data(
        api_client.create_unit(prog["id"], create_unit_payload(address="1 L St"), _pga())
    )
    lease = get_success_data(
        api_client.create_lease(
            prog["id"],
            unit["id"],
            create_lease_payload(household_id=hh["id"]),
            _lm(),
        )
    )
    fee = _activate_and_get_fee(prog["id"], unit["id"], lease["id"])
    # 50000 * (1 - 0.5) = 25000
    assert fee == 25_000, f"Expected 25000, got {fee}"


def test_lease_fee_middle_income_tier_at_070_tapers_linearly():
    """PRD §3.3: "If `ami_pct` is greater than 0.50 and at most 0.80
    (boundary inclusive — an `ami_pct` of exactly 0.80 lands in this middle
    tier), the fee is the base multiplied by one minus the product of
    `low_income_fee_reduction_pct` and the ratio formed by dividing the
    difference between 0.80 and `ami_pct` by 0.30, again rounded half-up to
    integer cents."

    Design: Difficulty/dual_variant_calc/lease_fee_tier_low_income_vs_middle_boundary
    """
    pa = _pa()
    prog = get_success_data(
        api_client.create_program(
            create_program_payload(
                name="P-MID",
                area_median_income_cents=10_000_000,
                ground_lease_base_fee_cents=50_000,
                low_income_fee_reduction_pct=0.5,
            ),
            pa,
        )
    )
    # size 4, income = 0.70 * 10_000_000 = 7_000_000
    hh, _, _ = setup_eligible_household(
        prog["id"], verified_income_cents=7_000_000, household_size=4
    )
    unit = get_success_data(
        api_client.create_unit(prog["id"], create_unit_payload(address="1 M St"), _pga())
    )
    lease = get_success_data(
        api_client.create_lease(
            prog["id"],
            unit["id"],
            create_lease_payload(household_id=hh["id"]),
            _lm(),
        )
    )
    fee = _activate_and_get_fee(prog["id"], unit["id"], lease["id"])
    # base * (1 - 0.5 * (0.80 - 0.70) / 0.30) = 50000 * (1 - 0.5 * 1/3)
    # = 50000 * (1 - 0.16666...) = 50000 * 0.83333... = 41666.66.. → 41667
    assert fee == 41_667, f"Expected 41667, got {fee}"


def test_lease_fee_tiers_low_vs_middle_diverge():
    """PRD §3.3: "The effect is a linear subsidy taper between 50% and 80% AMI,
    with full subsidy below 50% and no subsidy above 80%."

    Design: Difficulty/dual_variant_calc/lease_fee_tier_low_income_vs_middle_boundary
    """
    pa = _pa()
    prog = get_success_data(
        api_client.create_program(
            create_program_payload(
                name="P-CMP",
                area_median_income_cents=10_000_000,
                ground_lease_base_fee_cents=50_000,
                low_income_fee_reduction_pct=0.5,
            ),
            pa,
        )
    )
    hh_l, _, _ = setup_eligible_household(
        prog["id"], verified_income_cents=5_000_000, household_size=4, legal_name="H Low"
    )
    hh_m, _, _ = setup_eligible_household(
        prog["id"], verified_income_cents=7_000_000, household_size=4, legal_name="H Mid"
    )
    unit_l = get_success_data(
        api_client.create_unit(prog["id"], create_unit_payload(address="1 Low St"), _pga())
    )
    unit_m = get_success_data(
        api_client.create_unit(prog["id"], create_unit_payload(address="1 Mid St"), _pga())
    )
    lease_l = get_success_data(
        api_client.create_lease(
            prog["id"], unit_l["id"],
            create_lease_payload(household_id=hh_l["id"]),
            _lm(),
        )
    )
    lease_m = get_success_data(
        api_client.create_lease(
            prog["id"], unit_m["id"],
            create_lease_payload(household_id=hh_m["id"]),
            _lm(),
        )
    )
    fee_l = _activate_and_get_fee(prog["id"], unit_l["id"], lease_l["id"])
    fee_m = _activate_and_get_fee(prog["id"], unit_m["id"], lease_m["id"])
    assert fee_l != fee_m, (
        f"LOW tier fee ({fee_l}) must differ from MIDDLE tier fee ({fee_m})"
    )
    assert fee_l < fee_m, "Lower AMI must pay less than middle AMI"
