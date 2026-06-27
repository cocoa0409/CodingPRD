"""Composite setup helpers.

Each test runs against a freshly restarted, empty server, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints. All
setup calls go through get_success_data() (the lenient 2xx validator) so a
broken precondition surfaces as a clear "Setup failed" rather than a confusing
assertion error downstream.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_species_payload,
    create_tank_payload,
    create_broodstock_batch_payload,
    create_cohort_payload,
    create_feed_log_payload,
    create_water_quality_reading_payload,
    create_stocking_event_payload,
    create_grading_event_payload,
    create_health_treatment_payload,
    create_harvest_order_payload,
    create_processing_batch_payload,
    create_sales_order_payload,
    create_sales_order_line_payload,
)

FM = TEST_USERS["farm_manager_headers"]
FT = TEST_USERS["farm_technician_headers"]
VET = TEST_USERS["veterinarian_headers"]
HO = TEST_USERS["harvest_operator_headers"]
SA = TEST_USERS["sales_agent_headers"]


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(to_iso8601):
    """Move the logical clock; FarmManager-only."""
    return get_success_data(api_client.set_clock(to_iso8601, FM))


# ---------------------------------------------------------------------------
# Tier 1 / 2: reference data + base hierarchy
# ---------------------------------------------------------------------------
def create_species(**overrides):
    return get_success_data(api_client.create_species(create_species_payload(**overrides), FM))


def create_tank(**overrides):
    return get_success_data(api_client.create_tank(create_tank_payload(**overrides), FM))


def create_broodstock_batch(species_id, **overrides):
    return get_success_data(
        api_client.create_broodstock_batch(
            create_broodstock_batch_payload(species_id, **overrides), FM
        )
    )


def create_cohort(species_id, tank_id, **overrides):
    return get_success_data(
        api_client.create_cohort(
            create_cohort_payload(species_id, tank_id, **overrides), FT
        )
    )


def setup_species_tank_cohort(species_overrides=None, tank_overrides=None,
                              cohort_overrides=None):
    """Active OPEN tank + one STOCKED cohort of a fresh species.

    Returns (species, tank, cohort).
    """
    species = create_species(**(species_overrides or {}))
    tank = create_tank(**(tank_overrides or {}))
    cohort = create_cohort(species["id"], tank["id"], **(cohort_overrides or {}))
    return species, tank, cohort


# ---------------------------------------------------------------------------
# Water-quality posture drivers
# ---------------------------------------------------------------------------
def record_reading(tank_id, **overrides):
    """Record a water-quality reading on a tank (FarmTechnician)."""
    return get_success_data(
        api_client.create_water_quality_reading(
            tank_id, create_water_quality_reading_payload(**overrides), FT
        )
    )


def drive_tank_restricted(tank_id, measured_at="2026-01-02T00:00:00Z"):
    """Drive a tank to RESTRICTED via a WARNING reading (DO 5.0)."""
    record_reading(tank_id, measured_at=measured_at, dissolved_oxygen_mg_l=5.0,
                   ammonia_mg_l=0.1, water_temp_c=10.0)


def drive_tank_frozen(tank_id, measured_at="2026-01-02T00:00:00Z"):
    """Drive a tank to FROZEN via a CRITICAL reading (DO 3.0)."""
    record_reading(tank_id, measured_at=measured_at, dissolved_oxygen_mg_l=3.0,
                   ammonia_mg_l=0.1, water_temp_c=10.0)


# ---------------------------------------------------------------------------
# Feeding (advances lifecycle STOCKED -> GROWING on first feed)
# ---------------------------------------------------------------------------
def feed_cohort(cohort_id, **overrides):
    return get_success_data(
        api_client.create_feed_log(
            cohort_id, create_feed_log_payload(**overrides), FT
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: full harvest -> processing -> product-lot pipeline
# ---------------------------------------------------------------------------
def create_product_lot(processed_weight_kg, price_per_kg=10.0,
                       harvested_live_weight_kg=None, species=None, tank=None,
                       cohort_fish_count=1000, cohort_label="C1",
                       harvested_fish_count=1):
    """Build a ProductLot from scratch via the whole production pipeline.

    Creates (or reuses) species + tank + cohort, runs one harvest order through
    schedule -> start -> complete with the given landed weight, then runs a
    processing batch through start -> complete to mint a ProductLot.

    Returns (lot, species, tank). The lot is AVAILABLE with
    total_weight_kg == available_weight_kg == processed_weight_kg.
    """
    if harvested_live_weight_kg is None:
        harvested_live_weight_kg = max(processed_weight_kg, 1.0)
    if species is None:
        species = create_species()
    if tank is None:
        tank = create_tank()
    cohort = create_cohort(species["id"], tank["id"],
                           label=cohort_label, fish_count=cohort_fish_count)
    ho = get_success_data(
        api_client.create_harvest_order(
            create_harvest_order_payload(
                cohort["id"], planned_fish_count=harvested_fish_count,
                scheduled_at="2026-01-01T00:00:00Z",
            ), HO,
        )
    )
    get_success_data(api_client.schedule_harvest_order(ho["id"], HO))
    get_success_data(api_client.start_harvest_order(ho["id"], HO))
    get_success_data(
        api_client.complete_harvest_order(
            ho["id"],
            {"harvested_fish_count": harvested_fish_count,
             "harvested_live_weight_kg": harvested_live_weight_kg},
            HO,
        )
    )
    pb = get_success_data(
        api_client.create_processing_batch(
            create_processing_batch_payload(ho["id"]), HO
        )
    )
    get_success_data(api_client.start_processing_batch(pb["id"], HO))
    pb_done = get_success_data(
        api_client.complete_processing_batch(
            pb["id"],
            {"actual_processed_weight_kg": processed_weight_kg,
             "price_per_kg": price_per_kg},
            HO,
        )
    )
    # complete returns the ProcessingBatch; locate the minted lot by filter.
    lots, _ = _list_product_lots_by_batch(pb["id"])
    assert lots, "Setup failed: completed processing batch produced no ProductLot"
    return lots[0], species, tank


def _list_product_lots_by_batch(processing_batch_id):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_product_lots(HO, params={"processing_batch_id": processing_batch_id})
    return validate_paginated(resp)


# ---------------------------------------------------------------------------
# Tier 3: grading lifecycle
# ---------------------------------------------------------------------------
def create_planned_grading(source_cohort_id, planned_splits):
    """Create a grading event and move it to PLANNED. Returns the PLANNED event."""
    g = get_success_data(
        api_client.create_grading_event(
            create_grading_event_payload(source_cohort_id, planned_splits), FT
        )
    )
    g = get_success_data(api_client.plan_grading_event(g["id"], FT))
    return g


def setup_planned_grading_two_tanks(source_fish_count=1000, split_a=600, split_b=400):
    """Active source cohort + two OPEN target tanks + a PLANNED grading event.

    Returns (cohort, tank_a, tank_b, grading_event). The source cohort's
    version is captured on the returned cohort dict.
    """
    species = create_species()
    src_tank = create_tank(name="T1")
    tank_a = create_tank(name="T2")
    tank_b = create_tank(name="T3")
    cohort = create_cohort(species["id"], src_tank["id"], fish_count=source_fish_count)
    splits = [
        {"label": "big", "fish_count": split_a, "target_tank_id": tank_a["id"],
         "avg_weight_g": 60},
        {"label": "small", "fish_count": split_b, "target_tank_id": tank_b["id"],
         "avg_weight_g": 40},
    ]
    grading = create_planned_grading(cohort["id"], splits)
    return cohort, tank_a, tank_b, grading


# ---------------------------------------------------------------------------
# Tier 3: health treatment
# ---------------------------------------------------------------------------
def start_treatment(cohort_id, tank_id, **overrides):
    """Start a health treatment (HEALTHY -> UNDER_TREATMENT). Returns treatment."""
    return get_success_data(
        api_client.create_health_treatment(
            create_health_treatment_payload(cohort_id, tank_id, **overrides), VET
        )
    )


def setup_cohort_under_treatment(duration_days=5, withdrawal_days=10,
                                 started_at="2026-01-01T00:00:00Z"):
    """Cohort C1 driven to health_status UNDER_TREATMENT.

    Returns (species, tank, cohort, treatment).
    """
    species, tank, cohort = setup_species_tank_cohort()
    treatment = start_treatment(cohort["id"], tank["id"],
                                started_at=started_at,
                                duration_days=duration_days,
                                withdrawal_days=withdrawal_days)
    return species, tank, cohort, treatment


# ---------------------------------------------------------------------------
# Tier 3: harvest order lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_harvest_order(cohort_id, **overrides):
    return get_success_data(
        api_client.create_harvest_order(
            create_harvest_order_payload(cohort_id, **overrides), HO
        )
    )


def create_scheduled_harvest_order(cohort_id, planned_fish_count=500,
                                   scheduled_at="2026-01-05T00:00:00Z"):
    """Create a harvest order and schedule it (DRAFT -> SCHEDULED)."""
    ho = create_harvest_order(cohort_id, planned_fish_count=planned_fish_count,
                              scheduled_at=scheduled_at)
    ho = get_success_data(api_client.schedule_harvest_order(ho["id"], HO))
    return ho


# ---------------------------------------------------------------------------
# Tier 4: sales reservation chain
# ---------------------------------------------------------------------------
def create_sales_order(**overrides):
    return get_success_data(
        api_client.create_sales_order(create_sales_order_payload(**overrides), SA)
    )


def add_line(order_id, product_lot_id, weight_kg):
    return get_success_data(
        api_client.add_sales_order_line(
            order_id, create_sales_order_line_payload(product_lot_id, weight_kg), SA
        )
    )


def get_lot(lot_id):
    return get_success_data(api_client.get_product_lot(lot_id, SA))


def setup_confirmed_order_on_lot(lot_total_kg=50.0, line_weight_kg=30.0,
                                 price_per_kg=10.0, discount_tier="NONE"):
    """One ProductLot of lot_total_kg, plus a CONFIRMED order reserving
    line_weight_kg against it.

    Returns (lot_id, order_id). Re-fetch the lot via get_lot() for current state.
    """
    lot, _species, _tank = create_product_lot(lot_total_kg, price_per_kg=price_per_kg)
    order = create_sales_order(discount_tier=discount_tier)
    add_line(order["id"], lot["id"], line_weight_kg)
    lot_now = get_lot(lot["id"])
    get_success_data(
        api_client.confirm_sales_order(
            order["id"], {"expected_lot_version": lot_now["version"]}, SA
        )
    )
    return lot["id"], order["id"]


def setup_order_with_line(lot_total_kg=50.0, line_weight_kg=30.0,
                          price_per_kg=10.0, discount_tier="NONE"):
    """One ProductLot + a DRAFT order with a single line (not yet confirmed).

    Returns (lot, order). The order is DRAFT; the lot is freshly minted at
    version 1 (adding a line does not bump the lot version).
    """
    lot, _species, _tank = create_product_lot(lot_total_kg, price_per_kg=price_per_kg)
    order = create_sales_order(discount_tier=discount_tier)
    add_line(order["id"], lot["id"], line_weight_kg)
    return lot, order
