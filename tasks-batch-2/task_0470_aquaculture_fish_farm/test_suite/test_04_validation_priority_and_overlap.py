"""Validation precedence between rule categories, plus the two distinct interval-
overlap semantics (half-open tank occupancy vs buffer-extended treatment window).
"""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_species,
    create_tank,
    create_cohort,
    start_treatment,
    record_reading,
    create_stocking_event_payload,
    create_harvest_order_payload,
    create_health_treatment_payload,
)

FM = TEST_USERS["farm_manager_headers"]
FT = TEST_USERS["farm_technician_headers"]
VET = TEST_USERS["veterinarian_headers"]
HO = TEST_USERS["harvest_operator_headers"]


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict :: stocking_safety_beats_temporal_overlap
# ===========================================================================
def test_frozen_tank_stocking_with_overlap_reports_posture_not_overlap():
    """PRD §2.12: "Only after those five gates pass does the system evaluate
    domain-specific business rules: the tank posture and operational gate, the
    withdrawal gate, occupancy and treatment-window overlap, grading conservation,
    lot integrity and availability, biomass capacity, and broodstock allocation,
    in the order described across §3."
    PRD §3.6: "a stocking attempt against a tank whose posture is RESTRICTED or
    FROZEN is rejected with ERR_TANK_NOT_OPERATIONAL (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/stocking_safety_beats_temporal_overlap
    """
    species = create_species()
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    c1 = create_cohort(species["id"], tank["id"], label="C1", fish_count=100)
    get_success_data(
        api_client.create_stocking_event(
            create_stocking_event_payload(c1["id"], tank["id"], fish_count=100,
                                          stocked_at="2026-01-01T00:00:00Z",
                                          expected_harvest_at="2026-06-01T00:00:00Z"),
            FT,
        )
    )
    c2 = create_cohort(species["id"], tank["id"], label="C2", fish_count=100)
    # freeze the tank with a CRITICAL reading
    record_reading(tank["id"], measured_at="2026-01-02T00:00:00Z",
                   dissolved_oxygen_mg_l=3.0, ammonia_mg_l=0.1, water_temp_c=10.0)
    # this stocking both overlaps [2026-01-01,2026-06-01) AND hits a FROZEN tank
    resp = api_client.create_stocking_event(
        create_stocking_event_payload(c2["id"], tank["id"], fish_count=100,
                                      stocked_at="2026-03-01T00:00:00Z",
                                      expected_harvest_at="2026-09-01T00:00:00Z"),
        FT,
    )
    validate_error(resp, ApiErrorId.ERR_TANK_NOT_OPERATIONAL.value)


