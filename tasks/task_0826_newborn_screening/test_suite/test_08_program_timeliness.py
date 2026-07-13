"""Program timeliness summary: round-per-facility-then-average and the empty set (Newborn Screening PRD)."""
from test_helpers import (
    validate_success,
    create_facility,
    create_infant,
    create_specimen,
    receive_specimen,
    open_screen,
    set_clock,
    TEST_USERS,
)

LAB = TEST_USERS["lab_technician_headers"]
ADMIN = TEST_USERS["program_admin_headers"]


def _screened_initial(facility, infant):
    """Create an INITIAL specimen for `infant`, receive it SATISFACTORY, and open a screen
    (leaving the specimen IN_TESTING, ready for a metabolic report)."""
    specimen = create_specimen(facility, infant)  # collection +30h, INITIAL
    receive_specimen(specimen)                     # +18h transit, 5 spots → SATISFACTORY
    return open_screen(specimen), specimen


def _build_rate_75_scenario(api):
    """Two CA hospitals. Hosp A reports one TIMELY (48h) + one DELAYED (138h) → 50.0.
    Hosp B reports one TIMELY (48h) → 100.0. Program mean of rounded rates → 75.0."""
    hosp_a = create_facility(name="Hosp A", state_region="CA")
    hosp_b = create_facility(name="Hosp B", state_region="CA")
    a1 = create_infant(hosp_a)
    a2 = create_infant(hosp_a)
    b1 = create_infant(hosp_b)
    a1_screen, _ = _screened_initial(hosp_a, a1)
    a2_screen, _ = _screened_initial(hosp_a, a2)
    b1_screen, _ = _screened_initial(hosp_b, b1)

    # Report a1 and b1 with a 48-hour birth→report turnaround → TIMELY.
    set_clock("2026-03-01T06:00:00Z")
    api.report_metabolic(a1_screen["id"], {"metabolic_result": "NORMAL"}, LAB)
    api.report_metabolic(b1_screen["id"], {"metabolic_result": "NORMAL"}, LAB)
    # Report a2 with a 138-hour turnaround → DELAYED.
    set_clock("2026-03-05T00:00:00Z")
    api.report_metabolic(a2_screen["id"], {"metabolic_result": "NORMAL"}, LAB)


def test_program_rate_round_per_facility_then_average_is_75(api):
    """PRD §3.9: "For each facility with at least one eligible specimen, the per-facility
    rate is 100 times the count of that facility's eligible specimens classified `TIMELY`,
    divided by that facility's total eligible specimen count, rounded half-up to one decimal
    place."
    PRD §3.9: "The `program_rate` is then the mean of those already-rounded per-facility
    rates, itself rounded half-up to one decimal place."

    Design: Difficulty/combinatorial_formula/program_timeliness_rate_round_then_average_75
    """
    _build_rate_75_scenario(api)
    summary = validate_success(
        api.get_timeliness_summary(ADMIN, params={"state_region": "CA"}), 200
    )
    assert summary["program_rate"] == 75.0


def test_program_summary_reports_facility_and_eligible_counts(api):
    """PRD §3.9: "The response also reports `facility_count`, the number of facilities that
    contributed at least one eligible specimen, and `eligible_specimen_count`, the total
    number of eligible specimens counted."

    Design: Difficulty/combinatorial_formula/program_timeliness_rate_round_then_average_75
    """
    _build_rate_75_scenario(api)
    summary = validate_success(
        api.get_timeliness_summary(ADMIN, params={"state_region": "CA"}), 200
    )
    assert summary["facility_count"] == 2
    assert summary["eligible_specimen_count"] == 3


def test_program_rate_empty_set_returns_null(api):
    """PRD §3.9: "If no facility has any eligible specimen, the `program_rate` is null — not
    zero, and not an error."

    Design: Difficulty/boundary_precision_check/program_rate_empty_set_returns_null
    """
    create_facility(name="Hosp A", state_region="CA")  # no infants, no eligible specimens
    summary = validate_success(
        api.get_timeliness_summary(ADMIN, params={"state_region": "CA"}), 200
    )
    assert summary["program_rate"] is None


def test_program_summary_empty_set_zero_counts(api):
    """PRD §3.9: "The metric is computed only over **eligible** specimens: those whose
    `specimen_type` is `INITIAL` and whose `timeliness_final` has been reported (is not
    null)."

    Design: Difficulty/boundary_precision_check/program_rate_empty_set_returns_null
    """
    create_facility(name="Hosp A", state_region="CA")
    summary = validate_success(
        api.get_timeliness_summary(ADMIN, params={"state_region": "CA"}), 200
    )
    assert summary["facility_count"] == 0
    assert summary["eligible_specimen_count"] == 0
