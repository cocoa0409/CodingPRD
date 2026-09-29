"""
The resource layer itself: the envelope a create returns, the row a read echoes
back, the way a filter and a page window compose, what an omitted optional field
becomes, and which two resources are published once and never versioned.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U

MISSING_ID = "00000000-0000-4000-8000-000000000000"


def test_registering_a_room_returns_the_declared_envelope_and_the_opening_posture(api, clock):
    """
    The creation reply is a full envelope — a prefixed request identifier, a
    timestamp, an object response type — and the room opens in specification
    with nothing occupying it and its reported climate standing at its own
    target until the first sample arrives.

    PRD: "A newly registered room starts with `climate_status` of `IN_SPEC`,
    `occupied_slots` of zero, `out_of_spec_since` null, and `latest_rh_pct` and
    `latest_temp_c` reporting the room's own `target_rh_pct` and `target_temp_c`
    until the first hygrometer sample is logged."

    Design: Corner/entities/create_storage_room_returns_201_with_the_declared_envelope
    """
    response = api.create_storage_room(dict(C.DRY_STORE_1), U.PLANT_ADMIN_HEADERS)
    assert response.status_code == 201
    body = response.json()
    A.assert_envelope_meta(body)
    assert body["response_type"] == "object"

    room = body["data"]
    A.assert_system_fields(room)
    assert room["room_code"] == "DRY-1"
    assert room["room_type"] == "DRY_STORE"
    assert room["target_rh_pct"] == 45.0
    assert room["target_temp_c"] == 21.0
    assert room["capacity_slots"] == 20
    assert room["climate_status"] == "IN_SPEC"
    assert room["occupied_slots"] == 0
    assert room["out_of_spec_since"] is None
    assert room["latest_rh_pct"] == 45.0
    assert room["latest_temp_c"] == 21.0
    assert "error_id" not in room


def test_reading_a_lot_back_echoes_what_was_booked_in_plus_the_receipt_stamp(api, lot_received):
    """
    A read returns the delivery exactly as it was booked in, with the frozen
    receipt moisture and the paperwork posture the unprotected fork assigned,
    and reading it changes nothing about the row.

    PRD: "A lot declared `NONE` is created directly in status `RECEIVED` with
    `permit_status` set to `NOT_REQUIRED`."

    Design: Corner/entities/get_tonewood_lot_returns_the_stored_row
    """
    lot = validate_success(
        api.get_tonewood_lot(lot_received["lot1"], U.MACHINIST_HEADERS))
    A.assert_system_fields(lot)
    assert lot["lot_code"] == "LOT-001"
    assert lot["species_code"] == "SITKA_SPRUCE"
    assert lot["cites_appendix"] == "NONE"
    assert lot["board_feet_received"] == 100.00
    assert lot["moisture_content_pct"] == 12.0
    assert lot["moisture_at_receipt_pct"] == 12.0
    assert lot["permit_status"] == "NOT_REQUIRED"
    assert lot["status"] == "RECEIVED"
    assert lot["storage_room_id"] == lot_received["dry1"]

    again = validate_success(
        api.get_tonewood_lot(lot_received["lot1"], U.WOOD_BUYER_HEADERS))
    assert again["version"] == lot["version"]


def test_the_species_filter_and_the_page_window_compose_rather_than_shadow(api, four_lots):
    """
    Three spruce deliveries and one maple one page two at a time under a species
    filter: the reported total counts only the filtered set, and the flag saying
    more rows remain is true on the first window and false on the second.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` is the number of rows matching the filters
    before pagination is applied and `has_more` is true exactly when rows remain
    beyond the current page."

    Design: Corner/entities/list_tonewood_lots_filtered_by_species_with_pagination
    """
    page1, meta1 = validate_paginated(api.list_tonewood_lots(
        U.WOOD_BUYER_HEADERS,
        {"species_code": "SITKA_SPRUCE", "limit": 2, "offset": 0}))
    assert len(page1) == 2
    A.assert_pagination_meta(meta1, limit=2, offset=0, total_count=3, has_more=True)
    assert [row["lot_code"] for row in page1] == ["LOT-001", "LOT-002"]

    page2, meta2 = validate_paginated(api.list_tonewood_lots(
        U.WOOD_BUYER_HEADERS,
        {"species_code": "SITKA_SPRUCE", "limit": 2, "offset": 2}))
    assert len(page2) == 1
    A.assert_pagination_meta(meta2, limit=2, offset=2, total_count=3, has_more=False)
    assert page2[0]["lot_code"] == "LOT-003"


def test_an_unfiltered_listing_applies_the_declared_page_defaults(api, four_lots):
    """
    With no query string at all the collection comes back under the documented
    default window, which is wide enough to hold all four deliveries in a single
    page, and the maple lot that the species filter excluded is present again.

    PRD: "`limit` controls page size: it defaults to 10, its minimum accepted
    value is 1 and its maximum accepted value is 100."

    Design: Corner/entities/list_tonewood_lots_filtered_by_species_with_pagination
    """
    rows, meta = validate_paginated(api.list_tonewood_lots(U.WOOD_BUYER_HEADERS))
    assert len(rows) == 4
    A.assert_pagination_meta(meta, limit=10, offset=0, total_count=4, has_more=False)
    assert [row["lot_code"] for row in rows] == [
        "LOT-001", "LOT-002", "LOT-003", "LOT-004"]


def test_a_well_formed_identifier_that_names_nothing_is_a_not_found(api, clock):
    """
    An identifier that is perfectly well formed but names no order is answered
    with the order-specific not-found code inside the error envelope, rather
    than a success carrying an empty payload.

    PRD: "Every entity identifier in the URL path resolves to an existing row.
    Violation: the 404 belonging to that entity — `ERR_STORAGE_ROOM_NOT_FOUND`,
    `ERR_TONEWOOD_LOT_NOT_FOUND`, `ERR_BILLET_NOT_FOUND`,
    `ERR_COMPONENT_SPEC_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`,
    `ERR_STATION_NOT_FOUND`, `ERR_STATION_RESERVATION_NOT_FOUND`,
    `ERR_OPTION_CATALOG_NOT_FOUND`, `ERR_BUILD_ORDER_NOT_FOUND`,
    `ERR_OPTION_SELECTION_NOT_FOUND`, `ERR_FINISH_RUN_NOT_FOUND`,
    `ERR_SETUP_INSPECTION_NOT_FOUND`, `ERR_REPAIR_SHOP_NOT_FOUND`,
    `ERR_WARRANTY_REGISTRATION_NOT_FOUND` or `ERR_EXPORT_SHIPMENT_NOT_FOUND`."

    Design: Corner/entities/get_unknown_build_order_returns_build_order_not_found
    """
    response = api.get_build_order(MISSING_ID, U.COORDINATOR_HEADERS)
    body = response.json()
    assert body["response_type"] == "error"
    A.assert_envelope_meta(body)

    error = validate_error(response, E.ERR_BUILD_ORDER_NOT_FOUND, 404)
    assert error["message"].strip() != ""


def test_a_delivery_with_no_board_feet_is_refused_instead_of_defaulted_to_zero(api, clock):
    """
    The received quantity carries no default, so a delivery note that omits it is
    a schema violation and no lot is written — the server must not invent a
    zero-quantity delivery and compute a zero yield from it.

    PRD: "A `WoodBuyer` books a delivery in as a tonewood lot, supplying a
    `lot_code` unique across all lots, a `species_code` drawn from
    `SITKA_SPRUCE`, `HONDURAN_MAHOGANY`, `HARD_MAPLE`, `EAST_INDIAN_ROSEWOOD`,
    `BRAZILIAN_ROSEWOOD` and `EBONY`, the `cites_appendix` under which the
    species is declared at receipt — `NONE`, `APPENDIX_II` or `APPENDIX_I` — a
    positive `board_feet_received` figure carried to two decimal places, an
    initial `moisture_content_pct` between 2.0 and 30.0 inclusive, and the
    `storage_room_id` of the room the wood physically goes into."

    Design: Corner/entities/create_tonewood_lot_without_board_feet_received_is_refused
    """
    env = X.build_dry_store(api, clock)

    payload = {
        "lot_code": "LOT-001",
        "species_code": "SITKA_SPRUCE",
        "cites_appendix": "NONE",
        "moisture_content_pct": 12.0,
        "storage_room_id": env["dry1"],
    }
    validate_error(api.create_tonewood_lot(payload, U.WOOD_BUYER_HEADERS),
                   E.ERR_INVALID_REQUEST, 422)

    _, meta = validate_paginated(api.list_tonewood_lots(U.WOOD_BUYER_HEADERS))
    assert meta["total_count"] == 0


def test_three_omitted_plant_fields_land_on_their_declared_defaults(api, clock):
    """
    A station commissioned without a changeover figure and a spec published
    without a thickness tolerance or a room type all come back carrying the
    documented defaults rather than nulls, which is what the conflict window and
    the quality-control band later read.

    PRD: "Two optional fields carry defaults: `thickness_tolerance_mm`, the
    permitted absolute deviation from `target_thickness_mm` at quality control,
    defaults to 0.15 millimetres and must be positive; and `required_room_type`,
    the type of room the machining stations for this spec must sit in, defaults
    to `BUILD_ROOM` and may otherwise be `DRY_STORE`."

    Design: Corner/entities/omitted_optional_plant_fields_take_their_declared_defaults
    """
    room = validate_success(api.create_storage_room({
        "room_code": "BR-1", "room_type": "BUILD_ROOM", "target_rh_pct": 45.0,
        "target_temp_c": 21.0, "capacity_slots": 10,
    }, U.PLANT_ADMIN_HEADERS), 201)
    assert room["rh_tolerance_pct"] == 3.0

    station = validate_success(api.create_station({
        "station_code": "CNC-1", "station_type": "CNC_ROUTER",
        "room_id": room["id"],
    }, U.PLANT_ADMIN_HEADERS), 201)
    assert station["changeover_minutes"] == 30
    assert station["total_scheduled_minutes"] == 0
    assert station["held_minutes"] == 0

    spec = validate_success(api.create_component_spec({
        "spec_code": "TOP-OM", "component_type": "BODY_TOP",
        "required_species_codes": ["SITKA_SPRUCE"], "min_grade": "AA",
        "nominal_board_feet": 6.00, "target_thickness_mm": 2.90,
        "cnc_minutes": 45, "hand_shape_minutes": 60,
    }, U.PLANT_ADMIN_HEADERS), 201)
    assert spec["thickness_tolerance_mm"] == 0.15
    assert spec["required_room_type"] == "BUILD_ROOM"


def test_an_order_opened_with_only_its_required_fields_is_a_plain_nitro_build(api, clock):
    """
    The three shaping flags default to a non-custom, untiered, nitrocellulose
    build, and those defaults are load-bearing on the very same reply: the
    provisional total is the bare list price with no surcharge, and the priority
    score is zero because a promise ninety-two days out clamps the urgency term.

    PRD: "Three optional flags shape the rest of the order's life:
    `is_custom_shop` defaults to false and decides whether the order runs through
    the custom shop; `artist_tier` defaults to `NONE` and may be `ENDORSER` or
    `SIGNATURE`; and `finish_system` defaults to `NITRO` and may be `POLY`."

    Design: Corner/entities/omitted_build_order_flags_default_to_a_standard_nitro_build
    """
    order = validate_success(api.create_build_order({
        "order_code": "ORD-STD", "model_code": "D28",
        "base_price_cents": 300000, "promised_date": "2026-11-01T00:00:00Z",
    }, U.COORDINATOR_HEADERS), 201)

    assert order["is_custom_shop"] is False
    assert order["artist_tier"] == "NONE"
    assert order["finish_system"] == "NITRO"
    assert order["build_stage"] == "DRAFT"
    assert order["commercial_status"] == "QUOTED"
    assert order["provisional_quote_total_cents"] == 300000
    assert order["binding_quote_total_cents"] is None
    assert order["priority_score"] == 0.00
    assert order["deposit_paid_cents"] == 0
    assert order["deposit_held_cents"] == 0
    assert order["cites_permit_required"] is False
    assert order["strictest_cites_appendix"] == "NONE"


def test_the_receipt_projection_and_the_realised_figure_diverge_at_creation(api, clock):
    """
    The forward-looking projection already discounts the wet wood and the
    whole-lot saw allowance, while the realised figure is zero because nothing
    has been cut, and the six wood buckets open with everything still standing.

    PRD: "`nominal_yield_board_feet` is the receipt-time projection. It takes
    `board_feet_received`, reduces it by the shrinkage allowance computed from
    `moisture_at_receipt_pct` and by a single whole-lot sawing allowance of 30
    basis points, and rounds half up to two decimal places: multiply
    `board_feet_received` by the result of subtracting both the shrinkage
    allowance and the 30-basis-point sawing allowance from 10000, then divide by
    10000."

    Design: Corner/entities/lot_creation_computes_the_receipt_projection_and_a_zeroed_ledger
    """
    env = X.build_dry_store(api, clock)

    lot = F.create_lot(api, F.lot_payload(storage_room_id=env["dry1"]))
    assert lot["nominal_yield_board_feet"] == 97.90
    assert lot["actual_yield_board_feet"] == 0.00
    A.assert_lot_ledger(lot, available=100.00, unassigned=0.00, reserved=0.00,
                        consumed=0.00, scrapped=0.00, kerf_loss=0.00)
    assert lot["board_feet_cut"] == 0.00
    A.assert_wood_conserved(lot)


def test_the_receipt_moisture_stays_frozen_while_the_version_advances_per_write(api, lot_received):
    """
    Three further writes on the same delivery — a meter reading, the
    conditioning declaration and the release — each advance the row's version by
    one, and through all of them the stamped receipt moisture never moves even
    though the live figure does.

    PRD: "Both branches then do the same three things: they stamp
    `moisture_at_receipt_pct` from the `moisture_content_pct` supplied at
    creation and never move that stamped figure again; they initialise the wood
    ledger with `board_feet_cut` and `board_feet_kerf_loss` at zero,
    `board_feet_available` equal to `board_feet_received`, and
    `board_feet_unassigned`, `board_feet_reserved`, `board_feet_consumed` and
    `board_feet_scrapped` all at zero; and they compute both yield projections
    described below."

    Design: Corner/entities/lot_system_fields_are_server_minted_and_version_advances_per_write
    """
    created = validate_success(
        api.get_tonewood_lot(lot_received["lot1"], U.WOOD_BUYER_HEADERS))
    A.assert_system_fields(created)
    assert created["permit_status"] == "NOT_REQUIRED"

    dried = F.log_moisture_reading(api, lot_received["lot1"], 7.0)
    assert dried["moisture_content_pct"] == 7.0
    assert dried["moisture_at_receipt_pct"] == 12.0

    conditioned = F.condition_lot(api, lot_received["lot1"])
    released = F.release_lot(api, lot_received["lot1"])

    versions = [created["version"], dried["version"],
                conditioned["version"], released["version"]]
    assert versions == sorted(set(versions))
    assert released["status"] == "RELEASED"
    assert released["moisture_at_receipt_pct"] == 12.0


def test_an_unknown_species_and_an_oversized_page_are_both_schema_violations(api, four_lots):
    """
    A species outside the declared six and a page size one above the documented
    ceiling are refused with the same schema code, and a negative starting
    position is refused rather than being quietly clamped to zero.

    PRD: "A `limit` below 1 or above 100, or a negative `offset`, is a schema
    violation and is rejected with `ERR_INVALID_REQUEST` and HTTP 422 — the
    values are never silently clamped."

    Design: Corner/entities/unknown_species_enum_and_out_of_range_limit_are_both_refused
    """
    validate_error(api.create_tonewood_lot(F.lot_payload(
        lot_code="LOT-005", species_code="TEAK", board_feet_received=50.00,
        moisture_content_pct=10.0, storage_room_id=four_lots["dry1"]),
        U.WOOD_BUYER_HEADERS), E.ERR_INVALID_REQUEST, 422)

    validate_error(api.list_tonewood_lots(U.WOOD_BUYER_HEADERS, {"limit": 101}),
                   E.ERR_INVALID_REQUEST, 422)
    validate_error(api.list_tonewood_lots(U.WOOD_BUYER_HEADERS, {"offset": -1}),
                   E.ERR_INVALID_REQUEST, 422)

    rows, meta = validate_paginated(
        api.list_tonewood_lots(U.WOOD_BUYER_HEADERS, {"limit": 100, "offset": 0}))
    assert len(rows) == 4
    assert meta["total_count"] == 4


def test_reference_data_carries_no_version_and_no_update_endpoint(api, clock):
    """
    An engineering spec and a catalog option are published once: their reads
    carry an identifier and a creation stamp but no version and no modification
    stamp, and the catalog row's two optional fields are visible on the same read
    as an empty array and an unrestricted finish system.

    PRD: "A `ComponentSpec` and an `OptionCatalog` row are published once and
    never modified: they carry `id` and `created_at` only."

    Design: Corner/entities/component_spec_is_immutable_and_exposes_no_version
    """
    spec_id = F.create_spec(api, F.spec_payload())["id"]
    option_id = F.create_option(api, F.option_payload(
        option_code="INL-VINE", option_group="INLAY", upcharge_cents=130000,
        complexity_class="ARTISAN", lead_time_days=45,
        incompatible_option_codes=[]))["id"]

    spec = validate_success(api.get_component_spec(spec_id, U.MACHINIST_HEADERS))
    A.assert_reference_data_shape(spec)
    assert spec["spec_code"] == "TOP-OM"
    assert spec["component_type"] == "BODY_TOP"

    option = validate_success(api.get_option(option_id, U.COORDINATOR_HEADERS))
    A.assert_reference_data_shape(option)
    assert option["incompatible_option_codes"] == []
    assert option["requires_finish_system"] == "ANY"


def test_a_catalog_row_omitting_both_optional_fields_reports_a_list_and_an_enum(api, clock):
    """
    An option published without an incompatibility list and without a finish
    restriction reports an empty array and the unrestricted value, so an omitted
    optional array can never come back as null.

    PRD: "Two optional fields carry defaults: `incompatible_option_codes`
    defaults to an empty array and lists option codes that may not coexist on one
    order, and `requires_finish_system` defaults to `ANY` and may instead pin the
    option to `NITRO` or `POLY`."

    Design: Corner/entities/component_spec_is_immutable_and_exposes_no_version
    """
    option = F.create_option(api, {
        "option_code": "INL-VINE", "option_group": "INLAY",
        "upcharge_cents": 130000, "complexity_class": "ARTISAN",
        "lead_time_days": 45,
    })
    assert option["incompatible_option_codes"] == []
    assert option["requires_finish_system"] == "ANY"
    A.assert_reference_data_shape(option)


def test_sawing_against_a_lot_that_does_not_exist_names_the_lot_in_the_error(api, lot_released):
    """
    The body foreign key is resolved before the concurrency echo and before the
    availability arithmetic, so a cut quoting a lot that is not on file is a
    not-found on the lot and the real lot standing beside it is untouched.

    PRD: "Every foreign key in the request body resolves to an existing row —
    `lot_id` and `parent_billet_id` when sawing a billet; `spec_id`, `billet_id`
    and `build_order_id` when opening a component; `room_id` when commissioning a
    station; `station_id`, `build_order_id` and `component_id` when booking a
    reservation; `option_id` when configuring an option; `build_order_id` and
    `booth_id` when booking a finish run; `build_order_id` and
    `registering_shop_id` when registering a warranty; `build_order_id` when
    opening an export shipment; `storage_room_id` when receiving a tonewood lot."

    Design: Corner/entities/create_billet_against_an_unknown_lot_returns_tonewood_lot_not_found
    """
    validate_error(api.create_billet({
        "billet_code": "BLT-001", "lot_id": MISSING_ID, "board_feet": 30.00,
        "grade": "AAA",
        "expected_tonewood_lot_version": lot_released["lot_v1"],
    }, U.MACHINIST_HEADERS), E.ERR_TONEWOOD_LOT_NOT_FOUND, 404)

    _, meta = validate_paginated(api.list_billets(U.MACHINIST_HEADERS))
    assert meta["total_count"] == 0

    lot = validate_success(
        api.get_tonewood_lot(lot_released["lot1"], U.WOOD_BUYER_HEADERS))
    assert lot["board_feet_available"] == 100.00
    assert lot["board_feet_kerf_loss"] == 0.00


def test_the_same_part_is_reachable_from_its_spec_and_from_its_billet(api, comp_routed):
    """
    A part is a junction row with three independent edges, so filtering the
    collection by its spec and filtering it by its billet each return the same
    single row, and the row is legal with its order edge left unbound.

    PRD: "A `build_order_id` may be supplied once that order has been released to
    the machine shop, and is omitted entirely for shelf stock."

    Design: Corner/entities/component_is_the_graph_junction_of_spec_billet_and_order
    """
    by_billet, meta_b = validate_paginated(api.list_components(
        U.MACHINIST_HEADERS, {"billet_id": comp_routed["blt1"]}))
    assert meta_b["total_count"] == 1
    assert by_billet[0]["id"] == comp_routed["cmp1"]

    by_spec, meta_s = validate_paginated(api.list_components(
        U.MACHINIST_HEADERS, {"spec_id": comp_routed["spec1"]}))
    assert meta_s["total_count"] == 1
    assert by_spec[0]["id"] == comp_routed["cmp1"]

    part = by_spec[0]
    assert part["build_order_id"] is None
    assert part["status"] == "CNC_ROUTED"
    assert part["measured_thickness_mm"] == 2.90

    billet = validate_success(
        api.get_billet(comp_routed["blt1"], U.MACHINIST_HEADERS))
    assert billet["status"] == "RESERVED"
