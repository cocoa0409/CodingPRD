"""Registration surface (venues, technicians, assets, trucks, productions) and
the security envelope: authentication, authorization, and per-transition actors."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    create_venue, create_asset, create_truck, create_technician,
    setup_planning_production, create_plot, add_rigging_point, submit_plot,
    TEST_USERS,
)

PM = TEST_USERS["production_manager_headers"]
WH = TEST_USERS["warehouse_chief_headers"]


class TestVenueRegistration:
    def test_venue_creation_defaults_applied(self, api):
        """PRD §3.1: "Five labor parameters carry defaults and may be omitted at registration: `min_call_hours` (default 4), the minimum hours billed per crew member per day; `ot1_threshold_hours` (default 8), the daily straight-time ceiling before time-and-a-half; `ot2_threshold_hours` (default 12), the daily ceiling before double time; `turnaround_min_hours` (default 8), the minimum rest gap between two call windows for the same technician; `crew_call_publish_lead_hours` (default 48), how far before call start a call must be published; and `engineering_submission_lead_hours` (default 72), how far before production load-in rigging points must reach engineering review."

        Design: Corner/entities/venue_creation_defaults_applied
        """
        payload = {
            "name": "Bare Venue",
            "union_ruleset": "NON_UNION",
            "max_point_capacity_kg": 500,
            "bay_aggregate_limit_kg": 2000,
            "house_power_amps_per_phase": 200,
            "dock_doors": 2,
        }
        resp = api.create_venue(payload, PM)
        data = validate_success(resp, expected_status=201)
        assert data["min_call_hours"] == 4
        assert data["ot1_threshold_hours"] == 8
        assert data["ot2_threshold_hours"] == 12
        assert data["turnaround_min_hours"] == 8
        assert data["crew_call_publish_lead_hours"] == 48
        assert data["engineering_submission_lead_hours"] == 72

    def test_venue_invalid_enum_rejected(self, api):
        """PRD §2.6: "required fields present, enum members valid, numeric ranges respected, and every time window's end strictly after its start; productions additionally require `load_in_at` strictly before `show_at` strictly before `load_out_at`. Unique-attribute collisions on a technician's `union_card_no`, an asset's `asset_tag`, or a truck's `plate_no` are schema-category failures. All of these surface as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/venue_invalid_enum_rejected
        """
        payload = {
            "name": "Bad",
            "union_ruleset": "IBEW",
            "max_point_capacity_kg": 500,
            "bay_aggregate_limit_kg": 2000,
            "house_power_amps_per_phase": 200,
            "dock_doors": 2,
        }
        resp = api.create_venue(payload, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        data, meta = validate_paginated(api.list_venues(PM))
        assert meta["total_count"] == 0, f"rejected venue must not persist, got {meta['total_count']}"

    def test_production_get_not_found(self, api):
        """PRD §2.7: "The first identifier that does not resolve to an existing resource terminates the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404); later identifiers are never examined."

        Design: Corner/entities/production_get_not_found
        """
        resp = api.get_production(NON_EXISTENT_UUID, PM)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)

    def test_duplicate_unique_attribute_rejected(self, api):
        """PRD §2.6: "Unique-attribute collisions on a technician's `union_card_no`, an asset's `asset_tag`, or a truck's `plate_no` are schema-category failures. All of these surface as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/duplicate_unique_attribute_rejected
        """
        create_technician(union_card_no="U-1001")
        create_asset(asset_tag="ML-001")
        create_truck(plate_no="T-1")
        resp = api.create_technician(
            {"full_name": "Lt Dup", "union_card_no": "U-1001",
             "classification": "RIGGER", "hourly_rate_cents": 9000}, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        resp = api.create_asset(
            {"asset_tag": "ML-001", "asset_class": "CONSOLE", "weight_kg": 50,
             "daily_rate_cents": 8000, "replacement_cost_cents": 200000,
             "acquired_at": "2024-08-01T00:00:00Z"}, WH)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        resp = api.create_truck({"plate_no": "T-1", "capacity_kg": 8000}, WH)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_production_window_ordering_rejected(self, api):
        """PRD §3.2: "The schema requires `load_in_at` strictly before `show_at` strictly before `load_out_at`."

        Design: Corner/entities/production_window_ordering_rejected
        """
        venue = create_venue()
        resp = api.create_production(
            {"venue_id": venue["id"], "name": "BadWindow",
             "load_in_at": "2026-09-01T08:00:00Z",
             "show_at": "2026-09-01T08:00:00Z",
             "load_out_at": "2026-09-03T23:00:00Z"}, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_asset_list_pagination_and_filters(self, api):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD §2.3: "Several list endpoints accept optional filter query parameters in addition to `limit` and `offset`: productions may be filtered by `venue_id` and `status`; assets by `asset_class` and `status`; pull list entries by `status`; load schedules by `direction`; inspections by `inspection_type`; and damage reports by `status`."

        Design: Corner/entities/asset_list_pagination_and_filters
        """
        for tag in ("ML-001", "ML-002", "ML-003"):
            create_asset(asset_tag=tag, asset_class="MOVING_LIGHT")
        create_asset(asset_tag="CS-001", asset_class="CONSOLE", weight_kg=50,
                     daily_rate_cents=8000, replacement_cost_cents=200000)
        page1, meta1 = validate_paginated(api.list_assets(
            WH, params={"asset_class": "MOVING_LIGHT", "status": "AVAILABLE",
                        "limit": 2, "offset": 0}))
        assert len(page1) == 2 and meta1["total_count"] == 3 and meta1["has_more"] is True
        page2, meta2 = validate_paginated(api.list_assets(
            WH, params={"asset_class": "MOVING_LIGHT", "status": "AVAILABLE",
                        "limit": 2, "offset": 2}))
        assert len(page2) == 1 and meta2["total_count"] == 3 and meta2["has_more"] is False
        for item in page1 + page2:
            assert item["asset_class"] == "MOVING_LIGHT" and item["status"] == "AVAILABLE"


