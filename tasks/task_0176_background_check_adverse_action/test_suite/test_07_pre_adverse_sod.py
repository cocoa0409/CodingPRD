"""Pre-Adverse Action, segregation-of-duties, and AdverseActionFlow
creation — PRD §3.6, §2.11.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_adverse_action_flow,
    criminal_raw_finding,
    education_raw_finding,
    make_adjudicator_headers,
    make_recruiter_headers,
    open_order,
    record_consent_as_recruiter,
    setup_order_in_awaiting_adjudication,
    setup_order_pre_adverse,
    upsert_jurisdiction_policy,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Happy path — PRD §3.6
# ===========================================================================
class TestPreAdverseHappyPath:

    def test_issue_pre_adverse_on_consider_creates_flow(
        self, api, adjudicator_headers,
    ):
        """PRD §3.6: "On success the system creates a new
        `AdverseActionFlow` for the order with
        `pre_adverse_notice_sent_at` set to the current server time,
        `notification_status` moved from its initial `PENDING_DELIVERY`
        to `PRE_DELIVERED`, and `procedural_status` set to
        `PRE_AWAITING_DISPUTE_WINDOW`."

        Claim: POST /pre-adverse on a CONSIDER order returns 200 with
        an AdverseActionFlow whose notification_status=PRE_DELIVERED
        and procedural_status=PRE_AWAITING_DISPUTE_WINDOW.
        """
        cand, cons, order, items = setup_order_in_awaiting_adjudication(
            residence_jurisdiction="CA",
            jurisdiction_kwargs={"criminal_lookback_years": 7},
            requested_packages=["CRIMINAL"],
            findings_by_kind={
                "CRIMINAL": criminal_raw_finding(
                    conviction_date="2025-06-01",
                    severity="FELONY",
                ),
            },
        )
        assert order["composite_decision"] == "CONSIDER"
        resp = api.issue_pre_adverse(order["id"], adjudicator_headers)
        data = validate_success(resp)
        assert_adverse_action_flow(data)
        assert data["notification_status"] == "PRE_DELIVERED"
        assert data["procedural_status"] == "PRE_AWAITING_DISPUTE_WINDOW"
        assert data["order_id"] == order["id"]

    def test_pre_adverse_snapshots_waiting_period(
        self, api, adjudicator_headers,
    ):
        """PRD §3.6: "The flow snapshots the jurisdiction's
        `adverse_action_waiting_business_days` into its own
        `waiting_period_business_days` field at the moment of
        Pre-Adverse send, and the flow is pinned to that number even
        if the jurisdiction's policy changes later."

        Claim: AdverseActionFlow.waiting_period_business_days equals
        the jurisdiction's adverse_action_waiting_business_days at the
        time of Pre-Adverse send.
        """
        cand, cons, order, items = setup_order_in_awaiting_adjudication(
            residence_jurisdiction="CA",
            jurisdiction_kwargs={
                "criminal_lookback_years": 7,
                "adverse_action_waiting_business_days": 8,
            },
            requested_packages=["CRIMINAL"],
            findings_by_kind={
                "CRIMINAL": criminal_raw_finding(
                    conviction_date="2025-06-01",
                    severity="FELONY",
                ),
            },
        )
        resp = api.issue_pre_adverse(order["id"], adjudicator_headers)
        data = validate_success(resp)
        assert data["waiting_period_business_days"] == 8


# ===========================================================================
# Segregation of Duties — PRD §2.11, §3.6
# ===========================================================================
class TestSegregationOfDuties:

    def test_pre_adverse_by_order_opener_rejected(self, api):
        """PRD §2.11: "The Adjudicator's `X-User-ID` must differ from
        the `BackgroundCheckOrder.opened_by_user_id` recorded when the
        order was opened; a violation, whether attempted on issuing
        Pre-Adverse, on issuing Final Adverse, or on resolving a
        dispute attached to the order, surfaces as `ERR_SOD_VIOLATION`
        (HTTP 422)."

        Claim: Adjudicator's X-User-ID equals the Recruiter's X-User-ID
        from order open -> Pre-Adverse rejected with
        ERR_SOD_VIOLATION.
        """
        shared_id = "shared-operator-collision-001"
        # Recruiter and Adjudicator both use `shared_id`; per PRD §2.11
        # this is exactly what triggers the SoD violation.
        recruiter_h = make_recruiter_headers(shared_id)
        adjudicator_h = make_adjudicator_headers(shared_id)
        # Build a CONSIDER order through the colliding Recruiter id.
        cand, cons, order, items = setup_order_in_awaiting_adjudication(
            residence_jurisdiction="CA",
            jurisdiction_kwargs={"criminal_lookback_years": 7},
            requested_packages=["CRIMINAL"],
            findings_by_kind={
                "CRIMINAL": criminal_raw_finding(
                    conviction_date="2025-06-01",
                    severity="FELONY",
                ),
            },
            recruiter_headers=recruiter_h,
        )
        # Now try to issue Pre-Adverse as the same operator id.
        resp = api.issue_pre_adverse(order["id"], adjudicator_h)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value)


# ===========================================================================
# Composite_decision precondition — PRD §3.6
# ===========================================================================
class TestPreAdversePreconditions:

    def test_pre_adverse_when_completed_clear_rejected(
        self, api, adjudicator_headers,
    ):
        """PRD §3.6: "An `Adjudicator` issues Pre-Adverse Action on an
        order whose `composite_decision` is `CONSIDER` or `INELIGIBLE`".

        Claim: Pre-Adverse on a COMPLETED_CLEAR order (terminal state)
        is rejected with ERR_INVALID_STATE per the state-precondition
        rule.
        """
        cand, cons, order, items = setup_order_in_awaiting_adjudication(
            residence_jurisdiction="CA",
            requested_packages=["EDUCATION"],
            findings_by_kind={
                "EDUCATION": education_raw_finding(
                    institution="Test U", claim_verified=True,
                ),
            },
        )
        assert order["status"] == "COMPLETED_CLEAR"
        resp = api.issue_pre_adverse(order["id"], adjudicator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Uniqueness of AdverseActionFlow per order — PRD §3.6
# ===========================================================================
class TestAdverseFlowUniqueness:

    def test_second_pre_adverse_call_rejected(
        self, api, adjudicator_headers,
    ):
        """PRD §3.6: "no `AdverseActionFlow` may already exist on the
        order — two simultaneous Pre-Adverse calls on the same order
        serialize on the uniqueness of `order_id` in the adverse-
        action-flow table, and the loser receives
        `ERR_ADVERSE_FLOW_ALREADY_EXISTS` (HTTP 409)."

        Claim: a second sequential Pre-Adverse on the same order ->
        ERR_ADVERSE_FLOW_ALREADY_EXISTS.
        """
        cand, cons, order, items, flow = setup_order_pre_adverse(
            residence_jurisdiction="CA",
            jurisdiction_kwargs={"criminal_lookback_years": 7},
            adjudicator_headers=adjudicator_headers,
        )
        # Second call on the same order — flow already exists.
        # PRD §3.6 names ERR_ADVERSE_FLOW_ALREADY_EXISTS for the case
        # where a flow already exists on the order. After the first
        # Pre-Adverse the order has moved to PRE_ADVERSE_ISSUED, so a
        # PRD-faithful implementation may also surface
        # ERR_INVALID_STATE for the state-precondition mismatch — both
        # are consistent with the §3.6 sentence pinning the uniqueness
        # check. Accept either.
        resp = api.issue_pre_adverse(order["id"], adjudicator_headers)
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_ADVERSE_FLOW_ALREADY_EXISTS.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )
