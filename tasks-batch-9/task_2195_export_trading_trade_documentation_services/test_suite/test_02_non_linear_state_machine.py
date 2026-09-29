"""The two order dimensions advance independently, and the credit loop revisits states."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from test_helpers import (
    FINANCE_FRANK,
    OPS_ALICE,
    REVIEWER_BOB,
    approx_money,
    assert_order_dimensions,
    factories as f,
    fixtures as fx,
)

Json = Dict[str, Any]


def _insured_shipped_order(
    api,
    policy_overrides: Optional[Json] = None,
    credit_overrides: Optional[Json] = None,
    lines: Optional[List[Json]] = None,
) -> Json:
    """A shipped order whose credit acceptance charges a policy written first."""
    ctx = fx.cleared_order(api, lines=lines)
    ctx["policy"] = fx.create_policy(api, ctx["buyer_id"], **(policy_overrides or {}))
    ctx["policy_id"] = ctx["policy"]["id"]
    ctx = fx.booked_order(api, base=ctx)
    ctx = fx.confirmed_booking(api, ctx)
    ctx = fx.shipped_order(api, ctx)
    ctx = fx.accepted_credit(api, ctx, **(credit_overrides or {}))
    return ctx


def _claim_filed(api) -> Json:
    """The whole dishonour-to-claim walk on a single insured order."""
    ctx = _insured_shipped_order(
        api,
        policy_overrides={
            "policy_number": "POL-C",
            "credit_limit_usd": 30000.00,
            "insured_pct": 90.00,
            "deductible_usd": 5000.00,
        },
        credit_overrides={"lc_number": "LC-2195-003"},
    )
    ctx = fx.lodged_presentation(api, ctx)
    ctx = fx.examined_presentation(api, ctx, [])
    ctx["presentation"] = fx.data(
        api.dishonour_presentation(
            ctx["presentation_id"],
            {"refusal_reason": "issuing bank refused: applicant insolvent"},
            FINANCE_FRANK,
        )
    )
    ctx["dispute"] = fx.data(
        api.open_dispute(
            f.dispute_payload(
                ctx["order_id"], dispute_type="NON_PAYMENT", claimed_amount_usd=25000.00
            ),
            FINANCE_FRANK,
        )
    )
    ctx["dispute_id"] = ctx["dispute"]["id"]
    ctx["policy"] = fx.data(
        api.file_claim(
            ctx["policy_id"],
            f.claim_payload(ctx["dispute_id"], fx.policy_version(api, ctx["policy_id"])),
            FINANCE_FRANK,
        )
    )
    ctx["order"] = fx.read_order(api, ctx["order_id"])
    return ctx


class TestSettlementAxisWalksWhileGoodsAxisHolds:
    def test_money_axis_reaches_claim_filed_with_the_goods_axis_still_shipped(self, api):
        """PRD §2.10: "an attempt to drive either axis from a state where the
        requested transition is not declared is rejected with
        `ERR_ORDER_STATE_INVALID` (409)"

        Design: Difficulty/non_linear_state_machine/export_order_settlement_walks_four_states_while_fulfillment_pinned_at_shipped
        """
        ctx = _claim_filed(api)

        assert_order_dimensions(
            ctx["order"], fulfillment="SHIPPED", settlement="CLAIM_FILED"
        )
        assert fx.data(api.get_presentation(ctx["presentation_id"], REVIEWER_BOB))[
            "status"
        ] == "REFUSED"

        dispute = fx.data(api.get_dispute(ctx["dispute_id"], FINANCE_FRANK))
        assert dispute["status"] == "OPEN"
        assert dispute["credit_insurance_policy_id"] == ctx["policy_id"]

    def test_dishonour_releases_nothing_so_the_policy_still_carries_the_exposure(
        self, api
    ):
        """PRD §3.8: "Note the asymmetry with settlement: dishonour releases
        **nothing**. The insured exposure stays charged, because a dishonoured
        receivable is precisely the exposure the policy exists to cover."

        Design: Difficulty/non_linear_state_machine/export_order_settlement_walks_four_states_while_fulfillment_pinned_at_shipped
        """
        ctx = _claim_filed(api)
        policy = fx.read_policy(api, ctx["policy_id"])

        assert policy["premium_usd"] == approx_money(229.50)
        assert policy["utilized_usd"] == approx_money(25000.00)
        assert policy["available_limit_usd"] == approx_money(5000.00)
        assert policy["status"] == "ACTIVE"
        assert ctx["order"]["insured_exposure_usd"] == approx_money(25000.00)

        credit = fx.read_credit(api, ctx["lc_id"])
        assert credit["status"] == "ACCEPTED"
        assert credit["drawn_amount_usd"] == approx_money(0.00)


# ---------------------------------------------------------------------------
# The amendment cycle: an accepted credit returns to RECEIVED
# ---------------------------------------------------------------------------


def _amended_then_reaccepted_credit(api) -> Json:
    """Accept a credit on a minor finding, amend it in place, then accept again."""
    ctx = fx.cleared_order(api)
    ctx = fx.captured_credit(
        api, ctx, lc_number="LC-2195-004", amount_usd=26000.00, tolerance_pct=5.00
    )
    ctx = fx.opened_terms_review(api, ctx)
    ctx["review_one_id"] = ctx["review_id"]
    ctx["finding"] = fx.data(
        api.raise_terms_finding(
            ctx["review_id"],
            f.terms_finding_payload(severity="MINOR", clause_ref="DOCUMENTS"),
            REVIEWER_BOB,
        )
    )
    fx.data(
        api.submit_terms_review(
            ctx["review_id"], {"recommendation": "ACCEPT"}, REVIEWER_BOB
        )
    )
    ctx["credit"] = fx.data(
        api.amend_credit(
            ctx["lc_id"],
            {
                "expected_letter_of_credit_version": fx.credit_version(api, ctx["lc_id"]),
                "amount_usd": 27000.00,
                "tolerance_pct": 3.00,
            },
            OPS_ALICE,
        )
    )
    ctx = fx.opened_terms_review(api, ctx)
    ctx["review_two_id"] = ctx["review_id"]
    ctx["review_two"] = fx.data(
        api.submit_terms_review(
            ctx["review_id"], {"recommendation": "ACCEPT"}, REVIEWER_BOB
        )
    )
    ctx["credit"] = fx.read_credit(api, ctx["lc_id"])
    ctx["order"] = fx.read_order(api, ctx["order_id"])
    return ctx


class TestAmendmentCycleReturnsTheCreditToTheStartOfTheLoop:
    def test_amendment_recomputes_both_bounds_and_bumps_the_round(self, api):
        """PRD §3.4: "The amendment applies the submitted fields in place,
        increments `amendment_round` by one, recomputes `max_drawable_usd` and
        `min_drawable_usd`, moves the credit back to `RECEIVED`"

        Design: Difficulty/non_linear_state_machine/lc_amendment_cycle_returns_accepted_credit_to_received_and_supersedes_its_review
        """
        ctx = _amended_then_reaccepted_credit(api)

        assert ctx["credit"]["status"] == "ACCEPTED"
        assert ctx["credit"]["amendment_round"] == 1
        assert ctx["credit"]["max_drawable_usd"] == approx_money(27810.00)
        assert ctx["credit"]["min_drawable_usd"] == approx_money(26190.00)

    def test_amendment_supersedes_the_earlier_review_and_cures_its_open_finding(
        self, api
    ):
        """PRD §3.4: "moves **every** review of the credit in `SUBMITTED` to
        `SUPERSEDED`, marks every finding of the credit with `source` `TERMS` and
        `cure_status` `OPEN` as `CURED`"

        Design: Difficulty/non_linear_state_machine/lc_amendment_cycle_returns_accepted_credit_to_received_and_supersedes_its_review
        """
        ctx = _amended_then_reaccepted_credit(api)

        review_one = fx.data(api.get_terms_review(ctx["review_one_id"], REVIEWER_BOB))
        assert review_one["status"] == "SUPERSEDED"
        assert review_one["terms_risk_score"] == approx_money(5.00)

        finding = fx.data(api.get_finding(ctx["finding"]["id"], REVIEWER_BOB))
        assert finding["cure_status"] == "CURED"

        assert ctx["review_two"]["status"] == "SUBMITTED"
        assert ctx["review_two"]["terms_risk_score"] == approx_money(0.00)

        assert_order_dimensions(
            ctx["order"], fulfillment="COMPLIANCE_CLEARED", settlement="LC_ACCEPTED"
        )
        assert ctx["order"]["insured_exposure_usd"] == approx_money(0.00)
