"""License posture: the suspend/reinstate cascades and their immediacy."""
from test_helpers import (
    TEST_USERS,
    get_order,
    get_vial,
    set_clock,
    setup_f18_calibrated_vial,
    validate_error,
    validate_success,
    create_isotope,
    create_license,
)

ADMIN = TEST_USERS["admin_headers"]


class TestSuspendCascade:
    """Depth-2 chain from license suspension: hop one suspends the license's
    ACTIVE authorized users; hop two places those users' open orders ON_HOLD."""

    def test_suspend_cascades_to_users_and_orders(self, api):
        """PRD §3.1: "When a `DepartmentAdmin` suspends a license ... the cascade
        runs in two hops. Hop one: every authorized user whose `license_id`
        points at this license and whose status is `ACTIVE` becomes `SUSPENDED`.
        Hop two: every dose order prescribed by one of those just-suspended
        users whose status is `ORDERED` or `DOSE_PREPARED` moves to `ON_HOLD`,
        with `hold_reason` set to `LICENSE_SUSPENDED` and `hold_previous_status`
        recording the status it occupied. Vials are deliberately not quarantined
        by this cascade — unlike the spill cascade of §3.6 — because a licensing
        problem does not make the physical dose unsafe."

        Design: Difficulty/transitive_cascade/license_suspend_cascade_depth2
        """
        ctx = setup_f18_calibrated_vial(measured_activity_mbq=220)
        validate_success(api.suspend_license(ctx["license"]["id"], ADMIN), 200)

        au = validate_success(api.get_authorized_user(ctx["authorized_user"]["id"], ADMIN), 200)
        assert au["status"] == "SUSPENDED", "hop 1: user suspended"

        order = get_order(ctx["order"]["id"])
        assert order["status"] == "ON_HOLD", "hop 2: open order held"
        assert order["hold_reason"] == "LICENSE_SUSPENDED"
        assert order["hold_previous_status"] == "DOSE_PREPARED"

        vial = get_vial(ctx["vial"]["id"])
        assert vial["status"] == "CALIBRATED", "license cascade never quarantines"

    def test_reinstate_restores_users_and_orders(self, api):
        """PRD §3.1: "Reinstatement is the mirror image: only a `SUSPENDED`
        license may be reinstated (otherwise `ERR_INVALID_STATE`); suspended
        users return to `ACTIVE`, and every order sitting `ON_HOLD` with
        `hold_reason` of `LICENSE_SUSPENDED` returns to its recorded
        `hold_previous_status` with `hold_reason` cleared."

        Design: Difficulty/transitive_cascade/license_suspend_cascade_depth2
        """
        ctx = setup_f18_calibrated_vial(measured_activity_mbq=220)
        validate_success(api.suspend_license(ctx["license"]["id"], ADMIN), 200)
        reinstated = validate_success(api.reinstate_license(ctx["license"]["id"], ADMIN), 200)
        assert reinstated["status"] == "ACTIVE"

        au = validate_success(api.get_authorized_user(ctx["authorized_user"]["id"], ADMIN), 200)
        assert au["status"] == "ACTIVE"

        order = get_order(ctx["order"]["id"])
        assert order["status"] == "DOSE_PREPARED", "restore recovers hold_previous_status"
        assert order["hold_reason"] is None

        vial = get_vial(ctx["vial"]["id"])
        assert vial["status"] == "CALIBRATED"


class TestSuspendLegality:
    def test_suspend_requires_active_state(self, api):
        """PRD §3.1: "When a `DepartmentAdmin` suspends a license — only an
        `ACTIVE` license may be suspended, otherwise the call is rejected with
        `ERR_INVALID_STATE`..."

        Design: Corner/state_machines/license_suspend_requires_active_state
        """
        set_clock("2026-08-01T08:00:00Z")
        iso = create_isotope()
        lic = create_license(iso["id"])
        validate_success(api.suspend_license(lic["id"], ADMIN), 200)

        res = api.suspend_license(lic["id"], ADMIN)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


class TestImmediateConsistency:
    def test_suspend_effects_visible_immediately(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field." and PRD §3.1: "When a `DepartmentAdmin` suspends a license ...
        the cascade runs in two hops. ... Hop two: every dose order prescribed
        by one of those just-suspended users whose status is `ORDERED` or
        `DOSE_PREPARED` moves to `ON_HOLD`, with `hold_reason` set to
        `LICENSE_SUSPENDED`..."

        The suspend response itself carries the SUSPENDED license and the very
        next read of a cascaded order shows ON_HOLD — the cascade is part of
        the suspend operation, not a delayed repair.

        Design: Corner/consistency_model/immediate_visibility_after_suspend
        """
        ctx = setup_f18_calibrated_vial(measured_activity_mbq=220)
        license_after = validate_success(api.suspend_license(ctx["license"]["id"], ADMIN), 200)
        assert license_after["status"] == "SUSPENDED", "mutation visible in the same response"

        order = get_order(ctx["order"]["id"])
        assert order["status"] == "ON_HOLD", "cascaded state visible on the immediate read"
