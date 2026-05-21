"""Transfer application creation, VIN verification, auto-branching,
withdrawal.

PRD §3.4 (transfer workflow) and §3.2 (VIN verification on hold).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_transfer_application,
    create_owner,
    create_transfer_application,
    create_transfer_application_payload,
    create_vehicle,
    date_for_age,
    get_transfer_application,
    get_vehicle,
    make_applicant_headers,
    post_salvage_event,
    validate_error,
    validate_success,
    verify_vin,
    withdraw_application,
)


class TestTransferApplicationCreation:

    def test_create_application_initial_state_draft(self, api):
        """PRD §3.4: "The application enters the workflow in DRAFT,
        with salvage_branch_taken initialized to false, fee_subtotal,
        processing_fee, total_due, paid_at, plate_id, and
        rejection_reason all null."
        """
        owner = create_owner()
        vehicle = create_vehicle()
        app = create_transfer_application(
            owner["id"], vehicle["id"], application_type="TITLE_TRANSFER",
        )
        assert_transfer_application(app)
        assert app["status"] == "DRAFT"
        assert app["salvage_branch_taken"] is False
        assert app["fee_subtotal"] is None
        assert app["processing_fee"] is None
        assert app["total_due"] is None
        assert app["paid_at"] is None
        assert app["plate_id"] is None
        assert app["rejection_reason"] is None

    def test_create_application_trade_in_defaults_to_zero(self, api):
        """PRD §3.4: "an optional trade_in_value (defaulting to 0.00;
        same numeric domain as declared_sale_price but allowed to be
        zero, up to 1000000.00)."
        """
        owner = create_owner()
        vehicle = create_vehicle()
        # Note: not passing trade_in_value
        app = create_transfer_application(
            owner["id"], vehicle["id"], application_type="TITLE_TRANSFER",
        )
        assert app["trade_in_value"] == 0.00

    @pytest.mark.parametrize("application_type", [
        "TITLE_TRANSFER", "INITIAL_REGISTRATION",
    ])
    def test_create_application_each_type(self, api, application_type):
        """PRD §3.4: "application_type (either INITIAL_REGISTRATION for
        a freshly-manufactured vehicle or TITLE_TRANSFER for an
        ownership change — chosen at creation and immutable
        thereafter)."
        """
        owner = create_owner()
        vehicle = create_vehicle()
        app = create_transfer_application(
            owner["id"], vehicle["id"], application_type=application_type,
        )
        assert app["application_type"] == application_type

    def test_declared_sale_price_below_min_rejected(self, api):
        """PRD §3.4: "declared_sale_price ... in either case a positive
        number between 0.01 and 2000000.00 with two decimal places."
        """
        owner = create_owner()
        vehicle = create_vehicle()
        resp = api.create_transfer_application(
            vehicle["id"],
            create_transfer_application_payload(
                application_type="TITLE_TRANSFER",
                applicant_owner_id=owner["id"],
                declared_sale_price=0.00,
            ),
            make_applicant_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestVinVerificationAutoBranching:

    def test_verify_vin_clean_vehicle_auto_emissions_pending(self, api):
        """PRD §3.4: "if Vehicle.title_status is in the set CLEAN or
        REBUILT, the application advances to EMISSIONS_PENDING with no
        further side effects."

        Claim: verify-vin on a CLEAN vehicle → application lands in
        EMISSIONS_PENDING and Vehicle.vin_verification_status flips to
        VERIFIED.
        """
        owner = create_owner()
        vehicle = create_vehicle()
        app = create_transfer_application(
            owner["id"], vehicle["id"], application_type="TITLE_TRANSFER",
        )
        verify_vin(vehicle["id"], app["id"])
        app_after = get_transfer_application(app["id"])
        assert app_after["status"] == "EMISSIONS_PENDING"
        assert app_after["salvage_branch_taken"] is False
        vehicle_after = get_vehicle(vehicle["id"])
        assert vehicle_after["vin_verification_status"] == "VERIFIED"
        assert vehicle_after["vin_verified_at"] is not None

    def test_verify_vin_salvage_vehicle_auto_salvage_review(self, api):
        """PRD §3.4: "if Vehicle.title_status is in the set
        SALVAGE_PENDING_REBUILD or NON_REPAIRABLE, the application
        advances to SALVAGE_REVIEW and salvage_branch_taken is set to
        true."
        """
        owner = create_owner()
        vehicle = create_vehicle()
        # Force vehicle into SALVAGE_PENDING_REBUILD via salvage-event.
        post_salvage_event(vehicle["id"], severity="PARTIAL")
        vehicle_after_salvage = get_vehicle(vehicle["id"])
        assert vehicle_after_salvage["title_status"] == "SALVAGE_PENDING_REBUILD"
        app = create_transfer_application(
            owner["id"], vehicle["id"], application_type="TITLE_TRANSFER",
        )
        verify_vin(vehicle["id"], app["id"])
        app_after = get_transfer_application(app["id"])
        assert app_after["status"] == "SALVAGE_REVIEW"
        assert app_after["salvage_branch_taken"] is True


class TestWithdrawApplication:

    def test_withdraw_draft_application_succeeds(self, api):
        """PRD §3.4: "An Applicant may withdraw a DRAFT application at
        any time before VIN verification; doing so transitions the
        application directly from DRAFT to REJECTED and sets
        rejection_reason to WITHDRAWN."
        """
        owner = create_owner()
        vehicle = create_vehicle()
        app = create_transfer_application(
            owner["id"], vehicle["id"], application_type="TITLE_TRANSFER",
        )
        withdraw_application(owner["id"], app["id"])
        app_after = get_transfer_application(app["id"])
        assert app_after["status"] == "REJECTED"
        assert app_after["rejection_reason"] == "WITHDRAWN"

    def test_withdraw_after_vin_verify_rejected(self, api):
        """PRD §3.4: "No other state allows the applicant-initiated
        withdrawal."

        Claim: withdraw from VIN_VERIFIED/EMISSIONS_PENDING →
        ERR_INVALID_STATE.
        """
        owner = create_owner()
        vehicle = create_vehicle()
        app = create_transfer_application(
            owner["id"], vehicle["id"], application_type="TITLE_TRANSFER",
        )
        verify_vin(vehicle["id"], app["id"])
        resp = api.withdraw_application(
            app["id"], make_applicant_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestOwnerHoldsGuard:

    def test_verify_vin_with_outstanding_holds_unreachable(self, api):
        """PRD §3.1: "Verifying the VIN on a transfer application is
        gated on the owner being clear of holds: if
        outstanding_holds_count is greater than zero, VIN verification
        is rejected with ERR_OWNER_HAS_HOLDS."

        PRD does not declare an external endpoint that mints
        outstanding_holds_count > 0 directly. Since the field is
        computed and PRD §3.1 says "maintained by the system as unpaid
        fees or suspended plates accrue against this owner", we rely
        on a path that produces a suspended plate or unpaid fee. For
        this gate-only test we read the error_id via the priority
        ladder once a hold path is reproducible — see test_07/test_11
        for integrations. This test asserts only that a freshly-created
        Owner with no holds DOES NOT trigger ERR_OWNER_HAS_HOLDS on
        verify-vin.
        """
        owner = create_owner()
        vehicle = create_vehicle()
        app = create_transfer_application(
            owner["id"], vehicle["id"], application_type="TITLE_TRANSFER",
        )
        resp = api.verify_vin(
            vehicle["id"], app["id"], TEST_USERS["vin_verifier_headers"],
        )
        validate_success(resp, expected_status=200)


class TestVinOnHold:

    def test_verify_vin_when_vehicle_status_hold_unreachable_via_api(self, api):
        """PRD §3.2: "If the vehicle's vin_verification_status is HOLD —
        set by some upstream investigative process — the verification
        call is rejected with ERR_VIN_ON_HOLD."

        PRD §3.2 explicitly says HOLD is set by an upstream process; no
        public endpoint mints it. This test confirms a freshly-created
        UNVERIFIED vehicle does NOT trigger ERR_VIN_ON_HOLD.
        """
        owner = create_owner()
        vehicle = create_vehicle()
        app = create_transfer_application(
            owner["id"], vehicle["id"], application_type="TITLE_TRANSFER",
        )
        resp = api.verify_vin(
            vehicle["id"], app["id"], TEST_USERS["vin_verifier_headers"],
        )
        assert resp.status_code == 200
