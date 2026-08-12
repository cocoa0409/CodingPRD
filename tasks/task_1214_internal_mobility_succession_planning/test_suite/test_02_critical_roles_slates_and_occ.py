"""Critical role lifecycle, slate constraints, OCC guards, and supersession."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_version_incremented,
    ApiErrorId, TEST_USERS,
    setup_employee, setup_hrbp, setup_role, setup_active_role,
    add_successor_entry, add_active_successor, activate_entry,
    get_role_version,
    assert_critical_role, assert_successor_entry,
)

ADMIN = TEST_USERS["admin_headers"]


class TestRoleActivationState:
    def test_role_reactivate_returns_role_invalid_state(self, api):
        """PRD §3.2: "Activation binds the role to its incumbent: the role must
        be `PROPOSED` (otherwise `ERR_ROLE_INVALID_STATE`), and the supplied
        `incumbent_employee_id` must reference an existing employee (otherwise
        `ERR_NOT_FOUND`) whose `employment_status` is `ACTIVE` (otherwise
        `ERR_EMPLOYEE_NOT_ACTIVE`)."

        Design: Corner/state_machines/role_reactivate_returns_role_invalid_state
        """
        hrbp, hrbp_headers = setup_hrbp()
        incumbent = setup_employee(employee_code="INC70", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        role = setup_active_role(hrbp_headers, incumbent["id"],
                                 role_title="Role 70", criticality_tier="TIER_3")
        assert role["status"] == "ACTIVE"

        resp = api.activate_critical_role(
            role["id"], {"incumbent_employee_id": incumbent["id"]}, hrbp_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ROLE_INVALID_STATE, 409)
        after = get_success_data(api.get_critical_role(role["id"], hrbp_headers))
        assert after["status"] == "ACTIVE"


class TestSuccessorActivationGating:
    def test_successor_activation_blocked_while_role_proposed(self, api):
        """PRD §3.2: "Activation and reinstatement both require the role to be
        `ACTIVE` or `VACANT`, failing with `ERR_ROLE_NOT_ACTIVE` otherwise, and
        an entry transition attempted from the wrong status fails with
        `ERR_SUCCESSOR_INVALID_STATE` — with the entry-state check evaluated
        before the role-status check."

        Design: Difficulty/cross_entity_state_dependency/successor_activation_blocked_until_role_active
        """
        hrbp, hrbp_headers = setup_hrbp()
        setup_employee(employee_code="INC13", job_level=8,
                       performance_rating="STRONG", hire_date="2019-03-01")
        successor = setup_employee(employee_code="S13", job_level=6,
                                   performance_rating="STRONG", hire_date="2022-07-01")
        role = setup_role(hrbp_headers, role_title="Facilities Lead", department="OPS")
        entry = add_successor_entry(role["id"], successor["id"], hrbp_headers,
                                    readiness_rating="READY_1_2", slate_position=1)
        assert entry["status"] == "DRAFT"

        resp = api.patch_successor(entry["id"], {"status": "ACTIVE"}, hrbp_headers)
        validate_error(resp, ApiErrorId.ERR_ROLE_NOT_ACTIVE, 409)
        role_now = get_success_data(api.get_critical_role(role["id"], hrbp_headers))
        assert role_now["status"] == "PROPOSED"
        entry_now = get_success_data(api.get_successor(entry["id"], hrbp_headers))
        assert entry_now["status"] == "DRAFT"

    def test_successor_activation_succeeds_after_role_activated(self, api):
        """PRD §3.2: "Activation moves `DRAFT` to `ACTIVE`"
        PRD §3.2: "Activation and reinstatement both require the role to be
        `ACTIVE` or `VACANT`, failing with `ERR_ROLE_NOT_ACTIVE` otherwise"
        PRD §3.2: "When an entry joins the `ACTIVE` slate, the `version` of both
        the entry and the role increments"

        Design: Difficulty/cross_entity_state_dependency/successor_activation_blocked_until_role_active
        """
        hrbp, hrbp_headers = setup_hrbp()
        incumbent = setup_employee(employee_code="INC13", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        successor = setup_employee(employee_code="S13", job_level=6,
                                   performance_rating="STRONG", hire_date="2022-07-01")
        role = setup_role(hrbp_headers, role_title="Facilities Lead", department="OPS")
        entry = add_successor_entry(role["id"], successor["id"], hrbp_headers,
                                    readiness_rating="READY_1_2", slate_position=1)

        role = get_success_data(api.activate_critical_role(
            role["id"], {"incumbent_employee_id": incumbent["id"]}, hrbp_headers,
        ))
        assert role["status"] == "ACTIVE"

        updated = validate_success(
            api.patch_successor(entry["id"], {"status": "ACTIVE"}, hrbp_headers), 200,
        )
        assert updated["status"] == "ACTIVE"
        assert_successor_entry(updated)


class TestSlateConstraints:
    def test_duplicate_slate_entry_returns_error(self, api):
        """PRD §3.2: "then the candidate must not already hold another
        non-terminal entry on this role (`ERR_DUPLICATE_SLATE_ENTRY`)"

        Design: Corner/validations/duplicate_slate_entry_returns_error
        """
        hrbp, hrbp_headers = setup_hrbp()
        incumbent = setup_employee(employee_code="INC92", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        successor = setup_employee(employee_code="S92", job_level=6,
                                   performance_rating="STRONG", hire_date="2022-07-01")
        role = setup_active_role(hrbp_headers, incumbent["id"],
                                 role_title="Role 92", criticality_tier="TIER_3")
        add_successor_entry(role["id"], successor["id"], hrbp_headers,
                            readiness_rating="READY_1_2", slate_position=1)

        resp = api.create_successor(role["id"], {
            "employee_id": successor["id"],
            "readiness_rating": "READY_NOW",
            "slate_position": 2,
            "expected_critical_role_version": get_role_version(role["id"], hrbp_headers),
        }, hrbp_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SLATE_ENTRY, 409)

        entries, meta = validate_paginated(
            api.list_successors(hrbp_headers, params={"critical_role_id": role["id"]})
        )
        assert meta["total_count"] == 1, (
            "the role must still hold exactly 1 non-terminal entry"
        )

    def test_slate_position_taken_returns_error(self, api):
        """PRD §3.2: "and finally the requested `slate_position` must be free
        among the role's non-terminal entries, evaluated after any supersede
        removal (`ERR_SLATE_POSITION_TAKEN`)."

        Design: Corner/validations/slate_position_taken_returns_error
        """
        hrbp, hrbp_headers = setup_hrbp()
        incumbent = setup_employee(employee_code="INC93", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        sue_a = setup_employee(employee_code="S93A", job_level=6,
                               performance_rating="STRONG", hire_date="2022-07-01")
        sue_b = setup_employee(employee_code="S93B", job_level=6,
                               performance_rating="STRONG", hire_date="2022-07-01")
        role = setup_active_role(hrbp_headers, incumbent["id"],
                                 role_title="Role 93", criticality_tier="TIER_3")
        add_successor_entry(role["id"], sue_a["id"], hrbp_headers,
                            readiness_rating="READY_1_2", slate_position=1)

        resp = api.create_successor(role["id"], {
            "employee_id": sue_b["id"],
            "readiness_rating": "READY_NOW",
            "slate_position": 1,
            "expected_critical_role_version": get_role_version(role["id"], hrbp_headers),
        }, hrbp_headers)
        validate_error(resp, ApiErrorId.ERR_SLATE_POSITION_TAKEN, 409)


class TestSuccessorListing:
    def test_successor_list_filter_by_status(self, api):
        """PRD §3.2: "Entries can be listed filtered by `critical_role_id`,
        `employee_id`, or `status`."

        Design: Corner/endpoints/successor_list_filter_by_status
        """
        hrbp, hrbp_headers = setup_hrbp()
        incumbent = setup_employee(employee_code="INC110", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        sue_a = setup_employee(employee_code="S110A", job_level=6,
                               performance_rating="STRONG", hire_date="2022-07-01")
        sue_b = setup_employee(employee_code="S110B", job_level=6,
                               performance_rating="STRONG", hire_date="2022-07-01")
        role = setup_active_role(hrbp_headers, incumbent["id"],
                                 role_title="Role 110", criticality_tier="TIER_3")
        entry_a = add_active_successor(role["id"], sue_a["id"], hrbp_headers,
                                       readiness_rating="READY_NOW", slate_position=1)
        entry_b = add_successor_entry(role["id"], sue_b["id"], hrbp_headers,
                                      readiness_rating="READY_1_2", slate_position=2)
        assert entry_b["status"] == "DRAFT"

        data, meta = validate_paginated(api.list_successors(
            hrbp_headers,
            params={"critical_role_id": role["id"], "status": "ACTIVE"},
        ))
        assert meta["total_count"] == 1
        assert [e["id"] for e in data] == [entry_a["id"]], (
            "only the ACTIVE entry of the role must be returned"
        )


class TestOptimisticConcurrency:
    def test_occ_patch_stale_version_returns_412(self, api):
        """PRD §2.7: "Two write operations are guarded by optimistic concurrency
        control against the `CriticalRole` resource: updating a critical role's
        attributes, and adding a successor entry to a critical role's slate."
        PRD §2.7: "If the supplied value does not match the role's current
        `version` — because another writer has advanced the role in the meantime,
        for instance by patching it or by creating a slate entry (including one
        that legitimately supersedes an existing entry under the
        slate-replacement rule) — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/complexity_layers/occ_patch_stale_version_returns_412
        """
        hrbp, hrbp_headers = setup_hrbp()
        role = setup_role(hrbp_headers, role_title="Role 130",
                          criticality_tier="TIER_3")
        observed = role["version"]

        first = validate_success(api.patch_critical_role(role["id"], {
            "role_title": "Role 130 renamed",
            "expected_critical_role_version": observed,
        }, hrbp_headers), 200)
        assert first["role_title"] == "Role 130 renamed"
        assert_version_incremented(first["version"], observed)

        stale = api.patch_critical_role(role["id"], {
            "department": "OPS",
            "expected_critical_role_version": observed,
        }, hrbp_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

        after = get_success_data(api.get_critical_role(role["id"], hrbp_headers))
        assert after["department"] == "ENG", "stale PATCH must not modify the role"
        assert after["role_title"] == "Role 130 renamed"

    def test_occ_successor_create_stale_version_returns_412(self, api):
        """PRD §2.7: "Both require `expected_critical_role_version` as a
        non-optional request field carrying the `version` of the role the client
        last observed."
        PRD §2.7: "If the supplied value does not match the role's current
        `version` — because another writer has advanced the role in the meantime,
        for instance by patching it or by creating a slate entry (including one
        that legitimately supersedes an existing entry under the
        slate-replacement rule) — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/complexity_layers/occ_successor_create_stale_version_returns_412
        """
        hrbp, hrbp_headers = setup_hrbp()
        incumbent = setup_employee(employee_code="INC131", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        sue_a = setup_employee(employee_code="S131A", job_level=6,
                               performance_rating="STRONG", hire_date="2022-07-01")
        sue_b = setup_employee(employee_code="S131B", job_level=6,
                               performance_rating="STRONG", hire_date="2022-07-01")
        role = setup_active_role(hrbp_headers, incumbent["id"],
                                 role_title="Role 131", criticality_tier="TIER_3")
        observed = role["version"]

        first = validate_success(api.create_successor(role["id"], {
            "employee_id": sue_a["id"],
            "readiness_rating": "READY_1_2",
            "slate_position": 1,
            "expected_critical_role_version": observed,
        }, hrbp_headers), 201)
        assert first["status"] == "DRAFT"

        stale = api.create_successor(role["id"], {
            "employee_id": sue_b["id"],
            "readiness_rating": "READY_NOW",
            "slate_position": 2,
            "expected_critical_role_version": observed,
        }, hrbp_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

        entries, meta = validate_paginated(
            api.list_successors(hrbp_headers, params={"critical_role_id": role["id"]})
        )
        assert meta["total_count"] == 1, "no second entry may be created by the stale write"


class TestSlateSupersedeInvariant:
    def _setup_full_slate(self, api):
        """ACTIVE role with 5 DRAFT entries at positions 1..5; a 6th employee
        ready to add. Returns (role, hrbp_headers, entry_ids, sixth_employee)."""
        hrbp, hrbp_headers = setup_hrbp()
        incumbent = setup_employee(employee_code="INC17", department="FIN", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        role = setup_active_role(hrbp_headers, incumbent["id"], role_title="Treasurer",
                                 department="FIN", criticality_tier="TIER_3")
        entry_ids = []
        for i in range(1, 6):
            emp = setup_employee(employee_code=f"G{i}", department="FIN", job_level=5,
                                 performance_rating="SOLID", hire_date="2023-01-15")
            entry = add_successor_entry(role["id"], emp["id"], hrbp_headers,
                                        readiness_rating="READY_1_2", slate_position=i)
            entry_ids.append(entry["id"])
        sixth = setup_employee(employee_code="G6", department="FIN", job_level=5,
                               performance_rating="SOLID", hire_date="2023-01-15")
        return role, hrbp_headers, entry_ids, sixth

    def test_sixth_entry_without_supersede_returns_slate_full(self, api):
        """PRD §3.2: "then the slate must have room — fewer than five
        non-terminal entries — unless `supersede_entry_id` is supplied
        (`ERR_SLATE_FULL`)"

        Design: Difficulty/compensating_invariant/slate_supersede_preserves_cardinality
        """
        role, hrbp_headers, entry_ids, sixth = self._setup_full_slate(api)
        resp = api.create_successor(role["id"], {
            "employee_id": sixth["id"],
            "readiness_rating": "READY_1_2",
            "slate_position": 1,
            "expected_critical_role_version": get_role_version(role["id"], hrbp_headers),
        }, hrbp_headers)
        validate_error(resp, ApiErrorId.ERR_SLATE_FULL, 409)

    def test_supersede_preserves_slate_cardinality(self, api):
        """PRD §3.2: "When `supersede_entry_id` is supplied, the named entry
        first transitions to `REMOVED` — freeing its `slate_position` — and the
        new entry is then created in `DRAFT` within the same request, leaving
        the count of non-terminal entries unchanged; the new entry records what
        it replaced in its system-set `supersedes_entry_id`."
        PRD §3.2: "When `slate_position` is omitted on a supersede, the new
        entry inherits the superseded entry's position."

        Design: Difficulty/compensating_invariant/slate_supersede_preserves_cardinality
        """
        role, hrbp_headers, entry_ids, sixth = self._setup_full_slate(api)
        superseded_id = entry_ids[2]  # position 3

        created = validate_success(api.create_successor(role["id"], {
            "employee_id": sixth["id"],
            "readiness_rating": "READY_NOW",
            "supersede_entry_id": superseded_id,
            "expected_critical_role_version": get_role_version(role["id"], hrbp_headers),
        }, hrbp_headers), 201)
        assert created["status"] == "DRAFT"
        assert created["supersedes_entry_id"] == superseded_id
        assert created["slate_position"] == 3, (
            "omitted slate_position on a supersede must inherit the replaced entry's position"
        )

        old = get_success_data(api.get_successor(superseded_id, hrbp_headers))
        assert old["status"] == "REMOVED"

        entries = get_success_data(
            api.list_successors(hrbp_headers, params={"critical_role_id": role["id"]})
        )
        non_terminal = [
            e for e in entries if e["status"] in ("DRAFT", "ACTIVE", "SUSPENDED")
        ]
        assert len(non_terminal) == 5, (
            f"non-terminal slate cardinality must stay 5, got {len(non_terminal)}"
        )
        assert len(entries) == 6, "the REMOVED entry remains visible in the full list"
