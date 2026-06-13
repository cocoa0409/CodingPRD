"""Statement-total and contract-funding calculations.

Covers the dual-variant statement total (provisional vs final), the dual-variant
funded amount (preneed projection vs at-need chronological), the combinatorial
trust-required formula, and per-line-rounding-then-sum precision.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, get_success_data,
    create_funeral_home, create_gpl_item, create_disclosed_case,
    add_line, select_line, create_contract,
    setup_arranged_case, post_principal,
)

ADMIN = TEST_USERS["admin_headers"]
ARRANGER = TEST_USERS["arranger_headers"]
TRUST = TEST_USERS["trust_officer_headers"]


# ==========================================================================
# dual_variant_calc / case_statement_provisional_vs_final
# ==========================================================================
def test_provisional_total_includes_proposed_and_selected_lines(api):
    """PRD §3.3: "The provisional total, stored in
    statement_total_provisional_cents, is the sum of these line contributions
    over every line whose line_status is PROPOSED or SELECTED."

    A non-declinable SERVICE line (auto-SELECTED, 200000) plus a taxable
    MERCHANDISE casket left PROPOSED (150000 + round_half_up(150000*0.08)=12000
    = 162000) => provisional 362000.

    Design: Difficulty/dual_variant_calc/case_statement_provisional_vs_final
    """
    home = create_funeral_home(name="Rose Hill", sales_tax_pct=0.08,
                               state_trust_pct=0.90, trust_admin_retention_cents=5000)
    svc = create_gpl_item(home["id"], code="SVC-BASIC",
                          name="Basic services of funeral director", category="SERVICE",
                          taxable=False, non_declinable=True, preneed_trustable=True,
                          unit_price_cents=200000)
    casket = create_gpl_item(home["id"], code="CASKET-A", name="Oak casket",
                             category="MERCHANDISE", taxable=True, non_declinable=False,
                             preneed_trustable=True, unit_price_cents=150000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    add_line(case["id"], svc["id"])
    add_line(case["id"], casket["id"])

    data = validate_success(api.get_case(case["id"], ARRANGER))
    assert data["statement_total_provisional_cents"] == 362000, \
        f"provisional should be 362000, got {data['statement_total_provisional_cents']}"


def test_final_total_zero_until_gfs_issued(api):
    """PRD §3.3: "The final total, stored in statement_total_final_cents, is the
    sum of the same line contributions but over only the lines whose line_status
    is SELECTED; removed lines are excluded from both totals."
    PRD §3.2: "its computed statement_total_provisional_cents and
    statement_total_final_cents both begin at 0".

    Before GFS issuance the final total is not yet locked; gfs_issued is false.

    Design: Difficulty/dual_variant_calc/case_statement_provisional_vs_final
    """
    home = create_funeral_home(name="Rose Hill", sales_tax_pct=0.08,
                               state_trust_pct=0.90, trust_admin_retention_cents=5000)
    svc = create_gpl_item(home["id"], code="SVC-BASIC", name="Basic services",
                          category="SERVICE", taxable=False, non_declinable=True,
                          preneed_trustable=True, unit_price_cents=200000)
    casket = create_gpl_item(home["id"], code="CASKET-A", name="Oak casket",
                             category="MERCHANDISE", taxable=True, non_declinable=False,
                             preneed_trustable=True, unit_price_cents=150000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    add_line(case["id"], svc["id"])
    add_line(case["id"], casket["id"])

    data = validate_success(api.get_case(case["id"], ARRANGER))
    assert data["statement_total_final_cents"] == 0, \
        f"final should be 0 before GFS, got {data['statement_total_final_cents']}"
    assert data["gfs_issued"] is False


# ==========================================================================
# dual_variant_calc / contract_funded_preneed_projection_vs_at_need_chronological
# ==========================================================================
def test_preneed_funded_amount_adds_projection_to_principal(api):
    """PRD §3.4: "For a PRENEED_TRUST contract it is the sum of
    trust_principal_cents, credited_earnings_cents, and projected_earnings_cents".
    PRD §3.4: "For a PRENEED_TRUST contract it is the contract's
    trust_principal_cents multiplied by a projection rate of three percent, with
    the fractional cent discarded by taking the floor".

    Principal 360000 => projected floor(360000*0.03)=10800 => funded 370800.

    Design: Difficulty/dual_variant_calc/contract_funded_preneed_projection_vs_at_need_chronological
    """
    home = create_funeral_home(name="Rose Hill", sales_tax_pct=0.08,
                               state_trust_pct=0.90, trust_admin_retention_cents=5000)
    svc = create_gpl_item(home["id"], code="SVC-BASIC", name="Basic services",
                          category="SERVICE", taxable=False, non_declinable=True,
                          preneed_trustable=True, unit_price_cents=200000)
    casket = create_gpl_item(home["id"], code="CASKET-A", name="Oak casket",
                             category="MERCHANDISE", taxable=True, non_declinable=False,
                             preneed_trustable=True, unit_price_cents=150000)
    case = create_disclosed_case(home["id"], case_mode="PRENEED", date_of_death=None)
    add_line(case["id"], svc["id"])
    casket_line = add_line(case["id"], casket["id"])
    select_line(case["id"], casket_line["id"])
    contract = create_contract(case["id"], "PRENEED_TRUST")
    get_success_data(api.issue_gfs(case["id"], ARRANGER))
    post_principal(contract["id"], 360000)

    data = validate_success(api.get_contract(contract["id"], TRUST))
    assert data["funding_type"] == "PRENEED_TRUST"
    assert data["trust_principal_cents"] == 360000
    assert data["projected_earnings_cents"] == 10800
    assert data["funded_amount_cents"] == 370800
    assert data["contract_amount_cents"] == 362000


def test_at_need_funded_amount_is_chronological_sum_no_projection(api):
    """PRD §3.4: "For an AT_NEED_DIRECT contract it is the chronological sum of
    the amounts of every posted principal deposit ... this variant counts only
    realized posted principal payments, with no earnings and no projection."

    Two POSTED principal deposits 200000 + 162000 = 362000, projection 0.

    Design: Difficulty/dual_variant_calc/contract_funded_preneed_projection_vs_at_need_chronological
    """
    home, case, svc, contract = setup_arranged_case(
        funding_type="AT_NEED_DIRECT", case_mode="AT_NEED", svc_price=200000)
    post_principal(contract["id"], 200000)
    post_principal(contract["id"], 162000)

    data = validate_success(api.get_contract(contract["id"], TRUST))
    assert data["funded_amount_cents"] == 362000
    assert data["projected_earnings_cents"] == 0, \
        "AT_NEED_DIRECT has no projection term"


# ==========================================================================
# combinatorial_formula / trust_required_conditional_tiered_floor
# ==========================================================================
def test_trust_required_applies_state_pct_then_subtracts_retention(api):
    """PRD §3.4: "take that trustable base multiplied by the home's
    state_trust_pct, rounded half up to a whole cent, to get the gross
    requirement; then subtract the home's trust_admin_retention_cents and take
    the larger of 0 and the result."

    Trustable base 362000 * 0.90 = 325800; minus 5000 retention => 320800.

    Design: Difficulty/combinatorial_formula/trust_required_conditional_tiered_floor
    """
    home = create_funeral_home(name="Rose Hill", sales_tax_pct=0.08,
                               state_trust_pct=0.90, trust_admin_retention_cents=5000)
    svc = create_gpl_item(home["id"], code="SVC-BASIC", name="Basic services",
                          category="SERVICE", taxable=False, non_declinable=True,
                          preneed_trustable=True, unit_price_cents=200000)
    casket = create_gpl_item(home["id"], code="CASKET-A", name="Oak casket",
                             category="MERCHANDISE", taxable=True, non_declinable=False,
                             preneed_trustable=True, unit_price_cents=150000)
    case = create_disclosed_case(home["id"], case_mode="PRENEED", date_of_death=None)
    add_line(case["id"], svc["id"])
    casket_line = add_line(case["id"], casket["id"])
    select_line(case["id"], casket_line["id"])
    contract = create_contract(case["id"], "PRENEED_TRUST")
    get_success_data(api.issue_gfs(case["id"], ARRANGER))

    data = validate_success(api.get_contract(contract["id"], ARRANGER))
    assert data["trust_required_cents"] == 320800
    assert data["contract_amount_cents"] == 362000


def test_trust_required_is_zero_for_non_preneed_contract(api):
    """PRD §3.4: "The required trust principal, trust_required_cents, depends on
    the funding type. For any contract that is not PRENEED_TRUST, it is 0."

    Design: Difficulty/combinatorial_formula/trust_required_conditional_tiered_floor
    """
    home, case, svc, contract = setup_arranged_case(
        funding_type="AT_NEED_DIRECT", case_mode="AT_NEED", svc_price=200000)

    data = validate_success(api.get_contract(contract["id"], ARRANGER))
    assert data["trust_required_cents"] == 0, \
        "non-preneed contract requires zero trust principal"


# ==========================================================================
# combinatorial_formula / statement_total_per_line_rounding_then_sum
# ==========================================================================
def test_statement_total_rounds_each_line_before_summing(api):
    """PRD §3.3: "The statement total is computed by rounding each line's tax
    individually and then summing — never by summing first and rounding once."

    Two taxable lines of 631 (tax 631*0.08=50.48 -> 50 each => 681 each) plus a
    non-declinable 100000 => 100000 + 681 + 681 = 101362. Sum-then-round would
    give 101363.

    Design: Difficulty/combinatorial_formula/statement_total_per_line_rounding_then_sum
    """
    home = create_funeral_home(name="Rounding Home", sales_tax_pct=0.08,
                               state_trust_pct=0.90)
    svc = create_gpl_item(home["id"], code="SVC-BASIC", name="Basic services",
                          category="SERVICE", taxable=False, non_declinable=True,
                          preneed_trustable=True, unit_price_cents=100000)
    token = create_gpl_item(home["id"], code="TOKEN", name="Memorial token",
                            category="MERCHANDISE", taxable=True, non_declinable=False,
                            preneed_trustable=True, unit_price_cents=631)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    add_line(case["id"], svc["id"])
    l1 = add_line(case["id"], token["id"])
    l2 = add_line(case["id"], token["id"])
    select_line(case["id"], l1["id"])
    select_line(case["id"], l2["id"])

    data = validate_success(api.get_case(case["id"], ARRANGER))
    assert data["statement_total_provisional_cents"] == 101362
    assert data["statement_total_provisional_cents"] != 101363


def test_single_taxable_line_tax_rounded_half_up(api):
    """PRD §3.3: "if the line is taxable, its tax is that subtotal multiplied by
    the home's sales_tax_pct, rounded half up to a whole cent".

    A single taxable line of 150000 => tax round_half_up(150000*0.08)=12000 =>
    line contribution 162000.

    Design: Difficulty/combinatorial_formula/statement_total_per_line_rounding_then_sum
    """
    home = create_funeral_home(name="Rose Hill", sales_tax_pct=0.08,
                               state_trust_pct=0.90)
    casket = create_gpl_item(home["id"], code="CASKET", name="Casket",
                             category="MERCHANDISE", taxable=True, non_declinable=False,
                             unit_price_cents=150000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    line = add_line(case["id"], casket["id"])
    select_line(case["id"], line["id"])

    data = validate_success(api.get_case(case["id"], ARRANGER))
    assert data["statement_total_provisional_cents"] == 162000
