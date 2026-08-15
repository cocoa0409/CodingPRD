"""List pagination and FK reverse-lookup channels, the fixed startup clock,
and same-request visibility of writes (immediate consistency)."""
from test_helpers import (
    CLOCK_DEFAULT,
    approve_application,
    assert_clock_instant,
    attach_document,
    create_active_policy,
    create_application,
    create_funding_source,
    create_household,
    create_vendor,
    get_application_version,
    issue_payment,
    open_cleared_duplication_check,
    pass_verification,
    setup_pending_decision,
    submit_application,
    TEST_USERS,
    validate_paginated,
    validate_success,
)

CW1 = TEST_USERS["caseworker_headers"]
PM1 = TEST_USERS["program_manager_headers"]
AUD1 = TEST_USERS["auditor_headers"]


class TestListPaginationAndFilters:
    def test_applications_list_pagination_and_filter(self, api):
        """PRD §2.3: "List endpoints accept the `limit` and `offset` query
        parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of
        100; `offset` defaults to 0. List responses order their entries by
        `created_at` ascending. The `meta` object of a list response carries
        `limit`, `offset`, `total_count`, and `has_more`."
        PRD §3.9: "applications filter by `household_id`, `vendor_id`,
        `policy_id`, `status`, and `category`; documents, duplication checks, and
        case notes filter by `application_id`, with notes additionally filtering
        by `note_type`; verifications filter by `application_id` or `vendor_id`;
        awards filter by `application_id`, `policy_id`, or `status`; allocations
        filter by `award_id`, `funding_source_id`, or `status`; funding sources
        and policies filter by `status`; and payments filter by `award_id`,
        `vendor_id`, `funding_source_id`, or `status`."

        Design: Corner/endpoints/applications_list_pagination_and_filter
        """
        landlord = create_vendor("LANDLORD")
        utility = create_vendor(vendor_type="UTILITY", name="City Power & Light")
        household = create_household()
        # Eleven RENT applications in distinct month buckets.
        for month in range(1, 12):
            create_application(
                household["id"], landlord["id"],
                requested_amount_cents=1000, service_month=f"2026-{month:02d}",
            )
        # One UTILITY application (its own category bucket for 2026-08).
        create_application(
            household["id"], utility["id"], category="UTILITY",
            requested_amount_cents=1000, service_month="2026-08",
        )
        page1, meta1 = validate_paginated(
            api.list_applications(
                CW1, params={"household_id": household["id"], "limit": 10, "offset": 0}
            )
        )
        assert len(page1) == 10
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_applications(
                CW1, params={"household_id": household["id"], "limit": 10, "offset": 10}
            )
        )
        assert len(page2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False
        filtered, meta3 = validate_paginated(
            api.list_applications(
                CW1, params={"household_id": household["id"], "category": "UTILITY"}
            )
        )
        assert meta3["total_count"] == 1
        assert len(filtered) == 1
        assert filtered[0]["category"] == "UTILITY"
        body = api.list_applications(
            CW1, params={"household_id": household["id"]}
        ).json()
        assert body["response_type"] == "array"

    def test_fk_reverse_list_channels_resolve(self, api):
        """PRD §3.9: "applications filter by `household_id`, `vendor_id`,
        `policy_id`, `status`, and `category`; documents, duplication checks, and
        case notes filter by `application_id`, with notes additionally filtering
        by `note_type`; verifications filter by `application_id` or `vendor_id`;
        awards filter by `application_id`, `policy_id`, or `status`; allocations
        filter by `award_id`, `funding_source_id`, or `status`; funding sources
        and policies filter by `status`; and payments filter by `award_id`,
        `vendor_id`, `funding_source_id`, or `status`."

        Design: Corner/endpoints/fk_reverse_list_channels_resolve
        """
        ctx = setup_pending_decision(requested_amount_cents=7000)
        app_id = ctx["application"]["id"]
        household_id = ctx["household"]["id"]
        vendor_id = ctx["vendor"]["id"]
        source_id = ctx["source"]["id"]
        approved = approve_application(app_id)
        award_id = approved["active_award_id"]
        issue_payment(award_id, vendor_id, source_id, 7000)

        def single(lst, what):
            assert len(lst) == 1, f"expected exactly 1 {what}, got {len(lst)}"
            return lst[0]

        apps, _ = validate_paginated(
            api.list_applications(AUD1, params={"household_id": household_id})
        )
        assert single(apps, "application")["id"] == app_id

        docs, _ = validate_paginated(
            api.list_documents(AUD1, params={"application_id": app_id})
        )
        assert single(docs, "document")["application_id"] == app_id

        vers, _ = validate_paginated(
            api.list_verifications(AUD1, params={"application_id": app_id})
        )
        assert single(vers, "verification")["id"] == ctx["verification"]["id"]
        vers_by_vendor, _ = validate_paginated(
            api.list_verifications(AUD1, params={"vendor_id": vendor_id})
        )
        assert single(vers_by_vendor, "verification")["id"] == ctx["verification"]["id"]

        checks, _ = validate_paginated(
            api.list_duplication_checks(AUD1, params={"application_id": app_id})
        )
        assert single(checks, "duplication check")["id"] == ctx["check"]["id"]

        awards, _ = validate_paginated(
            api.list_awards(AUD1, params={"application_id": app_id})
        )
        assert single(awards, "award")["id"] == award_id

        allocs, _ = validate_paginated(
            api.list_allocations(AUD1, params={"funding_source_id": source_id})
        )
        assert single(allocs, "allocation")["award_id"] == award_id

        pays, _ = validate_paginated(
            api.list_payments(AUD1, params={"award_id": award_id})
        )
        assert single(pays, "payment")["award_id"] == award_id
        pays_by_vendor, _ = validate_paginated(
            api.list_payments(AUD1, params={"vendor_id": vendor_id})
        )
        assert single(pays_by_vendor, "payment")["vendor_id"] == vendor_id


class TestLogicalClock:
    def test_clock_default_is_fixed_at_startup(self, api):
        """PRD §2.4: "All time inside the service reads a logical clock, never
        the host's wall clock. At startup the clock reads exactly
        2026-08-01T00:00:00Z."
        PRD §2.4: "Every recorded timestamp — `submitted_at`, `waitlisted_at`,
        `denied_at`, `closed_at`, `completed_at`, `cleared_at`, and the default
        for `occurred_at` — is stamped from this clock, and every time-window
        rule in the program (appeal windows, funding periods, benefit years)
        evaluates against it."

        Design: Corner/endpoints/clock_default_is_fixed_at_startup
        """
        # No clock call is ever made in this test: the server starts fresh.
        create_active_policy()
        vendor = create_vendor("LANDLORD")
        household = create_household()
        application = create_application(household["id"], vendor["id"])
        attach_document(application["id"], "EVICTION_NOTICE")
        submitted = submit_application(application["id"])
        assert_clock_instant(submitted["submitted_at"], "2026-08-01T00:00:00Z")

    def test_immediate_visibility_of_writes_in_same_and_next_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.1: "These three are recomputed after every mutation that touches
        the source — approval, payment clearing, award adjustment, award voiding,
        or deposit — and the invariant that committed plus reserved plus
        available always equals `total_budget_cents` holds at all times."
        PRD §3.5: "A successful approval creates the AssistanceAward in `ACTIVE`
        status, pins its `policy_id` to the application's pinned policy, stamps
        its `benefit_year` with the clock's current calendar year, sets its
        `awarded_amount_cents` to the determined amount, points the application's
        `active_award_id` at it, moves the application from `PENDING_DECISION`
        into `APPROVED`, and bumps the application's `version`."

        Design: Corner/consistency_model/immediate_visibility_of_writes_in_same_and_next_response
        """
        ctx = setup_pending_decision(requested_amount_cents=9000)
        # The approve response body itself carries the updated application.
        resp = api.approve_application(ctx["application"]["id"], PM1)
        approved = validate_success(resp, 200)
        assert approved["status"] == "APPROVED"
        assert approved.get("active_award_id"), "active_award_id visible in the same response"
        # A follow-up read of the source shows the reservation already debited.
        source = validate_success(api.get_funding_source(ctx["source"]["id"], AUD1), 200)
        assert source["reserved_cents"] == 9000, "no reconciliation lag"
        assert source["available_cents"] == 100000 - 9000
