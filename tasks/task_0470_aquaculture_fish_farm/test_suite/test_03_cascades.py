"""Transitive cascades and cross-entity state dependencies: the tank-freeze
depth-3 chain, the sales-cancel lot-release depth-2 chain, the lot-depletes-at-
zero boundary, and the harvest/stocking cross-entity gates.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_species,
    create_tank,
    create_cohort,
    feed_cohort,
    record_reading,
    drive_tank_restricted,
    create_scheduled_harvest_order,
    setup_species_tank_cohort,
    setup_cohort_under_treatment,
    setup_confirmed_order_on_lot,
    create_product_lot,
    create_sales_order,
    add_line,
    get_lot,
    create_stocking_event_payload,
    create_harvest_order_payload,
)

FM = TEST_USERS["farm_manager_headers"]
FT = TEST_USERS["farm_technician_headers"]
HO = TEST_USERS["harvest_operator_headers"]
SA = TEST_USERS["sales_agent_headers"]


# ===========================================================================
# Rule 4 — transitive_cascade :: tank_freeze_cascades_to_cohort_then_harvest_order_depth3
# ===========================================================================
def _setup_growing_cohort_with_scheduled_harvest():
    species = create_species()
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    cohort = create_cohort(species["id"], tank["id"], fish_count=1000)
    feed_cohort(cohort["id"], fed_at="2026-01-01T00:00:00Z", amount_kg=10,
                feed_type="starter")
    ho = create_scheduled_harvest_order(cohort["id"], planned_fish_count=500,
                                        scheduled_at="2026-01-05T00:00:00Z")
    return species, tank, cohort, ho


def test_freeze_cascade_suspends_cohort_and_blocks_harvest():
    """PRD §3.4: "The second hop, caused by the first, suspends every cohort
    residing in the tank that is in production ... by setting its
    operational_status to SUSPENDED and bumping that cohort's version. The third
    hop, caused by the second, blocks harvest: any harvest order on a now-suspended
    cohort that was in SCHEDULED is moved to BLOCKED (SCHEDULED -> BLOCKED),
    bumping that order's version."

    Design: Difficulty/transitive_cascade/tank_freeze_cascades_to_cohort_then_harvest_order_depth3
    """
    _species, tank, cohort, ho = _setup_growing_cohort_with_scheduled_harvest()
    record_reading(tank["id"], measured_at="2026-01-06T00:00:00Z",
                   dissolved_oxygen_mg_l=3.0, ammonia_mg_l=0.1, water_temp_c=10.0)
    tank_after = validate_success(api_client.get_tank(tank["id"], FM))
    cohort_after = validate_success(api_client.get_cohort(cohort["id"], FT))
    ho_after = validate_success(api_client.get_harvest_order(ho["id"], HO))
    assert tank_after["posture"] == "FROZEN", "hop 1: tank must be FROZEN"
    assert cohort_after["operational_status"] == "SUSPENDED", \
        "hop 2: residing cohort must be SUSPENDED"
    assert ho_after["status"] == "BLOCKED", \
        "hop 3: SCHEDULED harvest order must move to BLOCKED"


def test_freeze_cascade_originates_from_single_critical_reading():
    """PRD §3.4: "Freezing a tank fires a cascade in three hops. The first hop
    sets posture to FROZEN."
    PRD §3.4: "The third hop, caused by the second, blocks harvest: any harvest
    order on a now-suspended cohort that was in SCHEDULED is moved to BLOCKED
    (SCHEDULED -> BLOCKED), bumping that order's version."

    Design: Difficulty/transitive_cascade/tank_freeze_cascades_to_cohort_then_harvest_order_depth3
    """
    _species, tank, cohort, ho = _setup_growing_cohort_with_scheduled_harvest()
    before = validate_success(api_client.get_harvest_order(ho["id"], HO))
    assert before["status"] == "SCHEDULED"
    # one CRITICAL reading triggers the entire depth-3 chain
    record_reading(tank["id"], measured_at="2026-01-06T00:00:00Z",
                   dissolved_oxygen_mg_l=3.0, ammonia_mg_l=0.1, water_temp_c=10.0)
    ho_after = validate_success(api_client.get_harvest_order(ho["id"], HO))
    assert ho_after["status"] == "BLOCKED", \
        "single CRITICAL reading must block the scheduled harvest via the chain"


# ===========================================================================
# Rule 4 — transitive_cascade :: sales_cancel_cascades_lot_release_then_status_revert_depth2
# ===========================================================================
def test_sales_cancel_releases_reservation_and_reverts_lot_to_available():
    """PRD §3.10: "the second hop, caused by the first, releases each line's
    reserved weight by decreasing the referenced lot's reserved_weight_kg by the
    line's weight_kg and recomputing the lot's available_weight_kg upward; and a
    further effect of that release is that any lot whose status was DEPLETED and
    now has available_weight_kg greater than zero reverts DEPLETED -> AVAILABLE."

    Design: Difficulty/transitive_cascade/sales_cancel_cascades_lot_release_then_status_revert_depth2
    """
    lot_id, order_id = setup_confirmed_order_on_lot(
        lot_total_kg=50.0, line_weight_kg=50.0, price_per_kg=10.0)
    before = get_lot(lot_id)
    assert before["available_weight_kg"] == pytest.approx(0.00, abs=0.01)
    assert before["status"] == "DEPLETED"
    get_success_data(api_client.cancel_sales_order(order_id, SA))
    after = get_lot(lot_id)
    assert after["reserved_weight_kg"] == pytest.approx(0.00, abs=0.01), \
        f"reserved must release to 0, got {after['reserved_weight_kg']}"
    assert after["available_weight_kg"] == pytest.approx(50.00, abs=0.01), \
        f"available must recover to 50, got {after['available_weight_kg']}"
    assert after["status"] == "AVAILABLE", \
        f"lot must revert DEPLETED -> AVAILABLE, got {after['status']}"


def test_lot_deplete_then_release_is_depth2_from_sales_trigger():
    """PRD §3.10: "Cancelling a confirmed order (CONFIRMED -> CANCELLED) is a
    compensation cascade: the first hop sets the order's status to CANCELLED."
    PRD §3.10: "any lot whose status was DEPLETED and now has available_weight_kg
    greater than zero reverts DEPLETED -> AVAILABLE."

    Design: Difficulty/transitive_cascade/sales_cancel_cascades_lot_release_then_status_revert_depth2
    """
    lot_id, order_id = setup_confirmed_order_on_lot(
        lot_total_kg=50.0, line_weight_kg=50.0, price_per_kg=10.0)
    cancelled = validate_success(api_client.cancel_sales_order(order_id, SA))
    assert cancelled["status"] == "CANCELLED", "hop 1: order must be CANCELLED"
    after = get_lot(lot_id)
    assert after["status"] == "AVAILABLE", \
        "hop 2: released lot must revert to AVAILABLE"


# ===========================================================================
# Rule 6 — boundary_precision_check :: lot_depletes_at_exactly_zero_available
# ===========================================================================
def test_reserving_all_weight_depletes_lot_at_exactly_zero():
    """PRD §3.10: "if a lot's available_weight_kg reaches exactly 0 the lot
    transitions AVAILABLE -> DEPLETED."
    PRD §3.10: "The lot's status is AVAILABLE while its available_weight_kg is
    greater than zero and DEPLETED when its available_weight_kg reaches exactly 0."

    Design: Difficulty/boundary_precision_check/lot_depletes_at_exactly_zero_available
    """
    lot, _species, _tank = create_product_lot(40.0, price_per_kg=10.0)
    order = create_sales_order(discount_tier="NONE")
    add_line(order["id"], lot["id"], 40.0)
    lot_now = get_lot(lot["id"])
    get_success_data(
        api_client.confirm_sales_order(
            order["id"], {"expected_lot_version": lot_now["version"]}, SA
        )
    )
    after = get_lot(lot["id"])
    assert after["available_weight_kg"] == pytest.approx(0.00, abs=0.01), \
        f"available must hit exactly 0.00, got {after['available_weight_kg']}"
    assert after["status"] == "DEPLETED", \
        f"lot must be DEPLETED at zero available, got {after['status']}"


def test_full_reservation_records_reserved_weight_at_zero_boundary():
    """PRD §3.10: "for each line the referenced lot's reserved_weight_kg is
    increased by the line's weight_kg, the lot's available_weight_kg is recomputed,
    and if a lot's available_weight_kg reaches exactly 0 the lot transitions
    AVAILABLE -> DEPLETED."

    Design: Difficulty/boundary_precision_check/lot_depletes_at_exactly_zero_available
    """
    lot, _species, _tank = create_product_lot(40.0, price_per_kg=10.0)
    order = create_sales_order(discount_tier="NONE")
    add_line(order["id"], lot["id"], 40.0)
    lot_now = get_lot(lot["id"])
    get_success_data(
        api_client.confirm_sales_order(
            order["id"], {"expected_lot_version": lot_now["version"]}, SA
        )
    )
    after = get_lot(lot["id"])
    assert after["reserved_weight_kg"] == pytest.approx(40.00, abs=0.01), \
        f"reserved must equal full 40.00, got {after['reserved_weight_kg']}"


# ===========================================================================
# Rule 7 — cross_entity_state_dependency :: harvest_schedule_depends_on_cohort_health
# ===========================================================================
def test_harvest_schedule_rejected_while_cohort_under_treatment():
    """PRD §3.7: "Scheduling or starting a harvest is forbidden while the cohort's
    health_status is anything other than HEALTHY, or while the current clock is
    earlier than the cohort's withdrawal_until; such an attempt is rejected with
    ERR_WITHDRAWAL_ACTIVE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/harvest_schedule_depends_on_cohort_health
    """
    _species, _tank, cohort, _tx = setup_cohort_under_treatment(
        duration_days=5, withdrawal_days=10)
    ho = get_success_data(
        api_client.create_harvest_order(
            create_harvest_order_payload(cohort["id"], planned_fish_count=500,
                                         scheduled_at="2026-01-05T00:00:00Z"),
            HO,
        )
    )
    resp = api_client.schedule_harvest_order(ho["id"], HO)
    validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_ACTIVE.value)


def test_harvest_schedule_blocked_by_health_status_not_lifecycle():
    """PRD §3.8: "Scheduling an order (DRAFT -> SCHEDULED, or BLOCKED -> SCHEDULED
    when re-scheduling after a freeze recovery) requires that the cohort's
    operational_status is ACTIVE, that its health_status is HEALTHY, that the clock
    has reached or passed the cohort's withdrawal_until (or it is null) ... A
    health or withdrawal failure is rejected with ERR_WITHDRAWAL_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/harvest_schedule_depends_on_cohort_health
    """
    _species, _tank, cohort, _tx = setup_cohort_under_treatment(
        duration_days=5, withdrawal_days=10)
    # cohort is GROWING-eligible operationally but UNDER_TREATMENT -> blocked
    ho = get_success_data(
        api_client.create_harvest_order(
            create_harvest_order_payload(cohort["id"], planned_fish_count=500,
                                         scheduled_at="2026-01-05T00:00:00Z"),
            HO,
        )
    )
    resp = api_client.schedule_harvest_order(ho["id"], HO)
    validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_ACTIVE.value)


# ===========================================================================
# Rule 7 — cross_entity_state_dependency :: stocking_depends_on_tank_posture
# ===========================================================================
def test_stocking_rejected_when_tank_restricted():
    """PRD §3.6: "Recording a stocking event requires the destination tank's
    posture to be OPEN; a stocking attempt against a tank whose posture is
    RESTRICTED or FROZEN is rejected with ERR_TANK_NOT_OPERATIONAL (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/stocking_depends_on_tank_posture
    """
    species = create_species()
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    cohort = create_cohort(species["id"], tank["id"], fish_count=100)
    drive_tank_restricted(tank["id"])
    resp = api_client.create_stocking_event(
        create_stocking_event_payload(cohort["id"], tank["id"], fish_count=100,
                                      stocked_at="2026-02-01T00:00:00Z",
                                      expected_harvest_at="2026-06-01T00:00:00Z"),
        FT,
    )
    validate_error(resp, ApiErrorId.ERR_TANK_NOT_OPERATIONAL.value)


def test_stocking_tank_posture_gate_distinct_from_health_gate():
    """PRD §2.7: "OPEN permits new stocking and feeding; RESTRICTED blocks new
    stocking but still permits feeding; FROZEN blocks all cohort operations on
    that tank."
    PRD §3.6: "a stocking attempt against a tank whose posture is RESTRICTED or
    FROZEN is rejected with ERR_TANK_NOT_OPERATIONAL (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/stocking_depends_on_tank_posture
    """
    species = create_species()
    tank = create_tank(volume_liters=100000, max_biomass_kg=100000)
    cohort = create_cohort(species["id"], tank["id"], fish_count=100)
    drive_tank_restricted(tank["id"])
    resp = api_client.create_stocking_event(
        create_stocking_event_payload(cohort["id"], tank["id"], fish_count=100,
                                      stocked_at="2026-02-01T00:00:00Z",
                                      expected_harvest_at="2026-06-01T00:00:00Z"),
        FT,
    )
    validate_error(resp, ApiErrorId.ERR_TANK_NOT_OPERATIONAL.value)
