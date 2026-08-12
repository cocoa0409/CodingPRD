"""Non-linear state machines: the interlocked assessment/work-order cycles and
the parallel order_status x fulfillment_status axes on one SupplyOrder."""
from test_helpers import (
    validate_success, ApiErrorId, validate_error, get_success_data,
    create_program, create_patient, create_active_home_patient,
    create_approved_order, schedule_appointment, complete_appointment,
    set_clock, create_machine,
    api_client, make_admin_headers, make_nurse_headers,
    make_biomed_headers, make_coordinator_headers,
    create_home_assessment_payload, create_work_order_payload,
)
from test_helpers.assertions import assert_supply_order


class TestHomeAssessmentRemediationResubmissionCycle:
    """Two interlocked cycles: the assessment loops
    SUBMITTED -> REMEDIATION_REQUIRED -> SUBMITTED -> ACCEPTED while its work
    order loops through a failed inspection rework cycle."""

    def test_work_order_rework_loop_unblocks_resubmit(self, api):
        """PRD §3.3: "A `ProgramAdmin` approves and schedules one — from
        `REQUESTED`, or from `INSPECTED_FAIL` as a rework cycle — by storing
        `scheduled_window_start` and `scheduled_window_end`, which must be
        strictly ordered with the start before the end (`ERR_INVALID_REQUEST`);
        the order becomes `SCHEDULED`."
        PRD §3.3: "Resubmission returns a `REMEDIATION_REQUIRED` assessment to
        `SUBMITTED` with fresh measurements supplied in the payload"

        Design: Difficulty/non_linear_state_machine/home_assessment_remediation_resubmission_cycle
        """
        program = create_program()
        patient = create_patient(program["id"])
        resp = api.create_home_assessment(
            create_home_assessment_payload(patient["id"],
                                           water_chloramine_ppm=0.2),
            make_nurse_headers("nurse-1"))
        asmt = validate_success(resp, 201)
        assert asmt["result"] == "FAIL", "chloramine 0.2 > 0.1 fails"
        validate_success(api.require_remediation(asmt["id"],
                                                 make_nurse_headers("nurse-2")))
        wo = validate_success(api.create_work_order(
            create_work_order_payload(patient["id"], asmt["id"],
                                      cost_estimate_cents=250000),
            make_nurse_headers("nurse-1")), 201)
        # First cycle: approve -> complete -> inspect fail.
        validate_success(api.approve_work_order(
            wo["id"], {"scheduled_window_start": "2026-05-05T08:00:00Z",
                       "scheduled_window_end": "2026-05-05T16:00:00Z"},
            make_admin_headers("admin-1")))
        validate_success(api.complete_work_order(
            wo["id"], {"final_cost_cents": 240000},
            make_biomed_headers("biomed-1")))
        failed = validate_success(api.inspect_work_order(
            wo["id"], {"passed": False}, make_biomed_headers("biomed-1")))
        assert failed["status"] == "INSPECTED_FAIL"
        # Resubmit still blocked while the work order is unsettled.
        resp = api.resubmit_assessment(
            asmt["id"],
            {"water_chloramine_ppm": 0.05, "electrical_dedicated_circuit": True,
             "electrical_voltage_verified": True, "storage_area_sqft": 100},
            make_nurse_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_WORK_ORDERS_OUTSTANDING)
        # Rework cycle: approve from INSPECTED_FAIL -> complete -> inspect pass.
        validate_success(api.approve_work_order(
            wo["id"], {"scheduled_window_start": "2026-05-12T08:00:00Z",
                       "scheduled_window_end": "2026-05-12T16:00:00Z"},
            make_admin_headers("admin-1")))
        validate_success(api.complete_work_order(
            wo["id"], {"final_cost_cents": 245000},
            make_biomed_headers("biomed-1")))
        passed = validate_success(api.inspect_work_order(
            wo["id"], {"passed": True}, make_biomed_headers("biomed-1")))
        assert passed["status"] == "INSPECTED_PASS"
        resubmitted = validate_success(api.resubmit_assessment(
            asmt["id"],
            {"water_chloramine_ppm": 0.05, "electrical_dedicated_circuit": True,
             "electrical_voltage_verified": True, "storage_area_sqft": 100},
            make_nurse_headers("nurse-1")))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["result"] == "PASS"

    def test_resubmitted_assessment_accepts_with_recomputed_cap(self, api):
        """PRD §3.3: "Resubmission replaces the measurement fields, recomputes
        `result` and `storage_cap_units`, and refreshes `assessed_by_user_id`
        to the resubmitting nurse, which means the next acceptance must again
        come from a different nurse."
        PRD §3.3: "The first is `storage_cap_units`: four units per certified
        square foot, rounded down to a whole unit, and capped at 400 units."

        Design: Difficulty/non_linear_state_machine/home_assessment_remediation_resubmission_cycle
        """
        program = create_program()
        patient = create_patient(program["id"])
        asmt = validate_success(api.create_home_assessment(
            create_home_assessment_payload(patient["id"],
                                           water_chloramine_ppm=0.2),
            make_nurse_headers("nurse-1")), 201)
        validate_success(api.require_remediation(asmt["id"],
                                                 make_nurse_headers("nurse-2")))
        wo = validate_success(api.create_work_order(
            create_work_order_payload(patient["id"], asmt["id"]),
            make_nurse_headers("nurse-1")), 201)
        # Settle the work order via cancellation (CANCELLED is terminal and
        # satisfies the resubmit gate).
        validate_success(api.cancel_work_order(wo["id"],
                                               make_admin_headers("admin-1")))
        resubmitted = validate_success(api.resubmit_assessment(
            asmt["id"],
            {"water_chloramine_ppm": 0.05, "electrical_dedicated_circuit": True,
             "electrical_voltage_verified": True, "storage_area_sqft": 100},
            make_nurse_headers("nurse-1")))
        assert resubmitted["status"] == "SUBMITTED"
        # The resubmitting nurse is the fresh assessor and cannot self-accept.
        resp = api.accept_assessment(asmt["id"], make_nurse_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_ASSESSOR_SELF_ACCEPT)
        accepted = validate_success(api.accept_assessment(
            asmt["id"], make_nurse_headers("nurse-2")))
        assert accepted["status"] == "ACCEPTED"
        assert accepted["storage_cap_units"] == 400, (
            "min(400, floor(100 * 4)) = 400")


