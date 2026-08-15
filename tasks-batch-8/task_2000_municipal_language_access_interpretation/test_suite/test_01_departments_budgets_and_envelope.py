"""Departments, budgets, optimistic concurrency, pagination, and envelopes."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_department,
    assert_interpretation_request,
    assert_version_incremented,
    complete_request,
    create_assigned_request,
    create_department,
    create_department_payload,
    get_department,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_liaison_headers,
    set_clock,
    setup_interpretation_workspace,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDepartmentCreationDefaults:
    def test_create_department_applies_defaults(self, api, coordinator_headers):
        """PRD §3.1: "`signage_status` may be supplied at creation and otherwise
        defaults to `CURRENT` (the recognized values are `CURRENT`, `DEFICIENT`,
        and `MISSING`). New departments begin with `spent_cents` at zero, a
        `compliance_score` of 1000 points, and a `posture` of `GOOD_STANDING`."
        PRD §3.1: "`remaining_cents` is the read-only difference between
        `annual_budget_cents` and `spent_cents`"

        Design: Corner/entities/create_department_applies_defaults
        """
        resp = api.create_department(
            create_department_payload(name="Dept Audit", service_area_code="SA-C1",
                                      annual_budget_cents=250000),
            coordinator_headers,
        )
        data = validate_success(resp, 201)
        assert_department(data)
        assert data["signage_status"] == "CURRENT", "default signage must be CURRENT"
        assert data["spent_cents"] == 0
        assert data["remaining_cents"] == 250000, (
            "remaining_cents must equal annual_budget_cents when nothing is spent"
        )
        assert data["compliance_score"] == 1000
        assert data["posture"] == "GOOD_STANDING"
        assert is_valid_uuid(data["id"]), "id must be server-minted UUID"
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert isinstance(data["version"], int), "version must be server-managed"

    def test_create_department_missing_required_budget_returns_invalid_request(
            self, api, coordinator_headers):
        """PRD §3.1: "A `LanguageAccessCoordinator` onboards a department with its
        display `name`, the `service_area_code` it operates in, and an
        `annual_budget_cents` allocation for language services"
        PRD §2.10: "Required fields are present, types match, enum values are
        valid, and numeric ranges hold (counts at least zero; populations,
        encounter totals, word counts, and minute declarations strictly positive;
        `period_start` earlier than `period_end`); computed or system fields
        supplied as input are refused — all as `ERR_VALIDATION`."

        Design: Corner/entities/create_department_missing_required_budget_returns_invalid_request
        """
        resp = api.create_department(
            {"name": "Dept Missing", "service_area_code": "SA-C3"},
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestDepartmentReads:
    def test_get_department_not_found_returns_404(self, api, coordinator_headers):
        """PRD §2.8: "Each unresolvable reference produces the not-found
        identifier for its own resource type: `ERR_DEPARTMENT_NOT_FOUND`,
        `ERR_ASSESSMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_JOB_NOT_FOUND`,
        `ERR_INTERPRETER_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, or
        `ERR_PLAN_NOT_FOUND`."

        Design: Corner/entities/get_department_not_found_returns_404
        """
        resp = api.get_department(NON_EXISTENT_UUID, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_DEPARTMENT_NOT_FOUND.value)

    def test_immediate_read_after_write_visibility(self, api, coordinator_headers):
        """PRD §3.1: "New departments begin with `spent_cents` at zero, a
        `compliance_score` of 1000 points, and a `posture` of `GOOD_STANDING`."
        PRD §3.1: "`remaining_cents` is the read-only difference between
        `annual_budget_cents` and `spent_cents`"

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        created = validate_success(api.create_department(
            create_department_payload(name="Dept Imm", service_area_code="SA-C47",
                                      annual_budget_cents=123456),
            coordinator_headers,
        ), 201)
        fetched = validate_success(
            api.get_department(created["id"], coordinator_headers))
        assert fetched["name"] == "Dept Imm"
        assert fetched["annual_budget_cents"] == 123456
        assert fetched["remaining_cents"] == 123456
        assert fetched["compliance_score"] == 1000
        assert fetched["version"] == created["version"], (
            "the immediately following GET must reflect the created resource"
        )


class TestDepartmentListPagination:
    def test_list_departments_pagination_limit_offset(self, api, coordinator_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10 when omitted, accepts a minimum of 1, and is bounded above
        at 100. The `offset` parameter skips that many items from the front of
        the result set and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.3: "Unless otherwise specified, list endpoints return resources
        sorted by `created_at` in ascending order."

        Design: Corner/endpoints/list_departments_pagination_limit_offset
        """
        # Move the logical clock between creations so created_at values are
        # distinct and the ascending created_at order is well-defined.
        ids = []
        for i, clock in enumerate(("2026-08-01T00:00:00Z", "2026-08-01T00:01:00Z",
                                   "2026-08-01T00:02:00Z"), start=1):
            set_clock(clock)
            ids.append(create_department(name=f"Dept P{i}",
                                         service_area_code=f"SA-C2{i}",
                                         annual_budget_cents=100000)["id"])
        page1, meta1 = validate_paginated(api.list_departments(
            coordinator_headers, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert [d["id"] for d in page1] == ids[:2], (
            "page 1 must hold the two earliest-created departments"
        )
        page2, meta2 = validate_paginated(api.list_departments(
            coordinator_headers, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert page2[0]["id"] == ids[2]


class TestResponseEnvelope:
    def test_response_envelope_success_and_error_shape(self, api, coordinator_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        ok_resp = api.create_department(
            create_department_payload(name="Dept Env", service_area_code="SA-C26",
                                      annual_budget_cents=100000),
            coordinator_headers,
        )
        ok_body = ok_resp.json()
        assert ok_resp.status_code == 201
        assert isinstance(ok_body["meta"]["api_request_id"], str)
        assert ok_body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(ok_body["meta"]["api_request_timestamp"])
        assert ok_body["response_type"] == "object"
        dept_id = ok_body["data"]["id"]
        assert is_valid_uuid(dept_id)

        err_resp = api.get_department(NON_EXISTENT_UUID, coordinator_headers)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == ApiErrorId.ERR_DEPARTMENT_NOT_FOUND.value
        assert isinstance(err_body["data"]["message"], str)
        assert len(err_body["data"]["message"].strip()) > 0


class TestDepartmentPatchOcc:
    def test_occ_department_patch_stale_and_fresh(self, api, coordinator_headers):
        """PRD §2.7: "Such a request must carry `expected_department_version`, a
        non-optional field holding the department `version` the client last
        observed."
        PRD §2.7: "When `expected_department_version` no longer matches the
        department's current `version`, the update is rejected with
        `ERR_STALE_VERSION` (HTTP 412) so the client cannot overwrite state it
        has not observed."
        PRD §2.4: "`version` (integer): a system-managed counter that increments
        by one on every accepted mutation"

        Design: Corner/complexity_layers/occ_department_patch_stale_and_fresh
        """
        dept = create_department(name="Dept OCC", service_area_code="SA-C39",
                                 annual_budget_cents=100000)
        observed_v = dept["version"]

        first = validate_success(api.patch_department(
            dept["id"],
            {"signage_status": "DEFICIENT", "expected_department_version": observed_v},
            coordinator_headers,
        ))
        assert first["signage_status"] == "DEFICIENT"
        assert_version_incremented(first["version"], observed_v)
        fresh_v = first["version"]

        stale = api.patch_department(
            dept["id"],
            {"signage_status": "CURRENT", "expected_department_version": observed_v},
            coordinator_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)
        after_stale = get_department(dept["id"])
        assert after_stale["signage_status"] == "DEFICIENT", (
            "a stale write must not overwrite state the client has not observed"
        )
        assert after_stale["version"] == fresh_v

        fresh = validate_success(api.patch_department(
            dept["id"],
            {"signage_status": "CURRENT", "expected_department_version": fresh_v},
            coordinator_headers,
        ))
        assert fresh["signage_status"] == "CURRENT"
        assert_version_incremented(fresh["version"], fresh_v)


class TestDepartmentFiscalGate:
    def test_patch_budget_below_spent_rejected(self, api, coordinator_headers):
        """PRD §3.1: "Profile updates — a new `name`, `service_area_code`,
        `annual_budget_cents`, or `signage_status` — are Coordinator-only and
        guarded by the optimistic-concurrency rule of §2.7; the budget may never
        be lowered below the already-recorded `spent_cents`, a violation reported
        as `ERR_VALIDATION`."

        Design: Corner/validations/patch_budget_below_spent_rejected
        """
        ws = setup_interpretation_workspace(dept_budget=100000)
        dept_id = ws["department"]["id"]
        interpreter_id = ws["interpreter"]["id"]
        request = create_assigned_request(dept_id, modality="PHONE",
                                          scheduled_duration_minutes=30)
        completed = complete_request(request["id"], interpreter_id, 30)
        assert completed["final_cost_cents"] == 1725, (
            "setup: 30 phone minutes at 50c with a CERTIFIED 1.15 multiplier"
        )
        dept = get_department(dept_id)
        assert dept["spent_cents"] == 1725

        resp = api.patch_department(
            dept_id,
            {"annual_budget_cents": 1000,
             "expected_department_version": dept["version"]},
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
        assert get_department(dept_id)["annual_budget_cents"] == 100000

    def test_department_budget_estimated_cost_gate(self, api, coordinator_headers):
        """PRD §3.6: "The department must then be able to afford the selection:
        `remaining_cents` at least equal to the estimate, an exact fit allowed,
        failing which the creation is rejected with
        `ERR_DEPARTMENT_BUDGET_EXCEEDED`."

        Design: Corner/validations/department_budget_estimated_cost_gate
        """
        dept_poor = create_department(name="Dept Poor", service_area_code="SA-C21",
                                      annual_budget_cents=5000)
        dept_exact = create_department(name="Dept Exact", service_area_code="SA-C22",
                                       annual_budget_cents=9400)
        setup_interpretation_workspace(
            dept_budget=1000000, tier="CERTIFIED", modalities=("IN_PERSON",))
        # The estimate for a 45-minute IN_PERSON CERTIFIED session in business
        # hours: max(60, 48) x 100c x 1.15 + 2500c travel = 9400 cents.
        poor_resp = api.create_interpretation_request(
            {"department_id": dept_poor["id"], "language_code": "es",
             "modality": "IN_PERSON", "encounter_setting": "GENERAL",
             "scheduled_start": "2026-08-02T10:00:00Z",
             "scheduled_duration_minutes": 45},
            make_liaison_headers(dept_poor["id"]),
        )
        validate_error(poor_resp, ApiErrorId.ERR_DEPARTMENT_BUDGET_EXCEEDED.value)
        _, poor_meta = validate_paginated(api.list_interpretation_requests(
            coordinator_headers, params={"department_id": dept_poor["id"]}))
        assert poor_meta["total_count"] == 0, "a rejected request must not persist"

        exact_resp = api.create_interpretation_request(
            {"department_id": dept_exact["id"], "language_code": "es",
             "modality": "IN_PERSON", "encounter_setting": "GENERAL",
             "scheduled_start": "2026-08-02T10:00:00Z",
             "scheduled_duration_minutes": 45},
            make_liaison_headers(dept_exact["id"]),
        )
        assigned = validate_success(exact_resp, 201)
        assert_interpretation_request(assigned)
        assert assigned["status"] == "ASSIGNED"
        assert assigned["estimated_cost_cents"] == 9400, (
            "estimate must exactly equal the 9400-cent budget (exact fit allowed)"
        )
        dept_exact_after = get_department(dept_exact["id"])
        assert dept_exact_after["remaining_cents"] == 9400, (
            "remaining_cents is spent-based; the estimate is committed on the "
            "contract, not drawn from the department"
        )


class TestDepartmentRbac:
    def test_liaison_cannot_create_department(self, api, coordinator_headers):
        """PRD §2.1: "Beyond authentication, each operation restricts which roles
        may invoke it, and some operations add an ownership scope; violations are
        rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §2.10: "The role is permitted for the operation and any ownership
        scope holds — a liaison's `X-User-ID` must equal the `department_id`
        being acted on, an interpreter may submit or complete only their own
        assignments, and only a `ComplianceOfficer` may pass an interpreter
        `status` change — else `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/liaison_cannot_create_department
        """
        home = create_department(name="Dept Home", service_area_code="SA-C32",
                                 annual_budget_cents=100000)
        resp = api.create_department(
            create_department_payload(name="Dept Rogue", service_area_code="SA-C33",
                                      annual_budget_cents=100000),
            make_liaison_headers(home["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
        _, meta = validate_paginated(api.list_departments(coordinator_headers))
        assert meta["total_count"] == 1, "the denied creation must not persist"
