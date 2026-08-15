"""Project creation, listing, retrieval, and request-shape validation."""

from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_DEFAULTS, assert_project,
    create_bay, create_project, create_project_payload,
    create_watermark_profile, activate_watermark_profile, activate_project,
    set_clock, setup_active_project, validate_error, validate_paginated,
    validate_success,
)
from test_helpers.test_users import make_post_supervisor_headers

PS = make_post_supervisor_headers()


class TestProjectCreation:
    def test_project_create_with_all_required_fields(self, api):
        """PRD §3.1: "A new project begins in `SETUP` with `storage_used_gb` at
        zero, `open_change_list_count` at zero, and `conform_ready` false."
        PRD §2.5: "`version` (integer): a system-managed integer that increments
        by one on every modification to the resource."

        Design: Corner/entities/project_create_with_all_required_fields
        """
        resp = api.create_project(create_project_payload(
            title="T", client_code="CL100", storage_quota_gb=50), PS)
        project = validate_success(resp, expected_status=201)
        assert_project(project)
        assert project["status"] == "SETUP"
        assert project["version"] == 1
        assert project["storage_used_gb"] == 0
        assert project["open_change_list_count"] == 0
        assert project["conform_ready"] is False

    def test_project_create_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.9: "Required fields must be present, types must match, enum
        values must be members of their declared enumerations, and numeric ranges
        must be respected; otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/project_create_missing_required_field_returns_invalid_request
        """
        payload = create_project_payload(title="T", client_code="CL101")
        del payload["storage_quota_gb"]
        resp = api.create_project(payload, PS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_project_create_invalid_enum_security_tier(self, api):
        """PRD §2.9: "Required fields must be present, types must match, enum
        values must be members of their declared enumerations, and numeric ranges
        must be respected; otherwise `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "a `security_tier` of `STANDARD`, `ELEVATED`, or `LOCKDOWN`".

        Design: Corner/entities/project_create_invalid_enum_security_tier
        """
        resp = api.create_project(create_project_payload(
            title="T", client_code="CL102", storage_quota_gb=50,
            security_tier="PARANOID"), PS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_project_get_not_found(self, api):
        """PRD §2.6: "the system validates them sequentially from left to right
        and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
        identifier that does not resolve to an existing entity".

        Design: Corner/entities/project_get_not_found
        """
        resp = api.get_project(NON_EXISTENT_UUID, PS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestProjectListing:
    def test_project_list_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; when omitted it defaults to 10, and it is bounded below by 1
        and above by 100. The `offset` parameter specifies how many items to skip
        and defaults to 0."
        PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/entities/project_list_pagination_defaults
        """
        for title, code in (("A", "CLA"), ("B", "CLB"), ("C", "CLC")):
            create_project(title=title, client_code=code, storage_quota_gb=10)
        resp = api.list_projects(PS)
        data, meta = validate_paginated(resp)
        assert len(data) == 3, f"Expected 3 projects, got {len(data)}"
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

    def test_project_list_filter_by_status(self, api):
        """PRD §3.1: "The project list can be filtered by `status` and
        `security_tier`."

        Design: Corner/entities/project_list_filter_by_status
        """
        proj_s = create_project(title="S", client_code="CLS", storage_quota_gb=10)
        proj_a, _wm, _bay = setup_active_project(project_overrides={
            "title": "A", "client_code": "CLA2", "storage_quota_gb": 10})
        assert proj_a["status"] == "ACTIVE"
        resp = api.list_projects(PS, params={"status": "SETUP"})
        data, meta = validate_paginated(resp)
        ids = [p["id"] for p in data]
        assert all(p["status"] == "SETUP" for p in data)
        assert proj_s["id"] in ids
        assert proj_a["id"] not in ids

    def test_pagination_with_filtering_interaction(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; when omitted it defaults to 10, and it is bounded below by 1
        and above by 100. The `offset` parameter specifies how many items to skip
        and defaults to 0."
        PRD §3.1: "The project list can be filtered by `status` and
        `security_tier`."

        Design: Corner/cross_cutting_complexity_layers/pagination_with_filtering_interaction
        """
        for i in range(1, 6):
            create_project(title=f"P{i}", client_code=f"CL90{i}",
                           storage_quota_gb=10)
        resp = api.list_projects(PS, params={"status": "SETUP", "limit": 2,
                                             "offset": 1})
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"Expected 2 items, got {len(data)}"
        assert meta["limit"] == 2
        assert meta["offset"] == 1
        assert meta["total_count"] == 5
        assert meta["has_more"] is True
        assert all(p["status"] == "SETUP" for p in data)
