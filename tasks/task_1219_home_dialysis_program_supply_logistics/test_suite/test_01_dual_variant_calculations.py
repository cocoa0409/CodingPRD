"""Dual-variant calculation pairs: supply allowance STANDARD vs ACTUALIZED,
and adherence STREAK vs ROLLING_28."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_program, create_active_home_patient, create_approved_order,
    schedule_appointment, complete_appointment, create_log, mark_reviewed,
    list_reviews, sign_off_review, set_clock, get_patient, create_draft_order,
    api_client, make_admin_headers, make_patient_headers,
    make_coordinator_headers, create_supply_order_payload,
)


class TestSupplyAllowanceStandardVsActualized:
    """The forward-looking STANDARD variant stored at submit diverges from the
    ACTUALIZED replay at close; the delta carries into the next month."""

    def test_close_computes_actualized_and_adjustment(self, api):
        """PRD §3.5: "At close the system replays the month: `actualized_units`
        is the sum of `consumption_units` over the patient's TreatmentLog rows
        dated inside the order month, first and last day inclusive, across every
        log status — `SUBMITTED`, `REVIEWED`, and `FLAGGED` alike; and
        `adjustment_units` is `actualized_units` minus the stored
        `standard_allowance_units`, which may be negative."

        Design: Difficulty/dual_variant_calc/supply_allowance_standard_vs_actualized_diverge
        """
        ctx = create_active_home_patient(
            catalog=[{"sku": "DIALYSATE_2L", "name": "Dialysate 2L bag",
                      "unit_price_cents": 1200, "handling_rate_cents": 10.5,
                      "unit_credit_cents": 300},
                     {"sku": "TUBING_SET", "name": "Tubing set",
                      "unit_price_cents": 3400, "handling_rate_cents": 25,
                      "unit_credit_cents": 800}])
        pat = ctx["patient"]["id"]
        mach = ctx["machine"]["id"]
        # May order of 40 units, APPROVED then fully DELIVERED.
        order = create_approved_order(pat, "2026-05",
                                      [{"sku": "DIALYSATE_2L", "quantity": 40}])
        appt = schedule_appointment(order["id"], "2026-05-04T08:00:00Z",
                                    "2026-05-04T12:00:00Z")
        set_clock("2026-05-04T09:00:00Z")
        complete_appointment(appt["id"], 40)
        # 5 logs of 6 units each, all marked REVIEWED, cadence review signed off.
        set_clock("2026-05-09T12:00:00Z")
        logs = [create_log(pat, mach, f"2026-05-0{d}",
                           consumption=[{"sku": "DIALYSATE_2L", "units": 6}])
                for d in range(5, 10)]
        for log in logs:
            mark_reviewed(log["id"])
        reviews = list_reviews(pat)
        assert reviews, "a CADENCE review must exist (cadence 2)"
        sign_off_review(reviews[0]["id"], "CONTINUE")
        # Close on the first day of the following month.
        set_clock("2026-06-01T00:00:00Z")
        resp = api.close_supply_order(order["id"], make_coordinator_headers("coord-1"))
        closed = validate_success(resp)
        assert closed["standard_allowance_units"] == 72, (
            "STANDARD variant: 3 treatments/week * 4 weeks * 6 units = 72")
        assert closed["actualized_units"] == 30, (
            "ACTUALIZED variant: 5 logs * 6 units = 30")
        assert closed["adjustment_units"] == -42
        assert closed["order_status"] == "CLOSED"

    def test_negative_carry_reduces_next_month_allowance(self, api):
        """PRD §3.5: "That delta is exactly what the next month's
        `carried_adjustment_units` picks up, so a patient who under-consumed
        finds next month's allowance room reduced, and one who over-consumed
        finds it enlarged."
        PRD §3.5: "Only if storage passes does the allowance bound apply: if
        `provisional_total_units` exceeds `standard_allowance_units` plus
        `carried_adjustment_units`, the rejection is `ERR_ALLOWANCE_EXCEEDED`."

        Design: Difficulty/dual_variant_calc/supply_allowance_standard_vs_actualized_diverge
        """
        ctx = create_active_home_patient(
            catalog=[{"sku": "DIALYSATE_2L", "name": "Dialysate 2L bag",
                      "unit_price_cents": 1200, "handling_rate_cents": 10.5,
                      "unit_credit_cents": 300}])
        pat = ctx["patient"]["id"]
        mach = ctx["machine"]["id"]
        order = create_approved_order(pat, "2026-05",
                                      [{"sku": "DIALYSATE_2L", "quantity": 40}])
        appt = schedule_appointment(order["id"], "2026-05-04T08:00:00Z",
                                    "2026-05-04T12:00:00Z")
        set_clock("2026-05-04T09:00:00Z")
        complete_appointment(appt["id"], 40)
        set_clock("2026-05-09T12:00:00Z")
        logs = [create_log(pat, mach, f"2026-05-0{d}",
                           consumption=[{"sku": "DIALYSATE_2L", "units": 6}])
                for d in range(5, 10)]
        for log in logs:
            mark_reviewed(log["id"])
        sign_off_review(list_reviews(pat)[0]["id"], "CONTINUE")
        set_clock("2026-06-01T00:00:00Z")
        validate_success(api.close_supply_order(order["id"],
                                                make_coordinator_headers("coord-1")))
        # June order: allowance_room = 72 + (-42) = 30.
        june = create_draft_order(pat, "2026-06",
                                  [{"sku": "DIALYSATE_2L", "quantity": 31}])
        resp = api.submit_supply_order(june["id"], make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_ALLOWANCE_EXCEEDED)
        # Patch down to exactly 30: fits the carried allowance.
        resp = api.patch_supply_order(june["id"],
                                      {"lines": [{"sku": "DIALYSATE_2L",
                                                  "quantity": 30}]},
                                      make_patient_headers(pat))
        validate_success(resp)
        submitted = validate_success(api.submit_supply_order(
            june["id"], make_patient_headers(pat)))
        assert submitted["order_status"] == "SUBMITTED"
        assert submitted["standard_allowance_units"] == 72
        assert submitted["carried_adjustment_units"] == -42


class TestAdherenceStreakVsRollingDiverge:
    """Identical log data yields rolling 41.7 at sign-off while the streak
    variant later escalates the same patient to AT_RISK."""

    def test_rolling_pct_computed_at_sign_off(self, api):
        """PRD §3.6: "The rolling adherence looks back over the trailing 28
        calendar days ending at the clock date: the scheduled count is
        `prescription_treatments_per_week` times four, the actual count is the
        number of the patient's logs of any status with `treatment_date` inside
        the window, and the percentage is the smaller of actual and scheduled
        divided by scheduled, times one hundred, rounded half up to one decimal
        place — so a patient who logged five times early in the window and then
        fell silent reports 41.7 against a thrice-weekly prescription, even as
        the streak monitor escalates."

        Design: Difficulty/dual_variant_calc/adherence_streak_vs_rolling_diverge
        """
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        mach = ctx["machine"]["id"]
        set_clock("2026-05-06T12:00:00Z")
        logs = [create_log(pat, mach, f"2026-05-0{d}") for d in range(2, 7)]
        for log in logs:
            mark_reviewed(log["id"])
        reviews = list_reviews(pat)
        assert reviews, "cadence review must exist"
        signed = sign_off_review(reviews[0]["id"], "CONTINUE")
        assert signed["adherence_rolling_pct"] == pytest.approx(41.7, abs=0.05), (
            "5 logs / 12 scheduled = 41.7 at one decimal place")

    def test_streak_escalates_posture_after_silence(self, api):
        """PRD §3.6: "the streak is that silence divided by the expected
        interval, rounded down. A streak greater than or equal to the program's
        `max_missed_log_streak` contributes `AT_RISK` at rung 5 of the posture
        ladder — a patient who logged today has streak 0 even after a bad month."

        Design: Difficulty/dual_variant_calc/adherence_streak_vs_rolling_diverge
        """
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        mach = ctx["machine"]["id"]
        set_clock("2026-05-06T12:00:00Z")
        logs = [create_log(pat, mach, f"2026-05-0{d}") for d in range(2, 7)]
        for log in logs:
            mark_reviewed(log["id"])
        sign_off_review(list_reviews(pat)[0]["id"], "CONTINUE")
        # 7 days of silence after the latest log (2026-05-06); interval 2 days.
        set_clock("2026-05-13T00:00:00Z")
        patient = get_patient(pat)
        assert patient["missed_log_streak"] == 3, (
            "floor(7 days silence / 2 day expected interval) = 3")
        assert patient["posture"] == "AT_RISK", (
            "streak >= max_missed_log_streak escalates to AT_RISK")
