"""Project catalog lifecycle — PRD §3.1.

Covers DRAFT → UNDER_REVIEW → ON_SHELF → OFF_SHELF transitions, the
in-use guard on take-off-shelf, and the catalog-conservation invariant
(off-shelf followed by return-to-shelf restores the ON_SHELF count).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ATTENDING_PHYSICIAN_ID,
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_project,
    assert_on_shelf_count_unchanged,
    assert_project,
    assert_version_incremented_by_one,
    count_rows,
    create_consumable_sku,
    create_draft_plan,
    create_kyc_verified_customer,
    create_on_shelf_project,
    create_project_draft,
    create_project_payload,
    list_projects,
    plan_item,
    reject_project,
    return_project_to_shelf,
    submit_project,
    take_project_off_shelf,
    validate_error,
    validate_success,
)


# ===========================================================================
# Happy-path transitions
# ===========================================================================
class TestProjectCreate:

    def test_create_returns_draft_status(self, api):
        """PRD §3.1: "Upon creation the project's status is DRAFT."

        Claim: POST /aesthetics/projects returns status == 'DRAFT'.
        """
        sku = create_consumable_sku()
        payload = create_project_payload(sku_id=sku["id"])
        data = validate_success(
            api.create_project(
                payload, TEST_USERS["medical_director_headers"],
            ),
            201,
        )
        assert_project(data)
        assert data["status"] == "DRAFT"
        assert data["version"] == 1

    def test_submit_moves_draft_to_under_review(self, api):
        """PRD §3.1: "A submission action by Consultant or
        MedicalDirector transitions the project to UNDER_REVIEW
        provided bom, qualified_doctor_ids, and pricing_tiers are
        each non-empty."

        Claim: POST /aesthetics/projects/{id}/submit on DRAFT →
        status='UNDER_REVIEW'.
        """
        sku = create_consumable_sku()
        draft = create_project_draft(sku_id=sku["id"])
        submitted = submit_project(draft["id"])
        assert submitted["status"] == "UNDER_REVIEW"
        assert_version_incremented_by_one(submitted, draft)

    def test_approve_moves_under_review_to_on_shelf(self, api):
        """PRD §3.1: "an approval which advances the project to
        ON_SHELF and writes the acting user's id into reviewer_id."

        Claim: POST /aesthetics/projects/{id}/approve sets status
        ON_SHELF and reviewer_id.
        """
        sku = create_consumable_sku()
        draft = create_project_draft(sku_id=sku["id"])
        submitted = submit_project(draft["id"])
        on_shelf = approve_project(draft["id"])
        assert on_shelf["status"] == "ON_SHELF"
        assert on_shelf["reviewer_id"], (
            "reviewer_id must be set by approve transition"
        )
        assert on_shelf["version"] == submitted["version"] + 1

    def test_reject_returns_to_draft(self, api):
        """PRD §3.1: "a rejection which sends the project back to
        DRAFT."

        Claim: POST /aesthetics/projects/{id}/reject moves
        UNDER_REVIEW → DRAFT.
        """
        sku = create_consumable_sku()
        draft = create_project_draft(sku_id=sku["id"])
        submit_project(draft["id"])
        rejected = reject_project(draft["id"])
        assert rejected["status"] == "DRAFT"


# ===========================================================================
# Take-off-shelf in-use guard
# ===========================================================================
class TestProjectInUseGuard:

    def test_take_off_shelf_blocked_when_draft_plan_references_project(
        self, api,
    ):
        """PRD §3.1: "Attempting to take an off-shelf action when
        non-terminal plans still reference the project is rejected
        with ERR_PROJECT_IN_USE (HTTP 409)."

        Claim: take-off-shelf with a DRAFT plan referencing the project
        → ERR_PROJECT_IN_USE.
        """
        project, _ = create_on_shelf_project()
        customer = create_kyc_verified_customer()
        # Plan stays in DRAFT, referencing the project.
        create_draft_plan(
            customer_id=customer["id"],
            items=[plan_item(project["id"], "T0", 1)],
            attending_physician_id=ATTENDING_PHYSICIAN_ID,
        )
        res = api.take_project_off_shelf(
            project["id"], TEST_USERS["medical_director_headers"],
        )
        validate_error(res, ApiErrorId.ERR_PROJECT_IN_USE.value)

    def test_take_off_shelf_allowed_with_no_referencing_plans(self, api):
        """PRD §3.1: "Once on shelf, a MedicalDirector may take the
        project off shelf — ON_SHELF to OFF_SHELF — but only when no
        TreatmentPlan in DRAFT or SUBMITTED status references the
        project."

        Claim: take-off-shelf with no plans → status OFF_SHELF.
        """
        project, _ = create_on_shelf_project()
        off = take_project_off_shelf(project["id"])
        assert off["status"] == "OFF_SHELF"


# ===========================================================================
# difficulty: compensating_invariant/project_inventory_invariant_on_off_shelf_return
# ===========================================================================
class TestOnShelfInventoryInvariant:
    """PRD §3.1: take-off-shelf + return-to-shelf must restore the
    on-shelf catalog count. The forward action decrements the count;
    the compensating action restores it.
    """

    def test_on_shelf_count_round_trip_unchanged(self, api):
        """PRD §3.1: "A project that is currently off shelf may be
        returned to shelf again by a MedicalDirector, with the
        transition OFF_SHELF to ON_SHELF."

        Claim: after take-off-shelf + return-to-shelf, status is
        ON_SHELF and the COUNT(Project where status='ON_SHELF') is
        unchanged from the pre-action snapshot.

        # difficulty: compensating_invariant/project_inventory_invariant_on_off_shelf_return
        """
        # Seed three ON_SHELF projects.
        p1, _ = create_on_shelf_project()
        p2, _ = create_on_shelf_project()
        p3, _ = create_on_shelf_project()
        before = list_projects(params={"status": "ON_SHELF", "limit": 100})
        # Allow the response to be either an array directly or a row
        # list under common pagination conventions.
        before_rows = before if isinstance(before, list) else before
        before_count_initial = count_rows(before_rows, status="ON_SHELF")
        assert before_count_initial >= 3

        # Forward action: take p2 off shelf.
        off = take_project_off_shelf(p2["id"])
        assert off["status"] == "OFF_SHELF"

        intermediate = list_projects(
            params={"status": "ON_SHELF", "limit": 100},
        )
        intermediate_rows = (
            intermediate if isinstance(intermediate, list) else intermediate
        )
        intermediate_count = count_rows(intermediate_rows, status="ON_SHELF")
        assert intermediate_count == before_count_initial - 1, (
            f"on_shelf count must decrement by 1 after take-off-shelf; "
            f"before={before_count_initial}, after={intermediate_count}"
        )

        # Compensating action: return p2 to shelf.
        restored = return_project_to_shelf(p2["id"])
        assert restored["status"] == "ON_SHELF"

        after = list_projects(params={"status": "ON_SHELF", "limit": 100})
        after_rows = after if isinstance(after, list) else after
        after_count = count_rows(after_rows, status="ON_SHELF")
        assert after_count == before_count_initial, (
            f"on_shelf count must be restored after return-to-shelf; "
            f"before={before_count_initial}, after={after_count}"
        )

    def test_returned_project_status_is_on_shelf(self, api):
        """PRD §3.1: "A project that is currently off shelf may be
        returned to shelf again by a MedicalDirector, with the
        transition OFF_SHELF to ON_SHELF."

        Claim: after the compensating action, Project.status ==
        'ON_SHELF'.

        # difficulty: compensating_invariant/project_inventory_invariant_on_off_shelf_return
        """
        project, _ = create_on_shelf_project()
        take_project_off_shelf(project["id"])
        restored = return_project_to_shelf(project["id"])
        assert restored["status"] == "ON_SHELF"


# ===========================================================================
# Wrong-state transitions
# ===========================================================================
class TestProjectInvalidTransitions:

    def test_approve_draft_rejected(self, api):
        """PRD §3.1: "From UNDER_REVIEW a MedicalDirector may take one
        of two actions: an approval which advances the project to
        ON_SHELF and writes the acting user's id into reviewer_id, or
        a rejection which sends the project back to DRAFT."

        Claim: approve a DRAFT project → ERR_INVALID_STATE.
        """
        sku = create_consumable_sku()
        draft = create_project_draft(sku_id=sku["id"])
        res = api.approve_project(
            draft["id"], TEST_USERS["medical_director_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_return_to_shelf_on_already_on_shelf_rejected(self, api):
        """PRD §3.1: "A project that is currently off shelf may be
        returned to shelf again by a MedicalDirector, with the
        transition OFF_SHELF to ON_SHELF."

        Claim: return-to-shelf on an ON_SHELF project → ERR_INVALID_STATE.
        """
        project, _ = create_on_shelf_project()
        res = api.return_project_to_shelf(
            project["id"], TEST_USERS["medical_director_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
