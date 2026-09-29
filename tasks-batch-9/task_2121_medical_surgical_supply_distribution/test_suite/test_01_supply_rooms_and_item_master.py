"""Supply-room registration and the item master.

Covers resource identity, server-owned defaults, schema rejection, listing and
the self-referential low-unit-of-measure edge on the item master.
"""

from test_helpers import (
    ApiErrorId,
    assert_item,
    assert_lot,
    assert_millisecond_timestamp,
    assert_supply_room,
    create_item,
    create_item_payload,
    create_lot_payload,
    create_supply_room_payload,
    is_valid_uuid,
    make_distribution_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
    DISTRIBUTION_OPERATOR_USER_ID,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]


def test_create_supply_room_applies_every_restrictive_default(api):
    """PRD §3.1: "Three of the room's attributes are safety attributes and they
    default to their most restrictive setting."
    PRD §3.1: "`controlled_license_status` is `NONE` by default and may also be
    `ACTIVE` or `LAPSED`; only `ACTIVE` counts as a live licence."
    PRD §3.1: "`window_open_min` is the earliest delivery minute the room will
    accept a stop and defaults to 360 — six o'clock in the morning;
    `window_close_min` is the latest minute by which a stop must have finished
    and defaults to 1080, six o'clock in the evening."
    PRD §3.1: "Commercially, the room carries `credit_limit_cents`, the largest
    open commitment it may hold at once, defaulting to 100000000 cents — one
    million dollars — and `open_commitment_cents`, a server-maintained figure
    that starts at zero and is never written directly by a client."
    PRD §2.4: "`id` is a server-minted UUID string with no type prefix, and it
    is never supplied by a client."
    PRD §2.4: "`version` is an integer that begins at 1 when the resource is
    created and increments by exactly one on every mutation of that resource,
    including mutations that arrive as a side effect of an operation aimed at
    some other resource."
    PRD §4: "Creating a new resource returns HTTP 201 with the created resource
    in `data`"

    Design: Corner/entities/create_supply_room_returns_201_with_defaults_and_system_fields
    """
    payload = create_supply_room_payload(
        facility_code="FAC-100",
        room_code="GEN-100",
        gpo_member_class="NON_ACUTE",
        room_type="GENERAL_STORE",
    )
    response = api.create_supply_room(payload, ADMIN)
    room = validate_success(response, 201)

    assert response.json()["response_type"] == "object"
    assert_supply_room(room)

    assert room["refrigerated"] is False
    assert room["controlled_secured"] is False
    assert room["controlled_license_status"] == "NONE"
    assert room["window_open_min"] == 360
    assert room["window_close_min"] == 1080
    assert room["credit_limit_cents"] == 100000000
    assert room["open_commitment_cents"] == 0
    assert room["version"] == 1, "version begins at 1 when the resource is created"
    assert is_valid_uuid(room["id"]), "id is a bare UUID with no type prefix"
    assert not room["id"].startswith("sr_")
    assert_millisecond_timestamp(room["created_at"], "created_at")
    assert_millisecond_timestamp(room["updated_at"], "updated_at")


def test_get_supply_room_returns_the_stored_row(api):
    """PRD §3.1: "Registration records the member facility it belongs to through
    `facility_code`, and a `room_code` that must be globally unique across every
    supply room in the system and between 1 and 40 characters long — a second
    room offered the same code is refused with `ERR_DUPLICATE_ROOM_CODE`."
    PRD §3.1: "Two enumerations describe the room: `gpo_member_class`, one of
    `ACUTE`, `NON_ACUTE` or `SURGERY_CENTER`, which decides which GPO contracts
    are allowed to price for it, and `room_type`, one of `OR_CORE`, `ICU`,
    `GENERAL_STORE` or `PHARMACY_VAULT`."

    Design: Corner/entities/get_supply_room_returns_stored_entity
    """
    created = validate_success(
        api.create_supply_room(
            create_supply_room_payload(
                facility_code="FAC-101",
                room_code="PHARM-101",
                gpo_member_class="SURGERY_CENTER",
                room_type="PHARMACY_VAULT",
                refrigerated=True,
                controlled_secured=True,
                controlled_license_status="ACTIVE",
                window_open_min=420,
                window_close_min=900,
                credit_limit_cents=250000,
            ),
            ADMIN,
        ),
        201,
    )

    fetched = validate_success(api.get_supply_room(created["id"], ADMIN), 200)
    assert_supply_room(fetched)

    assert fetched["id"] == created["id"]
    assert fetched["room_code"] == "PHARM-101"
    assert fetched["facility_code"] == "FAC-101"
    assert fetched["gpo_member_class"] == "SURGERY_CENTER"
    assert fetched["room_type"] == "PHARMACY_VAULT"
    assert fetched["refrigerated"] is True
    assert fetched["controlled_secured"] is True
    assert fetched["controlled_license_status"] == "ACTIVE"
    assert fetched["window_open_min"] == 420
    assert fetched["window_close_min"] == 900
    assert fetched["credit_limit_cents"] == 250000


