"""Subcontractor reliability: the forward-looking vs backward-looking dual-variant score."""
from test_helpers import setup_reliability_projected_vs_realized


def test_reliability_projected_counts_non_failed_gates(api):
    """PRD §3.5: "The forward-looking reliability_projected looks across the sub's bookings whose
    status is SCHEDULED or COMPLETED: let the denominator be the count of those bookings and the
    numerator be the count of them whose referenced phase gate is not FAILED. If the denominator is
    zero the score defaults to 100; otherwise it is 100 multiplied by the numerator divided by the
    denominator, rounded half-up."

    Design: Difficulty/dual_variant_calc/subcontractor_projected_vs_realized_reliability
    """
    # Two COMPLETED bookings; both referenced gates are now PASSED (neither FAILED).
    sub = setup_reliability_projected_vs_realized()
    assert sub["reliability_projected"] == 100


def test_reliability_realized_requires_first_attempt_pass(api):
    """PRD §3.5: "The backward-looking reliability_realized looks only across the sub's COMPLETED
    bookings: let the denominator be the count of COMPLETED bookings and the numerator be the count
    of them whose referenced phase gate is PASSED and whose inspection_attempts equals exactly 1
    (that is, the gate passed on its first inspection with no rework)."
    PRD §3.5: "The two scores diverge whenever a gate passed only after rework, or is still open,
    because such a gate counts as good for the projected score but not for the realized one."

    Design: Difficulty/dual_variant_calc/subcontractor_projected_vs_realized_reliability
    """
    # One gate passed on attempt 1, the other only after rework (attempt 2): realized = 1/2 = 50.
    sub = setup_reliability_projected_vs_realized()
    assert sub["reliability_realized"] == 50
    assert sub["reliability_projected"] != sub["reliability_realized"]
