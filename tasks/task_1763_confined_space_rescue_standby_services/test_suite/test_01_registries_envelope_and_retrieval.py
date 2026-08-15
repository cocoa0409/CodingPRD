"""Registries, response envelope, and retrieval coverage (PRD §2.2-§2.5, §3.1).

Covers the simplest claims: registry defaults, request-shape rejections,
append-only record shape, not-found errors, pagination, and envelope shape.
"""
from test_helpers import (
    CLERK,
    NON_EXISTENT_UUID,
    OPS,
    ApiErrorId,
    assert_atmospheric_reading,
    create_account,
    create_client_account_payload,
    create_ops_team,
    create_permit,
    create_personnel_payload,
    create_space,
    generate_statement,
    make_personnel,
    post_reading,
    set_clock,
    setup_issued_permit,
    statement_lines,
    validate_error,
    validate_paginated,
    validate_success,
    is_iso8601_timestamp,
    is_valid_uuid,
)


class TestRegistryDefaults:
    def test_personnel_create_defaults_applied(self, api):
        """PRD §3.1: "any `certifications` they carry (drawn from
        `CONFINED_SPACE_RESCUE`, `HIGH_ANGLE`, `HAZMAT`, `MEDIC`, defaulting to
        an empty list). Each worker's `max_duty_hours` caps the length of any
        single scheduled roster shift, defaulting to 12 hours when omitted. New
        personnel start `ACTIVE` with `committed_standby_minutes` at zero".

        Design: Corner/entities/corner_personnel_create_defaults_applied
        """
        set_clock("2026-08-03T06:00:00Z")
        resp = api.create_personnel(
            create_personnel_payload(full_name="Plain Worker",
                                     role_qualifications=[]), OPS)
        person = validate_success(resp, expected_status=201)
        assert person["certifications"] == [], (
            "omitted certifications must default to []")
        assert person["max_duty_hours"] == 12, (
            "omitted max_duty_hours must default to 12")
        assert person["status"] == "ACTIVE", "new personnel start ACTIVE"
        assert person["committed_standby_minutes"] == 0, (
            "new personnel start with committed_standby_minutes at zero")

    def test_personnel_missing_required_fields_rejected(self, api):
        """PRD §2.6: "Request-shape validation comes next: required fields
        must be present, unknown fields are rejected (this includes
        client-supplied system or computed fields such as `within_limits`,
        `balance_cents`, or `id`, which are never accepted from clients), enum
        values must belong to their declared enumerations, and numeric values
        must fall inside sane ranges, all reported as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/corner_personnel_missing_required_fields_rejected
        """
        # full_name deliberately omitted
        resp = api.create_personnel({"role_qualifications": []}, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

    def test_account_defaults_applied(self, api):
        """PRD §3.1: "five defaulted knobs — `deployment_surcharge_cents`
        (default 50000), `minimum_billable_hours` (default 4),
        `tier1_hours_threshold` (default 8), `tier2_multiplier` (default 1.5),
        `after_hours_multiplier` (default 1.5), and `weekend_multiplier`
        (default 2.0). New accounts begin with `balance_cents` at zero and
        `on_credit_hold` false."

        Design: Corner/entities/corner_account_defaults_applied
        """
        resp = api.create_client_account(create_client_account_payload(), OPS)
        account = validate_success(resp, expected_status=201)
        assert account["deployment_surcharge_cents"] == 50000
        assert account["minimum_billable_hours"] == 4
        assert account["tier1_hours_threshold"] == 8
        assert account["tier2_multiplier"] == 1.5
        assert account["after_hours_multiplier"] == 1.5
        assert account["weekend_multiplier"] == 2.0
        assert account["balance_cents"] == 0
        assert account["on_credit_hold"] is False


class TestRequestShapeAndAppendOnlyRecords:
    def test_reading_computed_field_input_rejected(self, api):
        """PRD §2.6: "unknown fields are rejected (this includes
        client-supplied system or computed fields such as `within_limits`,
        `balance_cents`, or `id`, which are never accepted from clients)".

        Design: Corner/entities/corner_reading_computed_field_input_rejected
        """
        ctx = setup_issued_permit(at="2026-08-03T06:00:00Z", with_plan=False)
        payload = {
            "reading_kind": "PRE_ENTRY", "o2_pct": 20.9, "lel_pct": 0,
            "h2s_ppm": 0, "co_ppm": 0, "within_limits": True,
        }
        resp = api.create_atmospheric_reading(
            ctx["permit"]["id"], payload, ctx["team"]["attendant_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_reading_immutable_common_field_shape(self, api):
        """PRD §2.4: "Two resource kinds are exempt from the full set:
        `AtmosphericReading` and `StatementLine` are append-only ledger-style
        records and carry only `id` and `created_at` — both `updated_at` and
        `version` are absent on these two resources, and any request that
        supplies them is rejected as an unknown-field violation."
        PRD §3.6: "Each reading stamps `recorded_at` from the logical clock,
        records the attendant as `recorded_by`, and computes `within_limits`:
        true exactly when `o2_pct` is at least 19.5 and at most 23.5, `lel_pct`
        is at most 10, `h2s_ppm` is at most 10, and `co_ppm` is at most 35 —
        all bounds inclusive."

        Design: Corner/entities/corner_reading_immutable_common_field_shape
        """
        ctx = setup_issued_permit(at="2026-08-03T06:00:00Z", with_plan=False)
        reading = post_reading(ctx["permit"]["id"],
                               ctx["team"]["attendant_headers"],
                               reading_kind="PRE_ENTRY")
        assert_atmospheric_reading(reading)
        assert "version" not in reading and "updated_at" not in reading
        assert reading["within_limits"] is True, (
            "20.9/0/0/0 is inside every inclusive bound")
        assert reading["recorded_by"] == ctx["team"]["attendant"]["id"], (
            "recorded_by is server-stamped from the attendant's identity")
        assert is_iso8601_timestamp(reading["recorded_at"])

    def test_permit_account_fk_denormalized(self, api):
        """PRD §3.3: "A new permit starts in `DRAFT`, denormalizes the space's
        owning account onto `client_account_id` for billing sweeps,
        auto-cancels any existing `DRAFT` permits of the same space (supersede
        semantics, closing them with `close_reason` `CANCELLED`), and
        increments the space's `version`."

        Design: Corner/entities/corner_permit_account_fk_denormalized
        """
        team = create_ops_team()
        set_clock("2026-08-03T06:00:00Z")
        account = create_account(name="Denorm Co", billing_mode="EVENT")
        space = create_space(account["id"], space_code="TK-D")
        permit = create_permit(space["id"], team["supervisor_headers"],
                               purpose="Denorm job",
                               planned_start_at="2026-08-03T06:00:00Z",
                               planned_end_at="2026-08-03T20:00:00Z")
        assert permit["client_account_id"] == account["id"], (
            "client_account_id is denormalized from the parent space's account")
        assert permit["status"] == "DRAFT"
        assert permit["suspension_count"] == 0 and permit["reentry_count"] == 0


class TestNotFound:
    def test_space_get_not_found(self, api):
        """PRD §2.5: "A path such as
        `/rescue-ops/client-accounts/{accountId}/confined-spaces` or
        `/rescue-ops/entry-permits/{permitId}/roster-entries` resolves each
        identifier in order, and the request is rejected immediately with the
        `404` error corresponding to the first identifier that does not exist
        — `ERR_ACCOUNT_NOT_FOUND` before `ERR_SPACE_NOT_FOUND`,
        `ERR_PERMIT_NOT_FOUND` before `ERR_ROSTER_ENTRY_NOT_FOUND`, and so on
        through `ERR_PERSONNEL_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_VERIFICATION_NOT_FOUND`, `ERR_READING_NOT_FOUND`,
        `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, and
        `ERR_STATEMENT_NOT_FOUND`."

        Design: Corner/entities/corner_space_get_not_found
        """
        resp = api.get_confined_space(NON_EXISTENT_UUID, OPS)
        validate_error(resp, ApiErrorId.ERR_SPACE_NOT_FOUND)

    def test_not_found_sweep(self, api):
        """PRD §2.5: "the request is rejected immediately with the `404` error
        corresponding to the first identifier that does not exist —
        `ERR_ACCOUNT_NOT_FOUND` before `ERR_SPACE_NOT_FOUND`,
        `ERR_PERMIT_NOT_FOUND` before `ERR_ROSTER_ENTRY_NOT_FOUND`, and so on
        through `ERR_PERSONNEL_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_VERIFICATION_NOT_FOUND`, `ERR_READING_NOT_FOUND`,
        `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, and
        `ERR_STATEMENT_NOT_FOUND`."

        Design: Corner/errors/corner_not_found_sweep
        """
        cases = [
            (api.get_entry_permit, ApiErrorId.ERR_PERMIT_NOT_FOUND),
            (api.get_rescue_plan, ApiErrorId.ERR_PLAN_NOT_FOUND),
            (api.get_personnel, ApiErrorId.ERR_PERSONNEL_NOT_FOUND),
            (api.get_statement, ApiErrorId.ERR_STATEMENT_NOT_FOUND),
            (api.get_incident, ApiErrorId.ERR_INCIDENT_NOT_FOUND),
            (api.get_standby_assignment, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
            (api.get_isolation_verification,
             ApiErrorId.ERR_VERIFICATION_NOT_FOUND),
            (api.get_atmospheric_reading, ApiErrorId.ERR_READING_NOT_FOUND),
            (api.get_roster_entry, ApiErrorId.ERR_ROSTER_ENTRY_NOT_FOUND),
            (api.get_client_account, ApiErrorId.ERR_ACCOUNT_NOT_FOUND),
        ]
        for getter, error_id in cases:
            resp = getter(NON_EXISTENT_UUID, OPS)
            err = validate_error(resp, error_id)
            assert resp.status_code == 404, (
                f"{error_id} must be HTTP 404, got {resp.status_code}: "
                f"{err.get('message')}")

    def test_body_fk_not_found(self, api):
        """PRD §2.5: "Body-supplied foreign-key references — `personnel_id` on
        a roster entry, `rescuer_id` on a standby assignment,
        `relief_of_entry_id` on a relief rotation — must also resolve to
        existing resources or the request fails with the matching not-found
        error."

        Design: Corner/errors/corner_body_fk_not_found
        """
        ctx = setup_issued_permit(at="2026-08-03T06:00:00Z", with_plan=False)
        payload = {
            "personnel_id": NON_EXISTENT_UUID,
            "assignment_role": "ENTRANT",
            "scheduled_start_at": "2026-08-03T10:00:00Z",
            "scheduled_end_at": "2026-08-03T18:00:00Z",
        }
        resp = api.create_roster_entry(
            ctx["permit"]["id"], payload, ctx["team"]["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_PERSONNEL_NOT_FOUND)
        assert resp.status_code == 404


class TestPaginationAndEnvelope:
    def test_list_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items returned; when omitted it defaults to 10, and accepted values
        range from a minimum of 1 to a maximum of 100. The `offset` parameter
        specifies how many items to skip and defaults to 0."

        Design: Corner/endpoints/corner_list_pagination_defaults
        """
        set_clock("2026-08-03T06:00:00Z")
        for i in range(1, 12):
            make_personnel(f"W{i:02d}", [])

        page1, meta1 = validate_paginated(api.list_personnel(OPS))
        assert len(page1) == 10, "default limit is 10"
        assert meta1["total_count"] == 11
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_personnel(OPS, params={"limit": 10, "offset": 10}))
        assert len(page2) == 1, "one item remains after offset 10"
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 11

    def test_success_envelope_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."; "The
        `response_type` is either "object" for a single resource or "array"
        for a list of resources."; "Pagination-related fields in `meta`
        (`limit`, `offset`, `total_count`, `has_more`) are included for list
        endpoints."

        Design: Corner/endpoints/corner_success_envelope_shape
        """
        set_clock("2026-08-03T06:00:00Z")
        create_resp = api.create_personnel(
            create_personnel_payload(full_name="Env One",
                                     role_qualifications=[]), OPS)
        person = validate_success(create_resp, expected_status=201)
        body = create_resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert is_valid_uuid(person["id"])

        list_resp = api.list_personnel(OPS)
        _, meta = validate_paginated(list_resp)
        assert list_resp.json()["response_type"] == "array"
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"meta.{field} must be present on lists"

    def test_fk_reverse_reachability_lists(self, api):
        """PRD §3.6: "The readings list endpoint supports filtering by
        `permit_id`, `reading_kind`, `within_limits`, and `recorded_by`."
        PRD §3.3: "The permit list endpoint supports filtering by `space_id`,
        `client_account_id`, `status`, and `issued_by`."
        PRD §3.8: "lines of a statement are listed through the statement's
        lines sub-resource."

        Design: Corner/endpoints/corner_fk_reverse_reachability_lists
        """
        ctx = setup_issued_permit(at="2026-08-03T06:00:00Z", with_plan=False)
        permit = ctx["permit"]
        reading = post_reading(permit["id"], ctx["team"]["attendant_headers"],
                               reading_kind="PRE_ENTRY")
        stmt = generate_statement(ctx["account"]["id"])

        readings, meta_r = validate_paginated(
            api.list_atmospheric_readings(OPS,
                                          params={"permit_id": permit["id"]}))
        assert [r["id"] for r in readings] == [reading["id"]]
        assert meta_r["total_count"] == 1

        by_space, _ = validate_paginated(
            api.list_entry_permits(OPS, params={"space_id": ctx["space"]["id"]}))
        assert [p["id"] for p in by_space] == [permit["id"]]

        by_account, _ = validate_paginated(
            api.list_entry_permits(
                OPS, params={"client_account_id": ctx["account"]["id"]}))
        assert [p["id"] for p in by_account] == [permit["id"]], (
            "denormalized client_account_id supports reverse filtering")

        lines = statement_lines(stmt["id"])
        assert lines == [], "an empty OPEN statement has no lines"
        lines_resp = api.list_statement_lines(stmt["id"], CLERK)
        assert lines_resp.json()["response_type"] == "array"
