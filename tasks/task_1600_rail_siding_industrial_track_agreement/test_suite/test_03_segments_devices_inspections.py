"""TrackSegments, DerailDevices, and the SafetyInspection cycle with its FAIL
cascade into segment suspension (PRD §2.4, §2.8, §3.4, §3.5, §3.6).
"""
from test_helpers import (
    ENGINEER,
    INSPECTOR,
    SHIPPER,
    ApiErrorId,
    assert_derail_device,
    assert_liability_claim,
    assert_service_order,
    assert_storage_placement,
    assert_track_segment,
    create_segment_payload,
    create_service_order_payload,
    create_storage_placement_payload,
    get_device,
    get_inspection,
    get_segment,
    make_active_agreement,
    make_device,
    make_inspection,
    make_installed_device,
    make_liability_claim,
    make_project,
    make_segment,
    make_service_order,
    make_storage_placement,
    record_inspection_result,
    set_clock,
    setup_agreement_with_segment,
    setup_suspended_segment,
    validate_error,
    validate_success,
)


class TestSegmentCreation:
    def test_segment_create_ignores_computed_field_input(self, api):
        """PRD §3.4: "Segments are born `IN_SERVICE` with `stored_car_count` 0,
        `accrued_storage_cents` 0, and `safety_suspended` false."

        Design: Corner/entities/segment_create_computed_field_input_ignored
        """
        agreement = make_active_agreement()
        payload = create_segment_payload(agreement["id"])
        payload["stored_car_count"] = 99
        payload["safety_suspended"] = True
        res = api.create_segment(payload, ENGINEER)
        segment = validate_success(res, 201)
        assert_track_segment(segment)
        assert segment["stored_car_count"] == 0, (
            "client-supplied 99 must be ignored; the count derives from placements"
        )
        assert segment["safety_suspended"] is False
        assert segment["accrued_storage_cents"] == 0
        assert segment["status"] == "IN_SERVICE"


class TestInitialStates:
    def test_child_entities_born_in_initial_states(self, api):
        """PRD §3.3: "A new project starts in `DRAFT` with `spec_revision_no` 0
        and `amount_paid_cents` 0"
        PRD §3.6: "A successful placement starts `STORED`, and the segment's
        `stored_car_count` increments by 1."
        PRD §3.7: "The claim is born `FILED`."
        PRD §3.4: "the device starts `PROPOSED`"
        PRD §3.5: "The order is born `REQUESTED`."

        Design: Corner/state_machines/initial_states_on_creation
        """
        ctx = setup_agreement_with_segment()
        agr_id = ctx["agreement"]["id"]
        seg_id = ctx["segment"]["id"]
        project = make_project(agr_id)
        assert project["status"] == "DRAFT"
        placement = make_storage_placement(seg_id, car_mark="STGX9301")
        assert placement["status"] == "STORED"
        claim = make_liability_claim(agr_id)
        assert claim["status"] == "FILED"
        device = make_device(seg_id)
        assert device["status"] == "PROPOSED"
        order = make_service_order(agr_id, seg_id)
        assert order["status"] == "REQUESTED"
        assert_derail_device(device)
        assert_service_order(order)
        assert_storage_placement(placement)
        assert_liability_claim(claim)


