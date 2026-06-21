"""Difficulty Rule 9 — compensating_invariant.

A compensating action restores the conserved quantity to its pre-forward-action
value: reversing an interval restores LeaveCase.fmla_hours_charged and
flips job_restoration_protected back; partial payments leave
employee_owes == employee_share - payments_received with zero drift.
"""
from test_helpers import (
    apply_payment,
    assert_owes_invariant,
    get_case,
    list_benefit_ledgers_for_case,
    record_interval,
    reverse_interval,
    seed_historic_interval,
    set_clock,
    setup_active_case_with_first_interval,
    setup_approved_case,
)


class TestIntervalReverseRestoresFmlaPool:
    """PRD §3.6: reversing an interval subtracts its charges from the case totals;
    if cumulative fmla_hours_charged drops below 480, job_restoration_protected
    flips back to true (the conserved-quantity invariant).
    """

    def test_reverse_interval_restores_quota_and_flips_protection_back(self, api):
        """PRD §3.6: "Reversing an interval — a compensating action HR may take within fourteen days of the interval's record date while the case remains `ACTIVE` — transitions the interval's `status` from `RECORDED` to `REVERSED`, subtracts the interval's `fmla_hours_charged` and `pfl_hours_charged` from the case totals, and, if the new cumulative `fmla_hours_charged` is below 480, flips `job_restoration_protected` back to true (the compensating invariant: the case's total FMLA charged equals the sum of `RECORDED` intervals' FMLA charges)."

        Design: Difficulty/compensating_invariant/interval_reverse_restores_fmla_pool
        """
        bundle = setup_approved_case(
            employer_state="FED",
            fmla_method="CALENDAR_YEAR",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
            cert_expected_duration_weeks=10,
        )
        seed_historic_interval(
            bundle.case["id"],
            "2026-02-01T00:00:00.000Z",
            "2026-04-30T00:00:00.000Z",
            479,
            479,
            0,
        )
        set_clock("2026-06-01T00:00:00.000Z")
        interval = record_interval(
            bundle.case["id"],
            "2026-06-01T00:00:00.000Z",
            "2026-06-01T01:00:00.000Z",
            1,
        )
        # Forward action: cumulative now 480; protection flipped to false.
        case_mid = get_case(bundle.case["id"])
        assert case_mid["fmla_hours_charged"] == 480
        assert case_mid["job_restoration_protected"] is False
        # Compensating action: reverse the new interval.
        reverse_interval(interval["id"])
        case_after = get_case(bundle.case["id"])
        # Invariant: case fmla_hours_charged == sum of RECORDED intervals' charges
        # = 479 (the seeded historic interval; the new interval is REVERSED).
        assert case_after["fmla_hours_charged"] == 479, (
            f"after reverse, cumulative must equal sum of RECORDED interval charges = 479; "
            f"got {case_after['fmla_hours_charged']!r}"
        )
        assert case_after["job_restoration_protected"] is True, (
            f"once cumulative drops below 480, protection flips back to true; "
            f"got {case_after['job_restoration_protected']!r}"
        )

    def test_reverse_interval_marks_interval_reversed_status(self, api):
        """PRD §3.6: "Reversing an interval — a compensating action HR may take within fourteen days of the interval's record date while the case remains `ACTIVE` — transitions the interval's `status` from `RECORDED` to `REVERSED`"

        Design: Difficulty/compensating_invariant/interval_reverse_restores_fmla_pool
        """
        bundle = setup_active_case_with_first_interval(
            employer_state="FED",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
            interval_start="2026-06-01T00:00:00.000Z",
            interval_end="2026-06-08T00:00:00.000Z",
            interval_hours=40,
            cert_expected_duration_weeks=10,
        )
        reversed_interval = reverse_interval(bundle["interval"]["id"])
        assert reversed_interval["status"] == "REVERSED", (
            f"reversed interval must have status REVERSED; got {reversed_interval['status']!r}"
        )


class TestPaymentApplicationConservesOwesEquation:
    """PRD §3.7: employee_owes_cents == employee_premium_share_cents -
    payments_received_cents. Two partial payments summing to the share leave
    employee_owes_cents == 0 with zero drift.
    """

    def test_two_partial_payments_summing_to_share_yield_paid_terminal(self, api):
        """PRD §3.7: "The row's `employee_owes_cents` is `employee_premium_share_cents` minus `payments_received_cents`."
        PRD §3.7: "when the applied amount equals the outstanding balance exactly, the row moves to `PAID` and `employee_owes_cents` is set to zero."

        Design: Difficulty/compensating_invariant/payment_application_conserves_owes_equation
        """
        # Set up a full month leave so leave_fraction = 1.0 — clean numbers.
        # monthly=10000, share=0.5 → employee_share = 5000.
        bundle = setup_active_case_with_first_interval(
            employer_state="FED",
            monthly_premium_total_cents=10000,
            employer_premium_share_pct=0.50,
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
            interval_start="2026-06-01T00:00:00.000Z",
            interval_end="2026-07-01T00:00:00.000Z",
            interval_hours=160,
        )
        ledgers = list_benefit_ledgers_for_case(bundle["case"]["id"])
        assert len(ledgers) == 1
        row = ledgers[0]
        assert row["employee_premium_share_cents"] == 5000, (
            f"full-month leave_fraction=1; employee_share = round(10000*0.5*1) = 5000; "
            f"got {row['employee_premium_share_cents']!r}"
        )
        ledger_id = row["id"]
        # First partial payment: 2000.
        after1 = apply_payment(ledger_id, 2000)
        assert after1["payments_received_cents"] == 2000
        assert after1["employee_owes_cents"] == 3000
        assert after1["payment_status"] == "PARTIAL"
        assert_owes_invariant(after1)
        # Second partial payment exactly closes the balance: 3000.
        after2 = apply_payment(ledger_id, 3000)
        assert after2["payments_received_cents"] == 5000
        assert after2["employee_owes_cents"] == 0
        assert after2["payment_status"] == "PAID", (
            f"paying remaining balance exactly must transition to PAID; got {after2['payment_status']!r}"
        )
        assert_owes_invariant(after2)

    def test_single_full_balance_payment_transitions_pending_to_paid(self, api):
        """PRD §3.7: "when the applied amount equals the outstanding balance exactly, the row moves to `PAID` and `employee_owes_cents` is set to zero."

        Design: Difficulty/compensating_invariant/payment_application_conserves_owes_equation
        """
        bundle = setup_active_case_with_first_interval(
            employer_state="FED",
            monthly_premium_total_cents=10000,
            employer_premium_share_pct=0.50,
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
            interval_start="2026-06-01T00:00:00.000Z",
            interval_end="2026-07-01T00:00:00.000Z",
            interval_hours=160,
        )
        ledgers = list_benefit_ledgers_for_case(bundle["case"]["id"])
        row = ledgers[0]
        after = apply_payment(row["id"], 5000)
        assert after["payment_status"] == "PAID"
        assert after["employee_owes_cents"] == 0
        assert_owes_invariant(after)
