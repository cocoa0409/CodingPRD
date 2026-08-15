"""Diversion posture: windows, lift guards, segregation of duties, cascades."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    T_0020,
    T_0030,
    T_0100,
    add_physician,
    assert_instant_equal,
    create_diversion_payload,
    create_facility,
    create_transfer_request,
    declare_diversion,
    dispatch_consult,
    get_success_data,
    make_coordinator_headers,
    make_house_supervisor_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["sysadmin_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestDiversionWindows:
    def test_diversion_windows_half_open_adjacency(self, api):
        """PRD §2.11: "Two diversion windows therefore may be adjacent — a new
        window starting exactly when an existing one ends does not overlap it".
        PRD §3.7: "The window must not overlap any other `ACTIVE` diversion of
        the same facility: overlap means the new window starts before the
        existing window ends and the existing window starts before the new
        window ends, evaluated under the half-open convention of §2.11, so
        adjacent windows that merely touch at a boundary are allowed. An
        overlap is rejected with `ERR_DIVERSION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/diversion_windows_half_open_adjacency
        """
        set_clock()
        facility = create_facility(name="Window Facility")
        declare_diversion(facility["id"], level="FULL",
                          starts_at="2026-08-01T00:00:00Z",
                          ends_at="2026-08-01T02:00:00Z", supervisor_id="hs_1")
        adjacent = validate_success(api.create_diversion(
            facility["id"],
            create_diversion_payload(level="SERVICE", service="CARDIAC",
                                     starts_at="2026-08-01T02:00:00Z",
                                     ends_at="2026-08-01T04:00:00Z"),
            make_house_supervisor_headers("hs_2")), 201)
        assert adjacent["status"] == "ACTIVE"
        resp = api.create_diversion(
            facility["id"],
            create_diversion_payload(level="FULL",
                                     starts_at="2026-08-01T01:00:00Z",
                                     ends_at="2026-08-01T03:00:00Z"),
            make_house_supervisor_headers("hs_1"))
        validate_error(resp, ApiErrorId.ERR_DIVERSION_WINDOW_OVERLAP)

    def test_diversion_window_invalid_shape_rejected(self, api):
        """PRD §3.7: "Supplying a `service` for a `FULL` diversion, or omitting
        it for a `SERVICE` diversion, is rejected with `ERR_INVALID_REQUEST`,
        as is a window whose `ends_at` is not strictly later than its
        `starts_at`."

        Design: Difficulty/resource_temporal_overlap/diversion_windows_half_open_adjacency
        """
        set_clock()
        facility = create_facility(name="Window Facility 2")
        # ends_at equal to starts_at is not strictly later.
        resp = api.create_diversion(
            facility["id"],
            create_diversion_payload(level="FULL",
                                     starts_at="2026-08-01T02:00:00Z",
                                     ends_at="2026-08-01T02:00:00Z"),
            make_house_supervisor_headers("hs_1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # service supplied for a FULL diversion is rejected.
        resp2 = api.create_diversion(
            facility["id"],
            create_diversion_payload(level="FULL", service="CARDIAC",
                                     starts_at="2026-08-01T00:00:00Z",
                                     ends_at="2026-08-01T02:00:00Z"),
            make_house_supervisor_headers("hs_1"))
        validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST)


class TestDiversionLift:
    def test_sod_diversion_lift_same_actor_denied(self, api):
        """PRD §2.10: "A diversion event may only be lifted by a
        `HouseSupervisor` whose `X-User-ID` differs from the
        `declared_by_user_id` recorded when the diversion was declared; the
        same operator attempting both is rejected with
        `ERR_SOD_DIVERSION_DECLARE_LIFT_SAME_ACTOR` (HTTP 403)."

        Design: Corner/validations/sod_diversion_lift_same_actor_denied
        """
        set_clock()
        facility = create_facility(name="SOD Fac")
        diversion = declare_diversion(
            facility["id"], level="FULL",
            starts_at="2026-08-01T00:00:00Z",
            ends_at="2026-08-01T04:00:00Z", supervisor_id="hs_1")
        set_clock(T_0045 := "2026-08-01T00:45:00Z")
        resp = api.lift_diversion(
            diversion["id"], make_house_supervisor_headers("hs_1"))
        validate_error(
            resp, ApiErrorId.ERR_SOD_DIVERSION_DECLARE_LIFT_SAME_ACTOR)
        lifted = validate_success(api.lift_diversion(
            diversion["id"], make_house_supervisor_headers("hs_2")), 200)
        assert lifted["status"] == "LIFTED"
        assert lifted["lifted_by_user_id"] == "hs_2"

    def test_diversion_lift_too_soon_rejected(self, api):
        """PRD §3.7: "at least thirty minutes must have elapsed since the
        diversion's `created_at`, with an earlier attempt rejected as
        `ERR_DIVERSION_LIFT_TOO_SOON`."

        Design: Corner/validations/diversion_lift_too_soon_rejected
        """
        set_clock()
        facility = create_facility(name="Lift Fac")
        diversion = declare_diversion(
            facility["id"], level="FULL",
            starts_at="2026-08-01T00:00:00Z",
            ends_at="2026-08-01T04:00:00Z", supervisor_id="hs_1")
        set_clock(T_0020)
        resp = api.lift_diversion(
            diversion["id"], make_house_supervisor_headers("hs_2"))
        validate_error(resp, ApiErrorId.ERR_DIVERSION_LIFT_TOO_SOON)
        set_clock(T_0030)  # exactly created_at + 30 minutes
        lifted = validate_success(api.lift_diversion(
            diversion["id"], make_house_supervisor_headers("hs_2")), 200)
        assert lifted["status"] == "LIFTED"

    def test_diversion_lift_twice_rejected(self, api):
        """PRD §3.7: "A `HouseSupervisor` may lift an `ACTIVE` diversion —
        lifting from any other status is rejected with
        `ERR_DIVERSION_INVALID_STATE`".

        Design: Corner/errors/diversion_lift_twice_rejected
        """
        set_clock()
        facility = create_facility(name="DIS Fac")
        diversion = declare_diversion(
            facility["id"], level="FULL",
            starts_at="2026-08-01T00:00:00Z",
            ends_at="2026-08-01T04:00:00Z", supervisor_id="hs_1")
        set_clock(T_0100)
        validate_success(api.lift_diversion(
            diversion["id"], make_house_supervisor_headers("hs_2")), 200)
        resp = api.lift_diversion(
            diversion["id"], make_house_supervisor_headers("hs_3"))
        validate_error(resp, ApiErrorId.ERR_DIVERSION_INVALID_STATE)


class TestDiversionIntakeGate:
    def test_diversion_full_blocks_transfer_intake(self, api):
        """PRD §3.3: "Intake is gated by diversion posture: if the destination
        facility is in `DIVERT_FULL`, or is in `DIVERT_SERVICE` for a service
        matching the request's `service`, creation is rejected with
        `ERR_FACILITY_ON_DIVERSION`."

        Design: Difficulty/cross_entity_state_dependency/diversion_full_blocks_transfer_intake
        """
        set_clock()
        facility = create_facility(name="Gate Facility")
        declare_diversion(facility["id"], level="FULL",
                          starts_at="2026-08-01T00:00:00Z",
                          ends_at="2026-08-01T02:00:00Z", supervisor_id="hs_1")
        set_clock(T_0030)  # inside the diversion window
        resp = api.create_transfer_request(
            facility["id"],
            {"source_facility_name": "St Elsewhere", "patient_ref": "PG1",
             "acuity": "ACUITY_3_MEDICAL_SURGICAL", "isolation_need": "NONE",
             "service": "CARDIAC", "priority": "URGENT"},
            make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_FACILITY_ON_DIVERSION)
        _data, meta = validate_paginated(
            api.list_transfer_requests(facility["id"], COORD))
        assert meta["total_count"] == 0, "no request is persisted"

    def test_divert_service_blocks_only_matching_service(self, api):
        """PRD §3.3: "if the destination facility is in `DIVERT_FULL`, or is in
        `DIVERT_SERVICE` for a service matching the request's `service`,
        creation is rejected with `ERR_FACILITY_ON_DIVERSION`."

        Design: Difficulty/cross_entity_state_dependency/diversion_full_blocks_transfer_intake
        """
        set_clock()
        facility = create_facility(name="Gate Facility 2")
        declare_diversion(facility["id"], level="SERVICE", service="CARDIAC",
                          starts_at="2026-08-01T00:00:00Z",
                          ends_at="2026-08-01T02:00:00Z", supervisor_id="hs_1")
        set_clock(T_0030)
        # Matching service is refused.
        resp = api.create_transfer_request(
            facility["id"],
            {"source_facility_name": "St Elsewhere", "patient_ref": "PG2",
             "acuity": "ACUITY_3_MEDICAL_SURGICAL", "isolation_need": "NONE",
             "service": "CARDIAC", "priority": "URGENT"},
            make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_FACILITY_ON_DIVERSION)
        # A non-matching service still intakes under DIVERT_SERVICE.
        ok = validate_success(api.create_transfer_request(
            facility["id"],
            {"source_facility_name": "St Elsewhere", "patient_ref": "PG3",
             "acuity": "ACUITY_3_MEDICAL_SURGICAL", "isolation_need": "NONE",
             "service": "NEURO", "priority": "URGENT"},
            make_coordinator_headers("coord_1")), 201)
        assert ok["status"] == "INTAKE"


class TestDiversionCascade:
    def _pipeline_facility(self, api, name="Divert Facility"):
        facility = create_facility(name=name)
        physician = add_physician(facility["id"], full_name="Dr D",
                                  services=("CARDIAC",))
        tr1 = create_transfer_request(facility["id"], patient_ref="PD1")
        tr2 = create_transfer_request(facility["id"], patient_ref="PD2",
                                      priority="EMERGENT")
        dispatch_consult(tr2["id"], physician["id"])
        return facility, physician, tr1, tr2

    def test_diversion_declaration_declines_pipeline_chain(self, api):
        """PRD §3.7: "Entering `DIVERT_FULL` has teeth: every transfer request
        of the facility sitting in `INTAKE` or `CONSULT_PENDING` is moved to
        `DECLINED` with `decline_reason` set to `DIVERSION`,
        `accepting_physician_id` cleared, and `consult_deadline` cleared, after
        which `active_inbound_transfers` and the load scores are recomputed."

        Design: Difficulty/transitive_cascade/diversion_declaration_declines_pipeline_chain
        """
        set_clock()
        facility, _physician, tr1, tr2 = self._pipeline_facility(api)
        declare_diversion(facility["id"], level="FULL",
                          starts_at="2026-08-01T00:00:00Z",
                          ends_at="2026-08-01T02:00:00Z", supervisor_id="hs_1")
        facility_after = validate_success(api.get_facility(facility["id"], COORD))
        assert facility_after["diversion_status"] == "DIVERT_FULL"
        # §3.2: DECLINED is a non-terminal status and remains counted in
        # active_inbound_transfers; the cascade recomputes the counter, it
        # does not drain it. Both requests (ex-INTAKE, ex-CONSULT_PENDING)
        # are now DECLINED.
        assert facility_after["active_inbound_transfers"] == 2
        for request in (tr1, tr2):
            after = validate_success(
                api.get_transfer_request(request["id"], COORD))
            assert after["status"] == "DECLINED"
            assert after["decline_reason"] == "DIVERSION"

    def test_diversion_cascade_clears_consult_fields(self, api):
        """PRD §3.7: "every transfer request of the facility sitting in
        `INTAKE` or `CONSULT_PENDING` is moved to `DECLINED` with
        `decline_reason` set to `DIVERSION`, `accepting_physician_id` cleared,
        and `consult_deadline` cleared".
        PRD §3.7: "it is `DIVERT_FULL` when any `ACTIVE` `FULL` diversion's
        window contains the current time".

        Design: Difficulty/transitive_cascade/diversion_declaration_declines_pipeline_chain
        """
        set_clock()
        facility, physician, _tr1, tr2 = self._pipeline_facility(
            api, name="Divert Facility 2")
        # Sanity: tr2 is mid-consult before the cascade.
        pending = validate_success(api.get_transfer_request(tr2["id"], COORD))
        assert pending["status"] == "CONSULT_PENDING"
        assert pending["accepting_physician_id"] == physician["id"]
        assert_instant_equal(pending["consult_deadline"], "2026-08-01T00:30:00Z")
        declare_diversion(facility["id"], level="FULL",
                          starts_at="2026-08-01T00:00:00Z",
                          ends_at="2026-08-01T02:00:00Z", supervisor_id="hs_1")
        after = validate_success(api.get_transfer_request(tr2["id"], COORD))
        assert after["status"] == "DECLINED"
        assert after["decline_reason"] == "DIVERSION"
        assert after["accepting_physician_id"] is None
        assert after["consult_deadline"] is None
