"""Registration lifecycle, surety bonds, and records retention (PRD §3.1, §3.9)."""
from test_helpers import (
    ApiErrorId,
    create_and_activate_bond,
    create_bond_payload,
    create_event,
    create_jurisdiction,
    create_pending_registration,
    create_rated_event,
    create_registrant,
    new_admin_headers,
    new_analyst_headers,
    setup_active_registration,
    validate_error,
    validate_success,
)


class TestBondGatedActivation:
    def test_bond_insufficient_on_activation_rejected(self, api):
        """PRD §3.1: "Activating a `PENDING` registration requires coverage at
        least equal to the requirement, failing with `ERR_BOND_INSUFFICIENT`
        otherwise" and "if there is no filed history the requirement is a
        floor of 1,000,000 cents (ten thousand dollars)".

        Design: Corner/validations/bond_insufficient_on_activation_rejected
        """
        jur = create_jurisdiction()
        rgt = create_registrant()
        rgn = create_pending_registration(rgt["id"], jur["id"])
        create_and_activate_bond(rgn["id"], principal_amount_cents=500000)
        resp = api.activate_registration(rgn["id"], new_admin_headers())
        validate_error(resp, ApiErrorId.ERR_BOND_INSUFFICIENT)

    def test_bond_window_elapsed_rejected(self, api):
        """PRD §3.1: "Activating a bond requires that its window not be fully
        elapsed — its `effective_to` must not lie before the current logical
        date, or the attempt fails with `ERR_BOND_WINDOW_ELAPSED`".

        Design: Corner/validations/bond_window_elapsed_rejected
        """
        jur = create_jurisdiction()
        rgt = create_registrant()
        rgn = create_pending_registration(rgt["id"], jur["id"])
        bond = validate_success(api.create_bond(
            create_bond_payload(registration_id=rgn["id"],
                                effective_from="2026-01-01T00:00:00Z",
                                effective_to="2026-06-01T00:00:00Z"),
            new_admin_headers()), expected_status=201)
        # Logical clock is 2026-08-01, after the bond's 2026-06-01 end.
        resp = api.activate_bond(bond["id"], new_admin_headers())
        validate_error(resp, ApiErrorId.ERR_BOND_WINDOW_ELAPSED)

    def test_bond_expiry_flips_registration_bond_deficient(self, api):
        """PRD §3.1: "the clock sweep moves an `ACTIVE` bond whose
        `effective_to` has passed to `EXPIRED`; either transition recomputes
        coverage, and if coverage has fallen below the requirement the
        registration flips to `BOND_DEFICIENT`."

        Design: Corner/state_machines/bond_expiry_flips_registration_bond_deficient
        """
        ctx = setup_active_registration(
            create_rate=False,
            bond_overrides={"effective_to": "2026-08-20T00:00:00Z"})
        rgn, bnd = ctx["registration"], ctx["bond"]
        admin = new_admin_headers()
        validate_success(api.set_clock("2026-08-21T00:00:00Z", admin))

        bond = validate_success(api.get_bond(bnd["id"], admin))
        assert bond["status"] == "EXPIRED"

        status = validate_success(api.get_bond_status(rgn["id"], admin))
        assert status["bond_coverage_cents"] == 0
        assert status["deficient"] is True

        registration = validate_success(api.get_registration(rgn["id"], admin))
        assert registration["status"] == "BOND_DEFICIENT"


class TestRevocation:
    def test_terminal_lockdown_revoked_registration_rejected(self, api):
        """PRD §3.1: "Revocation is terminal and guarded."
        PRD §2.10: "(5) state legality of the requested transition, including
        terminal-state lockdown, yielding `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/terminal_lockdown_revoked_registration_rejected
        """
        ctx = setup_active_registration(create_rate=False)
        rgn = ctx["registration"]
        admin = new_admin_headers()
        revoked = validate_success(api.revoke_registration(rgn["id"], admin))
        assert revoked["status"] == "REVOKED"

        resp = api.activate_registration(rgn["id"], admin)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_revoke_with_open_liability_rejected(self, api):
        """PRD §3.1: "Revoking a registration requires that no return of the
        registration sit in `DRAFT` or `SUBMITTED` and that no `FILED` return
        remain `AWAITING_PAYMENT`, failing with
        `ERR_REGISTRATION_HAS_OPEN_LIABILITY` otherwise".

        Design: Corner/validations/revoke_with_open_liability_rejected
        """
        ctx = setup_active_registration()
        # Rating an event auto-creates a DRAFT return for the period.
        create_rated_event(ctx["registration"], ctx["jurisdiction"],
                           ctx["product_class"], quantity_units=10)
        resp = api.revoke_registration(
            ctx["registration"]["id"], new_admin_headers())
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_HAS_OPEN_LIABILITY)


class TestRetention:
    def test_retention_purge_too_early_rejected(self, api):
        """PRD §3.9: "Attempting a purge before the anchor has aged seven
        years is rejected with `ERR_RETENTION_NOT_ELAPSED`".

        Design: Corner/validations/retention_purge_too_early_rejected
        """
        ctx = setup_active_registration()
        ev = create_event(ctx["registration"], ctx["jurisdiction"],
                          ctx["product_class"], quantity_units=10)
        validate_success(api.void_event(ev["id"], new_analyst_headers()))
        # Clock is still 2026-08-01; the period's retention anchor + 7 years
        # is far in the future.
        resp = api.purge_expired_records(
            ctx["registration"]["id"], "2026-08", new_admin_headers())
        validate_error(resp, ApiErrorId.ERR_RETENTION_NOT_ELAPSED)


class TestRegistrationUniqueness:
    def test_duplicate_registration_rejected(self, api):
        """PRD §3.1: "At most one non-`REVOKED` registration may exist for a
        registrant–jurisdiction pair; a conflicting creation is rejected with
        `ERR_DUPLICATE_REGISTRATION`."

        Design: Corner/validations/duplicate_registration_rejected
        """
        jur = create_jurisdiction()
        rgt = create_registrant()
        create_pending_registration(rgt["id"], jur["id"],
                                    deposit_method="SAFE_HARBOR")
        resp = api.create_registration(
            {"registrant_id": rgt["id"], "jurisdiction_id": jur["id"],
             "deposit_method": "ACTUAL"},
            new_admin_headers())
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REGISTRATION)
