"""Payroll cost allocation: per-line-then-remainder rounding, reversal draining."""
from test_helpers import (
    get_success_data,
    setup_allocated_payroll_run, setup_posted_payroll_run, allocation_sum,
    api_client, TEST_USERS,
)

CFO = TEST_USERS["cfo_headers"]
BK = TEST_USERS["bookkeeper_headers"]


def _alloc_map(api, run_id):
    body = api.list_payroll_allocations(run_id, CFO, params={"limit": 100, "offset": 0}).json()
    return {a["id"]: a for a in body["data"]}


class TestPayrollAllocationRounding:
    def test_three_equal_departments_remainder_to_first_created(self, api):
        """PRD §3.6: "For each line, a raw share is computed as
        `total_employer_cost_cents` multiplied by that line's `dept_gross_cents`,
        divided by the sum of gross, rounded half up to whole cents."
        PRD §3.6: "These rounded shares are summed, and the leftover remainder —
        the run's `total_employer_cost_cents` minus the sum of the rounded shares —
        is added in full to a single recipient line: the line with the largest
        `dept_gross_cents`, breaking a tie in favor of the earliest `created_at`."

        Design: Difficulty/combinatorial_formula/payroll_allocation_round_per_line_then_remainder
        """
        cid, close_id, run_id, alloc_ids = setup_allocated_payroll_run(
            total_employer_cost_cents=1000000,
            dept_gross_list=(("A", 500000), ("B", 500000), ("C", 500000)),
            period_month=3)
        aA, aB, aC = alloc_ids
        allocs = _alloc_map(api, run_id)
        assert allocs[aA]["allocated_cents"] == 333334
        assert allocs[aB]["allocated_cents"] == 333333
        assert allocs[aC]["allocated_cents"] == 333333

    def test_allocation_sum_equals_total_exactly(self, api):
        """PRD §3.6: "Because the remainder is reconciled onto exactly one line
        rather than left to drift, the sum of every line's `allocated_cents` equals
        the run's `total_employer_cost_cents` exactly."

        Design: Difficulty/combinatorial_formula/payroll_allocation_round_per_line_then_remainder
        """
        cid, close_id, run_id, alloc_ids = setup_allocated_payroll_run(
            total_employer_cost_cents=1000000,
            dept_gross_list=(("A", 500000), ("B", 500000), ("C", 500000)),
            period_month=4)
        assert allocation_sum(run_id) == 1000000


class TestPayrollReverseCascade:
    def test_reverse_zeroes_every_allocation(self, api):
        """PRD §3.6: "As compensation, reversing the run sets every one of its
        `PayrollAllocation` lines' `allocated_cents` back to zero, draining the
        run's allocation."
        PRD §3.6: "Reversing the run is a `CFO` action permitted only from
        `POSTED`, moving it `POSTED → REVERSED`"

        Design: Difficulty/transitive_cascade/payroll_reverse_zeroes_allocations
        """
        cid, close_id, run_id, alloc_ids = setup_posted_payroll_run(
            total_employer_cost_cents=1000000,
            dept_gross_list=(("A", 500000), ("B", 500000), ("C", 500000)),
            period_month=5)
        run = get_success_data(api.reverse_payroll_run(run_id, CFO))
        assert run["status"] == "REVERSED"
        allocs = _alloc_map(api, run_id)
        for aid in alloc_ids:
            assert allocs[aid]["allocated_cents"] == 0

    def test_reverse_run_reaches_reversed_status(self, api):
        """PRD §3.6: "Reversing the run is a `CFO` action permitted only from
        `POSTED`, moving it `POSTED → REVERSED`"

        Design: Difficulty/transitive_cascade/payroll_reverse_zeroes_allocations
        """
        cid, close_id, run_id, alloc_ids = setup_posted_payroll_run(period_month=6)
        run = get_success_data(api.reverse_payroll_run(run_id, CFO))
        assert run["status"] == "REVERSED"


class TestPayrollSumConservedThenDrained:
    def test_sum_conserved_after_allocate_then_drained_after_reverse(self, api):
        """PRD §3.6: "Because the remainder is reconciled onto exactly one line
        rather than left to drift, the sum of every line's `allocated_cents` equals
        the run's `total_employer_cost_cents` exactly."
        PRD §3.6: "As compensation, reversing the run sets every one of its
        `PayrollAllocation` lines' `allocated_cents` back to zero, draining the
        run's allocation."

        Design: Difficulty/compensating_invariant/payroll_allocation_sum_conserved_then_drained
        """
        cid, close_id, run_id, alloc_ids = setup_posted_payroll_run(
            total_employer_cost_cents=1000000,
            dept_gross_list=(("A", 500000), ("B", 500000), ("C", 500000)),
            period_month=8)
        assert allocation_sum(run_id) == 1000000
        run = get_success_data(api.reverse_payroll_run(run_id, CFO))
        assert run["status"] == "REVERSED"
        assert allocation_sum(run_id) == 0

    def test_allocated_sum_equals_total_before_reverse(self, api):
        """PRD §3.6: "the sum of every line's `allocated_cents` equals the run's
        `total_employer_cost_cents` exactly."

        Design: Difficulty/compensating_invariant/payroll_allocation_sum_conserved_then_drained
        """
        cid, close_id, run_id, alloc_ids = setup_posted_payroll_run(
            total_employer_cost_cents=1000000, period_month=9)
        assert allocation_sum(run_id) == 1000000
