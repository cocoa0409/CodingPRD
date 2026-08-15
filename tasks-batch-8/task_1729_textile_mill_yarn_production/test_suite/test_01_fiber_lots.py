"""Fiber lot receiving: creation defaults, field validation, retrieval, pagination."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_fiber_lot,
    create_fiber_lot,
    create_fiber_lot_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["mill_planner_headers"]


class TestFiberLotCreation:
    def test_fiber_lot_create_returns_201_with_defaults(self, api):
        """PRD §3.1: "Receiving a fiber lot records its `fiber_type` — one of `COTTON`, `POLYESTER`, `RAYON`, `WOOL`, or `NYLON` — its gross `received_weight_lbs` (strictly greater than zero), and its `unit_cost_per_lb` (zero or greater)."
        PRD §3.1: "The lot's `available_weight_lbs` is initialized equal to the received weight and is thereafter maintained by blend consumption: it can never fall below zero nor exceed the received weight. New lots begin life in `RECEIVED` status."
        PRD §2.4: "`id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/fiber_lot_create_returns_201_with_defaults
        """
        resp = api.create_fiber_lot(
            create_fiber_lot_payload(
                fiber_type="COTTON", received_weight_lbs=500.0, unit_cost_per_lb=1.5
            ),
            PLANNER,
        )
        lot = validate_success(resp, 201)
        assert_fiber_lot(lot)
        assert lot["status"] == "RECEIVED", "A new fiber lot begins life in RECEIVED"
        assert lot["available_weight_lbs"] == pytest.approx(500.0), (
            "available_weight_lbs initializes equal to the received weight"
        )
        assert is_valid_uuid(lot["id"]), "id is a server-minted UUID"

        fetched = validate_success(api.get_fiber_lot(lot["id"], PLANNER))
        assert fetched["status"] == "RECEIVED"
        assert fetched["available_weight_lbs"] == pytest.approx(500.0)

    def test_fiber_lot_missing_fiber_type_rejected(self, api):
        """PRD §2.5: "A request whose payload is malformed, missing a required field, or violates a field's type or range — a non-positive weight, a `hand_score` outside the 1–5 band, a shrinkage percentage outside 0–100 — is rejected with `ERR_INVALID_REQUEST`."
        PRD §3.1: "Receiving a fiber lot records its `fiber_type` — one of `COTTON`, `POLYESTER`, `RAYON`, `WOOL`, or `NYLON` — its gross `received_weight_lbs` (strictly greater than zero), and its `unit_cost_per_lb` (zero or greater)."

        Design: Corner/entities/fiber_lot_missing_required_field_returns_invalid_request
        """
        payload = create_fiber_lot_payload(received_weight_lbs=500.0,
                                           unit_cost_per_lb=1.5)
        del payload["fiber_type"]
        resp = api.create_fiber_lot(payload, PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _data, meta = validate_paginated(api.list_fiber_lots(PLANNER))
        assert meta["total_count"] == 0, "No lot may be persisted by the rejected create"

    def test_fiber_lot_invalid_enum_rejected(self, api):
        """PRD §3.1: "Receiving a fiber lot records its `fiber_type` — one of `COTTON`, `POLYESTER`, `RAYON`, `WOOL`, or `NYLON` — its gross `received_weight_lbs` (strictly greater than zero), and its `unit_cost_per_lb` (zero or greater)."
        PRD §2.5: "A request whose payload is malformed, missing a required field, or violates a field's type or range — a non-positive weight, a `hand_score` outside the 1–5 band, a shrinkage percentage outside 0–100 — is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/fiber_lot_invalid_enum_rejected
        """
        resp = api.create_fiber_lot(
            create_fiber_lot_payload(
                fiber_type="SILK", received_weight_lbs=100.0, unit_cost_per_lb=5.0
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_system_fields_input_ignored(self, api):
        """PRD §2.4: "`id` is a server-minted UUID with no type prefix."
        PRD §2.4: "`version` is a system-managed integer that increments by one on every mutation, including mutations caused by cascade side effects from operations on related resources."

        Design: Corner/entities/system_fields_input_ignored
        """
        supplied_id = "aaaaaaaa-1111-1111-1111-111111111111"
        payload = create_fiber_lot_payload(
            fiber_type="COTTON", received_weight_lbs=100.0, unit_cost_per_lb=1.5
        )
        payload["id"] = supplied_id
        payload["version"] = 99
        lot = validate_success(api.create_fiber_lot(payload, PLANNER), 201)
        assert lot["id"] != supplied_id, (
            "The server mints the id; a client-supplied id is ignored"
        )
        assert is_valid_uuid(lot["id"])
        assert lot["version"] != 99, (
            "version is system-managed; a client-supplied 99 must not persist"
        )


class TestFiberLotRetrieval:
    def test_fiber_lot_get_by_id_returns_stored_data(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.1: "Receiving a fiber lot records its `fiber_type` — one of `COTTON`, `POLYESTER`, `RAYON`, `WOOL`, or `NYLON` — its gross `received_weight_lbs` (strictly greater than zero), and its `unit_cost_per_lb` (zero or greater)."

        Design: Corner/entities/fiber_lot_get_by_id_returns_stored_data
        """
        created = create_fiber_lot(
            received_weight_lbs=250.5, unit_cost_per_lb=2.25, fiber_type="POLYESTER"
        )
        fetched = validate_success(api.get_fiber_lot(created["id"], PLANNER))
        assert_fiber_lot(fetched)
        assert fetched["fiber_type"] == "POLYESTER"
        assert fetched["received_weight_lbs"] == pytest.approx(250.5)
        assert fetched["unit_cost_per_lb"] == pytest.approx(2.25)

    def test_fiber_lot_get_nonexistent_returns_404(self, api):
        """PRD §2.7: "The request is rejected with `ERR_NOT_FOUND` at the first path identifier that does not resolve to an existing resource, before any later identifier or body field is examined."

        Design: Corner/entities/fiber_lot_get_nonexistent_returns_404
        """
        resp = api.get_fiber_lot(NON_EXISTENT_UUID, PLANNER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_fiber_lot_list_pagination(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0."
        PRD §2.3: "Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object."

        Design: Corner/entities/fiber_lot_list_pagination
        """
        create_fiber_lot(received_weight_lbs=100.0, unit_cost_per_lb=1.0)
        create_fiber_lot(received_weight_lbs=200.0, unit_cost_per_lb=1.1)
        create_fiber_lot(received_weight_lbs=300.0, unit_cost_per_lb=1.2,
                         fiber_type="POLYESTER")

        data, meta = validate_paginated(
            api.list_fiber_lots(PLANNER, params={"limit": 2, "offset": 0})
        )
        assert len(data) == 2, "limit=2 caps the page size"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        for lot in data:
            assert_fiber_lot(lot)
