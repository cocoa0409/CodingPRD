"""Project intake, response envelope, and request-shape compliance tests."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_project,
    create_contractor_payload,
    create_homeowner_payload,
    create_moisture_assessment_payload,
    create_project_payload,
    create_subcontractor_payload,
    get_success_data,
    is_iso8601_timestamp,
    make_contractor_headers,
    setup_intake_project,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestProjectCreation:
    def test_project_creation_success(self, api):
        """PRD §3.1: "A new project starts in `INTAKE` with `strike_count` at zero and
        `version` at 1; `last_resumed_at` stays null until the first resume, and
        `approved_design_id` stays null until the first design approval."
        PRD §3.1: "The server stamps the acting contractor's identity onto the project
        as `contractor_id`; that value never arrives through the request body."

        Design: Corner/entities/project_creation_success
        """
        ctr = get_success_data(
            api.create_contractor(
                create_contractor_payload(name="GC C1", license_no="LIC-C1"), ADMIN
            )
        )
        ctr_h = make_contractor_headers(ctr["id"])
        ho = get_success_data(
            api.create_homeowner(
                create_homeowner_payload(name="H C1", email="hc1@x.com", phone="c1"),
                ctr_h,
            )
        )
        res = api.create_project(
            create_project_payload(
                ho["id"],
                address="1 Corner Way",
                basement_sqft=800,
                base_contract_cents=4000000,
            ),
            ctr_h,
        )
        proj = validate_success(res, 201)
        assert_project(proj)
        assert proj["status"] == "INTAKE"
        assert proj["version"] == 1
        assert proj["strike_count"] == 0
        assert proj["contractor_id"] == ctr["id"], (
            "contractor_id must be stamped from the acting Contractor identity"
        )
        assert proj["address"] == "1 Corner Way"
        assert proj["basement_sqft"] == 800
        assert proj["base_contract_cents"] == 4000000

    def test_project_missing_required_base_contract_returns_400(self, api):
        """PRD §2.6: "Request shape — deliberately last: required fields present, types
        and enum members valid, dates ISO-formatted with the start not after the end
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/project_missing_required_base_contract_returns_400
        """
        ctr = get_success_data(
            api.create_contractor(
                create_contractor_payload(name="GC C2", license_no="LIC-C2"), ADMIN
            )
        )
        ctr_h = make_contractor_headers(ctr["id"])
        ho = get_success_data(
            api.create_homeowner(
                create_homeowner_payload(name="H C2", email="hc2@x.com", phone="c2"),
                ctr_h,
            )
        )
        payload = create_project_payload(
            ho["id"], address="2 Corner Way", basement_sqft=800
        )
        del payload["base_contract_cents"]
        res = api.create_project(payload, ctr_h)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_subcontractor_invalid_trade_enum_rejected(self, api):
        """PRD §3.1: "each trade crew by its `name` and `trade` — one of `DEMOLITION`,
        `FRAMING`, `PLUMBING`, `ELECTRICAL`, `HVAC`, `INSULATION`, `DRYWALL`,
        `FLOORING`, `PAINT`, or `GENERAL`."
        PRD §2.6: "Request shape — deliberately last: required fields present, types
        and enum members valid, dates ISO-formatted with the start not after the end
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/subcontractor_invalid_trade_enum_rejected
        """
        res = api.create_subcontractor(
            create_subcontractor_payload(name="Roof Co", trade="ROOFING"), ADMIN
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestExistence:
    def test_project_not_found_returns_404(self, api):
        """PRD §2.6: "Path resolution: every identifier in the URL must exist and nest
        correctly under its parent, validated strictly left-to-right so that the first
        missing or mis-nested segment decides the failure (`ERR_NOT_FOUND`)."

        Design: Corner/entities/project_not_found_returns_404
        """
        ctr = get_success_data(
            api.create_contractor(
                create_contractor_payload(name="GC C8", license_no="LIC-C8"), ADMIN
            )
        )
        res = api.get_project(NON_EXISTENT_UUID, make_contractor_headers(ctr["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_child_create_under_missing_parent_returns_404(self, api):
        """PRD §2.6: "Path resolution: every identifier in the URL must exist and nest
        correctly under its parent, validated strictly left-to-right so that the first
        missing or mis-nested segment decides the failure (`ERR_NOT_FOUND`)."

        Design: Corner/entities/child_create_under_missing_parent_returns_404
        """
        ctr = get_success_data(
            api.create_contractor(
                create_contractor_payload(name="GC C9", license_no="LIC-C9"), ADMIN
            )
        )
        res = api.create_moisture_assessment(
            NON_EXISTENT_UUID,
            create_moisture_assessment_payload(),
            make_contractor_headers(ctr["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestListingAndEnvelope:
    def test_list_projects_pagination_envelope(self, api):
        """PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."
        PRD §3.1: "the project list can be filtered by `homeowner_id`, `contractor_id`,
        `status`, or `approved_design_id`."

        Design: Corner/entities/list_projects_pagination_envelope
        """
        ctr = get_success_data(
            api.create_contractor(
                create_contractor_payload(name="GC C10", license_no="LIC-C10"), ADMIN
            )
        )
        ctr_h = make_contractor_headers(ctr["id"])
        ho_a = get_success_data(
            api.create_homeowner(
                create_homeowner_payload(name="H C10a", email="a@x.com", phone="a"),
                ctr_h,
            )
        )
        ho_b = get_success_data(
            api.create_homeowner(
                create_homeowner_payload(name="H C10b", email="b@x.com", phone="b"),
                ctr_h,
            )
        )
        api.create_project(
            create_project_payload(
                ho_a["id"], address="10a Corner Way", basement_sqft=700,
                base_contract_cents=3000000,
            ),
            ctr_h,
        )
        api.create_project(
            create_project_payload(
                ho_b["id"], address="10b Corner Way", basement_sqft=710,
                base_contract_cents=3100000,
            ),
            ctr_h,
        )

        data, meta = validate_paginated(
            api.list_projects(ctr_h, params={"limit": 1, "offset": 0})
        )
        assert len(data) == 1, f"limit=1 must return exactly 1 item, got {len(data)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0

        filtered, meta_f = validate_paginated(
            api.list_projects(ctr_h, params={"homeowner_id": ho_a["id"]})
        )
        assert meta_f["total_count"] == 1
        assert len(filtered) == 1
        assert filtered[0]["homeowner_id"] == ho_a["id"]

    def test_response_envelope_shape_on_read(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."

        Design: Corner/endpoints/response_envelope_shape_on_read
        """
        ctx = setup_intake_project()
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])

        res = api.get_project(ctx["project"]["id"], ctr_h)
        body = res.json()
        assert res.status_code == 200
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["id"] == ctx["project"]["id"]

        err_res = api.get_project(NON_EXISTENT_UUID, ctr_h)
        err_body = err_res.json()
        assert err_res.status_code == 404
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert len(err_body["data"]["message"]) > 0
