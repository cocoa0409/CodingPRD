"""Copay authorize/capture/void/refund money path and the clinic ledger
(PRD §2.9, §3.10).

Covers the capture-then-refund money-conservation invariant, the void path that
leaves the ledger untouched, the amount-mismatch fiscal guard, and the
state-vs-fiscal validation-priority conflict on copay authorization.
"""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    fixtures,
)

FRONT = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
PATIENT = TEST_USERS["patient_headers"]


def test_capture_then_refund_conserves_ledger(api):
    """PRD §2.9: "Capturing a copay credits this ledger by the captured amount;
    refunding that same copay debits it by the same amount, so the net effect of
    a capture followed by a refund is exactly zero."
    PRD §3.10: "debits the clinic's `collected_copay_cents` ledger by `amount_cents` (so the net of capture plus refund is zero), and cascades the session's `financial_status` from `COPAY_SETTLED` back to `COPAY_DUE`."

    Design: Difficulty/compensating_invariant/capture_then_refund_money_conserved
    """
    clinic, provider, patient, appt, session, card, payment = fixtures.setup_session_copay_settled(
        clinic_name="C17"
    )
    mid = validate_success(api.get_clinic(clinic["id"], FRONT))
    assert mid["collected_copay_cents"] == 9100, "ledger credited on capture"

    refunded = validate_success(api.refund_copay(payment["id"], BILLING))
    assert refunded["status"] == "REFUNDED"
    assert refunded["refunded_cents"] == 9100

    clinic_after = validate_success(api.get_clinic(clinic["id"], FRONT))
    assert clinic_after["collected_copay_cents"] == 0, "ledger back to zero after refund"

    session_after = validate_success(api.get_intake_session(session["id"], FRONT))
    assert session_after["financial_status"] == "COPAY_DUE"


def test_refund_reverts_financial_status(api):
    """PRD §3.10: "cascades the session's `financial_status` from `COPAY_SETTLED` back to `COPAY_DUE`."

    Design: Difficulty/compensating_invariant/capture_then_refund_money_conserved
    """
    clinic, provider, patient, appt, session, card, payment = fixtures.setup_session_copay_settled(
        clinic_name="C17b"
    )
    settled = validate_success(api.get_intake_session(session["id"], FRONT))
    assert settled["financial_status"] == "COPAY_SETTLED"

    fixtures.api_client.refund_copay(payment["id"], BILLING)
    after = validate_success(api.get_intake_session(session["id"], FRONT))
    assert after["financial_status"] == "COPAY_DUE"


def test_void_authorized_copay_leaves_ledger_unchanged(api):
    """PRD §3.10: "Alternatively, a `BillingClerk` may void an authorized payment, moving it from `AUTHORIZED` to `VOIDED` (requires `AUTHORIZED`, otherwise `ERR_PAYMENT_NOT_AUTHORIZED`)."

    Design: Corner/state_machines/copay_void_path_no_ledger_change
    """
    clinic, provider, patient, appt, session, card, payment = fixtures.setup_session_copay_authorized(
        clinic_name="CE7"
    )
    voided = validate_success(api.void_copay(payment["id"], BILLING))
    assert voided["status"] == "VOIDED"

    clinic_after = validate_success(api.get_clinic(clinic["id"], FRONT))
    assert clinic_after["collected_copay_cents"] == 0, "void never touches the ledger"

    session_after = validate_success(api.get_intake_session(session["id"], FRONT))
    assert session_after["financial_status"] == "COPAY_DUE"


def test_copay_amount_mismatch_on_authorize(api):
    """PRD §3.10: "The authorized `amount_cents` must equal the session's `final_patient_responsibility_cents`; a mismatch is rejected with `ERR_COPAY_AMOUNT_MISMATCH`."

    Design: Corner/validations/copay_amount_mismatch_on_authorize
    """
    clinic, provider, patient, appt, session, card = fixtures.setup_session_copay_due(
        clinic_name="CE13"
    )
    version = fixtures.session_version(session["id"])
    resp = api.create_copay_payment(
        {"intake_session_id": session["id"], "amount_cents": 9000,
         "expected_intake_session_version": version},
        BILLING,
    )
    validate_error(resp, "ERR_COPAY_AMOUNT_MISMATCH")


def test_copay_authorize_state_error_precedes_fiscal(api):
    """PRD §3.10: "The session's financial dimension must be `COPAY_DUE`; if it is not, the authorization is rejected with `ERR_COPAY_NOT_DUE`. The authorized `amount_cents` must equal the session's `final_patient_responsibility_cents`; a mismatch is rejected with `ERR_COPAY_AMOUNT_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_copay_capture
    """
    # Drive the session all the way to COPAY_SETTLED so financial_status is no
    # longer COPAY_DUE; then authorize a fresh payment with a *wrong* amount.
    clinic, provider, patient, appt, session, card, payment = fixtures.setup_session_copay_settled(
        clinic_name="C9"
    )
    settled = validate_success(api.get_intake_session(session["id"], BILLING))
    assert settled["financial_status"] == "COPAY_SETTLED"
    version = settled["version"]

    resp = api.create_copay_payment(
        {"intake_session_id": session["id"], "amount_cents": 8000,
         "expected_intake_session_version": version},
        BILLING,
    )
    # Both the state failure (not COPAY_DUE) and the fiscal failure (8000 != 9100)
    # apply; the state check (priority 6) precedes the fiscal check (priority 15).
    validate_error(resp, "ERR_COPAY_NOT_DUE")


def test_copay_authorize_state_error_precedes_fiscal_second(api):
    """PRD §3.10: "The session's financial dimension must be `COPAY_DUE`; if it is not, the authorization is rejected with `ERR_COPAY_NOT_DUE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_copay_capture
    """
    clinic, provider, patient, appt, session, card, payment = fixtures.setup_session_copay_settled(
        clinic_name="C9b"
    )
    version = fixtures.session_version(session["id"])
    resp = api.create_copay_payment(
        {"intake_session_id": session["id"], "amount_cents": 1,
         "expected_intake_session_version": version},
        BILLING,
    )
    validate_error(resp, "ERR_COPAY_NOT_DUE")


def test_patient_cannot_capture_copay(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/patient_cannot_capture_copay
    """
    clinic, provider, patient, appt, session, card, payment = fixtures.setup_session_copay_authorized(
        clinic_name="CE18"
    )
    resp = api.capture_copay(payment["id"], PATIENT)
    validate_error(resp, "ERR_INSUFFICIENT_PERMISSIONS")
