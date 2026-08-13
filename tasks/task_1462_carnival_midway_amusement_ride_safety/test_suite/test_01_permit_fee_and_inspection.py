"""Permit fee calculation variants, inspector assignment, and the permit
decision gate (PRD section 3.2).

Covers design instances:
  Difficulty/dual_variant_calc/permit_fee_estimated_vs_final_diverge_on_inventory_change
  Difficulty/combinatorial_formula/permit_fee_tiers_surcharge_and_cap_eval_order
  Difficulty/cross_entity_state_dependency/permit_approval_gated_by_completed_fair_wide_inspection
  Difficulty/resource_temporal_overlap/inspector_buffer_gap_and_daily_cap_on_assignment
  Corner/calculations/inspector_selector_tie_break_uses_earliest_created
  Corner/validations/permit_sod_conducting_inspector_cannot_approve
  Corner/errors/permit_request_without_verified_rides_rejected
  Corner/errors/appointment_window_and_not_due_errors
  Corner/state_machines/permit_denial_loops_fair_back_to_setup_and_repermit
  Corner/state_machines/appointment_cancel_after_completion_rejected
"""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_admin_headers,
    make_inspector_headers,
    make_manager_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


class TestPermitFeeDualVariant:
    def test_estimated_fee_frozen_at_request_time(self, api):
        """PRD section 3.2: "The *estimated* variant is evaluated at request time
        over the qualifying ride set as it then stands, with the failure count
        fixed at zero; it is frozen into `estimated_fee_cents` and never
        recomputed."

        One THRILL ride qualifies at request time: 25000 + 14000 = 39000.

        Design: Difficulty/dual_variant_calc/permit_fee_estimated_vs_final_diverge_on_inventory_change
        """
        ctx = fx.setup_fair_with_staff("D1")
        sup = ctx["sup"]
        fx.create_inspector("LIC-D1-1")
        insp2 = fx.create_inspector("LIC-D1-2")
        crew = fx.create_staff_via_manager(sup, "Crew D1", ["CREW"])
        ride1 = fx.create_ride(sup, name="Coaster", ride_class="THRILL",
                               cycle_inspection_interval=3, serial_number="SN-D1-1")
        fx.book_setup_shift(sup, crew)
        ride1 = fx.verify_ride(crew, ride1["id"])
        permit = fx.request_permit(sup)
        assert permit["estimated_fee_cents"] == 39000, (
            f"estimated fee must be 39000, got {permit['estimated_fee_cents']}")
        assert permit["status"] == "PENDING"

        # A second ride registered and verified AFTER the request cannot change
        # the frozen estimate, but joins the qualifying set for the final fee.
        ride2 = fx.create_ride(sup, name="Swings", ride_class="FAMILY",
                               cycle_inspection_interval=5, serial_number="SN-D1-2",
                               min_rider_height_in=40, max_rider_height_in=84,
                               wind_limit_mph=25, capacity_per_cycle=8)
        fx.verify_ride(crew, ride2["id"])
        appt = fx.schedule_fair_wide(sup)
        fx.set_clock(fx.INSPECTION_CLOCK_ISO)
        fx.complete_appointment(appt, outcome="PASS")
        approved = fx.approve_permit(insp2, permit["id"], sup["fair_id"], sup)
        reloaded = fx.get_permit(sup, permit["id"])
        assert reloaded["estimated_fee_cents"] == 39000
        assert approved["estimated_fee_cents"] == 39000

    def test_final_fee_reevaluated_at_approval_over_current_rides(self, api):
        """PRD section 3.2: "The *final* variant is re-evaluated at approval time
        over the qualifying ride set as it then stands, with the actual failure
        count; it is stored in `final_fee_cents` together with
        `billable_ride_count`... and `reinspection_failure_count`."

        With the FAMILY ride verified before approval, the final variant sees
        two qualifying rides: 25000 + 14000 + 9000 = 48000.

        Design: Difficulty/dual_variant_calc/permit_fee_estimated_vs_final_diverge_on_inventory_change
        """
        ctx = fx.setup_fair_with_staff("D1b")
        sup = ctx["sup"]
        fx.create_inspector("LIC-D1b-1")
        insp2 = fx.create_inspector("LIC-D1b-2")
        crew = fx.create_staff_via_manager(sup, "Crew D1b", ["CREW"])
        ride1 = fx.create_ride(sup, name="Coaster", ride_class="THRILL",
                               cycle_inspection_interval=3, serial_number="SN-D1b-1")
        fx.book_setup_shift(sup, crew)
        fx.verify_ride(crew, ride1["id"])
        permit = fx.request_permit(sup)
        ride2 = fx.create_ride(sup, name="Swings", ride_class="FAMILY",
                               cycle_inspection_interval=5, serial_number="SN-D1b-2",
                               min_rider_height_in=40, max_rider_height_in=84,
                               wind_limit_mph=25, capacity_per_cycle=8)
        fx.verify_ride(crew, ride2["id"])
        appt = fx.schedule_fair_wide(sup)
        fx.set_clock(fx.INSPECTION_CLOCK_ISO)
        fx.complete_appointment(appt, outcome="PASS")
        approved = fx.approve_permit(insp2, permit["id"], sup["fair_id"], sup)
        assert approved["final_fee_cents"] == 48000
        assert approved["billable_ride_count"] == 2
        assert approved["reinspection_failure_count"] == 0
        assert approved["status"] == "APPROVED"
        fair = fx.get_success_data(api.get_fair(sup["fair_id"], make_manager_headers(sup["id"])))
        assert fair["status"] == "PERMITTED"
        for rid in (ride1["id"], ride2["id"]):
            ride = fx.get_ride(sup, rid)
            assert ride["license_status"] == "LICENSED", (
                f"ride {rid} must be LICENSED after approval, got {ride['license_status']}")


