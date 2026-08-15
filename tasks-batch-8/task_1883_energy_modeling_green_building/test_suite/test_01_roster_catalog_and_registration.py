"""Consultancy roster, credit catalog, and project registration: creation
defaults, server-minted ids, body conformance, listing pagination, catalog
snapshots, filtered listings, and universal read access."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_certification_project,
    assert_credit_attempt,
    assert_credit_library_entry,
    assert_team_member,
    create_attempt,
    create_credit_entry,
    create_credit_library_entry_payload,
    create_energy_model,
    create_members,
    create_project,
    create_project_payload,
    create_team_member,
    create_team_member_payload,
    get_success_data,
    is_valid_uuid,
    make_any_headers,
    make_project_administrator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANY = TEST_USERS["any_headers"]


class TestTeamMemberRegistration:
    def test_create_team_member_applies_independent_default(self, api):
        """PRD §3.1: "Each **team member** is created with a `full_name`, a
        contact `email` that must be unique across members, a `specialty` of
        `MANAGEMENT`, `MODELING`, `DOCUMENTATION`, or `COMMISSIONING`, and an
        `is_independent` flag that defaults to false."
        PRD §2.4: "`version` — an integer beginning at 1 and incremented on
        every mutation."

        Design: Corner/entities/create_team_member_applies_defaults
        """
        member = validate_success(
            api.create_team_member(
                create_team_member_payload(
                    full_name="Tim Type", email="tim@x.com", specialty="MODELING"),
                ADMIN),
            201,
        )
        assert_team_member(member)
        assert member["is_independent"] is False, "omitted is_independent must default to false"
        assert member["version"] == 1

    def test_create_team_member_ignores_client_supplied_id(self, api):
        """PRD §2.4: "`id` — a server-minted UUID with no type prefix."

        Design: Corner/entities/create_team_member_id_input_ignored
        """
        member = validate_success(
            api.create_team_member(
                create_team_member_payload(
                    id="11111111-1111-1111-1111-111111111111",
                    full_name="Ida Input", email="ida@x.com",
                    specialty="DOCUMENTATION"),
                ADMIN),
            201,
        )
        assert member["id"] != "11111111-1111-1111-1111-111111111111", (
            "the server mints its own id; a client-supplied id must not be honored"
        )
        assert is_valid_uuid(member["id"])


class TestProjectRegistration:
    def test_create_project_missing_required_field_rejected(self, api):
        """PRD §2.7: "2. Body conformance — required fields present, types
        valid, enum members valid, datetime ordering valid; violations yield
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "A `ProjectAdministrator` then registers a **certification
        project** by supplying its `project_name`, the `rating_system` —
        `LEED_BD_C`, `LEED_ID_C`, or `LEED_O_M` — the `compliance_path`, the
        `gross_floor_area_sqft` (a positive whole number of square feet, since
        it drives the certification fee formula of §3.4), the `target_level`
        (`CERTIFIED`, `SILVER`, `GOLD`, or `PLATINUM`), and a non-negative
        `fee_budget_cents` that funds phase submissions."

        Design: Corner/entities/create_project_missing_required_field_invalid_request
        """
        members = create_members()
        payload = create_project_payload(project_name="No Area Tower")
        del payload["gross_floor_area_sqft"]
        resp = api.create_project(
            payload, make_project_administrator_headers(members["admin"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_project_invalid_rating_system_rejected(self, api):
        """PRD §2.7: "2. Body conformance — required fields present, types
        valid, enum members valid, datetime ordering valid; violations yield
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "the `rating_system` — `LEED_BD_C`, `LEED_ID_C`, or
        `LEED_O_M`"

        Design: Corner/validations/create_project_invalid_enum_rejected
        """
        members = create_members()
        resp = api.create_project(
            create_project_payload(project_name="Enum Tower", rating_system="LEED_V5"),
            make_project_administrator_headers(members["admin"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCreditCatalog:
    def test_credit_library_entries_default_page_paginates(self, api):
        """PRD §2.3: "`limit` caps the number of returned items; it defaults to
        10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the envelope's `meta` object."

        Design: Corner/entities/list_credit_library_entries_paginates
        """
        for i in range(1, 12):
            get_success_data(
                api.create_credit_library_entry(
                    create_credit_library_entry_payload(
                        credit_code=f"C{i:02d}", title=f"Credit {i}", points_possible=1),
                    ADMIN),
                201,
            )
        data, meta = validate_paginated(api.list_credit_library_entries(ANY))
        assert meta["total_count"] == 11
        assert len(data) == 10, "default page size is 10"
        assert meta["has_more"] is True
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        for entry in data:
            assert_credit_library_entry(entry)

    def test_credit_attempt_snapshots_catalog_fields(self, api):
        """PRD §3.2: "Creation snapshots the catalog: the attempt permanently
        pins the entry's `credit_code`, `points_possible`, and
        `is_prerequisite` at their creation-time values, so later catalog edits
        never rewrite a live strategy."
        PRD §3.2: "The new attempt starts in `SELECTED` with its
        `submission_round` at zero, `pinned_proposed_model_id` null,
        `has_stale_model_pin` false, and `raw_points_earned` and
        `points_awarded` null until an award."

        Design: Corner/entities/credit_attempt_snapshots_entry_fields
        """
        members = create_members()
        entry = create_credit_entry(
            credit_code="EAc9", title="Green Power", category="ENERGY_ATMOSPHERE",
            points_possible=7, is_prerequisite=False, phase_eligibility="DESIGN",
            requires_energy_model=False)
        project = create_project(
            members["admin"]["id"], project_name="Snap Tower", rating_system="LEED_ID_C")
        attempt = validate_success(
            api.create_credit_attempt(
                {"project_id": project["id"], "credit_library_entry_id": entry["id"],
                 "phase": "DESIGN", "documentation_owner_id": members["spec"]["id"]},
                make_project_administrator_headers(members["admin"]["id"])),
            201,
        )
        assert_credit_attempt(attempt)
        assert attempt["credit_code"] == "EAc9"
        assert attempt["points_possible"] == 7
        assert attempt["is_prerequisite"] is False
        assert attempt["status"] == "SELECTED"
        assert attempt["submission_round"] == 0
        assert attempt["pinned_proposed_model_id"] is None
        assert attempt["has_stale_model_pin"] is False
        assert attempt["raw_points_earned"] is None
        assert attempt["points_awarded"] is None


class TestReadAccess:
    def test_any_role_can_read_listings(self, api):
        """PRD §2.1: "Read access is universal: every listing and detail
        endpoint accepts `Any` authenticated role."

        Design: Corner/rbac/any_role_can_read
        """
        members = create_members()
        create_project(members["admin"]["id"], project_name="Read Tower")

        projects, meta = validate_paginated(api.list_projects(make_any_headers("reader-9")))
        assert meta["total_count"] == 1
        assert_certification_project(projects[0])

        members_list, members_meta = validate_paginated(
            api.list_team_members(make_any_headers("reader-9")))
        assert members_meta["total_count"] == 4


class TestFilteredListings:
    def test_filtered_lists_resolve_children_from_parent_id(self, api):
        """PRD §3.2: "Attempt listings filter by `project_id`,
        `credit_library_entry_id`, `documentation_owner_id`,
        `pinned_proposed_model_id`, `status`, or `phase`."
        PRD §3.3: "Models list filtered by `project_id`, `model_type`,
        `status`, or `created_by`."

        Design: Corner/endpoints/filtered_list_reverse_reachability
        """
        members = create_members()
        entry = create_credit_entry(
            credit_code="WEc1", title="Water Efficiency", category="WATER",
            points_possible=2, is_prerequisite=False, phase_eligibility="DESIGN",
            requires_energy_model=False)
        p1 = create_project(members["admin"]["id"], project_name="P1")
        p2 = create_project(
            members["admin"]["id"], project_name="P2", rating_system="LEED_ID_C",
            gross_floor_area_sqft=5000, target_level="SILVER")
        attempt = create_attempt(
            p1["id"], entry["id"], members["spec"]["id"], members["admin"]["id"])
        baseline = create_energy_model(
            p1["id"], members["modeler"]["id"], "BASELINE",
            modeled=12000000, confirmed=12000000)

        data, meta = validate_paginated(
            api.list_credit_attempts(ANY, params={"project_id": p1["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == attempt["id"]

        data, meta = validate_paginated(
            api.list_credit_attempts(ANY, params={"project_id": p2["id"]}))
        assert meta["total_count"] == 0
        assert data == []

        data, meta = validate_paginated(
            api.list_energy_models(
                ANY, params={"project_id": p1["id"], "model_type": "PROPOSED"}))
        assert meta["total_count"] == 0

        data, meta = validate_paginated(
            api.list_energy_models(
                ANY, params={"project_id": p1["id"], "model_type": "BASELINE"}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == baseline["id"]
