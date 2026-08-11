"""Site budget variance: the provisional and final ratio variants diverge on
identical data while budget_posture stays keyed to the final variant."""
from test_helpers import (
    approve_change_order_now,
    propose_change_order,
    read_site,
    setup_awarded_site,
    validate_success,
)


class TestProvisionalVsFinalDivergence:
    def test_site_variance_provisional_vs_final_posture_divergence(self, api):
        """PRD §3.6: "Otherwise the final ratio, `variance_ratio_final_bp`, is
        `committed_cents` minus `base_contract_cents`, multiplied by 10000,
        divided by `base_contract_cents`, and rounded half up; the provisional
        ratio, `variance_ratio_provisional_bp`, applies the same formula to
        `committed_cents` plus `proposed_co_cents`, so identical data yields a
        higher provisional figure whenever a `PROPOSED` order exists. The
        site's `budget_posture` keys off the final ratio: at most 500 basis
        points reads `WITHIN`, at most 1500 reads `WATCH`, and beyond that
        `OVERRUN`."

        Design: Difficulty/dual_variant_calc/site_variance_provisional_vs_final_posture_divergence
        """
        ctx = setup_awarded_site(bid_amount_cents=9_000_000,
                                 budget_allocation_cents=10_000_000)
        site_id = ctx["site"]["id"]
        co_approved = propose_change_order(site_id, 400_000,
                                           description="Added millwork")
        resp = approve_change_order_now(co_approved["id"], site_id,
                                        role="FinanceController",
                                        approver_user_id="fin-1")
        validate_success(resp)
        propose_change_order(site_id, 120_000, description="Lighting upgrade")

        site = read_site(site_id)
        assert site["committed_cents"] == 9_400_000
        assert site["proposed_co_cents"] == 120_000
        # Final: (9400000-9000000)*10000/9000000 = 444.44 -> 444.
        assert site["variance_ratio_final_bp"] == 444
        # Provisional on identical data: (9520000-9000000)*10000/9000000
        # = 577.78 -> 578.
        assert site["variance_ratio_provisional_bp"] == 578
        # Posture reads the final variant only: WITHIN despite the
        # provisional reading crossing the WATCH threshold.
        assert site["budget_posture"] == "WITHIN"

    def test_posture_tracks_final_ratio_once_proposed_becomes_committed(self, api):
        """PRD §3.6: "The site's `budget_posture` keys off the final ratio: at
        most 500 basis points reads `WITHIN`, at most 1500 reads `WATCH`, and
        beyond that `OVERRUN`."
        PRD §3.6: "the provisional ratio, `variance_ratio_provisional_bp`,
        applies the same formula to `committed_cents` plus
        `proposed_co_cents`, so identical data yields a higher provisional
        figure whenever a `PROPOSED` order exists."

        Design: Difficulty/dual_variant_calc/site_variance_provisional_vs_final_posture_divergence
        """
        ctx = setup_awarded_site(bid_amount_cents=9_000_000,
                                 budget_allocation_cents=10_000_000)
        site_id = ctx["site"]["id"]
        co1 = propose_change_order(site_id, 400_000, description="Added millwork")
        validate_success(approve_change_order_now(co1["id"], site_id,
                                                  role="FinanceController",
                                                  approver_user_id="fin-1"))
        co2 = propose_change_order(site_id, 120_000, description="Lighting upgrade")
        assert read_site(site_id)["budget_posture"] == "WITHIN"

        # Approving the proposed order moves its amount into committed: the
        # variants converge at 578 and the posture flips to WATCH.
        validate_success(approve_change_order_now(co2["id"], site_id,
                                                  role="FinanceController",
                                                  approver_user_id="fin-1"))
        site = read_site(site_id)
        assert site["committed_cents"] == 9_520_000
        assert site["proposed_co_cents"] == 0
        assert site["variance_ratio_final_bp"] == 578
        assert site["variance_ratio_provisional_bp"] == 578
        assert site["budget_posture"] == "WATCH"
