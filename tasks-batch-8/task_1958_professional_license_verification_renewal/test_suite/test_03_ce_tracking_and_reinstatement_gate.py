"""Continuing-education logging, half-hour rounding, tallies, and the CE gate."""
from test_helpers import (
    ApiErrorId,
    create_active_license,
    create_ce_activity,
    create_employee,
    create_license,
    create_license_type,
    create_validated_ce_activity,
    get_success_data,
    set_clock,
    setup_license_with_cycle_hours,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OFFICER = TEST_USERS["officer_headers"]


def _rn_type_and_employee(api, email, expires_on="2026-12-31"):
    lt = create_license_type()
    emp = create_employee(work_email=email)
    return lt, emp


class TestRoundingOrder:
    def test_two_point_seven_four_activities_round_individually(self, api):
        """PRD §3.4: "The ordering is contractual — two activities of 0.74 hours
        each round to 0.5 apiece and therefore tally 1.0, never 1.5."

        Design: Difficulty/combinatorial_formula/ce_per_activity_rounding_order_pinned
        """
        lt, emp = _rn_type_and_employee(api, "nora.round@example.com")
        lic = create_active_license(emp["id"], lt["id"], license_number="RN-6001",
                                    expires_on="2027-06-30")
        ce1 = create_ce_activity(lic["id"], activity_title="Refresher A",
                                 hours=0.74, completed_on="2026-03-01")
        ce2 = create_ce_activity(lic["id"], activity_title="Refresher B",
                                 hours=0.74, completed_on="2026-03-01")
        assert ce1["rounded_hours"] == 0.5, (
            f"round_half_up(0.74 * 2) / 2 == 0.5, got {ce1['rounded_hours']}"
        )
        assert ce2["rounded_hours"] == 0.5

    def test_validated_pair_tallies_one_point_zero(self, api):
        """PRD §3.4: "the raw hours are rounded half up to the nearest half hour,
        per activity, before any summation ever happens. The ordering is
        contractual — two activities of 0.74 hours each round to 0.5 apiece and
        therefore tally 1.0, never 1.5."

        Design: Difficulty/combinatorial_formula/ce_per_activity_rounding_order_pinned
        """
        lt, emp = _rn_type_and_employee(api, "nora.round2@example.com")
        lic = create_active_license(emp["id"], lt["id"], license_number="RN-6002",
                                    expires_on="2027-06-30")
        create_validated_ce_activity(lic["id"], activity_title="Refresher A",
                                     hours=0.74, completed_on="2026-03-01")
        create_validated_ce_activity(lic["id"], activity_title="Refresher B",
                                     hours=0.74, completed_on="2026-03-01")
        data = get_success_data(api.get_license(lic["id"], OFFICER))
        assert data["cycle_ce_hours_validated"] == 1.0, (
            "per-activity rounding then sum; sum-then-round would give 1.5"
        )


class TestDualWindowProgress:
    def test_cycle_and_rolling_tallies_diverge(self, api):
        """PRD §3.4: "`cycle_ce_hours_validated` covers the cycle window: from
        `ce_cycle_anchor_on` through the earlier of the anchor plus the type's
        `cycle_length_months` months and the license's `expires_on`, inclusive
        at both ends". "`rolling_ce_hours_validated` covers the regulator's
        window: the 365-day span ending on the logical current date — from 364
        days before it through the current date itself, inclusive at both ends."

        Design: Difficulty/dual_variant_calc/ce_progress_reported_vs_required_diverge
        """
        lt = create_license_type()
        create_role = api.create_role_requirement(
            {"role_code": "STAFF_NURSE", "license_type_id": lt["id"],
             "state_code": "CA", "is_required": True}, TEST_USERS["admin_headers"])
        assert create_role.status_code == 201
        emp = create_employee(full_name="Nora Nurse", work_email="nora@example.com")
        lic = create_active_license(emp["id"], lt["id"], license_number="RN-1001",
                                    expires_on="2027-06-30")
        set_clock("2027-06-01T00:00:00Z")
        # In cycle (anchor 2026-01-01), outside rolling window
        # [2026-06-02, 2027-06-01].
        create_validated_ce_activity(lic["id"], activity_title="Pharmacology",
                                     hours=15.0, completed_on="2026-03-01")
        # In both windows.
        create_validated_ce_activity(lic["id"], activity_title="Ethics",
                                     hours=15.0, completed_on="2026-09-01")
        data = get_success_data(api.get_license(lic["id"], OFFICER))
        assert data["cycle_ce_hours_validated"] == 30.0
        assert data["rolling_ce_hours_validated"] == 15.0

    def test_reported_and_required_percentages_diverge(self, api):
        """PRD §3.4: "`ce_progress_reported_pct` is the employer-reported posture
        — what the current cycle's file shows — computed from the cycle tally
        against the requirement. `ce_progress_required_pct` is the
        regulator-required posture — what the rolling 365-day file shows —
        computed from the rolling tally against the same requirement. Identical
        inputs can legitimately produce two different percentages".

        Design: Difficulty/dual_variant_calc/ce_progress_reported_vs_required_diverge
        """
        lt = create_license_type()
        emp = create_employee(full_name="Nora Nurse",
                              work_email="nora.pct@example.com")
        lic = create_active_license(emp["id"], lt["id"], license_number="RN-1002",
                                    expires_on="2027-06-30")
        set_clock("2027-06-01T00:00:00Z")
        create_validated_ce_activity(lic["id"], activity_title="Pharmacology",
                                     hours=15.0, completed_on="2026-03-01")
        create_validated_ce_activity(lic["id"], activity_title="Ethics",
                                     hours=15.0, completed_on="2026-09-01")
        data = get_success_data(api.get_license(lic["id"], OFFICER))
        assert data["ce_progress_reported_pct"] == 100.0
        assert data["ce_progress_required_pct"] == 50.0


class TestCeEligibilityAndAdjudication:
    def test_ce_activity_on_pending_license_rejected(self, api):
        """PRD §3.4: "the host license must stand in `ACTIVE`, `EXPIRED`,
        `LAPSED`, or `SUSPENDED`; logging against a `PENDING_VERIFICATION` or
        `REVOKED` license fails with `ERR_LICENSE_NOT_CE_ELIGIBLE`."

        Design: Corner/validations/ce_activity_on_pending_license_rejected
        """
        lt, emp = _rn_type_and_employee(api, "nora.ceelig@example.com")
        lic = create_license(emp["id"], lt["id"], license_number="RN-9314")
        resp = api.create_ce_activity(lic["id"], {
            "provider_name": "CEU Inc", "activity_title": "Early Course",
            "hours": 3.0, "completed_on": "2026-03-01",
        }, OFFICER)
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_CE_ELIGIBLE, 409)

    def test_ce_rejected_activity_cannot_be_validated(self, api):
        """PRD §3.4: "both outcomes are terminal, so adjudicating an activity
        that is no longer `LOGGED` fails with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/ce_rejected_activity_cannot_be_validated
        """
        lt, emp = _rn_type_and_employee(api, "nora.cerej@example.com")
        lic = create_active_license(emp["id"], lt["id"], license_number="RN-9101")
        ce = create_ce_activity(lic["id"], activity_title="Refresher", hours=2.0,
                                completed_on="2026-03-01")
        validate_success(api.reject_ce_activity(ce["id"], OFFICER), 200)
        resp = api.validate_ce_activity(ce["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestCeGateBoundary:
    def test_ce_gate_exactly_at_requirement_passes(self, api):
        """PRD §3.4: "verifying an `EXPIRED` or `LAPSED` license back to `ACTIVE`
        demands a `cycle_ce_hours_validated` of at least the type's
        `ce_hours_required_per_cycle`".

        Design: Difficulty/boundary_precision_check/ce_gate_exactly_at_requirement_passes
        """
        lt, emp = _rn_type_and_employee(api, "nora.cegate@example.com")
        # Exactly 30.0 validated hours: 10.25->10.5, 10.25->10.5, 9.0->9.0.
        lic = setup_license_with_cycle_hours(
            emp["id"], lt["id"], [10.25, 10.25, 9.0], expires_on="2026-12-31")
        set_clock("2027-01-05T00:00:00Z")  # EXPIRED, inside 45-day grace
        data = validate_success(api.verify_license(lic["id"], {
            "verified_on": "2027-01-05", "source": "STATE_BOARD_API",
            "outcome": "VERIFIED",
        }, OFFICER), 200)
        assert data["status"] == "ACTIVE"

    def test_reinstatement_extends_expiry_and_reanchors_cycle(self, api):
        """PRD §3.3: "On an `EXPIRED` or `LAPSED` license, a `VERIFIED` event is
        reinstatement: the license returns to `ACTIVE`, `expires_on` becomes
        `verified_on` plus 365 days, and `ce_cycle_anchor_on` is re-set to
        `verified_on` so the cycle CE window restarts from the new anchor".

        Design: Difficulty/boundary_precision_check/ce_gate_exactly_at_requirement_passes
        """
        lt, emp = _rn_type_and_employee(api, "nora.cegate2@example.com")
        lic = setup_license_with_cycle_hours(
            emp["id"], lt["id"], [10.25, 10.25, 9.0], expires_on="2026-12-31")
        set_clock("2027-01-05T00:00:00Z")
        data = validate_success(api.verify_license(lic["id"], {
            "verified_on": "2027-01-05", "source": "STATE_BOARD_API",
            "outcome": "VERIFIED",
        }, OFFICER), 200)
        assert data["expires_on"] == "2028-01-05"
        assert data["ce_cycle_anchor_on"] == "2027-01-05"

    def test_expired_reinstatement_below_ce_gate_rejected(self, api):
        """PRD §3.4: "a shortfall blocks the reinstatement with
        `ERR_CE_HOURS_INSUFFICIENT`."

        Design: Corner/state_machines/expired_reinstatement_below_ce_gate_rejected
        """
        lt, emp = _rn_type_and_employee(api, "nora.cefail@example.com")
        # 29.5 validated hours: 10.25->10.5, 9.0->9.0, 9.75->10.0.
        lic = setup_license_with_cycle_hours(
            emp["id"], lt["id"], [10.25, 9.0, 9.75], expires_on="2026-12-31")
        set_clock("2027-01-05T00:00:00Z")
        resp = api.verify_license(lic["id"], {
            "verified_on": "2027-01-05", "source": "STATE_BOARD_API",
            "outcome": "VERIFIED",
        }, OFFICER)
        validate_error(resp, ApiErrorId.ERR_CE_HOURS_INSUFFICIENT, 409)
        after = get_success_data(api.get_license(lic["id"], OFFICER))
        assert after["status"] == "EXPIRED"
