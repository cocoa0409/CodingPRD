"""Vendor onboarding and RBAC, assignment creation gates, weekly capacity
ledger boundaries, and the vendor-termination cascade."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_plan_entry,
    assert_vendor_hours_invariant,
    complete_assignment,
    create_approved_plan,
    create_assignment,
    create_assignment_payload,
    create_plan,
    create_title,
    create_vendor,
    create_vendor_payload,
    get_assignment,
    get_plan,
    get_vendor,
    set_clock,
    transition_assignment,
    transition_vendor,
    validate_error,
    validate_paginated,
    validate_success,
)

VM_HEADERS = TEST_USERS["vendor_manager_headers"]
READER_HEADERS = TEST_USERS["reader_headers"]


class TestVendorListing:
    def test_vendor_list_pagination_envelope(self, api, reader_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum
        of 1 and a maximum of 100."
        PRD §2.3: "Paginated and non-paginated list-based responses include
        the following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/vendor_list_pagination_envelope
        """
        for name in ("VendorP1", "VendorP2", "VendorP3"):
            create_vendor(name=name, weekly_capacity_hours=10,
                          cost_rate_cents_per_hour=1000)
        page1, meta1 = validate_paginated(
            api.list_vendors(reader_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_vendors(reader_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestVendorRbac:
    def test_vendor_create_forbidden_for_qa_lead(self, api, qa_lead_headers,
                                                 reader_headers):
        """PRD §3.3: "A `VendorManager` onboards a vendor with a unique legal
        `name`, a `weekly_capacity_hours` contract between 1 and 10000
        tester-hours per ISO week, and a `cost_rate_cents_per_hour` billing
        rate of at least one cent."
        PRD §2.1: "When a declared role attempts an operation reserved for a
        different role — including the per-transition role restrictions on
        lifecycle endpoints — the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/vendor_create_forbidden_for_qalead
        """
        resp = api.create_vendor(
            create_vendor_payload(name="VendorNo", weekly_capacity_hours=10,
                                  cost_rate_cents_per_hour=1000),
            qa_lead_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        _rows, meta = validate_paginated(api.list_vendors(reader_headers))
        assert meta["total_count"] == 0


class TestAssignmentCreationGates:
    def test_assignment_week_must_start_on_monday(self, api):
        """PRD §3.3: "the consumed week starts on a Monday
        (`ERR_WEEK_START_NOT_MONDAY`)"

        Design: Corner/entities/assignment_week_must_be_monday_rejected
        """
        title = create_title(title_code="ENT-T5", cert_budget_total_cents=1000)
        vendor = create_vendor(name="VendorE5")
        plan = create_plan(title["id"], "PS5")
        add_plan_entry(plan["id"], feature_area="COMBAT",
                       required_coverage_hours=1)
        resp = api.create_assignment(
            create_assignment_payload(
                vendor["id"], plan["id"], feature_area="COMBAT",
                week_start_date="2026-08-04", reserved_hours=4,  # a Tuesday
            ),
            VM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_WEEK_START_NOT_MONDAY)

    def test_assignment_with_unknown_plan_not_found(self, api):
        """PRD §2.8: "Path identifiers are validated left to right, then body
        foreign-key references (vendor, plan, build, regression target), then
        resolution of an embedded plan entry by feature area — otherwise
        `ERR_NOT_FOUND` or `ERR_ENTRY_NOT_FOUND` (both HTTP 404)."

        Design: Corner/entities/assignment_unknown_plan_not_found
        """
        vendor = create_vendor(name="VendorE7", weekly_capacity_hours=10,
                               cost_rate_cents_per_hour=1000)
        resp = api.create_assignment(
            create_assignment_payload(
                vendor["id"], NON_EXISTENT_UUID, feature_area="COMBAT",
                week_start_date="2026-08-03", reserved_hours=4,
            ),
            VM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_assignment_with_unknown_feature_area_not_found(self, api):
        """PRD §3.3: "the feature area resolves to an embedded entry of that
        plan (`ERR_ENTRY_NOT_FOUND`)"

        Design: Corner/validations/assignment_unknown_feature_area_not_found
        """
        title = create_title(title_code="VAL-ENT", cert_budget_total_cents=1000)
        vendor = create_vendor(name="VendorEnt")
        plan = create_plan(title["id"], "PS5")
        add_plan_entry(plan["id"], feature_area="COMBAT",
                       required_coverage_hours=1)
        resp = api.create_assignment(
            create_assignment_payload(
                vendor["id"], plan["id"], feature_area="NOPE",
                week_start_date="2026-08-03", reserved_hours=4,
            ),
            VM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_FOUND)

    def test_assignment_on_suspended_vendor_rejected(self, api):
        """PRD §3.3: "Creation enforces, in cascade order: the vendor exists
        and is `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`)"

        Design: Corner/validations/assignment_on_suspended_vendor_rejected
        """
        title = create_title(title_code="VAL-VND", cert_budget_total_cents=1000)
        vendor = create_vendor(name="VendorSus")
        transition_vendor(vendor["id"], "SUSPENDED")
        plan = create_plan(title["id"], "PS5")
        add_plan_entry(plan["id"], feature_area="COMBAT",
                       required_coverage_hours=1)
        resp = api.create_assignment(
            create_assignment_payload(
                vendor["id"], plan["id"], feature_area="COMBAT",
                week_start_date="2026-08-03", reserved_hours=4,
            ),
            VM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_ACTIVE)
        transition_vendor(vendor["id"], "ACTIVE")
        created = api.create_assignment(
            create_assignment_payload(
                vendor["id"], plan["id"], feature_area="COMBAT",
                week_start_date="2026-08-03", reserved_hours=4,
            ),
            VM_HEADERS,
        )
        validate_success(created, expected_status=201)


class TestWeeklyCapacityBoundary:
    def _setup_vendor_at_32_of_40(self):
        """Clock inside the ISO week of Monday 2026-08-03; vendor at 32/40
        committed hours for that week."""
        set_clock("2026-08-04T00:00:00Z")
        title = create_title(title_code="BND-CAP", cert_budget_total_cents=500000)
        vendor = create_vendor(name="VendorCap", weekly_capacity_hours=40,
                               cost_rate_cents_per_hour=5000)
        plan = create_plan(title["id"], "PS5")
        add_plan_entry(plan["id"], feature_area="COMBAT",
                       required_coverage_hours=1)
        create_assignment(vendor["id"], plan["id"], feature_area="COMBAT",
                          week_start_date="2026-08-03", reserved_hours=32)
        return title, vendor, plan

    def test_capacity_exact_fit_accepted_then_overflow_rejected(self, api):
        """PRD §3.3: "the reservation does not push the week's committed total
        above `weekly_capacity_hours` (`ERR_VENDOR_CAPACITY_EXCEEDED`, HTTP
        409), where a reservation landing exactly at the cap is allowed."

        Design: Difficulty/boundary_precision_check/vendor_weekly_capacity_exact_fit
        """
        _title, vendor, plan = self._setup_vendor_at_32_of_40()
        exact = api.create_assignment(
            create_assignment_payload(vendor["id"], plan["id"],
                                      feature_area="COMBAT",
                                      week_start_date="2026-08-03",
                                      reserved_hours=8),
            VM_HEADERS,
        )
        validate_success(exact, expected_status=201)
        over = api.create_assignment(
            create_assignment_payload(vendor["id"], plan["id"],
                                      feature_area="COMBAT",
                                      week_start_date="2026-08-03",
                                      reserved_hours=1),
            VM_HEADERS,
        )
        validate_error(over, ApiErrorId.ERR_VENDOR_CAPACITY_EXCEEDED)

    def test_capacity_exact_fit_leaves_zero_available(self, api):
        """PRD §3.3: "`committed_hours_current_week` is the sum of
        `reserved_hours` over the vendor's assignments whose `week_start_date`
        is the Monday of the logical clock's current ISO week and whose status
        is `SCHEDULED` or `IN_PROGRESS`; `available_hours_current_week` is the
        contracted capacity minus that commitment."

        Design: Difficulty/boundary_precision_check/vendor_weekly_capacity_exact_fit
        """
        _title, vendor, plan = self._setup_vendor_at_32_of_40()
        exact = api.create_assignment(
            create_assignment_payload(vendor["id"], plan["id"],
                                      feature_area="COMBAT",
                                      week_start_date="2026-08-03",
                                      reserved_hours=8),
            VM_HEADERS,
        )
        validate_success(exact, expected_status=201)
        view = get_vendor(vendor["id"])
        assert view["committed_hours_current_week"] == 40
        assert view["available_hours_current_week"] == 0
        assert_vendor_hours_invariant(view)


class TestVendorHoursConservation:
    def _setup(self):
        set_clock("2026-08-04T00:00:00Z")
        title = create_title(title_code="INV-HRS", cert_budget_total_cents=500000)
        vendor = create_vendor(name="VendorInv", weekly_capacity_hours=40,
                               cost_rate_cents_per_hour=5000)
        plan = create_plan(title["id"], "PS5")
        add_plan_entry(plan["id"], feature_area="COMBAT",
                       required_coverage_hours=1)
        return title, vendor, plan

    def test_create_then_cancel_restores_bucket(self, api):
        """PRD §3.3: "The weekly ledger obeys a conservation invariant —
        committed plus available always equals `weekly_capacity_hours` —
        across every forward action (reserving hours) and every compensating
        action (cancellation, completion, or the termination cascade)."

        Design: Difficulty/compensating_invariant/vendor_hours_cancel_conservation
        """
        _title, vendor, plan = self._setup()
        a1 = create_assignment(vendor["id"], plan["id"], feature_area="COMBAT",
                               week_start_date="2026-08-03", reserved_hours=15)
        view = get_vendor(vendor["id"])
        assert view["committed_hours_current_week"] == 15
        assert view["available_hours_current_week"] == 25
        assert_vendor_hours_invariant(view)
        transition_assignment(a1["id"], "CANCELLED")
        view = get_vendor(vendor["id"])
        assert view["committed_hours_current_week"] == 0
        assert view["available_hours_current_week"] == 40
        assert_vendor_hours_invariant(view)

    def test_create_then_complete_frees_reservation(self, api):
        """PRD §3.3: "Completion frees the weekly reservation (a `DONE`
        assignment stops consuming capacity) while the hours continue to count
        toward plan-entry coverage."

        Design: Difficulty/compensating_invariant/vendor_hours_cancel_conservation
        """
        _title, vendor, plan = self._setup()
        a2 = create_assignment(vendor["id"], plan["id"], feature_area="COMBAT",
                               week_start_date="2026-08-03", reserved_hours=20)
        view = get_vendor(vendor["id"])
        assert view["committed_hours_current_week"] == 20
        assert view["available_hours_current_week"] == 20
        assert_vendor_hours_invariant(view)
        complete_assignment(a2["id"], actual_hours=18)
        view = get_vendor(vendor["id"])
        assert view["committed_hours_current_week"] == 0
        assert view["available_hours_current_week"] == 40
        assert_vendor_hours_invariant(view)


class TestVendorTerminationCascade:
    def _setup_approved_plan_with_two_entries(self):
        set_clock("2026-08-04T00:00:00Z")
        title = create_title(title_code="CASC-VND", cert_budget_total_cents=500000)
        vendor = create_vendor(name="VendorTerm", weekly_capacity_hours=40,
                               cost_rate_cents_per_hour=5000)
        plan = create_approved_plan(
            title["id"], vendor["id"], "PS5",
            entries=(("COMBAT", 10, True), ("NETWORK", 6, True)),
        )
        return title, vendor, plan

    def test_termination_cancels_assignments_and_demotes_plan(self, api):
        """PRD §3.3: "Terminating a vendor fires the same cancellation cascade
        across every one of its `SCHEDULED` or `IN_PROGRESS` assignments
        automatically."
        PRD §3.2: "if a cancellation drops a cert-blocker entry below
        `COVERED` on an `APPROVED` plan, the plan is demoted `APPROVED` →
        `DRAFT` as part of the cancellation cascade."

        Design: Difficulty/transitive_cascade/vendor_termination_cascade_assignments_plan
        """
        _title, vendor, plan = self._setup_approved_plan_with_two_entries()
        rows, meta = validate_paginated(
            api.list_assignments(READER_HEADERS, params={"plan_id": plan["id"]})
        )
        assert meta["total_count"] == 2
        transition_vendor(vendor["id"], "TERMINATED")
        for row in rows:
            assert get_assignment(row["id"])["status"] == "CANCELLED"
        after = get_plan(plan["id"])
        assert after["status"] == "DRAFT"
        assert after["covered_required_count"] == 0

    def test_termination_releases_committed_hours(self, api):
        """PRD §3.3: "Cancelling from `SCHEDULED` or `IN_PROGRESS` moves the
        assignment to `CANCELLED`, releases its `reserved_hours` from the
        vendor's weekly commitment, and recomputes entry coverage"

        Design: Difficulty/transitive_cascade/vendor_termination_cascade_assignments_plan
        """
        _title, vendor, plan = self._setup_approved_plan_with_two_entries()
        view = get_vendor(vendor["id"])
        assert view["committed_hours_current_week"] == 16
        transition_vendor(vendor["id"], "TERMINATED")
        view = get_vendor(vendor["id"])
        assert view["status"] == "TERMINATED"
        assert view["committed_hours_current_week"] == 0
        assert_vendor_hours_invariant(view)
