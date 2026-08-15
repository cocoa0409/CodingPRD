"""Project setup, registry reads, envelope, pagination, and baseline auth."""
from test_helpers import (
    ADMIN,
    EO,
    NON_EXISTENT_UUID,
    PM,
    ApiErrorId,
    assert_repair_project,
    assert_timestamp_instant,
    create_dock,
    create_dock_payload,
    create_draft_project,
    create_repair_project_payload,
    create_subcontractor,
    create_vessel,
    create_work_item_payload,
    get_success_data,
    make_subcontractor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProjectCreation:
    def test_create_project_applies_default_warranty_days(self, api):
        """PRD §3.2: "`warranty_days`, the length of the post-delivery warranty
        window in calendar days, which must be positive and defaults to 90".

        Design: Corner/entities/create_project_applies_default_warranty_days
        """
        dock = create_dock()
        vessel = create_vessel()
        resp = api.create_repair_project(
            create_repair_project_payload(vessel["id"], dock["id"]), PM
        )
        project = validate_success(resp, 201)
        assert_repair_project(project)
        assert project["warranty_days"] == 90, (
            f"Omitted warranty_days must default to 90, got {project['warranty_days']}"
        )

    def test_create_project_system_fields_server_generated(self, api):
        """PRD §3.2: "The project is born in `DRAFT`, with its commercial and
        scheduling fields — `awarded_price_cents`, `contracted_price_cents`,
        `ld_daily_rate_cents`, `actual_dock_in_utc`, `forecast_delivery_utc`,
        `liquidated_damages_cents`, `delivered_at_utc`, `warranty_end_utc` — null
        until the lifecycle fills them in, `critical_path_days` at zero, and
        `provisional_ld_cents` at zero."
        PRD §2.5: "At startup the logical clock reads exactly
        2026-08-01T00:00:00Z, and it never falls back to the host's wall clock."

        Design: Corner/entities/create_project_system_fields_server_generated
        """
        dock = create_dock()
        vessel = create_vessel()
        resp = api.create_repair_project(
            create_repair_project_payload(vessel["id"], dock["id"]), PM
        )
        project = validate_success(resp, 201)
        assert_repair_project(project)
        assert project["status"] == "DRAFT"
        assert project["bid_total_cents"] == 0, (
            "With no work items the live roll-up sums to zero"
        )
        assert project["critical_path_days"] == 0
        assert project["provisional_ld_cents"] == 0
        for field in (
            "awarded_price_cents", "contracted_price_cents", "ld_daily_rate_cents",
            "actual_dock_in_utc", "forecast_delivery_utc",
            "liquidated_damages_cents", "delivered_at_utc", "warranty_end_utc",
        ):
            assert project[field] is None, (
                f"{field} must be null at creation, got {project[field]!r}"
            )
        assert_timestamp_instant(project["created_at"], "2026-08-01T00:00:00")

    def test_create_project_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.9: "Request well-formedness: required fields present, types
        correct, enum values valid, and a non-empty `reason` or `description`
        where one is required — failures yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_project_missing_required_field_returns_invalid_request
        """
        dock = create_dock()
        vessel = create_vessel()
        resp = api.create_repair_project(
            {"vessel_id": vessel["id"], "dock_id": dock["id"]}, PM
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_project_with_unknown_id_returns_not_found(self, api):
        """PRD §2.9: "Identifier resolution: path identifiers first, resolved
        left to right, then identifiers referenced in the body (`vessel_id`,
        `dock_id`, `project_id`, `work_item_id`, `subcontractor_id`, and each
        element of `depends_on_ids`) — the first miss yields `ERR_NOT_FOUND`."

        Design: Corner/entities/get_project_with_unknown_id_returns_not_found
        """
        resp = api.get_repair_project(NON_EXISTENT_UUID, PM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestWorkItemCreation:
    def test_create_work_item_with_invalid_enum_returns_invalid_request(self, api):
        """PRD §3.2: "a `pricing_mode` of either `LUMP_SUM` or `TIME_AND_MATERIALS`."
        PRD §2.9: "Request well-formedness: required fields present, types
        correct, enum values valid, and a non-empty `reason` or `description`
        where one is required — failures yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_work_item_with_invalid_enum_returns_invalid_request
        """
        project = create_draft_project()
        resp = api.create_work_item(
            create_work_item_payload(project["id"], pricing_mode="COST_PLUS"), PM
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_computed_line_total_input_ignored(self, api):
        """PRD §3.2: "its priced value is the quantity multiplied by the unit
        price, rounded half-up to a whole cent."

        Design: Corner/entities/computed_line_total_input_ignored
        """
        project = create_draft_project()
        resp = api.create_work_item(
            create_work_item_payload(
                project["id"],
                description="Pipe renewal",
                quantity=2,
                unit_price_cents=500000,
                line_total_cents=1,
            ),
            PM,
        )
        item = validate_success(resp, 201)
        assert item["line_total_cents"] == 1000000, (
            f"Server computes 2 x 500000 = 1000000 regardless of client input, "
            f"got {item['line_total_cents']}"
        )


class TestListing:
    def test_list_work_items_paginates_with_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10 when omitted, accepts a minimum of 1, and is capped at a
        maximum of 100. The `offset` parameter skips that many items from the
        front of the result set and defaults to 0."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/list_work_items_paginates_with_envelope
        """
        project = create_draft_project()
        for i in range(3):
            get_success_data(
                api.create_work_item(
                    create_work_item_payload(project["id"], description=f"Line {i+1}"),
                    PM,
                ),
                201,
            )
        page1, meta1 = validate_paginated(
            api.list_work_items(PM, params={"project_id": project["id"], "limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_work_items(PM, params={"project_id": project["id"], "limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_reverse_reachability_work_items_by_project(self, api):
        """PRD §3.4: "Work items can be listed and filtered by `project_id`,
        `subcontractor_id`, `origin_change_order_id`, or `status`."

        Design: Corner/endpoints/reverse_reachability_work_items_by_project
        """
        project1 = create_draft_project()
        get_success_data(api.create_work_item(
            create_work_item_payload(project1["id"], description="P1 line 1"), PM), 201)
        get_success_data(api.create_work_item(
            create_work_item_payload(project1["id"], description="P1 line 2"), PM), 201)
        project2 = create_draft_project(
            dock_id=project1["dock_id"], vessel_id=project1["vessel_id"]
        )
        get_success_data(api.create_work_item(
            create_work_item_payload(project2["id"], description="P2 line 1"), PM), 201)

        data, meta = validate_paginated(
            api.list_work_items(PM, params={"project_id": project1["id"]})
        )
        assert meta["total_count"] == 2
        assert len(data) == 2
        descriptions = {item["description"] for item in data}
        assert descriptions == {"P1 line 1", "P1 line 2"}, (
            f"Filtered listing must return exactly the addressed project's items, "
            f"got {descriptions}"
        )

    def test_dependents_subresource_lists_dependents(self, api):
        """PRD §3.4: "A reverse lookup lists the items that depend on a given
        item — every work item whose `depends_on_ids` contains the addressed
        item — which planners use for impact analysis before edits."

        Design: Corner/endpoints/dependents_subresource_lists_dependents
        """
        project = create_draft_project()
        item_a = get_success_data(api.create_work_item(
            create_work_item_payload(project["id"], description="A"), PM), 201)
        item_b = get_success_data(api.create_work_item(
            create_work_item_payload(
                project["id"], description="B", depends_on_ids=[item_a["id"]]
            ), PM), 201)

        data, meta = validate_paginated(
            api.list_work_item_dependents(item_a["id"], PM)
        )
        assert len(data) == 1
        assert data[0]["id"] == item_b["id"], (
            f"Dependents of A must list B ({item_b['id']}), got "
            f"{[d['id'] for d in data]}"
        )


class TestAuthenticationAndAuthorization:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role string
        outside this set, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/missing_auth_header_returns_unauthenticated
        """
        dock = create_dock()
        resp = api.get_dock(dock["id"], None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_forbidden_role_beats_not_found(self, api):
        """PRD §2.9: "Every request is validated against an ordered ladder of
        rungs; a request failing any rung is rejected without evaluating later
        rungs, while checks sharing a rung carry no relative order among
        themselves." (Role authorization is rung 2; identifier resolution is
        rung 4.)

        Design: Corner/validations/forbidden_role_beats_not_found
        """
        subcontractor = create_subcontractor()
        resp = api.get_repair_project(
            NON_EXISTENT_UUID, make_subcontractor_headers(subcontractor["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_subcontractor_cannot_create_dock_returns_forbidden(self, api):
        """PRD §2.1: "an authenticated caller whose role is not listed is
        rejected with `ERR_FORBIDDEN`."
        PRD §4: POST `/v1/docks` lists YardAdmin as its only authorized role.

        Design: Corner/rbac/subcontractor_cannot_create_dock_returns_forbidden
        """
        subcontractor = create_subcontractor()
        resp = api.create_dock(
            create_dock_payload(name="Drydock 9", daily_rate_cents=100000),
            make_subcontractor_headers(subcontractor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