class TestPermitFeeCombinatorial:
    def test_class_rates_and_surcharge_sum_before_cap(self, api):
        """PRD section 3.2: "The fee starts from a 25,000-cent base, adds a
        per-ride class rate for each qualifying ride... and then adds a
        7,500-cent reinspection surcharge for each of the fair's `FAIR_WIDE`
        appointments that ended `COMPLETED_FAIL`."

        KIDDIE + EXTREME with one FAIR_WIDE failure: 25000 + 5000 + 20000 + 7500
        = 57500 (under the 200000 cap).

        Design: Difficulty/combinatorial_formula/permit_fee_tiers_surcharge_and_cap_eval_order
        """
        ctx = fx.setup_fair_with_staff("C1")
        sup = ctx["sup"]
        insp1 = fx.create_inspector("LIC-C1-1")
        fx.create_inspector("LIC-C1-2")
        crew = fx.create_staff_via_manager(sup, "Crew C1", ["CREW"])
        ride1 = fx.create_ride(sup, name="Kiddie Train", ride_class="KIDDIE",
                               capacity_per_cycle=6, min_rider_height_in=30,
                               max_rider_height_in=60, wind_limit_mph=35,
                               cycle_inspection_interval=10, serial_number="SN-C1-1")
        ride2 = fx.create_ride(sup, name="Drop Tower", ride_class="EXTREME",
                               capacity_per_cycle=4, min_rider_height_in=52,
                               max_rider_height_in=84, wind_limit_mph=20,
                               cycle_inspection_interval=2, serial_number="SN-C1-2")
        fx.book_setup_shift(sup, crew, end_hour=12)
        fx.verify_ride(crew, ride1["id"])
        fx.verify_ride(crew, ride2["id"])
        permit = fx.request_permit(sup)
        assert permit["estimated_fee_cents"] == 50000

        appt1 = fx.schedule_fair_wide(sup, start_hour=9, duration_hours=2)
        fx.set_clock("2026-08-02T12:00:00Z")
        fx.complete_appointment(appt1, outcome="FAIL", findings="restraint sensor fault")
        # The second appointment must dodge the travel buffer (11 + 2 <= 13).
        appt2 = fx.schedule_fair_wide(sup, start_hour=13, duration_hours=1)
        fx.complete_appointment(appt2, outcome="PASS")
        # The approver must not be the inspector of the latest COMPLETED_PASS.
        approved = fx.approve_permit(insp1, permit["id"], sup["fair_id"], sup)
        assert approved["reinspection_failure_count"] == 1
        assert approved["final_fee_cents"] == 57500, (
            f"final fee must be min(25000+5000+20000+7500, 200000) = 57500, "
            f"got {approved['final_fee_cents']}")

    def test_load_based_selector_skips_loaded_inspector(self, api):
        """PRD section 3.2: "Eligible inspectors are ranked by their same-date
        appointment count in ascending order, ties broken by inspector
        seniority — the earlier `created_at` first — and the first inspector in
        that ranking receives the assignment."

        After inspector 1 takes the 09:00 appointment, the 13:00 appointment
        goes to inspector 2 (load 0 outranks load 1).

        Design: Difficulty/combinatorial_formula/permit_fee_tiers_surcharge_and_cap_eval_order
        """
        ctx = fx.setup_fair_with_staff("C1b")
        sup = ctx["sup"]
        insp1 = fx.create_inspector("LIC-C1b-1")
        insp2 = fx.create_inspector("LIC-C1b-2")
        crew = fx.create_staff_via_manager(sup, "Crew C1b", ["CREW"])
        ride = fx.create_ride(sup, name="Kiddie Train", ride_class="KIDDIE",
                              capacity_per_cycle=6, min_rider_height_in=30,
                              max_rider_height_in=60, wind_limit_mph=35,
                              cycle_inspection_interval=10, serial_number="SN-C1b-1")
        fx.book_setup_shift(sup, crew)
        fx.verify_ride(crew, ride["id"])
        fx.request_permit(sup)
        appt1 = fx.schedule_fair_wide(sup, start_hour=9, duration_hours=2)
        assert appt1["inspector_id"] == insp1["id"]
        appt2 = fx.schedule_fair_wide(sup, start_hour=13, duration_hours=1)
        assert appt2["inspector_id"] == insp2["id"], (
            f"load-based selector must bypass the already-loaded inspector 1; "
            f"got {appt2['inspector_id']}")


