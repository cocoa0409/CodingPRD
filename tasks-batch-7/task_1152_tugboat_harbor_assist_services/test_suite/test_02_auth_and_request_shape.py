"""Authentication, role authorization, ownership, and request-shape rejections."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_job_order_payload,
    create_tug_payload,
    create_vessel,
    create_pilot,
    create_tariff_rate,
    create_job_order,
    create_tug,
    propose_assignment,
    propose_pilot_booking,
    setup_filed_claim,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import make_vessel_agent_headers


class TestAuthentication:
    def test_missing_role_header_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role the system
        does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_role_header_unauthenticated
        """
        res = api.list_tugs(headers={})
        validate_error(res, "ERR_UNAUTHENTICATED")


class TestRoleAuthorization:
    def test_create_tug_as_vessel_agent_returns_forbidden(self, api):
        """PRD §2.1: "an authenticated caller whose role is not on that operation's
        list is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/create_tug_as_vessel_agent_returns_forbidden
        """
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        res = api.create_tug(
            create_tug_payload(
                name="Tug Rogue",
                bollard_pull_tons=50.0,
                horsepower=4000,
                hourly_rate_cents=100000,
                insured_value_cents=15000000,
            ),
            make_vessel_agent_headers(vessel["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_dispatcher_cannot_settle_claim_returns_forbidden(self, api):
        """PRD §3.9: "Review belongs to the `ClaimsAdjuster`, a role deliberately
        segregated from dispatch."
        PRD §4: the settle row lists ClaimsAdjuster as the sole authorized role.

        Design: Corner/rbac/dispatcher_cannot_settle_claim_returns_forbidden
        """
        ctx = setup_filed_claim(claimed_amount_cents=500000)
        res = api.settle_damage_claim(
            ctx["claim"]["id"], TEST_USERS["port_dispatcher_headers"]
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_dispatcher_cannot_record_gear_inspection_returns_forbidden(self, api):
        """PRD §3.6: "A `MarineSurveyor` records an inspection of one item of towing
        gear."
        PRD §2.1: "an authenticated caller whose role is not on that operation's
        list is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/dispatcher_cannot_record_gear_inspection_returns_forbidden
        """
        tug = create_tug(name="Tug Atlas")
        res = api.create_gear_inspection(
            {
                "tug_id": tug["id"],
                "inspection_item": "WINCH",
                "outcome": "PASSED",
                "inspected_at": "2026-05-01T00:00:00Z",
                "next_due_at": "2026-11-01T00:00:00Z",
            },
            TEST_USERS["port_dispatcher_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")


class TestVesselAgentOwnership:
    def test_agent_cannot_order_for_other_vessel(self, api):
        """PRD §3.2: "the request's `vessel_id` must equal the caller's `X-User-ID`,
        or the order is refused with `ERR_JOB_NOT_OWNED` (§2.1)."

        Design: Corner/validations/agent_cannot_order_for_other_vessel
        """
        v1 = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        v2 = create_vessel(name="MV Borealis", imo_number="IMO9088888")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        res = api.create_job_order(
            create_job_order_payload(
                v2["id"],
                tariff["id"],
                scheduled_start="2026-06-01T08:00:00Z",
                scheduled_end="2026-06-01T10:00:00Z",
            ),
            make_vessel_agent_headers(v1["id"]),
        )
        validate_error(res, "ERR_JOB_NOT_OWNED")


class TestPilotOwnership:
    def test_pilot_cannot_confirm_other_pilots_booking(self, api):
        """PRD §2.1: "confirming or boarding a booking compares the booking's
        `pilot_id` against `X-User-ID`, and a mismatch is rejected with
        `ERR_BOOKING_NOT_OWNED` (HTTP 403)."

        Design: Corner/rbac/pilot_cannot_confirm_other_pilots_booking
        """
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        p1 = create_pilot(name="Pilot Reyes", license_class="CLASS_I")
        p2 = create_pilot(name="Pilot Sato", license_class="CLASS_I")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        booking = propose_pilot_booking(
            job["id"],
            p1["id"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T10:00:00Z",
        )
        res = api.confirm_pilot_booking(
            booking["id"],
            {"X-User-ID": p2["id"], "X-User-Role": "Pilot", "Content-Type": "application/json"},
        )
        validate_error(res, "ERR_BOOKING_NOT_OWNED")


class TestTugCaptainOwnership:
    def test_captain_cannot_confirm_other_tugs_assignment(self, api):
        """PRD §3.3: "the caller's `X-User-ID` must equal the assignment's `tug_id`,
        or the attempt is refused with `ERR_ASSIGNMENT_NOT_OWNED`."

        Design: Corner/rbac/captain_cannot_confirm_other_tugs_assignment
        """
        tug_a = create_tug(name="Tug Atlas", bollard_pull_tons=60.0)
        tug_b = create_tug(
            name="Tug Brutus",
            bollard_pull_tons=55.0,
            horsepower=4500,
            hourly_rate_cents=110000,
            insured_value_cents=18000000,
        )
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T10:00:00Z",
        )
        asg = propose_assignment(
            job["id"],
            tug_a["id"],
            job["version"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T10:00:00Z",
        )
        res = api.confirm_tug_assignment(
            asg["id"],
            {"X-User-ID": tug_b["id"], "X-User-Role": "TugCaptain", "Content-Type": "application/json"},
        )
        validate_error(res, "ERR_ASSIGNMENT_NOT_OWNED")


class TestRequestShape:
    def test_create_job_order_missing_scheduled_end_returns_invalid_request(self, api):
        """PRD §2.8 stage 11: "Request shape — required fields present and well-typed,
        else `ERR_INVALID_REQUEST`."
        PRD §3.2 lists `scheduled_start` to `scheduled_end` as supplied inputs.

        Design: Corner/entities/create_job_order_missing_scheduled_end_returns_invalid_request
        """
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        res = api.create_job_order(
            {
                "vessel_id": vessel["id"],
                "tariff_rate_id": tariff["id"],
                "maneuver_type": "DOCKING",
                "scheduled_start": "2026-06-01T08:00:00Z",
            },
            make_vessel_agent_headers(vessel["id"]),
        )
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_create_job_order_invalid_maneuver_type_returns_invalid_enum(self, api):
        """PRD §2.8 stage 11: "and finally enum membership, else `ERR_INVALID_ENUM`."
        PRD §3.2: the maneuver is one of docking, undocking, shifting, escort, tow.

        Design: Corner/entities/create_job_order_invalid_maneuver_type_returns_invalid_enum
        """
        vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
        tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
        res = api.create_job_order(
            {
                "vessel_id": vessel["id"],
                "tariff_rate_id": tariff["id"],
                "maneuver_type": "CIRCLE",
                "scheduled_start": "2026-06-01T08:00:00Z",
                "scheduled_end": "2026-06-01T10:00:00Z",
            },
            make_vessel_agent_headers(vessel["id"]),
        )
        validate_error(res, "ERR_INVALID_ENUM")
