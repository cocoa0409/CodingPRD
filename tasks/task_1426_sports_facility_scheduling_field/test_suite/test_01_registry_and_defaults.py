"""Registry creation defaults, single-resource reads, schedule publication,
the logical-clock default, and permit listing pagination."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_facility,
    assert_fee_schedule,
    assert_organization,
    close_allocation_window,
    create_allocation_window,
    create_facility_payload,
    create_fee_schedule,
    create_organization_payload,
    publish_fee_schedule,
    run_allocation,
    set_clock,
    setup_open_season,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOrganizationCreation:
    def test_organization_creation_system_defaults_applied(self, api, athletics_admin_headers):
        """PRD §3.1: "New organizations begin with `standing` `GOOD` and
        `no_show_strikes_active` at 0."
        PRD §2.5: "`id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/organization_creation_system_field_input_ignored_and_defaults_applied
        """
        set_clock()
        org = validate_success(
            api.create_organization(create_organization_payload(), athletics_admin_headers), 201)
        assert_organization(org)
        assert org["standing"] == "GOOD"
        assert org["no_show_strikes_active"] == 0
        assert org["prior_seasons_active"] == 3

    def test_get_organization_not_found_returns_404(self, api, athletics_admin_headers):
        """PRD §2.8: "Path identifiers are validated left to right, and the first
        missing resource produces its dedicated 404: `ERR_ORGANIZATION_NOT_FOUND`,
        `ERR_FACILITY_NOT_FOUND`, `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_CLOSURE_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, or `ERR_STRIKE_NOT_FOUND`."

        Design: Corner/entities/get_organization_not_found_returns_404
        """
        res = api.get_organization(NON_EXISTENT_UUID, athletics_admin_headers)
        validate_error(res, ApiErrorId.ERR_ORGANIZATION_NOT_FOUND)


class TestFacilityCreation:
    def test_facility_creation_defaults_open_condition(self, api, athletics_admin_headers):
        """PRD §3.2: "A new facility begins with `condition_status` `OPEN`, an empty
        `condition_reason`, and `weekly_prime_hours_used` at 0."

        Design: Corner/entities/facility_creation_defaults_open_condition
        """
        facility = validate_success(
            api.create_facility(create_facility_payload(), athletics_admin_headers), 201)
        assert_facility(facility)
        assert facility["condition_status"] == "OPEN"
        assert facility["condition_reason"] == ""
        assert facility["weekly_prime_hours_used"] == 0


class TestFeeSchedulePublication:
    def test_fee_schedule_publish_supersedes_previous(self, api, athletics_admin_headers):
        """PRD §3.3: "At most one schedule is `PUBLISHED` at any moment: publishing a
        new schedule automatically moves the previously `PUBLISHED` one to `SUPERSEDED`,
        a terminal state, and each side of that handoff increments its own schedule's
        `version`."

        Design: Corner/entities/fee_schedule_publish_supersedes_previous
        """
        set_clock()
        fs1 = create_fee_schedule()
        fs2 = create_fee_schedule(name="2026 Revised",
                                  effective_from="2026-08-15T00:00:00Z",
                                  hourly_resident_cents=2200,
                                  lights_block_cents=750)
        publish_fee_schedule(fs1["id"])
        fs2_after = validate_success(
            api.publish_fee_schedule(fs2["id"], athletics_admin_headers), 200)
        assert fs2_after["status"] == "PUBLISHED"
        fs1_after = validate_success(
            api.get_fee_schedule(fs1["id"], athletics_admin_headers), 200)
        assert_fee_schedule(fs1_after)
        assert fs1_after["status"] == "SUPERSEDED"

    def test_publish_superseded_schedule_rejected(self, api, athletics_admin_headers):
        """PRD §3.3: "Publishing is the transition `DRAFT` → `PUBLISHED`, performed by
        an administrator, and it requires that `effective_from` lie no more than 365
        days beyond the logical clock's current date. Publishing a schedule that is
        not in `DRAFT` is rejected with `ERR_INVALID_SCHEDULE_STATE`."

        SUPERSEDED is terminal: re-publishing the superseded schedule is rejected.

        Design: Corner/state_machines/publish_superseded_schedule_rejected
        """
        set_clock()
        fs1 = create_fee_schedule()
        fs2 = create_fee_schedule(name="2026 Revised",
                                  effective_from="2026-08-15T00:00:00Z")
        publish_fee_schedule(fs1["id"])
        publish_fee_schedule(fs2["id"])
        # fs1 is now SUPERSEDED (terminal): re-publishing it is rejected.
        res = api.publish_fee_schedule(fs1["id"], athletics_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_SCHEDULE_STATE)
        fs1_after = validate_success(
            api.get_fee_schedule(fs1["id"], athletics_admin_headers), 200)
        assert fs1_after["status"] == "SUPERSEDED"


class TestLogicalClockDefault:
    def test_clock_default_value_used_when_never_set(self, api, athletics_admin_headers):
        """PRD §2.4: "Before any test-driving call, that clock reads exactly
        `2026-08-01T00:00:00Z`."
        PRD §3.4: "An administrator opens a `SCHEDULED` window only once the logical
        clock has reached `opens_at`; opening earlier fails with
        `ERR_WINDOW_NOT_YET_OPEN`, and opening, closing, or running allocation on a
        window in the wrong state fails with `ERR_INVALID_WINDOW_STATE`."

        No clock call is ever made in this test: the default instant must satisfy the
        >= opens_at guard exactly.

        Design: Corner/endpoints/clock_default_value_used_when_never_set
        """
        window = create_allocation_window(opens_at="2026-08-01T00:00:00Z")
        opened = validate_success(
            api.open_allocation_window(window["id"], athletics_admin_headers), 200)
        assert opened["status"] == "OPEN"


class TestPermitRead:
    def test_get_permit_not_found_returns_404(self, api, athletics_admin_headers):
        """PRD §2.8: "Path identifiers are validated left to right, and the first
        missing resource produces its dedicated 404: `ERR_ORGANIZATION_NOT_FOUND`,
        `ERR_FACILITY_NOT_FOUND`, `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_CLOSURE_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, or `ERR_STRIKE_NOT_FOUND`."

        Design: Corner/errors/get_permit_not_found_returns_404
        """
        res = api.get_permit(NON_EXISTENT_UUID, athletics_admin_headers)
        validate_error(res, ApiErrorId.ERR_PERMIT_NOT_FOUND)


class TestPermitListingPagination:
    def test_list_permits_filter_and_pagination_interaction(self, api, athletics_admin_headers):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter sets how many items to skip and defaults to 0."
        PRD §3.6: "Permits can be browsed through the listing with filters on
        `organization_id`, `facility_id`, `application_id`, `fee_schedule_id`,
        `original_permit_id`, `permit_date`, and `status`."

        The organization filter narrows the corpus to the org's two permits before
        pagination: page 1 (limit 1) reports total_count 2 with has_more true, page 2
        (offset 1) returns the second permit with has_more false.

        Design: Corner/endpoints/list_permits_filter_and_pagination_interaction
        """
        ctx = setup_open_season()
        org_id = ctx["organization"]["id"]
        submit_application(ctx["window"]["id"], ctx["facility"]["id"], org_id,
                           event_date="2026-08-10")
        set_clock("2026-08-01T09:01:00Z")  # keep created_at order == submission order
        submit_application(ctx["window"]["id"], ctx["facility"]["id"], org_id,
                           event_date="2026-08-11")
        close_allocation_window(ctx["window"]["id"])
        run_allocation(ctx["window"]["id"])

        page1, meta1 = validate_paginated(api.list_permits(
            athletics_admin_headers,
            params={"organization_id": org_id, "limit": 1, "offset": 0}))
        assert len(page1) == 1, f"page 1 must hold exactly 1 permit, got {len(page1)}"
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_permits(
            athletics_admin_headers,
            params={"organization_id": org_id, "limit": 1, "offset": 1}))
        assert len(page2) == 1, f"page 2 must hold exactly 1 permit, got {len(page2)}"
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert page2[0]["id"] != page1[0]["id"], "pages must be disjoint"
