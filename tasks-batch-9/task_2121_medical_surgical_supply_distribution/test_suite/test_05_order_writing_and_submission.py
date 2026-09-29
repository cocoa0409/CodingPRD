"""Opening orders, writing lines onto them, and the five submission gates."""

from test_helpers import (
    ApiErrorId,
    add_order_line,
    create_order,
    create_order_payload,
    create_order_line_payload,
    create_supply_room,
    decide_formulary_item,
    make_materials_manager_headers,
    read_order,
    read_formulary_item,
    read_supply_room,
    setup_draft_order,
    setup_priced_catalogue,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]


def test_new_order_is_born_draft_and_unbilled(api):
    """PRD §3.4: "A `MaterialsManager` opens an order against its own room by
    naming the `supply_room_id`. The new order is born with
    `fulfillment_status` `DRAFT`, `settlement_status` `UNBILLED`,
    `order_total_cents` at zero, and `route_id`, `stop_arrival_min`,
    `stop_service_minutes`, `service_date`, `submitted_at` and `delivered_at`
    all null."

    Design: Corner/state_machines/new_order_starts_in_draft_and_unbilled
    """
    room = create_supply_room(
        facility_code="FAC-200", room_code="GEN-200", gpo_member_class="ACUTE",
        room_type="GENERAL_STORE",
    )
    order = validate_success(
        api.create_order(
            create_order_payload(room["id"]), make_materials_manager_headers(room["id"])
        ),
        201,
    )

    assert order["fulfillment_status"] == "DRAFT"
    assert order["settlement_status"] == "UNBILLED"
    assert order["order_total_cents"] == 0
    assert order.get("route_id") is None
    assert order.get("stop_arrival_min") is None
    assert order.get("stop_service_minutes") is None
    assert order.get("service_date") is None
    assert order.get("submitted_at") is None
    assert order.get("delivered_at") is None