def test_item_master_listing_pages_with_total_count_and_has_more(api):
    """PRD §2.3: "Every list endpoint accepts two optional query parameters,
    `limit` and `offset`."
    PRD §2.3: "For list responses the `meta` object carries `limit` and `offset`
    as they were resolved for the request, `total_count` as the number of rows
    matching the filters before `limit` and `offset` were applied, and
    `has_more`, which is true exactly when rows remain beyond the current page."

    Design: Corner/entities/list_items_paginates_with_total_count_and_has_more
    """
    for suffix in ("L1", "L2", "L3"):
        create_item(
            sku=f"SKU-{suffix}-CS",
            description=f"List probe {suffix}",
            manufacturer_code="MFR-ACME",
            uom="CS",
            wac_cents=1000,
            handling_class="AMBIENT",
            units_per_parent=10,
        )

    first_page, first_meta = validate_paginated(
        api.list_items(ADMIN, params={"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2, f"limit 2 must return 2 rows, got {len(first_page)}"
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    last_page, last_meta = validate_paginated(
        api.list_items(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert len(last_page) == 1, f"offset 2 must return the last row, got {len(last_page)}"
    assert last_meta["total_count"] == 3
    assert last_meta["has_more"] is False
    assert first_page[0]["id"] != last_page[0]["id"]


def test_unknown_item_id_reports_item_not_found(api):
    """PRD §2.5: "Each path variable has its own dedicated 404: `supply_room_id`
    yields `ERR_SUPPLY_ROOM_NOT_FOUND`, `item_id` yields `ERR_ITEM_NOT_FOUND`,
    `contract_id` yields `ERR_CONTRACT_NOT_FOUND`, `contract_line_id` yields
    `ERR_CONTRACT_LINE_NOT_FOUND`, `formulary_item_id` yields
    `ERR_FORMULARY_ITEM_NOT_FOUND`, `lot_id` yields `ERR_LOT_NOT_FOUND`,
    `order_id` yields `ERR_ORDER_NOT_FOUND`, `order_line_id` yields
    `ERR_ORDER_LINE_NOT_FOUND`, `substitution_request_id` yields
    `ERR_SUBSTITUTION_REQUEST_NOT_FOUND`, `recall_notice_id` yields
    `ERR_RECALL_NOTICE_NOT_FOUND`, `route_id` yields `ERR_ROUTE_NOT_FOUND` and
    `chargeback_claim_id` yields `ERR_CHARGEBACK_CLAIM_NOT_FOUND`. All of them
    are HTTP 404."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/get_item_with_unknown_uuid_returns_not_found
    """
    response = api.get_item("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(response, ApiErrorId.ERR_ITEM_NOT_FOUND.value, 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_item_creation_without_wac_cents_is_a_schema_violation(api):
    """PRD §2.9: "**Request schema.** Every required input field present, types
    correct, enum values inside their declared sets, integer bounds honoured
    (`requested_qty` greater than zero, `par_qty` greater than zero,
    `reorder_point` at least zero and strictly below `par_qty`,
    `floor_price_cents` greater than zero, `effective_to` strictly after
    `effective_from`, `window_open_min` at least zero and strictly below
    `window_close_min` which is at most 1439, `service_minutes` greater than
    zero, `arrival_min` between zero and 1439 inclusive), and pagination within
    its declared range — otherwise `ERR_VALIDATION` (400). Applies everywhere."
    PRD §3.1: "`wac_cents` is the wholesale acquisition cost per ordering unit
    and must be greater than zero"

    Design: Corner/entities/create_item_missing_required_wac_returns_validation_error
    """
    response = api.create_item(
        {
            "sku": "SKU-BAD-CS",
            "description": "Missing wac",
            "manufacturer_code": "MFR-ACME",
            "uom": "CS",
            "handling_class": "AMBIENT",
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    rows, meta = validate_paginated(api.list_items(ADMIN, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 0, "the refused create must write no item row"
    assert rows == []


def test_item_creation_applies_declared_defaults(api):
    """PRD §3.1: "`units_per_parent` states how many eaches one such unit
    contains and defaults to 1, which is also its minimum, so the replenishment
    arithmetic in §3.3 never divides by zero."
    PRD §3.1: "`is_lot_tracked` defaults to true and marks that allocation must
    draw from a lot row, and `status` is `ACTIVE` by default or `DISCONTINUED`."
    PRD §3.1: "Low-unit-of-measure picking is modelled by pointing an each-level
    record at its case-level parent through `lum_parent_item_id`, which is null
    on case-level records"

    Design: Corner/entities/create_item_defaults_applied_when_optional_fields_omitted
    """
    item = validate_success(
        api.create_item(
            {
                "sku": "SKU-DEF-EA",
                "description": "Defaults probe",
                "manufacturer_code": "MFR-ACME",
                "uom": "EA",
                "wac_cents": 300,
                "handling_class": "AMBIENT",
            },
            ADMIN,
        ),
        201,
    )
    assert_item(item)

    assert item["units_per_parent"] == 1
    assert item["is_lot_tracked"] is True
    assert item["status"] == "ACTIVE"
    assert item.get("lum_parent_item_id") is None


def test_lot_quantity_on_hand_and_status_are_server_owned(api):
    """PRD §3.5: "A new lot begins with `quantity_on_hand` equal to
    `received_quantity`, `status` `AVAILABLE` and `excursion_flagged_by_user_id`
    null."
    PRD §3.5: "The received quantity is immutable once written and anchors a
    units-conservation invariant: at every instant, the lot's
    `quantity_on_hand` plus the quantity currently allocated out of it to order
    lines must equal the received quantity, unless the lot has been written
    off."

    Design: Corner/entities/lot_quantity_on_hand_is_computed_and_client_input_ignored
    """
    item = create_item(
        sku="SKU-LOTSYS-CS",
        description="Lot system-field probe",
        manufacturer_code="MFR-ACME",
        uom="CS",
        wac_cents=2000,
        handling_class="AMBIENT",
        units_per_parent=10,
    )

    payload = create_lot_payload(
        item["id"], lot_code="LOT-SYS", expiry_date="2027-12-31T00:00:00Z",
        received_quantity=40,
    )
    payload["quantity_on_hand"] = 5
    payload["status"] = "QUARANTINED"

    response = api.create_lot(
        payload, make_distribution_operator_headers(DISTRIBUTION_OPERATOR_USER_ID)
    )

    if 200 <= response.status_code < 300:
        lot = validate_success(response, response.status_code)
        assert_lot(lot)
        assert lot["received_quantity"] == 40
        assert lot["quantity_on_hand"] == 40, (
            "quantity_on_hand is server-derived from received_quantity"
        )
        assert lot["status"] == "AVAILABLE", "a new lot begins AVAILABLE"
        assert lot.get("excursion_flagged_by_user_id") is None
    else:
        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)


def test_handling_class_outside_the_declared_enum_is_rejected(api):
    """PRD §2.9: "**Request schema.** Every required input field present, types
    correct, enum values inside their declared sets, integer bounds honoured"
    PRD §3.1: "`handling_class` — `AMBIENT`, `COLD_CHAIN`, `CONTROLLED` or
    `CONTROLLED_COLD` — is the storage and security class that gates which rooms
    may receive the item"

    Design: Corner/entities/create_item_with_invalid_handling_class_enum_returns_validation_error
    """
    response = api.create_item(
        create_item_payload(
            sku="SKU-ENUM-CS",
            description="Enum probe",
            manufacturer_code="MFR-ACME",
            uom="CS",
            wac_cents=1000,
            handling_class="FROZEN",
            units_per_parent=10,
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)


def test_lum_parent_reference_resolves_through_the_filtered_item_listing(api):
    """PRD §3.1: "Low-unit-of-measure picking is modelled by pointing an
    each-level record at its case-level parent through `lum_parent_item_id`,
    which is null on case-level records; listing the item master filtered by
    that reference returns the each-level children of a case."

    Design: Corner/entities/item_self_reference_lum_parent_resolves_through_filtered_list
    """
    parent = create_item(
        sku="SKU-PARENT-CS",
        description="Suture, case of 36",
        manufacturer_code="MFR-ACME",
        uom="CS",
        wac_cents=9000,
        handling_class="AMBIENT",
        units_per_parent=36,
    )
    child = create_item(
        sku="SKU-CHILD-EA",
        description="Suture, each",
        manufacturer_code="MFR-ACME",
        uom="EA",
        wac_cents=250,
        handling_class="AMBIENT",
        units_per_parent=1,
        lum_parent_item_id=parent["id"],
    )

    rows, meta = validate_paginated(
        api.list_items(
            ADMIN, params={"lum_parent_item_id": parent["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1, "only the each-level child is a child of the case"
    assert len(rows) == 1
    assert rows[0]["id"] == child["id"]
    assert child["lum_parent_item_id"] == parent["id"]
    assert parent.get("lum_parent_item_id") is None


def test_duplicate_room_code_is_refused(api):
    """PRD §3.1: "Registration records the member facility it belongs to through
    `facility_code`, and a `room_code` that must be globally unique across every
    supply room in the system and between 1 and 40 characters long — a second
    room offered the same code is refused with `ERR_DUPLICATE_ROOM_CODE`."

    Design: Corner/entities/duplicate_room_code_rejected_with_uniqueness_error
    """
    validate_success(
        api.create_supply_room(
            create_supply_room_payload(
                facility_code="FAC-103",
                room_code="OR-DUP",
                gpo_member_class="ACUTE",
                room_type="OR_CORE",
            ),
            ADMIN,
        ),
        201,
    )

    response = api.create_supply_room(
        create_supply_room_payload(
            facility_code="FAC-104",
            room_code="OR-DUP",
            gpo_member_class="NON_ACUTE",
            room_type="ICU",
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ROOM_CODE.value, 409)
