"""Payment posting and waterfall allocation across obligations."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    clerk_headers, supervisor_headers,
    make_case, make_victim, make_obligation, post_payment,
    setup_case_with_obligation, setup_case_with_restitution,
    api_client,
)


class TestStatutoryPriorityAllocation:
    def test_statutory_priority_fills_highest_rank_first(self, api):
        """PRD §3.3: "Under STATUTORY_PRIORITY, the system walks that ordered list
        and gives each obligation the smaller of the payment amount still remaining
        and that obligation's balance_cents, stopping when the payment is exhausted.
        A lower-priority obligation receives nothing until every higher-priority
        obligation above it is fully covered."

        Design: Difficulty/dual_variant_calc/allocation_statutory_priority_fills_top_first
        """
        case = make_case(case_number="C-STAT")
        victim = make_victim(name="Val Payee")
        rest = make_obligation(case["id"], "RESTITUTION", 30000, victim_id=victim["id"], priority_rank=1)
        fee = make_obligation(case["id"], "COURT_FEE", 10000, priority_rank=2)

        post_payment(case["id"], 20000, "STATUTORY_PRIORITY")

        rest_after = validate_success(api.get_obligation(rest["id"], clerk_headers()))
        fee_after = validate_success(api.get_obligation(fee["id"], clerk_headers()))
        assert rest_after["paid_amount_cents"] == 20000
        assert rest_after["status"] == "PARTIALLY_PAID"
        assert fee_after["paid_amount_cents"] == 0

    def test_statutory_priority_records_single_allocation_line(self, api):
        """PRD §3.3: "For every non-zero allocation, the obligation's paid_amount_cents
        increases by the amount applied and a corresponding line is appended to the
        payment's allocations."

        Design: Difficulty/dual_variant_calc/allocation_statutory_priority_fills_top_first
        """
        case = make_case(case_number="C-STAT2")
        victim = make_victim(name="Val Payee")
        rest = make_obligation(case["id"], "RESTITUTION", 30000, victim_id=victim["id"], priority_rank=1)
        make_obligation(case["id"], "COURT_FEE", 10000, priority_rank=2)

        payment = post_payment(case["id"], 20000, "STATUTORY_PRIORITY")
        lines = payment["allocations"]
        assert len(lines) == 1, f"only the funded rank-1 obligation gets a line, got {lines}"
        assert lines[0]["obligation_id"] == rest["id"]
        assert lines[0]["amount_cents"] == 20000


class TestProRataAllocation:
    def test_prorata_floor_each_share_then_remainder_to_priority(self, api):
        """PRD §3.3: "Each candidate's provisional share is the floor of the payment
        amount multiplied by that candidate's balance_cents divided by the total.
        Flooring leaves a remainder — the payment amount minus the sum of the
        provisional shares — which is then distributed one cent at a time to
        candidates in priority_rank ascending order, breaking ties by created_at
        ascending, until the remainder is used up."

        Design: Difficulty/combinatorial_formula/prorata_floor_then_remainder_by_priority
        """
        case = make_case(case_number="C-PRORATA")
        victim = make_victim(name="Vic Prorata")
        rest = make_obligation(case["id"], "RESTITUTION", 10000, victim_id=victim["id"], priority_rank=1)
        fee = make_obligation(case["id"], "COURT_FEE", 6000, priority_rank=2)
        fine = make_obligation(case["id"], "FINE", 4000, priority_rank=3)

        post_payment(case["id"], 10001, "PRO_RATA")

        rest_after = validate_success(api.get_obligation(rest["id"], clerk_headers()))
        fee_after = validate_success(api.get_obligation(fee["id"], clerk_headers()))
        fine_after = validate_success(api.get_obligation(fine["id"], clerk_headers()))
        assert rest_after["paid_amount_cents"] == 5001, "rank-1 gets floor 5000 + the 1c remainder"
        assert fee_after["paid_amount_cents"] == 3000
        assert fine_after["paid_amount_cents"] == 2000

    def test_prorata_allocation_lines_sum_to_payment(self, api):
        """PRD §3.3: "the system first sums the balance_cents of all candidates to get
        a total. Each candidate's provisional share is the floor of the payment amount
        multiplied by that candidate's balance_cents divided by the total."

        Design: Difficulty/combinatorial_formula/prorata_floor_then_remainder_by_priority
        """
        case = make_case(case_number="C-PRORATA2")
        victim = make_victim(name="Vic Prorata")
        make_obligation(case["id"], "RESTITUTION", 10000, victim_id=victim["id"], priority_rank=1)
        make_obligation(case["id"], "COURT_FEE", 6000, priority_rank=2)
        make_obligation(case["id"], "FINE", 4000, priority_rank=3)

        payment = post_payment(case["id"], 10001, "PRO_RATA")
        total = sum(line["amount_cents"] for line in payment["allocations"])
        assert total == 10001, f"allocation lines must sum to the full payment, got {total}"
        assert len(payment["allocations"]) == 3


class TestRestitutionSatisfactionCascade:
    def test_full_payment_satisfies_restitution_and_bumps_victim(self, api):
        """PRD §3.3: "if paid plus waived now equals assessed_amount_cents, its
        balance_cents becomes zero and it moves to SATISFIED (from either OUTSTANDING
        or PARTIALLY_PAID). Whenever a RESTITUTION obligation collects money, the
        linked victim's payable_balance_cents increases by the restitution collected."

        Design: Difficulty/transitive_cascade/payment_satisfies_restitution_bumps_victim
        """
        case, victim, rest = setup_case_with_restitution(case_number="C-CASCADE2", assessed_amount_cents=10000)

        post_payment(case["id"], 10000, "STATUTORY_PRIORITY")

        rest_after = validate_success(api.get_obligation(rest["id"], clerk_headers()))
        victim_after = validate_success(api.get_victim(victim["id"], clerk_headers()))
        assert rest_after["status"] == "SATISFIED"
        assert victim_after["payable_balance_cents"] == 10000

    def test_restitution_collection_reflected_in_case_totals(self, api):
        """PRD §2.8: "total_paid_cents is the sum of paid_amount_cents across all
        obligations of the case."

        Design: Difficulty/transitive_cascade/payment_satisfies_restitution_bumps_victim
        """
        case, victim, rest = setup_case_with_restitution(case_number="C-CASCADE2B", assessed_amount_cents=10000)

        post_payment(case["id"], 10000, "STATUTORY_PRIORITY")

        rest_after = validate_success(api.get_obligation(rest["id"], clerk_headers()))
        case_after = validate_success(api.get_case(case["id"], clerk_headers()))
        assert rest_after["paid_amount_cents"] == 10000
        assert case_after["total_paid_cents"] == 10000


def test_case_status_becomes_satisfied_when_balance_zero(api):
    """PRD §2.8: "the case's status becomes SATISFIED when total_assessed_cents is
    greater than zero and the case balance_cents is exactly zero; otherwise it is OPEN."

    Design: Corner/entities/case_status_becomes_satisfied_when_balance_zero
    """
    case, obl = setup_case_with_obligation(case_number="C-SAT", assessed_amount_cents=8000)

    post_payment(case["id"], 8000, "STATUTORY_PRIORITY")

    case_after = validate_success(api.get_case(case["id"], clerk_headers()))
    assert case_after["balance_cents"] == 0
    assert case_after["status"] == "SATISFIED"


def test_payment_exceeding_case_balance_rejected(api):
    """PRD §3.3: "the amount_cents received (which must be greater than zero and must
    not exceed the case's balance_cents at posting time — otherwise
    ERR_AMOUNT_EXCEEDS_BALANCE)."

    Design: Corner/endpoints/payment_exceeds_case_balance_returns_amount_exceeds
    """
    case, obl = setup_case_with_obligation(case_number="C-OVERPAY", assessed_amount_cents=10000)

    resp = api_client.create_payment(
        {"case_id": case["id"], "amount_cents": 20000, "allocation_method": "STATUTORY_PRIORITY"},
        clerk_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_AMOUNT_EXCEEDS_BALANCE.value)
