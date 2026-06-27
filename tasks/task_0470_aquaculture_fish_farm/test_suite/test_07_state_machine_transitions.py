"""State-machine transition surface: invalid transitions, terminal lockdown,
commit idempotency, the grading revise cycle, processing reject side effects,
freeze recovery bubble-up, and the treatment-not-due precondition.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_species,
    create_tank,
    create_cohort,
    record_reading,
    start_treatment,
    create_planned_grading,
    create_harvest_order,
    setup_species_tank_cohort,
)

FM = TEST_USERS["farm_manager_headers"]
FT = TEST_USERS["farm_technician_headers"]
VET = TEST_USERS["veterinarian_headers"]
HO = TEST_USERS["harvest_operator_headers"]


# ===========================================================================
# state_machines :: harvest_complete_from_scheduled_invalid_state
# ===========================================================================
def test_complete_harvest_from_scheduled_is_invalid_state():
    """PRD §3.8: "Completing an order (IN_PROGRESS -> COMPLETED) supplies the
    actual harvested_fish_count and harvested_live_weight_kg."
    PRD §2.12: "then whether the target resource is in a state from which the
    requested transition is defined (ERR_INVALID_STATE)."

    Design: Corner/state_machines/harvest_complete_from_scheduled_invalid_state
    """
    species = create_species()
    tank = create_tank()
    cohort = create_cohort(species["id"], tank["id"], fish_count=1000)
    ho = create_harvest_order(cohort["id"], planned_fish_count=500,
                              scheduled_at="2026-01-05T00:00:00Z")
    get_success_data(api_client.schedule_harvest_order(ho["id"], HO))
    resp = api_client.complete_harvest_order(
        ho["id"], {"harvested_fish_count": 500, "harvested_live_weight_kg": 100.0}, HO
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# state_machines :: cohort_harvested_terminal_lockdown
# ===========================================================================
def test_feeding_harvested_cohort_is_invalid_state():
    """PRD §3.8: "if that brings the cohort's fish_count to 0 its lifecycle_status
    becomes HARVESTED (HARVESTING -> HARVESTED)."
    PRD §3.3: "A cohort in STOCKED moves to GROWING (STOCKED -> GROWING) on its
    first feed, provided the operational and posture preconditions above hold."

    Design: Corner/state_machines/cohort_harvested_terminal_lockdown
    """
    species = create_species()
    tank = create_tank()
    cohort = create_cohort(species["id"], tank["id"], fish_count=100)
    ho = create_harvest_order(cohort["id"], planned_fish_count=100,
                              scheduled_at="2026-01-05T00:00:00Z")
    get_success_data(api_client.schedule_harvest_order(ho["id"], HO))
    get_success_data(api_client.start_harvest_order(ho["id"], HO))
    get_success_data(
        api_client.complete_harvest_order(
            ho["id"], {"harvested_fish_count": 100, "harvested_live_weight_kg": 30.0}, HO
        )
    )
    resp = api_client.create_feed_log(
        cohort["id"], {"fed_at": "2026-01-06T00:00:00Z", "amount_kg": 5,
                       "feed_type": "grower"}, FT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# state_machines :: grading_commit_twice_idempotency_second_fails
# ===========================================================================
def test_second_grading_commit_is_invalid_state():
    """PRD §3.5: "Committing a planned event (PLANNED -> COMMITTED) is the
    consequential step and carries expected_source_cohort_version for the
    optimistic-concurrency check of §2.8."
    PRD §2.12: "then whether the target resource is in a state from which the
    requested transition is defined (ERR_INVALID_STATE)."

    Design: Corner/state_machines/grading_commit_twice_idempotency_second_fails
    """
    species = create_species()
    t1 = create_tank(name="T1")
    t2 = create_tank(name="T2")
    cohort = create_cohort(species["id"], t1["id"], fish_count=100)
    splits = [{"label": "all", "fish_count": 100, "target_tank_id": t2["id"],
               "avg_weight_g": 55}]
    grading = create_planned_grading(cohort["id"], splits)
    get_success_data(
        api_client.commit_grading_event(
            grading["id"], {"expected_source_cohort_version": cohort["version"]}, FT
        )
    )
    resp = api_client.commit_grading_event(
        grading["id"], {"expected_source_cohort_version": cohort["version"]}, FT
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# state_machines :: grading_revise_cycle_planned_to_draft
# ===========================================================================
def test_grading_revise_returns_event_to_draft():
    """PRD §3.5: "A planned event may be revised back to DRAFT (PLANNED -> DRAFT),
    optionally replacing planned_splits, which makes the planning loop cyclic."

    Design: Corner/state_machines/grading_revise_cycle_planned_to_draft
    """
    species = create_species()
    t1 = create_tank(name="T1")
    t2 = create_tank(name="T2")
    cohort = create_cohort(species["id"], t1["id"], fish_count=100)
    splits = [{"label": "all", "fish_count": 100, "target_tank_id": t2["id"],
               "avg_weight_g": 55}]
    grading = create_planned_grading(cohort["id"], splits)
    new_splits = [
        {"label": "a", "fish_count": 60, "target_tank_id": t2["id"], "avg_weight_g": 60},
        {"label": "b", "fish_count": 40, "target_tank_id": t1["id"], "avg_weight_g": 40},
    ]
    revised = validate_success(
        api_client.revise_grading_event(grading["id"], FT,
                                        payload={"planned_splits": new_splits})
    )
    assert revised["status"] == "DRAFT", \
        f"revise must return status DRAFT, got {revised['status']}"


# ===========================================================================
# state_machines :: processing_reject_no_product_lot_created
# ===========================================================================
def test_processing_reject_creates_no_product_lot():
    """PRD §3.9: "Alternatively, a batch in PROCESSING may be rejected (PROCESSING
    -> REJECTED), in which case no product lot is created."

    Design: Corner/state_machines/processing_reject_no_product_lot_created
    """
    species = create_species()
    tank = create_tank()
    cohort = create_cohort(species["id"], tank["id"], fish_count=100)
    ho = create_harvest_order(cohort["id"], planned_fish_count=10,
                              scheduled_at="2026-01-01T00:00:00Z")
    get_success_data(api_client.schedule_harvest_order(ho["id"], HO))
    get_success_data(api_client.start_harvest_order(ho["id"], HO))
    get_success_data(
        api_client.complete_harvest_order(
            ho["id"], {"harvested_fish_count": 10, "harvested_live_weight_kg": 20.0}, HO
        )
    )
    pb = get_success_data(api_client.create_processing_batch({"harvest_order_id": ho["id"]}, HO))
    get_success_data(api_client.start_processing_batch(pb["id"], HO))
    rejected = validate_success(api_client.reject_processing_batch(pb["id"], HO))
    assert rejected["status"] == "REJECTED"
    lots, meta = validate_paginated(
        api_client.list_product_lots(HO, params={"processing_batch_id": pb["id"]})
    )
    assert meta["total_count"] == 0, \
        f"rejected batch must create no product lot, got {meta['total_count']}"


# ===========================================================================
# state_machines :: tank_recovery_restores_cohort_operational_status
# ===========================================================================
def test_tank_recovery_restores_cohort_to_active():
    """PRD §3.4: "Recovery is deliberately asymmetric: when a tank returns to
    OPEN, every residing cohort whose operational_status is SUSPENDED is restored
    to ACTIVE (with a version bump)."

    Design: Corner/state_machines/tank_recovery_restores_cohort_operational_status
    """
    species = create_species()
    tank = create_tank()
    cohort = create_cohort(species["id"], tank["id"], fish_count=100)
    record_reading(tank["id"], measured_at="2026-01-02T00:00:00Z",
                   dissolved_oxygen_mg_l=3.0, ammonia_mg_l=0.1, water_temp_c=10.0)
    suspended = validate_success(api_client.get_cohort(cohort["id"], FT))
    assert suspended["operational_status"] == "SUSPENDED"
    record_reading(tank["id"], measured_at="2026-01-03T00:00:00Z",
                   dissolved_oxygen_mg_l=8.0, ammonia_mg_l=0.1, water_temp_c=10.0)
    tank_after = validate_success(api_client.get_tank(tank["id"], FM))
    cohort_after = validate_success(api_client.get_cohort(cohort["id"], FT))
    assert tank_after["posture"] == "OPEN"
    assert cohort_after["operational_status"] == "ACTIVE", \
        "residing SUSPENDED cohort must restore to ACTIVE on recovery"


# ===========================================================================
# state_machines :: treatment_complete_before_due_returns_error
# ===========================================================================
def test_complete_treatment_before_due_rejected():
    """PRD §3.7: "Completing dosing moves the treatment ACTIVE -> COMPLETED and
    the cohort UNDER_TREATMENT -> WITHDRAWAL; this is permitted only once the
    current clock has reached or passed the treatment's treatment_end_at."
    PRD §3.7: "Either action attempted before its boundary - completing before
    treatment_end_at, or clearing before withdrawal_end_at - is rejected with
    ERR_TREATMENT_NOT_DUE (HTTP 409)."

    Design: Corner/state_machines/treatment_complete_before_due_returns_error
    """
    species, tank, cohort = setup_species_tank_cohort(
        cohort_overrides={"fish_count": 100})
    tx = start_treatment(cohort["id"], tank["id"], started_at="2026-01-01T00:00:00Z",
                         duration_days=5, withdrawal_days=10)
    set_clock("2026-01-03T00:00:00Z")  # before treatment_end 2026-01-06
    resp = api_client.complete_health_treatment(tx["id"], VET)
    validate_error(resp, ApiErrorId.ERR_TREATMENT_NOT_DUE.value)
