"""Difficulty rule combinatorial_formula: the tuition waterfall's nested min()
plus delivery-mode branch, and the refund settlement's pinned per-payer rounding
order (PRD 3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_invoice_conservation,
    get_invoice,
    refund_invoice,
    setup_delivery_mode_pair,
    setup_mismatch_withdraw_scenario,
    validate_error,
)


class TestTuitionWaterfallDeliveryModeBranch:
    def test_hs_campus_offering_opens_the_state_bucket(self, api):
        """PRD 3.7: "Bucket 1 is the state: when the agreement's `funding_model` is
        `STATE_PROGRAM` and the offering's `delivery_mode` is `HS_CAMPUS`,
        `state_amount_cents` is the smaller of `tuition_total_cents` and
        `state_rate_cents_per_credit` multiplied by `college_credit_hours`; in every
        other case `state_amount_cents` is 0."
        PRD 3.7: "Bucket 2 is the district: when the agreement's `funding_model` is
        `FAMILY_RESPONSIBLE` the district bucket is skipped entirely and
        `district_amount_cents` is 0; otherwise `district_amount_cents` is the
        smaller of the first remainder and `district_cap_cents`."

        Design: Difficulty/combinatorial_formula/tuition_waterfall_delivery_mode_branch
        """
        ctx = setup_delivery_mode_pair()
        invoice = ctx["invoice_a"]
        assert invoice["tuition_total_cents"] == 120000
        assert invoice["state_amount_cents"] == 90000, (
            f"HS_CAMPUS: min(120000, 30000 x 3) == 90000, got "
            f"{invoice['state_amount_cents']}"
        )
        assert invoice["district_amount_cents"] == 30000, (
            f"min(remainder 30000, cap 50000) == 30000, got "
            f"{invoice['district_amount_cents']}"
        )
        assert invoice["family_amount_cents"] == 0
        assert_invoice_conservation(invoice)

    def test_online_offering_closes_the_state_bucket(self, api):
        """PRD 3.7: "Bucket 1 is the state: when the agreement's `funding_model` is
        `STATE_PROGRAM` and the offering's `delivery_mode` is `HS_CAMPUS`,
        `state_amount_cents` is the smaller of `tuition_total_cents` and
        `state_rate_cents_per_credit` multiplied by `college_credit_hours`; in every
        other case `state_amount_cents` is 0."
        PRD 3.7: "Bucket 3 is the family, which takes the remainder:
        `family_amount_cents` is the first remainder minus `district_amount_cents`."
        PRD 3.7: "The three buckets always sum to `tuition_total_cents`."

        Design: Difficulty/combinatorial_formula/tuition_waterfall_delivery_mode_branch
        """
        ctx = setup_delivery_mode_pair()
        invoice = ctx["invoice_b"]
        assert invoice["tuition_total_cents"] == 120000
        assert invoice["state_amount_cents"] == 0, (
            f"ONLINE delivery closes the state bucket, got "
            f"{invoice['state_amount_cents']}"
        )
        assert invoice["district_amount_cents"] == 50000, (
            f"min(remainder 120000, cap 50000) == 50000, got "
            f"{invoice['district_amount_cents']}"
        )
        assert invoice["family_amount_cents"] == 70000
        assert_invoice_conservation(invoice)


class TestRefundPerPayerRoundingOrder:
    def _setup_fully_paid_withdrawn(self):
        return setup_mismatch_withdraw_scenario(
            fully_pay=True,
            course_overrides={
                "course_code": "ART100",
                "title": "Art Appreciation",
                "college_credit_hours": 1,
                "hs_credit_units": 0.5,
                "placement_exam_code": "NONE",
                "min_placement_score": 0,
            },
            funding_overrides={
                "tuition_cents_per_credit": 33333,
                "state_rate_cents_per_credit": 11111,
                "district_cap_cents": 10001,
            },
        )

    def test_estimate_pins_family_to_the_rounding_remainder(self, api):
        """PRD 3.7: "`refund_estimate_cents` is `tuition_total_cents` multiplied by
        `refund_pct` and divided by 100, rounded half-up. `est_state_refund_cents`
        is `state_amount_cents` multiplied by `refund_pct` and divided by 100,
        rounded half-up. `est_district_refund_cents` is `district_amount_cents`
        multiplied by `refund_pct` and divided by 100, rounded half-up.
        `est_family_refund_cents` is the remainder — `refund_estimate_cents` minus
        `est_state_refund_cents` minus `est_district_refund_cents` — pinning the
        family bucket to absorb any rounding drift."
        PRD 2.7: "Where a proportional share must be computed, the system uses
        round-half-up at exactly the steps named in the refund settlement rules —
        no more, no fewer."

        Design: Difficulty/combinatorial_formula/refund_per_payer_rounding_order
        """
        ctx = self._setup_fully_paid_withdrawn()
        invoice = ctx["invoice"]
        assert invoice["tuition_total_cents"] == 33333
        assert invoice["state_amount_cents"] == 11111
        assert invoice["district_amount_cents"] == 10001
        assert invoice["family_amount_cents"] == 12221
        assert invoice["refund_pct"] == 50
        assert invoice["refund_estimate_cents"] == 16667, (
            f"round_half_up(33333 x 50/100) = round_half_up(16666.5) == 16667, got "
            f"{invoice['refund_estimate_cents']}"
        )
        assert invoice["est_state_refund_cents"] == 5556, (
            f"round_half_up(5555.5) == 5556, got {invoice['est_state_refund_cents']}"
        )
        assert invoice["est_district_refund_cents"] == 5001, (
            f"round_half_up(5000.5) == 5001, got {invoice['est_district_refund_cents']}"
        )
        # Pinned remainder 16667 - 5556 - 5001 == 6110, NOT round_half_up(12221 x
        # 0.5) == 6111 — the family bucket absorbs the rounding drift.
        assert invoice["est_family_refund_cents"] == 6110, (
            f"Family takes the remainder 16667 - 5556 - 5001 == 6110, got "
            f"{invoice['est_family_refund_cents']}"
        )

    def test_settled_equals_estimate_when_fully_paid(self, api):
        """PRD 3.7: "When the invoice is fully paid the settled amount equals the
        estimate; when partially paid the settled amount is at most the estimate
        and the two diverge."
        PRD 3.7: "The settled variant fires when the `Bursar` processes the refund,
        moving `refund_status` from `DUE` to `PROCESSED` (any other starting value
        is rejected with `ERR_REFUND_NOT_DUE`, HTTP 409, including a second refund
        call on an already-processed invoice)."

        Design: Difficulty/combinatorial_formula/refund_per_payer_rounding_order
        """
        ctx = self._setup_fully_paid_withdrawn()
        invoice = ctx["invoice"]
        assert invoice["status"] == "PAID"
        assert invoice["refund_status"] == "DUE"

        settled = refund_invoice(invoice["id"])
        assert settled["refund_paid_cents"] == 16667, (
            f"Fully paid: settled follows the same pinned order and equals the "
            f"estimate 16667, got {settled['refund_paid_cents']}"
        )
        assert settled["refund_status"] == "PROCESSED"
