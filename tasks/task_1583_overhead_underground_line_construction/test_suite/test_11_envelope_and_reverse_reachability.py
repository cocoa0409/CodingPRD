"""Response envelope shape and reverse-reachability of foreign keys through the
filtered list endpoints."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_contract_payload,
    is_iso8601_timestamp,
    issue_material,
    report_production,
    request_outage,
    schedule_inspection,
    setup_field_scenario,
    setup_stock_item,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["contractor_pm_headers"]


class TestResponseEnvelope:
    def test_response_envelope_shape_on_success_and_error(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.2: "The `data` field contains the resource object or an array of
        resource objects. For 2xx responses with no data, it contains an empty
        object. Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        create_resp = api.create_contract(
            create_contract_payload(contract_number="CE-1"), PM)
        created = validate_success(create_resp, 201)
        body = create_resp.json()
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id starts with req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert isinstance(created["id"], str) and created["id"], (
            "The created contract object rides in data")

        err_resp = api.get_contract(NON_EXISTENT_UUID, PM)
        error_data = validate_error(err_resp, ApiErrorId.ERR_NOT_FOUND)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert set(err_body["meta"].keys()) == {
            "api_request_id", "api_request_timestamp"}, (
            "The error meta object contains only the two request fields")
        assert error_data["error_id"] == "ERR_NOT_FOUND"
        assert error_data["message"].strip(), "The message explains the error"


class TestReverseReachability:
    def test_fk_reverse_reachability_lists(self, api):
        """PRD §3.2: "The assignment collection lists with filters on
        `work_package_id`, `crew_id`, `equipment_id`, and `status`, and a single
        read includes the assignment's current `version`, which the foreman
        needs for production reporting."
        PRD §3.3: "The production-entry collection lists with filters on
        `assignment_id`, `bid_item_id`, and `status`, and a single read shows
        the entry's status and `rework_count`."
        PRD §3.4: "The material-issue collection lists with filters on
        `work_package_id`, `stock_item_id`, and `status`, and a single read
        shows all four quantities, the `variance`, and the status."
        PRD §3.5: "The inspection collection lists with filters on
        `work_package_id`, `production_entry_id`, and `result`."
        PRD §3.6: "The outage collection lists with filters on
        `work_package_id`, `circuit_id`, and `status`."

        Design: Corner/endpoints/fk_reverse_reachability_lists
        """
        scenario = setup_field_scenario(
            contract_overrides={"contract_number": "CE-2"},
            wp_overrides={"name": "WP fk", "location": "L23"},
            crew_overrides={"crew_code": "CR-FK"},
            equipment_overrides={"equipment_code": "EQ-FK"})
        wp_id = scenario["work_package"]["id"]
        asg_id = scenario["assignment"]["id"]
        crew_id = scenario["crew"]["id"]
        entry = report_production(asg_id, scenario["bid_item"]["id"],
                                  "2026-08-04", 5)
        inspection = schedule_inspection(wp_id, entry["id"], "UTIL-OH-1.0")
        stock = setup_stock_item(scenario["contract"]["id"], initial_on_hand=10,
                                 material_code="MAT-FK", description="FK stock")
        issue = issue_material(wp_id, stock["id"], 2)
        outage = request_outage(wp_id, "CKT-FK",
                                "2026-08-10T08:00:00Z", "2026-08-10T12:00:00Z")

        assignments, _ = validate_paginated(
            api.list_assignments(PM, params={"crew_id": crew_id}))
        assert asg_id in [a["id"] for a in assignments], (
            "GET /assignments?crew_id= returns the crew's assignment")

        entries, _ = validate_paginated(
            api.list_production_entries(PM, params={"assignment_id": asg_id}))
        assert entry["id"] in [e["id"] for e in entries], (
            "GET /production-entries?assignment_id= returns the entry")

        issues, _ = validate_paginated(
            api.list_material_issues(PM, params={"work_package_id": wp_id}))
        assert issue["id"] in [m["id"] for m in issues], (
            "GET /material-issues?work_package_id= returns the issue")

        inspections, _ = validate_paginated(
            api.list_inspections(PM, params={"production_entry_id": entry["id"]}))
        assert inspection["id"] in [i["id"] for i in inspections], (
            "GET /inspections?production_entry_id= returns the inspection")

        outages, _ = validate_paginated(
            api.list_outage_requests(PM, params={"work_package_id": wp_id}))
        assert outage["id"] in [o["id"] for o in outages], (
            "GET /outage-requests?work_package_id= returns the outage")
