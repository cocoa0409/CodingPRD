"""Complaint submission, triage, mediation, and resolution.

Covers PRD §3.5 complaint paragraphs.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_complaint,
    create_certified_nurse,
    create_complaint_payload,
    escalate_complaint,
    get_success_data,
    make_compliance_officer_headers,
    make_patient_headers,
    resolve_complaint,
    resolve_complaint_payload,
    setup_completed_order,
    submit_complaint,
    triage_complaint,
    validate_error,
    validate_success,
)


class TestComplaintRouting:

    def test_routing_nurse_misconduct_is_nurse_related(
        self, api, compliance_officer_headers,
    ):
        """PRD §3.5: 'A ComplianceOfficer triages the complaint -- the
        SUBMITTED to TRIAGE transition derives routing from category: it
        is NURSE_RELATED when category is NURSE_MISCONDUCT or SAFETY,
        and SERVICE_RELATED for the other three categories.'

        Claim: category=NURSE_MISCONDUCT -> routing=NURSE_RELATED on
        triage.
        """
        setup = setup_completed_order(nurse_specialty="ELDERLY_CARE")
        complaint = submit_complaint(
            setup["order"]["id"], setup["patient_id"],
            category="NURSE_MISCONDUCT",
        )
        assert complaint["stage"] == "SUBMITTED"
        triaged = triage_complaint(complaint["id"])
        assert triaged["stage"] == "TRIAGE"
        assert triaged["routing"] == "NURSE_RELATED"

    def test_routing_safety_is_nurse_related(
        self, api, compliance_officer_headers,
    ):
        """PRD §3.5: 'NURSE_RELATED when category is NURSE_MISCONDUCT or
        SAFETY'."""
        setup = setup_completed_order(nurse_specialty="ELDERLY_CARE")
        complaint = submit_complaint(
            setup["order"]["id"], setup["patient_id"],
            category="SAFETY",
        )
        triaged = triage_complaint(complaint["id"])
        assert triaged["routing"] == "NURSE_RELATED"

    def test_routing_billing_is_service_related(
        self, api, compliance_officer_headers,
    ):
        """PRD §3.5: 'SERVICE_RELATED for the other three categories'
        (BILLING, SERVICE_QUALITY, OTHER)."""
        setup = setup_completed_order(nurse_specialty="ELDERLY_CARE")
        complaint = submit_complaint(
            setup["order"]["id"], setup["patient_id"],
            category="BILLING",
        )
        triaged = triage_complaint(complaint["id"])
        assert triaged["routing"] == "SERVICE_RELATED"


class TestComplaintResolution:

    def test_compensation_exceeds_fee_rejected(
        self, api, compliance_officer_headers,
    ):
        """PRD §3.5: 'The compensation_cents must not exceed the subject
        settlement's gross_fee_cents, otherwise
        ERR_COMPENSATION_EXCEEDS_FEE.'
        """
        setup = setup_completed_order(
            nurse_specialty="ELDERLY_CARE",
            base_price_cents=20000,
        )
        gross = setup["settlement"]["gross_fee_cents"]
        complaint = submit_complaint(
            setup["order"]["id"], setup["patient_id"],
            category="SERVICE_QUALITY",
        )
        triage_complaint(complaint["id"])
        escalate_complaint(complaint["id"])
        res = api.resolve_complaint(
            complaint["id"],
            resolve_complaint_payload(
                decision="UPHOLD",
                compensation_cents=gross + 1,
                rating_impact=0,  # SERVICE_RELATED routing
            ),
            compliance_officer_headers,
        )
        validate_error(res, ApiErrorId.ERR_COMPENSATION_EXCEEDS_FEE.value)

    def test_resolve_uphold_with_compensation_advances_complaint(
        self, api, compliance_officer_headers,
    ):
        """PRD §3.5: 'On a successful upheld resolution that advances
        the complaint to RESOLVED, ... when compensation_cents is
        greater than zero, the amount is added to Settlement.refund_cents,
        and if the settlement was previously FINALIZED or PAID_OUT its
        status is moved to REVERSED'.
        """
        setup = setup_completed_order(
            nurse_specialty="ELDERLY_CARE",
            base_price_cents=20000,
        )
        complaint = submit_complaint(
            setup["order"]["id"], setup["patient_id"],
            category="SERVICE_QUALITY",
        )
        triage_complaint(complaint["id"])
        escalate_complaint(complaint["id"])
        resolved = resolve_complaint(
            complaint["id"],
            decision="UPHOLD",
            compensation_cents=1000,
            rating_impact=0,
        )
        assert resolved["stage"] == "RESOLVED"
        # Settlement should now be REVERSED with refund_cents incremented.
        s = get_success_data(api.get_settlement(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        ))
        assert s["status"] == "REVERSED"
        assert s["refund_cents"] >= 1000


class TestComplaintRatingImpact:

    def test_nurse_related_rating_impact_below_minus_one_invalid(
        self, api, compliance_officer_headers,
    ):
        """PRD §3.5: 'The rating_impact must be in the range [-1.0, 0]
        when routing is NURSE_RELATED, and must be exactly 0 when
        routing is SERVICE_RELATED.'

        Claim: rating_impact=-2 on NURSE_RELATED is outside the allowed
        range and is rejected (ERR_INVALID_REQUEST per §2.5 generic
        request-shape rule).
        """
        setup = setup_completed_order(nurse_specialty="ELDERLY_CARE")
        complaint = submit_complaint(
            setup["order"]["id"], setup["patient_id"],
            category="NURSE_MISCONDUCT",
        )
        triage_complaint(complaint["id"])
        escalate_complaint(complaint["id"])
        res = api.resolve_complaint(
            complaint["id"],
            resolve_complaint_payload(
                decision="UPHOLD",
                rating_impact=-2.0,
            ),
            compliance_officer_headers,
        )
        # PRD §3.5 names the range bound but does not pin a specific
        # error_id for an out-of-range rating_impact; ERR_INVALID_REQUEST
        # is the §2.5 generic-shape rule. Accept either.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            res,
            [
                ApiErrorId.ERR_INVALID_REQUEST.value,
            ],
        )


class TestComplaintNotFound:

    def test_unknown_complaint_404(
        self, api, compliance_officer_headers,
    ):
        from test_helpers import NON_EXISTENT_UUID
        res = api.triage_complaint(
            NON_EXISTENT_UUID, compliance_officer_headers,
        )
        validate_error(res, ApiErrorId.ERR_COMPLAINT_NOT_FOUND.value)
