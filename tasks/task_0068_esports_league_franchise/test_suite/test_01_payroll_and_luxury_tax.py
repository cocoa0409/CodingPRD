"""Payroll variants and luxury-tax marginal-tier calculations (GET /teams/{id}/payroll).

Covers difficulty queue: dual_variant_calc (cap vs full-commitment payroll),
combinatorial_formula (marginal luxury tax), boundary_precision_check (luxury tax
at the cap boundary); and corner queue luxury-tax cases.
"""
from test_helpers import (
    validate_success,
    setup_team_with_two_contracts, setup_team_with_two_standard_contracts,
    setup_team_single_standard,
    make_team_gm_headers,
)


def test_payroll_excludes_unpromoted_two_way_salary(api):
    """PRD §3.3: "A contract counts toward the cap when its contract_type is STANDARD,
    or when its contract_type is TWO_WAY and its two_way_promoted flag is true."

    Design: Difficulty/dual_variant_calc/cap_payroll_excludes_unpromoted_two_way_vs_full_commitment
    """
    season, team, std, tw = setup_team_with_two_contracts(
        std_salary=30_000_000, two_way_salary=8_000_000, weight=3)
    res = api.get_team_payroll(team["id"], make_team_gm_headers(team["id"]))
    data = validate_success(res, 200)
    assert data["payroll_active_cents"] == 30_000_000


def test_full_commitment_includes_unpromoted_two_way_salary(api):
    """PRD §3.3: "The full-roster commitment is a second variant of the payroll sum:
    it adds base_salary_cents over all ACTIVE contracts regardless of type or
    promotion state, so unpromoted two-way salaries are included. The full commitment
    therefore exceeds the cap-counting payroll by exactly the total of all unpromoted
    two-way base salaries on the team."

    Design: Difficulty/dual_variant_calc/cap_payroll_excludes_unpromoted_two_way_vs_full_commitment
    """
    season, team, std, tw = setup_team_with_two_contracts(
        std_salary=30_000_000, two_way_salary=8_000_000, weight=3)
    res = api.get_team_payroll(team["id"], make_team_gm_headers(team["id"]))
    data = validate_success(res, 200)
    assert data["full_commitment_cents"] == 38_000_000
    assert data["full_commitment_cents"] - data["payroll_active_cents"] == 8_000_000


def test_luxury_tax_marginal_split_across_two_tiers(api):
    """PRD §2.6: "Where a calculation produces a fractional intermediate — the luxury
    tax tiers and the sponsorship league cut — the result is rounded half up to whole
    cents."
    PRD §3.3: "For transparency a team's payroll can be read on demand, returning four
    figures: the cap-counting payroll payroll_active_cents, the full-roster commitment
    full_commitment_cents, the season's salary_cap_cents, and the computed luxury_tax_cents."

    Overage 6,000,000 over cap 50,000,000 splits 5,000,000 @ 1.5 + 1,000,000 @ 2.0 = 9,500,000.

    Design: Difficulty/combinatorial_formula/luxury_tax_marginal_tiering_mode_a
    """
    season, team = setup_team_with_two_standard_contracts(30_000_000, 26_000_000)
    res = api.get_team_payroll(team["id"], make_team_gm_headers(team["id"]))
    data = validate_success(res, 200)
    assert data["payroll_active_cents"] == 56_000_000
    assert data["luxury_tax_cents"] == 9_500_000


def test_luxury_tax_top_tier_three_marginal_split(api):
    """PRD §2.6: "Where a calculation produces a fractional intermediate — the luxury
    tax tiers and the sponsorship league cut — the result is rounded half up to whole
    cents."

    Overage 14,000,000 over cap 50,000,000 splits 5M @ 1.5 + 5M @ 2.0 + 4M @ 2.5 = 27,500,000.

    Design: Corner/calculations/luxury_tax_top_tier_three_marginal_split
    """
    season, team = setup_team_with_two_standard_contracts(32_000_000, 32_000_000)
    res = api.get_team_payroll(team["id"], make_team_gm_headers(team["id"]))
    data = validate_success(res, 200)
    assert data["payroll_active_cents"] == 64_000_000
    assert data["luxury_tax_cents"] == 27_500_000


def test_luxury_tax_payroll_reported_with_tax(api):
    """PRD §3.3: "For transparency a team's payroll can be read on demand, returning four
    figures: the cap-counting payroll payroll_active_cents, the full-roster commitment
    full_commitment_cents, the season's salary_cap_cents, and the computed
    luxury_tax_cents."

    The reported salary_cap_cents echoes the season cap alongside the marginal tax.

    Design: Difficulty/combinatorial_formula/luxury_tax_marginal_tiering_mode_a
    """
    season, team = setup_team_with_two_standard_contracts(30_000_000, 26_000_000)
    res = api.get_team_payroll(team["id"], make_team_gm_headers(team["id"]))
    data = validate_success(res, 200)
    assert data["salary_cap_cents"] == 50_000_000
    assert data["luxury_tax_cents"] == 9_500_000


def test_luxury_tax_zero_at_exactly_cap(api):
    """PRD §3.3: "the hard reference cap per team in cents above which payroll incurs
    luxury tax". PRD §3.1: "salary_cap_cents, the hard reference cap per team in cents
    above which payroll incurs luxury tax".

    Payroll exactly equal to the cap yields zero overage and zero tax.

    Design: Difficulty/boundary_precision_check/luxury_tax_zero_at_cap_two_at_cap_plus_one
    """
    season, team = setup_team_single_standard(salary=50_000_000, cap=50_000_000)
    res = api.get_team_payroll(team["id"], make_team_gm_headers(team["id"]))
    data = validate_success(res, 200)
    assert data["payroll_active_cents"] == 50_000_000
    assert data["luxury_tax_cents"] == 0


def test_luxury_tax_two_at_cap_plus_one(api):
    """PRD §2.6: "Where a calculation produces a fractional intermediate — the luxury
    tax tiers and the sponsorship league cut — the result is rounded half up to whole
    cents."

    Payroll cap+1 (50,000,001) yields overage 1 taxed at tier-1 rate 1.5 → round_half_up(1.5) == 2.

    Design: Difficulty/boundary_precision_check/luxury_tax_zero_at_cap_two_at_cap_plus_one
    """
    season, team = setup_team_single_standard(salary=50_000_001, cap=50_000_000)
    res = api.get_team_payroll(team["id"], make_team_gm_headers(team["id"]))
    data = validate_success(res, 200)
    assert data["payroll_active_cents"] == 50_000_001
    assert data["luxury_tax_cents"] == 2


def test_luxury_tax_zero_at_exactly_cap_corner(api):
    """PRD §3.3: "the hard reference cap per team in cents above which payroll incurs
    luxury tax".

    Design: Corner/calculations/luxury_tax_zero_at_exactly_cap
    """
    season, team = setup_team_single_standard(salary=50_000_000, cap=50_000_000)
    res = api.get_team_payroll(team["id"], make_team_gm_headers(team["id"]))
    data = validate_success(res, 200)
    assert data["payroll_active_cents"] == 50_000_000
    assert data["luxury_tax_cents"] == 0
