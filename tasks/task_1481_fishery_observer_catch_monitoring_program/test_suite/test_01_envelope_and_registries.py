"""Registries, response envelope, pagination, and authentication basics."""
import pytest

from test_helpers import (
    CLOCK_START_ISO,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_fishery,
    assert_same_instant,
    create_deployment_for_notice,
    create_fishery_payload,
    create_vessel_payload,
    is_valid_uuid,
    make_fishery,
    make_operator,
    make_vessel,
    make_vessel_operator_headers,
    setup_notice_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestResponseEnvelope:
    def test_success_and_error_envelope_shapes(self, api, admin_headers, coordinator_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`." and "The
        `response_type` is either "object" for a single resource or "array"
        for a list of resources." and "The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_success_and_error_shapes
        """
        created = api.create_fishery(create_fishery_payload(), admin_headers)
        assert created.status_code == 201
        body = created.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        fishery_id = body["data"]["id"]

        fetched = api.get_fishery(fishery_id, coordinator_headers)
        fetched_body = fetched.json()
        assert fetched_body["response_type"] == "object"
        assert fetched_body["data"]["id"] == fishery_id

        listed = api.list_fisheries(coordinator_headers)
        assert listed.json()["response_type"] == "array"

        missing = api.get_fishery(NON_EXISTENT_UUID, coordinator_headers)
        err_body = missing.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == ApiErrorId.ERR_NOT_FOUND.value
        assert isinstance(err_body["data"]["message"], str)
        assert len(err_body["data"]["message"].strip()) > 0


class TestFisheryRegistry:
    def test_fishery_creation_applies_defaults(self, api, admin_headers):
        """PRD §3.1: "A fishery is born `ACTIVE`". PRD §2.7: "At startup the
        clock reads exactly `2026-08-01T00:00:00Z`, and it must never fall back
        to wall-clock time."

        Design: Corner/entities/fishery_creation_applies_defaults_and_computed_surface
        """
        resp = api.create_fishery(
            create_fishery_payload(
                code="BSAI-ENT", name="Entity Fishery", region="Bering Sea",
                coverage_target_pct=0.25, priority_gear="POT",
            ),
            admin_headers,
        )
        data = validate_success(resp, 201)
        assert_fishery(data)
        assert data["status"] == "ACTIVE", "fishery must be born ACTIVE"
        assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
        assert data["code"] == "BSAI-ENT"
        assert data["coverage_target_pct"] == pytest.approx(0.25)
        assert data["priority_gear"] == "POT"
        assert isinstance(data["version"], int)
        assert_same_instant(data["created_at"], CLOCK_START_ISO, "created_at")

    def test_fishery_creation_missing_coverage_target_rejected(self, api, admin_headers):
        """PRD §2.11: "4. **Request schema** — required fields, types, enum values, and
        value ranges (`ERR_INVALID_REQUEST`; the fishery coverage target has
        its own `ERR_COVERAGE_TARGET_OUT_OF_RANGE`)."

        Design: Corner/entities/fishery_creation_missing_coverage_target_returns_invalid_request
        """
        payload = create_fishery_payload(code="BSAI-MISS")
        del payload["coverage_target_pct"]
        resp = api.create_fishery(payload, admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows, meta = validate_paginated(api.list_fisheries(admin_headers))
        assert meta["total_count"] == 0, "no Fishery row may be created"

    def test_fishery_coverage_target_range_boundaries(self, api, admin_headers):
        """PRD §3.1: "a `coverage_target_pct` between 0.02 and 1.00 inclusive —
        a target outside that band is rejected with
        `ERR_COVERAGE_TARGET_OUT_OF_RANGE`".

        Design: Corner/entities/fishery_coverage_target_out_of_range_boundary_values
        """
        low = api.create_fishery(
            create_fishery_payload(code="BSAI-LO", coverage_target_pct=0.01),
            admin_headers,
        )
        validate_error(low, ApiErrorId.ERR_COVERAGE_TARGET_OUT_OF_RANGE)
        high = api.create_fishery(
            create_fishery_payload(code="BSAI-HI", coverage_target_pct=1.01),
            admin_headers,
        )
        validate_error(high, ApiErrorId.ERR_COVERAGE_TARGET_OUT_OF_RANGE)
        ok_lo = api.create_fishery(
            create_fishery_payload(code="BSAI-MIN", coverage_target_pct=0.02),
            admin_headers,
        )
        assert validate_success(ok_lo, 201)["coverage_target_pct"] == pytest.approx(0.02)
        ok_hi = api.create_fishery(
            create_fishery_payload(code="BSAI-MAX", coverage_target_pct=1.00),
            admin_headers,
        )
        assert validate_success(ok_hi, 201)["coverage_target_pct"] == pytest.approx(1.00)


class TestPersonnelRegistries:
    def test_observer_max_consecutive_sea_days_derived(self, api, admin_headers):
        """PRD §3.1: "The certification derives the observer's
        `max_consecutive_sea_days` ceiling — 20 days for a trainee, 30 for
        certified, 45 for a lead".

        Design: Corner/entities/observer_max_consecutive_sea_days_derived_from_certification
        """
        trainee = validate_success(
            api.create_observer(
                {
                    "person_ref": "person-ent-t",
                    "full_name": "Trainee Troy",
                    "home_port": "Kodiak",
                    "certification_level": "TRAINEE",
                },
                admin_headers,
            ),
            201,
        )
        certified = validate_success(
            api.create_observer(
                {
                    "person_ref": "person-ent-c",
                    "full_name": "Certified Cara",
                    "home_port": "Kodiak",
                    "certification_level": "CERTIFIED",
                },
                admin_headers,
            ),
            201,
        )
        lead = validate_success(
            api.create_observer(
                {
                    "person_ref": "person-ent-l",
                    "full_name": "Lead Liam",
                    "home_port": "Kodiak",
                    "certification_level": "LEAD",
                },
                admin_headers,
            ),
            201,
        )
        assert trainee["max_consecutive_sea_days"] == 20
        assert certified["max_consecutive_sea_days"] == 30
        assert lead["max_consecutive_sea_days"] == 45


class TestVesselRegistry:
    def test_vessel_creation_seeds_prior_history_fields(self, api, admin_headers):
        """PRD §3.1: "Two optional seeds bridge pre-program history:
        `prior_last_observed_end_date` is copied into the vessel's
        `last_observed_end_date` — the actual return date of the vessel's most
        recent closed human-observer deployment, null when the vessel has never
        been observed — and `prior_harassment_points`, defaulting to zero, is
        copied into `selection_penalty_points`." and "A new vessel starts in
        `REGISTERED` status with `monitoring_mode` of `HUMAN_OBSERVER`, a
        `substantiated_harassment_count` of zero, and `sea_days_observed_ytd`
        of zero."

        Design: Corner/entities/vessel_creation_seeds_prior_history_fields
        """
        fishery = make_fishery()
        operator = make_operator()
        op = make_vessel_operator_headers(operator["id"])
        seeded = validate_success(
            api.create_vessel(
                create_vessel_payload(
                    operator_id=operator["id"],
                    fishery_id=fishery["id"],
                    prior_last_observed_end_date="2025-11-30T00:00:00Z",
                    prior_harassment_points=4,
                ),
                op,
            ),
            201,
        )
        assert_same_instant(
            seeded["last_observed_end_date"],
            "2025-11-30T00:00:00Z",
            "last_observed_end_date",
        )
        assert seeded["selection_penalty_points"] == 4
        assert seeded["monitoring_mode"] == "HUMAN_OBSERVER"
        assert seeded["status"] == "REGISTERED"

        plain = validate_success(
            api.create_vessel(
                create_vessel_payload(
                    operator_id=operator["id"], fishery_id=fishery["id"]
                ),
                op,
            ),
            201,
        )
        assert plain["last_observed_end_date"] is None
        assert plain["selection_penalty_points"] == 0

    def test_vessel_get_not_found_returns_404(self, api, admin_headers):
        """PRD §2.5: "Each path identifier must resolve to an existing resource
        before the next is examined, and the request is rejected immediately
        with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not
        resolve."

        Design: Corner/entities/entity_get_not_found_returns_404
        """
        resp = api.get_vessel(NON_EXISTENT_UUID, admin_headers)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err["error_id"] == "ERR_NOT_FOUND"

    def test_vessel_list_pagination_contract(self, api, coordinator_headers):
        """PRD §2.3: "`limit` bounds the page size: it defaults to 10, with a
        minimum of 1 and a maximum of 100. `offset` skips a number of records
        and defaults to 0." and "The `meta` object of a list response carries
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_endpoint_pagination_fields_and_defaults
        """
        fishery = make_fishery()
        operator = make_operator()
        op = make_vessel_operator_headers(operator["id"])
        ids = []
        for _ in range(3):
            vessel = validate_success(
                api.create_vessel(
                    create_vessel_payload(
                        operator_id=operator["id"], fishery_id=fishery["id"]
                    ),
                    op,
                ),
                201,
            )
            ids.append(vessel["id"])

        page1, meta1 = validate_paginated(
            api.list_vessels(
                coordinator_headers, params={"operator_id": operator["id"], "limit": 2, "offset": 0}
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_vessels(
                coordinator_headers, params={"operator_id": operator["id"], "limit": 2, "offset": 2}
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        page1_ids = {row["id"] for row in page1}
        page2_ids = {row["id"] for row in page2}
        assert page1_ids.isdisjoint(page2_ids), "offset pages must be disjoint"
        assert page1_ids | page2_ids == set(ids)

    def test_unique_constraint_on_code_and_permit(self, api, admin_headers):
        """PRD §3.1: "Registry identifiers must stay unique across their type:
        a duplicate fishery `code`, operator `license_number`, vessel
        `permit_number`, or `person_ref` within any one personnel registry is
        rejected with `ERR_UNIQUE_CONSTRAINT`."

        Design: Corner/entities/unique_constraint_on_fishery_code_and_vessel_permit
        """
        make_fishery(code="BSAI-UQ")
        dup_fishery = api.create_fishery(
            create_fishery_payload(code="BSAI-UQ"), admin_headers
        )
        validate_error(dup_fishery, ApiErrorId.ERR_UNIQUE_CONSTRAINT)

        fishery = make_fishery()
        operator = make_operator()
        op = make_vessel_operator_headers(operator["id"])
        make_vessel(operator, fishery, activate=False, permit_number="PERMIT-UQ")
        dup_vessel = api.create_vessel(
            create_vessel_payload(
                operator_id=operator["id"],
                fishery_id=fishery["id"],
                permit_number="PERMIT-UQ",
            ),
            op,
        )
        validate_error(dup_vessel, ApiErrorId.ERR_UNIQUE_CONSTRAINT)

    def test_fk_reverse_reachability_filtered_lists(self, api, coordinator_headers):
        """PRD §4: "List endpoints accept optional filter query parameters
        naming their resource's foreign keys and status fields, alongside the
        pagination parameters of §2.3. The fishery list filters by `status`;
        the operator list by `payment_standing` and `status`; the vessel list
        by `operator_id`, `fishery_id`, `status`, and `monitoring_mode`" and
        "the deployment list by `selection_notice_id`, `coverage_plan_id`,
        `vessel_id`, `observer_id`, `assigned_debriefer_id`, and `status`" and
        "the selection-notice list by `selection_run_id`, `coverage_plan_id`,
        `vessel_id`, and `status`".

        Design: Corner/entities/fk_reverse_reachability_filtered_lists
        """
        bundle = setup_notice_scenario()
        deployment = create_deployment_for_notice(
            bundle["notice"]["id"], bundle["observer"]["id"],
            "2026-09-10T00:00:00Z", "2026-09-15T00:00:00Z",
        )
        vessels, _ = validate_paginated(
            api.list_vessels(coordinator_headers, params={"operator_id": bundle["operator"]["id"]})
        )
        assert [row["id"] for row in vessels] == [bundle["vessel"]["id"]]

        deployments, _ = validate_paginated(
            api.list_deployments(coordinator_headers, params={"vessel_id": bundle["vessel"]["id"]})
        )
        assert [row["id"] for row in deployments] == [deployment["id"]]
        assert deployments[0]["vessel_id"] == bundle["vessel"]["id"]

        notices, _ = validate_paginated(
            api.list_selection_notices(
                coordinator_headers, params={"coverage_plan_id": bundle["plan"]["id"]}
            )
        )
        assert [row["id"] for row in notices] == [bundle["notice"]["id"]]


class TestAuthenticationBasics:
    def test_unauthenticated_request_missing_headers(self, api):
        """PRD §2.1: "A request missing either header, carrying a role outside
        this set, or whose `X-User-ID` fails to resolve to an existing record
        for an entity-backed role is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)." PRD §2.11: "Incoming writes are checked in a fixed
        priority order so that a request with several problems always surfaces
        the same error. Lower numbers win:"

        Design: Corner/rbac/unauthenticated_request_missing_headers
        """
        # Malformed body sent with NO auth headers: authentication (step 1)
        # must preempt the schema error the body would otherwise produce.
        resp = api.create_fishery(
            {"code": "BSAI-NA", "coverage_target_pct": "not-a-number"}, headers={}
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_role_denied_for_exclusive_operation(self, api, admin_headers, coordinator_headers):
        """PRD §2.1: "Beyond authentication, each endpoint admits only specific
        roles (§4); an authenticated caller attempting an operation outside
        their role, or on a resource they do not own, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/role_denied_for_exclusive_operation
        """
        fishery = make_fishery()
        # POST /fisheries is ProgramAdmin-only (PRD §4).
        forbidden_fishery = api.create_fishery(
            create_fishery_payload(code="BSAI-RB2"), coordinator_headers
        )
        validate_error(forbidden_fishery, ApiErrorId.ERR_FORBIDDEN, 403)
        # POST /coverage-plans is ProgramCoordinator-only (PRD §4).
        forbidden_plan = api.create_coverage_plan(
            {
                "fishery_id": fishery["id"],
                "period_start": "2026-09-01T00:00:00Z",
                "period_end": "2026-12-31T00:00:00Z",
                "projected_fleet_effort_days": 100,
                "projected_em_effort_days": 0,
            },
            admin_headers,
        )
        validate_error(forbidden_plan, ApiErrorId.ERR_FORBIDDEN, 403)
