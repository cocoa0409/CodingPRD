"""The error envelope, the pagination bounds and the resource-specific not-found catalog."""

from __future__ import annotations

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    get_success_data,
    is_iso8601_timestamp,
    make_certification_agency_headers,
    make_conditioning_manager_headers,
    make_field_officer_headers,
    make_grower,
    make_program_admin_headers,
    make_settlement_accountant_headers,
    validate_error,
    validate_paginated,
)

ERROR_META_KEYS = {"api_request_id", "api_request_timestamp"}
LIMIT_CEILING = 100
LIMIT_FLOOR = 1


class TestErrorEnvelopeShape:
    def test_an_unknown_grower_comes_back_in_the_declared_error_envelope(self, api):
        """The failure carries its identity inside `data`, with a success-shaped `meta`.

        PRD: "All error API responses (4xx status codes) follow this standard envelope format:"

        PRD: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        PRD: "The `error_id` is a unique, machine-readable string that identifies the specific
        error."

        PRD: "The `message` provides a human-readable explanation of what went wrong."

        PRD: "The path parameters and their errors are: `variety_id` yields
        `ERR_VARIETY_NOT_FOUND`; `treatment_product_id` yields `ERR_TREATMENT_PRODUCT_NOT_FOUND`;
        `grower_id` yields `ERR_GROWER_NOT_FOUND`; `production_field_id` yields
        `ERR_PRODUCTION_FIELD_NOT_FOUND`; `field_history_record_id` yields
        `ERR_FIELD_HISTORY_RECORD_NOT_FOUND`; `production_contract_id` yields
        `ERR_CONTRACT_NOT_FOUND`; `field_inspection_id` yields `ERR_INSPECTION_NOT_FOUND`;
        `harvest_equipment_id` yields `ERR_EQUIPMENT_NOT_FOUND`; `harvest_event_id` yields
        `ERR_HARVEST_EVENT_NOT_FOUND`; `conditioning_line_id` yields `ERR_LINE_NOT_FOUND`;
        `seed_lot_id` yields `ERR_SEED_LOT_NOT_FOUND`; `conditioning_run_id` yields
        `ERR_RUN_NOT_FOUND`; `lot_sample_id` yields `ERR_SAMPLE_NOT_FOUND`; `certification_tag_id`
        yields `ERR_TAG_NOT_FOUND`; and `settlement_id` yields `ERR_SETTLEMENT_NOT_FOUND`."

        PRD: "All fifteen carry HTTP 404."

        PRD: "The `api_request_id` is a server-generated unique identifier for the request that
        starts with `req_`."

        PRD: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three
        fractional digits."

        Design: Corner/errors/error_envelope_shape_on_unknown_grower
        """
        grower = make_grower(api)
        headers = make_program_admin_headers()

        success = api.get_grower(grower["id"], headers)
        assert success.status_code == 200
        success_body = success.json()
        assert success_body["response_type"] == "object"

        response = api.get_grower(NON_EXISTENT_UUID, headers)
        error = validate_error(response, "ERR_GROWER_NOT_FOUND", 404)
        assert error["message"].strip() != ""

        body = response.json()
        assert body["response_type"] == "error"
        assert set(body["data"].keys()) == {"error_id", "message"}
        assert "error_id" not in body
        assert "message" not in body

        assert set(body["meta"].keys()) == ERROR_META_KEYS
        assert ERROR_META_KEYS.issubset(set(success_body["meta"].keys()))
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

        still_there = get_success_data(api.get_grower(grower["id"], headers))
        assert still_there["id"] == grower["id"]


class TestPaginationBounds:
    def test_out_of_range_pagination_is_rejected_while_the_bounds_themselves_pass(self, api):
        """101 and -1 are refused outright; 100 and 1 are honoured as declared bounds.

        PRD: "`limit` controls the page size; it defaults to 10 when absent, may not be smaller than
        1 and may not be larger than 100."

        PRD: "`offset` controls how many records are skipped before the page begins; it defaults to 0
        and may not be negative."

        PRD: "A `limit` outside the range of 1 through 100 inclusive, or a negative `offset`, is a
        request-shape failure and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        PRD: "The `meta` block of a list response carries `limit`, `offset`, `total_count` and
        `has_more`, where `total_count` is the number of records matching the filters before
        pagination is applied and `has_more` indicates whether any matching records remain beyond the
        current page."

        Design: Corner/errors/pagination_limit_out_of_range_rejected
        """
        make_grower(api)
        make_grower(
            api,
            grower_name=TEST_DEFAULTS["SECOND_GROWER_NAME"],
            region_code=TEST_DEFAULTS["SECOND_REGION_CODE"],
            contact_email=TEST_DEFAULTS["SECOND_CONTACT_EMAIL"],
        )
        headers = make_program_admin_headers()

        over_limit = api.list_growers(headers, {"limit": LIMIT_CEILING + 1, "offset": 0})
        validate_error(over_limit, "ERR_INVALID_REQUEST", 400)

        negative_offset = api.list_growers(headers, {"limit": 10, "offset": -1})
        validate_error(negative_offset, "ERR_INVALID_REQUEST", 400)

        at_ceiling, ceiling_meta = validate_paginated(
            api.list_growers(headers, {"limit": LIMIT_CEILING, "offset": 0})
        )
        assert ceiling_meta["limit"] == LIMIT_CEILING
        assert ceiling_meta["offset"] == 0
        assert ceiling_meta["total_count"] == 2
        assert ceiling_meta["has_more"] is False
        assert len(at_ceiling) == 2

        at_floor, floor_meta = validate_paginated(
            api.list_growers(headers, {"limit": LIMIT_FLOOR, "offset": 0})
        )
        assert floor_meta["limit"] == LIMIT_FLOOR
        assert floor_meta["total_count"] == 2
        assert floor_meta["has_more"] is True
        assert len(at_floor) == 1


