"""Work order intake, triage edit with OCC, lookup, and filtered listing."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_instant_equals,
    create_property,
    create_resident,
    create_work_order,
    create_work_order_payload,
    get_work_order,
    make_resident_headers,
    setup_property_resident_technician,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestWorkOrderIntake:
    def test_work_order_starts_triaged_with_clean_counters(self, api):
        """PRD §3.2: "On acceptance the work order enters `TRIAGED` status."
        PRD §3.2: "The system snapshots the resident's current `unit_number` onto the work order so later unit reassignments do not rewrite history, initializes `recall_count` to 0 and `resident_signoff` to false, and computes the two SLA due timestamps: `response_due_at` is the work order's `created_at` plus the property's response-hours value for the chosen priority, and `completion_due_at` is `created_at` plus the property's completion-hours value for that priority."

        Design: Corner/state_machines/work_order_initial_state_triaged
        """
        bundle = setup_property_resident_technician("Init Property", unit_number="204")
        wo = create_work_order(
            bundle["property"]["id"], bundle["resident"]["id"],
            category="ELECTRICAL", priority="URGENT", description="Outlet sparks",
        )
        assert wo["status"] == "TRIAGED"
        assert wo["recall_count"] == 0
        assert wo["resident_signoff"] is False
        assert wo["unit_number"] == "204", "unit_number is snapshotted from the resident"
        assert wo["version"] == 1

    def test_create_work_order_with_invalid_priority_rejected(self, api):
        """PRD §3.2: "A resident files a maintenance request by supplying `property_id`, their own `resident_id`, a `category` drawn from the five-trade vocabulary, a `priority` of `EMERGENCY`, `URGENT`, or `ROUTINE`, and a free-text `description` of the problem."
        PRD §2.1: "The precedence among all validation categories — authentication, authorization, ownership, existence, concurrency, state, business safety, business temporal, business constraint, business fiscal, and finally general shape validation — is honored across every endpoint: an unauthenticated request is rejected before a forbidden one, a forbidden one before a non-owner one, and so on, with malformed-payload errors of the general `ERR_VALIDATION` category evaluated last."

        Design: Corner/validations/create_work_order_with_invalid_enum_rejected
        """
        bundle = setup_property_resident_technician("Enum Property", unit_number="416")
        payload = create_work_order_payload(
            property_id=bundle["property"]["id"],
            resident_id=bundle["resident"]["id"],
            category="PLUMBING",
            priority="WHENEVER",
            description="Bad enum",
        )
        resp = api.create_work_order(
            payload, make_resident_headers(bundle["resident"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestTriageEdit:
    def test_patch_priority_recomputes_due_timestamps(self, api):
        """PRD §3.2: "A successful edit increments the work order's `version` by one, and when `priority` changed, both `response_due_at` and `completion_due_at` are recomputed from the original `created_at` and the new priority's configured hours — the SLA clock always starts at intake, never at reclassification."
        PRD §3.1: "The SLA configuration is expressed as six hour-valued fields: `emergency_response_hours` defaults to 4, `emergency_completion_hours` defaults to 24, `urgent_response_hours` defaults to 24, `urgent_completion_hours` defaults to 72, `routine_response_hours` defaults to 72, and `routine_completion_hours` defaults to 168."

        Design: Corner/endpoints/patch_triage_recomputes_due_timestamps
        """
        bundle = setup_property_resident_technician("Patch Property", unit_number="504")
        wo = create_work_order(
            bundle["property"]["id"], bundle["resident"]["id"],
            category="PLUMBING", priority="ROUTINE", description="Reclassify me",
        )
        assert wo["version"] == 1
        resp = api.patch_work_order(
            wo["id"],
            {"expected_work_order_version": wo["version"], "priority": "EMERGENCY"},
            DISPATCHER,
        )
        data = validate_success(resp, 200)
        assert data["priority"] == "EMERGENCY"
        # created at the logical-clock default 2026-08-01T00:00:00Z; emergency is +4h/+24h.
        assert_instant_equals(data["response_due_at"], "2026-08-01T04:00:00Z", "response_due_at")
        assert_instant_equals(data["completion_due_at"], "2026-08-02T00:00:00Z", "completion_due_at")
        assert data["version"] == 2

    def test_patch_with_stale_version_returns_412(self, api):
        """PRD §3.2: "This is the first of the two OCC-guarded writes: the request must carry `expected_work_order_version` equal to the work order's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.7: "In both cases, if the supplied value does not equal the work order's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is applied."

        Design: Corner/complexity_layers/patch_with_stale_version_returns_412
        """
        bundle = setup_property_resident_technician("Occ1 Property", unit_number="701")
        wo = create_work_order(
            bundle["property"]["id"], bundle["resident"]["id"],
            category="PLUMBING", priority="ROUTINE", description="Stale edit",
        )
        first = api.patch_work_order(
            wo["id"],
            {"expected_work_order_version": wo["version"], "description": "first edit"},
            DISPATCHER,
        )
        data = validate_success(first, 200)
        assert data["version"] == 2

        stale = api.patch_work_order(
            wo["id"],
            {"expected_work_order_version": wo["version"], "description": "stale edit"},
            DISPATCHER,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        after = get_work_order(wo["id"])
        assert after["description"] == "first edit", "rejected edit must not be applied"
        assert after["version"] == 2


class TestLookupAndListing:
    def test_get_missing_work_order_returns_not_found(self, api):
        """PRD §2.10: "Every URL path identifier and every foreign-key identifier in a request payload must resolve to an existing resource of the right type; otherwise the request is rejected with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/work_order_get_missing_returns_not_found
        """
        resp = api.get_work_order(NON_EXISTENT_UUID, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_error_envelope_shape_for_not_found(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/errors/error_envelope_shape_for_not_found
        """
        resp = api.get_work_order(NON_EXISTENT_UUID, DISPATCHER)
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(error_data["message"], str) and error_data["message"].strip()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)

    def test_work_order_list_paginates_and_filters_by_status(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; it defaults to 10, has a minimum of 1, and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0."
        PRD §2.3: "List responses include the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope."

        Design: Corner/entities/work_order_list_pagination_and_status_filter
        """
        prop = create_property("Page Property")
        resident = create_resident(prop["id"], unit_number="203", full_name="R Page",
                                   email="rpage@x.com")
        for category, priority, description in (
            ("PLUMBING", "ROUTINE", "Job 1"),
            ("HVAC", "URGENT", "Job 2"),
            ("GENERAL", "EMERGENCY", "Job 3"),
        ):
            create_work_order(prop["id"], resident["id"], category=category,
                              priority=priority, description=description)

        page1, meta1 = validate_paginated(
            api.list_work_orders(
                DISPATCHER,
                params={"resident_id": resident["id"], "status": "TRIAGED",
                        "limit": 2, "offset": 0},
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_work_orders(
                DISPATCHER,
                params={"resident_id": resident["id"], "status": "TRIAGED",
                        "limit": 2, "offset": 2},
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        for item in page1 + page2:
            assert item["status"] == "TRIAGED"
            assert item["resident_id"] == resident["id"]
