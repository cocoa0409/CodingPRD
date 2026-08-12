"""wRVU dual-variant rounding tests: provisional (per-line round then sum) vs
final (sum raw then round once) — the two variants deliberately diverge.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data, ApiErrorId,
    TEST_USERS, make_hospitalist_headers,
    set_clock, create_hospitalist, create_patient, create_encounter_for,
    generate_report,
)

ADMIN = TEST_USERS["group_admin_headers"]


class TestWrvuProvisionalVsFinalDiverge:
    """Difficulty instance: wrvu_provisional_vs_final_diverge."""

    def test_provisional_per_line_rounding_then_sum(self, api):
        """PRD §3.8: "the report is born `PROVISIONAL`, links every `RECORDED`
        encounter of that hospitalist whose `occurred_on` falls inside the
        period by stamping their `productivity_report_id`, and computes its
        provisional view: `encounter_count`, the size of the linked set, and
        `total_wrvu_provisional`, the sum of the per-line `estimated_wrvu`
        values — per-line rounding first, summation second."
        PRD §3.8: "the server computes `estimated_wrvu`: the encounter type's
        standard estimate — 2.5 for `ADMISSION_HCP`, 1.2 for `SUBSEQUENT_VISIT`,
        1.8 for `DISCHARGE_DAY`, 1.5 for `CONSULT_NOTE` — multiplied by the
        adjustment factor 1.06, the product rounded half up to two decimals,
        per line, and stored on the encounter."

        Design: Difficulty/dual_variant_calc/wrvu_provisional_vs_final_diverge
        """
        set_clock("2026-05-04T12:00:00Z")
        h = create_hospitalist("H One", "INTERNAL_MEDICINE", max_census_cap=16)
        p = create_patient(mrn="M001", acuity="MEDIUM", admit_source="DIRECT",
                           stay_type="INPATIENT", admitted_at="2026-05-04T08:00:00Z")
        e1 = create_encounter_for(p["id"], h["id"], "ADMISSION_HCP", "2026-05-04", 2.654)
        e2 = create_encounter_for(p["id"], h["id"], "SUBSEQUENT_VISIT", "2026-05-04", 1.115)
        # per-line estimates pinned by PRD §3.8
        assert e1["estimated_wrvu"] == pytest.approx(2.65, abs=0.001)
        assert e2["estimated_wrvu"] == pytest.approx(1.27, abs=0.001)

        report = generate_report(h["id"], "2026-05-01", "2026-05-31")
        assert report["status"] == "PROVISIONAL"
        # per-line round then sum: 2.65 + 1.27 = 3.92
        assert report["total_wrvu_provisional"] == pytest.approx(3.92, abs=0.001)
        assert report["encounter_count"] == 2
        # final fields remain null until first finalize
        assert report["total_wrvu_final"] is None
        assert report["wrvu_variance"] is None

    def test_final_sum_then_single_rounding(self, api):
        """PRD §3.8: "The final variant follows the opposite rounding
        discipline: the raw `wrvu_value` figures across the linked `RECORDED`
        set are summed first and the total is rounded once, half up to two
        decimals, yielding `total_wrvu_final`; `wrvu_variance` is that final
        total minus the provisional total, again at two decimals."

        Design: Difficulty/dual_variant_calc/wrvu_provisional_vs_final_diverge
        """
        set_clock("2026-05-04T12:00:00Z")
        h = create_hospitalist("H One", "INTERNAL_MEDICINE", max_census_cap=16)
        p = create_patient(mrn="M002", acuity="MEDIUM", admit_source="DIRECT",
                           stay_type="INPATIENT", admitted_at="2026-05-04T08:00:00Z")
        create_encounter_for(p["id"], h["id"], "ADMISSION_HCP", "2026-05-04", 2.654)
        create_encounter_for(p["id"], h["id"], "SUBSEQUENT_VISIT", "2026-05-04", 1.115)
        report = generate_report(h["id"], "2026-05-01", "2026-05-31")

        fin = get_success_data(api.finalize_productivity_report(report["id"], ADMIN))
        assert fin["status"] == "FINALIZED"
        # sum raw: 2.654 + 1.115 = 3.769 -> round(3.769, 2) = 3.77
        assert fin["total_wrvu_final"] == pytest.approx(3.77, abs=0.001)
        # variance: 3.77 - 3.92 = -0.15
        assert fin["wrvu_variance"] == pytest.approx(-0.15, abs=0.001)
        assert fin["encounter_count"] == 2
        # provisional is unchanged after finalize
        assert fin["total_wrvu_provisional"] == pytest.approx(3.92, abs=0.001)


class TestLosMidnightsVsHourBlocksDiverge:
    """Difficulty instance: los_midnights_vs_hour_blocks_diverge."""

    def test_los_midnights_counts_calendar_boundaries(self, api):
        """PRD §3.2: "`los_midnights` counts the UTC calendar dates strictly
        after the date of `admitted_at` and on or before the current date —
        a midnight-census view, so a patient admitted at 23:00 and measured
        the next day at 01:00 shows 1."

        Design: Difficulty/dual_variant_calc/los_midnights_vs_hour_blocks_diverge
        """
        p = create_patient(mrn="M101", acuity="MEDIUM", admit_source="ED",
                           stay_type="INPATIENT", admitted_at="2026-05-01T23:00:00Z")
        set_clock("2026-05-02T01:00:00Z")
        api.monitor_run(ADMIN)
        p_now = get_success_data(api.get_patient(p["id"], ADMIN))
        assert p_now["los_midnights"] == 1

    def test_los_blocks_counts_full_24h_blocks(self, api):
        """PRD §3.2: "`los_blocks` instead counts whole 24-hour blocks fully
        elapsed since `admitted_at` — the same 23:00-to-01:00 measurement
        yields 0."
        PRD §3.2: "`los_alert_flag` turns true when `los_midnights` strictly
        exceeds the expected stay for the patient's current `stay_type` and
        `acuity` multiplied by 1.5 — equality is not an alert."

        Design: Difficulty/dual_variant_calc/los_midnights_vs_hour_blocks_diverge
        """
        p = create_patient(mrn="M102", acuity="MEDIUM", admit_source="ED",
                           stay_type="INPATIENT", admitted_at="2026-05-01T23:00:00Z")
        set_clock("2026-05-02T01:00:00Z")
        api.monitor_run(ADMIN)
        p_now = get_success_data(api.get_patient(p["id"], ADMIN))
        assert p_now["los_blocks"] == 0
        # same inputs, divergent variants
        assert p_now["los_midnights"] != p_now["los_blocks"]
        # MEDIUM INPATIENT threshold = 4 * 1.5 = 6; 1 midnight is not > 6
        assert p_now["los_alert_flag"] is False
