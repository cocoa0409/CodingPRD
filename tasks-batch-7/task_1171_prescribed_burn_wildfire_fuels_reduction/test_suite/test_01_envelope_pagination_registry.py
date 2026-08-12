"""Envelope, pagination, listing, and registry-read claims (PRD §2.2–§2.6, §3.1)."""
from test_helpers import (
    ANY_READER_HEADERS,
    TEST_USERS,
    assert_contractor,
    assert_parcel,
    assert_weather_observation,
    create_contractor_payload,
    create_parcel_payload,
    create_permit_payload,
    create_weather_observation_payload,
    ctx_add_execution,
    ctx_add_parcel,
    ctx_add_plan,
    ctx_author,
    make_landowner_headers,
    setup_approved_plan_ctx,
    setup_registry,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _setup_three_draft_plans(api):
    """Registry + three GRASS/FLAT parcels, each with one DRAFT 50-acre plan."""
    ctx = setup_registry()
    plan_ids = {}
    for key in ("parcel_a", "parcel_b", "parcel_c"):
        ctx_add_parcel(ctx, key=key, name=key.upper(), acreage=120,
                       fuel_model="GRASS", slope_class="FLAT", drought_index=5)
        plan = ctx_add_plan(
            ctx, key=f"plan_{key}", parcel_key=key,
            planned_acres=50,
            treatment_lines=[{"category": "BROADCAST", "rate_class": "GRASS", "acres": 50}])
        plan_ids[key] = (ctx[key]["id"], plan["id"])
    return ctx, plan_ids


class TestRegistryComputedFields:
    def test_parcel_creation_computes_hazard_and_system_fields(self, api):
        """PRD §3.1: "From these immutable attributes the system computes `hazard_score`
        once, at registration: the fuel weight (20 for `GRASS`, 35 for `BRUSH`, 50 for
        `TIMBER`), plus the slope weight (0 for `FLAT`, 10 for `MODERATE`, 20 for `STEEP`),
        plus 20 when the parcel is `wui_adjacent`, plus the `drought_index`."

        Design: Corner/entities/parcel_creation_computes_hazard_and_system_fields
        """
        ctx = setup_registry()
        # BRUSH(35) + MODERATE(10) + non-WUI(0) + drought 10
        parcel = validate_success(api.create_parcel(
            create_parcel_payload(ctx["landowner"]["id"]),
            make_landowner_headers(ctx["landowner"]["id"])), 201)
        assert_parcel(parcel)
        assert parcel["hazard_score"] == 35 + 10 + 0 + 10, (
            f"hazard_score must be 55, got {parcel['hazard_score']}"
        )

    def test_contractor_defaults_applied(self, api):
        """PRD §3.1: "Two counters track reliability: `no_show_count`, starting at 0 and
        incremented on every `NO_SHOW` assignment, and a computed `standing` that becomes
        `SUSPENDED` once `no_show_count` reaches 2 or more."
        PRD §3.1: "A contractor's `available_units` is computed as `capacity_units` minus
        the units committed on that contractor's assignments currently in `ASSIGNED` or
        `CONFIRMED` status"

        Design: Corner/entities/contractor_defaults_applied
        """
        setup_registry()
        contractor = validate_success(api.create_contractor(
            create_contractor_payload(), ADMIN), 201)
        assert_contractor(contractor)
        assert contractor["no_show_count"] == 0
        assert contractor["standing"] == "GOOD_STANDING"
        assert contractor["available_units"] == contractor["capacity_units"] == 4


class TestListingAndPagination:
    def test_list_endpoint_envelope_and_pagination_defaults(self, api):
        """PRD §2.3: "`limit` caps the number of items returned: it defaults to 10, with
        a minimum of 1 and a maximum of 100."
        PRD §2.3: "The `meta` object of a list response carries four pagination fields:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_endpoint_envelope_and_pagination_defaults
        """
        _setup_three_draft_plans(api)
        resp = api.list_burn_plans(ANY_READER_HEADERS)
        body = resp.json()
        assert "api_request_id" in body["meta"], "meta.api_request_id must be present"
        assert body["response_type"] == "array"
        data, meta = validate_paginated(resp)
        assert len(data) == 3
        assert meta["limit"] == 10 and meta["offset"] == 0
        assert meta["total_count"] == 3 and meta["has_more"] is False

    def test_list_endpoint_limit_offset_pagination(self, api):
        """PRD §2.3: "`offset` skips a number of items from the front of the result set
        and defaults to 0."

        Design: Corner/endpoints/list_endpoint_limit_offset_pagination
        """
        _setup_three_draft_plans(api)
        data1, meta1 = validate_paginated(
            api.list_burn_plans(ANY_READER_HEADERS, params={"limit": 2, "offset": 0}))
        assert len(data1) == 2 and meta1["has_more"] is True and meta1["total_count"] == 3
        data2, meta2 = validate_paginated(
            api.list_burn_plans(ANY_READER_HEADERS, params={"limit": 2, "offset": 2}))
        assert len(data2) == 1 and meta2["has_more"] is False and meta2["total_count"] == 3

    def test_list_filter_by_parcel_id(self, api):
        """PRD §3.2: "Plan listings support filters on `parcel_id`, `author_boss_id`,
        `approved_by_boss_id`, `supersedes_plan_id`, and `status`."

        Design: Corner/endpoints/list_filter_by_parcel_id
        """
        ctx, plan_ids = _setup_three_draft_plans(api)
        parcel_a_id, plan_a_id = plan_ids["parcel_a"]
        data, meta = validate_paginated(
            api.list_burn_plans(ANY_READER_HEADERS, params={"parcel_id": parcel_a_id}))
        assert meta["total_count"] == 1 and len(data) == 1
        assert data[0]["id"] == plan_a_id
        assert data[0]["parcel_id"] == parcel_a_id

    def test_fk_reverse_reachability_plan_permits(self, api):
        """PRD §3.3: "The new permit is born `UNDER_REVIEW`, bound to its plan through
        `burn_plan_id`, with `issued_by_boss_id` null until issuance."

        Design: Corner/endpoints/fk_reverse_reachability_plan_permits
        """
        ctx = setup_registry()
        ctx_add_parcel(ctx)
        plan = ctx_add_plan(ctx, submit=True)
        permit = validate_success(api.create_permit(
            plan["id"], create_permit_payload(notifications_required=0),
            ctx_author(ctx)), 201)
        data, meta = validate_paginated(
            api.list_plan_permits(plan["id"], ANY_READER_HEADERS))
        assert meta["total_count"] == 1 and data[0]["id"] == permit["id"]
        assert data[0]["burn_plan_id"] == plan["id"]


class TestAuditRecordsAndConsistency:
    def test_weather_observation_is_immutable_event(self, api):
        """PRD §2.4: "Two audit-record resources are deliberately lighter: a
        `WeatherObservation` and a `GoNoGoChecklist` carry only `id` and `created_at` —
        both `updated_at` and `version` are absent from them."

        Design: Corner/entities/weather_observation_is_immutable_event
        """
        ctx = setup_approved_plan_ctx()
        ex = ctx_add_execution(ctx)
        obs = validate_success(api.create_weather_observation(
            ex["id"], create_weather_observation_payload(
                observed_at="2026-04-30T06:00:00Z"), ctx_author(ctx)), 201)
        assert_weather_observation(obs)
        data, _meta = validate_paginated(
            api.list_weather_observations(ex["id"], ANY_READER_HEADERS))
        assert data[0]["id"] == obs["id"]
        assert_weather_observation(data[0])

    def test_immediate_read_after_write_consistency(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."
        PRD §2.4: "As a rule, every state transition described in §3 increments the acting
        entity's `version` by one and refreshes its `updated_at`."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        ctx = setup_registry()
        ctx_add_parcel(ctx)
        plan = ctx_add_plan(ctx)
        written = validate_success(api.submit_plan(plan["id"], ctx_author(ctx)), 200)
        assert written["status"] == "SUBMITTED"
        assert written["version"] == plan["version"] + 1
        read = validate_success(api.get_burn_plan(plan["id"], ANY_READER_HEADERS), 200)
        assert read["status"] == written["status"] and read["version"] == written["version"]
