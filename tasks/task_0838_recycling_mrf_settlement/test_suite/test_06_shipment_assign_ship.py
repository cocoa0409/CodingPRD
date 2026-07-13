"""Assigning bales to shipments and shipping: preconditions and boundaries."""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers.fixtures import (
    set_clock, create_municipality, create_mill, create_sort_line, create_load,
    audit_load, close_load, create_and_publish_index, create_bale, create_shipment,
    assign_bale, ship_shipment, setup_closed_load_with_bale,
)

TRADER = TEST_USERS["commodity_trader_headers"]


# --- Difficulty: ship-empty boundary (0 vs >=1 staged bale) -----------------

def test_ship_empty_shipment_rejected(api):
    """PRD §3.7: "Shipping requires at least one `STAGED` bale; an attempt to ship
    an empty shipment is rejected with `ERR_SHIPMENT_EMPTY`, and shipping is only
    allowed from `BUILDING`, else `ERR_SHIPMENT_NOT_BUILDING`."

    Design: Difficulty/boundary_precision_check/ship_empty_shipment_zero_bales_boundary
    """
    mill = create_mill(api, "OCC")
    ship = create_shipment(api, mill["id"], "OCC", 0)  # BUILDING, zero bales
    resp = api.ship_mill_shipment(ship["id"], TRADER)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_EMPTY.value)


def test_ship_with_one_staged_bale_succeeds(api):
    """PRD §3.7: "Shipping advances the shipment from `BUILDING` to `SHIPPED` and
    carries all its `STAGED` bales to `SHIPPED` with it."

    Design: Difficulty/boundary_precision_check/ship_empty_shipment_zero_bales_boundary
    """
    ctx = setup_closed_load_with_bale(api, bale_net_tons=5)
    mill = create_mill(api, "OCC")
    ship = create_shipment(api, mill["id"], "OCC", 0)
    assign_bale(api, ship["id"], ctx["bale_id"])
    ship = ship_shipment(api, ship["id"])
    assert ship["status"] == "SHIPPED"


# --- Difficulty: assignment requires source load CLOSED ----------------------

def _audited_load_with_bale_and_building_shipment(api):
    set_clock(api, "2026-03-10T00:00:00Z")
    muni = create_municipality(api, revenue_share_pct=0.50)
    mill = create_mill(api, "OCC")
    create_and_publish_index(api, "OCC", 8000)
    line = create_sort_line(api)
    load = create_load(api, muni["id"], line["id"], gross_tons=12, tare_tons=2)
    audit_load(api, load["id"], 3.0, [{"commodity": "OCC", "pct": 99}])
    bale = create_bale(api, load["id"], "OCC", net_tons=10, moisture_pct=0,
                       quality_grade="A")
    ship = create_shipment(api, mill["id"], "OCC", 0)
    return load, bale, ship


def test_assign_bale_of_audited_load_rejected(api):
    """PRD §3.7: "and the bale's source load must already be `CLOSED`, or
    `ERR_BALE_LOAD_NOT_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/assign_requires_source_load_closed
    """
    load, bale, ship = _audited_load_with_bale_and_building_shipment(api)
    resp = api.assign_bale_to_shipment(ship["id"], {"bale_id": bale["id"]}, TRADER)
    validate_error(resp, ApiErrorId.ERR_BALE_LOAD_NOT_CLOSED.value)


def test_assign_bale_after_load_closed_succeeds(api):
    """PRD §3.7: "On success the bale's `shipment_id` is set, the bale becomes
    `STAGED`, and the shipment's `total_net_tons` — the sum of `net_tons` over its
    assigned, non-`VOIDED` bales — is recomputed."

    Design: Difficulty/cross_entity_state_dependency/assign_requires_source_load_closed
    """
    load, bale, ship = _audited_load_with_bale_and_building_shipment(api)
    close_load(api, load["id"], residual_tons=0)
    assign_bale(api, ship["id"], bale["id"])
    staged = validate_success(api.get_bale(bale["id"], TRADER))
    assert staged["status"] == "STAGED"


# --- Corner: commodity mismatch at assignment -------------------------------

def test_assign_commodity_mismatch_rejected(api):
    """PRD §3.7: "the bale's `commodity` must equal the shipment's `commodity`, or
    `ERR_COMMODITY_MISMATCH`".

    Design: Corner/validations/corner_assign_commodity_mismatch_rejected
    """
    ctx = setup_closed_load_with_bale(api, bale_net_tons=5)  # OCC bale
    mill = create_mill(api, "PET")
    ship = create_shipment(api, mill["id"], "PET", 0)
    resp = api.assign_bale_to_shipment(ship["id"], {"bale_id": ctx["bale_id"]}, TRADER)
    validate_error(resp, ApiErrorId.ERR_COMMODITY_MISMATCH.value)


# --- Corner: assign to an already-shipped shipment --------------------------

def test_assign_to_shipped_shipment_rejected(api):
    """PRD §3.7: "The shipment must still be `BUILDING`, or the assignment is
    refused with `ERR_SHIPMENT_NOT_BUILDING`".

    Design: Corner/errors/corner_assign_to_shipped_shipment_not_building
    """
    set_clock(api, "2026-03-10T00:00:00Z")
    muni = create_municipality(api, revenue_share_pct=0.50)
    mill = create_mill(api, "OCC")
    create_and_publish_index(api, "OCC", 8000)
    line = create_sort_line(api)
    load = create_load(api, muni["id"], line["id"], gross_tons=22, tare_tons=2)
    audit_load(api, load["id"], 3.0, [{"commodity": "OCC", "pct": 99}])
    b1 = create_bale(api, load["id"], "OCC", net_tons=5, moisture_pct=0, quality_grade="A")
    b2 = create_bale(api, load["id"], "OCC", net_tons=5, moisture_pct=0, quality_grade="A")
    close_load(api, load["id"], residual_tons=0)
    ship = create_shipment(api, mill["id"], "OCC", 0)
    assign_bale(api, ship["id"], b1["id"])
    ship_shipment(api, ship["id"])  # now SHIPPED
    resp = api.assign_bale_to_shipment(ship["id"], {"bale_id": b2["id"]}, TRADER)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_BUILDING.value)
