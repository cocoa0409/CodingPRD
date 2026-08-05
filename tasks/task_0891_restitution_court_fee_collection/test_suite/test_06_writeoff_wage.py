"""Obligation aging & write-off boundaries, and wage-assignment capacity limits."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    clerk_headers, supervisor_headers, finance_headers,
    set_clock, make_case, make_obligation, make_wage_assignment, post_payment,
    setup_case_with_obligation,
    api_client,
)


class TestWriteOffAgeBoundary:
    def test_writeoff_at_exactly_1825_days_permitted(self, api):
        """PRD §3.7: "Write-off requires that this age be at least 1,825 days — five
        years — otherwise the request is rejected with ERR_WRITEOFF_TOO_EARLY ... A
        written-off obligation moves to WRITTEN_OFF (from either OUTSTANDING or
        PARTIALLY_PAID); the case's total_written_off_cents increases by the balance
        removed, that obligation drops out of the case balance_cents."

        Design: Difficulty/boundary_precision_check/writeoff_age_exactly_1825_days
        """
        case = make_case(case_number="C-BND-WOFF")
        obl = make_obligation(case["id"], "FINE", 20000)  # created at default clock 2026-05-01
        set_clock("2031-04-30T00:00:00Z")  # exactly 1825 days later

        written = validate_success(api.write_off_obligation(obl["id"], supervisor_headers()))
        assert written["status"] == "WRITTEN_OFF"
        assert written["balance_cents"] == 0

    def test_writeoff_at_1824_days_rejected_too_early(self, api):
        """PRD §3.7: "Write-off requires that this age be at least 1,825 days — five
        years — otherwise the request is rejected with ERR_WRITEOFF_TOO_EARLY."

        Design: Difficulty/boundary_precision_check/writeoff_age_exactly_1825_days
        """
        case = make_case(case_number="C-BND-WOFF24")
        obl = make_obligation(case["id"], "FINE", 20000)
        set_clock("2031-04-29T00:00:00Z")  # 1824 days later

        resp = api.write_off_obligation(obl["id"], supervisor_headers())
        validate_error(resp, ApiErrorId.ERR_WRITEOFF_TOO_EARLY.value, expected_status=409)


class TestWageWithholdCapacity:
    def test_overlapping_orders_exceeding_cap_rejected(self, api):
        """PRD §3.8: "the system finds the ACTIVE wage assignments of the same case whose
        closed effective interval intersects the new interval ... If the new order's
        monthly_withhold_cents plus the sum of monthly_withhold_cents across that
        overlapping set would exceed 50,000 cents (500 dollars) per month, the order is
        rejected with ERR_WITHHOLD_CAPACITY_EXCEEDED."

        Design: Difficulty/resource_temporal_overlap/wage_aggregate_withhold_capacity_exceeded
        """
        case = make_case(case_number="C-WAGE-CAP")
        make_wage_assignment(
            case["id"], employer_name="Acme Co", monthly_withhold_cents=40000,
            effective_start_date="2026-06-01T00:00:00Z", effective_end_date="2026-12-31T00:00:00Z",
        )

        resp = api.create_wage_assignment(
            {"case_id": case["id"], "employer_name": "Beta LLC", "monthly_withhold_cents": 20000,
             "effective_start_date": "2026-08-01T00:00:00Z", "effective_end_date": "2026-09-30T00:00:00Z"},
            finance_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_WITHHOLD_CAPACITY_EXCEEDED.value, expected_status=409)

    def test_disjoint_orders_over_cap_allowed(self, api):
        """PRD §3.8: "the system finds the ACTIVE wage assignments of the same case whose
        closed effective interval intersects the new interval — two closed intervals
        intersect when they share at least one instant, so touching endpoints count as
        overlap."

        Design: Difficulty/resource_temporal_overlap/wage_aggregate_withhold_capacity_exceeded
        """
        case = make_case(case_number="C-WAGE-OK")
        make_wage_assignment(
            case["id"], employer_name="Acme Co", monthly_withhold_cents=40000,
            effective_start_date="2026-06-01T00:00:00Z", effective_end_date="2026-06-30T00:00:00Z",
        )

        resp = api.create_wage_assignment(
            {"case_id": case["id"], "employer_name": "Beta LLC", "monthly_withhold_cents": 40000,
             "effective_start_date": "2026-08-01T00:00:00Z", "effective_end_date": "2026-08-31T00:00:00Z"},
            finance_headers(),
        )
        created = validate_success(resp, expected_status=201)
        assert created["status"] == "ACTIVE", "disjoint intervals do not aggregate toward the cap"


def test_writeoff_before_age_rejected(api):
    """PRD §3.7: "Write-off requires that this age be at least 1,825 days — five years —
    otherwise the request is rejected with ERR_WRITEOFF_TOO_EARLY."

    Design: Corner/state_machines/writeoff_before_age_returns_writeoff_too_early
    """
    case, obl = setup_case_with_obligation(case_number="C-EARLYWOFF", assessed_amount_cents=3000,
                                           obligation_type="FINE")
    resp = api.write_off_obligation(obl["id"], supervisor_headers())
    validate_error(resp, ApiErrorId.ERR_WRITEOFF_TOO_EARLY.value, expected_status=409)


def test_writeoff_aged_zero_balance_rejected(api):
    """PRD §3.7: "it also requires that the obligation still have something owed, a
    balance_cents greater than zero, otherwise ERR_NOTHING_TO_WRITE_OFF."

    Design: Corner/state_machines/writeoff_aged_zero_balance_returns_nothing_to_write_off
    """
    case = make_case(case_number="C-WOFFZERO")
    obl = make_obligation(case["id"], "FINE", 3000)
    post_payment(case["id"], 3000, "STATUTORY_PRIORITY")  # obligation fully paid, balance 0
    set_clock("2031-06-01T00:00:00Z")  # well past the write-off age

    resp = api.write_off_obligation(obl["id"], supervisor_headers())
    validate_error(resp, ApiErrorId.ERR_NOTHING_TO_WRITE_OFF.value, expected_status=409)


def test_terminate_already_terminated_wage_rejected(api):
    """PRD §3.8: "termination is permitted only while the assignment is ACTIVE
    (otherwise ERR_INVALID_STATE), moves it to TERMINATED."

    Design: Corner/state_machines/terminate_already_terminated_wage_returns_invalid_state
    """
    case = make_case(case_number="C-WGTERM")
    wa = make_wage_assignment(
        case["id"], employer_name="Gamma Inc", monthly_withhold_cents=10000,
        effective_start_date="2026-06-01T00:00:00Z", effective_end_date="2026-12-31T00:00:00Z",
    )
    validate_success(api.terminate_wage_assignment(wa["id"], finance_headers()))

    resp = api.terminate_wage_assignment(wa["id"], finance_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_wage_end_before_start_rejected(api):
    """PRD §3.8: "The effective_end_date must be on or after the effective_start_date,
    or the request is rejected with ERR_INVALID_DATE_RANGE."

    Design: Corner/errors/wage_end_before_start_returns_invalid_date_range
    """
    case = make_case(case_number="C-WGDATE")
    resp = api.create_wage_assignment(
        {"case_id": case["id"], "employer_name": "Delta Co", "monthly_withhold_cents": 10000,
         "effective_start_date": "2026-09-01T00:00:00Z", "effective_end_date": "2026-06-01T00:00:00Z"},
        finance_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value, expected_status=422)