class TestPermitApprovalGate:
    def test_approve_blocked_until_fair_wide_passes(self, api):
        """PRD section 3.2: "Approval requires... evidence that the fair passed
        inspection since the permit was opened, namely a `FAIR_WIDE` appointment
        in `COMPLETED_PASS` whose `completed_at` is at or after the permit's
        `created_at` (`ERR_INSPECTION_REQUIRED`)".

        Design: Difficulty/cross_entity_state_dependency/permit_approval_gated_by_completed_fair_wide_inspection
        """
        ctx = fx.setup_permit_requested("X1")
        sup = ctx["sup"]
        fx.create_inspector("LIC-X1-1b") if False else None
        inspectors = ctx["inspectors"]
        approver = inspectors[1]
        appt = fx.schedule_fair_wide(sup)
        fx.set_clock("2026-08-02T09:30:00Z")
        fair = fx.get_success_data(api.get_fair(sup["fair_id"], make_manager_headers(sup["id"])))
        resp = api.approve_permit(ctx["permit"]["id"],
                                  {"expected_fair_version": fair["version"]},
                                  make_inspector_headers(approver["id"]))
        validate_error(resp, ApiErrorId.ERR_INSPECTION_REQUIRED, 422)
        permit = fx.get_permit(sup, ctx["permit"]["id"])
        assert permit["status"] == "PENDING"
        fair = fx.get_success_data(api.get_fair(sup["fair_id"], make_manager_headers(sup["id"])))
        assert fair["status"] == "PERMIT_REQUESTED"

    def test_approve_succeeds_after_pass_and_sets_decision_fields(self, api):
        """PRD section 3.2: "Approving computes the final fee fields, records
        the caller in `approved_by_inspector_id`, stamps `decided_at` from the
        logical clock, moves the permit to `APPROVED`, and cascades: the fair
        moves `PERMIT_REQUESTED` to `PERMITTED`".

        Design: Difficulty/cross_entity_state_dependency/permit_approval_gated_by_completed_fair_wide_inspection
        """
        ctx = fx.setup_permit_requested("X1b")
        sup = ctx["sup"]
        approver = ctx["inspectors"][1]
        appt = fx.schedule_fair_wide(sup)
        fx.set_clock(fx.INSPECTION_CLOCK_ISO)
        fx.complete_appointment(appt, outcome="PASS")
        approved = fx.approve_permit(approver, ctx["permit"]["id"], sup["fair_id"], sup)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_inspector_id"] == approver["id"]
        assert approved["decided_at"] is not None
        fair = fx.get_success_data(api.get_fair(sup["fair_id"], make_manager_headers(sup["id"])))
        assert fair["status"] == "PERMITTED"


