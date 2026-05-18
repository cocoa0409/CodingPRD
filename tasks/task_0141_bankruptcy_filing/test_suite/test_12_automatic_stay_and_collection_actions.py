"""Automatic stay enforcement: collection action insertion semantics.

PRD §2.7 / §3.4 / §3.10 / §3.11.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_collection_action,
    attempt_collection_action,
    create_case,
    create_creditor,
    create_debtor,
    get_success_data,
    re_get_case,
    setup_ch7_discharged_case,
    setup_draft_case_filing_ready,
    setup_filed_case,
    setup_meeting_held_case,
    setup_meeting_scheduled_case,
    validate_error,
    validate_success,
    file_case,
)


# ===========================================================================
# Collection on DRAFT case — PRD §2.7
# ===========================================================================
class TestCollectionOnDraft:
    """PRD §2.7: 'The stay is false while the case is in DRAFT ... Only
    when the stay is inactive does the CollectionAction outcome become
    PROCESSED with a 201 response, and in that case rejected_reason is
    the empty string.'"""

    def test_collection_action_on_draft_case_is_processed(self, api):
        """PRD §2.7: "Only when the stay is inactive does the
        CollectionAction outcome become PROCESSED with a 201
        response, and in that case rejected_reason is the empty
        string."

        Claim: collection on DRAFT case (stay false) ->
        outcome=PROCESSED, rejected_reason="", 201.
        # difficulty: cross_entity_state_dependency/collection_action_outcome_depends_on_case_stay
        """
        debtor = create_debtor()
        case = create_case(debtor=debtor)
        assert case["automatic_stay_active"] is False
        creditor = create_creditor(creditor_type="GENERAL_UNSECURED")
        resp = attempt_collection_action(
            case=case, creditor=creditor, action_kind="LIEN",
        )
        data = validate_success(resp, expected_status=201)
        assert_collection_action(data)
        assert data["outcome"] == "PROCESSED"
        assert data["rejected_reason"] == ""


# ===========================================================================
# Collection on FILED case (stay active) — PRD §2.7
# ===========================================================================
class TestCollectionOnFiledCase:
    """PRD §2.7: 'While the stay is active, every collection attempt —
    whether of action_kind GARNISH, LIEN, LAWSUIT, or DUNNING_LETTER
    — is recorded but blocked: the CollectionAction row is still
    persisted (the immutable attempt log is the audit trail of
    creditor behaviour during stay), but its outcome is written as
    REJECTED_STAY, its rejected_reason is written as the string
    AUTOMATIC_STAY_ACTIVE, and the HTTP response is 409
    ERR_AUTOMATIC_STAY_VIOLATION.'"""

    @pytest.mark.parametrize(
        "kind", ["GARNISH", "LIEN", "LAWSUIT", "DUNNING_LETTER"],
    )
    def test_collection_blocked_on_filed_case(self, api, kind):
        """PRD §2.7: "While the stay is active, every collection
        attempt — whether of action_kind GARNISH, LIEN, LAWSUIT, or
        DUNNING_LETTER — is recorded but blocked".
        PRD §2.7: "its outcome is written as REJECTED_STAY, its
        rejected_reason is written as the string
        AUTOMATIC_STAY_ACTIVE, and the HTTP response is 409
        ERR_AUTOMATIC_STAY_VIOLATION."

        Claim: collection on FILED case (stay active) for any
        action_kind -> ERR_AUTOMATIC_STAY_VIOLATION / 409.
        # difficulty: cross_entity_state_dependency/collection_action_outcome_depends_on_case_stay
        """
        debtor, case, _mtr = setup_filed_case()
        assert case["automatic_stay_active"] is True
        creditor = create_creditor(creditor_type="GENERAL_UNSECURED")
        resp = attempt_collection_action(
            case=case, creditor=creditor, action_kind=kind,
        )
        validate_error(
            resp, ApiErrorId.ERR_AUTOMATIC_STAY_VIOLATION.value,
        )


# ===========================================================================
# Stay survives through every active state — PRD §2.7
# ===========================================================================
class TestStayActiveDuringEveryFilingState:
    """PRD §2.7: 'flips to true the instant the case transitions from
    DRAFT to FILED, remains true throughout FILED, MEETING_SCHEDULED,
    MEETING_HELD, PLAN_PROPOSED, PLAN_CONFIRMED, and IN_REPAYMENT'."""

    def test_stay_active_in_meeting_scheduled(self, api):
        """PRD §2.7: "remains true throughout FILED, MEETING_SCHEDULED,
        MEETING_HELD, PLAN_PROPOSED, PLAN_CONFIRMED, and
        IN_REPAYMENT".

        Claim: a case in MEETING_SCHEDULED has stay active and a new
        collection attempt is blocked.
        """
        debtor, case, _mtr, _md = setup_meeting_scheduled_case()
        assert case["automatic_stay_active"] is True
        creditor = create_creditor(creditor_type="GENERAL_UNSECURED")
        resp = attempt_collection_action(case=case, creditor=creditor)
        validate_error(
            resp, ApiErrorId.ERR_AUTOMATIC_STAY_VIOLATION.value,
        )

    def test_stay_active_in_meeting_held(self, api):
        """PRD §2.7: "remains true throughout FILED, MEETING_SCHEDULED,
        MEETING_HELD".

        Claim: stay active in MEETING_HELD blocks collection.
        """
        debtor, case, _mtr, _cr, _claims = setup_meeting_held_case()
        assert case["automatic_stay_active"] is True
        creditor = create_creditor(creditor_type="GENERAL_UNSECURED")
        resp = attempt_collection_action(case=case, creditor=creditor)
        validate_error(
            resp, ApiErrorId.ERR_AUTOMATIC_STAY_VIOLATION.value,
        )


