"""Request intake: gating, pinning, server-computed fields, listing (PRD §3.2, §2.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    basic_um_environment,
    create_criteria_set,
    create_prior_auth_request_payload,
    create_provider,
    make_active_criteria_set,
    pended_request,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["um_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
EDITOR = TEST_USERS["policy_editor_headers"]


class TestIntakeGating:
    def test_intake_on_draft_criteria_set_rejected(self, api):
        """PRD §3.2: "First, the criteria set must be `ACTIVE`; a set in any other status rejects intake with `ERR_CRITERIA_SET_NOT_ACTIVE`."

        Design: Corner/validations/intake_on_draft_criteria_set_rejected
        """
        cs = create_criteria_set(name="Draft Set")
        provider = create_provider(name="P")
        payload = create_prior_auth_request_payload(
            provider_id=provider["id"], criteria_set_id=cs["id"],
        )
        resp = api.create_prior_auth_request(payload, INTAKE)
        validate_error(resp, ApiErrorId.ERR_CRITERIA_SET_NOT_ACTIVE)

    def test_intake_without_covering_guideline_window_rejected(self, api):
        """PRD §3.2: "Third, guideline pinning: the server selects the `PUBLISHED` version of the set whose closed effective window contains the intake timestamp — `effective_from` on or before `received_at`, and `effective_until` either null or on or after `received_at` — ranking candidates by `effective_from` descending with ties broken by `created_at` descending. If no published window contains the timestamp, intake fails with `ERR_NO_ACTIVE_GUIDELINE`."

        Design: Corner/validations/intake_without_covering_guideline_window_rejected
        """
        # The only published window opens 2027-01-01, after the startup clock
        # 2026-08-01T00:00:00Z, so no window contains received_at.
        cs, _gv = make_active_criteria_set(
            name="Future Window Set", effective_from="2027-01-01T00:00:00Z",
        )
        provider = create_provider(name="P")
        payload = create_prior_auth_request_payload(
            provider_id=provider["id"], criteria_set_id=cs["id"],
        )
        resp = api.create_prior_auth_request(payload, INTAKE)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_GUIDELINE)


class TestServerComputedIntakeFields:
    def test_client_supplied_status_and_due_at_ignored(self, api):
        """PRD §3.2: "With pinning complete, `received_at` is stamped from the logical clock, `due_at` is computed per §2.5, and the auto-approval decision runs synchronously inside the intake call."
        PRD §3.2: "When neither lane fires, the request lands in `PENDED_REVIEW` and awaits human review."
        PRD §2.5: "A request's `due_at` is its `received_at` plus the SLA hours for the pairing of the request's `urgency` and the governing criteria set's `line_of_business`: 24 hours for `URGENT` requests under `MEDICARE` or `MEDICAID`, 48 hours for `URGENT` requests under `COMMERCIAL`, 72 hours for `STANDARD` requests under `MEDICARE`, 120 hours for `STANDARD` requests under `MEDICAID`, and 168 hours for `STANDARD` requests under `COMMERCIAL`."

        Design: Corner/entities/request_intake_client_status_field_input_ignored
        """
        provider, cs, _gv = basic_um_environment()
        payload = create_prior_auth_request_payload(
            provider_id=provider["id"], criteria_set_id=cs["id"],
        )
        payload["status"] = "APPROVED"
        payload["due_at"] = "2030-01-01T00:00:00Z"
        data = validate_success(
            api.create_prior_auth_request(payload, INTAKE), expected_status=201,
        )
        assert data["status"] == "PENDED_REVIEW", (
            "client-supplied status ignored; no auto-approval lane fired"
        )
        assert data["due_at"] == "2026-08-08T00:00:00.000Z", (
            "server-computed 168h STANDARD x COMMERCIAL SLA from the startup "
            "clock 2026-08-01T00:00:00Z; client-supplied due_at ignored"
        )


class TestRequestListing:
    def _setup_twelve_pended_requests(self):
        provider, cs, _gv = basic_um_environment()
        for i in range(12):
            pended_request(provider["id"], cs["id"], member_ref=f"L-{i + 1:02d}")
        return provider, cs

    def test_default_pagination_and_offset_page(self, api):
        """PRD §2.3: "`limit` caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/request_list_pagination_and_filters
        """
        self._setup_twelve_pended_requests()
        first_page, meta = validate_paginated(api.list_prior_auth_requests(ADMIN))
        assert len(first_page) == 10, "default page returns the limit of 10 rows"
        assert meta["limit"] == 10 and meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        second_page, meta2 = validate_paginated(
            api.list_prior_auth_requests(
                ADMIN, params={"limit": 10, "offset": 10},
            )
        )
        assert len(second_page) == 2, "offset page returns the remaining 2 rows"
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False

    def test_status_filter_narrows_listing(self, api):
        """PRD §3.2: "Requests can be listed with `provider_id`, `criteria_set_id`, `guideline_version_id`, `status`, and `urgency` filters alongside the standard `limit` and `offset` parameters."

        Design: Corner/entities/request_list_pagination_and_filters
        """
        self._setup_twelve_pended_requests()
        rows, meta = validate_paginated(
            api.list_prior_auth_requests(ADMIN, params={"status": "PENDED_REVIEW"})
        )
        assert meta["total_count"] == 12
        assert all(r["status"] == "PENDED_REVIEW" for r in rows)
        rows2, meta2 = validate_paginated(
            api.list_prior_auth_requests(ADMIN, params={"status": "APPROVED"})
        )
        assert meta2["total_count"] == 0
        assert rows2 == []


class TestNotFound:
    def test_get_nonexistent_request_returns_not_found(self, api):
        """PRD §2.7: "Third, left-to-right existence of path identifiers — each id in the URL is resolved in order and the first missing resource yields `ERR_NOT_FOUND` (HTTP 404)."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error. The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/entities/request_get_nonexistent_returns_not_found
        """
        resp = api.get_prior_auth_request(
            "123e4567-e89b-42d3-a456-426614174000", ADMIN,
        )
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert error["message"].strip(), "error message must be non-empty"
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
