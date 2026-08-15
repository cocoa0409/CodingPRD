"""Foundry commissioning, response envelope, pagination, FK-filtered listing,
and read-after-write visibility."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_charges,
    assert_foundry,
    certify_heat,
    create_foundry,
    create_furnace,
    create_heat,
    create_pattern_payload,
    pour_molds,
    set_clock,
    setup_shop,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["foundry_admin_headers"]
PM = TEST_USERS["pattern_maker_headers"]
MELT = TEST_USERS["melt_supervisor_headers"]
LINE = TEST_USERS["line_operator_headers"]


class TestFoundryCommissioning:
    def test_foundry_create_initializes_posture_embargo(self, api):
        """PRD §3.1: "A new foundry reports `sand_available_kg` of zero,
        `alloy_available_kg` of zero, a `posture` of `EMBARGO` (it holds no
        in-service sand), and an `ops_run_index` of zero."

        Design: Corner/entities/foundry_create_initializes_posture_embargo
        """
        data = validate_success(
            api.create_foundry({"name": "F1"}, ADMIN), expected_status=201
        )
        assert_foundry(data)
        assert data["sand_available_kg"] == 0
        assert data["alloy_available_kg"] == 0
        assert data["posture"] == "EMBARGO"
        assert data["ops_run_index"] == 0


class TestEnvelope:
    def test_success_envelope_shape_on_object_and_error(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources." and "The `error_id` is a unique,
        machine-readable string that identifies the specific error."

        Design: Corner/endpoints/success_envelope_shape_on_object_and_error
        """
        foundry = create_foundry()

        ok_res = api.get_foundry(foundry["id"], ADMIN)
        ok_body = ok_res.json()
        assert ok_res.status_code == 200
        assert ok_body["response_type"] == "object"
        assert isinstance(ok_body["meta"]["api_request_id"], str)
        assert isinstance(ok_body["meta"]["api_request_timestamp"], str)
        assert ok_body["data"]["id"] == foundry["id"]

        bad_res = api.get_foundry(NON_EXISTENT_UUID, ADMIN)
        bad_body = bad_res.json()
        assert bad_res.status_code == 404
        assert bad_body["response_type"] == "error"
        assert bad_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(bad_body["data"]["message"], str)
        assert bad_body["data"]["message"].strip()


class TestNotFoundAndPagination:
    def test_get_missing_pattern_returns_not_found(self, api):
        """PRD §2.10: "Third, existence: path identifiers and body foreign-key
        references must resolve (`ERR_NOT_FOUND`, including the cross-foundry
        rule of §2.11)."

        Design: Corner/entities/get_missing_pattern_returns_not_found
        """
        res = api.get_pattern(NON_EXISTENT_UUID, PM)
        err = validate_error(res, "ERR_NOT_FOUND", expected_status=404)
        assert err["message"].strip()

    def test_list_patterns_pagination_envelope(self, api):
        """PRD §2.3: "List endpoints accept two query parameters. `limit` defaults
        to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0.
        The `meta` object of a list response carries `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/list_patterns_pagination_envelope
        """
        foundry = create_foundry()
        for i in range(3):
            payload = create_pattern_payload(
                foundry["id"], part_number=f"PN-{i}",
                finish_dimensions_mm=[10.0], machining_allowance_mm=1.0,
                impressions=1)
            validate_success(api.create_pattern(payload, PM), expected_status=201)

        data, meta = validate_paginated(
            api.list_patterns(PM, params={"foundry_id": foundry["id"],
                                          "limit": 2, "offset": 0})
        )
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert len(data) == 2


class TestReverseReachability:
    def test_fk_reverse_reachability_lists(self, api):
        """PRD §4: "GET | /api/castings | List castings, filterable by `mold_id`,
        `order_id`, `routing_status`, `quality_status`" and "GET | /api/molds |
        List molds, filterable by `pattern_id`, `sand_batch_id`, `order_id`,
        `pour_slot_id`, `status`" and "GET | /api/pour-slots | List pour slots,
        filterable by `molding_line_id`, `heat_id`, `status`".

        Design: Corner/endpoints/fk_reverse_reachability_lists
        """
        ctx = setup_shop()
        pour_molds(ctx, [{"sand_weight_kg": 50, "metal_weight_kg": 200,
                          "cooling_hours": 2}], tap_weight_kg=500)
        mold = ctx["molds"][0]
        slot = ctx["slot"]
        casting = ctx["castings"][0][0]

        by_mold, _ = validate_paginated(
            api.list_castings(LINE, params={"mold_id": mold["id"]}))
        assert len(by_mold) == 1
        assert by_mold[0]["id"] == casting["id"]
        assert by_mold[0]["order_id"] == ctx["order"]["id"]

        by_order, _ = validate_paginated(
            api.list_castings(LINE, params={"order_id": ctx["order"]["id"]}))
        assert [c["id"] for c in by_order] == [casting["id"]]

        molds_of_slot, _ = validate_paginated(
            api.list_molds(LINE, params={"pour_slot_id": slot["id"]}))
        assert [m["id"] for m in molds_of_slot] == [mold["id"]]

        slots_of_heat, _ = validate_paginated(
            api.list_pour_slots(LINE, params={"heat_id": ctx["heat"]["id"]}))
        assert [s["id"] for s in slots_of_heat] == [slot["id"]]


class TestImmediateConsistency:
    def test_immediate_consistency_read_after_write(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field." PRD §3.4: "A successful tap records `tapped_weight_kg` from the
        payload, stamps `tapped_date` with the UTC date of the logical now,
        initializes `remaining_metal_kg` to the tapped weight, transitions the
        heat to `TAPPED`, and increments its `version`."

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        set_clock("2026-08-10T08:00:00Z")
        foundry = create_foundry()
        furnace = create_furnace(foundry["id"])
        heat = create_heat(foundry["id"], furnace["id"])
        heat = add_charges(heat, [{"source": "VIRGIN", "weight_kg": 1000,
                                   "composition": {"C": 3.40}}])
        heat = certify_heat(heat, {"C": 3.40})

        tap_res = api.tap_heat(heat["id"], {"tap_weight_kg": 700}, MELT)
        tap_data = validate_success(tap_res, expected_status=200)
        assert tap_data["status"] == "TAPPED"
        assert tap_data["tapped_weight_kg"] == 700
        assert tap_data["remaining_metal_kg"] == 700

        get_data = validate_success(api.get_heat(heat["id"], MELT))
        assert get_data["status"] == tap_data["status"]
        assert get_data["remaining_metal_kg"] == tap_data["remaining_metal_kg"]
