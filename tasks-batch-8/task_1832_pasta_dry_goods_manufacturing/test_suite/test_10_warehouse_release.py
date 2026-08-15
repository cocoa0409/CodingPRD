"""Warehouse zones and goods release: put-away gate ordering, occupancy
balance, shelf-life fraction boundary, and the expiry lazy sweep."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_approved_recipe,
    create_gf_validated_line,
    create_line,
    create_mounted_die,
    create_zone,
    drive_run_to_completed,
    get_goods_lot,
    get_run,
    get_zone,
    put_away,
    record_and_verify_pest_inspection,
    record_and_verify_product_test,
    release_goods_lot,
    schedule_run,
    set_clock,
    setup_run_world,
    setup_stored_goods_lot,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

QAM = TEST_USERS["qa_manager_headers"]
CLERK = TEST_USERS["warehouse_clerk_headers"]


def _release_run(run):
    if run["gluten_free"]:
        record_and_verify_product_test(run["id"], "PASS")
    validate_success(api_client.quality_release_run(run["id"], QAM))


def test_zone_putaway_gate_ordering_quarantine_type_capacity(api):
    """PRD: "Put-away is a `WarehouseClerk` action naming a `zone_id`, evaluated
    with three gates in a fixed order. First, the zone's `pest_posture` must
    not be `QUARANTINED` (`ERR_ZONE_QUARANTINED`). Second, if the lot is
    gluten-free the zone's `zone_type` must be `GLUTEN_FREE`
    (`ERR_ZONE_TYPE_MISMATCH`). Third, the zone's `occupied_pallets` plus the
    incoming lot's `pallet_count` must not exceed `capacity_pallets` —
    equality is allowed — else `ERR_ZONE_CAPACITY_EXCEEDED`."

    Design: Corner/errors/zone_putaway_gate_ordering_quarantine_type_capacity
    """
    world = setup_run_world(
        contract_code="C-ZG", lot_weight_kg=5000.0, with_die=False,
        recipe_overrides={"recipe_name": "Penne ZG"},
    )
    lot = world["lot"]
    r_norm = world["recipe"]
    r_gf = create_approved_recipe(recipe_name="GF ZG", shape_family="SHORT_CUT",
                                  gluten_free=True)

    line_a = create_line("L-ZA")
    create_mounted_die(line_a["id"], "D-ZA", "LONG_CUT", 100000.0)
    line_b = create_gf_validated_line("L-ZB")
    create_mounted_die(line_b["id"], "D-ZB", "SHORT_CUT", 100000.0)

    run_a = schedule_run(r_norm["id"], line_a["id"], lot["id"], 300.0)
    run_b = schedule_run(r_gf["id"], line_b["id"], lot["id"], 300.0)
    goods_a = drive_run_to_completed(run_a, 100.0)
    goods_b = drive_run_to_completed(run_b, 100.0)
    _release_run(get_run(run_a["id"]))
    _release_run(get_run(run_b["id"]))

    set_clock("2026-08-12T01:00:00Z")
    run_c = schedule_run(r_norm["id"], line_a["id"], lot["id"], 300.0,
                         scheduled_start="2026-08-12T01:00:00Z",
                         scheduled_end="2026-08-13T00:00:00Z")
    goods_c = drive_run_to_completed(run_c, 100.0,
                                     mix_clock="2026-08-12T01:00:00Z",
                                     finish_clock="2026-08-12T19:00:00Z")
    _release_run(get_run(run_c["id"]))

    zq = create_zone("ZQ", "CONVENTIONAL", 5)
    record_and_verify_pest_inspection(zq["id"], "CRITICAL", notes="infestation")
    assert get_zone(zq["id"])["pest_posture"] == "QUARANTINED"
    zc = create_zone("ZC", "CONVENTIONAL", 1)
    zg = create_zone("ZG", "GLUTEN_FREE", 1)

    resp1 = api.put_away_lot(goods_a["id"], {"zone_id": zq["id"]}, CLERK)
    validate_error(resp1, ApiErrorId.ERR_ZONE_QUARANTINED)

    resp2 = api.put_away_lot(goods_b["id"], {"zone_id": zc["id"]}, CLERK)
    validate_error(resp2, ApiErrorId.ERR_ZONE_TYPE_MISMATCH)

    stored_a = put_away(goods_a["id"], zc["id"])
    assert stored_a["status"] == "STORED"
    assert get_zone(zc["id"])["occupied_pallets"] == 1, "1 == capacity: equality admitted"

    resp3 = api.put_away_lot(goods_c["id"], {"zone_id": zc["id"]}, CLERK)
    validate_error(resp3, ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED)

    stored_b = put_away(goods_b["id"], zg["id"])
    assert stored_b["status"] == "STORED", "GF lot into GLUTEN_FREE zone"


class TestZonePalletOccupancyBalance:
    def test_putaway_then_release_returns_occupancy_to_zero(self, api):
        """PRD: "Success moves the lot from `CREATED` to `STORED`, sets its
        `zone_id`, and adds its pallets to the zone's occupancy."
        PRD: "Release moves the lot to `RELEASED` and removes its pallets from
        the zone's occupancy."

        Design: Difficulty/compensating_invariant/zone_pallet_occupancy_putaway_release_balance
        """
        sc = setup_stored_goods_lot(contract_code="C-ZIB", lot_weight_kg=3000.0,
                                    planned_input_kg=2000.0, actual_yield_kg=1001.0,
                                    zone_name="Z-INV", capacity_pallets=10,
                                    quality_release=True)
        zone = sc["zone"]
        mid = get_zone(zone["id"])
        assert mid["occupied_pallets"] == 3, "put-away adds pallet_count"

        lot = release_goods_lot(sc["goods_lot"]["id"])
        assert lot["status"] == "RELEASED"
        end = get_zone(zone["id"])
        assert end["occupied_pallets"] == 0, "release compensates exactly"

    def test_two_lots_aggregate_then_partial_release(self, api):
        """PRD: "it is the sum of `pallet_count` over the zone's finished-goods
        lots in `STORED`"
        PRD: "Release moves the lot to `RELEASED` and removes its pallets from
        the zone's occupancy."

        Design: Difficulty/compensating_invariant/zone_pallet_occupancy_putaway_release_balance
        """
        world = setup_run_world(contract_code="C-ZIB2", lot_weight_kg=5000.0,
                                die_code="D-ZIB1")
        line2 = create_line("L-ZIB2")
        create_mounted_die(line2["id"], "D-ZIB2", "LONG_CUT", 100000.0)
        run_a = schedule_run(world["recipe"]["id"], world["line"]["id"],
                             world["lot"]["id"], 2000.0)
        run_b = schedule_run(world["recipe"]["id"], line2["id"],
                             world["lot"]["id"], 2000.0)
        goods_a = drive_run_to_completed(run_a, 1001.0)
        goods_b = drive_run_to_completed(run_b, 1001.0)
        _release_run(get_run(run_a["id"]))
        _release_run(get_run(run_b["id"]))

        zone = create_zone("Z-AGG", "CONVENTIONAL", 10)
        put_away(goods_a["id"], zone["id"])
        assert get_zone(zone["id"])["occupied_pallets"] == 3
        put_away(goods_b["id"], zone["id"])
        assert get_zone(zone["id"])["occupied_pallets"] == 6, "aggregate over STORED lots"

        release_goods_lot(goods_a["id"])
        assert get_zone(zone["id"])["occupied_pallets"] == 3


def _two_pl_lots_stored():
    """PRIVATE_LABEL recipe (shelf 100, min 0.75); two runs COMPLETED on
    2026-08-10, released, goods lots stored in one zone."""
    world = setup_run_world(
        contract_code="C-SLF", lot_weight_kg=3000.0, with_die=False,
        recipe_overrides={
            "recipe_name": "Acme Penne", "brand_type": "PRIVATE_LABEL",
            "customer_name": "Acme Retail", "shelf_life_days": 100,
            "min_remaining_shelf_life_pct": 0.75,
        },
    )
    line1 = create_line("L-SL1")
    create_mounted_die(line1["id"], "D-SL1", "LONG_CUT", 100000.0)
    line2 = create_line("L-SL2")
    create_mounted_die(line2["id"], "D-SL2", "LONG_CUT", 100000.0)
    run_a = schedule_run(world["recipe"]["id"], line1["id"], world["lot"]["id"], 500.0)
    run_b = schedule_run(world["recipe"]["id"], line2["id"], world["lot"]["id"], 500.0)
    goods_a = drive_run_to_completed(run_a, 400.0, private_label=True)
    goods_b = drive_run_to_completed(run_b, 400.0, private_label=True)
    _release_run(get_run(run_a["id"]))
    _release_run(get_run(run_b["id"]))
    zone = create_zone("Z-SL", "CONVENTIONAL", 10)
    put_away(goods_a["id"], zone["id"])
    put_away(goods_b["id"], zone["id"])
    return goods_a, goods_b


def test_shelf_life_private_label_fraction_boundary(api):
    """PRD: "for a private-label lot, the remaining shelf life must satisfy the
    recipe's minimum: the days from the current date to `expiry_date`, divided
    by the recipe's `shelf_life_days`, must be at least
    `min_remaining_shelf_life_pct`, with the inclusive boundary passing
    (`ERR_SHELF_LIFE_INSUFFICIENT`)"

    Design: Corner/validations/shelf_life_private_label_fraction_boundary
    """
    goods_a, goods_b = _two_pl_lots_stored()
    assert goods_a["production_date"] == "2026-08-10"
    assert goods_a["expiry_date"] == "2026-11-18", "production_date + 100 days"

    set_clock("2026-09-04T00:00:00Z")
    released = release_goods_lot(goods_a["id"])
    assert released["status"] == "RELEASED", "75/100 == 0.75 inclusive boundary passes"

    set_clock("2026-09-05T00:00:00Z")
    resp = api.release_goods_lot(goods_b["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_SHELF_LIFE_INSUFFICIENT)
    assert get_goods_lot(goods_b["id"])["status"] == "STORED", "unchanged"


def _two_branded_lots_stored_short_shelf():
    """BRANDED recipe shelf 30; two runs COMPLETED 2026-08-10, released, lots
    stored in one zone (1 pallet each)."""
    world = setup_run_world(
        contract_code="C-EXP", lot_weight_kg=3000.0, with_die=False,
        recipe_overrides={"recipe_name": "Penne EXP", "shelf_life_days": 30},
    )
    line1 = create_line("L-EX1")
    create_mounted_die(line1["id"], "D-EX1", "LONG_CUT", 100000.0)
    line2 = create_line("L-EX2")
    create_mounted_die(line2["id"], "D-EX2", "LONG_CUT", 100000.0)
    run_a = schedule_run(world["recipe"]["id"], line1["id"], world["lot"]["id"], 500.0)
    run_b = schedule_run(world["recipe"]["id"], line2["id"], world["lot"]["id"], 500.0)
    goods_a = drive_run_to_completed(run_a, 400.0)
    goods_b = drive_run_to_completed(run_b, 400.0)
    _release_run(get_run(run_a["id"]))
    _release_run(get_run(run_b["id"]))
    zone = create_zone("Z-EX", "CONVENTIONAL", 10)
    put_away(goods_a["id"], zone["id"])
    put_away(goods_b["id"], zone["id"])
    return goods_a, goods_b, zone


def test_expiry_date_inclusive_release_then_lazy_sweep(api):
    """PRD: "the current clock date must not be later than the lot's
    `expiry_date` — release on the expiry date itself is allowed — else
    `ERR_LOT_EXPIRED`"
    PRD: "a release attempted on a still-`STORED` lot whose expiry has passed
    fails with `ERR_LOT_EXPIRED`, while the same release attempted after a read
    has already swept the lot fails with `ERR_INVALID_STATE`, because the lot
    is by then in `EXPIRED`."
    PRD: "The lazy expiry sweep of §2.5 moves a `STORED` lot past its expiry
    date to `EXPIRED` on read, also freeing its pallets."

    Design: Corner/validations/expiry_date_inclusive_release_then_lazy_sweep
    """
    goods_a, goods_b, zone = _two_branded_lots_stored_short_shelf()
    assert goods_a["expiry_date"] == "2026-09-09", "2026-08-10 + 30 days"

    set_clock("2026-09-09T00:00:00Z")
    released = release_goods_lot(goods_a["id"])
    assert released["status"] == "RELEASED", "release on the expiry date itself is allowed"

    set_clock("2026-09-10T00:00:00Z")
    resp1 = api.release_goods_lot(goods_b["id"], CLERK)
    validate_error(resp1, ApiErrorId.ERR_LOT_EXPIRED)

    swept = get_goods_lot(goods_b["id"])
    assert swept["status"] == "EXPIRED", "lazy sweep on GET"
    assert get_zone(zone["id"])["occupied_pallets"] == 0, "sweep frees the pallets"

    resp2 = api.release_goods_lot(goods_b["id"], CLERK)
    validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)
