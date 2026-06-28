"""Entity creation defaults, listing/pagination, action endpoints, RBAC, and
cross-cutting layers (FEFO selector, OCC happy path, hazmat force-carrier, storage).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    build_user_headers,
    create_client,
    create_sku,
    create_bin,
    create_order,
    order_line,
    stock_client_sku_bin,
    setup_packed_order,
    setup_lot_with_version,
    putaway_units,
    lot_for,
    get_bin,
    assert_client,
    assert_bin,
    assert_billing_charge,
    assert_appendonly_no_audit_fields,
    make_client_user_headers,
    TEST_USERS,
)

BILLING = TEST_USERS["billing_clerk_headers"]
RECEIVING = TEST_USERS["receiving_clerk_headers"]
WAVE = TEST_USERS["wave_planner_headers"]
SHIP = TEST_USERS["ship_station_headers"]
PICK = TEST_USERS["pick_operator_headers"]


# --- entities ---

def test_create_client_defaults_and_zero_balances(api):
    """PRD §3.1: "plus three optional rate fields that each default to 0 when
    omitted".
    PRD §3.1: "A newly created client starts with `status` set to `ACTIVE`, and
    both `storage_balance_cents` and `handling_balance_cents` initialised to 0."
    PRD §2.4: "`version`, an integer that begins at 1 when the resource is created".

    Design: Corner/entities/create_client_returns_201_with_defaults_and_zero_balances
    """
    resp = api.create_client(
        {"name": "Acme3PL", "storage_rate_per_pallet_cents": 1000, "handling_rate_per_order_cents": 500},
        BILLING,
    )
    data = validate_success(resp, expected_status=201)
    assert_client(data)
    assert data["status"] == "ACTIVE"
    assert data["storage_balance_cents"] == 0
    assert data["handling_balance_cents"] == 0
    assert data["handling_rate_per_extra_unit_cents"] == 0
    assert data["handling_surcharge_per_extra_carton_cents"] == 0
    assert data["carrier_discount_bps"] == 0
    assert data["version"] == 1


def test_create_bin_computed_occupied_cc_and_open_status(api):
    """PRD §3.2: "On creation a bin's `status` is `OPEN` and its `occupied_cc` is 0."
    PRD §2.4: "`version`, an integer that begins at 1 when the resource is created".

    Design: Corner/entities/get_bin_returns_computed_occupied_cc_and_system_fields
    """
    created = validate_success(
        api.create_bin({"location_code": "G-CORNER-01", "bin_type": "GENERAL", "capacity_cc": 50000}, RECEIVING),
        expected_status=201,
    )
    fetched = validate_success(api.get_bin(created["id"], RECEIVING))
    assert_bin(fetched)
    assert fetched["occupied_cc"] == 0
    assert fetched["status"] == "OPEN"
    assert fetched["capacity_cc"] == 50000
    assert fetched["version"] == 1


def test_get_nonexistent_client_returns_not_found(api):
    """PRD §2.5: "Path identifiers are validated left to right: the `clientId` is
    resolved first, and if no such client exists the request fails with
    `ERR_CLIENT_NOT_FOUND` before any nested identifier is examined."

    Design: Corner/entities/get_client_nonexistent_id_returns_client_not_found
    """
    resp = api.get_client("00000000-0000-4000-8000-000000000000", BILLING)
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_FOUND.value)


def test_billing_charge_is_append_only_no_audit_fields(api):
    """PRD §2.4: "A `BillingCharge` is an append-only ledger event: it carries only
    `id` and `created_at`. It has no `updated_at` and no `version`, because a
    billing charge, once posted, is never modified — there is no reversal entry and
    no in-place edit."

    Design: Corner/entities/billing_charge_is_immutable_event_only_id_and_created_at
    """
    client = create_client()
    sku = create_sku(client["id"], unit_volume_cc=400)
    pallet = create_bin(bin_type="PALLET", capacity_cc=100000)
    putaway_units(client["id"], sku["id"], pallet["id"], 4)

    charge = validate_success(api.accrue_storage(client["id"], {"days": 1}, BILLING), expected_status=201)
    fetched = validate_success(api.get_billing_charge(charge["id"], BILLING))
    assert_billing_charge(fetched)
    assert fetched["posted"] is True
    assert fetched["charge_type"] == "STORAGE"
    assert fetched["amount_cents"] == 1000
    assert_appendonly_no_audit_fields(fetched)


def test_list_clients_pagination_envelope(api):
    """PRD §2.3: "The pagination fields surfaced in the `meta` block of a list
    response are `limit`, `offset`, `total_count` (the total number of matching
    records across all pages), and `has_more` (true when records remain beyond the
    current page)."

    Two clients; limit=1 -> array of 1, total_count 2, has_more true.

    Design: Corner/entities/list_clients_pagination_envelope_fields_present
    """
    create_client(name="PageA")
    create_client(name="PageB")
    data, meta = validate_paginated(api.list_clients(BILLING, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# --- endpoints ---

def test_suspend_client_sets_suspended(api):
    """PRD §3.1: "A client may later be suspended by a `BillingClerk`, moving its
    `status` from `ACTIVE` to `SUSPENDED`."

    Design: Corner/endpoints/suspend_client_action_endpoint_sets_suspended
    """
    client = create_client(name="ToSuspend")
    suspended = validate_success(api.suspend_client(client["id"], BILLING))
    assert suspended["status"] == "SUSPENDED"


def test_block_bin_then_putaway_rejected(api):
    """PRD §2.7: "A clerk may block a bin, moving `status` from `OPEN` to `BLOCKED`."
    PRD §2.7: "a `BLOCKED` bin rejects putaway, pick confirmation, and
    sellable-return restock with `ERR_BIN_BLOCKED` (HTTP 409)."

    Design: Corner/endpoints/block_bin_then_putaway_rejected_action_endpoint
    """
    client = create_client()
    sku = create_sku(client["id"], unit_volume_cc=400)
    b = create_bin(bin_type="GENERAL", capacity_cc=100000)
    rcpt = validate_success(
        api.create_receipt(client["id"], {"sku_id": sku["id"], "bin_id": b["id"], "expected_qty": 3}, RECEIVING),
        expected_status=201,
    )
    validate_success(api.receive_receipt(client["id"], rcpt["id"], {"received_qty": 3}, RECEIVING))
    blocked = validate_success(api.block_bin(b["id"], RECEIVING))
    assert blocked["status"] == "BLOCKED"

    resp = api.putaway_receipt(client["id"], rcpt["id"], RECEIVING)
    validate_error(resp, ApiErrorId.ERR_BIN_BLOCKED.value)
    refreshed = validate_success(api.get_client_receipt(client["id"], rcpt["id"], RECEIVING))
    assert refreshed["status"] == "RECEIVED"


# --- rbac ---

def test_client_user_cannot_create_bin(api):
    """PRD §2.1: "When the headers are present and valid but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    POST /bins is ReceivingClerk-exclusive (§4); a ClientUser is forbidden.

    Design: Corner/rbac/client_user_cannot_create_bin_peer_role_denied
    """
    client = create_client(name="RbacCo")
    resp = api.create_bin(
        {"location_code": "G-RBAC-01", "bin_type": "GENERAL", "capacity_cc": 100000},
        make_client_user_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_pick_operator_cannot_pack(api):
    """PRD §2.1: "When the headers are present and valid but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    POST .../pack is PackStation-exclusive (§4); a PickOperator is forbidden and
    the order stays PICKING.

    Design: Corner/rbac/pick_operator_cannot_pack_other_role_exclusive_denied
    """
    from test_helpers import order_in_picking
    client, sku, b = stock_client_sku_bin(unit_volume_cc=400, stock_qty=2)
    order, wave = order_in_picking(client["id"], sku["id"], 2, ship_to_zone=2)
    resp = api.pack_order(client["id"], order["id"], {"cartons": [{"packed_units": 2}]}, PICK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    refreshed = validate_success(api.get_client_order(client["id"], order["id"], BILLING))
    assert refreshed["status"] == "PICKING"


def test_unknown_role_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` does not name a
    known role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.list_clients(build_user_headers("someone", "NotARole"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# --- cross_cutting_layers ---

def test_cycle_count_correct_version_succeeds_and_bumps_version(api):
    """PRD §3.10: "the server reads the lot's `on_hand_qty` at apply time as the
    before-count baseline and records the count's `variance_qty` as the
    `counted_qty` minus that baseline; the variance may be negative."
    PRD §3.10: "Applying the correction increments the lot's `version` by one and
    recomputes the owning bin's `occupied_cc`."

    Count an 8-on-hand lot (version 1) to 6 -> variance -2, on_hand 6, version 2.

    Design: Corner/cross_cutting_layers/cycle_count_correct_version_succeeds_and_increments_version
    """
    client, sku, b, lot = setup_lot_with_version(stock_qty=8, unit_volume_cc=400)
    assert lot["version"] == 1
    cc = validate_success(
        api.create_cycle_count(
            client["id"],
            {"lot_id": lot["id"], "expected_lot_version": lot["version"], "counted_qty": 6},
            RECEIVING,
        ),
        expected_status=201,
    )
    assert cc["variance_qty"] == -2
    refreshed = validate_success(api.get_inventory_lot(lot["id"], RECEIVING))
    assert refreshed["on_hand_qty"] == 6
    assert refreshed["available_qty"] == 6
    assert refreshed["version"] == 2


def test_fefo_reserves_earliest_created_lot_first(api):
    """PRD §3.4: "which orders the client's eligible lots for that SKU by their
    `created_at` ascending and picks from the earliest; the lot's own `id` is never
    used as a tiebreak or selector input."
    PRD §3.4: "Reserving a line increases the chosen lot's `reserved_qty` by the
    line's `qty`, with the lot's `available_qty` recomputed downward by the same
    amount."

    Two lots (lot1 earlier, lot2 later) of 5 each; an order for 3 reserves all 3
    against lot1; lot2 untouched.

    Design: Corner/cross_cutting_layers/fefo_selector_picks_earliest_created_lot_first
    """
    client = create_client()
    sku = create_sku(client["id"], unit_volume_cc=400)
    bin1 = create_bin(bin_type="GENERAL", capacity_cc=100000)
    bin2 = create_bin(bin_type="GENERAL", capacity_cc=100000)
    putaway_units(client["id"], sku["id"], bin1["id"], 5)  # earlier
    putaway_units(client["id"], sku["id"], bin2["id"], 5)  # later
    lot1 = lot_for(client["id"], sku["id"], bin1["id"])
    lot2 = lot_for(client["id"], sku["id"], bin2["id"])

    order = create_order(client["id"], [order_line(sku["id"], 3)], ship_to_zone=2)
    wave = validate_success(api.create_wave(client["id"], WAVE), expected_status=201)
    validate_success(api.add_order_to_wave(client["id"], wave["id"], {"order_id": order["id"]}, WAVE))
    released = validate_success(api.release_wave(client["id"], wave["id"], WAVE))
    assert released["status"] == "RELEASED"

    refreshed_lot1 = validate_success(api.get_inventory_lot(lot1["id"], RECEIVING))
    refreshed_lot2 = validate_success(api.get_inventory_lot(lot2["id"], RECEIVING))
    assert refreshed_lot1["reserved_qty"] == 3
    assert refreshed_lot1["available_qty"] == 2
    assert refreshed_lot2["reserved_qty"] == 0
    assert refreshed_lot2["available_qty"] == 5


def test_force_ground_economy_with_hazmat_forbidden(api):
    """PRD §3.7: "A `ShipStation` may also supply an optional `force_carrier` to
    demand a specific carrier; forcing `GROUND_ECONOMY` for an order carrying any
    `hazmat` line SKU is rejected with `ERR_HAZMAT_CARRIER_FORBIDDEN` (HTTP 409),
    mirroring the eligibility exclusion."

    Design: Corner/cross_cutting_layers/hazmat_force_carrier_ground_economy_forbidden
    """
    client, sku, b, order, cartons = setup_packed_order(
        order_qty=1, carton_units=[1], ship_to_zone=2, hazmat=True, carrier_discount_bps=0,
    )
    resp = api.create_shipment(client["id"], {"order_id": order["id"], "force_carrier": "GROUND_ECONOMY"}, SHIP)
    validate_error(resp, ApiErrorId.ERR_HAZMAT_CARRIER_FORBIDDEN.value)


# --- calculations: storage ---

def test_storage_charge_counts_pallet_once_times_days(api):
    """PRD §3.11: "A qualifying pallet bin counts exactly once for the client no
    matter how many of that client's lots it holds, and a bin holding none of this
    client's units does not count. The charge `amount_cents` is the number of
    occupied pallet bins multiplied by the client's `storage_rate_per_pallet_cents`,
    multiplied again by `days`."

    One PALLET bin holding two of the client's lots counts once: 1 * 1000 * 3 = 3000.

    Design: Corner/calculations/storage_charge_counts_pallet_bin_once_per_client_times_days
    """
    client = create_client(storage_rate_per_pallet_cents=1000)
    skuA = create_sku(client["id"], unit_volume_cc=400)
    skuB = create_sku(client["id"], unit_volume_cc=400)
    pallet = create_bin(bin_type="PALLET", capacity_cc=100000)
    putaway_units(client["id"], skuA["id"], pallet["id"], 3)
    putaway_units(client["id"], skuB["id"], pallet["id"], 2)

    charge = validate_success(api.accrue_storage(client["id"], {"days": 3}, BILLING), expected_status=201)
    assert charge["amount_cents"] == 3000
    assert charge["charge_type"] == "STORAGE"
    assert charge["source_order_id"] is None

    updated_client = validate_success(api.get_client(client["id"], BILLING))
    assert updated_client["storage_balance_cents"] == 3000
