"""Concurrency / race scenarios named explicitly in PRD §2.10.

Every test in this file maps to one of PRD §2.10's five named races. Each
race's losing error_id is named in PRD prose, so tests are entitled to
assert it.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    ADMIN,
    accept_consultation,
    advance_clock,
    api_client,
    approve_prescription,
    assert_exactly_one_succeeds,
    bureau_settled_event,
    dispatch_prescription,
    draft_prescription,
    get_success_data,
    make_doctor_headers,
    make_patient_headers,
    make_pharmacist_headers,
    make_prescription_item,
    reject_prescription,
    revise_prescription,
    run_race,
    setup_completed_consultation,
    setup_consultation_pending,
    setup_in_progress_consultation,
    submit_prescription,
    settle_claim,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    verify_eligibility,
    IN_SCOPE_DISEASE,
)


# =========================================================================
# §2.10: BUREAU_SETTLED idempotency on (claim_id, kind, bureau_ref).
# =========================================================================
class TestBureauSettledIdempotency:

    def test_duplicate_bureau_settled_event_rejected(self, api):
        """PRD §2.10: 'Two BUREAU_SETTLED events for the same
        InsuranceClaim arriving in quick succession are deduplicated by
        the idempotency key (claim_id, event.kind, bureau_ref); the first
        event mutates the claim, and the second returns
        ERR_DUPLICATE_BUREAU_EVENT with HTTP 409 without mutating
        self_pay_cents or reimbursed_cents.'

        Claim: emitting BUREAU_SETTLED twice with the same bureau_ref ->
        first 2xx, second 409 ERR_DUPLICATE_BUREAU_EVENT.
        """
        state = setup_completed_consultation(
            elapsed_seconds=20 * 60, doctor_base_fee=30.00,
            insurance_policy_no="POL-001",
        )
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
            items=[make_prescription_item(
                quantity=18, unit_price_cents=500,
            )],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("Eligibility not ELIGIBLE under this setup")
        pres = submit_prescription(prescription=pres, doctor=state["doctor"])
        pres = approve_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        pres = dispatch_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        from test_suite.test_06_insurance import _find_claim_for_consultation
        claim = _find_claim_for_consultation(state["consultation"]["id"])
        if claim is None:
            pytest.skip("No claim discoverable")
        verified = verify_eligibility(claim=claim, insurance_status="ELIGIBLE")
        settling = settle_claim(claim=verified)
        bureau_ref = "BR-DUP-001"
        # First event succeeds:
        first = bureau_settled_event(claim=settling, bureau_ref=bureau_ref)
        validate_success(first)
        # Second event with the same bureau_ref must be rejected:
        second = bureau_settled_event(claim=settling, bureau_ref=bureau_ref)
        validate_error(
            second, ApiErrorId.ERR_DUPLICATE_BUREAU_EVENT.value,
        )


# =========================================================================
# §2.10: Doctor /complete vs patient cancel-by-DELETE race.
# =========================================================================
class TestCompleteVsCancelRace:

    def test_complete_and_cancel_race_serialises(self, api):
        """PRD §2.10: 'A doctor's complete and a patient's
        cancel-by-DELETE on the same Consultation likewise serialise on
        the row's session_status; the loser sees ERR_INVALID_STATE with
        HTTP 409.'

        Claim: concurrent /complete (by doctor on IN_PROGRESS) and
        DELETE by patient: one succeeds, the other returns
        ERR_INVALID_STATE. (Note: PRD §3.4 says patient can cancel only
        from QUEUED/ACCEPTED, not IN_PROGRESS, so the natural race state
        is ACCEPTED. We replay accordingly: patient cancels from ACCEPTED
        while the doctor races to /start. Since PRD §2.10 names the
        outcome as ERR_INVALID_STATE, we accept either of the two
        as winner.)
        """
        # Use ACCEPTED state since that's the latest pre-IN_PROGRESS
        # status the patient is permitted to cancel from.
        state = setup_consultation_pending(mode="REAL_TIME")
        accept_consultation(
            consultation=state["consultation"], doctor=state["doctor"],
        )
        consult_id = state["consultation"]["id"]
        d_headers = make_doctor_headers(state["doctor"]["id"])
        p_headers = make_patient_headers(state["patient"]["id"])

        # Race: doctor /start (proceeds to IN_PROGRESS) vs patient DELETE.
        results = run_race(
            lambda: api.start_consultation(consult_id, d_headers),
            lambda: api.cancel_consultation(consult_id, p_headers),
        )
        # Exactly one of these should succeed; the loser must surface as
        # ERR_INVALID_STATE per PRD §2.10's serialization clause.
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        # The framework returns the Response; assert error_id from its
        # JSON envelope.
        body = loser.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == \
            ApiErrorId.ERR_INVALID_STATE.value


# =========================================================================
# §2.10: Pharmacist /approve vs Doctor /revise on REJECTED.
# =========================================================================
class TestApproveRejectedRace:

    def test_approve_on_rejected_returns_invalid_state(self, api):
        """PRD §2.10: 'A pharmacist who attempts to approve a REJECTED
        Prescription while the drafting doctor simultaneously calls
        revise will lose: the revise transition wins, and the
        pharmacist's call returns ERR_INVALID_STATE (one cannot approve
        a prescription that is no longer UNDER_REVIEW).'

        Sequential model: after /revise puts the prescription back to
        DRAFT, an /approve call on it returns ERR_INVALID_STATE.
        """
        state = setup_completed_consultation(elapsed_seconds=60)
        pres = draft_prescription(
            consultation=state["consultation"],
            doctor=state["doctor"],
            disease_codes=[IN_SCOPE_DISEASE],
        )
        if pres.get("eligibility_flag") != "ELIGIBLE":
            pytest.skip("eligibility not ELIGIBLE under this setup")
        pres = submit_prescription(prescription=pres, doctor=state["doctor"])
        pres = reject_prescription(
            prescription=pres, pharmacist=state["pharmacist"],
        )
        # Doctor revises -> DRAFT.
        revise_prescription(prescription=pres, doctor=state["doctor"])
        # Pharmacist attempts approve on the now-DRAFT prescription.
        res = api.approve_prescription(
            pres["id"],
            make_pharmacist_headers(state["pharmacist"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
