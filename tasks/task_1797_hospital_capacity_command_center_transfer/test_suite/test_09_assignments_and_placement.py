"""Bed assignments: creation validation ordering, segregation of duties,
completion cascade, and bed-status endpoint guards."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_bed,
    add_physician,
    create_accepted_request,
    create_admission,
    create_boarding_record_payload,
    create_facility,
    create_request_with_hold,
    create_transfer_request,
    get_success_data,
    make_bed_manager_headers,
    make_coordinator_headers,
    place_assignment,
    place_hold,
    place_holds_for_n_requests,
    set_clock,
    setup_accepted_request_scenario,
    setup_facility_with_physician,
    setup_hold_placed_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    walk_request_to_assigned,
)

ADMIN = TEST_USERS["sysadmin_headers"]
BED_MGR = TEST_USERS["bed_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestBedStatusEndpoint:
    def test_bed_status_endpoint_rejects_held_target(self, api):
        """PRD §3.1: "The statuses `HELD` and `OCCUPIED` are system-managed
        through the hold and admission lifecycles and are rejected as targets
        of this operation with `ERR_INVALID_REQUEST`".

        Design: Corner/state_machines/bed_status_endpoint_rejects_held_target
        """
        facility = create_facility(name="BedSt Fac")
        bed = add_bed(facility["id"], unit="C-1", label="B1", service="CARDIAC",
                      max_acuity="ACUITY_1_CRITICAL")
        resp = api.set_bed_status(bed["id"], {"to_status": "HELD"}, BED_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        after = validate_success(api.get_bed(bed["id"], COORD))
        assert after["status"] == "AVAILABLE"


class TestValidationPriority:
    def test_state_beats_isolation_on_hold_create(self, api):
        """PRD §2.8: "State-machine eligibility checks run after existence;
        optimistic-concurrency version comparisons run after state checks.
        Domain safety rules follow, and where several apply they run in their
        own pinned order (isolation compatibility, then acuity capability, then
        service matching; physician credentialing before physician on-call
        status)."
        PRD §3.4: "Once a request is `ACCEPTED`, a `TransferCenterCoordinator`
        places a bed hold for it; attempting placement from any other status is
        rejected with `ERR_TRANSFER_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_isolation_on_hold_create
        """
        set_clock()
        facility = create_facility(name="Prio Facility A")
        bed = add_bed(facility["id"], unit="C-1", label="B1", service="CARDIAC",
                      max_acuity="ACUITY_2_STEPDOWN", isolation_capability="NONE")
        # Request is INTAKE (state violation) AND the bed's isolation NONE is
        # below the request's CONTACT need (safety violation).
        request = create_transfer_request(
            facility["id"], patient_ref="PP1", isolation_need="CONTACT",
            service="CARDIAC")
        resp = api.create_bed_hold(
            request["id"], {"bed_id": bed["id"]},
            make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_TRANSFER_INVALID_STATE)

    def test_state_violation_alone_on_hold_create(self, api):
        """PRD §3.4: "Once a request is `ACCEPTED`, a `TransferCenterCoordinator`
        places a bed hold for it; attempting placement from any other status is
        rejected with `ERR_TRANSFER_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_isolation_on_hold_create
        """
        set_clock()
        facility = create_facility(name="Prio Facility A2")
        # The bed fully matches the request: only the state violation exists.
        bed = add_bed(facility["id"], unit="C-1", label="B1", service="CARDIAC",
                      max_acuity="ACUITY_1_CRITICAL",
                      isolation_capability="AIRBORNE")
        request = create_transfer_request(
            facility["id"], patient_ref="PP2", isolation_need="CONTACT",
            service="CARDIAC")
        resp = api.create_bed_hold(
            request["id"], {"bed_id": bed["id"]},
            make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_TRANSFER_INVALID_STATE)

    def test_isolation_beats_hold_quota_on_hold_create(self, api):
        """PRD §2.8: "Domain safety rules follow, and where several apply they
        run in their own pinned order (isolation compatibility, then acuity
        capability, then service matching; physician credentialing before
        physician on-call status). Segregation-of-duties checks come after the
        safety rules, then temporal checks (deadlines and minimum durations),
        then window-conflict checks, and finally quota and uniqueness
        constraints."
        PRD §3.4: "isolation compatibility is checked first
        (`ERR_ISOLATION_INCOMPATIBLE`)".

        Design: Difficulty/priority_pair_validation_conflict/isolation_beats_hold_quota_on_hold_create
        """
        set_clock()
        bundle = setup_facility_with_physician(name="Prio Facility B")
        facility, physician = bundle["facility"], bundle["physician"]
        held_bed_ids = []
        for i in range(1, 7):
            unit = "C-1" if i <= 3 else "C-2"
            bed = add_bed(facility["id"], unit=unit, label=f"H{i}",
                          service="CARDIAC", max_acuity="ACUITY_1_CRITICAL",
                          isolation_capability="AIRBORNE")
            held_bed_ids.append(bed["id"])
        b7 = add_bed(facility["id"], unit="C-3", label="B7", service="CARDIAC",
                     max_acuity="ACUITY_1_CRITICAL", isolation_capability="NONE")
        place_holds_for_n_requests(facility["id"], physician["id"],
                                   held_bed_ids)
        # Quota is now full (6 ACTIVE holds). The 7th request targets a bed
        # whose isolation NONE is below its AIRBORNE need.
        tr7 = create_accepted_request(
            facility["id"], physician["id"], patient_ref="PQ7",
            acuity="ACUITY_1_CRITICAL", isolation_need="AIRBORNE",
            service="CARDIAC", priority="EMERGENT")
        resp = api.create_bed_hold(
            tr7["id"], {"bed_id": b7["id"]},
            make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_ISOLATION_INCOMPATIBLE)

    def test_isolation_violation_alone_on_explicit_hold(self, api):
        """PRD §3.4: "its `isolation_capability` rank must be at least the
        request's `isolation_need` rank, using the ranks zero through three
        from `NONE` up to `AIRBORNE`".
        PRD §3.4: "In explicit mode, failures map to errors in a pinned order —
        after the state check that the bed is available, staffed, and non-ED
        (`ERR_BED_NOT_AVAILABLE`), isolation compatibility is checked first
        (`ERR_ISOLATION_INCOMPATIBLE`)".

        Design: Difficulty/priority_pair_validation_conflict/isolation_beats_hold_quota_on_hold_create
        """
        set_clock()
        bundle = setup_facility_with_physician(name="Prio Facility B2")
        facility, physician = bundle["facility"], bundle["physician"]
        # A single isolation-incompatible bed, quota far from full.
        bed = add_bed(facility["id"], unit="C-3", label="B7", service="CARDIAC",
                      max_acuity="ACUITY_1_CRITICAL", isolation_capability="NONE")
        request = create_accepted_request(
            facility["id"], physician["id"], patient_ref="PQ8",
            acuity="ACUITY_1_CRITICAL", isolation_need="AIRBORNE",
            service="CARDIAC", priority="EMERGENT")
        resp = api.create_bed_hold(
            request["id"], {"bed_id": bed["id"]},
            make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_ISOLATION_INCOMPATIBLE)


class TestAssignmentSegregation:
    def test_sod_assignment_complete_same_actor_denied(self, api):
        """PRD §2.10: "A bed assignment may only be completed by a `BedManager`
        whose `X-User-ID` differs from the assignment's `created_by_user_id`; a
        violation is rejected with
        `ERR_SOD_ASSIGNMENT_CREATE_COMPLETE_SAME_ACTOR` (HTTP 403)."
        PRD §3.5: "Completion stamps `completed_at`, moves the assignment to
        `COMPLETED`, moves the transfer request from `ASSIGNED` to its terminal
        `COMPLETED` status with a version increment, moves the bed from `HELD`
        to `OCCUPIED`, and creates a new admission in `ADMITTED` status on that
        bed carrying the transfer request's `acuity`, `isolation_need`, and
        `service`."

        Design: Corner/validations/sod_assignment_complete_same_actor_denied
        """
        set_clock()
        bundle = setup_facility_with_physician(name="SOD2 Fac")
        facility, physician = bundle["facility"], bundle["physician"]
        bed = add_bed(facility["id"], unit="C-1", label="B1", service="CARDIAC",
                      max_acuity="ACUITY_1_CRITICAL",
                      isolation_capability="AIRBORNE")
        request, hold = create_request_with_hold(
            facility["id"], physician["id"], bed["id"], patient_ref="PS2A",
            acuity="ACUITY_1_CRITICAL", priority="EMERGENT")
        assignment = place_assignment(request, hold, coordinator_id="coord_1")
        assert assignment["created_by_user_id"] == "coord_1"
        # Same operator id as the creator — even wearing a BedManager hat.
        resp = api.complete_bed_assignment(
            assignment["id"], make_bed_manager_headers("coord_1"))
        validate_error(
            resp, ApiErrorId.ERR_SOD_ASSIGNMENT_CREATE_COMPLETE_SAME_ACTOR)
        completed = validate_success(api.complete_bed_assignment(
            assignment["id"], make_bed_manager_headers("bm_1")), 200)
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"] is not None
        request_after = validate_success(
            api.get_transfer_request(request["id"], COORD))
        assert request_after["status"] == "COMPLETED"
        bed_after = validate_success(api.get_bed(bed["id"], COORD))
        assert bed_after["status"] == "OCCUPIED"


class TestFkReverseReads:
    def test_fk_reverse_reachability_reads(self, api):
        """PRD §4 lists the reverse reads: "List holds placed on a bed", "List
        holds of a transfer request", "List boarding records of an admission",
        and "List transfer requests accepted by a physician".

        Design: Corner/endpoints/fk_reverse_reachability_reads
        """
        set_clock()
        bundle = setup_facility_with_physician(
            name="FK Fac", services=("CARDIAC", "MEDICAL"))
        facility, physician = bundle["facility"], bundle["physician"]
        bed = add_bed(facility["id"], unit="C-1", label="B1", service="CARDIAC",
                      max_acuity="ACUITY_1_CRITICAL",
                      isolation_capability="AIRBORNE")
        ed_bed = add_bed(facility["id"], unit="ED-1", label="E1",
                         service="MEDICAL")
        request, hold = create_request_with_hold(
            facility["id"], physician["id"], bed["id"], patient_ref="PFK",
            acuity="ACUITY_1_CRITICAL")
        admission = create_admission(facility["id"], ed_bed["id"],
                                     patient_ref="PED")
        record = get_success_data(api.create_boarding_record(
            facility["id"], create_boarding_record_payload(admission["id"]),
            COORD))
        holds_by_bed, m1 = validate_paginated(
            api.list_bed_holds_for_bed(bed["id"], COORD))
        assert [h["id"] for h in holds_by_bed] == [hold["id"]]
        assert m1["total_count"] == 1
        holds_by_req, _m2 = validate_paginated(
            api.list_bed_holds_for_request(request["id"], COORD))
        assert [h["id"] for h in holds_by_req] == [hold["id"]]
        records, _m3 = validate_paginated(
            api.list_admission_boarding_records(admission["id"], COORD))
        assert [r["id"] for r in records] == [record["id"]]
        requests, _m4 = validate_paginated(
            api.list_physician_transfer_requests(physician["id"], COORD))
        assert [r["id"] for r in requests] == [request["id"]]


class TestNotFoundFamily:
    def test_not_found_family_all_resources(self, api):
        """PRD §2.7: "The first identifier in the path that does not resolve to
        an existing resource produces that resource type's 404 error —
        `ERR_FACILITY_NOT_FOUND`, `ERR_BED_NOT_FOUND`,
        `ERR_PHYSICIAN_NOT_FOUND`, `ERR_ADMISSION_NOT_FOUND`,
        `ERR_TRANSFER_REQUEST_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`,
        `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_DIVERSION_NOT_FOUND`,
        `ERR_BOARDING_RECORD_NOT_FOUND`, `ERR_HUDDLE_NOT_FOUND`, or
        `ERR_FORECAST_NOT_FOUND` as appropriate."

        Design: Corner/errors/not_found_family_all_resources
        """
        create_facility(name="NF Fac")  # ensure the parent exists for context
        cases = [
            (api.get_physician("11111111-1111-4111-8111-111111111111", COORD),
             ApiErrorId.ERR_PHYSICIAN_NOT_FOUND),
            (api.get_admission("22222222-2222-4222-8222-222222222222", COORD),
             ApiErrorId.ERR_ADMISSION_NOT_FOUND),
            (api.get_transfer_request("33333333-3333-4333-8333-333333333333", COORD),
             ApiErrorId.ERR_TRANSFER_REQUEST_NOT_FOUND),
            (api.get_bed_hold("44444444-4444-4444-8444-444444444444", COORD),
             ApiErrorId.ERR_HOLD_NOT_FOUND),
            (api.complete_bed_assignment(
                "55555555-5555-4555-8555-555555555555",
                make_bed_manager_headers("bm_1")),
             ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
            (api.lift_diversion("66666666-6666-4666-8666-666666666666",
                                TEST_USERS["house_supervisor_3_headers"]),
             ApiErrorId.ERR_DIVERSION_NOT_FOUND),
            (api.get_boarding_record("77777777-7777-4777-8777-777777777777", COORD),
             ApiErrorId.ERR_BOARDING_RECORD_NOT_FOUND),
            (api.resolve_huddle("88888888-8888-4888-8888-888888888888",
                                {"resolution": "x"},
                                TEST_USERS["house_supervisor_3_headers"]),
             ApiErrorId.ERR_HUDDLE_NOT_FOUND),
            (api.get_capacity_forecast("99999999-9999-4999-8999-999999999999", COORD),
             ApiErrorId.ERR_FORECAST_NOT_FOUND),
        ]
        for resp, expected in cases:
            validate_error(resp, expected)
