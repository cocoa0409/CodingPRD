"""wRVU rounding-order tests: per-line-then-sum (provisional) vs sum-then-round
(final), plus the per-encounter-type estimate constants.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_hospitalist_headers,
    set_clock, create_hospitalist, create_patient, create_encounter_for,
    generate_report,
)

ADMIN = TEST_USERS["group_admin_headers"]


class TestWrvuRoundingOrderPinned:
    """Difficulty instance: wrvu_rounding_order_pinned."""

    def test_per_line_estimate_rounding(self, api):
        """PRD §3.8: "the server computes `estimated_wrvu`: the encounter
        type's standard estimate — 2.5 for `ADMISSION_HCP`, 1.2 for
        `SUBSEQUENT_VISIT`, 1.8 for `DISCHARGE_DAY`, 1.5 for `CONSULT_NOTE` —
        multiplied by the adjustment factor 1.06, the product rounded half up
        to two decimals, per line, and stored on the encounter."

        Design: Difficulty/combinatorial_formula/wrvu_rounding_order_pinned
        """
        set_clock("2026-05-04T12:00:00Z")
        h = create_hospitalist("H One", "ICU", max_census_cap=16)
        p = create_patient(mrn="M301", acuity="HIGH", admit_source="TRANSFER",
                           stay_type="INPATIENT", admitted_at="2026-05-04T06:00:00Z")
        e3 = create_encounter_for(p["id"], h["id"], "CONSULT_NOTE", "2026-05-04", 1.505)
        e4 = create_encounter_for(p["id"], h["id"], "DISCHARGE_DAY", "2026-05-04", 1.805)
        # per-line estimate: round(1.5 * 1.06, 2) = round(1.59, 2) = 1.59
        assert e3["estimated_wrvu"] == pytest.approx(1.59, abs=0.001)
        # per-line estimate: round(1.8 * 1.06, 2) = round(1.908, 2) = 1.91
        assert e4["estimated_wrvu"] == pytest.approx(1.91, abs=0.001)

    def test_provisional_vs_final_rounding_diverges(self, api):
        """PRD §3.8: "the report is born `PROVISIONAL` ... `total_wrvu_provisional`,
        the sum of the per-line `estimated_wrvu` values — per-line rounding
        first, summation second."
        PRD §3.8: "The final variant follows the opposite rounding discipline:
        the raw `wrvu_value` figures across the linked `RECORDED` set are
        summed first and the total is rounded once, half up to two decimals,
        yielding `total_wrvu_final`; `wrvu_variance` is that final total minus
        the provisional total, again at two decimals."

        Design: Difficulty/combinatorial_formula/wrvu_rounding_order_pinned
        """
        set_clock("2026-05-04T12:00:00Z")
        h = create_hospitalist("H One", "ICU", max_census_cap=16)
        p = create_patient(mrn="M302", acuity="HIGH", admit_source="TRANSFER",
                           stay_type="INPATIENT", admitted_at="2026-05-04T06:00:00Z")
        create_encounter_for(p["id"], h["id"], "CONSULT_NOTE", "2026-05-04", 1.505)
        create_encounter_for(p["id"], h["id"], "DISCHARGE_DAY", "2026-05-04", 1.805)
        report = generate_report(h["id"], "2026-05-01", "2026-05-31")
        # provisional: 1.59 + 1.91 = 3.50
        assert report["total_wrvu_provisional"] == pytest.approx(3.50, abs=0.001)
        fin = get_success_data(api.finalize_productivity_report(report["id"], ADMIN))
        # final: round(1.505 + 1.805, 2) = round(3.31, 2) = 3.31
        assert fin["total_wrvu_final"] == pytest.approx(3.31, abs=0.001)
        # variance: 3.31 - 3.50 = -0.19
        assert fin["wrvu_variance"] == pytest.approx(-0.19, abs=0.001)


class TestEncounterEstimatedWrvuConstants:
    """Corner instance: encounter_estimated_wrvu_constants."""

    @pytest.mark.parametrize("encounter_type,wrvu,expected_est", [
        ("ADMISSION_HCP", 2.5, 2.65),
        ("SUBSEQUENT_VISIT", 1.2, 1.27),
        ("DISCHARGE_DAY", 1.8, 1.91),
        ("CONSULT_NOTE", 1.5, 1.59),
    ])
    def test_estimate_per_encounter_type(self, api, encounter_type, wrvu, expected_est):
        """PRD §3.8: "the server computes `estimated_wrvu`: the encounter
        type's standard estimate — 2.5 for `ADMISSION_HCP`, 1.2 for
        `SUBSEQUENT_VISIT`, 1.8 for `DISCHARGE_DAY`, 1.5 for `CONSULT_NOTE` —
        multiplied by the adjustment factor 1.06, the product rounded half up
        to two decimals, per line, and stored on the encounter."

        Design: Corner/calculations/encounter_estimated_wrvu_constants
        """
        set_clock("2026-05-04T12:00:00Z")
        h = create_hospitalist("H One", "ICU", max_census_cap=16)
        p = create_patient(mrn=f"K008-{encounter_type}", acuity="MEDIUM",
                           admit_source="DIRECT", stay_type="INPATIENT",
                           admitted_at="2026-05-04T08:00:00Z")
        e = create_encounter_for(p["id"], h["id"], encounter_type, "2026-05-04", wrvu)
        assert e["estimated_wrvu"] == pytest.approx(expected_est, abs=0.001)
