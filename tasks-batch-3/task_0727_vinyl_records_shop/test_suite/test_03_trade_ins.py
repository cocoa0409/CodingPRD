"""Trade-in dual-variant valuation, per-line rounding, and reversal conservation.

Queue A: dual_variant_calc/trade_in_provisional_vs_final_credit,
         combinatorial_formula/trade_in_round_per_line_then_sum,
         compensating_invariant/trade_in_reverse_conserves_allocation_of_credit_and_inventory.
Queue B: trade_in_approve_incomplete_inspection_rejected.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_customer_headers,
    register_customer, setup_trade_in_with_lines, submit_trade_in,
    setup_trade_in_under_inspection, setup_trade_in_approved,
)

GRADER = TEST_USERS["grader_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Queue A — trade_in_provisional_vs_final_credit (>=2 tests)
# ---------------------------------------------------------------------------
def _submit_credit_trade_in_two_lines(api):
    """CREDIT trade-in: line1 VG base 3000, line2 NM base 1000. Submitted (provisional)."""
    lines = [
        {"format": "VINYL", "claimed_grade": "VG", "base_value_cents": 3000},
        {"format": "CD", "claimed_grade": "NM", "base_value_cents": 1000},
    ]
    customer, ti, created = setup_trade_in_with_lines(
        api, payout_method="CREDIT", lines=lines, customer=register_customer(api, full_name="Seller"))
    submit_trade_in(api, customer=customer, trade_in=ti)
    return customer, ti, created


def test_trade_in_provisional_value_from_claimed_grades(api):
    """PRD §3.6: "The provisional variant, computed at submission, uses each line's
    claimed_grade and never applies the credit bonus, since the bonus is an
    inspection-verified reward."
    PRD §3.6: "VG at 0.30 ... NM at 0.50 ... this per-line product is rounded half up to
    whole cents before anything is summed."

    Design: Difficulty/dual_variant_calc/trade_in_provisional_vs_final_credit
    """
    customer, ti, _ = _submit_credit_trade_in_two_lines(api)
    data = validate_success(api.get_trade_in(ti["id"], make_customer_headers(customer["id"])))
    # 3000*0.30=900, 1000*0.50=500, sum=1400; no bonus provisionally.
    assert data["provisional_value_cents"] == 1400, f"got {data['provisional_value_cents']}"


def test_trade_in_final_value_from_inspected_grades_with_bonus(api):
    """PRD §3.6: "The final variant, computed at approval, uses each line's inspected_grade;
    when the payout_method is CREDIT, the summed total is then multiplied by 1.20 (a 20
    percent credit bonus) and that result is rounded half up to whole cents." PRD §3.6:
    "Approval computes final_value_cents, credits the seller's store_credit_cents by that
    amount when the payout_method is CREDIT".

    Design: Difficulty/dual_variant_calc/trade_in_provisional_vs_final_credit
    """
    lines = [
        {"format": "VINYL", "claimed_grade": "VG", "base_value_cents": 3000},
        {"format": "CD", "claimed_grade": "NM", "base_value_cents": 1000},
    ]
    customer, approved, _ = setup_trade_in_approved(
        api, payout_method="CREDIT", lines=lines, inspected_grades=["G", "NM"],
        customer=register_customer(api, full_name="Seller"))
    # inspected: G(3000*0.20=600) + NM(1000*0.50=500) = 1100; *1.20 = 1320.
    assert approved["final_value_cents"] == 1320, f"got {approved['final_value_cents']}"
    assert approved["final_value_cents"] != approved["provisional_value_cents"]
    cust = validate_success(api.get_customer(customer["id"], make_customer_headers(customer["id"])))
    assert cust["store_credit_cents"] == 1320, f"CREDIT payout must credit 1320, got {cust['store_credit_cents']}"


# ---------------------------------------------------------------------------
# Queue A — trade_in_round_per_line_then_sum (>=2 tests)
# ---------------------------------------------------------------------------
def test_trade_in_provisional_rounds_each_line_then_sums(api):
    """PRD §3.6: "this per-line product is rounded half up to whole cents before anything
    is summed. The trade-in value is the sum of those already-rounded per-line amounts;
    the rounding order is pinned to round each line first and then sum, because summing
    first and rounding once could differ by up to one cent per line."

    Design: Difficulty/combinatorial_formula/trade_in_round_per_line_then_sum
    """
    lines = [
        {"format": "VINYL", "claimed_grade": "VG", "base_value_cents": 55},
        {"format": "VINYL", "claimed_grade": "VG", "base_value_cents": 55},
        {"format": "VINYL", "claimed_grade": "VG", "base_value_cents": 55},
    ]
    customer, ti, _ = setup_trade_in_with_lines(
        api, payout_method="CASH", lines=lines, customer=register_customer(api, full_name="Seller Two"))
    submit = validate_success(api.submit_trade_in(ti["id"], make_customer_headers(customer["id"])))
    # 55*0.30=16.5 -> 17 each; 17*3 = 51 (sum-then-round would be 50).
    assert submit["provisional_value_cents"] == 51, f"round-each-then-sum must be 51, got {submit['provisional_value_cents']}"


def test_trade_in_round_per_line_status_submitted(api):
    """PRD §3.6: "Submitting the trade-in advances it from DRAFT to SUBMITTED and requires
    at least one line; submission computes provisional_value_cents."

    Design: Difficulty/combinatorial_formula/trade_in_round_per_line_then_sum
    """
    lines = [
        {"format": "VINYL", "claimed_grade": "VG", "base_value_cents": 55},
        {"format": "VINYL", "claimed_grade": "VG", "base_value_cents": 55},
        {"format": "VINYL", "claimed_grade": "VG", "base_value_cents": 55},
    ]
    customer, ti, _ = setup_trade_in_with_lines(
        api, payout_method="CASH", lines=lines, customer=register_customer(api, full_name="Seller Three"))
    submit = validate_success(api.submit_trade_in(ti["id"], make_customer_headers(customer["id"])))
    assert submit["status"] == "SUBMITTED", f"got {submit['status']}"
    assert submit["provisional_value_cents"] == 51, f"got {submit['provisional_value_cents']}"


# ---------------------------------------------------------------------------
# Queue A — trade_in_reverse_conserves_credit_and_inventory (>=2 tests)
# ---------------------------------------------------------------------------
def _approved_credit_trade_in_one_nm_line(api):
    lines = [{"format": "CD", "claimed_grade": "NM", "base_value_cents": 1000}]
    customer, approved, created = setup_trade_in_approved(
        api, payout_method="CREDIT", lines=lines, inspected_grades=["NM"],
        customer=register_customer(api, full_name="Reverse Seller"))
    return customer, approved, created


def test_trade_in_reverse_debits_exact_credit_back_to_zero(api):
    """PRD §3.6: "A successful reversal debits store_credit_cents by final_value_cents,
    conserving credit exactly against the original approval, and voids the copies the
    trade-in had created."

    Design: Difficulty/compensating_invariant/trade_in_reverse_conserves_allocation_of_credit_and_inventory
    """
    customer, approved, _ = _approved_credit_trade_in_one_nm_line(api)
    # NM 1000*0.50=500; *1.20 = 600.
    assert approved["final_value_cents"] == 600, f"got {approved['final_value_cents']}"
    reversed_ti = validate_success(api.reverse_trade_in(approved["id"], MANAGER))
    assert reversed_ti["status"] == "REVERSED", f"got {reversed_ti['status']}"
    cust = validate_success(api.get_customer(customer["id"], make_customer_headers(customer["id"])))
    assert cust["store_credit_cents"] == 0, f"credit must return to 0, got {cust['store_credit_cents']}"


def test_trade_in_reverse_reaches_reversed_terminal(api):
    """PRD §3.6: "A Manager may reverse an approved trade-in, moving it from APPROVED to
    the terminal REVERSED."

    Design: Difficulty/compensating_invariant/trade_in_reverse_conserves_allocation_of_credit_and_inventory
    """
    customer, approved, _ = _approved_credit_trade_in_one_nm_line(api)
    reversed_ti = validate_success(api.reverse_trade_in(approved["id"], MANAGER))
    assert reversed_ti["status"] == "REVERSED", f"got {reversed_ti['status']}"
    assert reversed_ti["final_value_cents"] == 600, f"got {reversed_ti['final_value_cents']}"


# ---------------------------------------------------------------------------
# Queue B — trade_in_approve_incomplete_inspection_rejected
# ---------------------------------------------------------------------------
def test_trade_in_approve_incomplete_inspection_rejected(api):
    """PRD §3.6: "Approval advances it from UNDER_INSPECTION to the terminal APPROVED and
    requires that every line has an inspected_grade set; approving before inspection is
    complete is rejected with ERR_INSPECTION_INCOMPLETE (HTTP 422)."

    Design: Corner/validations/trade_in_approve_incomplete_inspection_rejected
    """
    lines = [
        {"format": "VINYL", "claimed_grade": "NM", "base_value_cents": 1000},
        {"format": "CD", "claimed_grade": "VG", "base_value_cents": 800},
    ]
    customer, ti, created = setup_trade_in_under_inspection(
        api, payout_method="CASH", lines=lines, customer=register_customer(api, full_name="Incomplete"))
    # Grade only the first line.
    validate_success(api.set_inspected_grade(created[0]["id"], {"inspected_grade": "NM"}, GRADER))
    resp = api.approve_trade_in(ti["id"], GRADER)
    validate_error(resp, ApiErrorId.ERR_INSPECTION_INCOMPLETE.value)