class TestInspectorAssignment:
    def test_travel_buffer_gap_required(self, api):
        """PRD section 3.2: "The buffer is satisfied when the new appointment's
        end (its `start_hour` plus `duration_hours`) plus two hours is at or
        before the existing appointment's start hour, or when the existing
        appointment's `end_hour` plus two hours is at or before the new
        appointment's start hour; otherwise the two appointments conflict and
        the inspector is ineligible. An empty pool is rejected with
        `ERR_INSPECTOR_UNAVAILABLE`."

        With a single inspector holding 09:00-11:00, a 12:00 start conflicts
        (11+2=13 > 12) while a 13:00 start satisfies the buffer exactly.

        Design: Difficulty/resource_temporal_overlap/inspector_buffer_gap_and_daily_cap_on_assignment
        """
        ctx = fx.setup_fair_with_staff("R1")
        sup = ctx["sup"]
        insp = fx.create_inspector("LIC-R1-1", max_daily_inspections=3)
        crew = fx.create_staff_via_manager(sup, "Crew R1", ["CREW"])
        ride = fx.create_ride(sup)
        fx.book_setup_shift(sup, crew)
        fx.verify_ride(crew, ride["id"])
        fx.request_permit(sup)
        appt1 = fx.schedule_fair_wide(sup, start_hour=9, duration_hours=2)
        assert appt1["inspector_id"] == insp["id"]

        resp = api.create_appointment(
            {"fair_id": sup["fair_id"], "scope": "FAIR_WIDE",
             "scheduled_date": fx.INSPECTION_DAY, "start_hour": 12, "duration_hours": 1},
            make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_UNAVAILABLE, 422)
        appt2 = fx.schedule_fair_wide(sup, start_hour=13, duration_hours=1)
        assert appt2["inspector_id"] == insp["id"], (
            "13:00 start exactly satisfies the 11+2<=13 buffer")

    def test_daily_cap_empties_pool(self, api):
        """PRD section 3.2: "the number of their appointments on the same date
        in `SCHEDULED`, `COMPLETED_PASS`, or `COMPLETED_FAIL` status is below
        their `max_daily_inspections`... An empty pool is rejected with
        `ERR_INSPECTOR_UNAVAILABLE`."

        With max_daily_inspections 3 and three same-date appointments on the
        books, the fourth request finds an empty pool.

        Design: Difficulty/resource_temporal_overlap/inspector_buffer_gap_and_daily_cap_on_assignment
        """
        ctx = fx.setup_fair_with_staff("R1b")
        sup = ctx["sup"]
        insp = fx.create_inspector("LIC-R1b-1", max_daily_inspections=3)
        crew = fx.create_staff_via_manager(sup, "Crew R1b", ["CREW"])
        ride = fx.create_ride(sup)
        fx.book_setup_shift(sup, crew)
        fx.verify_ride(crew, ride["id"])
        fx.request_permit(sup)
        fx.schedule_fair_wide(sup, start_hour=9, duration_hours=2)
        fx.schedule_fair_wide(sup, start_hour=13, duration_hours=1)
        audit = fx.schedule_ride_audit(sup, ride["id"], scheduled_date=fx.INSPECTION_DAY,
                                       start_hour=16, duration_hours=1)
        assert audit["inspector_id"] == insp["id"]
        resp = api.create_appointment(
            {"fair_id": sup["fair_id"], "scope": "FAIR_WIDE",
             "scheduled_date": fx.INSPECTION_DAY, "start_hour": 19, "duration_hours": 1},
            make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_UNAVAILABLE, 422)


