"""Entity creation, defaults, uniqueness, listing, lineage, and FK
reverse-reachability reads.

Covers unit creation contract, not-found, missing required field, engine_hours
default, duplicate serial/sku, invalid enum, paginated listing, the
trade-in-to-unit self-referential lineage, system-managed fields on create, and
filtered/sub-resource GET endpoints.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_unit_payload, create_customer_payload, create_part_payload,
    create_trade_in_payload, create_deal_payload, create_work_order_payload,
    create_part_line_payload, create_floor_plan_note_payload, create_auction_lot_payload,
    create_bid_payload,
    create_customer, create_unit, create_part, create_offered_trade_in,
    create_quoted_deal, fund_deal, get_unit_version, create_live_lot,
    assert_unit, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["dealer_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]
SERVICE = TEST_USERS["service_advisor_headers"]
PARTS = TEST_USERS["parts_clerk_headers"]
AUCTION = TEST_USERS["auction_clerk_headers"]


# ─── Unit creation contract (Corner/entities) ────────────────────────────────

def test_create_unit_returns_201_with_all_fields(api):
    """PRD §3.1: "A newly created unit begins life `AVAILABLE`."
    PRD §2.4: "an integer `version` that begins at 1 and increments by one with
    each mutation of the resource."
    PRD §3.1: "The `floor_planned` boolean reads `true` exactly while an `ACTIVE`
    floor-plan note references the unit and defaults to `false`."

    Design: Corner/entities/create_unit_returns_201_with_all_fields
    """
    created = validate_success(api.create_unit(create_unit_payload(
        condition="NEW", model_code="5045E", dealer_cost_cents=3000000,
        list_price_cents=4000000), ADMIN), 201)
    assert_unit(created)
    assert created["status"] == "AVAILABLE"
    assert created["version"] == 1
    assert created["floor_planned"] is False


def test_get_unit_not_found_returns_404(api):
    """PRD §2.6: "the first identifier that does not correspond to an existing
    resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404)
    before any later identifier or business rule is evaluated."

    Design: Corner/entities/get_unit_not_found_returns_404
    """
    validate_error(api.get_unit(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_NOT_FOUND.value)


def test_create_unit_missing_serial_number_rejected(api):
    """PRD §3.9: "Request well-formedness is checked fourth: required input fields
    must be present and well-typed, every enum value must lie within its declared
    set, and numeric constraints ... must hold — a violation yields
    `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_unit_missing_required_field_returns_invalid_request
    """
    payload = {
        "stock_number": "S-MR-1", "condition": "NEW", "model_code": "5045E",
        "dealer_cost_cents": 3000000, "list_price_cents": 4000000,
    }
    validate_error(api.create_unit(payload, ADMIN), ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_unit_default_engine_hours_zero(api):
    """PRD §3.1: "an optional `engine_hours` meter reading may be supplied and
    defaults to 0 (it should be 0 for `NEW` units)."

    Design: Corner/entities/create_unit_default_engine_hours_zero
    """
    payload = create_unit_payload(condition="NEW", model_code="5045E",
                                  dealer_cost_cents=3000000, list_price_cents=4000000)
    payload.pop("engine_hours", None)
    created = validate_success(api.create_unit(payload, ADMIN), 201)
    assert created["engine_hours"] == 0


def test_duplicate_serial_number_returns_duplicate_key(api):
    """PRD §3.1: "the `serial_number` must be unique across all units; an attempt to
    create a unit whose stock number or serial number collides with an existing one
    is rejected with `ERR_DUPLICATE_KEY` (HTTP 409)."

    Design: Corner/entities/duplicate_serial_number_returns_duplicate_key
    """
    validate_success(api.create_unit(create_unit_payload(
        stock_number="S-DK-1", serial_number="SN-DUP", condition="NEW", model_code="5045E",
        dealer_cost_cents=3000000, list_price_cents=4000000), ADMIN), 201)
    validate_error(api.create_unit(create_unit_payload(
        stock_number="S-DK-2", serial_number="SN-DUP", condition="NEW", model_code="5045E",
        dealer_cost_cents=3100000, list_price_cents=4100000), ADMIN),
        ApiErrorId.ERR_DUPLICATE_KEY.value)


def test_create_unit_invalid_condition_enum_rejected(api):
    """PRD §3.9: "every enum value must lie within its declared set ... a violation
    yields `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_unit_invalid_enum_condition_returns_invalid_request
    """
    validate_error(api.create_unit(create_unit_payload(
        condition="REFURB", model_code="5045E", dealer_cost_cents=3000000,
        list_price_cents=4000000), ADMIN), ApiErrorId.ERR_INVALID_REQUEST.value)


def test_list_units_paginated_envelope(api):
    """PRD §2.3: "Every list response carries the pagination fields `limit`,
    `offset`, `total_count`, and `has_more` inside the `meta` object of the
    envelope, where `total_count` is the total number of matching resources before
    the page window is applied and `has_more` indicates whether further pages exist
    beyond the current window."

    Design: Corner/entities/list_units_paginated_envelope
    """
    create_unit(stock_number="S-LP-1", serial_number="SN-LP-1", condition="NEW")
    create_unit(stock_number="S-LP-2", serial_number="SN-LP-2", condition="USED",
                engine_hours=500)
    data, meta = validate_paginated(api.list_units(SALES, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_tradein_minted_unit_lineage(api):
    """PRD §3.1: "The `acquired_from_tradein_id` field records the lineage of a used
    unit that was minted from an accepted trade-in — it points back to the
    originating trade-in".
    PRD §3.4: "The minted unit is created with `condition` `USED`, `status`
    `AVAILABLE`, and `dealer_cost_cents` equal to the trade's `appraised_value_cents`;
    the trade's `minted_unit_id` is set to the new unit and the new unit's
    `acquired_from_tradein_id` is set back to the trade."

    Design: Corner/entities/tradein_minted_unit_acquired_from_tradein_lineage
    """
    customer = create_customer(name="Lineage Cust", customer_type="RETAIL")
    unit = create_unit(condition="NEW", model_code="8R280", dealer_cost_cents=6000000,
                       list_price_cents=8000000)
    trade = create_offered_trade_in(customer["id"], model_code="7820", engine_hours=800,
                                    condition_grade="FAIR", base_value_cents=5000000)
    deal = create_quoted_deal(unit["id"], customer["id"], deal_type="SALE",
                              sale_price_cents=8000000, tradein_id=trade["id"])
    get_success_data(api.approve_deal(deal["id"], FINANCE))
    fund_deal(deal["id"], unit["id"])
    trade_after = validate_success(api.get_trade_in(trade["id"], FINANCE), 200)
    assert trade_after["status"] == "ACCEPTED"
    minted = validate_success(api.get_unit(trade_after["minted_unit_id"], FINANCE), 200)
    assert minted["acquired_from_tradein_id"] == trade["id"]
    assert minted["condition"] == "USED"
    # appraised = round(5000000 * 0.65 * (1 - 0.08)) = 2990000.
    assert minted["dealer_cost_cents"] == 2990000


def test_create_customer_mints_id_and_version_one(api):
    """PRD §2.4: "Each such resource exposes an `id` — a server-minted UUID with no
    type prefix ... and an integer `version` that begins at 1".
    PRD §3.3: "an optional `tax_exempt` boolean (defaulting to `false`) that marks
    qualifying agricultural or government buyers."

    Design: Corner/entities/system_field_id_input_ignored_on_create
    """
    created = validate_success(api.create_customer(create_customer_payload(
        name="Sys Cust", customer_type="GOVERNMENT", tax_exempt=True), ADMIN), 201)
    assert created["version"] == 1
    assert created["tax_exempt"] is True


# ─── FK reverse-reachability reads (Corner/state_machines & endpoints) ───────

def test_list_floor_plan_notes_filtered_by_unit(api):
    """PRD §4: "GET `/floor-plan-notes` List floor-plan notes (filter by unit_id,
    status)".

    Design: Corner/state_machines/list_unit_floorplan_notes_via_filtered_get
    """
    unit = create_unit(condition="NEW", model_code="8R250", dealer_cost_cents=6000000,
                       list_price_cents=8000000)
    note = get_success_data(api.create_floor_plan_note(create_floor_plan_note_payload(
        unit["id"], principal_cents=6000000, annual_rate_bps=800), FINANCE))
    data, _ = validate_paginated(api.list_floor_plan_notes(FINANCE, params={"unit_id": unit["id"]}))
    assert any(n["id"] == note["id"] for n in data)


def test_work_order_part_lines_reverse_reachable(api):
    """PRD §4: "GET `/work-orders/{id}/part-lines` List part lines on a work order".

    Design: Corner/endpoints/work_order_part_lines_reverse_reachable
    """
    customer = create_customer(name="RV Cust", customer_type="RETAIL")
    unit = create_unit(condition="USED", model_code="5095E", engine_hours=900)
    part = create_part(sku="GSK-1", description="gasket", category="MECHANICAL",
                       unit_price_cents=5000, on_hand_qty=20)
    wo = get_success_data(api.create_work_order(create_work_order_payload(
        unit["id"], customer["id"], complaint="leak", labor_rate_cents=13000,
        flat_rate_hours=1.0), SERVICE))
    pl = get_success_data(api.add_part_line(wo["id"], create_part_line_payload(part["id"], 1), PARTS))
    data, _ = validate_paginated(api.list_wo_part_lines(wo["id"], SERVICE))
    assert any(p["id"] == pl["id"] for p in data)


def test_list_bids_filtered_by_lot(api):
    """PRD §4: "GET `/bids` List bids (filter by lot_id, bidder_customer_id)".

    Design: Corner/endpoints/list_bids_filtered_by_lot_reverse_reachable
    """
    bidder = create_customer(name="BL Cust", customer_type="COMMERCIAL_AG")
    _, lot = create_live_lot(
        unit_overrides={"model_code": "S770", "engine_hours": 2000},
        lot_overrides={"reserve_price_cents": 4000000, "closes_at": "2026-06-01T00:00:00Z"},
    )
    get_success_data(api.place_bid(lot["id"], create_bid_payload(bidder["id"], 4200000), AUCTION))
    data, meta = validate_paginated(api.list_bids(AUCTION, params={"lot_id": lot["id"]}))
    assert meta["total_count"] == 1
    assert len(data) == 1
