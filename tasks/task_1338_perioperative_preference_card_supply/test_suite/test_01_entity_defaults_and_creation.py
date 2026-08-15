"""Entity defaults, computed card fields, not-found and request-shape checks."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_card_line,
    api_client,
    assert_pct,
    create_supply_item_payload,
    get_success_data,
    is_valid_uuid,
    make_draft_card,
    make_supply_item,
    make_surgeon,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
ANY = TEST_USERS["any_headers"]


class TestSurgeonCreationDefaults:
    def test_surgeon_created_active_with_version_one(self):
        """PRD §3.1: "Newly registered surgeons carry `status` `ACTIVE`."
        PRD §2.4: "`version` (integer): a system-managed integer that
        increments by one on every mutation"

        Design: Corner/entities/surgeon_created_with_active_status_default
        """
        resp = api_client.create_surgeon(
            {"full_name": "Dr. New", "specialty": "ORTHO"}, ANALYST
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        # response envelope
        body = resp.json()
        assert body["response_type"] == "object"

    def test_surgeon_id_is_server_minted_uuid(self):
        """PRD §2.4: "`id` (string): a server-minted UUID with no type prefix."

        Design: Corner/entities/surgeon_created_with_active_status_default
        """
        resp = api_client.create_surgeon(
            {"full_name": "Dr. Minted", "specialty": "CARD"}, ANALYST
        )
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(data["id"])
        assert data["status"] == "ACTIVE"


class TestSupplyItemDefaults:
    def test_supply_item_created_with_system_defaults(self):
        """PRD §3.1: "At creation the item's `on_hand_quantity` is seeded from
        the optional `initial_on_hand`, defaulting to zero, and `status` starts
        as `ACTIVE`. The `consignment_flag` (default false) marks vendor-owned
        stock that is billed when opened."

        Design: Corner/entities/supply_item_created_with_system_defaults
        """
        resp = api_client.create_supply_item(
            {"sku": "SYR-10", "name": "Syringe 10ml", "unit_cost_cents": 75},
            ANALYST,
        )
        created = validate_success(resp, expected_status=201)
        fetched = get_success_data(api_client.get_supply_item(created["id"], ANY))
        assert fetched["on_hand_quantity"] == 0
        assert fetched["consignment_flag"] is False
        assert fetched["status"] == "ACTIVE"


class TestCardVersionNumberSequencing:
    def test_version_number_sequences_within_pair(self):
        """PRD §3.2: "The new card arrives in `DRAFT` status with
        `version_number` set to 1 when no card exists for that
        surgeon-and-procedure pair, or one more than the highest existing
        `version_number` for the pair otherwise."

        Design: Corner/entities/card_version_number_sequences_within_surgeon_procedure_pair
        """
        surgeon = make_surgeon(full_name="Dr. Seq")
        c1 = make_draft_card(surgeon["id"], "TKA")
        c2 = make_draft_card(surgeon["id"], "TKA")
        assert c1["version_number"] == 1
        assert c2["version_number"] == 2

    def test_different_procedure_restarts_sequence(self):
        """PRD §3.2: "The new card arrives in `DRAFT` status with
        `version_number` set to 1 when no card exists for that
        surgeon-and-procedure pair"

        Design: Corner/entities/card_version_number_sequences_within_surgeon_procedure_pair
        """
        surgeon = make_surgeon(full_name="Dr. Seq2")
        make_draft_card(surgeon["id"], "TKA")
        make_draft_card(surgeon["id"], "TKA")
        c3 = make_draft_card(surgeon["id"], "THA")
        assert c3["version_number"] == 1


class TestCardEstimatedCost:
    def test_estimated_cost_recomputed_on_line_add_and_delete(self):
        """PRD §3.2: "The card's `estimated_cost_cents` is a live computed
        field: after every line addition or deletion it is recomputed in full
        as the sum, over the card's current lines regardless of designation, of
        each line's `quantity` multiplied by its item's `unit_cost_cents`."

        Design: Corner/entities/card_estimated_cost_recomputed_on_line_add_and_delete
        """
        surgeon = make_surgeon(full_name="Dr. Est")
        item_a = make_supply_item(sku="GLOVE-PR", name="Gloves pair",
                                  unit_cost_cents=250, substitute_group="GLOVES",
                                  initial_on_hand=100)
        item_b = make_supply_item(sku="SUTURE-KIT", name="Suture kit",
                                  unit_cost_cents=1000, substitute_group="SUTURE",
                                  initial_on_hand=50)
        card = make_draft_card(surgeon["id"], "TKA")
        assert card["estimated_cost_cents"] == 0

        add_card_line(card["id"], item_a["id"], quantity=2, designation="OPEN",
                      pick_sequence=1)
        est1 = get_success_data(api_client.get_preference_card(card["id"], ANY))
        assert est1["estimated_cost_cents"] == 500

        line_b = add_card_line(card["id"], item_b["id"], quantity=1,
                               designation="HOLD", pick_sequence=2)
        est2 = get_success_data(api_client.get_preference_card(card["id"], ANY))
        assert est2["estimated_cost_cents"] == 1500

        resp = api_client.delete_preference_card_line(line_b["id"], ANALYST)
        assert resp.status_code == 204
        est3 = get_success_data(api_client.get_preference_card(card["id"], ANY))
        assert est3["estimated_cost_cents"] == 500


class TestNotFoundAndShape:
    def test_get_unknown_surgeon_returns_not_found(self):
        """PRD §2.4: "A path or body identifier that does not resolve to an
        existing resource yields `ERR_NOT_FOUND` (HTTP 404)."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`. ... The `error_id` is a
        unique, machine-readable string that identifies the specific error."

        Design: Corner/entities/get_unknown_surgeon_returns_not_found
        """
        resp = api_client.get_surgeon("11111111-1111-1111-1111-111111111111", ANY)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert "message" in err and len(err["message"]) > 0
        body = resp.json()
        assert body["response_type"] == "error"
        assert "api_request_id" in body["meta"]

    def test_surgeon_create_missing_required_field(self):
        """PRD §2.7: "**Request body shape**: required fields present, enum
        values valid, integer ranges respected ... — `ERR_INVALID_REQUEST` or
        `ERR_INVALID_QUANTITY`."
        PRD §3.1: "registering each surgeon with a `full_name` and a free-form
        `specialty` label"

        Design: Corner/entities/surgeon_create_missing_required_field_returns_invalid_request
        """
        resp = api_client.create_surgeon({"full_name": "Dr. Nofield"}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_card_line_invalid_enum_returns_invalid_request(self):
        """PRD §3.2: "Every line declares a `quantity` of at least 1 and a
        `designation` of exactly `OPEN` or `HOLD`"
        PRD §2.7: "**Request body shape**: required fields present, enum values
        valid ... — `ERR_INVALID_REQUEST`"

        Design: Corner/entities/card_line_invalid_enum_returns_invalid_request
        """
        surgeon = make_surgeon(full_name="Dr. Enum")
        item = make_supply_item(sku="GLOVE-PR", name="Gloves pair",
                                unit_cost_cents=250, substitute_group="GLOVES",
                                initial_on_hand=100)
        card = make_draft_card(surgeon["id"], "TKA")
        resp = api_client.create_preference_card_line(
            {"card_id": card["id"], "supply_item_id": item["id"],
             "quantity": 1, "designation": "MAYBE", "pick_sequence": 1},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_card_line_with_unknown_card_returns_not_found(self):
        """PRD §2.4: "A path or body identifier that does not resolve to an
        existing resource yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/card_line_with_unknown_card_returns_not_found
        """
        item = make_supply_item(sku="GLOVE-PR", name="Gloves pair",
                                unit_cost_cents=250, substitute_group="GLOVES",
                                initial_on_hand=100)
        resp = api_client.create_preference_card_line(
            {"card_id": "22222222-2222-2222-2222-222222222222",
             "supply_item_id": item["id"], "quantity": 1, "designation": "OPEN"},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestLineValidation:
    def test_duplicate_card_line_rejected(self):
        """PRD §3.2: "A card may not contain two lines for the same item — a
        duplicate (`card_id`, `supply_item_id`) pair is rejected with
        `ERR_DUPLICATE_CARD_LINE`."

        Design: Corner/validations/duplicate_card_line_rejected
        """
        surgeon = make_surgeon(full_name="Dr. Dup")
        item = make_supply_item(sku="GLOVE-PR", name="Gloves pair",
                                unit_cost_cents=250, substitute_group="GLOVES",
                                initial_on_hand=100)
        card = make_draft_card(surgeon["id"], "TKA")
        add_card_line(card["id"], item["id"], quantity=1, designation="OPEN",
                      pick_sequence=1)
        resp = api_client.create_preference_card_line(
            {"card_id": card["id"], "supply_item_id": item["id"],
             "quantity": 2, "designation": "HOLD", "pick_sequence": 2},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CARD_LINE)
        from test_helpers import validate_paginated
        _, meta = validate_paginated(
            api_client.list_preference_card_lines(ANY, params={"card_id": card["id"]})
        )
        assert meta["total_count"] == 1

    def test_quantity_zero_returns_invalid_quantity(self):
        """PRD §2.7: "**Request body shape**: required fields present, enum
        values valid, integer ranges respected (`quantity` at least 1, ...) —
        `ERR_INVALID_REQUEST` or `ERR_INVALID_QUANTITY`."
        PRD §3.2: "Every line declares a `quantity` of at least 1"

        Design: Corner/validations/quantity_zero_returns_invalid_quantity
        """
        surgeon = make_surgeon(full_name="Dr. Zero")
        item = make_supply_item(sku="GLOVE-PR", name="Gloves pair",
                                unit_cost_cents=250, substitute_group="GLOVES",
                                initial_on_hand=100)
        card = make_draft_card(surgeon["id"], "TKA")
        resp = api_client.create_preference_card_line(
            {"card_id": card["id"], "supply_item_id": item["id"],
             "quantity": 0, "designation": "OPEN"},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_QUANTITY)


class TestProductRequestIdentity:
    def test_requester_stamped_from_x_user_id(self):
        """PRD §2.1: "a product request records the acting surgeon's `id` as
        its `surgeon_id`"
        PRD §3.7: "The request's `surgeon_id` is taken from the caller's
        `X-User-ID`, never from the payload, and the request lands in
        `SUBMITTED`."

        Design: Corner/entities/product_request_requester_stamped_from_x_user_id
        """
        from test_helpers import make_surgeon_headers
        surgeon = make_surgeon(full_name="Dr. Stamp", specialty="CARD")
        resp = api_client.create_product_request(
            {"proposed_item_name": "Valve introducer",
             "proposed_sku": "VALVE-INTRO-1",
             "estimated_unit_cost_cents": 4000,
             "rationale": "better implant tray system"},
            make_surgeon_headers(surgeon["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["surgeon_id"] == surgeon["id"]
        assert data["status"] == "SUBMITTED"
        assert data["endorsements_count"] == 0
