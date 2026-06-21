"""Difficulty Rule 6 — boundary_precision_check.

Boundary tests on different metrics + endpoints: the strict-less-than priority
date vs visa-bulletin cutoff (interview scheduling), and the empty-array
cardinality boundary for RFE evidence (RFE issuance).
"""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    set_clock,
    publish_visa_bulletin,
    register_applicant,
    create_draft_case,
    file_case,
    schedule_biometrics_for,
    setup_under_review_i130,
    make_applicant_headers,
    make_officer_headers,
    schedule_interview_payload,
    issue_rfe_payload,
)


class TestVisaPriorityDateStrictlyLessThanCutoff:
    """priority_date == cutoff_date → RETROGRESSED (strict-less-than)."""

    def test_priority_date_equals_cutoff_rejected_with_visa_retrogressed(self, api):
        """PRD §3.4: "the result is CURRENT precisely when the case's `priority_date`
        is strictly less than the entry's `cutoff_date`, and `RETROGRESSED` otherwise.
        The strict inequality matters: if the priority date equals the cutoff date
        exactly, the result is `RETROGRESSED`, not `CURRENT`."
        PRD §3.5: "A retrogressed bulletin month is rejected with `ERR_VISA_RETROGRESSED`."

        Design: Difficulty/boundary_precision_check/visa_priority_date_strictly_less_than_cutoff_metric_numeric
        """
        # Set clock so file_date stamps to 2026-06-15 — exact equality with cutoff.
        set_clock("2026-06-15T00:00:00Z")
        # Publish a FINAL_ACTION bulletin entry whose cutoff equals the would-be
        # priority_date.
        publish_visa_bulletin("2026-06", "F2A", "WORLDWIDE",
                              "FINAL_ACTION", "2026-06-15")
        applicant = register_applicant(country_of_chargeability="WORLDWIDE")
        case = create_draft_case(applicant, case_type="I-485",
                                 preference_category="F2A")
        filed = file_case(case, applicant)
        assert filed["priority_date"] == "2026-06-15"
        officer = make_officer_headers(filed["assigned_officer_id"])
        # Walk to UNDER_REVIEW via biometrics.
        biom = schedule_biometrics_for(filed["id"], officer,
                                       scheduled_at="2026-06-25T15:00:00Z",
                                       asc_location_code="ASC-SF-04")
        set_clock("2026-06-26T00:00:00Z")
        get_success_data(api.complete_biometrics(biom["id"], officer))
        get_success_data(api.advance_review(filed["id"], officer))

        # Now attempt to schedule the interview — should fail visa retrogression.
        res = api.schedule_interview(
            filed["id"],
            schedule_interview_payload("2026-07-15T16:00:00Z", "FO-SFR"),
            officer,
        )
        validate_error(res, "ERR_VISA_RETROGRESSED")

    def test_priority_date_below_cutoff_passes_visa_gate(self, api):
        """PRD §3.4: "the result is CURRENT precisely when the case's `priority_date`
        is strictly less than the entry's `cutoff_date`"

        Design: Difficulty/boundary_precision_check/visa_priority_date_strictly_less_than_cutoff_metric_numeric
        """
        # File at 2026-06-14 so priority_date < cutoff (2026-06-15).
        set_clock("2026-06-14T00:00:00Z")
        publish_visa_bulletin("2026-06", "F2A", "WORLDWIDE",
                              "FINAL_ACTION", "2026-06-15")
        applicant = register_applicant(country_of_chargeability="WORLDWIDE")
        case = create_draft_case(applicant, case_type="I-485",
                                 preference_category="F2A")
        filed = file_case(case, applicant)
        assert filed["priority_date"] == "2026-06-14"
        officer = make_officer_headers(filed["assigned_officer_id"])
        biom = schedule_biometrics_for(filed["id"], officer,
                                       scheduled_at="2026-06-25T15:00:00Z",
                                       asc_location_code="ASC-SF-21")
        set_clock("2026-06-26T00:00:00Z")
        get_success_data(api.complete_biometrics(biom["id"], officer))
        get_success_data(api.advance_review(filed["id"], officer))

        # Schedule the interview — should pass.
        res = api.schedule_interview(
            filed["id"],
            schedule_interview_payload("2026-07-15T16:00:00Z", "FO-SFR"),
            officer,
        )
        # 201 per §2.12 (creating a new interview appointment).
        assert res.status_code == 201


class TestRfeEvidenceItemsEmptyArrayRejected:
    """Cardinality boundary: evidence_items_requested length == 0 is rejected.
    A length-1 request would succeed."""

    def test_empty_evidence_items_array_rejected(self, api):
        """PRD §3.5: "The officer supplies `evidence_items_requested`, an array of strings
        naming the evidence categories being requested; the array length must be
        at least 1 (one or more items requested)."

        Design: Difficulty/boundary_precision_check/rfe_evidence_items_empty_array_rejected_metric_cardinality
        """
        applicant, case_ur, officer_headers = setup_under_review_i130()
        res = api.issue_rfe(
            case_ur["id"],
            issue_rfe_payload(evidence_items_requested=[]),
            officer_headers,
        )
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_singleton_evidence_items_array_succeeds(self, api):
        """PRD §3.5: "the array length must be at least 1 (one or more items requested)"

        Design: Difficulty/boundary_precision_check/rfe_evidence_items_empty_array_rejected_metric_cardinality
        """
        applicant, case_ur, officer_headers = setup_under_review_i130()
        res = api.issue_rfe(
            case_ur["id"],
            issue_rfe_payload(evidence_items_requested=["birth_certificate"]),
            officer_headers,
        )
        # 201 per §2.12 (issuing a new RFE creates a resource).
        assert res.status_code == 201