class TestInspectionLifecycle:
    def test_record_result_twice_rejected(self, api):
        """PRD §3.4: "Recording a result requires the inspection to be in
        `SCHEDULED` or `OVERDUE` (otherwise `ERR_INSPECTION_INVALID_STATE`)"

        Design: Corner/state_machines/record_result_twice_returns_invalid_state
        """
        ctx = setup_agreement_with_segment()
        inspection = make_inspection(
            ctx["agreement"]["id"], ctx["segment"]["id"]
        )
        done = record_inspection_result(inspection["id"], "PASS", "2026-08-01")
        assert done["status"] == "COMPLETED_PASS"
        res = api.record_result(
            inspection["id"],
            {"result": "FAIL", "completed_date": "2026-08-02"},
            INSPECTOR,
        )
        validate_error(res, ApiErrorId.ERR_INSPECTION_INVALID_STATE, 409)
        assert get_inspection(inspection["id"])["status"] == "COMPLETED_PASS"

    def test_overdue_sweep_and_late_completion(self, api):
        """PRD §2.4: "The inspection overdue sweep moves an inspection in
        `SCHEDULED` to `OVERDUE` whenever the current logical date is later
        than the inspection's `due_date`"
        PRD §3.4: "an overdue inspection remains completable"

        Design: Corner/state_machines/inspection_overdue_sweep_and_late_completion
        """
        ctx = setup_agreement_with_segment()
        inspection = make_inspection(
            ctx["agreement"]["id"], ctx["segment"]["id"], scheduled_date="2026-08-01"
        )
        # On the due date itself the clock is not later than due_date.
        on_due = get_inspection(inspection["id"])
        assert on_due["status"] == "SCHEDULED"
        set_clock("2026-08-02T00:00:00Z")
        overdue = get_inspection(inspection["id"])
        assert overdue["status"] == "OVERDUE"
        done = record_inspection_result(inspection["id"], "PASS", "2026-08-02")
        assert done["status"] == "COMPLETED_PASS"

    def test_cited_device_on_wrong_segment_rejected(self, api):
        """PRD §3.4: "Every cited identifier must resolve to a derail device
        whose `segment_id` equals the inspection's own segment; any mismatch is
        rejected with `ERR_CROSS_REFERENCE_MISMATCH`."

        Design: Corner/validations/cited_device_wrong_segment_returns_mismatch
        """
        agreement = make_active_agreement()
        seg_a = make_segment(agreement["id"], segment_name="Siding A")
        seg_b = make_segment(
            agreement["id"],
            segment_name="Siding B",
            length_feet=800,
            storage_capacity_cars=2,
        )
        device_b = make_installed_device(seg_b["id"])
        inspection = make_inspection(agreement["id"], seg_a["id"])
        res = api.record_result(
            inspection["id"],
            {
                "result": "FAIL",
                "completed_date": "2026-08-01",
                "cited_device_ids": [device_b["id"]],
            },
            INSPECTOR,
        )
        validate_error(res, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH, 422)
        assert get_inspection(inspection["id"])["status"] == "SCHEDULED"
        assert get_device(device_b["id"])["status"] == "INSTALLED", (
            "the rejected record-result must leave device state untouched"
        )


class TestFailCascade:
    def test_fail_result_cascades_to_device_and_segment(self, api):
        """PRD §3.4: "A `FAIL` does the mirror image: every cited device
        currently `INSTALLED` becomes `NON_COMPLIANT`, and if any device on the
        segment is now non-compliant the segment's `safety_suspended` sets to
        true — which, per §3.5 and §3.6, blocks new service orders and storage
        placements on that segment with `ERR_SEGMENT_SAFETY_SUSPENDED`."

        Design: Difficulty/transitive_cascade/inspection_fail_cascade_suspends_segment
        """
        ctx = setup_agreement_with_segment()
        device = make_installed_device(ctx["segment"]["id"])
        inspection = make_inspection(ctx["agreement"]["id"], ctx["segment"]["id"])
        failed = record_inspection_result(
            inspection["id"], "FAIL", "2026-08-02", cited_device_ids=[device["id"]]
        )
        assert failed["status"] == "COMPLETED_FAIL"
        assert get_device(device["id"])["status"] == "NON_COMPLIANT"
        segment = get_segment(ctx["segment"]["id"])
        assert segment["safety_suspended"] is True
        # The suspension gates service-order creation (2026-08-03 is a Monday,
        # inside the agreement's service days, so only the gate blocks it).
        res = api.create_service_order(
            create_service_order_payload(
                ctx["agreement"]["id"],
                ctx["segment"]["id"],
                service_date="2026-08-03",
            ),
            SHIPPER,
        )
        validate_error(res, ApiErrorId.ERR_SEGMENT_SAFETY_SUSPENDED, 409)

    def test_record_result_auto_schedules_next_inspection(self, api):
        """PRD §3.4: "Either way, the cycle continues automatically: the system
        creates the next inspection for the same agreement and segment,
        scheduled for `completed_date` plus the agreement's
        `inspection_cadence_days` days, with its `due_date` equal to that
        scheduled date and status `SCHEDULED`."

        Design: Difficulty/transitive_cascade/inspection_fail_cascade_suspends_segment
        """
        ctx = setup_agreement_with_segment()
        device = make_installed_device(ctx["segment"]["id"])
        inspection = make_inspection(ctx["agreement"]["id"], ctx["segment"]["id"])
        record_inspection_result(
            inspection["id"], "FAIL", "2026-08-02", cited_device_ids=[device["id"]]
        )
        res = api.list_inspections(
            INSPECTOR, params={"segment_id": ctx["segment"]["id"]}
        )
        body = res.json()
        scheduled = [
            row for row in body["data"] if row["status"] == "SCHEDULED"
        ]
        assert len(scheduled) == 1, "exactly one follow-up inspection is created"
        # 2026-08-02 + 90 days = 2026-10-31.
        assert scheduled[0]["scheduled_date"] == "2026-10-31"
        assert scheduled[0]["due_date"] == "2026-10-31"
        assert scheduled[0]["agreement_id"] == ctx["agreement"]["id"]
        assert scheduled[0]["segment_id"] == ctx["segment"]["id"]


