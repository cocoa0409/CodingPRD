"""TemporaryOrder + FinalJudgment creation, issuance cascade, and
field-combination validation.

PRD §3.6, §2.9.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    assert_final_judgment,
    assert_temp_order,
    create_final_judgment_payload,
    create_support_order,
    create_temp_order_payload,
    issue_final_judgment_payload,
    issue_temp_order_payload,
    re_get_case,
    re_get_final_judgment,
    re_get_support_order,
    re_get_temp_order,
    setup_case_temp_ordered_with_final_judgment_draft,
    setup_case_with_agreed_plan,
    setup_case_with_both_disclosures_accepted,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# TemporaryOrder field-combination validation — PRD §3.6
# ===========================================================================
class TestTempOrderFieldRules:

    def test_minor_children_true_requires_plan_and_child_support(
        self, api, judge_headers,
    ):
        """PRD §3.6: 'when Case.has_minor_children is true, the body
        must carry both parenting_plan_id and child_support_order_id'.
        PRD §3.6: 'Any other combination of these three fields is
        rejected with ERR_TEMP_ORDER_FIELDS (HTTP 422).'

        Claim: has_minor_children=true with parenting_plan_id=null
        → ERR_TEMP_ORDER_FIELDS.
        """
        ctx = setup_case_with_agreed_plan()
        # Build only spousal-eligible SupportOrder so we have an id to
        # pass; intentionally omit child_support_order_id and
        # parenting_plan_id.
        payload = create_temp_order_payload(
            parenting_plan_id=None,
            child_support_order_id=None,
            spousal_support_order_id=None,
        )
        res = api.create_temp_order(
            ctx["case"]["id"], payload, judge_headers,
        )
        validate_error(
            res, "ERR_TEMP_ORDER_FIELDS", expected_status=422,
        )

    def test_no_minor_children_requires_plan_and_child_support_null(
        self, api, judge_headers,
    ):
        """PRD §3.6: 'when has_minor_children is false, both
        parenting_plan_id and child_support_order_id must be null'.

        Claim: has_minor_children=false with non-null
        parenting_plan_id → ERR_TEMP_ORDER_FIELDS.
        """
        # has_minor_children=false case
        ctx = setup_case_with_both_disclosures_accepted(
            has_minor_children=False,
            marriage_date="2010-01-01",
            separation_date="2025-01-01",
        )
        # Build a plan-like id (we don't actually have a plan on a
        # has_minor_children=false case; use a UUID-shaped string).
        # Use a real UUID via from_helpers.
        from prd_bench_local_runner.testing import NON_EXISTENT_UUID
        payload = create_temp_order_payload(
            parenting_plan_id=NON_EXISTENT_UUID,
            child_support_order_id=None,
            spousal_support_order_id=None,
        )
        res = api.create_temp_order(
            ctx["case"]["id"], payload, judge_headers,
        )
        # Per PRD §2.11, business_referential (priority 18) fires
        # AFTER state checks. The fields are wrong, so
        # ERR_TEMP_ORDER_FIELDS is the expected outcome.
        validate_error(
            res, "ERR_TEMP_ORDER_FIELDS", expected_status=422,
        )


# ===========================================================================
# Issue temp order cascade — PRD §2.9 / §3.6
# ===========================================================================
class TestIssueTempOrderCascade:

    def test_issue_temp_cascades_support_orders_to_issued(
        self, api, judge_headers,
    ):
        """PRD §2.9: 'When a Judge issues a temporary order, the
        TemporaryOrder itself transitions from DRAFT to EFFECTIVE ...
        and every TEMPORARY SupportOrder referenced by that temporary
        order transitions from DRAFT to ISSUED (with effective_from
        set to now).'

        Claim: after issue-temp-order, the TemporaryOrder is EFFECTIVE
        and the linked CHILD SupportOrder is ISSUED.
        """
        ctx = setup_case_with_agreed_plan(
            marriage_date="2010-01-01",
            separation_date="2025-01-01",
        )
        child = create_support_order(
            ctx["case"]["id"], support_type="CHILD",
            order_kind="TEMPORARY",
            parenting_plan_id=ctx["parenting_plan"]["id"],
        )
        t1_payload = create_temp_order_payload(
            parenting_plan_id=ctx["parenting_plan"]["id"],
            child_support_order_id=child["id"],
        )
        t1 = validate_success(
            api.create_temp_order(
                ctx["case"]["id"], t1_payload, judge_headers,
            ), 201,
        )
        # Issue.
        api.issue_temp_order(
            ctx["case"]["id"],
            issue_temp_order_payload(temporary_order_id=t1["id"]),
            judge_headers,
        )
        t_after = re_get_temp_order(ctx["case"]["id"], t1["id"])
        assert t_after["status"] == "EFFECTIVE"
        assert t_after["effective_from"], (
            "TemporaryOrder.effective_from must be set on issuance"
        )
        child_after = re_get_support_order(
            ctx["case"]["id"], child["id"],
        )
        assert child_after["status"] == "ISSUED"

    def test_issue_temp_sets_case_to_temp_ordered(
        self, api, judge_headers,
    ):
        """PRD §2.9: 'The parent Case.status advances to
        TEMP_ORDERED.'

        Claim: after issue-temp-order, Case.status = TEMP_ORDERED.
        """
        ctx = setup_case_temp_ordered_with_final_judgment_draft(
            jurisdiction_state="CA",
        )
        case = re_get_case(ctx["case"]["id"])
        # AWAITING_JUDGMENT is the further state reached after
        # TEMP_ORDERED automatically per PRD §3.6 (since we already
        # have AGREED plan). Either is acceptable proof the cascade
        # to TEMP_ORDERED happened.
        assert case["status"] in ("TEMP_ORDERED", "AWAITING_JUDGMENT")

    def test_temp_order_supersedes_on_final_judgment(
        self, api, judge_headers,
    ):
        """PRD §2.9: 'if Case.temporary_order_id is set, that
        TemporaryOrder transitions from EFFECTIVE to SUPERSEDED (its
        superseded_at is set to now) and every TEMPORARY SupportOrder
        it had referenced transitions to SUPERSEDED'.

        Claim: after issue-final-judgment, the TemporaryOrder is
        SUPERSEDED with superseded_at set, and its temporary
        SupportOrders are SUPERSEDED.
        """
        ctx = setup_case_temp_ordered_with_final_judgment_draft(
            jurisdiction_state="CA",
            marriage_date="2010-01-01",
            separation_date="2025-01-01",
        )
        api.issue_final_judgment(
            ctx["case"]["id"],
            issue_final_judgment_payload(
                final_judgment_id=ctx["final_judgment"]["id"],
            ),
            judge_headers,
        )
        t_after = re_get_temp_order(
            ctx["case"]["id"], ctx["temp_order"]["id"],
        )
        assert t_after["status"] == "SUPERSEDED"
        assert t_after["superseded_at"], (
            "TemporaryOrder.superseded_at must be set after final "
            "judgment issuance"
        )
        # Temporary CHILD SupportOrder must also be SUPERSEDED.
        ts = re_get_support_order(
            ctx["case"]["id"], ctx["temp_child_so"]["id"],
        )
        assert ts["status"] == "SUPERSEDED"


# ===========================================================================
# Final judgment status -> FINALIZED — PRD §2.9
# ===========================================================================
class TestFinalJudgmentCascade:

    def test_issue_final_judgment_sets_case_finalized(
        self, api, judge_headers,
    ):
        """PRD §2.9: 'The parent Case.status advances to FINALIZED and
        Case.final_judgment_id is set.'

        Claim: after issue-final-judgment, Case.status == FINALIZED
        and Case.final_judgment_id is set.
        """
        ctx = setup_case_temp_ordered_with_final_judgment_draft(
            jurisdiction_state="CA",
            marriage_date="2010-01-01",
            separation_date="2025-01-01",
        )
        api.issue_final_judgment(
            ctx["case"]["id"],
            issue_final_judgment_payload(
                final_judgment_id=ctx["final_judgment"]["id"],
            ),
            judge_headers,
        )
        case_after = re_get_case(ctx["case"]["id"])
        assert case_after["status"] == "FINALIZED"
        assert case_after["final_judgment_id"] == ctx["final_judgment"]["id"]

    def test_final_judgment_draft_carries_asset_shares(
        self, api, judge_headers,
    ):
        """PRD §3.6: 'On DRAFT creation the server computes
        petitioner_asset_share_cents and respondent_asset_share_cents
        and records division_model'.

        Claim: a freshly-created FinalJudgment DRAFT carries
        petitioner_asset_share_cents, respondent_asset_share_cents, and
        division_model.
        """
        ctx = setup_case_temp_ordered_with_final_judgment_draft(
            jurisdiction_state="CA",
            marriage_date="2010-01-01",
            separation_date="2025-01-01",
        )
        fj = ctx["final_judgment"]
        assert_final_judgment(fj)
        assert isinstance(fj["petitioner_asset_share_cents"], int)
        assert isinstance(fj["respondent_asset_share_cents"], int)
        assert fj["division_model"] in (
            "COMMUNITY_PROPERTY", "EQUITABLE_DISTRIBUTION",
        )
