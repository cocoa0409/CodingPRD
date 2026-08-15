"""Grower registration, orchard blocks, lot receiving, pagination, and the
response envelope."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_grower,
    assert_lot,
    assert_same_instant,
    create_block_payload,
    create_grower,
    create_grower_payload,
    create_grower_with_block,
    create_lot_payload,
    create_block,
    receive_lot,
    set_logical_clock,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CLERK = TEST_USERS["receiving_clerk_headers"]


class TestGrowerRegistration:
    def test_grower_create_read_uses_logical_clock_default(self, api):
        """PRD §2.4: "When the server starts and the clock has never been set, it
        reads exactly 2026-08-01T00:00:00Z; the logical clock must never fall back
        to wall-clock time."
        PRD §2.5: "`created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits, set at creation."
        PRD §2.5: "`id` (string): a server-minted UUID, with no type prefix."

        Design: Corner/entities/c_grower_create_read_defaults
        """
        resp = api.create_grower(create_grower_payload("Grower One", "G1"), ADMIN)
        grower = validate_success(resp, 201)
        assert_grower(grower)
        assert is_valid_uuid(grower["id"]), "id is a server-minted UUID"
        assert grower["name"] == "Grower One"
        assert isinstance(grower["version"], int), "version is an integer counter"
        assert_same_instant(grower["created_at"], "2026-08-01T00:00:00Z",
                            "created_at reads the logical clock default")

        fetched = validate_success(api.get_grower(grower["id"], ADMIN))
        assert_grower(fetched)
        assert fetched["id"] == grower["id"]
        assert fetched["name"] == "Grower One"
        assert_same_instant(fetched["created_at"], grower["created_at"],
                            "GET returns the same record")

    def test_grower_duplicate_code_rejected(self, api):
        """PRD §3.1: "The code must be unique across all growers and is immutable
        once assigned; a duplicate is rejected with
        `ERR_UNIQUE_CONSTRAINT_VIOLATION`."

        Design: Corner/entities/c_grower_duplicate_code_rejected
        """
        validate_success(
            api.create_grower(create_grower_payload("Grower One", "G1"), ADMIN), 201)
        resp = api.create_grower(create_grower_payload("Grower Dup", "G1"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNIQUE_CONSTRAINT_VIOLATION)


class TestOrchardBlocks:
    def test_block_create_unknown_grower_not_found(self, api):
        """PRD §2.8: "identifiers are validated left to right, and the request is
        rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does
        not resolve to an existing resource."

        Design: Corner/entities/c_block_create_unknown_grower_not_found
        """
        resp = api.create_block(NON_EXISTENT_UUID, create_block_payload(), CLERK)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_block_invalid_variety_enum_rejected(self, api):
        """PRD §2.9: "required fields are present, JSON types are correct, enum
        values fall within their declared sets, percentage fields stay within 0 to
        100"
        PRD §3.1: "the planted `variety` — one of `HONEYCRISP`, `GALA`, `FUJI`,
        `GRANNY_SMITH`, or `COSMIC_CRISP` — and `storage_life_days`"

        Design: Corner/validations/c_block_invalid_variety_enum_rejected
        """
        grower = create_grower()
        resp = api.create_block(
            grower["id"], create_block_payload(variety="RED_DELICIOUS"), CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_block_list_pagination_defaults(self, api):
        """PRD §2.3: "`limit` specifies the maximum number of items returned; when
        omitted it defaults to 10, and it is bounded below by 1 and above by 100.
        `offset` specifies how many items to skip and defaults to 0."

        Design: Corner/entities/c_block_list_pagination_defaults
        """
        grower = create_grower()
        varieties = ["GALA", "GALA", "FUJI", "FUJI", "HONEYCRISP", "HONEYCRISP",
                     "COSMIC_CRISP", "COSMIC_CRISP", "GRANNY_SMITH", "GRANNY_SMITH",
                     "GALA"]
        for i, variety in enumerate(varieties, start=1):
            create_block(grower["id"], variety=variety, block_code=f"B{i:02d}")

        page, meta = validate_paginated(api.list_blocks(grower["id"], ADMIN))
        assert len(page) == 10, "default limit is 10"
        assert meta["total_count"] == 11
        assert meta["has_more"] is True

        tail, meta2 = validate_paginated(api.list_blocks(
            grower["id"], ADMIN, params={"limit": 5, "offset": 10}))
        assert len(tail) == 1, "the tail page holds the single remaining row"
        assert meta2["total_count"] == 11
        assert meta2["has_more"] is False


class TestLotReceiving:
    def test_lot_create_block_grower_mismatch_rejected(self, api):
        """PRD §3.1: "The block must belong to the stated grower: when the block's
        owning grower differs from the lot's `grower_id`, receiving is rejected
        with `ERR_BLOCK_GROWER_MISMATCH`, evaluated at the state-gate tier of
        §2.9."

        Design: Corner/entities/c_lot_create_block_grower_mismatch_rejected
        """
        grower1, block1 = create_grower_with_block(grower_name="Grower One",
                                                   grower_code="G1")
        grower2 = create_grower("Grower Two", "G2")
        resp = api.create_lot(
            create_lot_payload(grower2["id"], block1["id"]), CLERK)
        validate_error(resp, ApiErrorId.ERR_BLOCK_GROWER_MISMATCH)

    def test_lot_received_at_uses_logical_clock_default(self, api):
        """PRD §3.1: "A freshly received lot is stamped with `received_at` from
        the logical clock, enters `RECEIVED` status, and its `weight_balance_lbs`
        is initialized to `received_weight_lbs`."
        PRD §2.4: "When the server starts and the clock has never been set, it
        reads exactly 2026-08-01T00:00:00Z; the logical clock must never fall back
        to wall-clock time."

        Design: Corner/entities/c_lot_received_at_uses_logical_clock_default
        """
        grower, block = create_grower_with_block()
        lot1 = receive_lot(grower["id"], block["id"])
        assert_lot(lot1)
        assert lot1["status"] == "RECEIVED"
        assert lot1["weight_balance_lbs"] == pytest.approx(4000)
        assert_same_instant(lot1["received_at"], "2026-08-01T00:00:00Z",
                            "received_at reads the logical clock default")

        set_logical_clock("2026-08-05T00:00:00Z")
        lot2 = receive_lot(grower["id"], block["id"], received_bin_count=3,
                           received_weight_lbs=2500, avg_color_pct=70)
        assert_same_instant(lot2["received_at"], "2026-08-05T00:00:00Z",
                            "received_at follows the set logical clock")

    def test_lots_filtered_by_block(self, api):
        """PRD §2.3: "The lot list filters by `grower_id`, `block_id`, and
        `status`; the allocation list by `room_id`, `lot_id`, and `status`"

        Design: Corner/endpoints/c_lots_filtered_by_block
        """
        grower = create_grower()
        block1 = create_block(grower["id"], variety="GALA", block_code="B1")
        block2 = create_block(grower["id"], variety="FUJI", block_code="B2")
        lot1 = receive_lot(grower["id"], block1["id"])
        lot2 = receive_lot(grower["id"], block2["id"], received_bin_count=3,
                           received_weight_lbs=2500, avg_color_pct=70)

        data, meta = validate_paginated(
            api.list_lots(ADMIN, params={"block_id": block1["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == lot1["id"], "lot L2 on block B2 is excluded"
        assert data[0]["id"] != lot2["id"]


class TestResponseEnvelope:
    def test_response_envelope_shape(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/c_response_envelope_shape
        """
        grower = create_grower("Grower One", "G1")

        resp = api.get_grower(grower["id"], ADMIN)
        data = validate_success(resp)
        body = resp.json()
        assert body["response_type"] == "object"
        assert data["name"] == "Grower One", "object envelope carries the resource"

        resp_list = api.list_lots(ADMIN)
        validate_success(resp_list)
        assert resp_list.json()["response_type"] == "array"

        resp_err = api.get_grower(NON_EXISTENT_UUID, ADMIN)
        err = validate_error(resp_err, ApiErrorId.ERR_NOT_FOUND)
        body_err = resp_err.json()
        assert body_err["response_type"] == "error"
        assert err["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err["message"], str) and err["message"].strip(), (
            "error envelope carries a human-readable message"
        )
