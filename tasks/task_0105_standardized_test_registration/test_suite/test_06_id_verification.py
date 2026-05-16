"""ID verification submit / clear / reject cycle tests.

Covers PRD §3.5 — initial state, cross-state rule, expiry rule,
cycle through REJECTED -> DOCS_SUBMITTED.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_id_verification,
    clear_id_verification,
    create_candidate,
    create_event_with_capacity,
    create_test_event,
    create_test_center,
    create_capacity,
    force_confirmed_registration,
    make_candidate_headers,
    reject_id_verification,
    reject_id_payload,
    submit_id_payload,
    submit_id_verification,
    validate_error,
    validate_success,
)


@pytest.fixture
def event_center_candidate_registration():
    """Common preamble: event + center + candidate + confirmed registration."""
    event, center, _ = create_event_with_capacity(
        total_capacity=5, accommodation_capacity=0,
    )
    cand = create_candidate(home_state_code="CA")
    reg = force_confirmed_registration(event["id"], cand, center["id"])
    return event, center, cand, reg


class TestSubmitID:
    def test_submit_advances_not_started_to_docs_submitted(
        self, api, event_center_candidate_registration,
    ):
        """PRD §3.5: "The `IDVerification` row is created with `status`
        of `NOT_STARTED` and immediately transitions to
        `DOCS_SUBMITTED` on the first submission".

        Claim: first submit returns IDVerification.status=DOCS_SUBMITTED.
        """
        event, center, cand, reg = event_center_candidate_registration
        idv = submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="DRIVERS_LICENSE",
            issuing_state_code="CA",
            id_expires_on="2030-01-01",
        )
        assert_id_verification(idv)
        assert idv["status"] == "DOCS_SUBMITTED", (
            "PRD §3.5: first submit lands in DOCS_SUBMITTED"
        )


class TestClearID:
    def test_clear_with_same_state_advances_to_cleared(
        self, api, event_center_candidate_registration,
    ):
        """PRD §3.5: "On successful clearance the row advances to
        `CLEARED`."

        Claim: clear after submit with matching state -> CLEARED.
        """
        event, center, cand, reg = event_center_candidate_registration
        submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="DRIVERS_LICENSE",
            issuing_state_code="CA",
            id_expires_on="2030-01-01",
        )
        cleared = clear_id_verification(event["id"], reg["id"])
        assert cleared["status"] == "CLEARED"

    def test_cross_state_id_without_override_rejected(
        self, api, event_center_candidate_registration,
    ):
        """PRD §3.5: "unless the document type is `PASSPORT`, the
        document's `issuing_state_code` must equal the candidate's
        `home_state_code`; if it does not, clearance is refused with
        `ERR_CROSS_STATE_ID_MISMATCH` unless the `Registrar` supplies
        `allow_cross_state_override` set to true on the clearance
        call."

        Claim: clear without override returns
        ERR_CROSS_STATE_ID_MISMATCH for cross-state non-PASSPORT IDs.
        """
        event, center, cand, reg = event_center_candidate_registration
        submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="DRIVERS_LICENSE",
            issuing_state_code="NY",  # cand.home_state_code = CA
            id_expires_on="2030-01-01",
        )
        res = api.clear_id_verification(
            event["id"], reg["id"],
            TEST_USERS["registrar_headers"],
        )
        validate_error(res, ApiErrorId.ERR_CROSS_STATE_ID_MISMATCH.value)

    def test_cross_state_override_succeeds_and_marks_audit_flag(
        self, api, event_center_candidate_registration,
    ):
        """PRD §3.5: "When the override is used, the row's
        `cross_state_override_granted` flag is set to true as an audit
        trace."

        Claim: clear with allow_cross_state_override=true on a cross-
        state ID succeeds and sets cross_state_override_granted=true.
        """
        event, center, cand, reg = event_center_candidate_registration
        submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="DRIVERS_LICENSE",
            issuing_state_code="NY",
            id_expires_on="2030-01-01",
        )
        res = api.clear_id_verification(
            event["id"], reg["id"],
            TEST_USERS["registrar_headers"],
            {"allow_cross_state_override": True},
        )
        cleared = validate_success(res, 200)
        assert cleared["status"] == "CLEARED"
        assert cleared["cross_state_override_granted"] is True

    def test_passport_exempt_from_state_check(self, api):
        """PRD §3.5: "unless the document type is `PASSPORT`, the
        document's `issuing_state_code` must equal the candidate's
        `home_state_code`".

        Claim: PASSPORT type can clear without matching state, no
        override required.
        """
        from test_helpers import create_event_with_capacity, create_candidate
        event, center, _ = create_event_with_capacity(
            total_capacity=5, accommodation_capacity=0,
        )
        cand = create_candidate(home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="PASSPORT",
            issuing_state_code=None,
            id_expires_on="2030-01-01",
        )
        cleared = clear_id_verification(event["id"], reg["id"])
        assert cleared["status"] == "CLEARED"

    def test_id_expired_on_or_before_test_date_rejected(self, api):
        """PRD §3.5: "the `id_expires_on` date must be strictly later
        than the event's `test_date`; a document that expires on or
        before the test day is rejected with
        `ERR_ID_EXPIRED_BEFORE_TEST`."

        Claim: an id_expires_on equal to test_date is rejected.
        """
        event = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        center = create_test_center()
        create_capacity(event["id"], center["id"], total_capacity=5, accommodation_capacity=0)
        cand = create_candidate(home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        # Submit a document expiring exactly on test_date date.
        submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="DRIVERS_LICENSE",
            issuing_state_code="CA",
            id_expires_on="2026-06-08",
        )
        res = api.clear_id_verification(
            event["id"], reg["id"], TEST_USERS["registrar_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ID_EXPIRED_BEFORE_TEST.value)


class TestRejectAndResubmitCycle:
    def test_reject_then_resubmit_cycle_revisits_docs_submitted(
        self, api, event_center_candidate_registration,
    ):
        """PRD §3.5: "A rejection — invoked with a free-text
        `rejection_reason` — moves the row to `REJECTED` and writes
        the supplied reason into the `rejection_reason` field. From
        `REJECTED`, the candidate may resubmit by calling the submit
        operation again, which advances the row back to
        `DOCS_SUBMITTED` (the cycle through rejection and resubmission
        is by design)."

        Claim: submit -> reject -> submit yields a second
        DOCS_SUBMITTED state, with rejection_reason captured between.
        """
        event, center, cand, reg = event_center_candidate_registration
        # First submit.
        idv1 = submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="DRIVERS_LICENSE",
            issuing_state_code="CA",
            id_expires_on="2030-01-01",
        )
        assert idv1["status"] == "DOCS_SUBMITTED"
        # Reject.
        rejected = reject_id_verification(
            event["id"], reg["id"], rejection_reason="blurry photo",
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "blurry photo"
        # Resubmit (PASSPORT this time) -> back to DOCS_SUBMITTED.
        re_submitted = submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="PASSPORT",
            issuing_state_code=None,
            id_expires_on="2031-01-01",
        )
        assert re_submitted["status"] == "DOCS_SUBMITTED", (
            "PRD §3.5: from REJECTED, submit advances back to DOCS_SUBMITTED"
        )
        assert re_submitted["id_document_type"] == "PASSPORT"
