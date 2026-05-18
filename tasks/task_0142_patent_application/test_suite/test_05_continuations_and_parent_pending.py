"""Continuations / CIPs and the parent-pending precondition.

Covers PRD §3.2 continuation rules.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    create_applicant,
    create_application_payload,
    create_draft_application,
    make_applicant_headers,
    setup_filed_application,
    validate_error,
    validate_success,
)


# ===========================================================================
# Continuation/CIP creation (PRD §3.2)
# ===========================================================================
class TestContinuationCreate:

    def test_continuation_against_filed_parent_succeeds(self, api):
        """PRD §3.2: "when a non-null parent_application_id is supplied,
        the referenced parent must exist, must not itself be a
        PROVISIONAL, must currently have a status that is one of FILED,
        UNDER_EXAMINATION, OFFICE_ACTION_PENDING, ALLOWED, or GRANTED,
        and the supplied continuation_type must be either CONTINUATION
        or CIP".

        Claim: a CONTINUATION draft against a FILED UTILITY parent
        is accepted.
        """
        a, parent = setup_filed_application(application_type="UTILITY")
        payload = create_application_payload(
            applicant_id=a["id"], application_type="UTILITY",
            claim_count=1, independent_claim_count=1,
            parent_application_id=parent["id"],
            continuation_type="CONTINUATION",
        )
        res = api.create_application(payload, make_applicant_headers(a["id"]))
        data = validate_success(res, 201)
        assert data["parent_application_id"] == parent["id"]
        assert data["continuation_type"] == "CONTINUATION"

    def test_cip_against_filed_parent_succeeds(self, api):
        """PRD §3.2: "the supplied continuation_type must be either
        CONTINUATION or CIP"."""
        a, parent = setup_filed_application(application_type="UTILITY")
        payload = create_application_payload(
            applicant_id=a["id"], application_type="UTILITY",
            claim_count=1, independent_claim_count=1,
            parent_application_id=parent["id"],
            continuation_type="CIP",
        )
        res = api.create_application(payload, make_applicant_headers(a["id"]))
        data = validate_success(res, 201)
        assert data["continuation_type"] == "CIP"

    def test_continuation_against_provisional_parent_rejected(self, api):
        """PRD §3.2: "must not itself be a PROVISIONAL ... Any violation
        of the parent-pending constraint is reported as
        ERR_PARENT_NOT_PENDING."
        """
        a, parent = setup_filed_application(application_type="PROVISIONAL")
        payload = create_application_payload(
            applicant_id=a["id"], application_type="UTILITY",
            claim_count=1, independent_claim_count=1,
            parent_application_id=parent["id"],
            continuation_type="CONTINUATION",
        )
        res = api.create_application(payload, make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_PARENT_NOT_PENDING.value)

    def test_continuation_against_draft_parent_rejected(self, api):
        """PRD §3.2: "must currently have a status that is one of
        FILED, UNDER_EXAMINATION, OFFICE_ACTION_PENDING, ALLOWED, or
        GRANTED ... Any violation of the parent-pending constraint is
        reported as ERR_PARENT_NOT_PENDING."

        Claim: a parent still in DRAFT state is NOT in the allowed
        status set, so continuation creation is rejected.
        """
        a = create_applicant(entity_size="SMALL")
        parent = create_draft_application(a, application_type="UTILITY")
        payload = create_application_payload(
            applicant_id=a["id"], application_type="UTILITY",
            claim_count=1, independent_claim_count=1,
            parent_application_id=parent["id"],
            continuation_type="CONTINUATION",
        )
        res = api.create_application(payload, make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_PARENT_NOT_PENDING.value)

    def test_original_filing_with_parent_id_and_none_type_rejected(self, api):
        """PRD §3.2: "with NONE permitted only when the parent reference
        is null". Equivalently, parent_application_id set with
        continuation_type == NONE violates the rule.
        """
        a, parent = setup_filed_application(application_type="UTILITY")
        payload = create_application_payload(
            applicant_id=a["id"], application_type="UTILITY",
            claim_count=1, independent_claim_count=1,
            parent_application_id=parent["id"],
            continuation_type="NONE",
        )
        res = api.create_application(payload, make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_PARENT_NOT_PENDING.value)
