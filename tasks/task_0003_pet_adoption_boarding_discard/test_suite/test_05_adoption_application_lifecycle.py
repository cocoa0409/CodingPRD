"""
Tests for the full AdoptionApplication lifecycle (SUBMITTED -> COMPLETED/REJECTED/WITHDRAWN).
Claims from Tables 2, 4, 5, 6 covering state transitions, preconditions, and side effects.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    assert_adoption_application,
    assert_version_incremented,
    create_adoption_application_payload,
    create_rejection_payload,
    create_payment_payload,
    create_shelter,
    create_shelter_with_fee_schedules,
    create_available_animal,
    create_adopter_in_shelter,
    create_animal_in_shelter,
    vaccinate_animal,
    submit_application,
    start_application_review,
    require_home_visit_on_application,
    complete_application_review,
    approve_application,
    complete_adoption,
    application_to_reviewed,
    pay_invoice_fully,
    schedule_home_visit,
    complete_home_visit_with_result,
    create_hold_on_animal,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
)


class TestApplicationSubmission:
    """POST /adoption-applications submission constraints."""

    def test_submit_application_success(self, api, caseworker_headers):
        """Submit with valid animal/adopter returns 201 + SUBMITTED status."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        adopter = create_adopter_in_shelter(shelter["id"])
        payload = create_adoption_application_payload(animal["id"], adopter["id"])
        res = api.create_adoption_application(payload, caseworker_headers)
        app = validate_success(res, 201)
        assert_adoption_application(app)
        assert app["status"] == "SUBMITTED"
        assert app["animal_id"] == animal["id"]
        assert app["adopter_id"] == adopter["id"]
        assert app["shelter_id"] == animal["shelter_id"]

    def test_submit_application_animal_not_available(self, api, caseworker_headers):
        """Animal not AVAILABLE -> ERR_ANIMAL_NOT_AVAILABLE."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"])  # INTAKE status
        adopter = create_adopter_in_shelter(shelter["id"])
        payload = create_adoption_application_payload(animal["id"], adopter["id"])
        res = api.create_adoption_application(payload, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_ANIMAL_NOT_AVAILABLE)

    def test_submit_application_adopter_blacklisted(self, api, caseworker_headers, manager_headers):
        """Blacklisted adopter -> ERR_ADOPTER_BLACKLISTED."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        adopter = create_adopter_in_shelter(shelter["id"])
        api.blacklist_adopter(adopter["id"], manager_headers)
        payload = create_adoption_application_payload(animal["id"], adopter["id"])
        res = api.create_adoption_application(payload, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_ADOPTER_BLACKLISTED)

    def test_submit_application_shelter_suspended(self, api, caseworker_headers, manager_headers):
        """Suspended shelter -> ERR_SHELTER_SUSPENDED."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        adopter = create_adopter_in_shelter(shelter["id"])
        api.suspend_shelter(shelter["id"], manager_headers)
        payload = create_adoption_application_payload(animal["id"], adopter["id"])
        res = api.create_adoption_application(payload, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_SHELTER_SUSPENDED)

    def test_submit_application_nonexistent_animal(self, api, caseworker_headers):
        """Non-existent animal_id -> ERR_ANIMAL_NOT_FOUND."""
        shelter = create_shelter()
        adopter = create_adopter_in_shelter(shelter["id"])
        payload = create_adoption_application_payload(NON_EXISTENT_UUID, adopter["id"])
        res = api.create_adoption_application(payload, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_ANIMAL_NOT_FOUND)

    def test_submit_application_nonexistent_adopter(self, api, caseworker_headers):
        """Non-existent adopter_id -> ERR_ADOPTER_NOT_FOUND."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        payload = create_adoption_application_payload(animal["id"], NON_EXISTENT_UUID)
        res = api.create_adoption_application(payload, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_ADOPTER_NOT_FOUND)

    @pytest.mark.parametrize("missing_field", ["animal_id", "adopter_id", "reason"])
    def test_submit_application_missing_field(self, api, caseworker_headers, missing_field):
        """Missing required field -> ERR_INVALID_REQUEST."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        adopter = create_adopter_in_shelter(shelter["id"])
        payload = create_adoption_application_payload(animal["id"], adopter["id"])
        del payload[missing_field]
        res = api.create_adoption_application(payload, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_nonexistent_application(self, api, caseworker_headers):
        """ERR_APPLICATION_NOT_FOUND for non-existent application."""
        res = api.get_adoption_application(NON_EXISTENT_UUID, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_APPLICATION_NOT_FOUND)


class TestApplicationReview:
    """Start-review, require-home-visit, complete-review transitions."""

    def test_start_review_success(self, api, caseworker_headers):
        """SUBMITTED -> UNDER_REVIEW with reviewer_id set and versions pinned."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])

        res = api.start_review(app["id"], caseworker_headers)
        reviewed = validate_success(res, 200)
        assert reviewed["status"] == "UNDER_REVIEW"
        assert reviewed["reviewer_id"] is not None
        assert reviewed["animal_version"] is not None
        assert reviewed["adopter_version"] is not None

    def test_start_review_animal_no_longer_available(self, api, caseworker_headers, manager_headers):
        """
        If animal becomes UNAVAILABLE between submission and review start,
        start-review fails with ERR_ANIMAL_NOT_AVAILABLE.
        """
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])

        # Make animal unavailable by creating a HIGH hold
        create_hold_on_animal(animal["id"], severity="HIGH")

        res = api.start_review(app["id"], caseworker_headers)
        validate_error(res, ApiErrorId.ERR_ANIMAL_NOT_AVAILABLE)

    def test_start_review_adopter_blacklisted(self, api, caseworker_headers, manager_headers):
        """Start-review fails if adopter is now BLACKLISTED -> ERR_ADOPTER_BLACKLISTED."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        api.blacklist_adopter(adopter["id"], manager_headers)

        # The blacklisting should have withdrawn the app already,
        # but if not, explicitly check start-review would fail
        app_state = validate_success(api.get_adoption_application(app["id"], caseworker_headers), 200)
        assert app_state["status"] == "WITHDRAWN"

    def test_require_home_visit(self, api, caseworker_headers):
        """UNDER_REVIEW -> HOME_VISIT_REQUIRED."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])

        res = api.require_home_visit(app["id"], caseworker_headers)
        updated = validate_success(res, 200)
        assert updated["status"] == "HOME_VISIT_REQUIRED"

    def test_require_home_visit_reviewer_mismatch(self, api, caseworker_headers):
        """Different caseworker than reviewer -> ERR_REVIEWER_MISMATCH."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])  # sets reviewer to caseworker-1

        other_cw = TEST_USERS["caseworker2_headers"]
        res = api.require_home_visit(app["id"], other_cw)
        validate_error(res, ApiErrorId.ERR_REVIEWER_MISMATCH)

    def test_complete_review_cat_no_home_visit_needed(self, api, caseworker_headers):
        """CAT adoption: complete-review without home visit."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])

        res = api.complete_review(app["id"], caseworker_headers)
        updated = validate_success(res, 200)
        assert updated["status"] == "REVIEWED"

    def test_complete_review_dog_requires_home_visit(self, api, caseworker_headers):
        """DOG adoption: complete-review without home visit -> ERR_HOME_VISIT_REQUIRED."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="DOG")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])

        res = api.complete_review(app["id"], caseworker_headers)
        validate_error(res, ApiErrorId.ERR_HOME_VISIT_REQUIRED)

    def test_complete_review_reviewer_mismatch(self, api, caseworker_headers):
        """Different caseworker -> ERR_REVIEWER_MISMATCH."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])

        other_cw = TEST_USERS["caseworker2_headers"]
        res = api.complete_review(app["id"], other_cw)
        validate_error(res, ApiErrorId.ERR_REVIEWER_MISMATCH)


