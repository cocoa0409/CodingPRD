"""Alert-tier day bands, the clock-driven expiry sweep, and lapse cascades."""
from test_helpers import (
    ApiErrorId,
    create_active_license,
    create_employee,
    create_license_type,
    create_pe_license_type,
    create_role_requirement,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OFFICER = TEST_USERS["officer_headers"]


def _pe_license(email, expires_on="2026-12-31"):
    lt = create_pe_license_type()
    emp = create_employee(full_name="Eric Engineer", work_email=email,
                          role_code="FIELD_ENGINEER")
    lic = create_active_license(emp["id"], lt["id"], license_number=None,
                                expires_on=expires_on, source="MANUAL_UPLOAD")
    return lt, emp, lic


class TestAlertTierBoundaries:
    def test_alert_tier_exactly_thirty_days_boundary(self, api):
        """PRD §3.5: "thirty-one through sixty reads `T60`; one through thirty
        reads `T30`"; "Boundaries fall into the nearer tier, so exactly ninety
        days is `T90`, exactly sixty is `T60`, and exactly thirty is `T30`."

        Design: Difficulty/boundary_precision_check/alert_tier_exactly_thirty_days_boundary
        """
        lt, emp, lic = _pe_license("eric.tier@example.com")
        set_clock("2026-11-30T00:00:00Z")  # 31 days until 2026-12-31
        tier31 = get_success_data(api.get_license(lic["id"], OFFICER))["alert_tier"]
        assert tier31 == "T60"

        set_clock("2026-12-01T00:00:00Z")  # exactly 30 days
        tier30 = get_success_data(api.get_license(lic["id"], OFFICER))["alert_tier"]
        assert tier30 == "T30"

    def test_alert_tier_thirty_one_days_stays_t60(self, api):
        """PRD §3.5: "thirty-one through sixty reads `T60`; one through thirty
        reads `T30`".

        Design: Difficulty/boundary_precision_check/alert_tier_exactly_thirty_days_boundary
        """
        lt, emp, lic = _pe_license("eric.tier31@example.com")
        set_clock("2026-11-30T00:00:00Z")  # 31 days until 2026-12-31
        assert get_success_data(api.get_license(lic["id"], OFFICER))["alert_tier"] == "T60"

    def test_alert_tier_t90_and_none_boundary(self, api):
        """PRD §3.5: "ninety-one or more days out reads `NONE`; sixty-one
        through ninety days reads `T90`"; "exactly ninety days is `T90`".

        Design: Corner/calculations/alert_tier_t90_and_none_boundary
        """
        lt, emp, lic = _pe_license("eric.t90@example.com")
        set_clock("2026-10-01T00:00:00Z")  # 91 days until 2026-12-31
        tier91 = get_success_data(api.get_license(lic["id"], OFFICER))["alert_tier"]
        assert tier91 == "NONE"

        set_clock("2026-10-02T00:00:00Z")  # exactly 90 days
        tier90 = get_success_data(api.get_license(lic["id"], OFFICER))["alert_tier"]
        assert tier90 == "T90"


class TestExpirySweep:
    def test_expiry_sweep_strictly_greater_than_boundary(self, api):
        """PRD §3.5: "An `ACTIVE` license whose `expires_on` now falls strictly
        before the current date drops to `EXPIRED` and takes `alert_tier` of
        `AT_EXPIRY`."

        Design: Corner/state_machines/expiry_sweep_strictly_greater_than_boundary
        """
        lt, emp, lic = _pe_license("eric.sweep@example.com")
        set_clock("2026-12-31T00:00:00Z")  # equal: not strictly before
        st_eq = get_success_data(api.get_license(lic["id"], OFFICER))["status"]
        assert st_eq == "ACTIVE"

        set_clock("2027-01-01T00:00:00Z")
        st_gt = get_success_data(api.get_license(lic["id"], OFFICER))["status"]
        assert st_gt == "EXPIRED"

    def test_clock_sweep_lapse_cascades_to_employee(self, api):
        """PRD §3.5: "An `EXPIRED` license whose grace has fully run out — the
        current date strictly after `expires_on` plus the type's
        `grace_period_days` — drops to `LAPSED`, again at `AT_EXPIRY`."
        "the moment the license reaches `LAPSED` (or `REVOKED`), the
        `LICENSE_LAPSED` reason engages for every mandatory matrix row the
        license covers."

        Design: Difficulty/transitive_cascade/clock_sweep_lapse_cascades_to_employee
        """
        lt = create_license_type()  # grace 45d
        create_role_requirement(lt["id"])
        emp = create_employee(work_email="nora.sweep@example.com")
        lic = create_active_license(emp["id"], lt["id"], license_number="RN-8002",
                                    expires_on="2026-12-31")

        # expires 2026-12-31 + 45d grace = 2027-02-14; 2027-02-15 is strictly after.
        set_clock("2027-02-15T00:00:00Z")
        lic_after = get_success_data(api.get_license(lic["id"], OFFICER))
        assert lic_after["status"] == "LAPSED"
        assert lic_after["alert_tier"] == "AT_EXPIRY"

        emp_after = get_success_data(api.get_employee(emp["id"], OFFICER))
        assert emp_after["work_authorization"] == "RESTRICTED"
        assert emp_after["restriction_reason"] == "LICENSE_LAPSED"

    def test_expired_inside_grace_is_not_a_restriction_reason(self, api):
        """PRD §3.5: "An `EXPIRED` license still inside its grace period is not,
        by itself, a restriction reason — the holder keeps working while renewal
        is arranged."

        Design: Difficulty/transitive_cascade/clock_sweep_lapse_cascades_to_employee
        """
        lt = create_license_type()  # grace 45d
        create_role_requirement(lt["id"])
        emp = create_employee(work_email="nora.grace@example.com")
        lic = create_active_license(emp["id"], lt["id"], license_number="RN-8003",
                                    expires_on="2026-12-31")
        set_clock("2027-01-05T00:00:00Z")  # EXPIRED, inside grace
        lic_after = get_success_data(api.get_license(lic["id"], OFFICER))
        assert lic_after["status"] == "EXPIRED"

        emp_after = get_success_data(api.get_employee(emp["id"], OFFICER))
        assert emp_after["work_authorization"] == "AUTHORIZED"
        assert emp_after["restriction_reason"] is None


class TestLicenseCyclicReinstatement:
    def _setup_lapsed_license(self, api, email):
        lt = create_license_type()  # CE 30.0, grace 45d
        create_role_requirement(lt["id"])
        emp = create_employee(work_email=email)
        lic = create_active_license(emp["id"], lt["id"], license_number="RN-2001",
                                    expires_on="2026-12-31")
        # 30.0 validated cycle hours: 10.25->10.5, 10.25->10.5, 9.0->9.0.
        from test_helpers import create_validated_ce_activity
        for hours in (10.25, 10.25, 9.0):
            create_validated_ce_activity(lic["id"], hours=hours,
                                         completed_on="2026-06-01")
        return lt, emp, lic

    def test_license_lapses_then_reinstates_with_reanchored_cycle(self, api):
        """PRD §3.3: "On an `EXPIRED` or `LAPSED` license, a `VERIFIED` event is
        reinstatement: the license returns to `ACTIVE`, `expires_on` becomes
        `verified_on` plus 365 days, and `ce_cycle_anchor_on` is re-set to
        `verified_on` so the cycle CE window restarts from the new anchor".

        Design: Difficulty/non_linear_state_machine/license_cyclic_reinstatement_loop
        """
        lt, emp, lic = self._setup_lapsed_license(api, "nora.cycle@example.com")

        set_clock("2027-01-05T00:00:00Z")
        assert get_success_data(api.get_license(lic["id"], OFFICER))["status"] == "EXPIRED"

        set_clock("2027-03-01T00:00:00Z")  # past 2026-12-31 + 45d = 2027-02-14
        assert get_success_data(api.get_license(lic["id"], OFFICER))["status"] == "LAPSED"
        emp_mid = get_success_data(api.get_employee(emp["id"], OFFICER))
        assert emp_mid["work_authorization"] == "RESTRICTED"
        assert emp_mid["restriction_reason"] == "LICENSE_LAPSED"

        data = validate_success(api.verify_license(lic["id"], {
            "verified_on": "2027-03-01", "source": "STATE_BOARD_API",
            "outcome": "VERIFIED",
        }, OFFICER), 200)
        assert data["status"] == "ACTIVE"
        assert data["expires_on"] == "2028-02-29"  # 2027-03-01 + 365 days
        assert data["ce_cycle_anchor_on"] == "2027-03-01"
        assert data["cycle_ce_hours_validated"] == 0.0  # window restarted

    def test_reinstatement_clears_lapse_restriction(self, api):
        """PRD §3.3: "the holder's work authorization is re-derived, which can
        clear `MISSING_LICENSE` on a first verification, `VERIFICATION_OVERDUE`
        on a cadence verification, or `LICENSE_LAPSED` on a reinstatement."

        Design: Difficulty/non_linear_state_machine/license_cyclic_reinstatement_loop
        """
        lt, emp, lic = self._setup_lapsed_license(api, "nora.cycle2@example.com")
        set_clock("2027-03-01T00:00:00Z")
        validate_success(api.verify_license(lic["id"], {
            "verified_on": "2027-03-01", "source": "STATE_BOARD_API",
            "outcome": "VERIFIED",
        }, OFFICER), 200)
        emp_after = get_success_data(api.get_employee(emp["id"], OFFICER))
        assert emp_after["work_authorization"] == "AUTHORIZED"
        assert emp_after["restriction_reason"] is None


class TestRevokedTerminalLockdown:
    def test_revoked_license_verify_rejected(self, api):
        """PRD §3.3: "Attempting to verify a license in `SUSPENDED` or `REVOKED`
        has no originating transition and fails with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/revoked_license_verify_rejected_terminal_lockdown
        """
        from test_helpers import create_disciplinary_event, confirm_disciplinary_event
        lt = create_license_type()
        emp = create_employee(work_email="nora.rev@example.com")
        lic = create_active_license(emp["id"], lt["id"], license_number="RN-9103")
        event = create_disciplinary_event(
            lic["id"], headers=None, board_case_number="B-31",
            event_type="REVOCATION", effective_on="2026-08-01")
        confirm_disciplinary_event(event["id"])

        resp = api.verify_license(lic["id"], {
            "verified_on": "2026-08-01", "source": "STATE_BOARD_API",
            "outcome": "VERIFIED",
        }, OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_success_data(api.get_license(lic["id"], OFFICER))
        assert after["status"] == "REVOKED"
