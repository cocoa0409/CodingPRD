"""Difficulty Rule 5 — priority_pair_validation_conflict.

Two error-pair conflicts where PRD prose pins the winner by priority class:
  (A) state (ERR_INVALID_STATE) > fiscal (ERR_AUTHORIZATION_EXHAUSTED) — finalize a
      CANCELLED visit on an exhausted grant; PRD §2.11 puts state above fiscal.
  (B) safety (ERR_VA_REFERRAL_REQUIRED) > referential (ERR_VETERAN_FLAG_REQUIRED).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    set_clock,
    setup_active_poc,
    setup_poc_with_grant,
    schedule_visit,
    complete_visit,
    finalize_visit,
    create_therapist,
    create_patient,
    create_draft_poc,
    record_initial_evaluation,
    create_patient_payload,
    create_plan_of_care_payload,
    finalize_visit_payload,
    make_therapist_headers,
    TEST_USERS,
)


class TestStateWinsOverFiscalFinalizeCancelledVisitOnExhaustedGrant:
    """Visit is CANCELLED (state-invalid for /finalize) AND grant.units_consumed
    equals total_units_granted (exhausted). PRD §2.11 puts state > fiscal, so
    the surfaced error is ERR_INVALID_STATE, not ERR_AUTHORIZATION_EXHAUSTED.
    """

    def test_finalize_cancelled_visit_on_exhausted_grant_returns_invalid_state(self, api):
        """PRD §2.11: "current-state preconditions (`ERR_INVALID_STATE`); the OCC
        stale-version check (`ERR_STALE_PLAN_VERSION`); business-safety rules
        (`ERR_VA_REFERRAL_REQUIRED`, `ERR_MIPS_ELIGIBILITY`, `ERR_CAPPED_POC_EXCEEDED`);
        business-constraint rules (`ERR_THERAPIST_LICENSE_INVALID`,
        `ERR_VA_VISIT_CAP_EXCEEDED`); business-temporal rules (`ERR_VISIT_OUT_OF_WINDOW`,
        `ERR_THERAPIST_DOUBLE_BOOKED`, `ERR_GRANT_WINDOW_OVERLAP`); business-fiscal rules
        (`ERR_AUTHORIZATION_EXHAUSTED`)"
        PRD §3.5: "The finalize is allowed only when the visit is already `COMPLETED`"

        Design: Difficulty/priority_pair_validation_conflict/state_wins_over_fiscal_finalize_cancelled_visit_on_exhausted_grant
        """
        # Setup an ACTIVE COMMERCIAL POC; use a tiny grant (total=2) that gets
        # filled by visit A (planned_minutes=30 → 2 units → fills the grant).
        ctx = setup_poc_with_grant(
            insurance_type="COMMERCIAL",
            total_units_granted=3,
            grant_effective_from="2026-06-01",
            grant_effective_to="2026-06-30",
        )
        th = ctx["therapist"]["id"]
        gid = ctx["grant"]["id"]
        poc_id = ctx["poc"]["id"]
        # Fill 2 units with vA: 30min/CPT_97110 → 2 units → finalize.
        vA = schedule_visit(gid, th, "2026-06-02T09:00:00Z", "2026-06-02T09:30:00Z",
                            planned_minutes=30, cpt_code="CPT_97110_THER_EX")
        complete_visit(vA["id"], th, actual_minutes=30)
        finalize_visit(vA["id"], poc_id)
        # vB: 15min/CPT_97110 → 1 unit → consumed=3 → grant EXHAUSTED.
        vB = schedule_visit(gid, th, "2026-06-03T09:00:00Z", "2026-06-03T09:15:00Z",
                            planned_minutes=15, cpt_code="CPT_97110_THER_EX")
        # Cancel vB → state CANCELLED. (PlatformAdmin may cancel at any time per PRD §3.5.)
        validate_success(api.cancel_visit(vB["id"], TEST_USERS["platform_admin_headers"]), 200)
        # Now trigger: finalize vB → state-invalid (CANCELLED, not COMPLETED).
        poc_v = get_success_data(api.get_plan_of_care(poc_id, TEST_USERS["billing_clerk_headers"]))["version"]
        res = api.finalize_visit(
            vB["id"], finalize_visit_payload(expected_plan_of_care_version=poc_v),
            TEST_USERS["billing_clerk_headers"],
        )
        # State should win (priority 300) over fiscal (priority 440).
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_finalize_cancelled_visit_does_not_return_authorization_exhausted(self, api):
        """PRD §2.11: "current-state preconditions (`ERR_INVALID_STATE`); ... business-fiscal
        rules (`ERR_AUTHORIZATION_EXHAUSTED`)"

        Same setup as above, asserts the LOWER-priority fiscal error is NOT surfaced.

        Design: Difficulty/priority_pair_validation_conflict/state_wins_over_fiscal_finalize_cancelled_visit_on_exhausted_grant
        """
        ctx = setup_poc_with_grant(
            insurance_type="COMMERCIAL",
            total_units_granted=3,
            grant_effective_from="2026-06-01",
            grant_effective_to="2026-06-30",
        )
        th = ctx["therapist"]["id"]
        gid = ctx["grant"]["id"]
        poc_id = ctx["poc"]["id"]
        vA = schedule_visit(gid, th, "2026-06-02T09:00:00Z", "2026-06-02T09:30:00Z",
                            planned_minutes=30, cpt_code="CPT_97110_THER_EX")
        complete_visit(vA["id"], th, actual_minutes=30)
        finalize_visit(vA["id"], poc_id)
        vB = schedule_visit(gid, th, "2026-06-03T09:00:00Z", "2026-06-03T09:15:00Z",
                            planned_minutes=15, cpt_code="CPT_97110_THER_EX")
        validate_success(api.cancel_visit(vB["id"], TEST_USERS["platform_admin_headers"]), 200)
        poc_v = get_success_data(api.get_plan_of_care(poc_id, TEST_USERS["billing_clerk_headers"]))["version"]
        res = api.finalize_visit(
            vB["id"], finalize_visit_payload(expected_plan_of_care_version=poc_v),
            TEST_USERS["billing_clerk_headers"],
        )
        body = res.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] != "ERR_AUTHORIZATION_EXHAUSTED"


class TestSafetyWinsOverReferentialVaActivateMissingReferralAndVetFlag:
    """Two parts of the conflict, on different writes:
      - Patient create with VA_TRICARE + is_veteran=false → ERR_VETERAN_FLAG_REQUIRED (referential).
      - POC activate for a clean VA_TRICARE patient without veteran_referral_id →
        ERR_VA_REFERRAL_REQUIRED (safety, higher priority than referential).
    """

    def test_patient_create_va_tricare_without_veteran_flag_returns_veteran_flag_required(self, api):
        """PRD §3.1: "if `insurance_type` is `VA_TRICARE`, then `is_veteran` must be true;
        submitting a `VA_TRICARE` patient with `is_veteran` unset or false is rejected
        with `ERR_VETERAN_FLAG_REQUIRED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_wins_over_referential_va_activate_missing_referral_and_vet_flag
        """
        set_clock("2026-06-01T00:00:00Z")
        res = api.create_patient(
            create_patient_payload(
                full_name="Vet Bad",
                date_of_birth="1965-01-01",
                insurance_type="VA_TRICARE",
                is_veteran=False,
            ),
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(res, "ERR_VETERAN_FLAG_REQUIRED", expected_status=422)

    def test_activate_va_poc_with_cancelled_referral_returns_va_referral_required(self, api):
        """PRD §3.2: "For VA_TRICARE plans there are two additional preconditions: the
        plan must have a `veteran_referral_id`, the referenced `VeteranReferral` must be
        in `ISSUED` status, and the plan's `certified_end_date` must fall on or before
        the referral's `expires_on`. Violating any of the VA-specific preconditions
        surfaces `ERR_VA_REFERRAL_REQUIRED` (HTTP 422)"

        The "missing veteran_referral_id" sub-condition is unreachable because PRD §3.2
        also requires that VA_TRICARE POC creation carry a `veteran_referral_id`. The
        reachable sub-condition exercised here is the referral-not-ISSUED branch: the
        referral is CANCELLED before activation, so the activation precondition
        "the referenced `VeteranReferral` must be in `ISSUED` status" trips.

        Design: Difficulty/priority_pair_validation_conflict/safety_wins_over_referential_va_activate_missing_referral_and_vet_flag
        """
        from test_helpers import create_veteran_referral

        set_clock("2026-06-01T00:00:00Z")
        th = create_therapist(license_state="CA", medicare_provider_enrolled=False,
                              full_name="VA Prio T")
        pt = create_patient(insurance_type="VA_TRICARE", is_veteran=True,
                            full_name="Vet Good", date_of_birth="1965-01-01")
        referral = create_veteran_referral(pt["id"], max_authorized_visits=10,
                                           expires_on="2026-12-31")
        poc = create_draft_poc(pt["id"], th["id"], veteran_referral_id=referral["id"])
        record_initial_evaluation(poc["id"], th["id"], performed_on="2026-06-01")
        # Cancel the referral so it is no longer in ISSUED status.
        get_success_data(
            api.cancel_veteran_referral(referral["id"], TEST_USERS["va_coordinator_headers"])
        )
        res = api.activate_plan_of_care(poc["id"], make_therapist_headers(th["id"]))
        validate_error(res, "ERR_VA_REFERRAL_REQUIRED", expected_status=422)