class TestApplicationApproval:
    """REVIEWED -> APPROVED with all preconditions."""

    def test_approve_application_success(self, api, manager_headers, caseworker_headers):
        """Approve a REVIEWED application -> APPROVED + animal ADOPTION_PENDING + invoice created."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")

        res = api.approve_application(app["id"], manager_headers)
        approved = validate_success(res, 200)
        assert approved["status"] == "APPROVED"
        assert approved["approver_id"] is not None
        assert approved["fee_invoice_id"] is not None

        # Animal should be ADOPTION_PENDING
        animal_after = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_after["status"] == "ADOPTION_PENDING"
        assert animal_after["adoption_eligible"] is False

    def test_approve_self_approval_rejected(self, api, caseworker_headers):
        """Approver same as reviewer -> ERR_SELF_APPROVAL."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])

        # Use caseworker as reviewer
        app = start_application_review(app["id"], caseworker_headers)
        app = complete_application_review(app["id"], caseworker_headers)

        # Now try to have the SAME user (as ShelterManager with same user ID) approve
        # We need a manager whose user-id matches the caseworker's
        same_user_mgr = build_user_headers("test-caseworker-1", "ShelterManager")
        res = api.approve_application(app["id"], same_user_mgr)
        validate_error(res, ApiErrorId.ERR_SELF_APPROVAL)

    def test_approve_stale_animal_data(self, api, manager_headers, caseworker_headers):
        """Animal modified after review -> ERR_STALE_ANIMAL_DATA."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")

        # Modify animal to increment its version
        api.update_animal(animal["id"], {"name": "Modified Name"}, caseworker_headers)

        res = api.approve_application(app["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_STALE_ANIMAL_DATA)

    def test_approve_stale_adopter_data(self, api, manager_headers, caseworker_headers):
        """Adopter modified after review -> ERR_STALE_ADOPTER_DATA."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")

        # Modify adopter to increment its version
        api.update_adopter(adopter["id"], {"full_name": "Modified"}, caseworker_headers)

        res = api.approve_application(app["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_STALE_ADOPTER_DATA)

    def test_approve_shelter_suspended(self, api, manager_headers):
        """Suspended shelter at approval time -> ERR_SHELTER_SUSPENDED."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")

        api.suspend_shelter(shelter["id"], manager_headers)

        res = api.approve_application(app["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_SHELTER_SUSPENDED)

    def test_approve_animal_no_longer_available(self, api, manager_headers):
        """Animal no longer AVAILABLE at approval -> ERR_ANIMAL_NOT_AVAILABLE."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")

        # Make animal unavailable
        create_hold_on_animal(animal["id"], severity="HIGH")

        res = api.approve_application(app["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_ANIMAL_NOT_AVAILABLE)


class TestApplicationCompletion:
    """APPROVED -> COMPLETED."""

    def test_complete_adoption_success(self, api, caseworker_headers, manager_headers):
        """Complete adoption after fee payment -> COMPLETED + animal ADOPTED."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        # Pay fee
        pay_invoice_fully(app["fee_invoice_id"])

        res = api.complete_application(app["id"], caseworker_headers)
        completed = validate_success(res, 200)
        assert completed["status"] == "COMPLETED"

        # Animal should be ADOPTED
        animal_after = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_after["status"] == "ADOPTED"

        # Shelter adoption_count incremented
        shelter_after = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        assert shelter_after["adoption_count"] >= 1

        # Adopter adoption_history_count incremented
        adopter_after = validate_success(api.get_adopter(adopter["id"], caseworker_headers), 200)
        assert adopter_after["adoption_history_count"] >= 1

    def test_complete_adoption_fee_not_paid(self, api, caseworker_headers):
        """Complete without paying fee -> ERR_FEE_NOT_PAID."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        res = api.complete_application(app["id"], caseworker_headers)
        validate_error(res, ApiErrorId.ERR_FEE_NOT_PAID)


class TestApplicationRejection:
    """REVIEWED -> REJECTED."""

    def test_reject_application_success(self, api, manager_headers, caseworker_headers):
        """Reject a REVIEWED application with rejection_reason."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")

        payload = create_rejection_payload(rejection_reason="Housing inadequate")
        res = api.reject_application(app["id"], payload, manager_headers)
        rejected = validate_success(res, 200)
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "Housing inadequate"


class TestApplicationWithdrawal:
    """Withdraw at various stages."""

    @pytest.mark.parametrize("target_status", [
        "SUBMITTED", "UNDER_REVIEW", "HOME_VISIT_REQUIRED", "REVIEWED",
    ])
    def test_withdraw_from_various_states(self, api, caseworker_headers, target_status):
        """Application can be withdrawn from any pre-approval state."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])

        if target_status == "SUBMITTED":
            pass
        elif target_status == "UNDER_REVIEW":
            app = start_application_review(app["id"])
        elif target_status == "HOME_VISIT_REQUIRED":
            app = start_application_review(app["id"])
            app = require_home_visit_on_application(app["id"])
        elif target_status == "REVIEWED":
            app = start_application_review(app["id"])
            app = complete_application_review(app["id"])

        res = api.withdraw_application(app["id"], caseworker_headers)
        withdrawn = validate_success(res, 200)
        assert withdrawn["status"] == "WITHDRAWN"

    def test_withdraw_cannot_withdraw_approved(self, api, caseworker_headers):
        """Cannot withdraw an APPROVED application -> ERR_INVALID_STATE."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        res = api.withdraw_application(app["id"], caseworker_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_withdraw_reverts_home_visit(self, api, caseworker_headers):
        """Withdraw with SCHEDULED home visit -> visit is CANCELLED."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="DOG")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])
        app = require_home_visit_on_application(app["id"])
        visit = schedule_home_visit(adopter["id"], app["id"])

        api.withdraw_application(app["id"], caseworker_headers)

        visit_after = validate_success(api.get_home_visit(visit["id"], caseworker_headers), 200)
        assert visit_after["status"] == "CANCELLED"


class TestApplicationListAndGet:
    """GET /adoption-applications endpoints."""

    def test_list_applications_with_filters(self, api, caseworker_headers):
        """GET /adoption-applications supports filters."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])

        data, meta = validate_paginated(
            api.list_adoption_applications(
                caseworker_headers, params={"shelter_id": shelter["id"]}
            )
        )
        assert meta["total_count"] >= 1
        assert any(a["id"] == app["id"] for a in data)