class TestInspectorTieBreak:
    def test_first_registered_wins_tie_then_load_governs(self, api):
        """PRD section 3.2: "Eligible inspectors are ranked by their same-date
        appointment count in ascending order, ties broken by inspector
        seniority — the earlier `created_at` first".

        Design: Corner/calculations/inspector_selector_tie_break_uses_earliest_created
        """
        ctx = fx.setup_fair_with_staff("CA1")
        sup = ctx["sup"]
        insp_a = fx.create_inspector("LIC-CA1-1", full_name="Insp Early")
        insp_b = fx.create_inspector("LIC-CA1-2", full_name="Insp Late")
        crew = fx.create_staff_via_manager(sup, "Crew CA1", ["CREW"])
        ride = fx.create_ride(sup)
        fx.book_setup_shift(sup, crew)
        fx.verify_ride(crew, ride["id"])
        fx.request_permit(sup)
        appt1 = fx.schedule_fair_wide(sup, start_hour=9, duration_hours=2)
        assert appt1["inspector_id"] == insp_a["id"], (
            f"tie at load 0 must break to the earlier-created inspector; got "
            f"{appt1['inspector_id']} expected {insp_a['id']}")
        appt2 = fx.schedule_fair_wide(sup, start_hour=14, duration_hours=1)
        assert appt2["inspector_id"] == insp_b["id"], (
            f"load 0 must outrank load 1; got {appt2['inspector_id']} "
            f"expected {insp_b['id']}")


class TestPermitSegregationOfDuties:
    def test_conducting_inspector_cannot_approve(self, api):
        """PRD section 3.2: "requires that the approving caller is not the
        inspector who conducted the latest such passed fair-wide inspection
        (`ERR_PERMIT_APPROVER_CONFLICT`)".

        Design: Corner/validations/permit_sod_conducting_inspector_cannot_approve
        """
        ctx = fx.setup_permit_requested("V5")
        sup = ctx["sup"]
        appt = fx.schedule_fair_wide(sup)
        fx.set_clock(fx.INSPECTION_CLOCK_ISO)
        fx.complete_appointment(appt, outcome="PASS")
        fair = fx.get_success_data(api.get_fair(sup["fair_id"], make_manager_headers(sup["id"])))
        resp = api.approve_permit(ctx["permit"]["id"],
                                  {"expected_fair_version": fair["version"]},
                                  make_inspector_headers(appt["inspector_id"]))
        validate_error(resp, ApiErrorId.ERR_PERMIT_APPROVER_CONFLICT, 422)
        permit = fx.get_permit(sup, ctx["permit"]["id"])
        assert permit["status"] == "PENDING"
        fair = fx.get_success_data(api.get_fair(sup["fair_id"], make_manager_headers(sup["id"])))
        assert fair["status"] == "PERMIT_REQUESTED"


class TestPermitRequestGate:
    def test_request_without_verified_rides_rejected(self, api):
        """PRD section 3.2: "Requesting with zero `SETUP_VERIFIED` rides is
        rejected with `ERR_NO_VERIFIED_RIDES`".

        Design: Corner/errors/permit_request_without_verified_rides_rejected
        """
        ctx = fx.setup_fair_with_staff("ER7")
        sup = ctx["sup"]
        fx.create_ride(sup)  # registered but never verified
        resp = api.request_permit(sup["fair_id"], {}, make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_VERIFIED_RIDES, 422)
        fair = fx.get_success_data(api.get_fair(sup["fair_id"], make_manager_headers(sup["id"])))
        assert fair["status"] == "SETUP"
        permits = fx.get_success_data(api.list_permits(make_manager_headers(sup["id"]),
                                                       params={"fair_id": sup["fair_id"]}))
        assert permits == [], "no Permit row may be created by a rejected request"


class TestAppointmentWindow:
    def test_schedule_beyond_teardown_rejected(self, api):
        """PRD section 3.2: "the `scheduled_date` must fall on or after the
        current date and on or before the fair's `teardown_end_date`
        (`ERR_APPOINTMENT_WINDOW_INVALID`)".

        Design: Corner/errors/appointment_window_and_not_due_errors
        """
        ctx = fx.setup_permit_requested("ER6")
        sup = ctx["sup"]
        resp = api.create_appointment(
            {"fair_id": sup["fair_id"], "scope": "FAIR_WIDE",
             "scheduled_date": "2026-08-09", "start_hour": 9, "duration_hours": 2},
            make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_WINDOW_INVALID, 422)

    def test_complete_before_scheduled_date_rejected(self, api):
        """PRD section 3.2: "completing before the `scheduled_date` has arrived
        is `ERR_APPOINTMENT_NOT_DUE`".

        Design: Corner/errors/appointment_window_and_not_due_errors
        """
        ctx = fx.setup_permit_requested("ER6b")
        sup = ctx["sup"]
        appt = fx.schedule_fair_wide(sup, scheduled_date="2026-08-04")
        fx.set_clock(fx.INSPECTION_CLOCK_ISO)
        resp = api.complete_appointment(appt["id"], {"outcome": "PASS"},
                                        make_inspector_headers(appt["inspector_id"]))
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_DUE, 422)
        appt_after = fx.get_success_data(api.get_appointment(
            appt["id"], make_manager_headers(sup["id"])))
        assert appt_after["status"] == "SCHEDULED"


