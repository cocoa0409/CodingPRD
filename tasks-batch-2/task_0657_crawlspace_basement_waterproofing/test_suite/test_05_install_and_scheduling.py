"""Install-order lifecycle, cost reconciliation, the complete cascade, crew-booking
overlap/capacity guards, financing-resolved precondition, OCC stale-version on create,
and the create->cancel conserved scheduling link.

Covers Difficulty queue: dual_variant_calc (install reconciliation variance),
transitive_cascade (install complete depth-3), cross_entity_state_dependency
(install requires financing resolved), boundary_precision_check (crew daily-capacity
zero-remaining), resource_temporal_overlap (half-open interval), compensating_invariant
(schedule link create-then-cancel).
Covers Corner queue: terminal COMPLETED cannot cancel, fail->restart rework loop,
immediate visibility of final_total_cents, OCC install-order create stale job.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_crew_payload, create_crew_booking_payload, create_install_order_payload,
    create_financing_application_payload,
    setup_sold_job, setup_sold_cash_job, setup_planned_install_order,
    setup_passed_install_order, setup_warranted_job, setup_scheduled_job_seed,
    setup_submitted_financing,
    TEST_USERS,
)

EST = TEST_USERS["estimator_headers"]
INS = TEST_USERS["inspector_headers"]
SCH = TEST_USERS["scheduler_headers"]
FIN = TEST_USERS["finance_partner_headers"]


class TestInstallReconciliation:
    def test_complete_with_actual_drain_reconciles_final_and_variance(self, api):
        """PRD §3.7: "The reconciliation re-runs the same pricing formula and pinned order
        used for the quote, but on the accepted quote's frozen scope flags and substituting
        `actual_drain_linear_ft` for the quoted `drain_linear_ft`: the billable drain
        footage is the actual footage minus the 20 free feet but never below zero ...
        charged at 4,500 cents per foot ... and the result becomes `final_total_cents`.
        The `variance_cents` is `final_total_cents` minus the accepted quote's
        `total_cents`".

        Design: Difficulty/dual_variant_calc/install_reconciliation_variance_vs_quoted_estimate
        """
        # Accepted Quote: 1000 sqft full scope SPRING10, drain 50 -> total 890775.
        # Reconcile with actual_drain 80: drain billable (80-20)*4500=270000;
        # subtotal = 400000+180000+120000+90000+270000 = 1060000; SPRING10 disc 106000;
        # discounted 954000; tax round(954000*0.07)=66780; final 1020780;
        # variance 1020780-890775 = 130005.
        ctx = setup_passed_install_order(
            footprint_sqft=1000, day="2026-05-01",
            quote_overrides={"includes_vapor_barrier": True, "includes_sump": True,
                             "includes_drain": True, "includes_battery_backup": True,
                             "drain_linear_ft": 50, "discount_code": "SPRING10"})
        io_id = ctx["install_order"]["id"]
        completed = validate_success(
            api.complete_install_order(io_id, {"actual_drain_linear_ft": 80}, SCH), 200)
        assert completed["final_total_cents"] == 1020780
        assert completed["variance_cents"] == 130005
        assert ctx["quote"]["total_cents"] == 890775


class TestInstallCompleteCascade:
    def test_complete_cascades_to_job_and_crew_booking(self, api):
        """PRD §3.7: "On completion the order moves from `PASSED` to `COMPLETED`, the Job
        advances from `SCHEDULED` to `INSTALLED`, every crew booking for that order still
        in `RESERVED` or `CONFIRMED` is released to `RELEASED`, and the final cost is
        reconciled."

        Design: Difficulty/transitive_cascade/install_complete_cascade_depth3
        """
        ctx = setup_passed_install_order(footprint_sqft=600, day="2026-05-02",
                                        quote_overrides={"includes_sump": True})
        io_id = ctx["install_order"]["id"]
        completed = validate_success(api.complete_install_order(io_id, {}, SCH), 200)
        assert completed["status"] == "COMPLETED"

        job_after = validate_success(api.get_job(ctx["job"]["id"], EST), 200)
        assert job_after["lifecycle_status"] == "INSTALLED"
        booking_after = validate_success(
            api.get_crew_booking(ctx["crew_booking"]["id"], SCH), 200)
        assert booking_after["status"] == "RELEASED"

    def test_complete_response_carries_reconciled_total_immediately(self, api):
        """PRD §3.7: "On completion the order moves from `PASSED` to `COMPLETED` ... and
        the final cost is reconciled."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
        return the created or updated resource object in the data field."

        Design: Corner/consistency_model/install_complete_immediate_visibility
        """
        # seed scheduled job uses sump-only quote (total 395900) with no drain; actual drain
        # defaults to 0, so reconciled final equals the quoted total 395900.
        seed = setup_scheduled_job_seed()
        io_id = seed["install_order_id"]
        crew = get_success_data(api.create_crew(
            create_crew_payload(name="Foxtrot", daily_capacity=3), SCH))
        booking = get_success_data(api.create_crew_booking(
            create_crew_booking_payload(crew["id"], io_id,
                                       "2026-05-12T08:00:00Z", "2026-05-12T17:00:00Z"), SCH))
        get_success_data(api.confirm_crew_booking(booking["id"], SCH))
        get_success_data(api.dispatch_install_order(io_id, SCH))
        api.set_clock("2026-05-12T09:00:00Z", SCH)
        get_success_data(api.start_install_order(io_id, SCH))
        get_success_data(api.inspect_pass_install_order(io_id, INS))

        completed = validate_success(api.complete_install_order(io_id, {}, SCH), 200)
        assert completed["status"] == "COMPLETED"
        assert completed["final_total_cents"] == 395900


class TestInstallRework:
    def test_fail_then_restart_returns_to_in_progress(self, api):
        """PRD §3.7: "A failed install loops back for rework: starting it again moves
        `FAILED` to `IN_PROGRESS` (with no clock precondition on the restart)."

        Design: Corner/state_machines/install_fail_then_restart_rework_loop
        """
        seed = setup_scheduled_job_seed()
        io_id = seed["install_order_id"]
        crew = get_success_data(api.create_crew(
            create_crew_payload(name="Echo", daily_capacity=3), SCH))
        booking = get_success_data(api.create_crew_booking(
            create_crew_booking_payload(crew["id"], io_id,
                                       "2026-05-10T08:00:00Z", "2026-05-10T17:00:00Z"), SCH))
        get_success_data(api.confirm_crew_booking(booking["id"], SCH))
        get_success_data(api.dispatch_install_order(io_id, SCH))
        api.set_clock("2026-05-10T09:00:00Z", SCH)
        get_success_data(api.start_install_order(io_id, SCH))
        get_success_data(api.inspect_fail_install_order(io_id, INS))

        restarted = validate_success(api.start_install_order(io_id, SCH), 200)
        assert restarted["status"] == "IN_PROGRESS"

    def test_completed_install_cannot_be_cancelled(self, api):
        """PRD §3.7: "An InstallOrder's `status` moves through `PLANNED`, `DISPATCHED`,
        `IN_PROGRESS`, `PASSED` or `FAILED`, `COMPLETED`, or `CANCELLED`, with `COMPLETED`
        and `CANCELLED` terminal."
        PRD §3.7: "A planned or dispatched install may instead be cancelled by the
        `Scheduler`. Cancelling is permitted only from `PLANNED` or `DISPATCHED`".

        Design: Corner/state_machines/terminal_install_completed_cannot_cancel
        """
        ctx = setup_warranted_job()  # install order is COMPLETED on a WARRANTED job
        res = api.cancel_install_order(ctx["install_order_id"], SCH)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


class TestInstallFinancingPrecondition:
    def test_install_create_without_resolved_financing_rejected(self, api):
        """PRD §3.7: "This is permitted only when the Job is `SOLD` and its
        `financing_status` is either `CASH` or `APPROVED`; an attempt while financing is
        still unresolved (any status other than `CASH` or `APPROVED`) is rejected with
        `ERR_FINANCING_UNRESOLVED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/install_order_requires_job_financing_resolved
        """
        # SOLD job whose financing_status is still NONE (no pay-cash, no approval).
        ctx = setup_sold_job(credit_band="PRIME", footprint_sqft=600,
                            quote_overrides={"includes_sump": True})
        res = api.create_install_order(
            ctx["job"]["id"],
            create_install_order_payload("2026-05-06T08:00:00Z", "2026-05-06T17:00:00Z",
                                        ctx["job_version"]),
            SCH)
        validate_error(res, "ERR_FINANCING_UNRESOLVED", expected_status=409)
        job_after = validate_success(api.get_job(ctx["job"]["id"], EST), 200)
        assert job_after["lifecycle_status"] == "SOLD"
        assert job_after["financing_status"] == "NONE"


class TestInstallOrderOcc:
    def test_install_create_with_stale_job_version_rejected(self, api):
        """PRD §2.8: "The install-order creation operation requires a body field
        `expected_job_version` carrying the `version` of the target Job that the client
        last read. If that value does not equal the Job's current `version`, the create is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.8: "a Job can remain in lifecycle status `SOLD` while its `version` is
        bumped underneath the client — for instance when a financing decision flips
        `financing_status` from `APPLIED` to `APPROVED` without leaving `SOLD`."

        Design: Corner/cross_cutting_complexity_layers/occ_install_order_create_stale_job
        """
        # SOLD job with a SUBMITTED application; record stale version, then approve to bump.
        ctx = setup_submitted_financing(credit_band="PRIME", footprint_sqft=600,
                                       term_months=36,
                                       quote_overrides={"includes_sump": True})
        stale_jv = validate_success(api.get_job(ctx["job"]["id"], SCH), 200)["version"]
        validate_success(api.decide_financing(ctx["app"]["id"], {"decision": "APPROVE"}, FIN), 200)

        res = api.create_install_order(
            ctx["job"]["id"],
            create_install_order_payload("2026-05-20T08:00:00Z", "2026-05-20T17:00:00Z",
                                        stale_jv),
            SCH)
        validate_error(res, "ERR_STALE_VERSION", expected_status=412)
        job_after = validate_success(api.get_job(ctx["job"]["id"], SCH), 200)
        assert job_after["lifecycle_status"] == "SOLD"


class TestScheduleLinkConserved:
    def test_install_create_then_cancel_restores_job_link(self, api):
        """PRD §3.7: "On success an InstallOrder is created in status `PLANNED` with its
        `job_id` set, its `quote_id` pinned ..., the Job's `install_order_id` pointed at
        the new order, and the Job advanced from `SOLD` to `SCHEDULED`".
        PRD §3.7: "Cancelling is permitted only from `PLANNED` or `DISPATCHED`; it moves
        the order to `CANCELLED`, releases every crew booking ..., reverts the Job's
        `lifecycle_status` from `SCHEDULED` back to `SOLD`, clears the Job's
        `install_order_id` back to null".

        Design: Difficulty/compensating_invariant/schedule_link_conserved_install_create_then_cancel
        """
        ctx = setup_planned_install_order(footprint_sqft=600,
                                         quote_overrides={"includes_sump": True},
                                         scheduled_start="2026-05-08T08:00:00Z",
                                         scheduled_end="2026-05-08T17:00:00Z")
        io_id = ctx["install_order"]["id"]
        cancelled = validate_success(api.cancel_install_order(io_id, SCH), 200)
        assert cancelled["status"] == "CANCELLED"

        job_after = validate_success(api.get_job(ctx["job"]["id"], EST), 200)
        assert job_after["lifecycle_status"] == "SOLD"
        assert job_after["install_order_id"] is None


class TestCrewBookingGuards:
    def test_confirm_at_zero_remaining_capacity_rejected(self, api):
        """PRD §3.8: "confirming must not push the crew over its `daily_capacity`: the
        count of the crew's `CONFIRMED` bookings on the booking's calendar day must remain
        below `daily_capacity`, and a confirm that would exceed it is rejected with
        `ERR_CREW_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/crew_daily_capacity_zero_remaining_boundary
        """
        crew = get_success_data(api.create_crew(
            create_crew_payload(name="Charlie", daily_capacity=1), SCH))
        seed1 = setup_scheduled_job_seed()
        seed2 = setup_scheduled_job_seed()
        io1, io2 = seed1["install_order_id"], seed2["install_order_id"]
        cb1 = get_success_data(api.create_crew_booking(
            create_crew_booking_payload(crew["id"], io1,
                                       "2026-05-05T08:00:00Z", "2026-05-05T12:00:00Z"), SCH))
        validate_success(api.confirm_crew_booking(cb1["id"], SCH), 200)
        cb2 = get_success_data(api.create_crew_booking(
            create_crew_booking_payload(crew["id"], io2,
                                       "2026-05-05T13:00:00Z", "2026-05-05T17:00:00Z"), SCH))

        res = api.confirm_crew_booking(cb2["id"], SCH)
        validate_error(res, "ERR_CREW_CAPACITY_EXCEEDED", expected_status=409)
        cb2_after = validate_success(api.get_crew_booking(cb2["id"], SCH), 200)
        assert cb2_after["status"] == "RESERVED"

    def test_confirm_overlapping_window_rejected(self, api):
        """PRD §3.8: "the booking must not overlap any existing `CONFIRMED` booking on the
        same crew: two windows collide when their half-open
        `window_start`-to-`window_end` intervals intersect, and a colliding confirm is
        rejected with `ERR_CREW_DOUBLE_BOOKED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/crew_booking_half_open_interval_overlap
        """
        # daily_capacity 5 so capacity is not the constraint; CONFIRMED [12,16) then
        # confirm [10,14) which intersects (12,14).
        crew = get_success_data(api.create_crew(
            create_crew_payload(name="Delta", daily_capacity=5), SCH))
        seed1 = setup_scheduled_job_seed()
        seed2 = setup_scheduled_job_seed()
        io1, io2 = seed1["install_order_id"], seed2["install_order_id"]
        cb1 = get_success_data(api.create_crew_booking(
            create_crew_booking_payload(crew["id"], io1,
                                       "2026-05-07T12:00:00Z", "2026-05-07T16:00:00Z"), SCH))
        validate_success(api.confirm_crew_booking(cb1["id"], SCH), 200)
        cb2 = get_success_data(api.create_crew_booking(
            create_crew_booking_payload(crew["id"], io2,
                                       "2026-05-07T10:00:00Z", "2026-05-07T14:00:00Z"), SCH))

        res = api.confirm_crew_booking(cb2["id"], SCH)
        validate_error(res, "ERR_CREW_DOUBLE_BOOKED", expected_status=409)
        cb2_after = validate_success(api.get_crew_booking(cb2["id"], SCH), 200)
        assert cb2_after["status"] == "RESERVED"
