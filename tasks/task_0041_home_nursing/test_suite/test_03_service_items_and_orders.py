"""Service catalog, order creation, eligibility review, and cancellation.

Covers PRD §3.2.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_NOW_ISO,
    DEFAULT_SCHEDULED_START_ISO,
    NON_EXISTENT_UUID,
    add_days,
    api_client,
    assert_order,
    assert_service_item,
    create_certified_nurse,
    create_order_payload,
    create_order_raw,
    create_package_payload,
    create_package_raw,
    create_service_item_payload,
    create_service_item_raw,
    get_success_data,
    make_patient_headers,
    review_order_payload,
    setup_basic_dispatched_order,
    stable_user_id,
    validate_error,
    validate_success,
)


class TestServiceItemCreate:

    def test_create_service_item_success(self, api, platform_admin_headers):
        """PRD §3.2: 'Each ServiceItem carries a unique catalog code (such
        as IV001), a display name, a patient-facing description and
        clinical contraindications, the single required_skill from the
        same six-tag set the nurses use'.

        Claim: POST /service-items returns 201 with a versioned
        ServiceItem.
        """
        res = api.create_service_item(
            create_service_item_payload(
                required_skill="ELDERLY_CARE",
            ),
            platform_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_service_item(data)
        assert data["required_skill"] == "ELDERLY_CARE"


class TestOrderCreation:

    def test_order_with_inactive_service_item_rejected(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: 'The chosen catalog item must exist and have active
        true (otherwise ERR_RESOURCE_LINK_INVALID).'

        Claim: order against an inactive item -> 422
        ERR_RESOURCE_LINK_INVALID.
        """
        item = create_service_item_raw(required_skill="ELDERLY_CARE")
        # Disable the item.
        # PRD §3.2 says soft-disable via active flag; we model this via
        # the catalog row by issuing a PATCH if available, otherwise via
        # creating an item with `active=false` directly.
        item2 = get_success_data(api.create_service_item(
            create_service_item_payload(
                required_skill="ELDERLY_CARE",
                active=False,
            ),
            platform_admin_headers,
        ))
        patient_id = stable_user_id("patient")
        res = api.create_order(
            create_order_payload(
                service_item_code=item2["code"],
                scheduled_start=DEFAULT_SCHEDULED_START_ISO,
            ),
            make_patient_headers(patient_id),
        )
        validate_error(res, ApiErrorId.ERR_RESOURCE_LINK_INVALID.value)

    def test_order_missing_required_medical_doc(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: 'When the catalog item's requires_medical_doc flag is
        true, the supplied medical_doc_url must be non-empty (otherwise
        ERR_MEDICAL_DOC_REQUIRED).'

        Claim: omit medical_doc_url on item with requires_medical_doc=true
        -> 422 ERR_MEDICAL_DOC_REQUIRED.
        """
        item = create_service_item_raw(
            required_skill="IV_INFUSION",
            requires_medical_doc=True,
        )
        patient_id = stable_user_id("patient")
        res = api.create_order(
            create_order_payload(
                service_item_code=item["code"],
                scheduled_start=DEFAULT_SCHEDULED_START_ISO,
            ),
            make_patient_headers(patient_id),
        )
        validate_error(res, ApiErrorId.ERR_MEDICAL_DOC_REQUIRED.value)

    def test_order_with_medical_doc_succeeds(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: medical_doc_url present satisfies
        requires_medical_doc."""
        item = create_service_item_raw(
            required_skill="IV_INFUSION",
            requires_medical_doc=True,
        )
        nurse = create_certified_nurse(specialty_tags=["IV_INFUSION"])
        patient_id = stable_user_id("patient")
        res = api.create_order(
            create_order_payload(
                service_item_code=item["code"],
                scheduled_start=DEFAULT_SCHEDULED_START_ISO,
                medical_doc_url="https://docs.example/p.pdf",
            ),
            make_patient_headers(patient_id),
        )
        data = validate_success(res, expected_status=201)
        assert_order(data)
        assert data["patient_id"] == patient_id

    def test_order_initial_dispatch_count_zero(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: 'The new order is initialized with status SUBMITTED,
        payment_status UNPAID, and dispatch_attempt_count of 0.'

        Claim: an order whose ServiceItem requires eligibility review
        starts with dispatch_attempt_count=0 (no dispatch yet).
        """
        item = create_service_item_raw(
            required_skill="IV_INFUSION",
            requires_eligibility_review=True,
        )
        patient_id = stable_user_id("patient")
        res = api.create_order(
            create_order_payload(
                service_item_code=item["code"],
                scheduled_start=DEFAULT_SCHEDULED_START_ISO,
            ),
            make_patient_headers(patient_id),
        )
        data = validate_success(res, expected_status=201)
        assert data["dispatch_attempt_count"] == 0


class TestEligibilityReview:

    def test_review_required_item_starts_under_review(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: 'When the catalog item's requires_eligibility_review
        is true, the order auto-routes from SUBMITTED to UNDER_REVIEW
        instead, and the engine waits.'
        """
        item = create_service_item_raw(
            required_skill="IV_INFUSION",
            requires_eligibility_review=True,
        )
        patient_id = stable_user_id("patient")
        order = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            scheduled_start=DEFAULT_SCHEDULED_START_ISO,
        )
        assert order["status"] == "UNDER_REVIEW"

    def test_review_approve_advances_order(
        self, api, compliance_officer_headers,
    ):
        """PRD §3.2: 'Approval moves the order from UNDER_REVIEW to
        AWAITING_DISPATCH and triggers nurse selection'."""
        item = create_service_item_raw(
            required_skill="IV_INFUSION",
            requires_eligibility_review=True,
        )
        nurse = create_certified_nurse(specialty_tags=["IV_INFUSION"])
        patient_id = stable_user_id("patient")
        order = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            scheduled_start=DEFAULT_SCHEDULED_START_ISO,
        )
        assert order["status"] == "UNDER_REVIEW"
        res = api.review_order(
            order["id"], review_order_payload(decision="APPROVE"),
            compliance_officer_headers,
        )
        data = validate_success(res)
        # Order should now be AWAITING_DISPATCH or DISPATCHED (dispatch
        # was created synchronously). PRD §3.2 says "moves the order from
        # UNDER_REVIEW to AWAITING_DISPATCH and triggers nurse selection".
        # Some implementations may have already created a Dispatch row
        # but the Order itself stays AWAITING_DISPATCH until a nurse
        # accepts. PRD §3.3 says Dispatch creation does NOT advance Order
        # status -- only Dispatch acceptance does.
        assert data["status"] == "AWAITING_DISPATCH"

    def test_review_reject_marks_rejected_and_refunds(
        self, api, compliance_officer_headers,
    ):
        """PRD §3.2: 'rejection moves the order from UNDER_REVIEW to
        REJECTED, and if the payment authorization had succeeded by then
        the platform emits a refund event and sets payment_status to
        REFUNDED.'
        """
        item = create_service_item_raw(
            required_skill="IV_INFUSION",
            requires_eligibility_review=True,
        )
        patient_id = stable_user_id("patient")
        order = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            scheduled_start=DEFAULT_SCHEDULED_START_ISO,
        )
        res = api.review_order(
            order["id"], review_order_payload(decision="REJECT"),
            compliance_officer_headers,
        )
        data = validate_success(res)
        assert data["status"] == "REJECTED"
        assert data["payment_status"] == "REFUNDED"


