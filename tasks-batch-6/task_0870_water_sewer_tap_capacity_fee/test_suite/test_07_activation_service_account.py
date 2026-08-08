"""Payment, activation guards, and service-account creation (PRD §3.7)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    approved_application, setup_ready_for_activation,
    make_applicant_headers, TEST_USERS,
)

REVIEWER = TEST_USERS["reviewer_headers"]


class TestActivateStateBeatsFees:
    """On activate, the state precondition (priority 6) is checked before the fees-paid check
    (priority 17): an APPROVED (not READY) application returns ERR_INVALID_STATE."""

    def test_approved_not_ready_activate_returns_state_error(self, api):
        """PRD §2.10: "Next comes the state-legality check (`ERR_INVALID_STATE`, HTTP 409),
        confirming the target resource is in a state from which the requested transition is
        allowed." PRD §3.7: "Activation ... transitions `READY_FOR_ACTIVATION → ACTIVATED`, and
        its guards are checked in order: the application must be `READY_FOR_ACTIVATION`".

        Design: Difficulty/priority_pair_validation_conflict/activate_state_beats_fees_unpaid
        """
        app = approved_application(service_type="WATER", use_type="RESIDENTIAL", parcel_id="APN-G")
        res = api.activate_application(app["id"], make_applicant_headers("appl-1"))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_state_error_precedes_fees_even_when_paid(self, api):
        """PRD §3.7: "Activation ... transitions `READY_FOR_ACTIVATION → ACTIVATED`, and its
        guards are checked in order: the application must be `READY_FOR_ACTIVATION`".

        Design: Difficulty/priority_pair_validation_conflict/activate_state_beats_fees_unpaid
        """
        app = approved_application(service_type="WATER", use_type="RESIDENTIAL", parcel_id="APN-G2")
        # Even after paying the full amount, the wrong state still blocks activation.
        api.pay_fees(app["id"], {"amount_cents": app["total_fees_due_cents"]},
                     make_applicant_headers("appl-1"))
        res = api.activate_application(app["id"], make_applicant_headers("appl-1"))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_activate_ready_without_fees_rejected(api):
    """PRD §3.7: "and `fees_paid_cents` must be at least `total_fees_due_cents`, or activation
    is rejected with `ERR_FEES_UNPAID` (HTTP 402)."

    Design: Corner/validations/activate_fees_unpaid_when_ready_rejected
    """
    ctx = setup_ready_for_activation(service_type="WATER", use_type="RESIDENTIAL", parcel_id="APN-FU")
    ready = validate_success(api.get_application(ctx["application_id"], REVIEWER), 200)
    assert ready["status"] == "READY_FOR_ACTIVATION"
    res = api.activate_application(ctx["application_id"], make_applicant_headers("appl-1"))
    validate_error(res, ApiErrorId.ERR_FEES_UNPAID.value, expected_status=402)


def test_pay_fees_then_activate_creates_service_account(api):
    """PRD §3.7: "On success, activation creates a **service account** for the application in
    the `ACTIVE` state, with a system-generated `account_number`, carrying the `application_id`."

    Design: Corner/endpoints/pay_fees_and_activate_creates_service_account
    """
    ctx = setup_ready_for_activation(service_type="WATER", use_type="RESIDENTIAL", parcel_id="APN-AC")
    assert ctx["total_fees_due_cents"] == 1287500
    applicant = make_applicant_headers("appl-1")
    api.pay_fees(ctx["application_id"], {"amount_cents": ctx["total_fees_due_cents"]}, applicant)
    activated = validate_success(api.activate_application(ctx["application_id"], applicant), 200)
    assert activated["status"] == "ACTIVATED"
    data, _meta = validate_paginated(
        api.list_service_accounts(applicant, params={"application_id": ctx["application_id"]}))
    assert len(data) == 1
    assert data[0]["status"] == "ACTIVE"
