"""Inspection defects: roadworthiness derivation, the correction workflow,
and compliance-desk role gating."""
from test_helpers import (
    TEST_USERS,
    advance_clock,
    attach_defect_call,
    create_standard_rate_card,
    create_technician,
    create_vehicle,
    file_defect,
    get_success_data,
    intake_call,
    mark_defect_corrected,
    open_triaged_call,
    parse_iso8601_utc,
    repair_existing_call,
    validate_error,
    verify_defect,
)
from test_helpers import ApiErrorId

OPS = TEST_USERS["ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


class TestRoadworthinessLifecycle:
    def test_vehicle_roadworthiness_flips_with_oos_defect_lifecycle(self, api):
        """PRD: roadworthiness "is `OUT_OF_SERVICE` while any of its
        inspection defects has `severity` `OOS` in a status of `OPEN`,
        `REPAIR_SCHEDULED`, `CORRECTED`, `VERIFICATION_FAILED`, or
        `ESCALATED`, and `ROADWORTHY` otherwise" and "Filing computes
        `correction_deadline_at` as exactly 15 days after discovery and opens
        the defect as `OPEN`".

        Design: Corner/entities/vehicle_roadworthiness_flips_with_oos_defect_lifecycle
        """
        advance_clock("2026-08-05T09:00:00Z")
        veh = create_vehicle()
        assert veh["roadworthiness"] == "ROADWORTHY"

        defect = file_defect(veh["id"], severity="OOS",
                             citation_reference="DOT-7788",
                             discovered_at="2026-08-05T08:00:00Z")
        assert defect["status"] == "OPEN"
        assert parse_iso8601_utc(defect["correction_deadline_at"]) == \
            parse_iso8601_utc("2026-08-20T08:00:00Z"), (
            "discovered_at + 15 days")
        veh_now = get_success_data(api.get_vehicle(veh["id"], SAFETY))
        assert veh_now["roadworthiness"] == "OUT_OF_SERVICE"

        # Correct the defect through a linked call.
        create_standard_rate_card()
        tech, tech_headers = create_technician(
            certifications=("ELECTRICAL",))
        call = open_triaged_call(veh["id"], symptom_category="LIGHTING",
                                 severity="DRIVABLE", received_at=None,
                                 symptom_description=
                                 "marker lamps out per citation")
        repair_existing_call(
            call["id"], tech["id"], tech_headers,
            window=("2026-08-05T09:30:00Z", "2026-08-05T13:00:00Z"),
            depart_at=None, arrive_at="2026-08-05T10:10:00Z",
            actual_travel_miles=20, labor_hours_actual=1.0,
            completion_odometer_miles=90020,
            diagnosis_summary="wiring repaired")
        attached = attach_defect_call(defect["id"], call["id"])
        assert attached["status"] == "REPAIR_SCHEDULED"
        corrected = mark_defect_corrected(defect["id"], tech_headers,
                                          correction_note=
                                          "replaced harness section")
        assert corrected["status"] == "CORRECTED"
        veh_mid = get_success_data(api.get_vehicle(veh["id"], SAFETY))
        assert veh_mid["roadworthiness"] == "OUT_OF_SERVICE", (
            "an OOS defect still CORRECTED holds the vehicle out of service")

        verified = verify_defect(defect["id"], "PASS")
        assert verified["status"] == "VERIFIED"
        veh_end = get_success_data(api.get_vehicle(veh["id"], SAFETY))
        assert veh_end["roadworthiness"] == "ROADWORTHY", (
            "verifying the last open OOS defect restores roadworthiness")


class TestDefectVerificationGate:
    def test_verify_uncorrected_defect_rejected(self, api):
        """PRD: "Verification belongs to the `SafetyOfficer` alone and
        requires the defect to be `CORRECTED` (`ERR_DEFECT_NOT_CORRECTED`
        otherwise)".

        Design: Corner/state_machines/verify_uncorrected_defect_rejected
        """
        veh = create_vehicle()
        defect = file_defect(veh["id"], severity="NON_OOS",
                             discovered_at="2026-08-05T08:00:00Z")
        resp = api.verify_defect(defect["id"], {"outcome": "PASS"}, SAFETY)
        validate_error(resp, ApiErrorId.ERR_DEFECT_NOT_CORRECTED)
        current = get_success_data(
            api.get_inspection_defect(defect["id"], SAFETY))
        assert current["status"] == "OPEN"


class TestDefectAttachVehicleMatch:
    def test_attach_call_with_wrong_vehicle_rejected(self, api):
        """PRD: "attaches a correcting call by its `service_call_id`, which
        must name a call on the same vehicle (`ERR_VEHICLE_MISMATCH`
        otherwise)".

        Design: Corner/errors/attach_call_with_wrong_vehicle_rejected
        """
        veh_a = create_vehicle()
        veh_b = create_vehicle()
        defect = file_defect(veh_a["id"], severity="NON_OOS",
                             source="ANNUAL_INSPECTION",
                             discovered_at="2026-08-01T08:00:00Z")
        call_b = intake_call(veh_b["id"], symptom_category="LIGHTING",
                             symptom_description="lamps",
                             breakdown_location_text="site B")
        resp = api.attach_defect_call(
            defect["id"], {"service_call_id": call_b["id"]}, SAFETY)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_MISMATCH)
        current = get_success_data(
            api.get_inspection_defect(defect["id"], SAFETY))
        assert current["status"] == "OPEN"


class TestDefectRecordingRoles:
    def test_dispatcher_cannot_record_inspection_defect(self, api):
        """PRD: inspection defects are "filed by a `SafetyOfficer` (or
        `OpsAdmin`)" — and "An attempt to perform an action outside the roles
        declared for that endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/dispatcher_cannot_record_inspection_defect
        """
        veh = create_vehicle()
        resp = api.create_inspection_defect(
            veh["id"],
            {"source": "DRIVER_REPORT", "defect_code": "393.9",
             "severity": "NON_OOS",
             "discovered_at": "2026-08-05T08:00:00Z"},
            DISPATCHER)
        assert resp.status_code == 403
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
