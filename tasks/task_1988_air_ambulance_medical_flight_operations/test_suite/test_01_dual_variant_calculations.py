"""Dual-variant calculations: billing provisional vs final totals, clinical
triage vs acceptance scoring, and the two crew-duty ledgers."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_invoice,
    close_shift,
    create_crew_member,
    create_crew_shift,
    create_base,
    create_mission_request,
    create_patient,
    create_ground_leg,
    create_invoice,
    get_success_data,
    make_flight_crew_headers,
    api_client,
    set_clock,
    setup_base_with_crew,
    setup_completed_mission_with_completed_destination_leg,
    setup_planning_mission,
    triage_request,
    accept_request,
    advance_mission_through,
    post_go_weather,
    TEST_USERS,
)

OPS = TEST_USERS["ops_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
MED = TEST_USERS["medical_director_headers"]
BILL = TEST_USERS["billing_specialist_headers"]


class TestInvoiceProvisionalVsFinalTotals:
    def test_provisional_total_uses_padded_miles_and_pre_completion_legs(self):
        """PRD §3.8: "The provisional quote, computed at creation while actuals
        are unknown, takes the mission's `estimated_loaded_miles`, multiplies it
        by a 1.15 pad factor, and rounds up to the next whole mile; it counts
        every ground leg in `SCHEDULED`, `ENROUTE`, `AT_BEDSIDE`, or
        `COMPLETED`."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_totals
        """
        ctx = setup_planning_mission(estimated_loaded_miles=100, planned_duration_min=180)
        pilot = ctx["roster"]["PILOT"]
        leg = create_ground_leg(ctx["mission"]["id"], leg_type="DESTINATION",
                                scheduled_pickup_iso="2026-08-01T09:00:00Z",
                                estimated_ground_miles=12)
        invoice = create_invoice(ctx["mission"]["id"])
        # est 100 -> ceil(100*1.15)=115 miles; 115*16000=1,840,000 mileage;
        # fuel round(1,840,000*0.07)=128,800; subtotal 1,800,000+1,840,000+128,800+120,000
        # = 3,888,800 >= 2,500,000 -> logistics round(3,888,800*0.04)=155,552;
        # ground 45,000; total 4,089,352.
        assert invoice["provisional_total_cents"] == 4089352, (
            f"Expected provisional 4089352, got {invoice['provisional_total_cents']}"
        )

    def test_final_total_uses_actual_miles_and_completed_legs_only(self):
        """PRD §3.8: "The final settlement, computed at finalize, takes
        `actual_loaded_miles` exactly as entered from the flight log — no pad
        factor, and fractional miles are allowed — and counts only `COMPLETED`
        ground legs."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_totals
        """
        ctx, leg = setup_completed_mission_with_completed_destination_leg(
            estimated_loaded_miles=100, planned_duration_min=180
        )
        invoice = create_invoice(ctx["mission"]["id"])
        invoice = get_success_data(
            api_client.finalize_invoice(invoice["id"], {"actual_loaded_miles": 92}, BILL)
        )
        assert_invoice(invoice)
        # final: 92*16000=1,472,000; fuel round(1,472,000*0.07)=103,040;
        # subtotal 1,800,000+1,472,000+103,040+120,000=3,495,040 >= 2,500,000
        # -> logistics round(3,495,040*0.04)=139,802; ground 45,000; total 3,679,842.
        assert invoice["final_total_cents"] == 3679842, (
            f"Expected final 3679842, got {invoice['final_total_cents']}"
        )
        assert invoice["provisional_total_cents"] == 4089352
        assert invoice["provisional_total_cents"] != invoice["final_total_cents"]
        assert invoice["claim_status"] == "FINALIZED"


class TestAcuityTriageVsAcceptanceDivergence:
    def test_triage_score_uses_intake_weights_without_bonus(self):
        """PRD §3.2: "Intake computes the request's `triage_acuity_score`: a
        weighted sum that weights the cardio subscale at 0.30, respiratory at
        0.30, neuro at 0.20, and interventions at 0.20, rounded half-up to two
        decimal places."

        Design: Difficulty/dual_variant_calc/acuity_triage_vs_acceptance_score_divergence
        """
        set_clock("2026-08-01T00:00:00Z")
        patient = create_patient(full_name="Amy Acute", date_of_birth="1975-11-02", weight_kg=65)
        request = create_mission_request(
            patient["id"],
            subscales={"cardio": 8, "resp": 6, "neuro": 5, "interv": 3},
            onset_iso="2026-07-31T23:00:00Z",
            transport_class="EMERGENCY_SCENE",
            origin_facility="Mile 42 I-10",
        )
        # 8*.30 + 6*.30 + 5*.20 + 3*.20 = 2.4+1.8+1.0+0.6 = 5.80; no bonus at intake.
        assert request["triage_acuity_score"] == pytest.approx(5.8, abs=1e-9), (
            f"Expected triage score 5.8, got {request['triage_acuity_score']}"
        )
        assert request["status"] == "RECEIVED"

    def test_acceptance_score_uses_acceptance_weights_plus_deterioration_bonus(self):
        """PRD §3.2: "Triage computes the `acceptance_acuity_score`: the same
        four-subscale structure but with acceptance weights — cardio 0.25,
        respiratory 0.35, neuro 0.25, interventions 0.15 — applied to the
        verified values, the weighted sum rounded half-up to two decimal places,
        and then, when the interval between the recorded `onset_iso` and the
        scoring instant is strictly less than 120 minutes (two hours), a
        deterioration bonus of 2.0 points added on top of the rounded figure."
        PRD §3.2: "a score of at least 7.0 is `CCT`, at least 4.0 but below 7.0
        is `ALS`, and anything below 4.0 is `BLS`, with both breaks inclusive."

        Design: Difficulty/dual_variant_calc/acuity_triage_vs_acceptance_score_divergence
        """
        set_clock("2026-08-01T00:00:00Z")
        patient = create_patient(full_name="Amy Acute", date_of_birth="1975-11-02", weight_kg=65)
        request = create_mission_request(
            patient["id"],
            subscales={"cardio": 8, "resp": 6, "neuro": 5, "interv": 3},
            onset_iso="2026-07-31T23:00:00Z",
            transport_class="EMERGENCY_SCENE",
            origin_facility="Mile 42 I-10",
        )
        request = triage_request(
            request["id"], subscales={"cardio": 8, "resp": 6, "neuro": 5, "interv": 3}
        )
        # 8*.25+6*.35+5*.25+3*.15 = 2.0+2.1+1.25+0.45 = 5.80; onset 60 min < 120 -> +2.0 = 7.80.
        assert request["acceptance_acuity_score"] == pytest.approx(7.8, abs=1e-9), (
            f"Expected acceptance 7.8, got {request['acceptance_acuity_score']}"
        )
        # The variant choice flips the tier: triage-alone 5.8 would map to ALS.
        assert request["acuity_tier"] == "CCT"
        assert request["triage_acuity_score"] == pytest.approx(5.8, abs=1e-9)


class TestDutyWindowRollingVsCalendarDay:
    def test_rolling_window_rejects_shift_that_calendar_day_view_undercounts(self):
        """PRD §2.9: "A shift crossing midnight splits its minutes across two
        dates, so the same history yields different numbers on the two ledgers:
        a 20:00–08:00 shift counts 240 minutes against the first date and 480
        against the second on the calendar view, but 720 contiguous minutes on
        the rolling window."
        PRD §3.1: "Consider the rolling window running from 24 hours before the
        candidate's planned end through that planned end. Sum the minutes of all
        of the member's shifts, `OPEN` or `CLOSED`, that intersect the window —
        shifts are processed in ascending planned-start order, ties broken by
        ascending creation order — and add the candidate's own
        `planned_minutes`. A projection of 840 minutes (fourteen hours) or less
        passes; 841 or more is rejected with `ERR_DUTY_LIMIT_EXCEEDED`."

        Design: Difficulty/dual_variant_calc/duty_window_rolling_vs_calendar_day
        """
        set_clock("2026-08-01T20:00:00Z")
        base = create_base(name="Base Beta", region="NW-US")
        pilot = create_crew_member(base["id"], "Chris Cross", "PILOT")
        shift1 = create_crew_shift(
            pilot["id"], "2026-08-01T20:00:00Z", "2026-08-02T08:00:00Z"
        )
        set_clock("2026-08-02T08:00:00Z")
        close_shift(shift1["id"])
        set_clock("2026-08-02T10:00:00Z")
        resp = api_client.create_crew_shift(
            {
                "crew_member_id": pilot["id"],
                "planned_start_iso": "2026-08-02T10:30:00Z",
                "planned_end_iso": "2026-08-02T14:30:00Z",
            },
            OPS,
        )
        # Rolling window [2026-08-01T14:30, 2026-08-02T14:30]: all 720 minutes of
        # shift1 + 240 candidate = 960 > 840.
        from test_helpers import validate_error
        validate_error(resp, ApiErrorId.ERR_DUTY_LIMIT_EXCEEDED)

    def test_calendar_day_ledger_reports_only_minutes_on_current_date(self):
        """PRD §2.9: "Separately, each crew member carries
        `duty_minutes_calendar_day`, a compliance reporting view that counts the
        member's minutes per UTC calendar date — the minutes of their shifts,
        `OPEN` or `CLOSED`, that fall on the calendar date of the logical now."
        PRD §2.9: "a 20:00–08:00 shift counts 240 minutes against the first date
        and 480 against the second on the calendar view, but 720 contiguous
        minutes on the rolling window."

        Design: Difficulty/dual_variant_calc/duty_window_rolling_vs_calendar_day
        """
        set_clock("2026-08-01T20:00:00Z")
        base = create_base(name="Base Beta", region="NW-US")
        pilot = create_crew_member(base["id"], "Chris Cross", "PILOT")
        shift1 = create_crew_shift(
            pilot["id"], "2026-08-01T20:00:00Z", "2026-08-02T08:00:00Z"
        )
        set_clock("2026-08-02T08:00:00Z")
        close_shift(shift1["id"])
        member = get_success_data(api_client.get_crew_member(pilot["id"], OPS))
        # On 2026-08-02 the calendar view counts only 00:00-08:00 = 480 minutes.
        assert member["duty_minutes_calendar_day"] == 480, (
            f"Expected calendar-day minutes 480, got {member['duty_minutes_calendar_day']}"
        )
