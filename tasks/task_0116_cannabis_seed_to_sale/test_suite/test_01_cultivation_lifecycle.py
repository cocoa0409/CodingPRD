"""Cultivation lifecycle: plant batches, harvest, cure, packaging, yield
reconciliation, and plant-side waste."""
from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId,
    assert_plant_batch, assert_harvest, assert_package,
    create_cultivation_license, create_flowering_batch, create_batch,
    create_cured_harvest, create_drying_harvest, create_package,
    cult_h,
)


def test_plant_batch_live_count_initialized_from_plant_count(api):
    """PRD §3.2: "The batch is created in `IMMATURE` status, and its
    `live_plant_count` is initialized to the supplied `plant_count`."

    Design: Corner/entities/plant_batch_live_count_computed_from_plant_count
    """
    cul = create_cultivation_license()
    resp = api.create_plant_batch({
        "license_id": cul["id"], "lot_tag": "LOT-CR4", "strain": "X",
        "plant_count": 12, "planted_at": "2026-01-01T00:00:00Z",
    }, cult_h())
    data = validate_success(resp, 201)
    assert_plant_batch(data)
    assert data["live_plant_count"] == 12, "live_plant_count must equal plant_count at creation"


def test_package_system_fields_server_generated(api):
    """PRD §3.4: "A new package is created in `TESTING` status with `lab_hold`
    true, its `remaining_grams` initialized to its `quantity_grams`, and its
    `thc_pct` null until a passing result exists."
    PRD §2.4: "The `version` field begins at 1 when the resource is created"

    Design: Corner/entities/package_system_fields_generated_input_ignored
    """
    cul = create_cultivation_license()
    harvest = create_cured_harvest(cul["id"], dry_weight_grams=500)
    resp = api.create_package({
        "harvest_id": harvest["id"], "package_tag": "PKG-CR5",
        "product_category": "FLOWER", "quantity_grams": 50,
    }, cult_h())
    data = validate_success(resp, 201)
    assert_package(data)
    assert data["version"] == 1, "new package version must be 1"
    assert data["status"] == "TESTING"
    assert data["lab_hold"] is True
    assert data["remaining_grams"] == 50


def test_advance_harvested_batch_rejected(api):
    """PRD §3.2: "An advance attempted from a state that is not the legal
    predecessor is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/advance_harvested_batch_rejected
    """
    cul = create_cultivation_license()
    batch = create_flowering_batch(cul["id"])
    # Harvest flips the batch FLOWERING -> HARVESTED.
    api_client.create_harvest({
        "plant_batch_id": batch["id"], "harvest_name": "H-S1",
        "wet_weight_grams": 1000,
    }, cult_h())
    resp = api.advance_plant_batch(batch["id"], cult_h())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_plant_batch(batch["id"], cult_h()))
    assert after["status"] == "HARVESTED", "batch must stay HARVESTED"


def test_new_manifest_starts_in_draft(api):
    """PRD §3.6: "A new manifest is born in `DRAFT` status with `version` 1. Its
    `line_count` (the number of attached lines) and `total_grams` (the sum of
    the grams across attached lines) are derived figures, both starting at 0,
    and its `departed_at` timestamp is null until departure."

    Design: Corner/state_machines/new_manifest_starts_in_draft
    """
    dist = create_cultivation_license()  # any two licenses suffice as origin/dest
    dest = create_cultivation_license()
    from test_helpers import dist_h
    resp = api.create_manifest({
        "origin_license_id": dist["id"], "destination_license_id": dest["id"],
    }, dist_h())
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT"
    assert data["line_count"] == 0
    assert data["total_grams"] == 0
    assert data["departed_at"] is None


def test_cure_drying_harvest_records_dry_weight(api):
    """PRD §3.3: "A drying harvest is cured by recording its `dry_weight_grams`,
    moving it from `DRYING` to `CURED`."
    PRD §3.4: "The harvest's `remaining_weight_grams` is then the harvest's
    `dry_weight_grams` minus that packaged total"

    Design: Corner/state_machines/cure_a_drying_harvest_records_dry_weight
    """
    cul = create_cultivation_license()
    harvest = create_drying_harvest(cul["id"], wet_weight_grams=1000)
    resp = api.cure_harvest(harvest["id"], {"dry_weight_grams": 700}, cult_h())
    data = validate_success(resp)
    assert_harvest(data)
    assert data["status"] == "CURED"
    assert data["dry_weight_grams"] == 700
    assert data["remaining_weight_grams"] == 700.0, "no packages yet => remaining == dry_weight"


