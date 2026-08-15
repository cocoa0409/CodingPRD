"""Optimistic concurrency on work-order writes and per-mutation version
increments."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_records_request,
    assign_auditor,
    create_appointment_payload,
    create_payroll_allocation_payload,
    refresh_work_order,
    setup_selected_work_order,
    validate_error,
    validate_success,
    wo_version,
)

MANAGER = TEST_USERS["audit_manager_headers"]


class TestOptimisticConcurrency:
    def test_occ_stale_version_appointment_create(self, api):
        """PRD: "Exactly two write operations are protected by optimistic
        concurrency control, and both require the request to carry
        `expected_work_order_version` holding the client-side `version` of the
        parent work order as last observed: **scheduling an appointment** on a
        work order, and **creating a payroll allocation** on a work order. If
        the supplied value does not equal the work order's current `version` —
        because another write has advanced it since the client last read the
        resource — the request is rejected with `ERR_STALE_VERSION` (HTTP
        412), forcing the client to re-read before acting."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_appointment_create
        """
        ctx = setup_selected_work_order(
            policy_number="WC-O1", estimated_annual_premium_cents=2000000,
            minimum_premium_cents=100000)
        observed_version = ctx["work_order"]["version"]

        first = api.create_appointment(
            ctx["work_order"]["id"],
            create_appointment_payload(
                scheduled_start="2026-08-10T09:00:00Z",
                scheduled_end="2026-08-10T11:00:00Z",
                expected_work_order_version=observed_version),
            ctx["auditor_headers"])
        appt = validate_success(first, 201)
        assert appt["status"] == "SCHEDULED"
        assert refresh_work_order(ctx)["version"] > observed_version

        stale = api.create_appointment(
            ctx["work_order"]["id"],
            create_appointment_payload(
                scheduled_start="2026-08-11T09:00:00Z",
                scheduled_end="2026-08-11T11:00:00Z", location_type="VIRTUAL",
                expected_work_order_version=observed_version),
            ctx["auditor_headers"])
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_stale_version_allocation_create(self, api):
        """PRD: "If the supplied value does not equal the work order's current
        `version` — because another write has advanced it since the client
        last read the resource — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read before
        acting."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_allocation_create
        """
        ctx = setup_selected_work_order(policy_number="WC-O2")
        observed_version = wo_version(ctx)
        # Another write advances the version after the client read it.
        add_records_request(ctx, "TAX_FILINGS")
        assert refresh_work_order(ctx)["version"] == observed_version + 1

        resp = api.create_payroll_allocation(
            ctx["work_order"]["id"],
            create_payroll_allocation_payload(
                class_code_id=ctx["cc"]["id"], gross_payroll_dollars=40000,
                expected_work_order_version=observed_version),
            ctx["auditor_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestVersioning:
    def test_version_increments_on_each_mutation(self, api):
        """PRD: "`version` (integer): starts at 1 and increments by one on
        every mutation of the resource."
        PRD: "A successful assignment sets `assigned_auditor_id` and
        increments the work order's `version`."
        PRD: "Records intake begins when an `AuditManager` files the first
        records request against the work order, moving it `SELECTED →
        RECORDS_REQUESTED` and incrementing its `version`"

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
        """
        ctx = setup_selected_work_order(policy_number="WC-O3", assign=False,
                                        request_types=())
        assert ctx["work_order"]["version"] == 1, (
            "A selection-created work order starts at version 1")

        assigned = assign_auditor(ctx)
        assert assigned["version"] == 2

        add_records_request(ctx, "PAYROLL_SUMMARY")
        assert ctx["work_order"]["version"] == 3