def test_materials_manager_cannot_open_an_order_for_another_room(api):
    """PRD §2.1: "Concretely, a materials manager may only act on the supply room
    named in the path, on a `ReplenishmentOrder` whose `supply_room_id` equals
    its `X-User-ID`, on a `FormularyItem` whose `supply_room_id` equals its
    `X-User-ID`, or on an order line or substitution request whose owning order
    belongs to that room. A mismatch is rejected with
    `ERR_SUPPLY_ROOM_SCOPE_VIOLATION` (HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `MaterialsManager`, `X-User-ID` is the `id`
    of the acting `SupplyRoom`; ownership checks on any resource that references
    a `SupplyRoom` compare the resource's supply-room reference to `X-User-ID`."

    Design: Corner/validations/materials_manager_cannot_open_an_order_for_another_supply_room
    """
    room_a = create_supply_room(
        facility_code="FAC-401", room_code="GEN-401A", gpo_member_class="ACUTE",
        room_type="GENERAL_STORE",
    )
    room_b = create_supply_room(
        facility_code="FAC-401", room_code="GEN-401B", gpo_member_class="ACUTE",
        room_type="GENERAL_STORE",
    )

    response = api.create_order(
        create_order_payload(room_b["id"]),
        make_materials_manager_headers(room_a["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SUPPLY_ROOM_SCOPE_VIOLATION.value, 403)

    _rows, meta = validate_paginated(
        api.list_orders(
            ADMIN, params={"supply_room_id": room_b["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, "the refused open must write no order"


def test_controlled_quantity_above_one_hundred_units_is_refused_at_submit(api):
    """PRD §3.4: "Fourth, **the controlled-substance ceiling**: the total
    `requested_qty` across all non-terminal lines whose items are `CONTROLLED`
    or `CONTROLLED_COLD` must be at most 100 units on a single order, and
    exceeding it is `ERR_CONTROLLED_QTY_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/controlled_quantity_limit_exceeded_on_submit
    """
    world = setup_draft_order(
        requested_qty=101,
        room_overrides={
            "facility_code": "FAC-404", "room_code": "PHARM-404",
            "gpo_member_class": "ACUTE", "room_type": "PHARMACY_VAULT",
            "controlled_secured": True, "controlled_license_status": "ACTIVE",
        },
        item_overrides={
            "sku": "SKU-CTRL2-EA", "description": "Controlled unit",
            "manufacturer_code": "MFR-PHARM", "uom": "EA", "wac_cents": 500,
            "handling_class": "CONTROLLED", "units_per_parent": 1,
        },
        contract_overrides={
            "manufacturer_code": "MFR-PHARM", "contract_code": "CTR-CTRL2",
            "tier": "TIER_1", "member_class_scope": "ACUTE",
        },
        tier_price_cents=100,
        floor_price_cents=50,
        formulary_overrides={"facility_item_code": "FAC-CTRL2", "par_qty": 500,
                             "reorder_point": 100},
    )

    response = api.submit_order(
        world["order"]["id"], make_materials_manager_headers(world["room"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_CONTROLLED_QTY_LIMIT_EXCEEDED.value, 422)

    after = read_order(world["order"]["id"])
    assert after["fulfillment_status"] == "DRAFT"
    assert after["order_total_cents"] == 10378
    assert read_supply_room(world["room"]["id"])["open_commitment_cents"] == 0


def test_cold_chain_item_into_an_unrefrigerated_room_is_refused_at_submit(api):
    """PRD §3.4: "Second, **cold-chain eligibility**: for every non-terminal line
    whose item's `handling_class` is `COLD_CHAIN` or `CONTROLLED_COLD`, the room
    must have `refrigerated` true; otherwise `ERR_COLD_CHAIN_ROOM_REQUIRED`
    (HTTP 422)."
    PRD §3.4: "What the room is physically licensed to store is deliberately
    **not** checked here: a draft order is a worksheet, and the controlled-item
    and cold-chain room gates run at submission and at substitution approval,
    never at line write."

    Design: Corner/validations/cold_chain_item_into_non_refrigerated_room_rejected_on_submit
    """
    world = setup_draft_order(
        requested_qty=1,
        room_overrides={
            "facility_code": "FAC-405", "room_code": "GEN-405",
            "gpo_member_class": "ACUTE", "room_type": "GENERAL_STORE",
            "refrigerated": False,
        },
        item_overrides={
            "sku": "SKU-COLD2-EA", "description": "Cold chain unit 2",
            "manufacturer_code": "MFR-BIO", "uom": "EA", "wac_cents": 1000,
            "handling_class": "COLD_CHAIN", "units_per_parent": 1,
        },
        contract_overrides={
            "manufacturer_code": "MFR-BIO", "contract_code": "CTR-COLD2",
            "tier": "TIER_1", "member_class_scope": "ACUTE",
        },
        tier_price_cents=100,
        floor_price_cents=100,
        formulary_overrides={"facility_item_code": "FAC-COLD2", "par_qty": 50,
                             "reorder_point": 10},
    )
    assert world["order_line"]["pinned_unit_price_cents"] == 145, (
        "the line write itself is allowed and pins 100 plus the 45-cent cold adder"
    )

    response = api.submit_order(
        world["order"]["id"], make_materials_manager_headers(world["room"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_COLD_CHAIN_ROOM_REQUIRED.value, 422)

    after = read_order(world["order"]["id"])
    assert after["fulfillment_status"] == "DRAFT"
    assert after.get("submitted_at") is None


def test_submission_over_the_room_credit_limit_is_refused(api):
    """PRD §3.4: "Fifth, **the room's credit limit**: the room's current
    `open_commitment_cents` plus this order's `order_total_cents` must be less
    than or equal to its `credit_limit_cents`, and a breach is
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Corner/validations/order_submit_over_credit_limit_returns_402
    """
    world = setup_draft_order(
        requested_qty=1,
        room_overrides={
            "facility_code": "FAC-406", "room_code": "GEN-406",
            "gpo_member_class": "ACUTE", "room_type": "GENERAL_STORE",
            "credit_limit_cents": 1000,
        },
        item_overrides={
            "sku": "SKU-CR-CS", "description": "Credit probe",
            "manufacturer_code": "MFR-ACME", "uom": "CS", "wac_cents": 8000,
            "handling_class": "AMBIENT", "units_per_parent": 10,
        },
        contract_overrides={
            "manufacturer_code": "MFR-ACME", "contract_code": "CTR-CR",
            "tier": "TIER_1", "member_class_scope": "ACUTE",
        },
        tier_price_cents=3000,
        floor_price_cents=2000,
        formulary_overrides={"facility_item_code": "FAC-CR", "par_qty": 50,
                             "reorder_point": 10},
    )

    response = api.submit_order(
        world["order"]["id"], make_materials_manager_headers(world["room"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, 402)

    after = read_order(world["order"]["id"])
    assert after["order_total_cents"] == 3083
    assert after["fulfillment_status"] == "DRAFT"
    assert read_supply_room(world["room"]["id"])["open_commitment_cents"] == 0


def test_stale_order_version_is_refused_on_the_second_line_write(api):
    """PRD §2.7: "Writing an order line — `POST /orders/{order_id}/lines` —
    requires a non-optional `expected_order_version` field in the request body
    carrying the client's last observed `version` of the target
    `ReplenishmentOrder`. If that value does not equal the order's current
    `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "On success, the order's `version` advances by one, which
    necessarily invalidates the value the client just used."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_order_version_rejected_on_second_line_write
    """
    world = setup_priced_catalogue(
        [
            {
                "item": {
                    "sku": "SKU-OCC-A-CS", "description": "OCC probe A",
                    "manufacturer_code": "MFR-ACME", "uom": "CS", "wac_cents": 8000,
                    "handling_class": "AMBIENT", "units_per_parent": 10,
                },
                "tier_price_cents": 3000, "floor_price_cents": 2000,
                "formulary": {"facility_item_code": "FAC-OCC-A", "par_qty": 50,
                              "reorder_point": 10},
            },
            {
                "item": {
                    "sku": "SKU-OCC-B-CS", "description": "OCC probe B",
                    "manufacturer_code": "MFR-ACME", "uom": "CS", "wac_cents": 8000,
                    "handling_class": "AMBIENT", "units_per_parent": 10,
                },
                "tier_price_cents": 3000, "floor_price_cents": 2000,
                "formulary": {"facility_item_code": "FAC-OCC-B", "par_qty": 50,
                              "reorder_point": 10},
            },
        ],
        room_overrides={
            "facility_code": "FAC-800", "room_code": "GEN-800",
            "gpo_member_class": "ACUTE", "room_type": "GENERAL_STORE",
        },
        contract_overrides={
            "manufacturer_code": "MFR-ACME", "contract_code": "CTR-OCC",
            "tier": "TIER_1", "member_class_scope": "ACUTE",
        },
    )
    room_id = world["room"]["id"]
    mm_headers = make_materials_manager_headers(room_id)
    order = create_order(room_id)
    version_at_open = order["version"]

    add_order_line(order["id"], room_id, world["items"][0]["id"], 1, version_at_open)

    stale = api.create_order_line(
        order["id"],
        create_order_line_payload(world["items"][1]["id"], 1, version_at_open),
        mm_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    after_refusal = read_order(order["id"])
    assert after_refusal["order_total_cents"] == 3083
    assert after_refusal["version"] != version_at_open
    _rows, meta = validate_paginated(
        api.list_order_lines(ADMIN, params={"order_id": order["id"], "limit": 10,
                                            "offset": 0})
    )
    assert meta["total_count"] == 1, "the refused write must create no second line"

    retried = add_order_line(
        order["id"], room_id, world["items"][1]["id"], 1, after_refusal["version"]
    )
    assert retried["pinned_unit_price_cents"] == 3000
    assert read_order(order["id"])["order_total_cents"] == 6166


def test_submission_commits_the_room_credit_in_the_same_request_cycle(api):
    """PRD §3.4: "On a successful submission, `submitted_at` is stamped with the
    logical clock and the order's `order_total_cents` is added to the room's
    `open_commitment_cents`."
    PRD §1: "Every side effect described in this document happens inside the
    request that triggers it, and every computed field a client can read is
    correct the moment the response is returned."

    Design: Corner/consistency_model/submit_commitment_is_visible_on_the_room_in_the_same_request_cycle
    """
    world = setup_draft_order(
        requested_qty=1,
        room_overrides={
            "facility_code": "FAC-900", "room_code": "GEN-900",
            "gpo_member_class": "ACUTE", "room_type": "GENERAL_STORE",
        },
        item_overrides={
            "sku": "SKU-CM-CS", "description": "Consistency probe",
            "manufacturer_code": "MFR-ACME", "uom": "CS", "wac_cents": 8000,
            "handling_class": "AMBIENT", "units_per_parent": 10,
        },
        contract_overrides={
            "manufacturer_code": "MFR-ACME", "contract_code": "CTR-CM",
            "tier": "TIER_1", "member_class_scope": "ACUTE",
        },
        tier_price_cents=3000,
        floor_price_cents=2000,
        formulary_overrides={"facility_item_code": "FAC-CM", "par_qty": 50,
                             "reorder_point": 10},
    )
    assert read_supply_room(world["room"]["id"])["open_commitment_cents"] == 0

    submitted = submit_order(world["order"]["id"], world["room"]["id"])
    assert submitted["fulfillment_status"] == "SUBMITTED"
    assert submitted["submitted_at"] is not None

    assert read_supply_room(world["room"]["id"])["open_commitment_cents"] == 3083, (
        "the very next read of the room already carries the commitment"
    )


class TestLineWriteStateBeatsFormularyStanding:
    """A line write that violates both the draft-state rule and the formulary
    rule reports the earlier rule."""

    @staticmethod
    def _submitted_order_with_unapproved_second_item():
        world = setup_priced_catalogue(
            [
                {
                    "item": {
                        "sku": "SKU-P-A-CS", "description": "Item A, case",
                        "manufacturer_code": "MFR-ACME", "uom": "CS",
                        "wac_cents": 5000, "handling_class": "AMBIENT",
                        "units_per_parent": 10,
                    },
                    "tier_price_cents": 1000, "floor_price_cents": 800,
                    "formulary": {"facility_item_code": "FAC-P-A", "par_qty": 50,
                                  "reorder_point": 10},
                },
                {
                    "item": {
                        "sku": "SKU-P-B-CS", "description": "Item B, case",
                        "manufacturer_code": "MFR-ACME", "uom": "CS",
                        "wac_cents": 5000, "handling_class": "AMBIENT",
                        "units_per_parent": 10,
                    },
                    "tier_price_cents": 1000, "floor_price_cents": 800,
                    "formulary": {"facility_item_code": "FAC-P-B", "par_qty": 50,
                                  "reorder_point": 10},
                    "decision": None,
                },
            ],
            room_overrides={
                "facility_code": "FAC-010", "room_code": "GEN-STORE-10",
                "gpo_member_class": "ACUTE", "room_type": "GENERAL_STORE",
            },
            contract_overrides={
                "manufacturer_code": "MFR-ACME", "contract_code": "CTR-P",
                "tier": "TIER_1", "member_class_scope": "ACUTE",
            },
        )
        room_id = world["room"]["id"]
        order = create_order(room_id)
        add_order_line(order["id"], room_id, world["items"][0]["id"], 2,
                       order["version"])
        world["order"] = submit_order(order["id"], room_id)
        return world

    def test_line_write_on_a_submitted_order_reports_the_state_failure(self, api):
        """PRD §2.9: "When a request violates several rules at once, the response
        is determined by the **first** rule to fail in the fixed order below;
        rules later in the order are not evaluated at all, and their error codes
        cannot appear."
        PRD §3.4: "Lines are written onto the order while it is still `DRAFT` — a
        line write against an order in any other fulfilment state is
        `ERR_ORDER_NOT_DRAFT` (HTTP 409)."
        PRD §3.4: "Before the line is accepted, the item must already be
        `APPROVED` on the destination room's formulary — otherwise
        `ERR_ITEM_NOT_ON_FORMULARY` (HTTP 422) — and the price selector of §3.2
        must find a candidate, otherwise `ERR_NO_ACTIVE_CONTRACT_PRICE`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_priority_8_beats_referential_priority_15_on_line_write
        """
        world = self._submitted_order_with_unapproved_second_item()

        response = api.create_order_line(
            world["order"]["id"],
            create_order_line_payload(
                world["items"][1]["id"], 1, world["order"]["version"]
            ),
            make_materials_manager_headers(world["room"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ORDER_NOT_DRAFT.value, 409)

        body = response.json()
        assert body["data"]["error_id"] != ApiErrorId.ERR_ITEM_NOT_ON_FORMULARY.value
        assert (
            read_formulary_item(world["formulary_items"][1]["id"])["formulary_status"]
            == "REQUESTED"
        )

    def test_the_refused_line_write_creates_no_order_line(self, api):
        """PRD §2.9: "When a request violates several rules at once, the response
        is determined by the **first** rule to fail in the fixed order below;
        rules later in the order are not evaluated at all, and their error codes
        cannot appear."
        PRD §3.4: "Lines are written onto the order while it is still `DRAFT` — a
        line write against an order in any other fulfilment state is
        `ERR_ORDER_NOT_DRAFT` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_priority_8_beats_referential_priority_15_on_line_write
        """
        world = self._submitted_order_with_unapproved_second_item()

        api.create_order_line(
            world["order"]["id"],
            create_order_line_payload(
                world["items"][1]["id"], 1, world["order"]["version"]
            ),
            make_materials_manager_headers(world["room"]["id"]),
        )

        lines, meta = validate_paginated(
            api.list_order_lines(
                ADMIN,
                params={"order_id": world["order"]["id"], "limit": 100, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert all(line["item_id"] != world["items"][1]["id"] for line in lines), (
            "no line for the unapproved item may exist on the order"
        )


class TestSafetyGateBeatsCreditGate:
    """Submission evaluates its five gates in ascending order."""

    @staticmethod
    def _unlicensed_room_over_its_credit_limit():
        return setup_draft_order(
            requested_qty=1,
            room_overrides={
                "facility_code": "FAC-011", "room_code": "PHARM-11",
                "gpo_member_class": "ACUTE", "room_type": "PHARMACY_VAULT",
                "controlled_secured": False, "controlled_license_status": "NONE",
                "credit_limit_cents": 1000,
            },
            item_overrides={
                "sku": "SKU-CTRL-EA", "description": "Controlled analgesic, each",
                "manufacturer_code": "MFR-PHARM", "uom": "EA", "wac_cents": 9000,
                "handling_class": "CONTROLLED", "units_per_parent": 1,
            },
            contract_overrides={
                "manufacturer_code": "MFR-PHARM", "contract_code": "CTR-CTRL",
                "tier": "TIER_1", "member_class_scope": "ACUTE",
            },
            tier_price_cents=5000,
            floor_price_cents=4000,
            formulary_overrides={"facility_item_code": "FAC-CTRL", "par_qty": 20,
                                 "reorder_point": 4},
        )

    def test_submit_reports_controlled_handling_never_the_credit_breach(self, api):
        """PRD §2.9: "Order submission is the sharpest illustration: it is
        guarded by rules 10, 11, 15, 21 and 24, and they are evaluated in exactly
        that ascending order for the order's open lines, so a room that is both
        unlicensed for controlled items and over its credit limit reports the
        controlled-handling failure, never the credit failure."
        PRD §3.4: "First, **controlled-item eligibility**: for every non-terminal
        line — that is, every line whose `line_status` is `OPEN`, `ALLOCATED`,
        `BACKORDERED` or `SUBSTITUTED` — whose item's `handling_class` is
        `CONTROLLED` or `CONTROLLED_COLD`, the destination room must have
        `controlled_secured` true **and** `controlled_license_status` equal to
        `ACTIVE`; otherwise `ERR_CONTROLLED_HANDLING_NOT_PERMITTED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_priority_10_beats_fiscal_priority_24_on_order_submit
        """
        world = self._unlicensed_room_over_its_credit_limit()
        assert read_order(world["order"]["id"])["order_total_cents"] == 5138, (
            "the order total sits far above the room's 1000-cent credit limit"
        )

        response = api.submit_order(
            world["order"]["id"], make_materials_manager_headers(world["room"]["id"])
        )
        validate_error(
            response, ApiErrorId.ERR_CONTROLLED_HANDLING_NOT_PERMITTED.value, 422
        )
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value
        )

    def test_the_refused_submit_leaves_the_order_draft_and_uncommitted(self, api):
        """PRD §2.9: "Order submission is the sharpest illustration: it is
        guarded by rules 10, 11, 15, 21 and 24, and they are evaluated in exactly
        that ascending order for the order's open lines, so a room that is both
        unlicensed for controlled items and over its credit limit reports the
        controlled-handling failure, never the credit failure."
        PRD §3.4: "On a successful submission, `submitted_at` is stamped with the
        logical clock and the order's `order_total_cents` is added to the room's
        `open_commitment_cents`."

        Design: Difficulty/priority_pair_validation_conflict/safety_priority_10_beats_fiscal_priority_24_on_order_submit
        """
        world = self._unlicensed_room_over_its_credit_limit()

        api.submit_order(
            world["order"]["id"], make_materials_manager_headers(world["room"]["id"])
        )

        after = read_order(world["order"]["id"])
        assert after["fulfillment_status"] == "DRAFT"
        assert after["order_total_cents"] == 5138
        assert after.get("submitted_at") is None
        assert read_supply_room(world["room"]["id"])["open_commitment_cents"] == 0


class TestLineWriteGatedOnFormularyStanding:
    """Whether a line may be written depends entirely on the standing of a
    different row: the formulary mapping for the same room and item."""

    @staticmethod
    def _restricted_mapping_world():
        return setup_draft_order(
            room_overrides={
                "facility_code": "FAC-014", "room_code": "ICU-14",
                "gpo_member_class": "ACUTE", "room_type": "ICU",
            },
            item_overrides={
                "sku": "SKU-X-CS", "description": "Restricted commodity, case",
                "manufacturer_code": "MFR-ACME", "uom": "CS", "wac_cents": 5000,
                "handling_class": "AMBIENT", "units_per_parent": 10,
            },
            contract_overrides={
                "manufacturer_code": "MFR-ACME", "contract_code": "CTR-X14",
                "tier": "TIER_1", "member_class_scope": "ACUTE",
            },
            tier_price_cents=1000,
            floor_price_cents=800,
            formulary_overrides={"facility_item_code": "FAC-X", "par_qty": 50,
                                 "reorder_point": 10},
            formulary_decision="RESTRICTED",
        )

    def test_line_write_is_refused_while_the_mapping_is_restricted(self, api):
        """PRD §3.4: "Before the line is accepted, the item must already be
        `APPROVED` on the destination room's formulary — otherwise
        `ERR_ITEM_NOT_ON_FORMULARY` (HTTP 422) — and the price selector of §3.2
        must find a candidate, otherwise `ERR_NO_ACTIVE_CONTRACT_PRICE`
        (HTTP 422)."
        PRD §3.3: "An approved mapping accepts `APPROVED → RESTRICTED`, which
        refuses **new** order lines for that item into that room from then on
        while leaving lines already written untouched, or `APPROVED →
        DELISTED`."

        Design: Difficulty/cross_entity_state_dependency/order_line_write_gated_on_formulary_item_state
        """
        world = self._restricted_mapping_world()

        response = api.create_order_line(
            world["order"]["id"],
            create_order_line_payload(
                world["item"]["id"], 2, world["order"]["version"]
            ),
            make_materials_manager_headers(world["room"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ITEM_NOT_ON_FORMULARY.value, 422)

        after = read_order(world["order"]["id"])
        assert after["version"] == world["order"]["version"]
        assert after["order_total_cents"] == 0

    def test_the_same_line_write_succeeds_once_the_mapping_is_approved(self, api):
        """PRD §3.3: "A restricted mapping accepts `RESTRICTED → APPROVED`,
        closing the approve-and-restrict cycle, or `RESTRICTED → DELISTED`."
        PRD §3.4: "Before the line is accepted, the item must already be
        `APPROVED` on the destination room's formulary — otherwise
        `ERR_ITEM_NOT_ON_FORMULARY` (HTTP 422) — and the price selector of §3.2
        must find a candidate, otherwise `ERR_NO_ACTIVE_CONTRACT_PRICE`
        (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/order_line_write_gated_on_formulary_item_state
        """
        world = self._restricted_mapping_world()

        api.create_order_line(
            world["order"]["id"],
            create_order_line_payload(
                world["item"]["id"], 2, world["order"]["version"]
            ),
            make_materials_manager_headers(world["room"]["id"]),
        )

        approved = decide_formulary_item(world["formulary_item"]["id"], "APPROVED")
        assert approved["formulary_status"] == "APPROVED"

        line = add_order_line(
            world["order"]["id"], world["room"]["id"], world["item"]["id"], 2,
            world["order"]["version"],
        )
        assert line["pinned_unit_price_cents"] == 1000
        assert line["extended_price_cents"] == 2000
        assert line["line_fee_cents"] == 55
        assert read_order(world["order"]["id"])["order_total_cents"] == 2055
