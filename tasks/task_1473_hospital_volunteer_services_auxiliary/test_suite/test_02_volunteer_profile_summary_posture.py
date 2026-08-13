"""Volunteer computed fields, profile update semantics, the computed summary read,
and the live compliance-posture derivation."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    api_client, ApiErrorId,
    set_clock, approve_application, create_cleared_volunteer, create_active_volunteer,
    create_department, create_role, create_open_request, complete_orientation,
    get_volunteer, get_summary,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


class TestVolunteerComputedFields:
    def test_freshly_approved_volunteer_initialized(self, api):
        """PRD §3.4: "`total_service_hours` and `recognition_points` and
        `recognition_tier` (§3.6 — all three start at zero or `NONE`)".
        PRD §2.9: "The posture is `FROZEN` when any one of the three types hard-fails."
        (with no clearance recorded at all, every type hard-fails).
        PRD §3.1: "approval creates the volunteer record with `service_status`
        `ONBOARDING` and `joined_at` stamped from the logical clock"

        Design: Corner/entities/volunteer_computed_fields_initialized
        """
        set_clock("2026-08-01T00:00:00Z")
        _, vol_id = approve_application(full_name="Init Vera", email="iv@x.org")

        volunteer = get_volunteer(vol_id)
        assert volunteer["service_status"] == "ONBOARDING"
        assert str(volunteer["joined_at"]).startswith("2026-08-01T00:00:00")

        summary = get_summary(vol_id)
        assert summary["total_service_hours"] == pytest.approx(0.0, abs=0.001)
        assert summary["recognition_points"] == pytest.approx(0.0, abs=0.001)
        assert summary["recognition_tier"] == "NONE"
        assert summary["compliance_posture"] == "FROZEN", (
            f"no clearance records at all -> FROZEN, got {summary['compliance_posture']}")
        assert summary["accepted_placement_count"] == 0
        assert summary["live_badge_status"] == "PENDING"

    def test_update_ignores_computed_field_input(self, api):
        """PRD §3.4: "the contact and profile fields — `full_name`, `email`, `phone`,
        and `notes` — are editable later by a coordinator through the profile update".
        (`total_service_hours` is not in the editable set; it is server-computed.)
        PRD §2.5: "`version` increments by exactly one on every mutation".

        Design: Corner/entities/volunteer_update_computed_field_input_ignored
        """
        set_clock("2026-08-01T00:00:00Z")
        _, vol_id = approve_application(full_name="Rogue Field", email="rf@x.org")
        v0 = get_volunteer(vol_id)["version"]

        updated = validate_success(api.update_volunteer(
            vol_id,
            {"email": "changed@x.org", "total_service_hours": 999,
             "expected_volunteer_version": v0},
            COORDINATOR))
        assert updated["email"] == "changed@x.org", "writable field must be applied"
        assert updated["total_service_hours"] == pytest.approx(0.0, abs=0.001), (
            "client-supplied computed field must be ignored (server-owned)")
        assert updated["version"] == v0 + 1, (
            f"version must increment by exactly one: {v0} -> {updated['version']}")

    def test_volunteer_not_found(self, api):
        """PRD §2.8: "Path identifiers are validated first, left to right, then
        body-referenced foreign keys in their declared order; any missing reference
        is `ERR_NOT_FOUND`."

        Design: Corner/entities/volunteer_not_found_returns_404
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api.get_volunteer("11111111-2222-4333-8444-555555555555", COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestVolunteerSummaryRead:
    def test_summary_computed_read_fields(self, api):
        """PRD §3.6: "The volunteer summary read exposes the current service year's
        figure as `service_year_hours`, alongside `compliance_posture`,
        `total_service_hours`, `recognition_points`, `recognition_tier`,
        `is_junior_today`, the `accepted_placement_count`, and the
        `live_badge_status`."

        Design: Corner/endpoints/summary_computed_read_fields
        """
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Emergency", head_user_id="dh-1")
        role = create_role(name="ED Greeter", category="PATIENT_FACING", minimum_age=18)
        request = create_open_request(dept["id"], role["id"], slots_needed=1)
        ctx = create_active_volunteer(dept, role, request, full_name="Summary Sue",
                                      email="ss2@x.org")

        summary = get_summary(ctx["volunteer_id"])
        assert summary["compliance_posture"] == "CLEAR"
        assert summary["accepted_placement_count"] == 1
        assert summary["live_badge_status"] == "ISSUED"
        assert summary["is_junior_today"] is False
        assert summary["service_year_hours"] == pytest.approx(0.0, abs=0.001)


class TestPostureGraceWindows:
    def test_posture_clock_positions(self, api):
        """PRD §2.9: "Past `expires_at` but by no more than 30 days (exactly 30 days
        past still qualifies) — **grace**, meaning expired but inside the grace
        window."
        PRD §2.9: "From exactly 30 days before `expires_at` up to and including the
        expiry instant itself — **grace**, meaning expiring soon."
        PRD §2.9: "The posture is `FROZEN` when any one of the three types hard-fails.
        It is `RESTRICTED` when no type hard-fails but at least one type is in grace."

        Design: Corner/calculations/posture_grace_window_clock_positions
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = create_cleared_volunteer(full_name="Posture Pat", email="pp@x.org")
        vol_id = ctx["volunteer_id"]
        # TB/FLU cleared at 2026-08-01 expire 2027-08-01; BACKGROUND expires 2028-08-01.

        summary = get_summary(vol_id)
        assert summary["compliance_posture"] == "CLEAR", "all three freshly cleared"

        set_clock("2027-07-15T00:00:00Z")  # 17 days before TB/FLU expiry
        summary = get_summary(vol_id)
        assert summary["compliance_posture"] == "RESTRICTED", (
            "inside the 30-day expiring-soon window -> RESTRICTED")

        set_clock("2027-08-31T00:00:00Z")  # exactly expires_at + 30 days (inclusive)
        summary = get_summary(vol_id)
        assert summary["compliance_posture"] == "RESTRICTED", (
            "exactly 30 days past expiry still qualifies as grace -> RESTRICTED")

        set_clock("2027-09-01T00:00:00Z")  # 31 days past expiry
        summary = get_summary(vol_id)
        assert summary["compliance_posture"] == "FROZEN", (
            "more than 30 days past expiry is a hard failure -> FROZEN")
