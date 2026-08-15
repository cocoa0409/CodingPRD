"""Volunteers and shifts: certification gates, half-open overlap, cancel
lockout, no-show strike cascade, and the hours ledger."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    MANAGER,
    create_menu_day,
    create_shift,
    create_site,
    create_volunteer,
    set_clock,
)
from test_helpers.test_users import make_volunteer_headers


class TestCheckInCertificationGate:
    """Queue A: cross_entity_state_dependency / shift_checkin_gated_by_volunteer_cert."""

    def _setup_cook_shift(self, api, certification_level, certification_expires_at):
        set_clock("2026-08-01T08:00:00Z")
        site = create_site(name="Cert Kitchen", dine_in_capacity=40,
                           togo_capacity_per_window=20, delivery_radius_km=5)
        menu_day = create_menu_day(site["id"], "2026-08-11")
        volunteer = create_volunteer(
            full_name="Vol X", certification_level=certification_level,
            certification_expires_at=certification_expires_at,
        )
        shift = create_shift(
            site["id"], volunteer["id"], menu_day["id"], role_on_shift="COOK",
            starts_at="2026-08-11T10:00:00Z", ends_at="2026-08-11T14:00:00Z",
        )
        return site, menu_day, volunteer, shift

    def test_checkin_rejected_when_certification_expired(self, api):
        """PRD 3.4: "Certification gates the role: working as `COOK` requires
        at least `BASIC`, and working as `SUPERVISOR_ON_DUTY` requires
        `SUPERVISOR`, with the card unexpired at the moment it is exercised;
        a shortfall is rejected with `ERR_CERTIFICATION_INSUFFICIENT`."
        PRD 2.5: "a food-handler certification is invalid at or after its
        `certification_expires_at`."

        Design: Difficulty/cross_entity_state_dependency/shift_checkin_gated_by_volunteer_cert
        """
        site, menu_day, volunteer, shift = self._setup_cook_shift(
            api, "BASIC", "2026-08-10T00:00:00Z"
        )
        # Clock inside the check-in window but past the cert expiry.
        set_clock("2026-08-11T09:50:00Z")
        resp = api.check_in_shift(shift["id"], make_volunteer_headers(volunteer["id"]))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_INSUFFICIENT)

    def test_checkin_at_exact_cert_expiry_instant_is_rejected(self, api):
        """PRD 2.5: "a food-handler certification is invalid at or after its
        `certification_expires_at`."
        PRD 3.4: "a shortfall is rejected with
        `ERR_CERTIFICATION_INSUFFICIENT`."

        Design: Difficulty/cross_entity_state_dependency/shift_checkin_gated_by_volunteer_cert
        """
        site, menu_day, volunteer, shift = self._setup_cook_shift(
            api, "BASIC", "2026-08-11T09:50:00Z"
        )
        # Check-in attempted at the exact expiry instant: cert already invalid.
        set_clock("2026-08-11T09:50:00Z")
        resp = api.check_in_shift(shift["id"], make_volunteer_headers(volunteer["id"]))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_INSUFFICIENT)


class TestShiftOverlap:
    """Queue A: resource_temporal_overlap / volunteer_shift_halfopen_overlap."""

    def test_abutting_shifts_accepted_overlapping_rejected(self, api):
        """PRD 3.4: "Shift intervals are half-open — they include `starts_at`
        and exclude `ends_at` — and one volunteer may never hold two
        overlapping shifts; a collision is rejected with
        `ERR_TEMPORAL_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/volunteer_shift_halfopen_overlap
        """
        set_clock("2026-08-01T08:00:00Z")
        site = create_site(name="Shift Kitchen", dine_in_capacity=40,
                           togo_capacity_per_window=20, delivery_radius_km=5)
        menu_day = create_menu_day(site["id"], "2026-08-11")
        volunteer = create_volunteer(full_name="Vol H")
        create_shift(
            site["id"], volunteer["id"], menu_day["id"], role_on_shift="PREP",
            starts_at="2026-08-11T08:00:00Z", ends_at="2026-08-11T10:00:00Z",
        )

        # Half-open: [10:00, 12:00) does not intersect [08:00, 10:00).
        resp = api.create_volunteer_shift(
            {
                "site_id": site["id"],
                "volunteer_id": volunteer["id"],
                "menu_day_id": menu_day["id"],
                "role_on_shift": "SERVER",
                "starts_at": "2026-08-11T10:00:00Z",
                "ends_at": "2026-08-11T12:00:00Z",
            },
            MANAGER,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "SCHEDULED"

        # [09:59, 11:00) overlaps [08:00, 10:00).
        resp = api.create_volunteer_shift(
            {
                "site_id": site["id"],
                "volunteer_id": volunteer["id"],
                "menu_day_id": menu_day["id"],
                "role_on_shift": "SERVER",
                "starts_at": "2026-08-11T09:59:00Z",
                "ends_at": "2026-08-11T11:00:00Z",
            },
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_CONFLICT)

    def test_overlap_rule_is_per_volunteer(self, api):
        """PRD 3.4: "one volunteer may never hold two overlapping shifts; a
        collision is rejected with `ERR_TEMPORAL_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/volunteer_shift_halfopen_overlap
        """
        set_clock("2026-08-01T08:00:00Z")
        site = create_site(name="Shift Kitchen 2", dine_in_capacity=40,
                           togo_capacity_per_window=20, delivery_radius_km=5)
        menu_day = create_menu_day(site["id"], "2026-08-11")
        v1 = create_volunteer(full_name="Vol A")
        v2 = create_volunteer(full_name="Vol B")
        create_shift(
            site["id"], v1["id"], menu_day["id"], role_on_shift="PREP",
            starts_at="2026-08-11T08:00:00Z", ends_at="2026-08-11T10:00:00Z",
        )
        # The same window held by a different volunteer is no collision.
        resp = api.create_volunteer_shift(
            {
                "site_id": site["id"],
                "volunteer_id": v2["id"],
                "menu_day_id": menu_day["id"],
                "role_on_shift": "COOK",
                "starts_at": "2026-08-11T08:00:00Z",
                "ends_at": "2026-08-11T10:00:00Z",
            },
            MANAGER,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "SCHEDULED"


class TestCancelLockout:
    def test_shift_cancel_lockout_for_volunteer(self, api):
        """PRD 3.4: "A volunteer may self-cancel a `SCHEDULED` shift only
        while the logical clock is earlier than `starts_at` by at least the
        program's `CANCEL_LOCKOUT_HOURS` lockout margin; inside the lockout
        the attempt is rejected with `ERR_CANCEL_IN_LOCKOUT`. A
        `KitchenManager` may cancel at any time".

        Design: Corner/state_machines/shift_cancel_lockout_for_volunteer
        """
        set_clock("2026-08-01T08:00:00Z")
        site = create_site(name="Lock Site", dine_in_capacity=30,
                           togo_capacity_per_window=15, delivery_radius_km=5)
        menu_day = create_menu_day(site["id"], "2026-08-12")
        volunteer = create_volunteer(full_name="Vol L")
        shift = create_shift(
            site["id"], volunteer["id"], menu_day["id"], role_on_shift="SERVER",
            starts_at="2026-08-12T10:00:00Z", ends_at="2026-08-12T14:00:00Z",
        )
        # One minute before starts_at is inside any positive lockout margin.
        set_clock("2026-08-12T09:59:00Z")

        resp = api.cancel_shift(shift["id"], {}, make_volunteer_headers(volunteer["id"]))
        validate_error(resp, ApiErrorId.ERR_CANCEL_IN_LOCKOUT)

        # The manager may cancel at the same instant.
        resp = api.cancel_shift(shift["id"], {"apply_penalty": False}, MANAGER)
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"


class TestNoShowStrikeCascade:
    """Queue A: transitive_cascade / volunteer_noshow_suspend_shiftcancel_cascade."""

    def test_third_strike_suspends_and_cancels_future_shifts(self, api):
        """PRD 3.4: "Either way the volunteer's `strike_count` increases by
        one, and a volunteer whose strike count reaches three — the program's
        `MAX_STRIKES` — is automatically moved from `ACTIVE` to `SUSPENDED`,
        with the cascade that all of their future `SCHEDULED` shifts are
        cancelled without penalty."

        Design: Difficulty/transitive_cascade/volunteer_noshow_suspend_shiftcancel_cascade
        """
        set_clock("2026-08-08T08:00:00Z")
        site = create_site(name="Strike Kitchen", dine_in_capacity=40,
                           togo_capacity_per_window=20, delivery_radius_km=5)
        d0 = create_menu_day(site["id"], "2026-08-08")
        d1 = create_menu_day(site["id"], "2026-08-09")
        d2 = create_menu_day(site["id"], "2026-08-10")
        d3 = create_menu_day(site["id"], "2026-08-12")
        volunteer = create_volunteer(full_name="Vol S")
        n1 = create_shift(site["id"], volunteer["id"], d0["id"],
                          role_on_shift="SERVER",
                          starts_at="2026-08-08T10:00:00Z",
                          ends_at="2026-08-08T12:00:00Z")
        n2 = create_shift(site["id"], volunteer["id"], d1["id"],
                          role_on_shift="SERVER",
                          starts_at="2026-08-09T10:00:00Z",
                          ends_at="2026-08-09T12:00:00Z")
        f1 = create_shift(site["id"], volunteer["id"], d2["id"],
                          role_on_shift="SERVER",
                          starts_at="2026-08-10T10:00:00Z",
                          ends_at="2026-08-10T14:00:00Z")
        f2 = create_shift(site["id"], volunteer["id"], d3["id"],
                          role_on_shift="SERVER",
                          starts_at="2026-08-12T10:00:00Z",
                          ends_at="2026-08-12T14:00:00Z")

        set_clock("2026-08-08T13:00:00Z")
        get_success_data(api.mark_no_show(n1["id"], MANAGER))
        set_clock("2026-08-09T13:00:00Z")
        get_success_data(api.mark_no_show(n2["id"], MANAGER))

        # Third strike: suspension and cascade.
        set_clock("2026-08-10T15:00:00Z")
        get_success_data(api.mark_no_show(f1["id"], MANAGER))

        volunteer = get_success_data(api.get_volunteer(volunteer["id"], MANAGER))
        assert volunteer["strike_count"] == 3, (
            f"three no-shows must give strike_count 3, got {volunteer['strike_count']}"
        )
        assert volunteer["status"] == "SUSPENDED", (
            f"strike_count reaching MAX_STRIKES must auto-suspend, "
            f"got {volunteer['status']!r}"
        )
        f2 = get_success_data(api.get_volunteer_shift(f2["id"], MANAGER))
        assert f2["status"] == "CANCELLED", (
            f"suspension cascades future SCHEDULED shifts to CANCELLED, "
            f"got {f2['status']!r}"
        )

    def test_single_no_show_increments_strike_without_suspend(self, api):
        """PRD 3.4: "Either way the volunteer's `strike_count` increases by
        one, and a volunteer whose strike count reaches three — the program's
        `MAX_STRIKES` — is automatically moved from `ACTIVE` to `SUSPENDED`".
        PRD 3.4: "Reinstating a suspended volunteer returns them `SUSPENDED` →
        `ACTIVE` and resets `strike_count` to zero."

        Design: Difficulty/transitive_cascade/volunteer_noshow_suspend_shiftcancel_cascade
        """
        set_clock("2026-08-08T08:00:00Z")
        site = create_site(name="Strike Kitchen 2", dine_in_capacity=40,
                           togo_capacity_per_window=20, delivery_radius_km=5)
        d0 = create_menu_day(site["id"], "2026-08-08")
        volunteer = create_volunteer(full_name="Vol One-Strike")
        shift = create_shift(site["id"], volunteer["id"], d0["id"],
                             role_on_shift="SERVER",
                             starts_at="2026-08-08T10:00:00Z",
                             ends_at="2026-08-08T12:00:00Z")
        set_clock("2026-08-08T13:00:00Z")
        get_success_data(api.mark_no_show(shift["id"], MANAGER))

        volunteer = get_success_data(api.get_volunteer(volunteer["id"], MANAGER))
        assert volunteer["strike_count"] == 1
        assert volunteer["status"] == "ACTIVE", (
            "a single strike must not suspend the volunteer"
        )

        # Manager-imposed suspension followed by reinstate resets strikes.
        get_success_data(api.suspend_volunteer(volunteer["id"], MANAGER))
        volunteer = get_success_data(api.reinstate_volunteer(volunteer["id"], MANAGER))
        assert volunteer["status"] == "ACTIVE"
        assert volunteer["strike_count"] == 0, (
            f"reinstate resets strike_count to zero, got {volunteer['strike_count']}"
        )


class TestVolunteerHoursLedger:
    def test_volunteer_hours_ledger_floor_and_penalty(self, api):
        """PRD 3.4: "Completion credits the hours ledger: the shift's duration
        — `ends_at` minus `starts_at`, expressed in fractional hours and
        rounded half up to two decimal places — is added to the volunteer's
        `hours_balance`."
        PRD 3.4: "A `KitchenManager` may cancel at any time, and when
        cancelling inside the lockout may set the request's `apply_penalty`
        flag, which subtracts two hours from the volunteer's `hours_balance`,
        floored at zero."

        Design: Corner/calculations/volunteer_hours_ledger_floor_and_penalty
        """
        set_clock("2026-08-01T08:00:00Z")
        site = create_site(name="Ledger Site", dine_in_capacity=30,
                           togo_capacity_per_window=15, delivery_radius_km=5)
        d1 = create_menu_day(site["id"], "2026-08-08")
        d2 = create_menu_day(site["id"], "2026-08-09")
        d3 = create_menu_day(site["id"], "2026-08-10")
        volunteer = create_volunteer(full_name="Vol Ledger")
        sh1 = create_shift(site["id"], volunteer["id"], d1["id"],
                           role_on_shift="SERVER",
                           starts_at="2026-08-08T10:00:00Z",
                           ends_at="2026-08-08T11:00:00Z")
        sh2 = create_shift(site["id"], volunteer["id"], d2["id"],
                           role_on_shift="SERVER",
                           starts_at="2026-08-09T10:00:00Z",
                           ends_at="2026-08-09T12:00:00Z")
        sh3 = create_shift(site["id"], volunteer["id"], d3["id"],
                           role_on_shift="SERVER",
                           starts_at="2026-08-10T10:00:00Z",
                           ends_at="2026-08-10T12:00:00Z")

        vol_headers = make_volunteer_headers(volunteer["id"])

        # Earn 1.0 hour on D1.
        set_clock("2026-08-08T10:30:00Z")
        get_success_data(api.check_in_shift(sh1["id"], vol_headers))
        set_clock("2026-08-08T11:30:00Z")
        get_success_data(api.complete_shift(sh1["id"], {}, MANAGER))

        # Penalty-cancel the D2 shift one second before its start: inside any
        # positive lockout margin, so the 2.0-hour penalty applies and the
        # balance floors at 0 (max(0, 1.0 - 2.0)).
        set_clock("2026-08-09T09:59:59Z")
        get_success_data(api.cancel_shift(sh2["id"], {"apply_penalty": True}, MANAGER))

        volunteer = get_success_data(api.get_volunteer(volunteer["id"], MANAGER))
        assert float(volunteer["hours_balance"]) == pytest.approx(0.0, abs=1e-9), (
            f"penalty must floor the balance at 0, got {volunteer['hours_balance']}"
        )

        # Earn 2.0 hours on D3.
        set_clock("2026-08-10T10:30:00Z")
        get_success_data(api.check_in_shift(sh3["id"], vol_headers))
        set_clock("2026-08-10T12:30:00Z")
        get_success_data(api.complete_shift(sh3["id"], {}, MANAGER))

        volunteer = get_success_data(api.get_volunteer(volunteer["id"], MANAGER))
        assert float(volunteer["hours_balance"]) == pytest.approx(2.0, abs=1e-9), (
            f"1.0 earned, floored penalty, then +2.0 must yield 2.0, "
            f"got {volunteer['hours_balance']}"
        )