class TestPermitDenialLoop:
    def test_denial_loops_fair_back_to_setup(self, api):
        """PRD section 3.2: "the permit lands in `DENIED`; and the fair loops
        back from `PERMIT_REQUESTED` to `SETUP` with its `version` advancing,
        leaving every ride's `setup_status` as it was and every license
        `PENDING` so the operator can remediate and request again."

        Design: Corner/state_machines/permit_denial_loops_fair_back_to_setup_and_repermit
        """
        ctx = fx.setup_permit_requested("SM6")
        sup = ctx["sup"]
        inspectors = ctx["inspectors"]
        appt = fx.schedule_fair_wide(sup)
        fx.set_clock(fx.INSPECTION_CLOCK_ISO)
        fx.complete_appointment(appt, outcome="FAIL", findings="cracked sweep bearing")
        denied = fx.deny_permit(inspectors[1], ctx["permit"]["id"],
                                reason="failed fair-wide inspection")
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "failed fair-wide inspection"
        fair = fx.get_success_data(api.get_fair(sup["fair_id"], make_manager_headers(sup["id"])))
        assert fair["status"] == "SETUP"

    def test_repermit_after_denial_creates_fresh_pending_permit(self, api):
        """PRD section 3.2: "so the operator can remediate and request again"
        and "The *estimated* variant... with the failure count fixed at zero;
        it is frozen into `estimated_fee_cents` and never recomputed."

        The re-requested permit is a NEW PENDING permit; its estimate ignores
        the earlier FAIR_WIDE failure (failures fixed at 0 for the estimate):
        one THRILL ride -> 25000 + 14000 = 39000.

        Design: Corner/state_machines/permit_denial_loops_fair_back_to_setup_and_repermit
        """
        ctx = fx.setup_permit_requested("SM6b")
        sup = ctx["sup"]
        inspectors = ctx["inspectors"]
        appt = fx.schedule_fair_wide(sup)
        fx.set_clock(fx.INSPECTION_CLOCK_ISO)
        fx.complete_appointment(appt, outcome="FAIL", findings="cracked sweep bearing")
        fx.deny_permit(inspectors[1], ctx["permit"]["id"])
        permit2 = fx.request_permit(sup)
        assert permit2["status"] == "PENDING"
        assert permit2["id"] != ctx["permit"]["id"]
        assert permit2["estimated_fee_cents"] == 39000, (
            f"second estimate must be recomputed with failures fixed at 0; got "
            f"{permit2['estimated_fee_cents']}")


class TestAppointmentTerminalState:
    def test_cancel_after_completion_rejected(self, api):
        """PRD section 3.2: "completing from any other status is
        `ERR_APPOINTMENT_INVALID_STATE`" and "A `FairManager` may also cancel a
        `SCHEDULED` appointment, moving it to `CANCELLED`."

        A COMPLETED_PASS appointment is no longer SCHEDULED, so cancel fails.

        Design: Corner/state_machines/appointment_cancel_after_completion_rejected
        """
        ctx = fx.setup_permit_requested("SM1")
        sup = ctx["sup"]
        appt = fx.schedule_fair_wide(sup)
        fx.set_clock(fx.INSPECTION_CLOCK_ISO)
        fx.complete_appointment(appt, outcome="PASS")
        resp = api.cancel_appointment(appt["id"], {}, make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_INVALID_STATE, 409)
        appt_after = fx.get_success_data(api.get_appointment(
            appt["id"], make_manager_headers(sup["id"])))
        assert appt_after["status"] == "COMPLETED_PASS"
