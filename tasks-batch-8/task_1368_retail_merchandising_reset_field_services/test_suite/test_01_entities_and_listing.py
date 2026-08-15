"""Entity creation defaults, input typing, not-found, pagination, evidence
immutability, initial lifecycle states, and sub-resource reverse reachability."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_project_store,
    api_client,
    assert_client,
    create_client,
    create_invoice,
    create_project,
    create_rep,
    create_store,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_field_rep_headers,
    make_scenario,
    schedule_assignment,
    scope_project,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["pm_headers"]
PA = TEST_USERS["payroll_admin_headers"]


class TestClientCreation:
    def test_client_create_defaults_active_status(self, api):
        """PRD 3.1: "A client's lifecycle `status` starts at `ACTIVE` and may
        move through `SUSPENDED` to `TERMINATED`; only an `ACTIVE` client may
        have its projects scoped."
        PRD 2.4: "`id` (string): a unique, server-generated identifier
        formatted as a UUID, with no type prefix."

        Design: Corner/entities/client_create_success_and_defaults
        """
        created = create_client(
            name="New Client", billing_model="PER_STORE", per_store_rate_cents=3000
        )
        cid = created["id"]
        resp = api.get_client(cid, PM)
        data = validate_success(resp)
        assert_client(data)
        assert data["id"] == cid
        assert is_valid_uuid(data["id"]), "client id must be a bare UUID"
        assert data["status"] == "ACTIVE", (
            f"new client must start ACTIVE, got {data['status']}"
        )

    def test_client_create_missing_name_rejected(self, api):
        """PRD 3.1: "A `ProjectManager` onboards a client organization by
        supplying its display `name` and an optional default `billing_model`."
        PRD 2.6: "Finally, raw input sanitization — required fields present and
        correctly typed, enums within their declared sets, non-negative integer
        fields at least 0, and an exception's `sku_count` at least 1 — is
        rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/client_create_missing_name_rejected
        """
        resp = api.create_client(
            {"billing_model": "PER_STORE", "per_store_rate_cents": 3000}, PM
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestRepCreation:
    def test_rep_create_invalid_employment_type_rejected(self, api):
        """PRD 3.1: "The field workforce is administered by a `PayrollAdmin`,
        who registers each rep with a `full_name`, an `employment_type` of
        either `W2` or `C1099`, a `mileage_policy` of either `HOME_BASED` or
        `FIRST_STOP`, and the pay parameters `home_base_commute_miles`,
        `mileage_rate_cents`, and `travel_minute_rate_cents`, each at least 0."
        PRD 2.6: "Finally, raw input sanitization — required fields present and
        correctly typed, enums within their declared sets, non-negative integer
        fields at least 0, and an exception's `sku_count` at least 1 — is
        rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/rep_create_invalid_employment_type_rejected
        """
        resp = api.create_rep(
            {
                "full_name": "Bad Rep",
                "employment_type": "SEASONAL",
                "home_base_commute_miles": 5,
                "mileage_rate_cents": 67,
                "travel_minute_rate_cents": 40,
                "mileage_policy": "HOME_BASED",
            },
            PA,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestNotFound:
    def test_get_project_not_found(self, api):
        """PRD 2.5: "When an endpoint path or request body references multiple
        resources, every path identifier and every body foreign-key reference
        must resolve to an existing entity, validated left to right; the first
        unresolvable reference is rejected with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/entity_not_found_returns_404
        """
        resp = api.get_project(NON_EXISTENT_UUID, PM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestProjectListing:
    def test_project_list_pagination_envelope(self, api):
        """PRD 2.3: "Paginated and non-paginated list-based responses include
        the following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."
        PRD 2.3: "The `limit` parameter specifies the maximum number of items
        to return. If not provided, it defaults to 10, with a minimum of 1 and
        a maximum of 100. The `offset` parameter specifies the number of items
        to skip and defaults to 0."

        Design: Corner/entities/project_list_pagination_envelope
        """
        client = create_client(name="Page Client")
        for title in ("P1", "P2", "P3"):
            create_project(client["id"], title=title)
        resp = api.list_projects(PM, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["total_count"] == 3, (
            f"total_count must be 3, got {meta['total_count']}"
        )
        assert meta["has_more"] is True, "has_more must be true at limit=2 offset=0"
        assert len(data) == 2


class TestPhotoEvidenceImmutability:
    def test_photo_evidence_has_no_version_or_updated_at(self, api):
        """PRD 2.4: "A `PhotoEvidence` record and an `ExceptionReport` record
        carry only `id` and `created_at`; both `updated_at` and `version` are
        absent on these two entities, because they are immutable once filed (an
        exception's later `resolution` change is the one sanctioned mutation,
        and it does not imply a `version` field)."

        Design: Corner/entities/photo_evidence_immutable_no_version
        """
        scn = make_scenario()
        asg = schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], scn["reps"][0]["id"]
        )
        set_clock("2026-08-05T09:30:00Z")
        rep_headers = make_field_rep_headers(scn["reps"][0]["id"])
        visit = validate_success(api.check_in_assignment(asg["id"], rep_headers), 201)
        resp = api.upload_photo(
            visit["id"],
            {
                "photo_type": "BEFORE",
                "image_url": "https://img/x.jpg",
                "captured_at": "2026-08-05T09:30:00Z",
            },
            rep_headers,
        )
        photo = validate_success(resp, 201)
        assert is_valid_uuid(photo.get("id", "")), "photo id must be a UUID"
        assert is_iso8601_timestamp(photo.get("created_at", "")), (
            "photo created_at must be ISO 8601"
        )
        assert "version" not in photo, "PhotoEvidence must not carry version"
        assert "updated_at" not in photo, "PhotoEvidence must not carry updated_at"


class TestInitialStates:
    def test_initial_states_on_creation(self, api):
        """PRD 3.2: "The project is born in `DRAFT` status."
        PRD 3.2: "each row names a `project_id`, a `store_id`, and a `due_date`
        by which the reset must be completed at that store, and is born in
        `PENDING` status with `assigned_rep_id` unset."
        PRD 3.3: "The new assignment is born `SCHEDULED` with `is_rework` false
        for an initial visit."
        PRD 3.7: "A `BillingClerk` may create an `OPEN` invoice manually with
        `client_id`, `project_id`, and an optional `adjustment_cents`
        (defaulting to 0)."

        Design: Corner/state_machines/initial_states_on_creation
        """
        client = create_client(name="Init Client")
        store = create_store()
        project = create_project(client["id"], title="Init Proj", scope_type="AUDIT")
        assert project["status"] == "DRAFT", (
            f"project must be born DRAFT, got {project['status']}"
        )
        ps = add_project_store(project["id"], store["id"])
        assert ps["status"] == "PENDING", (
            f"project-store row must be born PENDING, got {ps['status']}"
        )
        assert ps.get("assigned_rep_id") in (None, ""), (
            "assigned_rep_id must be unset at creation"
        )
        rep = create_rep()
        scope_project(project["id"])
        asg = schedule_assignment(project["id"], ps["id"], rep["id"])
        assert asg["status"] == "SCHEDULED", (
            f"assignment must be born SCHEDULED, got {asg['status']}"
        )
        assert asg["is_rework"] is False
        invoice = create_invoice(client["id"], project["id"])
        assert invoice["status"] == "OPEN", (
            f"manual invoice must be born OPEN, got {invoice['status']}"
        )


class TestReverseReachability:
    def test_project_stores_reverse_reachability(self, api):
        """PRD 4: "GET /retail-reset/projects/{id}/project-stores | List
        store-list rows of a project (sub-resource reverse reachability)."

        Design: Corner/endpoints/fk_reverse_reachability_project_stores
        """
        client = create_client(name="RR Client")
        stores = [create_store() for _ in range(3)]
        proj_1 = create_project(client["id"], title="RR P1")
        proj_2 = create_project(client["id"], title="RR P2")
        ps1 = add_project_store(proj_1["id"], stores[0]["id"])
        ps2 = add_project_store(proj_1["id"], stores[1]["id"])
        add_project_store(proj_2["id"], stores[2]["id"])
        resp = api.list_project_store_rows_of_project(proj_1["id"], PM)
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"expected exactly 2 rows, got {len(data)}"
        ids = {row["id"] for row in data}
        assert ids == {ps1["id"], ps2["id"]}
        for row in data:
            assert row["project_id"] == proj_1["id"], (
                "every returned row must belong to the requested project"
            )
