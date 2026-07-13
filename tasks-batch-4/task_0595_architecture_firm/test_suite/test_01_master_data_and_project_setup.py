"""Firm master data, project opening, request-shape rejection and the read surface."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    assert_project, assert_staff_member, assert_phase,
    create_staff_payload, create_architect_payload, create_project_payload,
    create_phase_payload, create_contract_payload, create_hourly_contract_payload,
    create_time_entry_payload, state_payload,
    make_project_manager_headers, make_staff_architect_headers,
    register_staff, register_architect, setup_project, add_contract,
    PRINCIPAL,
)


class TestProjectAndStaffCreation:

    def test_create_project_starts_in_draft_with_zeroed_counters(self, api):
        """PRD §3.2: "The project is born in status `DRAFT`, with `labor_cost_cents` at 0,
        `approved_hours` at 0, `budget_posture` at `WITHIN_BUDGET`, `open_rfi_count` at 0 and
        `ca_posture` at `CLEAR`."
        PRD §2.4: "an integer `version` that starts at 1 on creation and increments by exactly
        1 on every mutation of that resource."

        Design: Corner/entities/create_project_returns_201_with_defaulted_counters
        """
        pm = register_staff()

        response = api.create_project(
            create_project_payload(
                pm["id"], project_number="ENT-001", name="Entity Estate",
                labor_budget_cents=500_000,
            ),
            PRINCIPAL,
        )
        project = validate_success(response, 201)
        assert_project(project)

        assert project["status"] == "DRAFT"
        assert project["labor_cost_cents"] == 0
        assert project["approved_hours"] == 0
        assert project["budget_posture"] == "WITHIN_BUDGET"
        assert project["ca_posture"] == "CLEAR"
        assert project["open_rfi_count"] == 0
        assert project["version"] == 1

    def test_staff_member_active_defaults_to_true_when_omitted(self, api):
        """PRD §3.1: "A boolean `active` flag governs whether the person may be assigned new
        work; it defaults to `true` when omitted."
        PRD §2.4: "an integer `version` that starts at 1 on creation and increments by exactly
        1 on every mutation of that resource."

        Design: Corner/entities/staff_member_active_defaults_to_true_when_omitted
        """
        payload = create_staff_payload(
            full_name="Dana Designer", title="DESIGNER",
            billing_rate_cents_per_hour=9_000, cost_rate_cents_per_hour=4_000,
        )
        payload.pop("active", None)

        staff = validate_success(api.create_staff(payload, PRINCIPAL), 201)
        assert_staff_member(staff)

        assert staff["active"] is True
        assert staff["version"] == 1

    def test_phase_order_is_derived_from_phase_code_not_from_creation_order(self, api):
        """PRD §3.2: "Each phase's `phase_order` is not supplied by the caller — it is derived
        from the code, with `SD` ordering first, `DD` second, `CD` third and `CA` fourth."
        PRD §3.2: "Phases begin `NOT_STARTED` with `percent_complete` at 0,
        `fee_allocation_cents` at 0, `earned_cents` at 0 and `milestone_status` at `PENDING`."

        Design: Corner/entities/phase_order_is_derived_from_phase_code_and_input_is_ignored
        """
        bundle = setup_project(project_number="ORD-001", labor_budget_cents=500_000,
                               with_architect=False)
        pm_headers = bundle["pm_headers"]

        # Create CA first and SD second: creation order must not leak into phase_order.
        ca = validate_success(
            api.create_phase(
                create_phase_payload(bundle["project_id"], "CA", 2000), pm_headers
            ),
            201,
        )
        sd = validate_success(
            api.create_phase(
                create_phase_payload(bundle["project_id"], "SD", 2000), pm_headers
            ),
            201,
        )
        assert_phase(ca)
        assert_phase(sd)

        assert ca["phase_order"] == 4
        assert sd["phase_order"] == 1
        assert sd["status"] == "NOT_STARTED"
        assert sd["percent_complete"] == 0
        assert sd["fee_allocation_cents"] == 0


class TestStructuralUniqueness:

    def test_duplicate_project_number_is_rejected(self, api):
        """PRD §3.2: "A `PrincipalArchitect` opens a project by supplying a `project_number` —
        which must be unique across the entire firm, on pain of `ERR_DUPLICATE_PROJECT_NUMBER`"

        Design: Corner/validations/duplicate_project_number_is_rejected
        """
        pm = register_staff()
        validate_success(
            api.create_project(
                create_project_payload(pm["id"], project_number="PN-001", name="First",
                                       labor_budget_cents=500_000),
                PRINCIPAL,
            ),
            201,
        )

        response = api.create_project(
            create_project_payload(pm["id"], project_number="PN-001", name="Second",
                                   labor_budget_cents=500_000),
            PRINCIPAL,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_PROJECT_NUMBER.value)

        rows, meta = validate_paginated(
            api.list_projects(PRINCIPAL, params={"project_manager_staff_id": pm["id"]})
        )
        assert meta["total_count"] == 1, "the rejected project must not have been persisted"
        assert len(rows) == 1

    def test_duplicate_phase_code_on_same_project_is_rejected(self, api):
        """PRD §3.2: "Four design phases must then be added to the project, one per `phase_code`
        in `SD`, `DD`, `CD` and `CA`. A repeated code on the same project is rejected with
        `ERR_DUPLICATE_PHASE_CODE`."

        Design: Corner/validations/duplicate_phase_code_on_same_project_is_rejected
        """
        pm = register_staff()
        pm_headers = make_project_manager_headers(pm["id"])
        p1 = validate_success(
            api.create_project(
                create_project_payload(pm["id"], project_number="DUP-001", name="Dup One",
                                       labor_budget_cents=500_000),
                PRINCIPAL,
            ),
            201,
        )
        p2 = validate_success(
            api.create_project(
                create_project_payload(pm["id"], project_number="DUP-002", name="Dup Two",
                                       labor_budget_cents=500_000),
                PRINCIPAL,
            ),
            201,
        )
        validate_success(
            api.create_phase(create_phase_payload(p1["id"], "SD", 2500), pm_headers), 201
        )

        duplicate = api.create_phase(
            create_phase_payload(p1["id"], "SD", 2500, milestone_name="SD again"), pm_headers
        )
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_PHASE_CODE.value)

        rows, _ = validate_paginated(api.list_project_phases(p1["id"], pm_headers))
        assert len(rows) == 1, "the duplicate SD phase must not have been persisted"

        # The same code on a different project is perfectly legal — uniqueness is per project.
        sibling = validate_success(
            api.create_phase(create_phase_payload(p2["id"], "SD", 2500), pm_headers), 201
        )
        assert sibling["phase_code"] == "SD"

    def test_second_contract_on_same_project_is_rejected(self, api):
        """PRD §3.2: "The contract is written next, and exactly one may exist per project — a
        second attempt is rejected with `ERR_CONTRACT_ALREADY_EXISTS`."
        PRD §2.8: "A project's contract is returned as an array of length zero or one, never as
        a bare object, because a project may exist for some time before its contract is written."

        Design: Corner/validations/second_contract_on_same_project_is_rejected
        """
        bundle = setup_project(project_number="ONE-001", labor_budget_cents=500_000,
                               with_architect=False)
        first = add_contract(bundle)

        response = api.create_contract(
            create_hourly_contract_payload(bundle["project_id"], 500_000), PRINCIPAL
        )
        validate_error(response, ApiErrorId.ERR_CONTRACT_ALREADY_EXISTS.value)

        rows, _ = validate_paginated(
            api.get_project_contract(bundle["project_id"], bundle["pm_headers"])
        )
        assert len(rows) == 1
        assert rows[0]["id"] == first["id"]
        assert rows[0]["fee_basis"] == "PERCENT_OF_CONSTRUCTION"


class TestRequestShapeAndExistence:

    def test_missing_required_field_on_create_project_returns_invalid_request(self, api):
        """PRD §2.7: "**Request shape** — required body fields are present, types are correct,
        enum members are valid, and numeric ranges hold (`ERR_INVALID_REQUEST`, 400)."
        PRD §3.2: "and a `labor_budget_cents` ceiling greater than zero for internal labour cost."

        Design: Corner/errors/missing_required_field_on_create_project_returns_invalid_request
        """
        pm = register_staff()
        payload = create_project_payload(pm["id"], project_number="REQ-001",
                                         name="Missing Budget")
        payload.pop("labor_budget_cents")

        validate_error(
            api.create_project(payload, PRINCIPAL), ApiErrorId.ERR_INVALID_REQUEST.value
        )

        _, meta = validate_paginated(
            api.list_projects(PRINCIPAL, params={"project_manager_staff_id": pm["id"]})
        )
        assert meta["total_count"] == 0, "the malformed project must not have been persisted"

    def test_invalid_enum_member_on_create_phase_returns_invalid_request(self, api):
        """PRD §2.7: "**Request shape** — required body fields are present, types are correct,
        enum members are valid, and numeric ranges hold (`ERR_INVALID_REQUEST`, 400)."
        PRD §3.2: "Four design phases must then be added to the project, one per `phase_code`
        in `SD`, `DD`, `CD` and `CA`."

        Design: Corner/errors/invalid_enum_member_on_create_phase_returns_invalid_request
        """
        bundle = setup_project(project_number="ENM-001", labor_budget_cents=500_000,
                               with_architect=False)

        response = api.create_phase(
            {
                "project_id": bundle["project_id"],
                "phase_code": "SDX",
                "weight_bp": 2500,
                "milestone_name": "Bogus",
                "milestone_due_at": "2026-08-01T00:00:00Z",
            },
            bundle["pm_headers"],
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

        rows, _ = validate_paginated(
            api.list_project_phases(bundle["project_id"], bundle["pm_headers"])
        )
        assert len(rows) == 0

    def test_get_project_with_unknown_uuid_returns_project_not_found(self, api):
        """PRD §2.7: "**Path existence** — every resource named by a path parameter exists,
        validated left to right (the `..._NOT_FOUND` family, 404)."

        Design: Corner/entities/get_project_with_unknown_uuid_returns_project_not_found
        """
        validate_error(
            api.get_project(NON_EXISTENT_UUID, PRINCIPAL),
            ApiErrorId.ERR_PROJECT_NOT_FOUND.value,
        )

    def test_state_call_on_unknown_time_entry_returns_time_entry_not_found(self, api):
        """PRD §2.7: "**Path existence** — every resource named by a path parameter exists,
        validated left to right (the `..._NOT_FOUND` family, 404)."
        PRD §2.7: "A phase-completion attempt on a phase that is already `COMPLETED` while the
        project has open RFIs receives `ERR_INVALID_STATE`, because state-machine legality
        (step 9) precedes the open-item gate (step 13)."

        Design: Corner/errors/unknown_time_entry_id_returns_time_entry_not_found
        """
        response = api.set_time_entry_state(
            NON_EXISTENT_UUID, state_payload("APPROVED"), PRINCIPAL
        )
        error = validate_error(response, ApiErrorId.ERR_TIME_ENTRY_NOT_FOUND.value)
        assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value

    def test_unresolvable_body_foreign_key_returns_staff_not_found(self, api):
        """PRD §2.7: "**Body foreign keys** — every foreign key supplied in the request body
        resolves to an existing row (the `..._NOT_FOUND` family, 404)."
        PRD §2.8: "A body foreign key that does not resolve produces the corresponding
        not-found error at step 5 of §2.7."

        Design: Corner/errors/unknown_staff_member_id_in_body_returns_staff_not_found
        """
        bundle = setup_project(project_number="FKX-001", labor_budget_cents=500_000,
                               with_architect=False)

        response = api.create_expense(
            {
                "project_id": bundle["project_id"],
                "staff_member_id": NON_EXISTENT_UUID,
                "category": "TRAVEL",
                "amount_cents": 5_000,
            },
            bundle["pm_headers"],
        )
        validate_error(response, ApiErrorId.ERR_STAFF_NOT_FOUND.value)

        _, meta = validate_paginated(
            api.list_expenses(bundle["pm_headers"], params={"project_id": bundle["project_id"]})
        )
        assert meta["total_count"] == 0

    def test_missing_auth_headers_returns_unauthenticated_ahead_of_existence(self, api):
        """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the five
        declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.7: "1. **Authentication** — the headers are present and `X-User-Role` names one
        of the five roles (`ERR_UNAUTHENTICATED`, 401)."

        Design: Corner/errors/missing_auth_headers_returns_unauthenticated
        """
        response = api.get_project(NON_EXISTENT_UUID, {})
        error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
        assert error["error_id"] != ApiErrorId.ERR_PROJECT_NOT_FOUND.value, (
            "authentication is checked before path existence"
        )


class TestReadSurface:

    def test_success_envelope_carries_meta_and_response_type(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single resource or "array"
        for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request
        that starts with `req_`."

        Design: Corner/endpoints/success_envelope_carries_meta_and_response_type
        """
        bundle = setup_project(project_number="ENV-001", name="Envelope Estate",
                               labor_budget_cents=500_000, with_architect=False)
        pm_headers = bundle["pm_headers"]

        single = api.get_project(bundle["project_id"], pm_headers)
        body = single.json()
        assert single.status_code == 200
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]
        assert body["data"]["id"] == bundle["project_id"]

        listing = api.list_projects(pm_headers, params={"project_manager_staff_id": bundle["pm_id"]})
        list_body = listing.json()
        assert list_body["response_type"] == "array"
        rows, meta = validate_paginated(listing)
        assert len(rows) == 1 and rows[0]["id"] == bundle["project_id"]
        assert meta["total_count"] == 1

    def test_time_entry_list_honours_limit_offset_and_status_filter(self, api):
        """PRD §2.3: "`limit` defaults to 10 when omitted, may be no smaller than 1, and may be
        no larger than 100."
        PRD §2.3: "the `meta` block carries four pagination fields in addition to the two
        request-identification fields: `limit` (the effective page size), `offset` (the effective
        starting position), `total_count` (the number of records matching the filter *before* the
        page window is applied), and `has_more` (true when records remain beyond the current
        window)."

        Design: Corner/endpoints/time_entry_list_supports_limit_offset_and_status_filter
        """
        bundle = setup_project(project_number="PAG-001", name="Page Plaza")
        pm_headers = bundle["pm_headers"]
        sd = validate_success(
            api.create_phase(
                create_phase_payload(bundle["project_id"], "SD", 2500), pm_headers
            ),
            201,
        )
        for day in ("04", "05", "06"):
            validate_success(
                api.create_time_entry(
                    create_time_entry_payload(
                        sd["id"], bundle["arch_id"],
                        start_utc=f"2026-05-{day}T09:00:00Z",
                        end_utc=f"2026-05-{day}T17:00:00Z",
                    ),
                    pm_headers,
                ),
                201,
            )

        page1, meta1 = validate_paginated(
            api.list_time_entries(
                pm_headers,
                params={"staff_member_id": bundle["arch_id"], "status": "DRAFT",
                        "limit": 2, "offset": 0},
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_time_entries(
                pm_headers,
                params={"staff_member_id": bundle["arch_id"], "status": "DRAFT",
                        "limit": 2, "offset": 2},
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        approved, meta3 = validate_paginated(
            api.list_time_entries(
                pm_headers,
                params={"staff_member_id": bundle["arch_id"], "status": "APPROVED"},
            )
        )
        assert len(approved) == 0
        assert meta3["total_count"] == 0


class TestRoleGates:

    def test_staff_architect_cannot_create_a_project(self, api):
        """PRD §2.1: "If the headers are well-formed but the role is not among those authorised
        for the endpoint being called (see the table in §4), the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.2: "A `PrincipalArchitect` opens a project by supplying a `project_number` — which
        must be unique across the entire firm, on pain of `ERR_DUPLICATE_PROJECT_NUMBER` — a
        `name`, the opaque `client_rep_user_id` that will authorise the client's change-order
        decisions, the `project_manager_staff_id` of the `StaffMember` who will run the job, and
        a `labor_budget_cents` ceiling greater than zero for internal labour cost."

        Design: Corner/rbac/staff_architect_cannot_create_a_project_returns_unauthorized
        """
        arch = register_architect()

        response = api.create_project(
            create_project_payload(arch["id"], project_number="RBA-001", name="Not Allowed",
                                   labor_budget_cents=500_000),
            make_staff_architect_headers(arch["id"]),
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_project_manager_cannot_write_to_a_project_they_do_not_manage(self, api):
        """PRD §2.1: "Concretely, every write a `ProjectManager` performs against a project —
        whether directly on the project or on any phase, drawing, time entry, expense, RFI,
        submittal, permit review, field report, change order or invoice belonging to it — is
        rejected with `ERR_NOT_PROJECT_MANAGER` (HTTP 403) unless that project's
        `project_manager_staff_id` equals the caller's `X-User-ID`."

        Design: Corner/rbac/project_manager_cannot_write_to_a_project_they_do_not_manage
        """
        owner = register_staff(full_name="Pat Manager")
        rival = register_staff(full_name="Robin Rival")
        project = validate_success(
            api.create_project(
                create_project_payload(owner["id"], project_number="OWN-001",
                                       name="Owned by PM1", labor_budget_cents=500_000),
                PRINCIPAL,
            ),
            201,
        )

        response = api.create_phase(
            create_phase_payload(project["id"], "SD", 2500),
            make_project_manager_headers(rival["id"]),
        )
        validate_error(response, ApiErrorId.ERR_NOT_PROJECT_MANAGER.value)

        rows, _ = validate_paginated(
            api.list_project_phases(project["id"], make_project_manager_headers(owner["id"]))
        )
        assert len(rows) == 0
