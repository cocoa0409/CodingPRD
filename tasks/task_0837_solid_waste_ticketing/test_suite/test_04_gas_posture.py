"""Gas-status thresholds and their effect on acceptance posture."""
from test_helpers import create_facility, create_gas_reading, get_facility


def test_methane_500_is_exceedance_and_closes_facility(api):
    """PRD §2.9: "From that value the facility's `gas_status` is `EXCEEDANCE` when the
    concentration is at least 500 ppm, `ELEVATED` when it is at least 200 ppm but below 500,
    and `NORMAL` below 200 ppm."
    PRD §2.9: "if `gas_status` is `EXCEEDANCE`, the posture is `CLOSED`".

    Design: Difficulty/boundary_precision_check/methane_exceedance_500_inclusive_boundary
    """
    facility = create_facility(1000)
    reading = create_gas_reading(facility["id"], 500, "2026-03-01T10:00:00Z")
    assert reading["resulting_gas_status"] == "EXCEEDANCE"
    fetched = get_facility(facility["id"])
    assert fetched["gas_status"] == "EXCEEDANCE"
    assert fetched["acceptance_posture"] == "CLOSED"


def test_methane_499_is_elevated_not_exceedance(api):
    """PRD §2.9: "From that value the facility's `gas_status` is `EXCEEDANCE` when the
    concentration is at least 500 ppm, `ELEVATED` when it is at least 200 ppm but below 500,
    and `NORMAL` below 200 ppm."

    Design: Difficulty/boundary_precision_check/methane_exceedance_500_inclusive_boundary
    """
    facility = create_facility(1000)
    reading = create_gas_reading(facility["id"], 499, "2026-03-01T10:00:00Z")
    assert reading["resulting_gas_status"] == "ELEVATED"
    fetched = get_facility(facility["id"])
    assert fetched["gas_status"] == "ELEVATED"


def test_methane_200_is_elevated_inclusive_facility_stays_open(api):
    """PRD §2.9: "From that value the facility's `gas_status` is `EXCEEDANCE` when the
    concentration is at least 500 ppm, `ELEVATED` when it is at least 200 ppm but below 500,
    and `NORMAL` below 200 ppm."
    PRD §2.9: "otherwise, if `remaining_airspace_cubic_yards` is at most ten percent of
    `total_airspace_cubic_yards`, the posture is `RESTRICTED`; otherwise the posture is
    `OPEN`."

    Design: Corner/calculations/gas_elevated_boundary_200_inclusive
    """
    facility = create_facility(500)
    reading = create_gas_reading(facility["id"], 200, "2026-03-01T07:00:00Z")
    assert reading["resulting_gas_status"] == "ELEVATED"
    fetched = get_facility(facility["id"])
    assert fetched["gas_status"] == "ELEVATED"
    assert fetched["acceptance_posture"] == "OPEN"
