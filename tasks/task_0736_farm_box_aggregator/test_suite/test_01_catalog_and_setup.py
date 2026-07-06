"""Catalog onboarding and creation-time invariants (corner: entities section)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_admin_headers, make_farm_headers,
    create_farm_payload, create_offering_payload,
    assert_farm, assert_offering,
    set_clock, new_farm, new_hub, new_customer, new_product, new_cycle, new_offering, open_cycle,
    new_order, new_line, ABSENT_UUID,
)


def test_create_farm_returns_system_fields(api):
    """PRD §3.1: "A new farm starts with `payout_balance_cents` and `settled_cycle_count`
    both at 0; `payout_balance_cents` is the running sum of `net_payout_cents` from the
    farm's finalized settlements, and `settled_cycle_count` counts those finalized settlements."
    PRD §2.4: "`version` — an integer that begins at 1 on creation and increments by 1 on
    every mutation."

    Design: Corner/entities/create_farm_returns_system_fields
    """
    set_clock(api)
    resp = api.create_farm(create_farm_payload(), make_admin_headers())
    data = validate_success(resp, 201)
    assert_farm(data)
    assert data["version"] == 1, f"new farm version must be 1, got {data['version']}"
    assert data["payout_balance_cents"] == 0
    assert data["settled_cycle_count"] == 0


def test_get_farm_nonexistent_returns_not_found(api):
    """PRD §2.8: "the server validates the existence of each path segment from left to right
    and rejects the first missing identifier with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_farm_nonexistent_returns_not_found
    """
    set_clock(api)
    resp = api.get_farm(ABSENT_UUID, make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_product_missing_pricing_mode_invalid_request(api):
    """PRD §3.1: "Each `Product` carries the owning `farm_id`, a display `name`, a `category`
    (one of `PRODUCE`, `DAIRY`, `MEAT`, `PANTRY`, or `OTHER`), and a `pricing_mode`."
    PRD §2.10: "the request body is well-formed (`ERR_INVALID_REQUEST`): required fields
    present, enums valid, quantities at least 1, `commission_pct` within the inclusive range
    0 through 1, delivery slots present with end after start for delivery orders, weight-priced
    products carrying `price_per_kg_cents` and `estimated_weight_kg`, and fixed-price products
    carrying `unit_price_cents`."

    Design: Corner/entities/create_product_missing_pricing_mode_invalid_request
    """
    farm = new_farm(api)
    resp = api.create_product(farm["id"], {"name": "Mystery", "category": "OTHER"}, make_farm_headers(farm["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_snap_eligible_product_under_unauthorized_farm_rejected(api):
    """PRD §3.1: "A SNAP-eligible product may only be created under a farm whose `snap_authorized`
    is true; attempting to create a SNAP-eligible product under a farm that is not SNAP-authorized
    is rejected with `ERR_FARM_NOT_SNAP_AUTHORIZED`."

    Design: Corner/validations/product_snap_eligible_under_unauthorized_farm_rejected
    """
    farm = new_farm(api, name="No SNAP Farm", snap_authorized=False)
    resp = api.create_product(
        farm["id"],
        {"name": "Kale", "category": "PRODUCE", "pricing_mode": "FIXED",
         "unit_price_cents": 300, "snap_eligible": True},
        make_farm_headers(farm["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FARM_NOT_SNAP_AUTHORIZED.value, 422)


def test_offering_remaining_qty_computed_on_create(api):
    """PRD §3.3: "A new offering starts with `reserved_qty` and `committed_qty` at 0 and
    `remaining_qty` equal to `offered_qty`."

    Design: Corner/entities/offering_remaining_qty_computed_on_create
    """
    farm = new_farm(api)
    product = new_product(api, farm["id"])
    cycle = new_cycle(api)
    resp = api.create_offering(
        cycle["id"], create_offering_payload(product["id"], offered_qty=100), make_farm_headers(farm["id"])
    )
    data = validate_success(resp, 201)
    assert_offering(data)
    assert data["remaining_qty"] == 100
    assert data["reserved_qty"] == 0
    assert data["committed_qty"] == 0


def test_line_pricing_fixed_mode_computed_and_snap_copied(api):
    """PRD §3.5: "For a `FIXED` product, `estimated_line_cents` is the `requested_qty`
    multiplied by the effective per-unit price."
    PRD §3.5: "When the line is accepted it starts in `line_status` `REQUESTED`, its
    `snap_eligible` flag is copied from the offering's product `snap_eligible`, its offering's
    `reserved_qty` grows by the requested units (and `remaining_qty` is recomputed), and its
    `estimated_line_cents` is computed by the estimated pricing rule below."

    Design: Corner/entities/line_pricing_fixed_mode_computed
    """
    set_clock(api)
    farm = new_farm(api)
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=0)
    product = new_product(api, farm["id"], name="Eggs", category="DAIRY",
                          pricing_mode="FIXED", unit_price_cents=400, snap_eligible=False)
    cycle = new_cycle(api)
    offering = new_offering(api, cycle["id"], farm["id"], product["id"], offered_qty=100)
    open_cycle(api, cycle["id"])
    order = new_order(api, customer["id"], cycle["id"], hub["id"])

    line = new_line(api, customer["id"], order["id"], offering["id"], 2)
    assert line["estimated_line_cents"] == 800, "2 units * 400 cents == 800"
    assert line["snap_eligible"] is False, "snap_eligible copied from a non-eligible product"
    assert line["line_status"] == "REQUESTED"
