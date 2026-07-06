"""Combinatorial formulae: the full tiered/conditional H-1B filing fee and the
round-per-area-then-sum aggregate wage obligation (PRD §3.6, §3.4, §2.5).

Queue A / Difficulty — rule `combinatorial_formula`.
"""
from test_helpers import (
    api_client, validate_success, TEST_USERS,
    create_employer, create_lca, setup_draft_h1b_petition,
    make_employer_agent_headers, lca_payload,
)

EMPLOYER = TEST_USERS["employer_agent_headers"]


def test_filing_fee_full_stack_at_creation(api):
    """PRD §3.6: "Start from a base fee of 46000 cents. If the petition is *not*
    amended, add the fraud-prevention fee of 50000 cents; then add the ACWIA
    training fee, which is 75000 cents when the employer's `employee_count` is at
    most 25 and 150000 cents when it exceeds 25; and then, only when the
    employer's `employee_count` is greater than 50 *and* its `h1b_dependent` flag
    is true, add the Public Law 114-113 fee of 400000 cents."

    Design: Difficulty/combinatorial_formula/h1b_filing_fee_tiered_conditional
    """
    ctx = setup_draft_h1b_petition(
        employer_overrides={"employee_count": 60, "h1b_dependent": True},
        petition_overrides={"is_amended": False})
    # 46000 + 50000 + 150000 (ACWIA large) + 400000 (PL 114-113) = 646000
    assert ctx["petition"]["filing_fee_cents"] == 646000


def test_filing_fee_full_stack_persists_on_fetch(api):
    """PRD §3.6: "The resulting total is stored as `filing_fee_cents`."
    PRD §3.6: "a fetched petition exposes its `filing_fee_cents`, `rfe_status`,
    and `rfe_due_date`."

    Design: Difficulty/combinatorial_formula/h1b_filing_fee_tiered_conditional
    """
    ctx = setup_draft_h1b_petition(
        employer_overrides={"employee_count": 60, "h1b_dependent": True},
        petition_overrides={"is_amended": False})
    hdr = make_employer_agent_headers(ctx["employer"]["id"])
    fetched = validate_success(api.get_h1b_petition(ctx["petition"]["id"], hdr), 200)
    assert fetched["filing_fee_cents"] == 646000


def test_aggregate_wage_rounds_per_area_then_sums(api):
    """PRD §2.5: "That proration is rounded **half up** to a whole number of
    cents, and the rounding is applied **per worksite area before the amounts are
    summed** — never once at the end on the grand total."

    Design: Difficulty/combinatorial_formula/lca_aggregate_wage_rounding_order
    """
    emp = create_employer()
    lca = create_lca(emp["id"], worksite_areas=["AREA_A", "AREA_B"],
                     area_wage_map={"AREA_A": 10000002, "AREA_B": 10000002},
                     hours_per_week=30, prevailing_wage_cents=10000002, offered_wage_cents=12000000)
    # per area round_half_up(10000002 * 30 / 40) = round(7500001.5) = 7500002; sum = 15000004
    assert lca["aggregate_wage_obligation_cents"] == 15000004


def test_aggregate_wage_rounding_persists_on_fetch(api):
    """PRD §3.4: "iterating over `worksite_areas` in list order, each area's entry
    in `area_wage_map` is multiplied by `hours_per_week`, divided by 40, and
    rounded half up to whole cents; those per-area rounded amounts are then
    summed. The rounding is per area, before summing — never applied once to the
    total."

    Design: Difficulty/combinatorial_formula/lca_aggregate_wage_rounding_order
    """
    emp = create_employer()
    hdr = make_employer_agent_headers(emp["id"])
    lca = create_lca(emp["id"], worksite_areas=["AREA_A", "AREA_B"],
                     area_wage_map={"AREA_A": 10000002, "AREA_B": 10000002},
                     hours_per_week=30, prevailing_wage_cents=10000002, offered_wage_cents=12000000)
    fetched = validate_success(api.get_lca(lca["id"], hdr), 200)
    assert fetched["aggregate_wage_obligation_cents"] == 15000004