class TestNotFoundCatalogIsResourceSpecific:
    def test_the_same_unknown_id_names_a_different_error_on_every_route(self, api):
        """Twelve path-templated fetches, twelve distinct 404 identities.

        PRD: "Nested paths are resolved strictly left to right."

        PRD: "The path parameters and their errors are: `variety_id` yields
        `ERR_VARIETY_NOT_FOUND`; `treatment_product_id` yields `ERR_TREATMENT_PRODUCT_NOT_FOUND`;
        `grower_id` yields `ERR_GROWER_NOT_FOUND`; `production_field_id` yields
        `ERR_PRODUCTION_FIELD_NOT_FOUND`; `field_history_record_id` yields
        `ERR_FIELD_HISTORY_RECORD_NOT_FOUND`; `production_contract_id` yields
        `ERR_CONTRACT_NOT_FOUND`; `field_inspection_id` yields `ERR_INSPECTION_NOT_FOUND`;
        `harvest_equipment_id` yields `ERR_EQUIPMENT_NOT_FOUND`; `harvest_event_id` yields
        `ERR_HARVEST_EVENT_NOT_FOUND`; `conditioning_line_id` yields `ERR_LINE_NOT_FOUND`;
        `seed_lot_id` yields `ERR_SEED_LOT_NOT_FOUND`; `conditioning_run_id` yields
        `ERR_RUN_NOT_FOUND`; `lot_sample_id` yields `ERR_SAMPLE_NOT_FOUND`; `certification_tag_id`
        yields `ERR_TAG_NOT_FOUND`; and `settlement_id` yields `ERR_SETTLEMENT_NOT_FOUND`."

        PRD: "All fifteen carry HTTP 404."

        Design: Corner/errors/not_found_family_across_path_templated_resources_not_found
        """
        grower = make_grower(api)
        admin = make_program_admin_headers()
        officer = make_field_officer_headers()
        manager = make_conditioning_manager_headers()
        agency = make_certification_agency_headers()
        accountant = make_settlement_accountant_headers()

        probes = [
            (api.get_variety, admin, "ERR_VARIETY_NOT_FOUND"),
            (api.get_treatment_product, admin, "ERR_TREATMENT_PRODUCT_NOT_FOUND"),
            (api.get_production_field, admin, "ERR_PRODUCTION_FIELD_NOT_FOUND"),
            (api.get_production_contract, admin, "ERR_CONTRACT_NOT_FOUND"),
            (api.get_field_inspection, officer, "ERR_INSPECTION_NOT_FOUND"),
            (api.get_harvest_equipment, manager, "ERR_EQUIPMENT_NOT_FOUND"),
            (api.get_conditioning_line, manager, "ERR_LINE_NOT_FOUND"),
            (api.get_conditioning_run, manager, "ERR_RUN_NOT_FOUND"),
            (api.get_seed_lot, manager, "ERR_SEED_LOT_NOT_FOUND"),
            (api.get_lot_sample, agency, "ERR_SAMPLE_NOT_FOUND"),
            (api.get_certification_tag, agency, "ERR_TAG_NOT_FOUND"),
            (api.get_settlement, accountant, "ERR_SETTLEMENT_NOT_FOUND"),
        ]

        seen = []
        for fetch, headers, expected_error_id in probes:
            response = fetch(NON_EXISTENT_UUID, headers)
            error = validate_error(response, expected_error_id, 404)
            assert error["error_id"] != "ERR_NOT_FOUND"
            assert response.json()["data"] is not None
            seen.append(error["error_id"])

        assert len(set(seen)) == len(probes)

        untouched = get_success_data(api.get_grower(grower["id"], admin))
        assert untouched["id"] == grower["id"]
        assert untouched["version"] == grower["version"]
        assert untouched["status"] == "GOOD_STANDING"
