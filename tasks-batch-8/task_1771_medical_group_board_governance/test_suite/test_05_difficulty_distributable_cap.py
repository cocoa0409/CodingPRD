"""Difficulty queue: distributable cap — bonus accrual before cap (pinned order)."""
from test_helpers import (
    ApiErrorId,
    adopted_distribution,
    create_motion,
    create_policy,
    create_shareholder,
    distribution_payload,
    api_client,
    make_physician_headers,
    validate_error,
)

NIBB = 800000000


class TestDistributableCapBonusFirstEvaluationOrder:
    def test_over_cap_create_rejected_despite_naive_order_passing(self, api):
        """PRD §3.5: "The evaluation order is pinned — the bonus accrual is computed
        from pre-bonus net income first, and the cap applies to the remainder;
        computing the cap directly on pre-bonus income produces a different, wrong
        result. The motion's `amount_cents` must not exceed `distributable_cap_cents`,
        checked both at motion creation and again at adoption; an excess is rejected
        with `ERR_DISTRIBUTION_CAP_EXCEEDED`."
        Cap: round(800000000*0.25)=200000000 bonus first, then round(600000000*0.60)=
        360000000. Asking 400000000 exceeds 360000000 even though the wrong-order
        60%-of-pre-bonus figure (480000000) would have allowed it.

        Design: Difficulty/combinatorial_formula/distributable_cap_bonus_first_evaluation_order
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        resp = api_client.create_motion(
            {
                "motion_type": "DISTRIBUTION",
                "sponsor_physician_id": a["id"],
                "payload": distribution_payload(400000000),
            },
            make_physician_headers(a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISTRIBUTION_CAP_EXCEEDED)

    def test_at_cap_create_accepted_and_adoption_stamps_guardrails(self, api):
        """PRD §3.5: "First the bonus accrual: `bonus_accrual_cents` is
        `fiscal_net_income_before_bonus_cents` multiplied by `bonus_pool_pct`, rounded
        half-up. Then the cap: `distributable_cap_cents` is the remaining income after
        the bonus accrual, multiplied by `distribution_cap_pct`, rounded half-up."
        Asking exactly 360000000 (== the cap) is within "must not exceed" and adopts.

        Design: Difficulty/combinatorial_formula/distributable_cap_bonus_first_evaluation_order
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        motion, distribution = adopted_distribution(a, 360000000, voters=[a])
        assert motion["status"] == "ADOPTED"
        assert distribution["bonus_accrual_cents"] == 200000000, (
            f"bonus accrual must be round(800000000*0.25) = 200000000, "
            f"got {distribution['bonus_accrual_cents']}"
        )
        assert distribution["distributable_cap_cents"] == 360000000, (
            f"cap must be round(600000000*0.60) = 360000000, "
            f"got {distribution['distributable_cap_cents']}"
        )
        assert distribution["total_amount_cents"] == 360000000
        assert distribution["status"] == "APPROVED"