# ===========================================================================
# Stay lifts on DISCHARGED — PRD §2.7
# ===========================================================================
class TestStayLiftsOnDischarged:
    """PRD §2.7: 'flips back to false the instant the case reaches
    DISCHARGED or DISMISSED'."""

    def test_collection_processed_on_discharged_case(self, api):
        """PRD §2.7: "flips back to false the instant the case
        reaches DISCHARGED or DISMISSED."

        Claim: collection against a DISCHARGED case is PROCESSED, not
        REJECTED_STAY.
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_at_collection_insert
        """
        debtor, case, _mtr, _cr, _claims = setup_ch7_discharged_case()
        assert case["status"] == "DISCHARGED"
        assert case["automatic_stay_active"] is False
        creditor = create_creditor(creditor_type="GENERAL_UNSECURED")
        resp = attempt_collection_action(
            case=case, creditor=creditor, action_kind="GARNISH",
        )
        data = validate_success(resp, expected_status=201)
        assert data["outcome"] == "PROCESSED"
        assert data["rejected_reason"] == ""


# ===========================================================================
# Pre/post filing comparison — PRD §3.4 (two-hop cascade)
# ===========================================================================
class TestFilingActivatesStayCascade:
    """PRD §3.4: 'And from this point forward, any CollectionAction
    inserted for this case is gated on the stay as described in §2.7.'

    PRD §2.7: 'flips to true the instant the case transitions from
    DRAFT to FILED'."""

    def test_pre_filing_processed_post_filing_rejected(self, api):
        """PRD §3.4: "And from this point forward, any CollectionAction
        inserted for this case is gated on the stay as described in
        §2.7."
        PRD §2.7: "flips to true the instant the case transitions from
        DRAFT to FILED".

        Claim: a CollectionAction inserted while case is DRAFT is
        PROCESSED; after file_case the same case rejects new
        CollectionActions with ERR_AUTOMATIC_STAY_VIOLATION.
        # difficulty: transitive_cascade/case_file_two_hop_stay_then_collection_rejection
        """
        # Build DRAFT case but everything ready to file.
        debtor, case_draft, _sch, _mtr = setup_draft_case_filing_ready(
            chapter_requested="CHAPTER_7",
            monthly_income_cents=200_000, monthly_expenses_cents=100_000,
        )
        creditor = create_creditor(creditor_type="GENERAL_UNSECURED")
        # Pre-filing: processed.
        pre_resp = attempt_collection_action(
            case=case_draft, creditor=creditor, action_kind="GARNISH",
        )
        pre_data = validate_success(pre_resp, expected_status=201)
        assert pre_data["outcome"] == "PROCESSED"

        # File the case.
        case_filed = file_case(case=case_draft, debtor=debtor)
        assert case_filed["automatic_stay_active"] is True

        # Post-filing: rejected.
        post_resp = attempt_collection_action(
            case=case_filed, creditor=creditor, action_kind="GARNISH",
        )
        validate_error(
            post_resp, ApiErrorId.ERR_AUTOMATIC_STAY_VIOLATION.value,
        )


# ===========================================================================
# Listing collection actions — PRD §4
# ===========================================================================
class TestListCollectionActions:
    """PRD §4: 'GET /cases/{case_id}/collection-actions ... Trustee,
    Judge, Creditor'. The list endpoint paginates per §2.3."""

    def test_list_includes_rejected_stay_attempts(self, api):
        """PRD §2.7: "the CollectionAction row is still persisted
        (the immutable attempt log is the audit trail of creditor
        behaviour during stay)".

        Claim: an attempt blocked by stay is still listed in
        /cases/{id}/collection-actions.
        """
        from prd_bench_local_runner.testing import validate_paginated
        debtor, case, _mtr = setup_filed_case()
        creditor = create_creditor(creditor_type="GENERAL_UNSECURED")
        # Attempt and ignore the error response (the row is still
        # persisted per PRD §2.7).
        attempt_collection_action(case=case, creditor=creditor)
        from test_helpers import list_collection_actions
        resp = list_collection_actions(case=case)
        data, meta = validate_paginated(resp)
        # The persisted attempt is in the listing.
        assert isinstance(data, list)
        kinds = [row.get("outcome") for row in data]
        assert "REJECTED_STAY" in kinds, (
            f"expected at least one REJECTED_STAY in listing, got "
            f"outcomes={kinds!r}"
        )
