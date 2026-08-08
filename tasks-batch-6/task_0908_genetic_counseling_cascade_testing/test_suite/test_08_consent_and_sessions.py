"""Consent lifecycle guards and the session-credit ledger.

Translates a queue-A difficulty instance (credit conserved on book+cancel) and queue-B
corner instances (re-sign rejected, revoke-after-disclosure locked, no-show keeps
credit, booking with no credits).
"""
from test_helpers import (
    validate_success, validate_error, make_counselor_headers,
    create_session_payload, create_consent_payload,
    create_family, create_counselor, create_case,
    create_signed_testing_consent, setup_disclosed_case,
)


def _case_with_booked_session(covered_sessions=2):
    fam = create_family(budget=10000)
    gc = create_counselor()
    case = create_case(fam["id"], gc["id"], covered_sessions=covered_sessions)
    hdr = make_counselor_headers(gc["id"])
    session = validate_success(
        api_create_session(case["id"], gc["id"]), 201)
    return {"gc_id": gc["id"], "case_id": case["id"], "session_id": session["id"], "hdr": hdr}


def api_create_session(case_id, gc_id, **overrides):
    from test_helpers import api_client
    return api_client.create_session(
        create_session_payload(case_id, gc_id, **overrides), make_counselor_headers(gc_id))


# --------------------------------------------------------------------------- #
# Difficulty: session_credit_conserved_on_book_then_cancel
# --------------------------------------------------------------------------- #
def test_cancel_session_refunds_credit(api):
    """PRD 3.3: "Cancelling a scheduled session is the compensating path: it moves the
    session to CANCELLED, decrements sessions_used, recomputes sessions_remaining
    (refunding the credit), and frees the counselor's slot."

    Design: Difficulty/compensating_invariant/session_credit_conserved_on_book_then_cancel
    """
    ctx = _case_with_booked_session(covered_sessions=2)
    cancelled = validate_success(api.cancel_session(ctx["session_id"], ctx["hdr"]), 200)
    assert cancelled["status"] == "CANCELLED"
    case = validate_success(api.get_case(ctx["case_id"], ctx["hdr"]), 200)
    assert case["sessions_used"] == 0
    assert case["sessions_remaining"] == 2


def test_session_credit_invariant_after_book_then_cancel(api):
    """PRD 2.8: "A cancelled session is excluded from the count — its credit is refunded
    — so the invariant covered_sessions equals sessions_remaining plus sessions_used
    holds at all times."

    Design: Difficulty/compensating_invariant/session_credit_conserved_on_book_then_cancel
    """
    ctx = _case_with_booked_session(covered_sessions=2)
    validate_success(api.cancel_session(ctx["session_id"], ctx["hdr"]), 200)
    case = validate_success(api.get_case(ctx["case_id"], ctx["hdr"]), 200)
    assert case["covered_sessions"] == 2
    assert case["covered_sessions"] == case["sessions_remaining"] + case["sessions_used"]


# --------------------------------------------------------------------------- #
# Corner: sign_already_signed_consent_rejected
# --------------------------------------------------------------------------- #
def test_sign_already_signed_consent_rejected(api):
    """PRD 3.3: "Signing a pending consent — permitted only while it is PENDING,
    otherwise ERR_CONSENT_INVALID_STATE — moves it to SIGNED and stamps signed_at with
    the current logical clock."

    Design: Corner/state_machines/sign_already_signed_consent_rejected
    """
    fam = create_family(budget=10000)
    gc = create_counselor()
    case = create_case(fam["id"], gc["id"], covered_sessions=1)
    consent = create_signed_testing_consent(case["id"], gc["id"])
    hdr = make_counselor_headers(gc["id"])
    res = api.sign_consent(consent["id"], hdr)
    validate_error(res, "ERR_CONSENT_INVALID_STATE", expected_status=409)
    fetched = validate_success(api.get_consent(consent["id"], hdr), 200)
    assert fetched["status"] == "SIGNED"


# --------------------------------------------------------------------------- #
# Corner: revoke_consent_after_disclosure_rejected
# --------------------------------------------------------------------------- #
def test_revoke_consent_after_disclosure_locked(api):
    """PRD 3.3: "A signed consent may be revoked back to REVOKED, but only while it is
    SIGNED and only if no result has yet been disclosed for the case: once any test
    result for the case reaches DISCLOSED, revocation is locked and rejected with
    ERR_CONSENT_LOCKED_BY_DISCLOSURE."

    Design: Corner/state_machines/revoke_consent_after_disclosure_rejected
    """
    ctx = setup_disclosed_case(
        members=[{"relationship": "SIBLING", "degree": 1, "affected": True,
                  "age_of_onset": 60}],
        classification="VUS", covered_sessions=2)
    hdr = make_counselor_headers(ctx["counselor_id"])
    res = api.revoke_consent(ctx["consent_id"], hdr)
    validate_error(res, "ERR_CONSENT_LOCKED_BY_DISCLOSURE", expected_status=409)
    fetched = validate_success(api.get_consent(ctx["consent_id"], hdr), 200)
    assert fetched["status"] == "SIGNED"


# --------------------------------------------------------------------------- #
# Corner: session_no_show_credit_not_refunded
# --------------------------------------------------------------------------- #
def test_no_show_keeps_credit_consumed(api):
    """PRD 3.3: "Marking a scheduled session as a no-show moves it to NO_SHOW, and its
    credit likewise remains consumed." PRD 2.8: "sessions_used counts the case's sessions
    in SCHEDULED, COMPLETED, or NO_SHOW status, and sessions_remaining is covered_sessions
    minus sessions_used."

    Design: Corner/state_machines/session_no_show_credit_not_refunded
    """
    ctx = _case_with_booked_session(covered_sessions=2)
    no_show = validate_success(api.no_show_session(ctx["session_id"], ctx["hdr"]), 200)
    assert no_show["status"] == "NO_SHOW"
    case = validate_success(api.get_case(ctx["case_id"], ctx["hdr"]), 200)
    assert case["sessions_used"] == 1
    assert case["sessions_remaining"] == 1


# --------------------------------------------------------------------------- #
# Corner: book_session_no_credits_rejected
# --------------------------------------------------------------------------- #
def test_book_session_no_credits_rejected(api):
    """PRD 3.3: "Booking is fiscal: it consumes a session credit, so a case with no
    remaining credits — sessions_remaining not greater than zero — is refused with
    ERR_NO_SESSION_CREDITS".

    Design: Corner/validations/book_session_no_credits_rejected
    """
    fam = create_family(budget=10000)
    gc = create_counselor()
    case = create_case(fam["id"], gc["id"], covered_sessions=0)
    res = api.create_session(
        create_session_payload(case["id"], gc["id"]), make_counselor_headers(gc["id"]))
    validate_error(res, "ERR_NO_SESSION_CREDITS", expected_status=402)
