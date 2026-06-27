"""Non-linear state-machine shapes: the cohort's parallel lifecycle x health
dimensions, the tank's cyclic posture machine, and water-quality boundary
precision driving posture.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    create_species,
    create_tank,
    create_cohort,
    feed_cohort,
    start_treatment,
    record_reading,
    setup_species_tank_cohort,
)

FM = TEST_USERS["farm_manager_headers"]
FT = TEST_USERS["farm_technician_headers"]
VET = TEST_USERS["veterinarian_headers"]


# ===========================================================================
# Rule 3 — non_linear_state_machine :: cohort_parallel_lifecycle_and_health_dimensions
# ===========================================================================
def test_feeding_then_treating_yields_growing_and_under_treatment():
    """PRD §3.3: "Lifecycle and health are parallel, independent dimensions:
    feeding advances lifecycle_status without touching health_status, so a GROWING
    cohort can simultaneously be UNDER_TREATMENT."
    PRD §3.3: "A cohort in STOCKED moves to GROWING (STOCKED -> GROWING) on its
    first feed, provided the operational and posture preconditions above hold."

    Design: Difficulty/non_linear_state_machine/cohort_parallel_lifecycle_and_health_dimensions
    """
    species, tank, cohort = setup_species_tank_cohort(
        cohort_overrides={"fish_count": 1000})
    feed_cohort(cohort["id"], fed_at="2026-01-01T00:00:00Z", amount_kg=10,
                feed_type="starter")
    start_treatment(cohort["id"], tank["id"], started_at="2026-01-01T00:00:00Z",
                    duration_days=5, withdrawal_days=10)
    refreshed = validate_success(api_client.get_cohort(cohort["id"], FT))
    assert refreshed["lifecycle_status"] == "GROWING", \
        f"expected lifecycle_status GROWING, got {refreshed['lifecycle_status']}"
    assert refreshed["health_status"] == "UNDER_TREATMENT", \
        f"expected health_status UNDER_TREATMENT, got {refreshed['health_status']}"


def test_treatment_sets_cohort_withdrawal_until():
    """PRD §3.7: "A treatment can be started only when the cohort's health_status
    is HEALTHY, moving it to UNDER_TREATMENT (HEALTHY -> UNDER_TREATMENT) and
    setting the cohort's withdrawal_until to the treatment's withdrawal_end_at."
    PRD §3.7: "the treatment_end_at is the started_at advanced by duration_days
    days, and the withdrawal_end_at is the treatment_end_at advanced by a further
    withdrawal_days days."

    Design: Difficulty/non_linear_state_machine/cohort_parallel_lifecycle_and_health_dimensions
    """
    species, tank, cohort = setup_species_tank_cohort(
        cohort_overrides={"fish_count": 1000})
    feed_cohort(cohort["id"], fed_at="2026-01-01T00:00:00Z", amount_kg=10,
                feed_type="starter")
    start_treatment(cohort["id"], tank["id"], started_at="2026-01-01T00:00:00Z",
                    duration_days=5, withdrawal_days=10)
    refreshed = validate_success(api_client.get_cohort(cohort["id"], FT))
    # treatment_end 2026-01-06 + 10 withdrawal days -> 2026-01-16
    assert refreshed["withdrawal_until"] is not None, "withdrawal_until must be set"
    assert refreshed["withdrawal_until"].startswith("2026-01-16"), \
        f"expected withdrawal_until 2026-01-16, got {refreshed['withdrawal_until']}"


# ===========================================================================
# Rule 3 — non_linear_state_machine :: tank_posture_cyclic_open_frozen_open
# ===========================================================================
def test_critical_reading_freezes_tank():
    """PRD §3.4: "A CRITICAL reading drives OPEN -> FROZEN or RESTRICTED ->
    FROZEN, setting posture to FROZEN."
    PRD §3.4: "The reading is CRITICAL if the dissolved oxygen is strictly below
    4.0 mg/L or the ammonia is strictly above 1.0 mg/L."

    Design: Difficulty/non_linear_state_machine/tank_posture_cyclic_open_frozen_open
    """
    tank = create_tank(kind="POND", volume_liters=500000, max_biomass_kg=50000)
    record_reading(tank["id"], measured_at="2026-01-02T00:00:00Z",
                   dissolved_oxygen_mg_l=3.0, ammonia_mg_l=0.1, water_temp_c=10.0)
    refreshed = validate_success(api_client.get_tank(tank["id"], FM))
    assert refreshed["posture"] == "FROZEN", \
        f"expected posture FROZEN after CRITICAL reading, got {refreshed['posture']}"


def test_posture_cycles_back_to_open_on_normal_reading():
    """PRD §3.4: "Recovery runs the other way when posture_override is null: a
    NORMAL reading restores RESTRICTED -> OPEN or FROZEN -> OPEN, and a WARNING
    reading eases FROZEN -> RESTRICTED."

    Design: Difficulty/non_linear_state_machine/tank_posture_cyclic_open_frozen_open
    """
    tank = create_tank(kind="POND", volume_liters=500000, max_biomass_kg=50000)
    record_reading(tank["id"], measured_at="2026-01-02T00:00:00Z",
                   dissolved_oxygen_mg_l=3.0, ammonia_mg_l=0.1, water_temp_c=10.0)
    frozen = validate_success(api_client.get_tank(tank["id"], FM))
    assert frozen["posture"] == "FROZEN"
    record_reading(tank["id"], measured_at="2026-01-03T00:00:00Z",
                   dissolved_oxygen_mg_l=8.0, ammonia_mg_l=0.1, water_temp_c=10.0)
    recovered = validate_success(api_client.get_tank(tank["id"], FM))
    assert recovered["posture"] == "OPEN", \
        f"expected posture OPEN (cycled back), got {recovered['posture']}"


# ===========================================================================
# Rule 6 — boundary_precision_check :: do_threshold_strict_less_than_critical
# ===========================================================================
def test_do_exactly_4_is_warning_not_critical():
    """PRD §3.4: "The reading is CRITICAL if the dissolved oxygen is strictly
    below 4.0 mg/L or the ammonia is strictly above 1.0 mg/L. Otherwise, if the
    dissolved oxygen is strictly below 6.0 mg/L or the ammonia is strictly above
    0.5 mg/L, the reading is WARNING."
    PRD §3.4: "The boundary is exact: a dissolved oxygen reading of exactly 4.0 is
    not critical, while 3.99 is."

    Design: Difficulty/boundary_precision_check/do_threshold_strict_less_than_critical
    """
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    reading = validate_success(
        api_client.create_water_quality_reading(
            tank["id"],
            {"measured_at": "2026-01-02T00:00:00Z", "dissolved_oxygen_mg_l": 4.0,
             "ammonia_mg_l": 0.1, "water_temp_c": 10.0},
            FT,
        ),
        expected_status=201,
    )
    assert reading["severity"] == "WARNING", \
        f"DO exactly 4.0 must classify WARNING, got {reading['severity']}"


def test_do_exactly_4_drives_restricted_not_frozen():
    """PRD §3.4: "A WARNING reading (with no override floor in force) drives an
    OPEN tank to RESTRICTED (OPEN -> RESTRICTED), setting posture to RESTRICTED."
    PRD §3.4: "The boundary is exact: a dissolved oxygen reading of exactly 4.0 is
    not critical, while 3.99 is."

    Design: Difficulty/boundary_precision_check/do_threshold_strict_less_than_critical
    """
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    record_reading(tank["id"], measured_at="2026-01-02T00:00:00Z",
                   dissolved_oxygen_mg_l=4.0, ammonia_mg_l=0.1, water_temp_c=10.0)
    refreshed = validate_success(api_client.get_tank(tank["id"], FM))
    assert refreshed["posture"] == "RESTRICTED", \
        f"DO exactly 4.0 must leave tank RESTRICTED (not FROZEN), got {refreshed['posture']}"


def test_do_below_4_is_critical_and_freezes():
    """PRD §3.4: "The reading is CRITICAL if the dissolved oxygen is strictly
    below 4.0 mg/L or the ammonia is strictly above 1.0 mg/L."
    PRD §3.4: "The boundary is exact: a dissolved oxygen reading of exactly 4.0 is
    not critical, while 3.99 is."

    Design: Difficulty/boundary_precision_check/do_threshold_strict_less_than_critical
    """
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    reading = validate_success(
        api_client.create_water_quality_reading(
            tank["id"],
            {"measured_at": "2026-01-02T00:00:00Z", "dissolved_oxygen_mg_l": 3.99,
             "ammonia_mg_l": 0.1, "water_temp_c": 10.0},
            FT,
        ),
        expected_status=201,
    )
    assert reading["severity"] == "CRITICAL", \
        f"DO 3.99 must classify CRITICAL, got {reading['severity']}"
    refreshed = validate_success(api_client.get_tank(tank["id"], FM))
    assert refreshed["posture"] == "FROZEN", \
        f"DO 3.99 must drive posture FROZEN, got {refreshed['posture']}"
