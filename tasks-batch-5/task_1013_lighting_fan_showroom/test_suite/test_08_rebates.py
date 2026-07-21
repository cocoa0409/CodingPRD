"""Energy rebate claims: per-line rounding, eligibility gate, budget conservation (PRD §3.9)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_program, create_fixture, create_order, add_line, create_claim,
    setup_energy_star_order,
)

SM = TEST_USERS["sm_headers"]


# --------------------------- combinatorial: round per line then sum ----------------------
def test_rebate_claimed_cents_rounds_each_line_then_sums(api):
    """PRD §3.9: "The `claimed_cents` is built by taking, for each eligible line, the line's
    `unit_price_cents` times its `quantity` times the program's `rebate_rate`, rounding that
    per-line amount half-up to whole cents, and then summing those rounded per-line amounts —
    the rounding is applied to each line before the sum, not to the total."

    Design: Difficulty/combinatorial_formula/rebate_round_per_line_then_sum
    """
    prog, fx, order, lines = setup_energy_star_order(
        api, base_price_cents=2010, base_wattage=60, wattage_ceiling=100,
        budget_total_cents=100000000, rebate_rate=0.075, num_lines=3,
    )
    resp = api.create_rebate_claim({"order_id": order["id"], "rebate_program_id": prog["id"]}, SM)
    claim = validate_success(resp, 201)
    assert claim["claimed_cents"] == 453


def test_rebate_claimed_cents_persisted_value(api):
    """PRD §3.9: "The `claimed_cents` is built by taking, for each eligible line, the line's
    `unit_price_cents` times its `quantity` times the program's `rebate_rate`, rounding that
    per-line amount half-up to whole cents, and then summing those rounded per-line amounts —
    the rounding is applied to each line before the sum, not to the total."

    Design: Difficulty/combinatorial_formula/rebate_round_per_line_then_sum
    """
    prog, fx, order, lines = setup_energy_star_order(
        api, base_price_cents=2010, base_wattage=60, wattage_ceiling=100,
        budget_total_cents=100000000, rebate_rate=0.075, num_lines=3,
    )
    claim = create_claim(api, order["id"], prog["id"])
    fetched = validate_success(api.get_rebate_claim(claim["id"], SM), 200)
    assert fetched["claimed_cents"] == 453


# --------------------------- boundary: zero eligible lines -------------------------------
def test_rebate_no_energy_star_line_rejected(api):
    """PRD §3.9: "A line is eligible when its fixture's `energy_star` is true, when the line's
    effective wattage is at most the program's `wattage_ceiling`, and when the line is still
    `ACTIVE`. A claim must have at least one eligible line; a claim with none is rejected with
    `ERR_NO_ELIGIBLE_ITEMS`."

    Design: Difficulty/boundary_precision_check/rebate_zero_eligible_empty_set
    """
    prog = create_program(api, rebate_rate=0.075, wattage_ceiling=100, budget_total_cents=100000)
    fx = create_fixture(api, sku_base="F-NE", category="RECESSED", base_price_cents=3000,
                        base_wattage=40, energy_star=False)
    order = create_order(api, customer_name="NE")
    add_line(api, order["id"], fx["id"], quantity=2)
    resp = api.create_rebate_claim({"order_id": order["id"], "rebate_program_id": prog["id"]}, SM)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_ITEMS.value)


def test_rebate_wattage_over_ceiling_rejected(api):
    """PRD §3.9: "A line is eligible when its fixture's `energy_star` is true, when the line's
    effective wattage is at most the program's `wattage_ceiling`, and when the line is still
    `ACTIVE`. A claim must have at least one eligible line; a claim with none is rejected with
    `ERR_NO_ELIGIBLE_ITEMS`."

    Design: Difficulty/boundary_precision_check/rebate_zero_eligible_empty_set
    """
    prog = create_program(api, rebate_rate=0.075, wattage_ceiling=100, budget_total_cents=100000)
    fx = create_fixture(api, sku_base="F-HW", category="RECESSED", base_price_cents=3000,
                        base_wattage=200, energy_star=True)  # wattage 200 > ceiling 100
    order = create_order(api, customer_name="HW")
    add_line(api, order["id"], fx["id"], quantity=1)
    resp = api.create_rebate_claim({"order_id": order["id"], "rebate_program_id": prog["id"]}, SM)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_ITEMS.value)


# --------------------------- compensating invariant: budget approve/void ------------------
def test_rebate_approve_debits_program_budget(api):
    """PRD §3.9: "A successful approval moves the claim to `APPROVED` and debits the program's
    `budget_remaining_cents` by `claimed_cents`."

    Design: Difficulty/compensating_invariant/rebate_budget_approve_void_conserved
    """
    prog, fx, order, lines = setup_energy_star_order(
        api, base_price_cents=2000, base_wattage=50, wattage_ceiling=100,
        budget_total_cents=1000000, rebate_rate=0.075, num_lines=1,
    )
    claim = create_claim(api, order["id"], prog["id"])  # claimed_cents 150
    validate_success(api.approve_rebate_claim(claim["id"], SM), 200)
    program = validate_success(api.get_rebate_program(prog["id"], SM), 200)
    assert program["budget_remaining_cents"] == 999850


def test_rebate_void_restores_program_budget(api):
    """PRD §3.9: "A claim that has been approved may later be voided, which moves it to `VOID`
    and restores the program's `budget_remaining_cents` by the same `claimed_cents`,
    compensating the earlier debit."

    Design: Difficulty/compensating_invariant/rebate_budget_approve_void_conserved
    """
    prog, fx, order, lines = setup_energy_star_order(
        api, base_price_cents=2000, base_wattage=50, wattage_ceiling=100,
        budget_total_cents=1000000, rebate_rate=0.075, num_lines=1,
    )
    claim = create_claim(api, order["id"], prog["id"])
    api.approve_rebate_claim(claim["id"], SM)
    voided = validate_success(api.void_rebate_claim(claim["id"], SM), 200)
    assert voided["status"] == "VOID"
    program = validate_success(api.get_rebate_program(prog["id"], SM), 200)
    assert program["budget_remaining_cents"] == 1000000


# --------------------------- validation: approve over budget ------------------------------
def test_rebate_approve_over_budget_rejected(api):
    """PRD §3.9: "Approval requires the claim to be `SUBMITTED` and requires the program's
    `budget_remaining_cents` to be at least the claim's `claimed_cents`; an approval that would
    overdraw the program is rejected with `ERR_REBATE_BUDGET_EXCEEDED`."

    Design: Corner/validations/rebate_approve_over_budget_returns_budget_exceeded
    """
    prog, fx, order, lines = setup_energy_star_order(
        api, base_price_cents=2000, base_wattage=50, wattage_ceiling=100,
        budget_total_cents=100, rebate_rate=0.075, num_lines=1,
    )
    claim = create_claim(api, order["id"], prog["id"])  # claimed 150 > budget 100
    resp = api.approve_rebate_claim(claim["id"], SM)
    validate_error(resp, ApiErrorId.ERR_REBATE_BUDGET_EXCEEDED.value)
