"""Authorization lifecycle: PENDING -> APPROVED -> ACTIVE -> EXHAUSTED |
EXPIRED | RENEWED; PENDING -> DENIED.

PRD §3.4 (authorization), §2.9 (unit-hour economy and dual variant).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    add_seconds,
    advance_clock,
    approve_authorization,
    assert_authorization,
    create_authorization_payload,
    get_authorization,
    get_clinic,
    request_authorization,
    setup_active_authorization,
    setup_active_treatment_plan,
    setup_clinic_with_roster,
    validate_error,
    validate_success,
)


class TestCreateAuthorization:

    def test_create_authorization_enters_pending(self, api):
        """PRD §3.4: "A new authorization enters PENDING. A PayerAdmin
        resolves it either to APPROVED (when the backing TreatmentPlan
        is ACTIVE — otherwise the request fails the state precondition)
        or to DENIED (without further precondition)."

        Claim: a freshly-created authorization has status == PENDING.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        plan = setup_active_treatment_plan(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        effective_start = add_seconds(clinic["now_ts"], seconds=86400)
        effective_end = add_days(effective_start, days=180)
        auth = request_authorization(
            patient_id=roster["patient"]["id"],
            treatment_plan_id=plan["id"],
            cpt_code="97153",
            approved_units=240,
            effective_start=effective_start,
            effective_end=effective_end,
        )
        assert_authorization(auth)
        assert auth["status"] == "PENDING"

    def test_authorization_initial_consumption_is_zero(self, api):
        """PRD §3.4: "The two computed consumption fields
        provisional_units_consumed and adjudicated_units_consumed are
        initialised to zero."

        Claim: a fresh PENDING authorization has both consumption
        fields == 0.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        plan = setup_active_treatment_plan(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        effective_start = add_seconds(clinic["now_ts"], seconds=86400)
        effective_end = add_days(effective_start, days=180)
        auth = request_authorization(
            patient_id=roster["patient"]["id"],
            treatment_plan_id=plan["id"],
            effective_start=effective_start,
            effective_end=effective_end,
        )
        assert auth["provisional_units_consumed"] == 0
        assert auth["adjudicated_units_consumed"] == 0

    @pytest.mark.parametrize(
        "window_days,allowed",
        [(89, False), (90, True), (366, True), (367, False)],
    )
    def test_authorization_window_must_be_between_90_and_366_days(
        self, api, clinic_admin_headers, window_days, allowed,
    ):
        """PRD §3.4: "the elapsed span between them must be at least 90
        days and at most 366 days (both bounds inclusive)."

        Claim: window length outside [90, 366] days is rejected;
        boundary lengths are accepted.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        plan = setup_active_treatment_plan(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        effective_start = add_seconds(clinic["now_ts"], seconds=86400)
        effective_end = add_days(effective_start, days=window_days)
        res = api.create_authorization(
            roster["patient"]["id"],
            create_authorization_payload(
                treatment_plan_id=plan["id"],
                effective_start=effective_start,
                effective_end=effective_end,
            ),
            clinic_admin_headers,
        )
        if allowed:
            data = validate_success(res, expected_status=201)
            assert data["status"] == "PENDING"
        else:
            validate_error(res, "ERR_VALIDATION")

    def test_renewal_with_mismatched_cpt_rejected(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.4: "When renewed_from_id is supplied, it must resolve
        to an existing Authorization, and that prior Authorization's
        cpt_code must equal this new one's cpt_code; a mismatch is
        rejected with ERR_RENEWAL_CPT_MISMATCH."

        Claim: creating a renewal authorization with a different
        cpt_code than its parent returns ERR_RENEWAL_CPT_MISMATCH.
        """
        roster = setup_clinic_with_roster()
        parent_auth, _ = setup_active_authorization(
            clinic=roster["clinic"],
            patient=roster["patient"],
            plan=setup_active_treatment_plan(
                clinic=roster["clinic"],
                patient=roster["patient"],
                bcba=roster["bcbas"][0],
            ),
            cpt_code="97153",
        )
        clinic_state = get_clinic(roster["clinic"]["id"])
        # New auth with a different cpt_code referencing the parent.
        eff_start = add_seconds(clinic_state["now_ts"], seconds=60)
        eff_end = add_days(eff_start, days=180)
        res = api.create_authorization(
            roster["patient"]["id"],
            create_authorization_payload(
                treatment_plan_id=parent_auth["treatment_plan_id"],
                cpt_code="97155",  # mismatch
                effective_start=eff_start,
                effective_end=eff_end,
                renewed_from_id=parent_auth["id"],
            ),
            clinic_admin_headers,
        )
        validate_error(res, "ERR_RENEWAL_CPT_MISMATCH")


class TestApproveAuthorization:

    def test_approve_pending_authorization(self, api, payer_admin_headers):
        """PRD §3.4: "A PayerAdmin resolves it either to APPROVED (when
        the backing TreatmentPlan is ACTIVE — otherwise the request
        fails the state precondition) or to DENIED (without further
        precondition)."

        Claim: PayerAdmin approves a PENDING authorization, transitioning
        to APPROVED.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        plan = setup_active_treatment_plan(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        eff_start = add_seconds(clinic["now_ts"], seconds=86400)
        eff_end = add_days(eff_start, days=180)
        auth = request_authorization(
            patient_id=roster["patient"]["id"],
            treatment_plan_id=plan["id"],
            effective_start=eff_start,
            effective_end=eff_end,
        )
        res = api.approve_authorization(auth["id"], payer_admin_headers)
        approved = validate_success(res)
        assert approved["status"] == "APPROVED"

    def test_deny_pending_authorization(self, api, payer_admin_headers):
        """PRD §3.4: "A PayerAdmin resolves it … to DENIED (without
        further precondition)."

        Claim: PayerAdmin denies a PENDING authorization, transitioning
        to DENIED.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        plan = setup_active_treatment_plan(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        eff_start = add_seconds(clinic["now_ts"], seconds=86400)
        eff_end = add_days(eff_start, days=180)
        auth = request_authorization(
            patient_id=roster["patient"]["id"],
            treatment_plan_id=plan["id"],
            effective_start=eff_start,
            effective_end=eff_end,
        )
        res = api.deny_authorization(auth["id"], payer_admin_headers)
        denied = validate_success(res)
        assert denied["status"] == "DENIED"


class TestAuthorizationTimeGatedTransitions:

    def test_approved_authorization_becomes_active_on_clock_cross(
        self, api,
    ):
        """PRD §3.4: "When the clinic's now_ts later crosses at or past
        the authorization's effective_start, the Authorization
        auto-transitions from APPROVED to ACTIVE on the next
        clock-advance."

        Claim: after clock advance past effective_start, the
        authorization status is ACTIVE.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        plan = setup_active_treatment_plan(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        auth, _ = setup_active_authorization(
            clinic=clinic, patient=roster["patient"], plan=plan,
        )
        assert auth["status"] == "ACTIVE"

    def test_active_authorization_expires_strictly_after_effective_end(
        self, api,
    ):
        """PRD §3.4 + §2.12: "the authorization's transition to EXPIRED
        fires on a strict greater-than comparison of now_ts against
        effective_end".

        Claim: advancing the clock strictly past effective_end causes
        the authorization to auto-transition to EXPIRED.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        plan = setup_active_treatment_plan(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        auth, _ = setup_active_authorization(
            clinic=clinic, patient=roster["patient"], plan=plan,
        )
        # Advance well past the 180-day window.
        advance_clock(clinic["id"], 200 * 86400)
        # Re-read.
        after = get_authorization(auth["id"])
        assert after["status"] == "EXPIRED"


class TestApproveAuthorizationStatePrecondition:

    def test_approve_when_plan_not_active_yields_invalid_state(
        self, api, payer_admin_headers, clinic_admin_headers,
    ):
        """PRD §3.4: "A PayerAdmin resolves it … to APPROVED (when the
        backing TreatmentPlan is ACTIVE — otherwise the request fails
        the state precondition)".

        Claim: approving an authorization whose backing TreatmentPlan
        is not ACTIVE (e.g. plan expired before approval) returns
        ERR_INVALID_STATE.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        plan = setup_active_treatment_plan(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        eff_start = add_seconds(clinic["now_ts"], seconds=86400)
        eff_end = add_days(eff_start, days=180)
        auth = request_authorization(
            patient_id=roster["patient"]["id"],
            treatment_plan_id=plan["id"],
            effective_start=eff_start,
            effective_end=eff_end,
        )
        # Expire the plan by advancing the clock 366 days.
        advance_clock(clinic["id"], 366 * 86400)
        # Now plan is EXPIRED; approving should yield ERR_INVALID_STATE.
        res = api.approve_authorization(auth["id"], payer_admin_headers)
        validate_error(res, "ERR_INVALID_STATE")
