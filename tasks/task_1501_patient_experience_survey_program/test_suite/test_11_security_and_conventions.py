"""Auth headers, RBAC denial, entity-backed ownership, optimistic concurrency
on vendor registration, vendor supersession, the response envelope, and
list pagination (PRD §2.1–§2.6, §2.10, §2.11, §3.1)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    build_user_headers,
    create_cycle_payload,
    create_program_payload,
    create_response_payload,
    create_unit_payload,
    create_vendor_payload,
    get_case,
    get_program,
    get_success_data,
    get_vendor,
    make_program,
    make_steward_headers,
    make_unit,
    make_vendor,
    make_vendor_headers,
    record_response,
    set_clock,
    setup_cycle_in_state,
    setup_program,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
STEWARD = TEST_USERS["steward_headers"]


class TestAuthHeaders:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the user's
        operational capacity. ... A request missing either header, or carrying
        a role that is not one of the declared roles, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        program = make_program(name="P-V1")
        res = api.create_unit(
            create_unit_payload(program["id"], name="U", unit_code="U1"),
            headers={})
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert res.status_code == 400

    def test_undeclared_role_rejected_as_missing_context(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role that
        is not one of the declared roles, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        PRD §2.6: "1. **Headers.** Presence and validity of `X-User-ID` and
        `X-User-Role` (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        program = make_program(name="P-V1B")
        bogus = build_user_headers("test-x-1", "SuperUser")
        res = api.create_unit(
            create_unit_payload(program["id"], name="U", unit_code="U1"),
            bogus)
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert res.status_code == 400


class TestForbiddenRole:
    def test_forbidden_role_denied_on_cycle_create(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /api/cycles is listed with Authorized Role
        `ProgramAdmin`.

        Design: Corner/validations/forbidden_role_denied_on_cycle_create
        """
        program = make_program(name="P-V2")
        res = api.create_cycle(
            create_cycle_payload(program["id"]),
            make_vendor_headers("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert res.status_code == 403
        data, _meta = validate_paginated(
            api.list_cycles(ADMIN, params={"program_id": program["id"]}))
        assert data == []

    def test_forbidden_role_denied_for_data_steward_on_cycle_create(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /api/cycles is listed with Authorized Role
        `ProgramAdmin`.

        Design: Corner/validations/forbidden_role_denied_on_cycle_create
        """
        program = make_program(name="P-V2B")
        res = api.create_cycle(
            create_cycle_payload(program["id"], label="Q1", cycle_index=1),
            make_steward_headers())
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert res.status_code == 403


class TestVendorCaseOwnership:
    def test_vendor_operator_case_ownership(self, api):
        """PRD §2.1: "When `X-User-Role` is `VendorOperator`, `X-User-ID` is
        the `id` of the acting `SurveyVendor`; ownership checks on any resource
        that references a `SurveyVendor` compare the resource's `vendor_id`
        field to `X-User-ID`. A vendor operator submitting a response or a
        delivery disposition for a case whose `vendor_id` does not equal
        `X-User-ID` is rejected with `ERR_VENDOR_CASE_MISMATCH` (HTTP 403)."
        PRD §3.3: "Creation stamps the case with denormalized attribution:
        `vendor_id` is the snapshot of the program's `ACTIVE` vendor at that
        moment"

        Design: Corner/validations/vendor_operator_case_ownership
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V18"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        v1 = ctx["vendor"]
        assert get_case_vendor_id(api, case_id) == v1["id"]

        # A second vendor supersedes V1; the case stays owned by V1.
        program = get_program(ctx["program"]["id"])
        v2 = make_vendor(ctx["program"]["id"], program["version"], name="V2",
                         cycle_budget_cents=50000)

        res = api.create_response(
            create_response_payload(case_id),
            make_vendor_headers(v2["id"]))
        validate_error(res, ApiErrorId.ERR_VENDOR_CASE_MISMATCH)
        assert res.status_code == 403
        assert get_case_status(api, case_id) == "IN_FIELD"

    def test_superseded_vendor_keeps_case_ownership(self, api):
        """PRD §2.1: "A vendor operator submitting a response or a delivery
        disposition for a case whose `vendor_id` does not equal `X-User-ID` is
        rejected with `ERR_VENDOR_CASE_MISMATCH` (HTTP 403)."
        PRD §3.1: "its creation supersedes the program's previously `ACTIVE`
        vendor: that vendor moves to `SUPERSEDED`, its `superseded_at` is
        stamped from the logical clock, and `active_vendor_id` swings to the
        new vendor."

        Design: Corner/validations/vendor_operator_case_ownership
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V18B"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        v1 = ctx["vendor"]
        program = get_program(ctx["program"]["id"])
        v2 = make_vendor(ctx["program"]["id"], program["version"], name="V2",
                         cycle_budget_cents=50000)
        assert get_vendor(v1["id"])["status"] == "SUPERSEDED"

        validate_error(
            api.create_response(
                create_response_payload(
                    case_id, mode_used="MAIL",
                    nurse_comm_score=2, doctor_comm_score=2,
                    cleanliness_score=2, overall_rating_score=2),
                make_vendor_headers(v2["id"])),
            ApiErrorId.ERR_VENDOR_CASE_MISMATCH)
        # The rejected intake left the case untouched.
        assert get_case_status(api, case_id) == "IN_FIELD"
        data, _meta = validate_paginated(api.list_case_responses(case_id, ADMIN))
        assert data == []


def get_case_vendor_id(api, case_id):
    return get_case(case_id)["vendor_id"]


def get_case_status(api, case_id):
    return get_case(case_id)["status"]


class TestOptimisticConcurrency:
    def test_vendor_create_stale_version_rejected(self, api):
        """PRD §2.10: "That request must include `expected_program_version`, a
        non-optional field carrying the `version` of the `SurveyProgram` the
        client last observed. If the program's current `version` has advanced
        since that observation, the request is rejected with
        `ERR_STALE_PROGRAM_VERSION` (HTTP 412), and this check runs before any
        business rule, per §2.6."

        Design: Corner/cross_cutting_layers/vendor_create_stale_version_rejected
        """
        program = make_program(name="P-CC1")
        v1 = make_vendor(program["id"], program["version"], name="V1",
                         cycle_budget_cents=50000)
        # V1's creation bumped the program's version 1 -> 2 (PRD §2.10); the
        # stale expectation of 1 is rejected.
        res = api.create_vendor(
            create_vendor_payload(program["id"], program["version"], name="V2",
                                  cycle_budget_cents=60000),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_STALE_PROGRAM_VERSION)
        assert res.status_code == 412

        assert get_vendor(v1["id"])["status"] == "ACTIVE"
        data, _meta = validate_paginated(
            api.list_vendors(ADMIN, params={"program_id": program["id"]}))
        assert len(data) == 1

    def test_stale_vendor_registration_supersedes_nothing(self, api):
        """PRD §2.10: "If the program's current `version` has advanced since
        that observation, the request is rejected with
        `ERR_STALE_PROGRAM_VERSION` (HTTP 412), and this check runs before any
        business rule, per §2.6. A successful vendor registration increments
        the program's `version` by 1."

        Design: Corner/cross_cutting_layers/vendor_create_stale_version_rejected
        """
        program = make_program(name="P-CC1B")
        v1 = make_vendor(program["id"], program["version"], name="V1",
                         cycle_budget_cents=50000)
        program_after_v1 = get_program(program["id"])
        assert program_after_v1["version"] == program["version"] + 1

        res = api.create_vendor(
            create_vendor_payload(program["id"], program["version"], name="V2",
                                  cycle_budget_cents=60000),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_STALE_PROGRAM_VERSION)
        assert get_program(program["id"])["version"] == (
            program_after_v1["version"])
        assert get_program(program["id"])["active_vendor_id"] == v1["id"]
        data, _meta = validate_paginated(
            api.list_vendors(ADMIN, params={"program_id": program["id"]}))
        assert len(data) == 1


class TestVendorSupersede:
    def test_vendor_supersede_side_effects(self, api):
        """PRD §3.1: "The new vendor starts `ACTIVE` with
        `cycle_budget_remaining_cents` equal to its full budget, and its
        creation supersedes the program's previously `ACTIVE` vendor: that
        vendor moves to `SUPERSEDED`, its `superseded_at` is stamped from the
        logical clock, and `active_vendor_id` swings to the new vendor."
        PRD §2.10: "A successful vendor registration increments the program's
        `version` by 1."

        Design: Corner/state_machines/vendor_supersede_side_effects
        """
        program = make_program(name="P-SM5")
        v1 = make_vendor(program["id"], program["version"], name="V1",
                         cycle_budget_cents=50000)
        program_after_v1 = get_program(program["id"])
        v2 = make_vendor(program["id"], program_after_v1["version"], name="V2",
                         cycle_budget_cents=75000)

        old = get_vendor(v1["id"])
        assert old["status"] == "SUPERSEDED"
        assert old["superseded_at"] == "2026-08-01T00:00:00Z"
        program_now = get_program(program["id"])
        assert program_now["active_vendor_id"] == v2["id"]
        assert program_now["version"] == program["version"] + 2

    def test_second_vendor_repoints_active_vendor_and_bumps_version(self, api):
        """PRD §3.1: "its creation supersedes the program's previously `ACTIVE`
        vendor: that vendor moves to `SUPERSEDED`, its `superseded_at` is
        stamped from the logical clock, and `active_vendor_id` swings to the
        new vendor."
        PRD §2.4: "The logical clock stamps ... `superseded_at` on vendor
        supersession"

        Design: Corner/state_machines/vendor_supersede_side_effects
        """
        program = make_program(name="P-SM5B")
        assert program["version"] == 1
        v1 = make_vendor(program["id"], 1, name="V1",
                         cycle_budget_cents=50000)
        assert get_program(program["id"])["version"] == 2
        v2 = make_vendor(program["id"], 2, name="V2",
                         cycle_budget_cents=75000)
        assert v2["status"] == "ACTIVE"
        assert v2["cycle_budget_remaining_cents"] == 75000
        assert get_vendor(v1["id"])["status"] == "SUPERSEDED"
        assert get_vendor(v1["id"])["superseded_at"] == "2026-08-01T00:00:00Z"
        program_now = get_program(program["id"])
        assert program_now["active_vendor_id"] == v2["id"]
        assert program_now["version"] == 3


class TestResponseEnvelope:
    def test_response_envelope_and_any_role_get(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body:" with
        `meta.api_request_id`, `meta.api_request_timestamp`, `response_type`
        "object" | "array", and `data`.
        PRD §2.1: "(`Any` is a pseudo-role used in this document to mark
        read-only endpoints that every authenticated role may call; it is not
        a real role value.)"

        Design: Corner/endpoints/response_envelope_and_any_role_get
        """
        program = make_program(name="P-EP2")
        for headers in (ADMIN, STEWARD,
                        TEST_USERS["vendor_headers"],
                        TEST_USERS["unit_manager_headers"]):
            res = api.get_program(program["id"], headers)
            assert res.status_code == 200
            body = res.json()
            assert body["response_type"] == "object"
            assert body["data"]["id"] == program["id"]
            assert "api_request_id" in body["meta"]
            assert "api_request_timestamp" in body["meta"]

    def test_success_envelope_carries_meta_and_response_type(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/response_envelope_and_any_role_get
        """
        program = make_program(name="P-EP2B")
        res = api.get_program(program["id"], ADMIN)
        assert res.status_code == 200
        body = res.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]
        assert body["data"]["id"] == program["id"]


class TestListPagination:
    def test_list_pagination_defaults_and_offset(self, api):
        """PRD §2.3: "List endpoints accept two query parameters. `limit`
        specifies the maximum number of items to return: it defaults to 10,
        with a minimum of 1 and a maximum of 100. `offset` specifies the number
        of items to skip and defaults to 0."
        PRD §2.3: "Paginated list responses carry the fields `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/endpoints/list_pagination_defaults_and_offset
        """
        program = make_program(name="P-EP1")
        for i in range(1, 13):
            make_unit(program["id"], name=f"Unit {i:02d}",
                      unit_code=f"U{i:02d}")

        data1, meta1 = validate_paginated(
            api.list_units(ADMIN, params={"program_id": program["id"]}))
        assert len(data1) == 10
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0

        data2, meta2 = validate_paginated(
            api.list_units(ADMIN, params={"program_id": program["id"],
                                          "offset": 10}))
        assert len(data2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False

    def test_pagination_second_page_completes_first_page(self, api):
        """PRD §2.3: "`limit` specifies the maximum number of items to return:
        it defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
        specifies the number of items to skip and defaults to 0."
        PRD §2.3: "Unless otherwise specified, every list endpoint returns its
        resources sorted by `created_at` in ascending order."

        Design: Corner/endpoints/list_pagination_defaults_and_offset
        """
        program = make_program(name="P-EP1B")
        for i in range(1, 13):
            make_unit(program["id"], name=f"Unit {i:02d}",
                      unit_code=f"U{i:02d}")

        page1, meta1 = validate_paginated(
            api.list_units(ADMIN, params={"program_id": program["id"]}))
        page2, meta2 = validate_paginated(
            api.list_units(ADMIN, params={"program_id": program["id"],
                                          "offset": 10}))
        assert len(page1) == 10 and meta1["has_more"] is True
        assert len(page2) == 2 and meta2["has_more"] is False
        ids = [u["id"] for u in page1] + [u["id"] for u in page2]
        assert len(set(ids)) == 12
