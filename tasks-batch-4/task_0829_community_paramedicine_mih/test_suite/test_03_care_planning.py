"""Care-plan lifecycle: the ACTIVE <-> UNDER_REVISION cycle, HIGH-risk co-signature
guards, and optimistic-concurrency on care-plan creation."""
from test_helpers import (
    validate_error, ApiErrorId,
    setup_enrollment_with_active_plan, setup_enrollment_with_draft_plan,
    bootstrap, enroll_patient, create_care_plan,
    refetch_care_plan, refetch_enrollment, create_care_plan_payload,
)


def test_care_plan_revision_cycle_returns_to_active(api):
    """PRD 3.4: "A plan may be activated from DRAFT -> ACTIVE or, after a revision cycle,
    from UNDER_REVISION -> ACTIVE ... Activating a plan out of UNDER_REVISION clears the
    enrollment's needs_review flag."
    Revising an ACTIVE plan and then re-activating it returns it to ACTIVE with the
    enrollment's needs_review cleared.

    Design: Difficulty/non_linear_state_machine/care_plan_active_revision_cycle
    """
    ctx = setup_enrollment_with_active_plan(api)
    org, cp_id, enr_id = ctx["org"], ctx["care_plan_id"], ctx["enrollment_id"]
    api.revise_care_plan(cp_id, org["clin_headers"])
    api.activate_care_plan(cp_id, org["clin_headers"])
    plan = refetch_care_plan(api, org, cp_id)
    enrollment = refetch_enrollment(api, org, enr_id)
    assert plan["status"] == "ACTIVE", f"expected ACTIVE, got {plan['status']}"
    assert enrollment["needs_review"] is False, "needs_review must be cleared on reactivation"


def test_care_plan_revision_increments_enrollment_revision_count(api):
    """PRD 3.4: "an ACTIVE plan moves ACTIVE -> UNDER_REVISION, which increments the owning
    enrollment's revision_count by one and sets its needs_review flag to true."

    Design: Difficulty/non_linear_state_machine/care_plan_active_revision_cycle
    """
    ctx = setup_enrollment_with_active_plan(api)
    org, cp_id, enr_id = ctx["org"], ctx["care_plan_id"], ctx["enrollment_id"]
    api.revise_care_plan(cp_id, org["clin_headers"])
    api.activate_care_plan(cp_id, org["clin_headers"])
    enrollment = refetch_enrollment(api, org, enr_id)
    assert enrollment["revision_count"] == 1, (
        f"expected revision_count 1, got {enrollment['revision_count']}")


def test_activate_high_risk_plan_without_cosigner_rejected(api):
    """PRD 3.4: "When the plan's risk_level is HIGH, activation additionally requires a
    cosigner_clinician_id to be present - its absence is rejected with ERR_COSIGN_REQUIRED -"

    Design: Corner/validations/activate_high_plan_without_cosigner_returns_cosign_required
    """
    ctx = setup_enrollment_with_draft_plan(api, risk_level="HIGH")
    resp = api.activate_care_plan(ctx["care_plan_id"], ctx["org"]["clin_headers"])
    validate_error(resp, ApiErrorId.ERR_COSIGN_REQUIRED)


def test_activate_high_risk_plan_with_self_cosigner_rejected(api):
    """PRD 3.4: "that co-signer must be a different provider from the authoring_clinician_id,
    since a clinician may not co-sign their own high-risk plan; a co-signer equal to the
    author is rejected with ERR_COSIGN_SAME_CLINICIAN."

    Design: Corner/validations/activate_high_plan_same_cosigner_returns_sod_error
    """
    org = bootstrap(api)
    enr = enroll_patient(api, org, {"baseline_ed_visits_12mo": 9, "chronic_conditions_count": 4})
    cp = create_care_plan(api, org, enr["enrollment_id"], enr["enrollment_version"],
                          risk_level="HIGH", cosigner_clinician_id=org["clin_id"])
    resp = api.activate_care_plan(cp["id"], org["clin_headers"])
    validate_error(resp, ApiErrorId.ERR_COSIGN_SAME_CLINICIAN)


def test_create_care_plan_with_stale_enrollment_version_rejected(api):
    """PRD 2.7: "If that value does not match the enrollment's current version - because
    another writer has advanced it since the client last read the enrollment - the create is
    rejected with ERR_STALE_VERSION at HTTP 412 ... When the versions match, the create
    proceeds, closes any existing non-CLOSED care plan for the enrollment, and increments the
    enrollment's version by one."

    Design: Corner/endpoints/careplan_create_stale_enrollment_version_occ
    """
    org = bootstrap(api)
    enr = enroll_patient(api, org)
    stale_version = enr["enrollment_version"]
    # Plan A consumes the current version and advances the enrollment's version.
    create_care_plan(api, org, enr["enrollment_id"], stale_version, goals="plan A")
    # Plan B replays the now-stale expected_enrollment_version.
    payload = create_care_plan_payload(org["clin_id"], stale_version, goals="plan B")
    resp = api.create_care_plan(enr["enrollment_id"], payload, org["clin_headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