class TestSuspensionGate:
    def test_service_order_blocked_while_segment_suspended(self, api):
        """PRD §3.5: "The segment must be `IN_SERVICE` (else
        `ERR_SEGMENT_OUT_OF_SERVICE`) and not safety-suspended (else
        `ERR_SEGMENT_SAFETY_SUSPENDED`) — in that order, per §2.10."
        PRD §3.4: "A `FAIL` does the mirror image: every cited device currently
        `INSTALLED` becomes `NON_COMPLIANT`, and if any device on the segment
        is now non-compliant the segment's `safety_suspended` sets to true —
        which, per §3.5 and §3.6, blocks new service orders and storage
        placements on that segment with `ERR_SEGMENT_SAFETY_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/service_order_gated_by_segment_suspension
        """
        ctx = setup_suspended_segment()
        res = api.create_service_order(
            create_service_order_payload(
                ctx["agreement"]["id"],
                ctx["segment"]["id"],
                service_date="2026-08-03",
                start_hour=8,
                end_hour=10,
            ),
            SHIPPER,
        )
        validate_error(res, ApiErrorId.ERR_SEGMENT_SAFETY_SUSPENDED, 409)

    def test_service_order_allowed_after_compliance_restored(self, api):
        """PRD §3.4: "A `PASS` restores compliance: every cited device currently
        `NON_COMPLIANT` returns to `INSTALLED`, and if no device on that
        segment remains `NON_COMPLIANT`, the segment's `safety_suspended`
        clears to false."
        PRD §3.5: "The segment must be `IN_SERVICE` (else
        `ERR_SEGMENT_OUT_OF_SERVICE`) and not safety-suspended (else
        `ERR_SEGMENT_SAFETY_SUSPENDED`) — in that order, per §2.10."

        Design: Difficulty/cross_entity_state_dependency/service_order_gated_by_segment_suspension
        """
        ctx = setup_suspended_segment()
        followup = make_inspection(
            ctx["agreement"]["id"], ctx["segment"]["id"], scheduled_date="2026-08-04"
        )
        record_inspection_result(
            followup["id"], "PASS", "2026-08-04",
            cited_device_ids=[ctx["device"]["id"]],
        )
        assert get_device(ctx["device"]["id"])["status"] == "INSTALLED"
        assert get_segment(ctx["segment"]["id"])["safety_suspended"] is False
        res = api.create_service_order(
            create_service_order_payload(
                ctx["agreement"]["id"],
                ctx["segment"]["id"],
                service_date="2026-08-05",
                start_hour=8,
                end_hour=10,
            ),
            SHIPPER,
        )
        order = validate_success(res, 201)
        assert order["status"] == "REQUESTED"


class TestOutOfServiceGate:
    def test_out_of_service_segment_blocks_storage(self, api):
        """PRD §3.6: "under an `ACTIVE` agreement whose segment is `IN_SERVICE`
        (else `ERR_SEGMENT_OUT_OF_SERVICE`) and not safety-suspended (else
        `ERR_SEGMENT_SAFETY_SUSPENDED`)"
        PRD §2.8: "Conversely, operations that look similar but are defined as
        non-cascading — taking a single segment out of service for maintenance
        possession, for example — leave orders and placements untouched, and
        this distinction is contractual."

        Design: Corner/validations/out_of_service_segment_blocks_storage
        """
        ctx = setup_agreement_with_segment()
        taken = validate_success(
            api.take_out_of_service(ctx["segment"]["id"], ENGINEER)
        )
        assert taken["status"] == "OUT_OF_SERVICE"
        res = api.create_storage_placement(
            create_storage_placement_payload(
                ctx["segment"]["id"], car_mark="STGX9701", placed_date="2026-08-02"
            ),
            SHIPPER,
        )
        validate_error(res, ApiErrorId.ERR_SEGMENT_OUT_OF_SERVICE, 409)
