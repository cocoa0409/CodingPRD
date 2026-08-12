"""Prescription state machine: initial state, lazy expiry, invalid transitions."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_prescription,
    create_prescription_payload,
    set_clock,
    setup_pending_order,
    setup_pending_order_verified,
    validate_error,
    validate_success,
)


class TestPrescriptionInitialState:
    def test_new_prescription_is_pending_verification(self, api, care_coordinator_headers):
        """PRD §3.1: "A new prescription lands in `PENDING_VERIFICATION`."

        Design: Corner/state_machines/prescription_initial_state_pending
        """
        ctx = setup_pending_order()
        # setup_pending_order created the prescription but did not verify it.
        rx = validate_success(
            api.get_prescription(ctx["rx"]["id"], care_coordinator_headers), 200
        )
        assert_prescription(rx)
        assert rx["status"] == "PENDING_VERIFICATION"

    def test_new_prescription_has_no_verifier_or_consumer(self, api, care_coordinator_headers):
        """PRD §3.1: "An `InsuranceSpecialist` then verifies it — moving
        `PENDING_VERIFICATION → VERIFIED` and stamping `verified_by_user_id` with the
        caller's `X-User-ID`" (the stamp exists only once verification happens).
        PRD §3.3: "the supporting prescription cascades `VERIFIED → CONSUMED` with
        `consumed_by_order_id` pointing at this order" (the link exists only once a
        qualifying order consumes it).

        Design: Corner/state_machines/prescription_initial_state_pending
        """
        ctx = setup_pending_order()
        rx = validate_success(
            api.get_prescription(ctx["rx"]["id"], care_coordinator_headers), 200
        )
        assert rx["verified_by_user_id"] is None
        assert rx["consumed_by_order_id"] is None


class TestPrescriptionExpiry:
    def test_verify_after_expiration_flips_to_expired(self, api, care_coordinator_headers,
                                                      insurance_specialist_headers):
        """PRD §3.1: "Verification refuses an expired document: if the current logical
        date is already past `expiration_date`, the prescription transitions
        `PENDING_VERIFICATION → EXPIRED` on the spot and the call is rejected with
        `ERR_PRESCRIPTION_EXPIRED`."

        Design: Corner/state_machines/verify_expired_prescription_lazy_expiry
        """
        ctx = setup_pending_order(rx_overrides={"expiration_date": "2026-05-10"})
        set_clock("2026-05-11T00:00:00Z")

        res = api.verify_prescription(ctx["rx"]["id"], insurance_specialist_headers)
        validate_error(res, ApiErrorId.ERR_PRESCRIPTION_EXPIRED, expected_status=422)

    def test_expired_verify_leaves_prescription_in_expired_state(
        self, api, care_coordinator_headers, insurance_specialist_headers
    ):
        """PRD §2.5: "a prescription that has passed its `expiration_date` flips to
        `EXPIRED` only when a verification, resubmission, or pump-order qualification
        attempt touches it".

        Design: Corner/state_machines/verify_expired_prescription_lazy_expiry
        """
        ctx = setup_pending_order(rx_overrides={"expiration_date": "2026-05-10"})
        set_clock("2026-05-11T00:00:00Z")
        api.verify_prescription(ctx["rx"]["id"], insurance_specialist_headers)

        rx = validate_success(
            api.get_prescription(ctx["rx"]["id"], care_coordinator_headers), 200
        )
        assert rx["status"] == "EXPIRED"


class TestPrescriptionTransitions:
    def test_resubmit_from_verified_rejected(self, api, care_coordinator_headers,
                                             insurance_specialist_headers):
        """PRD §3.1: "a `CareCoordinator` or `InsuranceSpecialist` may resubmit it, moving
        `REJECTED → PENDING_VERIFICATION`" — resubmit is defined only from `REJECTED`, so
        from `VERIFIED` the state-machine precondition fails.
        PRD §2.8: "state-machine preconditions hold, including terminal-state lockdown
        (`ERR_INVALID_STATE`, 409, and the state-specific 409 errors".

        Design: Corner/state_machines/resubmit_from_verified_rejected
        """
        ctx = setup_pending_order_verified()
        res = api.resubmit_prescription(ctx["rx"]["id"], insurance_specialist_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        rx = validate_success(
            api.get_prescription(ctx["rx"]["id"], care_coordinator_headers), 200
        )
        assert rx["status"] == "VERIFIED"