def test_harvest_remaining_recomputed_after_packaging(api):
    """PRD §3.4: "The harvest's `packaged_weight_grams` is the sum, across every
    package ever pulled from that harvest, of each package's `quantity_grams`"
    PRD §3.4: "The harvest's `remaining_weight_grams` is then the harvest's
    `dry_weight_grams` minus that packaged total, with both figures rounded to 2
    decimal places using round-half-up."

    Design: Corner/calculations/harvest_remaining_after_packaging_recompute
    """
    cul = create_cultivation_license()
    harvest = create_cured_harvest(cul["id"], wet_weight_grams=1500, dry_weight_grams=1000)
    create_package(harvest["id"], quantity_grams=600, product_category="FLOWER")
    data = validate_success(api.get_harvest(harvest["id"], cult_h()))
    assert data["packaged_weight_grams"] == 600.0
    assert data["remaining_weight_grams"] == 400.0


def test_package_quantity_exceeding_harvest_remaining_rejected(api):
    """PRD §3.4: "The requested `quantity_grams` must not exceed the harvest's
    current `remaining_weight_grams`; an over-pull is rejected with
    `ERR_INSUFFICIENT_QUANTITY`."

    Design: Corner/validations/package_quantity_exceeds_harvest_remaining_rejected
    """
    cul = create_cultivation_license()
    harvest = create_cured_harvest(cul["id"], dry_weight_grams=500)
    resp = api.create_package({
        "harvest_id": harvest["id"], "package_tag": "PKG-V2",
        "product_category": "FLOWER", "quantity_grams": 600,
    }, cult_h())
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_QUANTITY.value)


def test_package_from_drying_harvest_rejected(api):
    """PRD §3.4: "Packaging is permitted only when the source harvest is in
    `CURED` status; attempting to package from a non-`CURED` harvest is rejected
    with `ERR_INVALID_PARENT_STATE`."

    Design: Corner/validations/package_from_drying_harvest_rejected_invalid_parent_state
    """
    cul = create_cultivation_license()
    harvest = create_drying_harvest(cul["id"])
    resp = api.create_package({
        "harvest_id": harvest["id"], "package_tag": "PKG-V3",
        "product_category": "FLOWER", "quantity_grams": 50,
    }, cult_h())
    validate_error(resp, ApiErrorId.ERR_INVALID_PARENT_STATE.value)


def test_cure_dry_weight_exceeding_wet_rejected(api):
    """PRD §3.3: "The supplied `dry_weight_grams` must be greater than 0 and must
    not exceed the harvest's `wet_weight_grams`; a dry weight above the wet
    weight is rejected with `ERR_WEIGHT_RANGE`."

    Design: Corner/validations/cure_dry_weight_exceeds_wet_rejected
    """
    cul = create_cultivation_license()
    harvest = create_drying_harvest(cul["id"], wet_weight_grams=1000)
    resp = api.cure_harvest(harvest["id"], {"dry_weight_grams": 1200}, cult_h())
    validate_error(resp, ApiErrorId.ERR_WEIGHT_RANGE.value)


def test_partial_plant_batch_waste_decrements_live_count(api):
    """PRD §3.2: "A partial destruction (fewer plants than are live) only
    decrements `live_plant_count` and leaves the batch in its current growing
    stage; it does not terminalize."

    Design: Corner/cross_cutting_complexity_layers/plant_batch_partial_waste_decrements_live_count
    """
    cul = create_cultivation_license()
    batch = create_batch(cul["id"], plant_count=10)
    api.create_waste_event({
        "source_type": "PLANT_BATCH", "plant_batch_id": batch["id"],
        "reason": "PEST", "destroyed_plant_count": 4,
        "destroyed_at": "2026-06-21T00:00:00Z",
    }, cult_h())
    data = validate_success(api.get_plant_batch(batch["id"], cult_h()))
    assert data["live_plant_count"] == 6
    assert data["status"] == "IMMATURE", "partial destroy must not terminalize"
