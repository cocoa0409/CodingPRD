"""Multi-reviewer cross-check, conflict cycle, and finalize (PRD §3.5 / §3.6)."""
from __future__ import annotations

import pytest

from test_helpers import (
    cross_check_clean,
    cross_check_discrepant,
    cross_check_payload,
    discrepancy_item,
    finalize_examination,
    get_presentation,
    make_operator_headers,
    primary_review_clean,
    primary_review_discrepant,
    primary_review_payload,
    reset_examination,
    setup_active_lc,
    setup_presentation_with_clean_documents,
    setup_examined_clean_presentation,
    start_examination,
    start_examination_payload,
    validate_error,
    validate_success,
)
from test_helpers import (
    DEFAULT_PRIMARY_REVIEWER_ID,
    DEFAULT_SECONDARY_REVIEWER_ID,
)


# ===========================================================================
# §3.5 — Examination start / reviewer segregation
# ===========================================================================
class TestExaminationStart:

    def test_start_examination_with_same_reviewer_rejected(self, api):
        """PRD §3.5: 'The IssuingBank starts examination by naming a
        primary_reviewer_id and a secondary_reviewer_id, both of which
        must be Operator users and the secondary must differ from the
        primary, otherwise the request is rejected with
        ERR_REVIEWER_SAME_PERSON.'"""
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        presentation = setup_presentation_with_clean_documents(
            lc=lc, bundle=bundle, drawing_amount_minor_units=5_000,
        )
        res = api.start_examination(
            presentation["id"],
            start_examination_payload(
                primary_reviewer_id="op-same",
                secondary_reviewer_id="op-same",
            ),
            bundle["issuing_bank_headers"],
        )
        validate_error(res, "ERR_REVIEWER_SAME_PERSON")

    def test_start_examination_freezes_documents(self, api):
        """PRD §3.5: 'Starting examination cascades: the presentation
        moves from SUBMITTED to UNDER_EXAMINATION, an ExaminationReport
        is created in IN_PROGRESS with deadline_at set to the
        presentation's presented_at plus 5 banking days ...'."""
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        presentation = setup_presentation_with_clean_documents(
            lc=lc, bundle=bundle, drawing_amount_minor_units=5_000,
        )
        examination = start_examination(
            presentation["id"], bundle["issuing_bank_headers"],
        )
        assert examination["status"] == "IN_PROGRESS"
        snapshot = get_presentation(
            presentation["id"], bundle["beneficiary_headers"],
        )
        assert snapshot["status"] == "UNDER_EXAMINATION"


# ===========================================================================
# §3.6 — Cross-check ordering
# ===========================================================================
class TestReviewOrdering:

    def test_cross_check_before_primary_rejected(self, api):
        """PRD §3.6: 'A cross-check submitted before any primary outcome
        has been recorded is rejected with ERR_REVIEW_OUT_OF_ORDER.'"""
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        presentation = setup_presentation_with_clean_documents(
            lc=lc, bundle=bundle, drawing_amount_minor_units=5_000,
        )
        examination = start_examination(
            presentation["id"], bundle["issuing_bank_headers"],
        )
        # Skip primary; jump straight to cross-check.
        res = api.cross_check(
            examination["id"],
            cross_check_payload(secondary_outcome="CLEAN"),
            make_operator_headers(DEFAULT_SECONDARY_REVIEWER_ID),
        )
        validate_error(res, "ERR_REVIEW_OUT_OF_ORDER")

    def test_double_primary_review_rejected(self, api):
        """PRD §3.6: 'Two reviewers attempting to submit the same
        primary review simultaneously serialise on
        ExaminationReport.primary_outcome: the first writer wins and
        the second receives ERR_REVIEW_ALREADY_RECORDED.'"""
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        presentation = setup_presentation_with_clean_documents(
            lc=lc, bundle=bundle, drawing_amount_minor_units=5_000,
        )
        examination = start_examination(
            presentation["id"], bundle["issuing_bank_headers"],
        )
        primary_review_clean(examination["id"])
        # Second attempt must fail.
        res = api.primary_review(
            examination["id"],
            primary_review_payload(primary_outcome="CLEAN"),
            make_operator_headers(DEFAULT_PRIMARY_REVIEWER_ID),
        )
        validate_error(res, "ERR_REVIEW_ALREADY_RECORDED")


