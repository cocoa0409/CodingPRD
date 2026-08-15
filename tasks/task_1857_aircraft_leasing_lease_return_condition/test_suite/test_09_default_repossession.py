"""Default & repossession workflow: declaration cascade, cure revert,
cure-deadline clock gating, and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_lease,
    create_default_case,
    make_credit_officer_headers,
    make_legal_approver_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["lessor_admin_headers"]


class TestDefaultDeclaration:
    def test_declaration_cascades_lease_to_defaulted(self, api):
        """PRD §3.8: "The system stamps `declared_at` from the logical clock,
        computes `cure_deadline` as `declared_at` plus the cure period in
        days, records the declaring officer's `X-User-ID` as `declared_by`,
        and opens the case in `DECLARED`. Declaration cascades the lease from
        `ACTIVE` — or from `RETURN_INITIATED`, if a return was already under
        way — into `DEFAULTED`."

        Design: Corner/state_machines/cure_reverts_default_cycle
        """
        lease, _aircraft, _lessee = create_active_lease()
        case = create_default_case(lease["id"], declared_by="cred_1",
                                   reason="rent arrears", cure_period_days=30)
        assert case["status"] == "DECLARED"
        assert case["declared_by"] == "cred_1"
        # Default clock is 2026-08-01T00:00:00Z; +30 days = 2026-08-31.
        assert case["declared_at"] == "2026-08-01T00:00:00Z"
        assert case["cure_deadline"] == "2026-08-31T00:00:00Z", (
            f"cure_deadline must be declared_at + cure_period_days, got {case['cure_deadline']!r}")

        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["status"] == "DEFAULTED"

    def test_second_open_default_case_rejected(self, api):
        """PRD §3.8: "A lease may carry at most one open default case: if a
        case in `DECLARED` or `REPOSSESSION_AUTHORIZED` already exists, a
        further declaration is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cure_reverts_default_cycle
        """
        lease, _aircraft, _lessee = create_active_lease()
        create_default_case(lease["id"], declared_by="cred_1")
        resp = api.create_default_case(
            lease["id"], {"reason": "second default", "cure_period_days": 10},
            make_credit_officer_headers("cred_1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestCure:
    def test_cure_reverts_default_cycle(self, api):
        """PRD §3.8: "If the lessee cures, the same credit desk marks the
        case `CURED`, and the lease compensates back `DEFAULTED → ACTIVE`."

        Design: Corner/state_machines/cure_reverts_default_cycle
        """
        lease, aircraft, _lessee = create_active_lease()
        case = create_default_case(lease["id"], declared_by="cred_1",
                                   reason="rent arrears", cure_period_days=30)

        aircraft_mid = validate_success(api.get_aircraft(aircraft["id"], ADMIN))
        assert aircraft_mid["status"] == "ON_LEASE", (
            "declaration alone never touches the aircraft")

        cured = validate_success(
            api.cure_default_case(case["id"], make_credit_officer_headers("cred_1")))
        assert cured["status"] == "CURED"

        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["status"] == "ACTIVE", (
            f"cure reverts the lease to ACTIVE, got {lease_now['status']!r}")
        aircraft_now = validate_success(api.get_aircraft(aircraft["id"], ADMIN))
        assert aircraft_now["status"] == "ON_LEASE"


class TestAuthorizeRepossession:
    def test_authorize_before_cure_deadline_rejected_then_allowed(self, api):
        """PRD §3.8: "If not, a `LegalApprover` authorizes repossession — but
        only once the logical clock reads strictly after `cure_deadline` (at
        or before the deadline the attempt is `ERR_CURE_DEADLINE_NOT_PASSED`),
        and only when the authorizer's `X-User-ID` differs from
        `declared_by`, since the officer who declared the default may not
        also authorize its repossession (`ERR_SOD_VIOLATION`)."

        Design: Corner/state_machines/authorize_repossession_before_cure_deadline_returns_error
        """
        lease, _aircraft, _lessee = create_active_lease()
        # Declared at the default clock 2026-08-01T00:00:00Z, cure 30 days.
        case = create_default_case(lease["id"], declared_by="cred_1",
                                   reason="reserve shortfall", cure_period_days=30)

        # Clock still at declaration time: at the deadline's start, not past it.
        resp = api.authorize_repossession(case["id"], make_legal_approver_headers("legal_1"))
        validate_error(resp, ApiErrorId.ERR_CURE_DEADLINE_NOT_PASSED, expected_status=409)

        # 2026-09-01 is strictly after the 2026-08-31 deadline.
        validate_success(api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, ADMIN))
        authorized = validate_success(
            api.authorize_repossession(case["id"], make_legal_approver_headers("legal_1")))
        assert authorized["status"] == "REPOSSESSION_AUTHORIZED"

    def test_declarer_cannot_authorize_own_default(self, api):
        """PRD §3.8: "and only when the authorizer's `X-User-ID` differs from
        `declared_by`, since the officer who declared the default may not
        also authorize its repossession (`ERR_SOD_VIOLATION`). Authorization
        moves the case to `REPOSSESSION_AUTHORIZED`."

        Design: Corner/validations/default_sod_declarer_cannot_authorize
        """
        lease, _aircraft, _lessee = create_active_lease()
        case = create_default_case(lease["id"], declared_by="cred_1",
                                   reason="rent arrears", cure_period_days=30)
        validate_success(api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, ADMIN))

        # Even under the LegalApprover role, the declarer's X-User-ID is
        # barred from authorizing.
        resp = api.authorize_repossession(case["id"], make_legal_approver_headers("cred_1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=409)

        authorized = validate_success(
            api.authorize_repossession(case["id"], make_legal_approver_headers("legal_9")))
        assert authorized["status"] == "REPOSSESSION_AUTHORIZED"
