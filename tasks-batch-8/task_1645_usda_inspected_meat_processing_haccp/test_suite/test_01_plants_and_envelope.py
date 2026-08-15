"""Plant registration defaults, schema validation, retrieval, response
envelope shape, and list pagination."""
import pytest

from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    TEST_USERS,
    assert_pct,
    create_plant_payload,
    create_production_day_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_open_day,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories, fixtures

ADMIN = TEST_USERS["plant_admin_headers"]
PROD = TEST_USERS["production_manager_headers"]
QA = TEST_USERS["qa_manager_headers"]


class TestPlantCreationDefaults:
    def test_plant_creation_applies_documented_defaults(self, api):
        """PRD §3.1: "Registration initializes `operating_status` to `ACTIVE`, both compliance scores to 100, and `cooler_occupied_lbs` to zero."
        PRD §2.5: "`id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix."

        Design: Corner/entities/plant_and_plan_creation_apply_defaults
        """
        resp = api.create_plant(
            create_plant_payload(establishment_number="EST-1645-S"), ADMIN
        )
        plant = validate_success(resp, 201)
        assert is_valid_uuid(plant["id"]), "plant id must be a server-minted UUID"
        assert is_iso8601_timestamp(plant["created_at"])
        assert is_iso8601_timestamp(plant["updated_at"])
        assert isinstance(plant["version"], int)
        assert plant["operating_status"] == "ACTIVE"
        assert plant["provisional_compliance_score"] == 100
        assert plant["official_compliance_score"] == 100
        assert_pct(plant["cooler_occupied_lbs"], 0.0)

    def test_plan_creation_applies_documented_defaults(self, api):
        """PRD §3.2: "A new plan starts in `DRAFT` with `revision_number` zero."

        Design: Corner/entities/plant_and_plan_creation_apply_defaults
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-S2")
        resp = api.create_haccp_plan(
            plant["id"], {"process_type": "RAW_GROUND"}, QA
        )
        plan = validate_success(resp, 201)
        assert is_valid_uuid(plan["id"])
        assert plan["status"] == "DRAFT"
        assert plan["revision_number"] == 0
        assert isinstance(plan["version"], int)


class TestPlantComputedFieldsInputIgnored:
    def test_computed_fields_in_create_payload_are_ignored(self, api):
        """PRD §3.1: "Registration initializes `operating_status` to `ACTIVE`, both compliance scores to 100, and `cooler_occupied_lbs` to zero."

        Design: Corner/entities/plant_computed_fields_input_ignored
        """
        payload = create_plant_payload(establishment_number="EST-1645-T")
        payload["cooler_occupied_lbs"] = 999.0
        payload["official_compliance_score"] = 1
        plant = validate_success(api.create_plant(payload, ADMIN), 201)
        assert_pct(
            plant["cooler_occupied_lbs"], 0.0,
        )
        assert plant["official_compliance_score"] == 100
        assert plant["provisional_compliance_score"] == 100
        assert plant["operating_status"] == "ACTIVE"


class TestPlantSchemaAndExistence:
    def test_missing_establishment_number_returns_invalid_request(self, api):
        """PRD §2.7: "required fields present, types and enum memberships valid, numeric ranges respected (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/plant_missing_required_establishment_number_returns_invalid_request
        """
        payload = {
            "name": "Prairie Packing",
            "district_code": "D25",
            "cooler_capacity_lbs": 10000,
        }
        resp = api.create_plant(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_missing_plant_returns_not_found(self, api):
        """PRD §2.6: "the first identifier that does not resolve rejects the request with `ERR_NOT_FOUND` (HTTP 404) before any later segment is examined."

        Design: Corner/entities/plant_get_not_found_returns_404
        """
        resp = api.get_plant(MISSING_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_invalid_process_type_enum_returns_invalid_request(self, api):
        """PRD §2.7: "required fields present, types and enum memberships valid, numeric ranges respected (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/production_day_invalid_enum_process_type_returns_invalid_request
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-U")
        resp = api.create_production_day(
            plant["id"],
            {"production_date": "2026-08-01", "process_type": "FERMENTED"},
            PROD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestLotsListPagination:
    def test_lots_list_pagination_defaults_and_envelope(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter sets the number of items to skip and defaults to 0."
        PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/lots_list_pagination_defaults_and_envelope
        """
        env = setup_open_day(establishment_number="EST-1645-V")
        lot1 = fixtures.receive_lot(env["day"]["id"], species="BOVINE")
        lot2 = fixtures.receive_lot(
            env["day"]["id"], species="SWINE", head_count=20, live_weight_lbs=5200
        )

        page1, meta1 = validate_paginated(
            api.list_lots(
                QA, params={"production_day_id": env["day"]["id"],
                            "limit": 1, "offset": 0}
            )
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_lots(
                QA, params={"production_day_id": env["day"]["id"],
                            "limit": 1, "offset": 1}
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert page2[0]["id"] != page1[0]["id"], (
            "page 2 must carry the other lot (creation-order ascending)"
        )
        assert {page1[0]["id"], page2[0]["id"]} == {lot1["id"], lot2["id"]}

        # Default limit is 10: both rows come back on one page.
        page_all, meta_all = validate_paginated(
            api.list_lots(QA, params={"production_day_id": env["day"]["id"]})
        )
        assert len(page_all) == 2
        assert meta_all["limit"] == 10
        assert meta_all["has_more"] is False


class TestResponseEnvelope:
    def test_success_and_error_envelope_shapes(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:"
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        resp = api.create_plant(
            create_plant_payload(establishment_number="EST-1645-37"), ADMIN
        )
        assert resp.status_code == 201
        body = resp.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert body["data"]["establishment_number"] == "EST-1645-37"

        err_resp = api.get_plant(MISSING_UUID, ADMIN)
        assert err_resp.status_code == 404
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert len(err_body["data"]["message"].strip()) > 0
