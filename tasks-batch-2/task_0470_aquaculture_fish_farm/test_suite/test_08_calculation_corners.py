"""Calculation corners: water-quality WARNING band, the strict-greater ammonia
critical boundary, and treatment-window date arithmetic.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    TEST_USERS,
    set_clock,
    create_tank,
    create_species,
    create_cohort,
    record_reading,
    start_treatment,
)

FM = TEST_USERS["farm_manager_headers"]
FT = TEST_USERS["farm_technician_headers"]
VET = TEST_USERS["veterinarian_headers"]


# ===========================================================================
# calculations :: classify_reading_warning_band
# ===========================================================================
def test_do_55_classifies_warning_and_restricts_tank():
    """PRD §3.4: "Otherwise, if the dissolved oxygen is strictly below 6.0 mg/L or
    the ammonia is strictly above 0.5 mg/L, the reading is WARNING."
    PRD §3.4: "A WARNING reading (with no override floor in force) drives an OPEN
    tank to RESTRICTED (OPEN -> RESTRICTED), setting posture to RESTRICTED."

    Design: Corner/calculations/classify_reading_warning_band
    """
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    reading = validate_success(
        api_client.create_water_quality_reading(
            tank["id"],
            {"measured_at": "2026-01-02T00:00:00Z", "dissolved_oxygen_mg_l": 5.5,
             "ammonia_mg_l": 0.1, "water_temp_c": 10.0},
            FT,
        ),
        expected_status=201,
    )
    assert reading["severity"] == "WARNING", \
        f"DO 5.5 must classify WARNING, got {reading['severity']}"
    tank_after = validate_success(api_client.get_tank(tank["id"], FM))
    assert tank_after["posture"] == "RESTRICTED", \
        f"WARNING reading must drive posture RESTRICTED, got {tank_after['posture']}"


# ===========================================================================
# calculations :: ammonia_critical_threshold_strict_greater
# ===========================================================================
def test_ammonia_exactly_1_is_warning_not_critical():
    """PRD §3.4: "The reading is CRITICAL if the dissolved oxygen is strictly below
    4.0 mg/L or the ammonia is strictly above 1.0 mg/L. Otherwise, if the
    dissolved oxygen is strictly below 6.0 mg/L or the ammonia is strictly above
    0.5 mg/L, the reading is WARNING."

    Design: Corner/calculations/ammonia_critical_threshold_strict_greater
    """
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    reading = validate_success(
        api_client.create_water_quality_reading(
            tank["id"],
            {"measured_at": "2026-01-02T00:00:00Z", "dissolved_oxygen_mg_l": 8.0,
             "ammonia_mg_l": 1.0, "water_temp_c": 10.0},
            FT,
        ),
        expected_status=201,
    )
    assert reading["severity"] == "WARNING", \
        f"ammonia exactly 1.0 (not > 1.0, but > 0.5) must be WARNING, got {reading['severity']}"


# ===========================================================================
# calculations :: compute_treatment_window_precision
# ===========================================================================
def test_treatment_window_dates_computed():
    """PRD §3.7: "the treatment_end_at is the started_at advanced by duration_days
    days, and the withdrawal_end_at is the treatment_end_at advanced by a further
    withdrawal_days days."

    Design: Corner/calculations/compute_treatment_window_precision
    """
    species = create_species()
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    cohort = create_cohort(species["id"], tank["id"], fish_count=100)
    set_clock("2026-02-01T00:00:00Z")
    tx = start_treatment(cohort["id"], tank["id"], started_at="2026-02-01T00:00:00Z",
                         duration_days=5, withdrawal_days=10)
    assert tx["treatment_end_at"].startswith("2026-02-06"), \
        f"treatment_end_at must be 2026-02-06, got {tx['treatment_end_at']}"
    assert tx["withdrawal_end_at"].startswith("2026-02-16"), \
        f"withdrawal_end_at must be 2026-02-16, got {tx['withdrawal_end_at']}"