# ===========================================================================
# §3.6 — Cross-check conflict and reset
# ===========================================================================
class TestConflictCycle:

    def test_diverging_outcomes_yield_conflict(self, api):
        """PRD §3.6: 'When primary_outcome equals secondary_outcome the
        report's status advances from PRIMARY_DONE to CROSS_CHECK_DONE;
        when they diverge the status advances instead to CONFLICT.'"""
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        presentation = setup_presentation_with_clean_documents(
            lc=lc, bundle=bundle, drawing_amount_minor_units=5_000,
        )
        examination = start_examination(
            presentation["id"], bundle["issuing_bank_headers"],
        )
        primary_review_clean(examination["id"])
        # Secondary diverges to DISCREPANT.
        res = api.cross_check(
            examination["id"],
            cross_check_payload(
                secondary_outcome="DISCREPANT",
                discrepancies=[discrepancy_item(
                    discrepancy_code="MISSING_DOCUMENT",
                )],
            ),
            make_operator_headers(DEFAULT_SECONDARY_REVIEWER_ID),
        )
        after = validate_success(res)
        assert after["status"] == "CONFLICT", (
            "PRD §3.6: 'when they diverge the status advances instead to CONFLICT'"
        )

    def test_reset_clears_outcomes_and_discrepancies(self, api):
        """PRD §3.6: 'From CONFLICT the IssuingBank may reset the report
        back to IN_PROGRESS, which clears primary_outcome and
        secondary_outcome and deletes every Discrepancy row attached to
        the report; documents nonetheless remain frozen.'"""
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        presentation = setup_presentation_with_clean_documents(
            lc=lc, bundle=bundle, drawing_amount_minor_units=5_000,
        )
        examination = start_examination(
            presentation["id"], bundle["issuing_bank_headers"],
        )
        primary_review_clean(examination["id"])
        cross_check_discrepant(
            examination["id"],
            [discrepancy_item(discrepancy_code="MISSING_DOCUMENT")],
        )
        # Now in CONFLICT — reset.
        res = api.reset_examination(
            examination["id"], bundle["issuing_bank_headers"],
        )
        after = validate_success(res)
        assert after["status"] == "IN_PROGRESS"
        # PRD: 'clears primary_outcome and secondary_outcome'
        assert after.get("primary_outcome") in (None, ""), (
            "PRD §3.6: 'clears primary_outcome'"
        )
        assert after.get("secondary_outcome") in (None, ""), (
            "PRD §3.6: 'clears ... secondary_outcome'"
        )
        # Discrepancies must be deleted.
        disc_res = api.list_discrepancies(
            examination["id"], bundle["issuing_bank_headers"],
        )
        from test_helpers import validate_paginated  # noqa: WPS433
        items, _meta = validate_paginated(disc_res)
        assert len(items) == 0, (
            "PRD §3.6: 'deletes every Discrepancy row attached to the report'"
        )


# ===========================================================================
# §3.6 — Finalize cascades to Presentation
# ===========================================================================
class TestFinalize:

    def test_finalize_clean_promotes_presentation(self, api):
        """PRD §3.6: 'On success, the report's status advances to
        FINALIZED, examined_at is set to the current clock instant,
        final_outcome is computed (CLEAN if and only if both individual
        outcomes are CLEAN, else DISCREPANT) ... and the parent
        Presentation cascades from UNDER_EXAMINATION to either
        EXAMINED_CLEAN or EXAMINED_DISCREPANT.'"""
        lc, bundle, presentation, examination = setup_examined_clean_presentation(
            amount_minor_units=10_000, drawing_amount_minor_units=5_000,
        )
        assert presentation["status"] == "EXAMINED_CLEAN"

    def test_finalize_discrepant_promotes_presentation(self, api):
        """PRD §3.6: 'and the parent Presentation cascades from
        UNDER_EXAMINATION to either EXAMINED_CLEAN or EXAMINED_DISCREPANT.'"""
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        presentation = setup_presentation_with_clean_documents(
            lc=lc, bundle=bundle, drawing_amount_minor_units=5_000,
        )
        examination = start_examination(
            presentation["id"], bundle["issuing_bank_headers"],
        )
        primary_review_discrepant(
            examination["id"],
            [discrepancy_item(discrepancy_code="MISSING_DOCUMENT")],
        )
        cross_check_discrepant(
            examination["id"],
            [discrepancy_item(discrepancy_code="MISSING_DOCUMENT")],
        )
        finalize_examination(examination["id"], bundle["issuing_bank_headers"])
        snapshot = get_presentation(
            presentation["id"], bundle["beneficiary_headers"],
        )
        assert snapshot["status"] == "EXAMINED_DISCREPANT"
