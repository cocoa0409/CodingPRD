"""Project/segment CRUD, defaults, listing/pagination, immutable weather
readings, RBAC, and auth. Covers §2.1, §2.3, §2.4, §3.1, §3.5.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_project, add_segment, create_estimate, project_version,
    create_approved_project, place_material_order,
    create_project_payload, create_segment_payload, create_estimate_payload,
    approve_estimate_payload, create_weather_reading_payload,
    create_change_order_payload,
    assert_project, assert_segment, assert_weather_reading,
    SINGLE_400_REBAR,
    TEST_USERS,
)

EST = TEST_USERS["estimator_headers"]
PM = TEST_USERS["project_manager_headers"]
INS = TEST_USERS["inspector_headers"]


class TestProjectCreation:
    def test_create_project_draft_defaults(self, api):
        """PRD §3.1: "A new project begins in DRAFT with a base_contract_amount of
        0.00 and every derived financial figure - provisional_contract_value,
        committed_contract_value, total_drawn_amount - also at 0.00, a
        warranty_risk_score of 0, a status_before_hold of null, and an
        approved_estimate_id of null."
        PRD §2.4: "And each has a version: an integer that starts at 1 on creation
        and increments by exactly 1 on every mutation"

        Design: Corner/entities/create_project_returns_201_with_draft_defaults
        """
        res = api.create_project(create_project_payload(site_name="Fresh", client_name="Acme"), EST)
        proj = validate_success(res, 201)
        assert_project(proj)
        assert proj["status"] == "DRAFT"
        assert proj["version"] == 1
        assert proj["base_contract_amount"] == 0.00
        assert proj["warranty_risk_score"] == 0

    def test_new_project_initial_state_is_draft(self, api):
        """PRD §3.1: "A new project begins in DRAFT with a base_contract_amount of
        0.00 and every derived financial figure - provisional_contract_value,
        committed_contract_value, total_drawn_amount - also at 0.00, a
        warranty_risk_score of 0, a status_before_hold of null, and an
        approved_estimate_id of null."

        Design: Corner/state_machines/new_project_initial_state_is_draft
        """
        res = api.create_project(create_project_payload(site_name="Init"), EST)
        proj = validate_success(res, 201)
        assert proj["status"] == "DRAFT"

    def test_get_nonexistent_project_not_found(self, api):
        """PRD §2.5: "The system validates the identifiers in such a path strictly
        left-to-right and rejects the request at the first identifier that does not
        resolve to an existing resource, returning ERR_NOT_FOUND (HTTP 404)."

        Design: Corner/entities/get_project_nonexistent_returns_not_found
        """
        res = api.get_project("00000000-0000-4000-8000-000000000000", EST)
        validate_error(res, "ERR_NOT_FOUND")

    def test_list_projects_paginated_envelope(self, api):
        """PRD §2.3: "Every list response includes limit, offset, total_count, and
        has_more in the meta object of the envelope."

        Design: Corner/entities/list_projects_paginated_envelope
        """
        create_project(site_name="L1", client_name="A")
        create_project(site_name="L2", client_name="B")
        data, meta = validate_paginated(api.list_projects(EST, params={"limit": 1, "offset": 0}))
        assert meta["total_count"] == 2
        assert meta["has_more"] is True


class TestSegmentValidation:
    def test_missing_area_rejected(self, api):
        """PRD §3.1: "A segment carries a label such as a driveway or patio, an
        area_sqft plan area that must be strictly greater than zero, a thickness_in
        slab thickness that must be strictly greater than zero, a finish_grade, and
        a reinforcement type."

        Design: Corner/entities/create_segment_missing_area_returns_invalid_request
        """
        proj = create_project(site_name="Seg X")
        res = api.create_segment(proj["id"], {"label": "s", "thickness_in": 4}, EST)
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_zero_area_rejected(self, api):
        """PRD §3.1: "an area_sqft plan area that must be strictly greater than
        zero"

        Design: Corner/entities/create_segment_zero_area_returns_invalid_request
        """
        proj = create_project(site_name="Seg Z")
        res = api.create_segment(proj["id"], create_segment_payload(area_sqft=0), EST)
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_bad_finish_enum_rejected(self, api):
        """PRD §3.1: "The finish_grade is one of BROOM, EXPOSED_AGGREGATE, or
        STAMPED, defaulting to BROOM"

        Design: Corner/entities/create_segment_bad_finish_enum_returns_invalid_request
        """
        proj = create_project(site_name="Seg E")
        res = api.create_segment(
            proj["id"], create_segment_payload(area_sqft=100, finish_grade="GLOSS"), EST)
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_finish_and_reinforcement_defaults(self, api):
        """PRD §3.1: "The finish_grade is one of BROOM, EXPOSED_AGGREGATE, or
        STAMPED, defaulting to BROOM; the reinforcement is one of NONE, MESH, or
        REBAR, defaulting to NONE."

        Design: Corner/entities/segment_finish_defaults_to_broom
        """
        proj = create_project(site_name="Seg D")
        res = api.create_segment(proj["id"], create_segment_payload(area_sqft=100), EST)
        seg = validate_success(res, 201)
        assert seg["finish_grade"] == "BROOM"
        assert seg["reinforcement"] == "NONE"

    def test_list_segments_reverse_reachability(self, api):
        """PRD §3.1: "Into a DRAFT project the Estimator adds one or more flatwork
        segments, each describing a pour area."

        Design: Corner/endpoints/list_segments_reverse_reachability
        """
        proj = create_project(site_name="Seglist")
        add_segment(proj["id"], label="a", area_sqft=100, thickness_in=4)
        add_segment(proj["id"], label="b", area_sqft=100, thickness_in=4)
        data, meta = validate_paginated(api.list_segments(proj["id"], EST))
        assert meta["total_count"] == 2


def test_weather_reading_immutable_no_version(api):
    """PRD §2.4: "A weather reading carries only id and created_at; it has no
    updated_at and no version, because it is never modified after creation."

    Design: Corner/entities/weather_reading_immutable_no_version
    """
    proj, est = create_approved_project(segments=SINGLE_400_REBAR, site_name="WR")
    mo = place_material_order(proj["id"])
    res = api.create_weather_reading(
        mo["id"], create_weather_reading_payload("2026-07-01T12:30:00Z", 70, 5), PM)
    wr = validate_success(res, 201)
    assert_weather_reading(wr)
    assert "version" not in wr


class TestRbacAndAuth:
    def test_estimator_cannot_approve_estimate(self, api):
        """PRD §2.1: "A request whose role is not permitted for the requested
        operation is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."
        PRD §3.3: "A ProjectManager decides the estimate's fate. Approving an
        estimate carries the project from ESTIMATING to APPROVED."

        Design: Corner/rbac/estimator_cannot_approve_estimate_forbidden
        """
        proj = create_project(site_name="Rbac1")
        add_segment(proj["id"], label="s", area_sqft=100, thickness_in=4)
        est = create_estimate(proj["id"])
        pv = project_version(proj["id"])
        res = api.approve_estimate(proj["id"], approve_estimate_payload(est["id"], pv), EST)
        validate_error(res, "ERR_FORBIDDEN_ROLE")

    def test_inspector_cannot_submit_change_order(self, api):
        """PRD §2.1: "A request whose role is not permitted for the requested
        operation is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."
        PRD §3.10: "A FinanceOfficer submits a ChangeOrder against a project"

        Design: Corner/rbac/inspector_cannot_issue_change_order_forbidden
        """
        proj = create_project(site_name="Rbac2")
        res = api.create_change_order(
            proj["id"], create_change_order_payload("x", 100.00), INS)
        validate_error(res, "ERR_FORBIDDEN_ROLE")

    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        ERR_UNAUTHENTICATED (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_unauthenticated
        """
        res = api.list_projects(headers={})
        validate_error(res, "ERR_UNAUTHENTICATED")