def test_frozen_tank_stocking_without_overlap_still_reports_posture():
    """PRD §3.6: "a stocking attempt against a tank whose posture is RESTRICTED or
    FROZEN is rejected with ERR_TANK_NOT_OPERATIONAL (HTTP 409)."
    PRD §2.12: "the system evaluate domain-specific business rules: the tank
    posture and operational gate, the withdrawal gate, occupancy and
    treatment-window overlap ... in the order described across §3."

    Design: Difficulty/priority_pair_validation_conflict/stocking_safety_beats_temporal_overlap
    """
    species = create_species()
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    cohort = create_cohort(species["id"], tank["id"], label="C1", fish_count=100)
    # freeze the tank; no prior occupancy interval exists so overlap cannot fire
    record_reading(tank["id"], measured_at="2026-01-02T00:00:00Z",
                   dissolved_oxygen_mg_l=3.0, ammonia_mg_l=0.1, water_temp_c=10.0)
    resp = api_client.create_stocking_event(
        create_stocking_event_payload(cohort["id"], tank["id"], fish_count=100,
                                      stocked_at="2026-03-01T00:00:00Z",
                                      expected_harvest_at="2026-09-01T00:00:00Z"),
        FT,
    )
    validate_error(resp, ApiErrorId.ERR_TANK_NOT_OPERATIONAL.value)


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict :: harvest_start_state_beats_withdrawal_safety
# ===========================================================================
def test_start_draft_harvest_under_treatment_reports_invalid_state_not_withdrawal():
    """PRD §2.12: "then whether the target resource is in a state from which the
    requested transition is defined (ERR_INVALID_STATE), then the
    optimistic-concurrency version match (ERR_STALE_VERSION). Only after those five
    gates pass does the system evaluate domain-specific business rules ... the
    withdrawal gate."
    PRD §3.8: "Starting an order (SCHEDULED -> IN_PROGRESS) again requires the
    cohort to be ACTIVE, HEALTHY, and past withdrawal."

    Design: Difficulty/priority_pair_validation_conflict/harvest_start_state_beats_withdrawal_safety
    """
    species = create_species()
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    cohort = create_cohort(species["id"], tank["id"], fish_count=1000)
    ho = get_success_data(
        api_client.create_harvest_order(
            create_harvest_order_payload(cohort["id"], planned_fish_count=500,
                                         scheduled_at="2026-01-05T00:00:00Z"),
            HO,
        )
    )
    # cohort UNDER_TREATMENT, but the order is still DRAFT (never scheduled)
    start_treatment(cohort["id"], tank["id"], started_at="2026-01-01T00:00:00Z",
                    duration_days=5, withdrawal_days=10)
    resp = api_client.start_harvest_order(ho["id"], HO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_start_draft_harvest_healthy_cohort_reports_invalid_state():
    """PRD §2.12: "then whether the target resource is in a state from which the
    requested transition is defined (ERR_INVALID_STATE)."
    PRD §3.8: "Starting an order (SCHEDULED -> IN_PROGRESS) again requires the
    cohort to be ACTIVE, HEALTHY, and past withdrawal."

    Design: Difficulty/priority_pair_validation_conflict/harvest_start_state_beats_withdrawal_safety
    """
    species = create_species()
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    cohort = create_cohort(species["id"], tank["id"], fish_count=1000)
    # cohort is HEALTHY with no withdrawal; order is DRAFT (not SCHEDULED)
    ho = get_success_data(
        api_client.create_harvest_order(
            create_harvest_order_payload(cohort["id"], planned_fish_count=500,
                                         scheduled_at="2026-01-05T00:00:00Z"),
            HO,
        )
    )
    resp = api_client.start_harvest_order(ho["id"], HO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Rule 8 — resource_temporal_overlap :: tank_occupancy_half_open_overlap
# ===========================================================================
def test_overlapping_stocking_interval_rejected():
    """PRD §3.6: "A new stocking event's interval must not overlap any existing
    in-production occupancy interval on the same tank; because the interval is
    half-open, a new event whose stocked_at equals a prior interval's
    expected_harvest_at is back-to-back and allowed, while any genuine overlap is
    rejected with ERR_TANK_OCCUPANCY_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/tank_occupancy_half_open_overlap
    """
    species = create_species()
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    c1 = create_cohort(species["id"], tank["id"], label="C1", fish_count=100)
    get_success_data(
        api_client.create_stocking_event(
            create_stocking_event_payload(c1["id"], tank["id"], fish_count=100,
                                          stocked_at="2026-01-01T00:00:00Z",
                                          expected_harvest_at="2026-06-01T00:00:00Z"),
            FT,
        )
    )
    c2 = create_cohort(species["id"], tank["id"], label="C2", fish_count=100)
    resp = api_client.create_stocking_event(
        create_stocking_event_payload(c2["id"], tank["id"], fish_count=100,
                                      stocked_at="2026-03-01T00:00:00Z",
                                      expected_harvest_at="2026-09-01T00:00:00Z"),
        FT,
    )
    validate_error(resp, ApiErrorId.ERR_TANK_OCCUPANCY_OVERLAP.value)


def test_back_to_back_stocking_at_boundary_allowed():
    """PRD §3.6: "because the interval is half-open, a new event whose stocked_at
    equals a prior interval's expected_harvest_at is back-to-back and allowed,
    while any genuine overlap is rejected with ERR_TANK_OCCUPANCY_OVERLAP (HTTP
    409)."

    Design: Difficulty/resource_temporal_overlap/tank_occupancy_half_open_overlap
    """
    species = create_species()
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    c1 = create_cohort(species["id"], tank["id"], label="C1", fish_count=100)
    get_success_data(
        api_client.create_stocking_event(
            create_stocking_event_payload(c1["id"], tank["id"], fish_count=100,
                                          stocked_at="2026-01-01T00:00:00Z",
                                          expected_harvest_at="2026-06-01T00:00:00Z"),
            FT,
        )
    )
    c2 = create_cohort(species["id"], tank["id"], label="C2", fish_count=100)
    # stocked_at == prior expected_harvest_at -> back-to-back, allowed
    resp = api_client.create_stocking_event(
        create_stocking_event_payload(c2["id"], tank["id"], fish_count=100,
                                      stocked_at="2026-06-01T00:00:00Z",
                                      expected_harvest_at="2026-09-01T00:00:00Z"),
        FT,
    )
    from test_helpers import validate_success
    validate_success(resp, expected_status=201)


# ===========================================================================
# Rule 8 — resource_temporal_overlap :: treatment_window_buffer_extended_overlap
# ===========================================================================
def test_treatment_within_prior_withdrawal_buffer_rejected():
    """PRD §3.7: "A new treatment on a tank is rejected if its started_at falls
    before the withdrawal_end_at of any prior treatment on that same tank whose
    status is ACTIVE or COMPLETED; because the withdrawal period acts as a
    mandatory buffer, adjacency is allowed - a new treatment whose started_at
    equals a prior treatment's withdrawal_end_at is permitted, while an earlier
    start is rejected with ERR_TREATMENT_WINDOW_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/treatment_window_buffer_extended_overlap
    """
    species = create_species()
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    c1 = create_cohort(species["id"], tank["id"], label="C1", fish_count=100)
    c2 = create_cohort(species["id"], tank["id"], label="C2", fish_count=100)
    # prior treatment: started 2026-01-01, dur 5, withdrawal 10 -> end 2026-01-16
    start_treatment(c1["id"], tank["id"], started_at="2026-01-01T00:00:00Z",
                    duration_days=5, withdrawal_days=10)
    # new treatment starts 2026-01-10 < 2026-01-16 -> rejected
    resp = api_client.create_health_treatment(
        create_health_treatment_payload(c2["id"], tank["id"], medication="florfenicol",
                                        started_at="2026-01-10T00:00:00Z",
                                        duration_days=3, withdrawal_days=7),
        VET,
    )
    validate_error(resp, ApiErrorId.ERR_TREATMENT_WINDOW_CONFLICT.value)


def test_treatment_adjacent_to_prior_withdrawal_end_allowed():
    """PRD §3.7: "adjacency is allowed - a new treatment whose started_at equals a
    prior treatment's withdrawal_end_at is permitted, while an earlier start is
    rejected with ERR_TREATMENT_WINDOW_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/treatment_window_buffer_extended_overlap
    """
    from test_helpers import validate_success
    species = create_species()
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    c1 = create_cohort(species["id"], tank["id"], label="C1", fish_count=100)
    c2 = create_cohort(species["id"], tank["id"], label="C2", fish_count=100)
    start_treatment(c1["id"], tank["id"], started_at="2026-01-01T00:00:00Z",
                    duration_days=5, withdrawal_days=10)
    # new treatment starts exactly at prior withdrawal_end_at 2026-01-16 -> allowed
    resp = api_client.create_health_treatment(
        create_health_treatment_payload(c2["id"], tank["id"], medication="florfenicol",
                                        started_at="2026-01-16T00:00:00Z",
                                        duration_days=3, withdrawal_days=7),
        VET,
    )
    validate_success(resp, expected_status=201)