class TestOrderCancellation:

    def test_patient_can_cancel_awaiting_dispatch(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: 'A patient may cancel before the nurse has accepted
        a dispatch -- that is, while the order is in SUBMITTED,
        UNDER_REVIEW, or AWAITING_DISPATCH. Cancellation accepts an
        optional free-text cancelled_reason, transitions the order to
        CANCELLED, flips any still-OFFERED dispatches for the order to
        CANCELLED, and refunds the authorized payment by setting
        payment_status to REFUNDED.'
        """
        setup = setup_basic_dispatched_order()
        order_id = setup["order"]["id"]
        patient_id = setup["patient_id"]
        res = api.cancel_order(
            order_id, make_patient_headers(patient_id),
            {"cancelled_reason": "schedule conflict"},
        )
        data = validate_success(res)
        assert data["status"] == "CANCELLED"
        assert data["payment_status"] == "REFUNDED"

    def test_cancel_after_dispatched_rejected(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: 'Cancellation attempts after the order has reached
        DISPATCHED, IN_PROGRESS, COMPLETED, CANCELLED, or REJECTED are
        rejected with ERR_INVALID_STATE.'
        """
        from test_helpers import accept_dispatch
        setup = setup_basic_dispatched_order()
        accept_dispatch(setup["dispatch"], setup["nurse_id"])
        # Order is now DISPATCHED.
        res = api.cancel_order(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


class TestOrderResourceLink:

    def test_unknown_service_item_code(
        self, api,
    ):
        """PRD §3.2: 'The chosen catalog item must exist and have active
        true (otherwise ERR_RESOURCE_LINK_INVALID).' """
        patient_id = stable_user_id("patient")
        res = api.create_order(
            create_order_payload(
                service_item_code="NOPE-DOES-NOT-EXIST",
                scheduled_start=DEFAULT_SCHEDULED_START_ISO,
            ),
            make_patient_headers(patient_id),
        )
        validate_error(res, ApiErrorId.ERR_RESOURCE_LINK_INVALID.value)

    def test_package_not_found_404(self, api):
        """PRD §3.2: 'When a package_id is supplied, the referenced
        package must exist (ERR_PACKAGE_NOT_FOUND otherwise)'."""
        item = create_service_item_raw(required_skill="IV_INFUSION")
        patient_id = stable_user_id("patient")
        res = api.create_order(
            create_order_payload(
                service_item_code=item["code"],
                scheduled_start=DEFAULT_SCHEDULED_START_ISO,
                package_id=NON_EXISTENT_UUID,
            ),
            make_patient_headers(patient_id),
        )
        validate_error(res, ApiErrorId.ERR_PACKAGE_NOT_FOUND.value)

    def test_package_owned_by_other_patient_rejected(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: 'its patient_id must equal the calling patient's
        X-User-ID (otherwise ERR_RESOURCE_LINK_INVALID)'."""
        item = create_service_item_raw(required_skill="IV_INFUSION")
        owner_id = stable_user_id("owner")
        attacker_id = stable_user_id("attacker")
        package = create_package_raw(
            patient_id=owner_id,
            service_item_code=item["code"],
        )
        res = api.create_order(
            create_order_payload(
                service_item_code=item["code"],
                scheduled_start=DEFAULT_SCHEDULED_START_ISO,
                package_id=package["id"],
            ),
            make_patient_headers(attacker_id),
        )
        validate_error(res, ApiErrorId.ERR_RESOURCE_LINK_INVALID.value)

    def test_package_service_item_mismatch_rejected(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: 'its service_item_code must match the order's
        service_item_code (also ERR_RESOURCE_LINK_INVALID on mismatch)'."""
        item_a = create_service_item_raw(required_skill="IV_INFUSION")
        item_b = create_service_item_raw(required_skill="ELDERLY_CARE")
        patient_id = stable_user_id("patient")
        package = create_package_raw(
            patient_id=patient_id,
            service_item_code=item_a["code"],
        )
        res = api.create_order(
            create_order_payload(
                service_item_code=item_b["code"],
                scheduled_start=DEFAULT_SCHEDULED_START_ISO,
                package_id=package["id"],
            ),
            make_patient_headers(patient_id),
        )
        validate_error(res, ApiErrorId.ERR_RESOURCE_LINK_INVALID.value)