class TestSupplyOrderParallelAxes:
    """order_status and fulfillment_status evolve independently on one row."""

    def test_fulfillment_walks_while_order_status_holds(self, api):
        """PRD §3.5: "The order row thus carries two independent axes on one
        record: `order_status` (the lifecycle: `DRAFT`, `SUBMITTED`,
        `CHANGES_REQUESTED`, `APPROVED`, `CLOSED`, `SUPERSEDED`, `CANCELLED`)
        and `fulfillment_status` (delivery progress: `UNFULFILLED`,
        `PARTIALLY_DELIVERED`, `DELIVERED`). Fulfillment transitions never
        change `order_status`, and lifecycle transitions never change
        `fulfillment_status`; both are readable on the same entity."

        Design: Difficulty/non_linear_state_machine/supply_order_parallel_order_and_fulfillment_axes
        """
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        order = create_approved_order(pat, "2026-05",
                                      [{"sku": "DIALYSATE_2L", "quantity": 20}])
        appt1 = schedule_appointment(order["id"], "2026-05-04T08:00:00Z",
                                     "2026-05-04T12:00:00Z")
        complete_appointment(appt1["id"], 10)
        mid = get_success_data(api.get_supply_order(order["id"],
                                                    make_admin_headers("admin-1")))
        assert mid["order_status"] == "APPROVED"
        assert mid["fulfillment_status"] == "PARTIALLY_DELIVERED"
        appt2 = schedule_appointment(order["id"], "2026-05-18T08:00:00Z",
                                     "2026-05-18T12:00:00Z")
        complete_appointment(appt2["id"], 10)
        after = get_success_data(api.get_supply_order(order["id"],
                                                      make_admin_headers("admin-1")))
        assert after["fulfillment_status"] == "DELIVERED"
        assert after["order_status"] == "APPROVED", (
            "fulfillment transitions never change order_status")
        assert after["delivered_units_total"] == 20

    def test_close_moves_lifecycle_axis_only(self, api):
        """PRD §3.5: "Closing is the month-end reconciliation, performed by a
        `SupplyCoordinator`. The order must be `APPROVED`
        (`ERR_ORDER_INVALID_STATE`), the first day of the month after
        `order_month` must have been reached on the logical clock
        (`ERR_MONTH_NOT_ENDED`), and no `SCHEDULED` delivery appointment may
        remain on the order (`ERR_OPEN_APPOINTMENTS_EXIST`)."
        PRD §3.5: "Fulfillment transitions never change `order_status`, and
        lifecycle transitions never change `fulfillment_status`; both are
        readable on the same entity."

        Design: Difficulty/non_linear_state_machine/supply_order_parallel_order_and_fulfillment_axes
        """
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        order = create_approved_order(pat, "2026-05",
                                      [{"sku": "DIALYSATE_2L", "quantity": 20}])
        appt = schedule_appointment(order["id"], "2026-05-04T08:00:00Z",
                                    "2026-05-04T12:00:00Z")
        complete_appointment(appt["id"], 20)
        set_clock("2026-06-01T00:00:00Z")
        closed = validate_success(api.close_supply_order(
            order["id"], make_coordinator_headers("coord-1")))
        assert closed["order_status"] == "CLOSED"
        assert closed["fulfillment_status"] == "DELIVERED", (
            "close does not rewrite the fulfillment axis")
        assert closed["delivered_units_total"] == 20
        assert_supply_order(closed)
