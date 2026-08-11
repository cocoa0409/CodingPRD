"""Process registry, dependency graph, envelope, and access control (PRD §2, §3.1)."""
from test_helpers import (
    ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    create_active_process,
    create_contact,
    create_process,
    make_plan_approver_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProcessCreation:
    def test_process_created_in_draft_with_system_fields(self, api):
        """PRD §3.1: "A new process begins life in `DRAFT`."
        PRD §2.5: "The `id` is a server-minted UUID with no type prefix of any kind. The `created_at` timestamp records creation as an ISO 8601 UTC instant with three fractional digits. The `updated_at` timestamp refreshes on every mutation of the resource. The `version` is an integer that starts at its initial value on creation and increments by one on every mutation — including mutations performed by the server itself as a side effect of another operation, such as a cascade or an adoption re-pin."

        A freshly created process is DRAFT at version 1 with server-minted identity.

        Design: Corner/entities/process_created_in_draft_with_system_fields
        """
        owner = create_contact("Owner Ora", "Owner")
        process = create_process(owner["id"], name="NewProc",
                                 criticality_tier="TIER_1")
        assert process["status"] == "DRAFT"
        assert process["version"] == 1
        assert process["id"] and process["created_at"]


class TestDependencyShape:
    def test_dependency_immutable_after_create(self, api):
        """PRD §2.5: "A `Dependency` edge and a `Notification` record each carry only `id` and `created_at`: both `updated_at` and `version` are absent from these resources, and clients must not expect them."
        PRD §3.1: "Edges may be deleted when they no longer reflect reality, and the collection may be filtered by `from_process_id`, `to_process_id`, or `dependency_type`."

        The created edge carries no version/updated_at and is listed under its
        from_process_id filter exactly once.

        Design: Corner/entities/dependency_immutable_after_create
        """
        owner = create_contact("Owner Ora", "Owner")
        p1 = create_process(owner["id"], name="P1")
        p2 = create_process(owner["id"], name="P2")
        edge = validate_success(
            api_client.create_dependency(
                {"from_process_id": p1["id"], "to_process_id": p2["id"],
                 "dependency_type": "DATA", "criticality": "HIGH"},
                ADMIN_HEADERS),
            expected_status=201)
        assert edge["id"] and edge["created_at"]
        assert "version" not in edge, "a dependency carries no version"
        assert "updated_at" not in edge, "a dependency carries no updated_at"

        listed, meta = validate_paginated(
            api_client.list_dependencies(ADMIN_HEADERS,
                                         params={"from_process_id": p1["id"]}))
        assert len(listed) == 1
        assert listed[0]["id"] == edge["id"]


class TestBlastRadius:
    def test_blast_radius_transitive_count(self, api):
        """PRD §3.1: "Walking edges in their declared direction, starting at the target process, the server collects every process reachable by a directed path — the target itself excluded — and reports the size of that set as `blast_radius` together with the member identifiers in `process_ids`."

        P1 -> P2 -> P3 plus P1 -> P4: blast_radius 3 for P1, 0 for P3.

        Design: Corner/calculations/blast_radius_transitive_count
        """
        owner = create_contact("Owner Ora", "Owner")
        processes = {name: create_process(owner["id"], name=name)
                     for name in ("BR1", "BR2", "BR3", "BR4")}

        def link(src, dst, dep_type, criticality):
            return validate_success(
                api_client.create_dependency(
                    {"from_process_id": processes[src]["id"],
                     "to_process_id": processes[dst]["id"],
                     "dependency_type": dep_type, "criticality": criticality},
                    ADMIN_HEADERS),
                expected_status=201)

        link("BR1", "BR2", "DATA", "HIGH")
        link("BR2", "BR3", "SYSTEM", "MEDIUM")
        link("BR1", "BR4", "STAFF", "LOW")

        first = validate_success(api_client.get_blast_radius(processes["BR1"]["id"],
                                                             ADMIN_HEADERS))
        assert first["blast_radius"] == 3, (
            f"P2, P3 (transitively) and P4 must count, got {first['blast_radius']}"
        )
        assert set(first["process_ids"]) == {
            processes["BR2"]["id"], processes["BR3"]["id"], processes["BR4"]["id"]}
        third = validate_success(api_client.get_blast_radius(processes["BR3"]["id"],
                                                             ADMIN_HEADERS))
        assert third["blast_radius"] == 0


class TestDependencyGraphGuards:
    def test_dependency_self_loop_and_cycle_rejected(self, api):
        """PRD §3.1: "The graph is kept acyclic at all times: an edge whose two ends are the same process is rejected with `ERR_DEPENDENCY_SELF_LOOP`, and an edge that would close a directed cycle is rejected with `ERR_DEPENDENCY_CYCLE`."

        from == to is a self-loop; adding P2 -> P1 after P1 -> P2 closes a cycle.

        Design: Corner/validations/dependency_self_loop_and_cycle_rejected
        """
        owner = create_contact("Owner Ora", "Owner")
        p1 = create_process(owner["id"], name="CycP1")
        p2 = create_process(owner["id"], name="CycP2")
        validate_success(
            api_client.create_dependency(
                {"from_process_id": p1["id"], "to_process_id": p2["id"],
                 "dependency_type": "DATA", "criticality": "HIGH"},
                ADMIN_HEADERS),
            expected_status=201)
        self_loop = api_client.create_dependency(
            {"from_process_id": p1["id"], "to_process_id": p1["id"],
             "dependency_type": "DATA", "criticality": "LOW"},
            ADMIN_HEADERS)
        validate_error(self_loop, ApiErrorId.ERR_DEPENDENCY_SELF_LOOP)
        cycle = api_client.create_dependency(
            {"from_process_id": p2["id"], "to_process_id": p1["id"],
             "dependency_type": "DATA", "criticality": "LOW"},
            ADMIN_HEADERS)
        validate_error(cycle, ApiErrorId.ERR_DEPENDENCY_CYCLE)


class TestListEnvelope:
    def test_process_list_pagination_envelope(self, api):
        """PRD §2.3: "List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.3: "The `limit` parameter sets the maximum number of items returned in one page: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip before the page begins and defaults to 0."

        Three processes paged limit=2 offset=2 yield the last slice with
        has_more false.

        Design: Corner/endpoints/process_list_pagination_envelope
        """
        owner = create_contact("Owner Ora", "Owner")
        for name in ("PageP1", "PageP2", "PageP3"):
            create_process(owner["id"], name=name,
                           criticality_tier={"PageP1": "TIER_1", "PageP2": "TIER_2",
                                             "PageP3": "TIER_3"}[name])
        response = api_client.list_processes(ADMIN_HEADERS,
                                             params={"limit": 2, "offset": 2})
        body = response.json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        data, meta = validate_paginated(response)
        assert len(data) == 1
        assert meta["limit"] == 2
        assert meta["offset"] == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is False


class TestNotFoundAndRbac:
    def test_get_missing_process_returns_not_found(self, api):
        """PRD §2.9: "Each path variable has its own dedicated not-found error: `contactId` maps to `ERR_CONTACT_NOT_FOUND`, `processId` (and the `{id}` segment of process sub-collection routes) to `ERR_PROCESS_NOT_FOUND`, `biaId` to `ERR_BIA_NOT_FOUND`, `planId` to `ERR_PLAN_NOT_FOUND`"
        PRD §2.9: "All not-found rejections carry HTTP 404."

        A well-formed GET against a never-existent process id yields the error
        envelope with ERR_PROCESS_NOT_FOUND.

        Design: Corner/errors/get_missing_process_returns_not_found
        """
        missing = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
        response = api_client.get_process(missing, ADMIN_HEADERS)
        validate_error(response, ApiErrorId.ERR_PROCESS_NOT_FOUND)

    def test_bia_create_forbidden_for_plan_approver(self, api):
        """PRD §2.1: "A request whose role is not listed among the authorized roles of the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "Write and action endpoints are segregated: process registry administration, dependency-graph maintenance, contact registration, alternate-site retirement, and the program clock belong to `ResilienceAdmin`; BIA authoring and submission to `BIAAnalyst`"

        BIA creation is exclusive to BIAAnalyst; a PlanApprover is rejected 403.

        Design: Corner/rbac/bia_create_forbidden_for_plan_approver
        """
        approver = create_contact("Approver Al", "Approver")
        response = api_client.create_bia(
            {"process_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
             "cycle_label": "FY2026-H1", "rto_target_hours": 8,
             "rpo_target_hours": 2, "mtpd_hours": 24, "peak_period_flag": False,
             "impact_financial_per_hour": 100, "impact_regulatory": "NONE",
             "impact_reputational": "NONE", "impact_operational": "NONE"},
            make_plan_approver_headers(approver["id"]))
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
