"""Optimistic concurrency, derived-field reconciliation, and immediate
consistency.

Corner queue: cross_cutting_complexity_layers + consistency_model.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    create_open_campaign, create_donor, create_pledge, record_gift,
    acknowledge_gift, create_acknowledged_gift, setup_open_campaign_with_donor,
)

CM = TEST_USERS["campaign_manager_headers"]
GA = TEST_USERS["gift_admin_headers"]
DR = TEST_USERS["donor_relations_headers"]


class TestOptimisticConcurrency:
    def test_pledge_cancel_stale_version_rejected(self, api):
        """PRD §2.10: "A gift acknowledgement allocated to a pledge legitimately
        advances the pledge's `version` (through the paid/balance recomputation and the
        installment cascade). If a cancel request still carries a `version` from before
        that advance, it is operating on a stale view of a now-partially-paid pledge;
        the request is rejected with `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_complexity_layers/occ_pledge_cancel_stale_version_conflict
        """
        camp, donor = setup_open_campaign_with_donor()
        pledge = create_pledge(camp["id"], donor["id"], total_amount_cents=10000,
                               installment_count=2, frequency="MONTHLY")
        stale_version = pledge["version"]
        gift = record_gift(camp["id"], donor["id"], amount_cents=5000, pledge_id=pledge["id"])
        acknowledge_gift(gift["id"])  # advances pledge.version

        validate_error(
            api.cancel_pledge(pledge["id"], {"expected_pledge_version": stale_version}, GA),
            ApiErrorId.ERR_STALE_VERSION.value,
        )

    def test_gift_refund_correct_version_succeeds_and_bumps(self, api):
        """PRD §2.10: "Refunding a gift requires the body to carry `expected_gift_version`
        ... If `expected_gift_version` does not match the gift's current `version`, the
        refund is rejected". PRD §2.4: "The `version` field is an integer that begins at
        its initial value and increments by one on every mutation of the resource".

        A refund carrying the current (post-acknowledge) version succeeds and the gift's
        version advances again.

        Design: Corner/cross_cutting_complexity_layers/occ_gift_refund_correct_version_succeeds
        """
        camp, donor = setup_open_campaign_with_donor()
        acked, gift_id = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=5000)
        refunded = validate_success(
            api.refund_gift(gift_id, {"expected_gift_version": acked["version"]}, GA)
        )
        assert refunded["status"] == "REFUNDED"
        assert refunded["version"] > acked["version"], \
            "a successful refund increments the gift version"


class TestDerivedFieldReconciliation:
    def test_campaign_raised_hard_reconciled_through_refund(self, api):
        """PRD §2.7: "A refund is the exact compensating action: every total the
        acknowledgement touched returns to the value it held beforehand." PRD §3.3: "it
        recomputes the campaign's `raised_hard_cents` and `raised_with_match_cents`".

        raised_hard_cents reads 5000 after acknowledge and 0 after refund.

        Design: Corner/cross_cutting_complexity_layers/campaign_raised_derived_field_reconciliation_on_refund
        """
        camp, donor = setup_open_campaign_with_donor()
        acked, gift_id = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=5000)
        mid = validate_success(api.get_campaign(camp["id"], CM))
        assert mid["raised_hard_cents"] == 5000

        validate_success(api.refund_gift(gift_id, {"expected_gift_version": acked["version"]}, GA))
        final = validate_success(api.get_campaign(camp["id"], CM))
        assert final["raised_hard_cents"] == 0, "derived field reconciles back to 0 after refund"


class TestImmediateConsistency:
    def test_acknowledge_cascade_visible_in_response(self, api):
        """PRD §2.7: "when an operation changes a fact that feeds a derived total, every
        dependent total is recomputed inside the same request, atomically." PRD §3.3:
        "The transition `RECORDED → ACKNOWLEDGED` fans out a single atomic cascade ... it
        sets the gift's `acknowledged_at` to the current clock; it pins the gift's
        `deductible_amount_cents`".

        The acknowledge call's own response shows the cascade results immediately.

        Design: Corner/consistency_model/immediate_acknowledge_visible_in_response
        """
        camp, donor = setup_open_campaign_with_donor()
        gift = record_gift(camp["id"], donor["id"], amount_cents=20000, benefit_value_cents=5000)
        acked = validate_success(api.acknowledge_gift(gift["id"], DR))
        assert acked["status"] == "ACKNOWLEDGED"
        assert acked["deductible_amount_cents"] == 15000, "deductible pinned in the same response"
        assert acked["acknowledged_at"] is not None, "acknowledged_at stamped in the same response"
