"""Difficulty Rule 1 — dual_variant_calc.

Same calculation, two PRD-declared variants yielding different observable
outcomes for identical inputs. The two-pool charge waterfall pins
CONCURRENT_DEBIT (pfl_charge = min(fmla_charge, pfl_remaining)) and explicitly
forbids exhausting PFL before FMLA; PRD §2.9 + §3.6.
"""
from test_helpers import (
    record_interval,
    set_clock,
    setup_approved_case,
    validate_success,
)


class TestConcurrentDebitVsPflFirst:
    """PRD §2.9 + §3.6: PFL ticks down alongside FMLA in CA where PFL_QUOTA=320 < 480."""

    def test_ca_employee_400_hour_interval_yields_fmla_400_pfl_320(self, api):
        """PRD §3.6: "First, the FMLA remaining is the larger of zero and 480 minus the case's pre-existing `fmla_hours_charged`, and the interval's FMLA charge is the smaller of `hours_taken` and that FMLA remaining."
        PRD §3.6: "the interval's PFL charge is the smaller of the FMLA charge just computed and that PFL remaining."
        PRD §3.6: "Reversing the evaluation order — exhausting PFL before charging FMLA — would produce a different total FMLA balance and a different protection-flip point in the boundary case where the state's PFL quota is less than 480 and `hours_taken` exceeds the PFL remaining; the system explicitly forbids that ordering."

        Design: Difficulty/dual_variant_calc/concurrent_vs_pfl_first_pool_charge_diverges
        """
        # PRD §3.6: CA PFL quota = 320; FMLA = 480. With 400 raw hours, concurrent debit
        # produces fmla_charge=400, pfl_charge=min(400, 320)=320.
        bundle = setup_approved_case(
            employer_state="CA",
            employee_home_state="CA",
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="CONTINUOUS",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
            cert_expected_duration_weeks=10,
        )
        assert bundle.case["pfl_concurrent"] is True, (
            f"CA + OWN_SERIOUS_HEALTH_CONDITION must be pfl_concurrent; got {bundle.case['pfl_concurrent']!r}"
        )
        set_clock("2026-06-01T00:00:00.000Z")
        interval = record_interval(
            bundle.case["id"],
            "2026-06-01T00:00:00.000Z",
            "2026-08-15T00:00:00.000Z",
            400,
        )
        assert interval["fmla_hours_charged"] == 400, (
            f"FMLA charge must equal min(400, 480) = 400 under CONCURRENT_DEBIT; got {interval['fmla_hours_charged']!r}"
        )
        assert interval["pfl_hours_charged"] == 320, (
            f"PFL charge must equal min(fmla_charge=400, pfl_remaining=320) = 320 under CONCURRENT_DEBIT; "
            f"PFL_FIRST would yield 320 too but fmla_charge would be 80 instead of 400. Got {interval['pfl_hours_charged']!r}"
        )
        # Verify case totals propagated.
        res_case = api.get_case(bundle.case["id"], _hr_headers())
        case_after = validate_success(res_case)
        assert case_after["fmla_hours_charged"] == 400
        assert case_after["pfl_hours_charged"] == 320
        # FMLA cumulative 400 < 480 so still protected.
        assert case_after["job_restoration_protected"] is True

    def test_ca_employee_concurrent_pfl_caps_at_state_quota_320(self, api):
        """PRD §3.6: "when the case's `pfl_concurrent` flag is true, the PFL remaining is the larger of zero and the employee's state-specific PFL quota — 320 for `CA`,...— minus the case's pre-existing `pfl_hours_charged`"

        Design: Difficulty/dual_variant_calc/concurrent_vs_pfl_first_pool_charge_diverges
        """
        # Second interval after exhausting PFL: pfl_charge should be 0 since pfl_remaining=0.
        bundle = setup_approved_case(
            employer_state="CA",
            employee_home_state="CA",
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="CONTINUOUS",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-09-01T00:00:00.000Z",
            cert_expected_duration_weeks=12,
        )
        set_clock("2026-06-01T00:00:00.000Z")
        # First interval exhausts CA PFL quota (320).
        first = record_interval(
            bundle.case["id"],
            "2026-06-01T00:00:00.000Z",
            "2026-07-15T00:00:00.000Z",
            320,
        )
        assert first["pfl_hours_charged"] == 320
        # Second interval — PFL is exhausted; pfl_charge must be 0.
        second = record_interval(
            bundle.case["id"],
            "2026-07-15T00:00:00.000Z",
            "2026-07-22T00:00:00.000Z",
            40,
        )
        assert second["fmla_hours_charged"] == 40
        assert second["pfl_hours_charged"] == 0, (
            f"PFL exhausted after first interval; second interval must charge 0 PFL; got {second['pfl_hours_charged']!r}"
        )


def _hr_headers() -> dict:
    """Local helper to avoid re-importing in each method body."""
    from test_helpers import TEST_USERS

    return TEST_USERS["hr_admin_headers"]
