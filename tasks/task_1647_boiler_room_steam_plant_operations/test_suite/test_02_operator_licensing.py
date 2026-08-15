"""Operator licensing: initial state, expiry windows, renewal cycle, and the
license gate on boiler operations."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_boiler,
    create_operator,
    create_operator_payload,
    create_plant,
    get_boiler,
    get_operator,
    make_operator_headers,
    record_passed_annual,
    run_ops,
    set_clock,
    validate_error,
    validate_success,
)


class TestOperatorInitialState:
    def test_operator_initial_state_is_active(self, api, plant_manager_headers):
        """PRD §3.1: "Enrollment starts every operator at `license_status`
        `ACTIVE`."

        Design: Corner/state_machines/operator_initial_state_is_active
        """
        plant = create_plant(name="Init Plant")
        resp = api.create_operator(
            plant["id"],
            create_operator_payload(
                full_name="Op Ini", license_class="CLASS_2", license_state="TX"
            ),
            plant_manager_headers,
        )
        operator = validate_success(resp, expected_status=201)
        assert operator["license_status"] == "ACTIVE"


class TestLicenseExpiryCycle:
    def test_expiring_window_then_renewal_returns_active(
        self, api, plant_manager_headers
    ):
        """PRD §3.2: "When the time remaining until expiry is sixty days or
        less — 5,184,000 seconds, with exactly sixty days remaining qualifying
        — the status becomes `EXPIRING`."
        PRD §3.2: "A `PlantManager` restores an `EXPIRING` or `EXPIRED`
        operator by renewing the license, supplying a `new_license_expires_on`
        that must lie strictly after the plant clock; renewal writes the new
        `license_expires_on` and returns the operator to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/operator_license_cyclic_renewal
        """
        set_clock("2026-08-01T00:00:00Z")
        plant = create_plant(name="Cyc Plant")
        operator = create_operator(
            plant["id"], full_name="Op Cyc",
            license_expires_on="2026-09-15T00:00:00Z",  # 45 days out
        )
        run_ops(plant["id"])
        after_ops = get_operator(plant["id"], operator["id"])
        assert after_ops["license_status"] == "EXPIRING", (
            "45 days remaining is inside the 60-day EXPIRING window"
        )

        resp = api.renew_license(
            plant["id"], operator["id"], "2027-08-01T00:00:00Z",
            plant_manager_headers,
        )
        renewed = validate_success(resp, expected_status=200)
        assert renewed["license_status"] == "ACTIVE"
        assert renewed["license_expires_on"].startswith("2027-08-01")

        # Cyclic return persists on read-back.
        reread = get_operator(plant["id"], operator["id"])
        assert reread["license_status"] == "ACTIVE"

    def test_expiring_boundary_exactly_sixty_days(
        self, api, plant_manager_headers
    ):
        """PRD §3.2: "When the time remaining until expiry is sixty days or
        less — 5,184,000 seconds, with exactly sixty days remaining qualifying
        — the status becomes `EXPIRING`." An expiry 60 days plus one second
        out is beyond the window and stays ACTIVE.

        Design: Difficulty/non_linear_state_machine/operator_license_cyclic_renewal
        """
        set_clock("2026-08-01T00:00:00Z")
        plant = create_plant(name="Cyc Boundary Plant")
        at_boundary = create_operator(
            plant["id"], full_name="Boundary Op",
            license_expires_on="2026-09-30T00:00:00Z",  # exactly 60 days
        )
        past_boundary = create_operator(
            plant["id"], full_name="Safe Op",
            license_expires_on="2026-09-30T00:00:01Z",  # 60 days + 1 second
        )
        run_ops(plant["id"])
        assert get_operator(plant["id"], at_boundary["id"])["license_status"] == (
            "EXPIRING"
        ), "exactly sixty days remaining qualifies for EXPIRING (inclusive)"
        assert get_operator(plant["id"], past_boundary["id"])["license_status"] == (
            "ACTIVE"
        ), "sixty days plus one second is outside the EXPIRING window"


class TestLicenseGateOnBoilerOps:
    def test_warm_rejected_when_operator_license_expired(
        self, api, plant_manager_headers
    ):
        """PRD §3.2: "An `EXPIRED` operator can no longer perform
        state-changing actions — every license-gated request fails with
        `ERR_OPERATOR_LICENSE_INVALID`".

        Design: Difficulty/cross_entity_state_dependency/boiler_warm_requires_operator_license_active
        """
        set_clock("2026-08-01T00:00:00Z")
        plant = create_plant(name="XD1 Plant")
        boiler = create_boiler(plant["id"], tag="B-X1")
        operator = create_operator(
            plant["id"], full_name="Op Expired",
            license_expires_on="2026-01-01T00:00:00Z",
        )
        # Keep the boiler certificate VALID through the checkpoint (a PASSED
        # annual inspection with a far-future expiry) so the license gate is
        # the only failing check when warm is attempted.
        record_passed_annual(
            plant["id"], boiler["id"],
            certificate_expires_on="2027-06-01T00:00:00Z",
        )
        # Move the clock one second past the licence expiry used above and
        # checkpoint, so the license flips EXPIRED (strict less-than rule).
        set_clock("2026-08-01T00:00:01Z")
        run_ops(plant["id"])
        assert get_operator(plant["id"], operator["id"])["license_status"] == "EXPIRED"

        resp = api.warm_boiler(
            plant["id"], boiler["id"], make_operator_headers(operator["id"])
        )
        validate_error(resp, ApiErrorId.ERR_OPERATOR_LICENSE_INVALID)
        assert get_boiler(plant["id"], boiler["id"])["ops_status"] == "STANDBY"

    def test_warm_rejected_when_operator_license_revoked(
        self, api, plant_manager_headers
    ):
        """PRD §2.7: "every operator-initiated state transition requires the
        calling operator's `license_status` to be `ACTIVE`, and certain
        transitions additionally require an adequate `license_class`;
        violations are rejected with `ERR_OPERATOR_LICENSE_INVALID` (422)."
        PRD §3.2: "Revocation, also a `PlantManager` act, moves an `ACTIVE` or
        `EXPIRED` operator to the terminal `REVOKED` state, after which they
        may no longer act at all."

        Design: Difficulty/cross_entity_state_dependency/boiler_warm_requires_operator_license_active
        """
        plant = create_plant(name="XD1b Plant")
        boiler = create_boiler(plant["id"], tag="B-XR")
        operator = create_operator(plant["id"], full_name="Op Revoked")
        resp = api.revoke_license(plant["id"], operator["id"], plant_manager_headers)
        revoked = validate_success(resp, expected_status=200)
        assert revoked["license_status"] == "REVOKED"

        resp = api.warm_boiler(
            plant["id"], boiler["id"], make_operator_headers(operator["id"])
        )
        validate_error(resp, ApiErrorId.ERR_OPERATOR_LICENSE_INVALID)
        assert get_boiler(plant["id"], boiler["id"])["ops_status"] == "STANDBY"


class TestLicenseAdministrationRbac:
    def test_operator_cannot_renew_own_license(self, api, plant_manager_headers):
        """PRD §4: renew-license is listed under Authorized Role(s)
        `PlantManager` only. PRD §2.7: "Authorization — the role is permitted
        for the endpoint per the RBAC matrix; otherwise `ERR_UNAUTHORIZED`
        (403)."

        Design: Corner/rbac/operator_cannot_renew_own_license
        """
        plant = create_plant(name="RBAC2 Plant")
        operator = create_operator(plant["id"], full_name="Op Self")
        resp = api.renew_license(
            plant["id"], operator["id"], "2027-08-01T00:00:00Z",
            make_operator_headers(operator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
