"""Tests for the AdoptionApplication pipeline: creation through completion.

Covers: PRD Section 3.3 (Adopters and the Application Pipeline),
Table 2 (AdoptionApplication state machine), Table 4 priorities 6, 11-16, 18, 26.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_adoption_application,
    create_adoption_application_payload, reject_application_payload,
    complete_home_visit_payload,
    setup_basic_adoption_scenario, create_submitted_application,
    create_application_under_review, create_reviewed_application,
    create_approved_application, create_completed_application,
    create_application_home_visit_required, create_home_visit_scheduled,
    pay_invoice_in_full, create_available_animal, create_adopter,
    setup_fee_schedule, create_shelter, user_id_from_headers,
)

_manager = TEST_USERS["manager_headers"]
_manager2 = TEST_USERS["manager_headers_2"]
_case_worker = TEST_USERS["case_worker_headers"]
_case_worker2 = TEST_USERS["case_worker_headers_2"]
_case_worker3 = TEST_USERS["case_worker_headers_3"]
_vet = TEST_USERS["vet_headers"]


class TestApplicationCreation:
    """PRD 3.3: CaseWorker submits a new application."""

    def test_create_application_success(self):
        shelter, animal, adopter = setup_basic_adoption_scenario(species="CAT", weight_kg=5.0)
        payload = create_adoption_application_payload(animal["id"], adopter["id"])
        resp = api_client.create_adoption_application(payload, _case_worker)
        data = validate_success(resp, 201)
        assert_adoption_application(data)
        assert data["status"] == "SUBMITTED"
        assert data["shelter_id"] == shelter["id"]
        assert data["animal_id"] == animal["id"]
        assert data["adopter_id"] == adopter["id"]
        # CAT + weight<25 => requires_home_visit False
        assert data["requires_home_visit"] is False

    def test_create_application_requires_home_visit_for_dog(self):
        """species=DOG => requires_home_visit True."""
        shelter, animal, adopter = setup_basic_adoption_scenario(species="DOG", weight_kg=10.0)
        resp = api_client.create_adoption_application(
            create_adoption_application_payload(animal["id"], adopter["id"]),
            _case_worker,
        )
        data = validate_success(resp, 201)
        assert data["requires_home_visit"] is True

    def test_create_application_requires_home_visit_heavy_animal(self):
        """weight_kg >= 25 => requires_home_visit True regardless of species."""
        shelter, animal, adopter = setup_basic_adoption_scenario(species="CAT", weight_kg=30.0)
        resp = api_client.create_adoption_application(
            create_adoption_application_payload(animal["id"], adopter["id"]),
            _case_worker,
        )
        data = validate_success(resp, 201)
        assert data["requires_home_visit"] is True

    def test_create_application_requires_home_visit_boundary_25(self):
        """weight_kg == 25 exactly triggers requires_home_visit True (>= 25)."""
        shelter, animal, adopter = setup_basic_adoption_scenario(species="CAT", weight_kg=25.0)
        resp = api_client.create_adoption_application(
            create_adoption_application_payload(animal["id"], adopter["id"]),
            _case_worker,
        )
        data = validate_success(resp, 201)
        assert data["requires_home_visit"] is True

    def test_create_application_requires_home_visit_boundary_just_below(self):
        """weight_kg == 24.99 + non-DOG => requires_home_visit False."""
        shelter, animal, adopter = setup_basic_adoption_scenario(species="CAT", weight_kg=24.99)
        resp = api_client.create_adoption_application(
            create_adoption_application_payload(animal["id"], adopter["id"]),
            _case_worker,
        )
        data = validate_success(resp, 201)
        assert data["requires_home_visit"] is False

    def test_create_application_animal_not_found(self):
        shelter = create_shelter()
        adopter = create_adopter(shelter_id=shelter["id"])
        payload = create_adoption_application_payload(NON_EXISTENT_UUID, adopter["id"])
        resp = api_client.create_adoption_application(payload, _case_worker)
        validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_FOUND)

    def test_create_application_adopter_not_found(self):
        animal = create_available_animal()
        payload = create_adoption_application_payload(animal["id"], NON_EXISTENT_UUID)
        resp = api_client.create_adoption_application(payload, _case_worker)
        validate_error(resp, ApiErrorId.ERR_ADOPTER_NOT_FOUND)


class TestStartReview:
    """PRD 3.3: /start-review transitions SUBMITTED -> UNDER_REVIEW."""

    def test_start_review_success(self):
        shelter, animal, adopter, app = create_submitted_application(species="CAT", weight_kg=5.0)
        resp = api_client.start_review_application(app["id"], _case_worker)
        data = validate_success(resp)
        assert data["status"] == "UNDER_REVIEW"
        # reviewer_id stamped
        assert data["reviewer_id"] == user_id_from_headers(_case_worker)
        # versions pinned
        assert data["animal_version_pinned"] == animal["version"]
        assert data["adopter_version_pinned"] == adopter["version"]

    def test_start_review_application_not_found(self):
        resp = api_client.start_review_application(NON_EXISTENT_UUID, _case_worker)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND)

    def test_start_review_wrong_state(self):
        """Can only start-review from SUBMITTED."""
        shelter, animal, adopter, app, reviewer = create_reviewed_application()
        resp = api_client.start_review_application(app["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_start_review_animal_not_available(self):
        """Animal must be AVAILABLE on start-review."""
        shelter, animal, adopter, app = create_submitted_application(species="CAT", weight_kg=5.0)
        # Take animal out of AVAILABLE via a hold.
        from test_helpers import create_compliance_hold_payload
        get_success_data(api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], severity="HIGH"), _vet
        ))
        resp = api_client.start_review_application(app["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_AVAILABLE)


class TestCompleteReview:
    """PRD 3.3: /complete-review transitions UNDER_REVIEW -> REVIEWED (no home visit)."""

    def test_complete_review_success(self):
        shelter, animal, adopter, app, reviewer = create_application_under_review(
            species="CAT", weight_kg=5.0
        )
        resp = api_client.complete_review(app["id"], reviewer)
        data = validate_success(resp)
        assert data["status"] == "REVIEWED"

    def test_complete_review_requires_reviewer(self):
        """Only the pinned reviewer can complete-review (ERR_REVIEWER_MISMATCH)."""
        shelter, animal, adopter, app, reviewer = create_application_under_review(
            species="CAT", weight_kg=5.0
        )
        resp = api_client.complete_review(app["id"], _case_worker2)
        validate_error(resp, ApiErrorId.ERR_REVIEWER_MISMATCH)

    def test_complete_review_blocked_when_home_visit_required(self):
        """If requires_home_visit is True, complete-review is not allowed."""
        shelter, animal, adopter, app = create_submitted_application(
            species="DOG", weight_kg=10.0
        )
        get_success_data(api_client.start_review_application(app["id"], _case_worker))
        resp = api_client.complete_review(app["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_HOME_VISIT_REQUIRED)


class TestRequireHomeVisit:
    """PRD 3.3: /require-home-visit transitions UNDER_REVIEW -> HOME_VISIT_REQUIRED."""

    def test_require_home_visit_success(self):
        shelter, animal, adopter, app = create_submitted_application(
            species="DOG", weight_kg=10.0
        )
        get_success_data(api_client.start_review_application(app["id"], _case_worker))
        resp = api_client.require_home_visit(app["id"], _case_worker)
        data = validate_success(resp)
        assert data["status"] == "HOME_VISIT_REQUIRED"

    def test_require_home_visit_reviewer_mismatch(self):
        """Only pinned reviewer can call require-home-visit."""
        shelter, animal, adopter, app = create_submitted_application(
            species="DOG", weight_kg=10.0
        )
        get_success_data(api_client.start_review_application(app["id"], _case_worker))
        resp = api_client.require_home_visit(app["id"], _case_worker2)
        validate_error(resp, ApiErrorId.ERR_REVIEWER_MISMATCH)


class TestApprove:
    """PRD 3.3: /approve REVIEWED -> APPROVED with segregation of duties."""

    def test_approve_success(self):
        shelter, animal, adopter, app, invoice, reviewer, approver = \
            create_approved_application(species="CAT", weight_kg=5.0)
        assert app["status"] == "APPROVED"
        assert app["approver_id"] == user_id_from_headers(approver)
        assert app["fee_invoice_id"] == invoice["id"]
        # Animal must be ADOPTION_PENDING
        refreshed_animal = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed_animal["status"] == "ADOPTION_PENDING"
        # Invoice must be ISSUED reference_type ADOPTION
        assert invoice["status"] == "ISSUED"
        assert invoice["reference_type"] == "ADOPTION"
        assert invoice["reference_id"] == app["id"]

    def test_approve_self_approval_rejected(self):
        """Reviewer and approver must differ (ERR_SELF_APPROVAL)."""
        # reviewer is CaseWorker role; approver must be ShelterManager role.
        # To test self-approval: reviewer must also be a ShelterManager user with
        # approval authority. But the PRD requires CaseWorker role for review and
        # ShelterManager role for approval. Segregation-of-duties means same X-User-ID
        # must not sit on both sides. Since the user IDs are distinct across roles,
        # self-approval would only occur if a user holds both roles with the same id.
        # The PRD says caller's X-User-ID must differ from reviewer_id. To trigger
        # ERR_SELF_APPROVAL cleanly, we use the same user ID string for both calls —
        # though the role differs, the ID comparison fires first.
        shelter, animal, adopter, app, reviewer = create_reviewed_application(
            species="CAT", weight_kg=5.0, reviewer_headers=_case_worker
        )
        setup_fee_schedule(shelter["id"])
        # Build manager headers using same user id as reviewer.
        from test_helpers import build_user_headers
        reviewer_user_id = user_id_from_headers(reviewer)
        collision_headers = build_user_headers(reviewer_user_id, "ShelterManager")
        resp = api_client.approve_application(app["id"], collision_headers)
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL)

    def test_approve_wrong_state(self):
        """Cannot approve from SUBMITTED or UNDER_REVIEW."""
        shelter, animal, adopter, app = create_submitted_application(
            species="CAT", weight_kg=5.0
        )
        resp = api_client.approve_application(app["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_approve_stale_animal_data(self):
        """If animal version changes after start-review, approve fails ERR_STALE_ANIMAL_DATA."""
        shelter, animal, adopter, app, reviewer = create_reviewed_application(
            species="CAT", weight_kg=5.0
        )
        setup_fee_schedule(shelter["id"])
        # Bump animal.version via a PATCH.
        get_success_data(api_client.update_animal(
            animal["id"], {"name": "NewName"}, _case_worker
        ))
        resp = api_client.approve_application(app["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_STALE_ANIMAL_DATA)

    def test_approve_stale_adopter_data(self):
        """If adopter version changes, approve fails ERR_STALE_ADOPTER_DATA."""
        shelter, animal, adopter, app, reviewer = create_reviewed_application(
            species="CAT", weight_kg=5.0
        )
        setup_fee_schedule(shelter["id"])
        get_success_data(api_client.update_adopter(
            adopter["id"], {"phone": "+15559999"}, _case_worker
        ))
        resp = api_client.approve_application(app["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_STALE_ADOPTER_DATA)

    def test_approve_blocked_by_hold_on_animal(self):
        """ACTIVE HIGH hold created between review and approve blocks approve."""
        shelter, animal, adopter, app, reviewer = create_reviewed_application(
            species="CAT", weight_kg=5.0
        )
        setup_fee_schedule(shelter["id"])
        from test_helpers import create_compliance_hold_payload
        get_success_data(api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], severity="HIGH"), _vet
        ))
        resp = api_client.approve_application(app["id"], _manager)
        # Either ERR_COMPLIANCE_HOLD_ACTIVE or ERR_ANIMAL_NOT_AVAILABLE (since animal
        # went to UNAVAILABLE). PRD 3.3 lists ERR_ANIMAL_NOT_AVAILABLE for state-based,
        # and Table 4 priority 9 lists ERR_COMPLIANCE_HOLD_ACTIVE. Both are valid.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_COMPLIANCE_HOLD_ACTIVE.value,
            ApiErrorId.ERR_ANIMAL_NOT_AVAILABLE.value,
        ])

    def test_approve_blocked_by_suspended_shelter(self):
        """Shelter suspended after review blocks approve."""
        shelter, animal, adopter, app, reviewer = create_reviewed_application(
            species="CAT", weight_kg=5.0
        )
        setup_fee_schedule(shelter["id"])
        get_success_data(api_client.suspend_shelter(shelter["id"], _manager))
        resp = api_client.approve_application(app["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_SHELTER_SUSPENDED)


class TestReject:
    """PRD 3.3: /reject REVIEWED -> REJECTED with mandatory reason."""

    def test_reject_success(self):
        shelter, animal, adopter, app, reviewer = create_reviewed_application(
            species="CAT", weight_kg=5.0
        )
        resp = api_client.reject_application(
            app["id"], reject_application_payload("Not a good match"), _manager
        )
        data = validate_success(resp)
        assert data["status"] == "REJECTED"
        assert data["rejection_reason"] == "Not a good match"

    def test_reject_self_rejection_forbidden(self):
        """Rejecter must differ from reviewer."""
        shelter, animal, adopter, app, reviewer = create_reviewed_application(
            species="CAT", weight_kg=5.0, reviewer_headers=_case_worker
        )
        from test_helpers import build_user_headers
        reviewer_user_id = user_id_from_headers(reviewer)
        collision_headers = build_user_headers(reviewer_user_id, "ShelterManager")
        resp = api_client.reject_application(
            app["id"], reject_application_payload(), collision_headers
        )
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL)

    def test_reject_missing_reason(self):
        """rejection_reason is mandatory."""
        shelter, animal, adopter, app, reviewer = create_reviewed_application(
            species="CAT", weight_kg=5.0
        )
        resp = api_client.reject_application(app["id"], {}, _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_reject_wrong_state(self):
        shelter, animal, adopter, app = create_submitted_application(species="CAT", weight_kg=5.0)
        resp = api_client.reject_application(
            app["id"], reject_application_payload(), _manager
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_reject_reverts_animal_to_available(self):
        """After a REJECTED application whose animal was ADOPTION_PENDING, the animal
        reverts to AVAILABLE — but only if it had moved to ADOPTION_PENDING. Since
        /reject is only from REVIEWED (animal still AVAILABLE), status should stay."""
        shelter, animal, adopter, app, reviewer = create_reviewed_application(
            species="CAT", weight_kg=5.0
        )
        get_success_data(api_client.reject_application(
            app["id"], reject_application_payload(), _manager
        ))
        refreshed = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed["status"] == "AVAILABLE"


class TestComplete:
    """PRD 3.3: /complete APPROVED -> COMPLETED (requires paid invoice)."""

    def test_complete_success(self):
        shelter, animal, adopter, app, invoice = create_completed_application(
            species="CAT", weight_kg=5.0
        )
        assert app["status"] == "COMPLETED"
        # Animal -> ADOPTED
        refreshed = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed["status"] == "ADOPTED"
        # Counters
        refreshed_shelter = get_success_data(api_client.get_shelter(shelter["id"], _manager))
        assert refreshed_shelter["adoption_count"] >= 1
        refreshed_adopter = get_success_data(api_client.get_adopter(adopter["id"], _manager))
        assert refreshed_adopter["adoption_history_count"] >= 1

    def test_complete_fails_if_not_paid(self):
        """ERR_FEE_NOT_PAID if invoice is ISSUED."""
        shelter, animal, adopter, app, invoice, reviewer, approver = \
            create_approved_application(species="CAT", weight_kg=5.0)
        # Invoice is ISSUED (unpaid).
        resp = api_client.complete_application(app["id"], reviewer)
        validate_error(resp, ApiErrorId.ERR_FEE_NOT_PAID)

    def test_complete_fails_if_partially_paid(self):
        """Partial payment does not satisfy /complete."""
        shelter, animal, adopter, app, invoice, reviewer, approver = \
            create_approved_application(species="CAT", weight_kg=5.0)
        # Pay only a portion
        from test_helpers import pay_invoice_payload
        half = max(1, invoice["total_amount_cents"] // 2)
        get_success_data(api_client.pay_fee_invoice(
            invoice["id"], pay_invoice_payload(half), _case_worker
        ))
        resp = api_client.complete_application(app["id"], reviewer)
        validate_error(resp, ApiErrorId.ERR_FEE_NOT_PAID)

    def test_complete_wrong_state(self):
        """Cannot /complete an application not in APPROVED."""
        shelter, animal, adopter, app = create_submitted_application(species="CAT", weight_kg=5.0)
        resp = api_client.complete_application(app["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestWithdraw:
    """PRD 3.3: /withdraw from pre-terminal states."""

    def test_withdraw_submitted(self):
        shelter, animal, adopter, app = create_submitted_application(species="CAT", weight_kg=5.0)
        resp = api_client.withdraw_application(app["id"], _case_worker)
        data = validate_success(resp)
        assert data["status"] == "WITHDRAWN"

    def test_withdraw_under_review(self):
        shelter, animal, adopter, app, reviewer = create_application_under_review(
            species="CAT", weight_kg=5.0
        )
        resp = api_client.withdraw_application(app["id"], reviewer)
        data = validate_success(resp)
        assert data["status"] == "WITHDRAWN"

    def test_withdraw_reviewed(self):
        shelter, animal, adopter, app, reviewer = create_reviewed_application(
            species="CAT", weight_kg=5.0
        )
        resp = api_client.withdraw_application(app["id"], reviewer)
        data = validate_success(resp)
        assert data["status"] == "WITHDRAWN"

    def test_withdraw_blocked_from_approved(self):
        """Cannot withdraw an APPROVED application."""
        shelter, animal, adopter, app, invoice, reviewer, approver = \
            create_approved_application(species="CAT", weight_kg=5.0)
        resp = api_client.withdraw_application(app["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_withdraw_blocked_from_rejected(self):
        shelter, animal, adopter, app, reviewer = create_reviewed_application(
            species="CAT", weight_kg=5.0
        )
        get_success_data(api_client.reject_application(
            app["id"], reject_application_payload(), _manager
        ))
        resp = api_client.withdraw_application(app["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_withdraw_cancels_scheduled_home_visit(self):
        """Withdrawing with a SCHEDULED home visit cancels it."""
        shelter, animal, adopter, app, hv, reviewer = create_home_visit_scheduled()
        get_success_data(api_client.withdraw_application(app["id"], reviewer))
        refreshed_hv = get_success_data(api_client.get_home_visit(hv["id"], reviewer))
        assert refreshed_hv["status"] == "CANCELLED"


class TestApplicationRetrieval:
    def test_get_application(self):
        shelter, animal, adopter, app = create_submitted_application(species="CAT", weight_kg=5.0)
        resp = api_client.get_adoption_application(app["id"], _manager)
        data = validate_success(resp)
        assert_adoption_application(data)

    def test_get_application_not_found(self):
        resp = api_client.get_adoption_application(NON_EXISTENT_UUID, _manager)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND)
