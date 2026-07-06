"""Difficulty rule: cross_entity_state_dependency.

A transition on one entity is gated by another entity's state:
  (A) a Citation may be issued only when its Shift is OPEN;
  (B) a manual BootTowOrder may be created only when the Vehicle is
      BOOT_ELIGIBLE or TOW_ELIGIBLE.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_enforcement_officer_headers,
    setup_issuing_context,
    issue_in_context,
    close_shift,
    create_vehicle,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]


class TestCitationRequiresOpenShift:
    def test_issue_on_closed_shift_rejected(self, api):
        """PRD §3.3: "The shift must be `OPEN` (else `ERR_SHIFT_NOT_OPEN`) and the
        violation code must be `ACTIVE` (else `ERR_VIOLATION_CODE_RETIRED`)."

        Design: Difficulty/cross_entity_state_dependency/citation_issue_requires_open_shift
        """
        ctx = setup_issuing_context(scheduled_start="2026-03-02T08:00:00Z",
                                    scheduled_end="2026-03-02T10:00:00Z")
        close_shift(ctx["shift"]["id"], ctx["officer"]["id"])
        validate_error(
            api.create_citation(
                {"vehicle_id": ctx["vehicle"]["id"], "shift_id": ctx["shift"]["id"],
                 "violation_code_id": ctx["violation_code"]["id"],
                 "issued_via": "HANDHELD", "evidence_photo_url": "https://ev/ce1.jpg"},
                make_enforcement_officer_headers(ctx["officer"]["id"])),
            ApiErrorId.ERR_SHIFT_NOT_OPEN.value)

    def test_issue_on_open_shift_succeeds(self, api):
        """PRD §3.3: "An `EnforcementOfficer` issues a citation against an `OPEN`
        shift they own."

        Design: Difficulty/cross_entity_state_dependency/citation_issue_requires_open_shift
        """
        ctx = setup_issuing_context()
        cit = validate_success(
            api.create_citation(
                {"vehicle_id": ctx["vehicle"]["id"], "shift_id": ctx["shift"]["id"],
                 "violation_code_id": ctx["violation_code"]["id"],
                 "issued_via": "LPR", "evidence_photo_url": "https://ev/ok.jpg"},
                make_enforcement_officer_headers(ctx["officer"]["id"])),
            201)
        assert cit["status"] == "ISSUED"


class TestBootOrderRequiresEligibleVehicle:
    def test_manual_boot_on_none_vehicle_rejected(self, api):
        """PRD §3.8: "A manual order is permitted only when the vehicle is
        `BOOT_ELIGIBLE` or `TOW_ELIGIBLE`; against a vehicle whose `scofflaw_status`
        is `NONE` or `SCOFFLAW` it is rejected with `ERR_VEHICLE_NOT_BOOT_ELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/boot_order_requires_boot_eligible_vehicle
        """
        vehicle = create_vehicle(plate="CE2PLT", headers=SUPERVISOR)
        validate_error(
            api.create_boot_tow_order(
                {"vehicle_id": vehicle["id"], "order_type": "BOOT"}, SUPERVISOR),
            ApiErrorId.ERR_VEHICLE_NOT_BOOT_ELIGIBLE.value)

    def test_manual_boot_on_scofflaw_vehicle_rejected(self, api):
        """PRD §3.8: "A manual order is permitted only when the vehicle is
        `BOOT_ELIGIBLE` or `TOW_ELIGIBLE`; against a vehicle whose `scofflaw_status`
        is `NONE` or `SCOFFLAW` it is rejected with `ERR_VEHICLE_NOT_BOOT_ELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/boot_order_requires_boot_eligible_vehicle
        """
        # 3 STREET_CLEAN citations -> count 3, balance 27000 (< 50000) -> SCOFFLAW.
        ctx = setup_issuing_context(base_fine_cents=6000, code="STREET_CLEAN",
                                    is_booting_eligible=False)
        issue_in_context(ctx, evidence_photo_url="https://ev/s1.jpg")
        issue_in_context(ctx, evidence_photo_url="https://ev/s2.jpg")
        issue_in_context(ctx, evidence_photo_url="https://ev/s3.jpg")
        veh = validate_success(api.get_vehicle(ctx["vehicle"]["id"], SUPERVISOR))
        assert veh["scofflaw_status"] == "SCOFFLAW"
        validate_error(
            api.create_boot_tow_order(
                {"vehicle_id": ctx["vehicle"]["id"], "order_type": "BOOT"}, SUPERVISOR),
            ApiErrorId.ERR_VEHICLE_NOT_BOOT_ELIGIBLE.value)
