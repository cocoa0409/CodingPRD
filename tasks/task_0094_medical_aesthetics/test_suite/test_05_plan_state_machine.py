"""Treatment-plan state machine — revision cycle, branching, submit gates.

PRD §3.3 describes a non-linear state machine on TreatmentPlan:
  - CYCLE: SUBMITTED → DRAFT (return-to-draft) → SUBMITTED, plus a
    DRAFT → DRAFT self-loop on consultant edit that bumps plan_version.
  - BRANCH at SUBMITTED: → APPROVED via attending OR via senior
    countersign, OR → REJECTED.

This file also covers the submit gates (project-on-shelf, doctor-
qualified, items length 1..10) and the validation-priority pair
state vs business_safety (Rule 5 instance 1).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ATTENDING_PHYSICIAN_ID,
    ATTENDING_PHYSICIAN_ID_ALT,
    ApiErrorId,
    PLAN_ITEMS_MAX,
    PLAN_ITEMS_MIN,
    SENIOR_PHYSICIAN_ID,
    TEST_USERS,
    api_client,
    approve_plan_via_attending,
    assert_plan_version_incremented_by_one,
    assert_treatment_plan,
    assert_version_incremented_by_one,
    countersign_plan,
    create_consumable_sku,
    create_draft_plan,
    create_kyc_verified_customer,
    create_on_shelf_project,
    create_plan_payload,
    create_project_draft,
    create_project_payload,
    get_plan,
    make_attending_physician_headers,
    make_customer_headers,
    make_senior_physician_headers,
    patch_plan_payload,
    plan_item,
    return_plan_to_draft,
    setup_approved_plan_simple,
    setup_draft_plan,
    setup_high_risk_plan_submitted,
    setup_rejected_plan_no_consent,
    setup_submitted_plan_no_consent,
    sign_consent,
    submit_plan,
    validate_error,
    validate_success,
)


# ===========================================================================
# Revision cycle and DRAFT→DRAFT plan_version increment (Rule 3 instance 1)
# ===========================================================================
# difficulty: non_linear_state_machine/treatment_plan_revision_cycle_with_branching_approval
class TestTreatmentPlanRevisionCycle:
    """PRD §3.3: "Editing a DRAFT plan ... increments the semantic
    plan_version by 1 in addition to the OCC version." PRD §2.4: "the
    semantic plan_version starts at 1 when a plan is created and is
    incremented by 1 every time a DRAFT plan is edited via the
    consultant-edit transition."
    """

    def test_draft_edit_increments_plan_version(self, api):
        """PRD §2.4: "the semantic plan_version starts at 1 when a
        plan is created and is incremented by 1 every time a DRAFT
        plan is edited via the consultant-edit transition."

        Claim: PATCH on DRAFT increments plan_version by exactly 1.

        # difficulty: non_linear_state_machine/treatment_plan_revision_cycle_with_branching_approval
        """
        ctx = setup_draft_plan()
        before = ctx["plan"]
        assert before["plan_version"] == 1

        res = api.patch_plan(
            before["id"],
            patch_plan_payload(expected_outcome="Updated narrative."),
            TEST_USERS["consultant_headers"],
        )
        after = validate_success(res, 200)
        assert_plan_version_incremented_by_one(after, before)
        assert after["plan_version"] == 2

    def test_submitted_to_draft_clears_consent(self, api):
        """PRD §3.3: "A return-to-draft by the originating consultant
        moves the plan from SUBMITTED back to DRAFT, clears
        informed_consent_signed_at (so consent must be re-collected
        the next time)."

        Claim: after return-to-draft, informed_consent_signed_at is null.

        # difficulty: non_linear_state_machine/treatment_plan_revision_cycle_with_branching_approval
        """
        ctx = setup_submitted_plan_no_consent()
        plan = ctx["plan"]
        # Sign consent so we can prove the field is cleared on return.
        plan = sign_consent(plan["id"], ctx["customer"]["id"])
        assert plan["informed_consent_signed_at"] is not None

        returned = return_plan_to_draft(plan["id"])
        assert returned["status"] == "DRAFT"
        assert returned["informed_consent_signed_at"] is None, (
            "PRD §3.3: return-to-draft must clear "
            "informed_consent_signed_at"
        )

    def test_full_revision_cycle_states_traversed(self, api):
        """PRD §3.3: state cycle traversal — patch (DRAFT → DRAFT),
        submit (DRAFT → SUBMITTED), return-to-draft (SUBMITTED → DRAFT),
        submit again (DRAFT → SUBMITTED).

        Claim: after PATCH → submit → return-to-draft → submit, the
        plan status proceeds through SUBMITTED → DRAFT → SUBMITTED.

        # difficulty: non_linear_state_machine/treatment_plan_revision_cycle_with_branching_approval
        """
        ctx = setup_draft_plan()
        plan = ctx["plan"]
        # PATCH DRAFT (DRAFT → DRAFT).
        res = api.patch_plan(
            plan["id"],
            patch_plan_payload(expected_outcome="Edit 1"),
            TEST_USERS["consultant_headers"],
        )
        plan = validate_success(res, 200)
        # Submit (DRAFT → SUBMITTED).
        plan = submit_plan(plan["id"])
        assert plan["status"] == "SUBMITTED"
        # Return-to-draft (SUBMITTED → DRAFT).
        plan = return_plan_to_draft(plan["id"])
        assert plan["status"] == "DRAFT"
        # Submit again (DRAFT → SUBMITTED).
        plan = submit_plan(plan["id"])
        assert plan["status"] == "SUBMITTED"


# ===========================================================================
# Branching: SUBMITTED → APPROVED (attending) vs REJECTED
# ===========================================================================
class TestTreatmentPlanBranching:

    def test_attending_approve_requires_consent(self, api):
        """PRD §3.3: "The plan cannot advance to APPROVED until
        informed_consent_signed_at is non-null; an attempt to approve
        or countersign before consent is rejected with
        ERR_CONSENT_NOT_SIGNED (HTTP 422)."

        Claim: approve before consent → ERR_CONSENT_NOT_SIGNED.
        """
        ctx = setup_submitted_plan_no_consent()
        res = api.approve_plan(
            ctx["plan"]["id"],
            make_attending_physician_headers(ctx["attending_doctor_id"]),
        )
        validate_error(res, ApiErrorId.ERR_CONSENT_NOT_SIGNED.value)

    def test_attending_can_reject_submitted_plan(self, api):
        """PRD §3.3: "A rejection by the attending physician moves
        the plan from SUBMITTED to the terminal REJECTED status with
        an audit entry of action PLAN_REJECTED."

        Claim: reject on SUBMITTED → status REJECTED.
        """
        ctx = setup_submitted_plan_no_consent()
        res = api.reject_plan(
            ctx["plan"]["id"],
            make_attending_physician_headers(ctx["attending_doctor_id"]),
        )
        rejected = validate_success(res, 200)
        assert rejected["status"] == "REJECTED"

    def test_segregation_of_duties_on_countersign(self, api):
        """PRD §3.3: "the acting SeniorPhysician must not be the same
        id as attending_physician_id (segregation of duties; otherwise
        the request is rejected with ERR_SEGREGATION_VIOLATION, HTTP
        422)."

        Claim: SeniorPhysician X-User-ID == attending_physician_id →
        ERR_SEGREGATION_VIOLATION.
        """
        ctx = setup_high_risk_plan_submitted()
        plan = ctx["plan"]
        # Sign consent first so the consent gate clears.
        sign_consent(plan["id"], ctx["customer"]["id"])

        # Countersign with the same doctor id as attending.
        same_doctor_headers = make_senior_physician_headers(
            ctx["attending_doctor_id"],
        )
        res = api.countersign_plan(plan["id"], same_doctor_headers)
        validate_error(res, ApiErrorId.ERR_SEGREGATION_VIOLATION.value)

    def test_high_risk_plan_routes_to_countersign(self, api):
        """PRD §3.3: "The plan's requires_senior_countersign flag is
        computed whenever the plan is created, edited, or submitted.
        It is true when any included project's risk_level is HIGH."

        Claim: a plan with a HIGH-risk project carries
        requires_senior_countersign == true.
        """
        ctx = setup_high_risk_plan_submitted()
        assert ctx["plan"]["requires_senior_countersign"] is True

    def test_low_risk_plan_does_not_require_countersign(self, api):
        """PRD §3.3: "Otherwise it is false."

        Claim: a plan whose projects are all LOW-risk has
        requires_senior_countersign == false.
        """
        ctx = setup_draft_plan(risk_level="LOW")
        assert ctx["plan"]["requires_senior_countersign"] is False


# ===========================================================================
# Plan items range — 1..10 (Rule 6 instance 2)
# ===========================================================================
# difficulty: boundary_precision_check/plan_items_zero_or_eleven_empty_set_boundary
class TestPlanItemsBoundary:
    """PRD §3.3: "A plan whose items length falls outside 1 to 10 —
    either empty or with eleven or more entries — is rejected at create
    or edit time with ERR_PLAN_ITEMS_OUT_OF_RANGE (HTTP 422)."
    """

    def test_empty_items_rejected_on_create(self, api):
        """PRD §3.3: "A plan whose `items` length falls outside 1 to 10
        — either empty or with eleven or more entries — is rejected at
        create or edit time with `ERR_PLAN_ITEMS_OUT_OF_RANGE` (HTTP
        422)."

        Claim: items=[] → ERR_PLAN_ITEMS_OUT_OF_RANGE.

        # difficulty: boundary_precision_check/plan_items_zero_or_eleven_empty_set_boundary
        """
        customer = create_kyc_verified_customer()
        payload = create_plan_payload(
            customer_id=customer["id"], items=[],
            attending_physician_id=ATTENDING_PHYSICIAN_ID,
        )
        res = api.create_plan(payload, TEST_USERS["consultant_headers"])
        validate_error(res, ApiErrorId.ERR_PLAN_ITEMS_OUT_OF_RANGE.value)

    def test_eleven_items_rejected_on_create(self, api):
        """PRD §3.3: "A plan whose `items` length falls outside 1 to 10
        — either empty or with eleven or more entries — is rejected at
        create or edit time with `ERR_PLAN_ITEMS_OUT_OF_RANGE` (HTTP
        422)."

        Claim: items.length == 11 → ERR_PLAN_ITEMS_OUT_OF_RANGE.

        # difficulty: boundary_precision_check/plan_items_zero_or_eleven_empty_set_boundary
        """
        project, _ = create_on_shelf_project()
        customer = create_kyc_verified_customer()
        items = [plan_item(project["id"], "T0", 1) for _ in range(11)]
        payload = create_plan_payload(
            customer_id=customer["id"], items=items,
            attending_physician_id=ATTENDING_PHYSICIAN_ID,
        )
        res = api.create_plan(payload, TEST_USERS["consultant_headers"])
        validate_error(res, ApiErrorId.ERR_PLAN_ITEMS_OUT_OF_RANGE.value)

    def test_one_item_accepted_on_create(self, api):
        """PRD §3.3: "An items array of {project_id, tier_code,
        quantity} entries of length 1 to 10."

        Claim: items.length == 1 succeeds with 201.

        # difficulty: boundary_precision_check/plan_items_zero_or_eleven_empty_set_boundary
        """
        project, _ = create_on_shelf_project()
        customer = create_kyc_verified_customer()
        items = [plan_item(project["id"], "T0", 1)]
        payload = create_plan_payload(
            customer_id=customer["id"], items=items,
            attending_physician_id=ATTENDING_PHYSICIAN_ID,
        )
        data = validate_success(
            api.create_plan(payload, TEST_USERS["consultant_headers"]),
            201,
        )
        assert_treatment_plan(data)
        assert data["status"] == "DRAFT"


# ===========================================================================
# Cross-entity dependency: plan submit requires project ON_SHELF (Rule 7 inst1)
# ===========================================================================
# difficulty: cross_entity_state_dependency/plan_submit_requires_project_on_shelf
class TestSubmitRequiresOnShelfProject:
    """PRD §3.3: "At submission time the system rechecks that each
    item's project is ON_SHELF (ERR_PROJECT_NOT_ON_SHELF otherwise,
    HTTP 422)."
    """

    def test_submit_rejected_when_project_not_on_shelf(self, api):
        """PRD §3.3: "At submission time the system rechecks that each
        item's project is ON_SHELF (ERR_PROJECT_NOT_ON_SHELF otherwise,
        HTTP 422)."

        Claim: a DRAFT plan referencing a project in UNDER_REVIEW (not
        yet ON_SHELF) fails submission with ERR_PROJECT_NOT_ON_SHELF.

        # difficulty: cross_entity_state_dependency/plan_submit_requires_project_on_shelf
        """
        # Create a project, push it to UNDER_REVIEW but don't approve.
        sku = create_consumable_sku()
        draft_project = create_project_draft(
            sku_id=sku["id"],
            qualified_doctor_ids=[ATTENDING_PHYSICIAN_ID],
        )
        from test_helpers import submit_project
        under_review = submit_project(draft_project["id"])
        assert under_review["status"] == "UNDER_REVIEW"

        customer = create_kyc_verified_customer()
        plan = create_draft_plan(
            customer_id=customer["id"],
            items=[plan_item(under_review["id"], "T0", 1)],
            attending_physician_id=ATTENDING_PHYSICIAN_ID,
        )
        res = api.submit_plan(
            plan["id"], TEST_USERS["consultant_headers"],
        )
        validate_error(res, ApiErrorId.ERR_PROJECT_NOT_ON_SHELF.value)

    def test_submit_succeeds_after_project_approved_to_shelf(self, api):
        """PRD §3.3: "the same submit succeeds and plan transitions to
        SUBMITTED" once Project is ON_SHELF.

        Claim: after UNDER_REVIEW → ON_SHELF, the same plan submits.

        # difficulty: cross_entity_state_dependency/plan_submit_requires_project_on_shelf
        """
        sku = create_consumable_sku()
        draft_project = create_project_draft(
            sku_id=sku["id"],
            qualified_doctor_ids=[ATTENDING_PHYSICIAN_ID],
        )
        from test_helpers import submit_project, approve_project
        submit_project(draft_project["id"])
        on_shelf = approve_project(draft_project["id"])
        assert on_shelf["status"] == "ON_SHELF"

        customer = create_kyc_verified_customer()
        plan = create_draft_plan(
            customer_id=customer["id"],
            items=[plan_item(on_shelf["id"], "T0", 1)],
            attending_physician_id=ATTENDING_PHYSICIAN_ID,
        )
        plan_submitted = submit_plan(plan["id"])
        assert plan_submitted["status"] == "SUBMITTED"


# ===========================================================================
# Priority pair: state vs business_safety (Rule 5 instance 1)
# ===========================================================================
# difficulty: priority_pair_validation_conflict/state_vs_business_safety_priority
class TestStateVsBusinessSafetyPriority:
    """PRD §2.6: "Within each category the priorities ordered higher
    in the list above fire first; in particular, the ERR_INVALID_STATE
    gate precedes ERR_VERSION_CONFLICT, which itself precedes every
    business check." The validation order names state preconditions
    before business_safety, so approve on a REJECTED plan (also
    missing consent) must surface ERR_INVALID_STATE.
    """

    def test_approve_rejected_plan_yields_invalid_state_not_consent(self, api):
        """PRD §2.6: "After these gates clear, business-safety checks
        run — customer age at submission, absolute-contraindication,
        segregation-of-duties for countersign, lot-number requirement,
        consent-signed-before-approval — followed by business-
        referential checks ..."

        PRD §2.6: "the order is: authentication (ERR_UNAUTHENTICATED)
        first, then authorization (ERR_FORBIDDEN), then path-existence
        (ERR_NOT_FOUND on path-bearing resources), then body
        foreign-key existence (also ERR_NOT_FOUND), then state
        preconditions (ERR_INVALID_STATE), then OCC version match
        (ERR_VERSION_CONFLICT)."

        Claim: calling /approve on a REJECTED plan (terminal) whose
        consent was never signed yields ERR_INVALID_STATE (state gate)
        rather than ERR_CONSENT_NOT_SIGNED (business_safety gate).

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_priority
        """
        ctx = setup_rejected_plan_no_consent()
        # Plan is now in REJECTED status with informed_consent_signed_at
        # == null. Calling /approve must hit ERR_INVALID_STATE first.
        res = api.approve_plan(
            ctx["plan"]["id"],
            make_attending_physician_headers(ctx["attending_doctor_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Consent self-loop on SUBMITTED
# ===========================================================================
class TestSignConsent:

    def test_sign_consent_sets_timestamp_and_stays_submitted(self, api):
        """PRD §3.3: "This is a self-loop on the SUBMITTED status that
        requires the acting customer to equal TreatmentPlan.customer_id
        and requires informed_consent_signed_at to currently be null;
        it sets informed_consent_signed_at to the server's current
        time."

        Claim: sign-consent on SUBMITTED sets
        informed_consent_signed_at and leaves status SUBMITTED.
        """
        ctx = setup_submitted_plan_no_consent()
        plan_signed = sign_consent(
            ctx["plan"]["id"], ctx["customer"]["id"],
        )
        assert plan_signed["status"] == "SUBMITTED"
        assert plan_signed["informed_consent_signed_at"] is not None

    # DELETED: test_sign_consent_by_wrong_customer_rejected
    # PRD §2.5 (nested-path ownership → ERR_NOT_FOUND) explicitly
    # restricts itself to "paths containing more than one resource
    # identifier"; the sign-consent path /aesthetics/plans/{id}/
    # sign-consent has only one identifier. PRD §3.3 mandates that
    # "the acting customer [must] equal TreatmentPlan.customer_id" but
    # is silent on the error_id to return when it doesn't. A faithful
    # PRD-only reader could plausibly surface this as either
    # ERR_FORBIDDEN (per §2.1 authorization) or ERR_NOT_FOUND (by
    # extension of §2.5). Unique-derivability fails → test deleted.