class TestSecurityEnvelope:
    def test_request_without_role_header_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/request_without_role_header_unauthenticated
        """
        payload = {
            "name": "Arena", "union_ruleset": "IATSE", "max_point_capacity_kg": 500,
            "bay_aggregate_limit_kg": 2000, "house_power_amps_per_phase": 200,
            "dock_doors": 2,
        }
        resp = api.create_venue(payload, {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_wrong_role_writes_forbidden(self, api):
        """PRD §2.1: "Each operation is restricted to a named set of roles (see §4); a request whose role is not listed for that operation — including a transition request whose `to` value belongs to a different role's transitions — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/errors/wrong_role_writes_forbidden
        """
        ctx = setup_planning_production()
        asset = create_asset()
        # WarehouseChief cannot create productions (§4: ProductionManager only).
        resp = api.create_production(
            {"venue_id": ctx["venue"]["id"], "name": "PX",
             "load_in_at": "2026-10-01T08:00:00Z", "show_at": "2026-10-02T19:00:00Z",
             "load_out_at": "2026-10-03T23:00:00Z"}, WH)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        # ClientContact cannot create crew calls (§4: ProductionManager only).
        resp = api.create_crew_call(
            ctx["production"]["id"],
            {"department": "LIGHTING", "call_start": "2026-09-01T08:00:00Z",
             "call_end": "2026-09-01T18:00:00Z", "required_headcount": 1},
            TEST_USERS["client_contact_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        # StructuralEngineer cannot create pull list entries (§4: WarehouseChief only).
        resp = api.create_pull_list_entry(
            ctx["production"]["id"], {"asset_id": asset["id"]},
            TEST_USERS["structural_engineer_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_production_manager_cannot_approve_plot(self, api):
        """PRD §3.3: "Plot-level approval (`SUBMITTED` → `APPROVED`) rests with the `StructuralEngineer` and enforces the same bay aggregate rule across the plot's non-`RELEASED` points, with `ERR_BAY_OVERLOAD` on violation."
        PRD §2.1: "Each operation is restricted to a named set of roles (see §4); a request whose role is not listed for that operation — including a transition request whose `to` value belongs to a different role's transitions — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/production_manager_cannot_approve_plot
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        add_rigging_point(plot["id"])
        plot = submit_plot(plot["id"])
        resp = api.transition_plot(plot["id"], {"to": "APPROVED"}, PM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_plot(plot["id"], PM))
        assert after["status"] == "SUBMITTED", f"plot must stay SUBMITTED, got {after['status']}"
