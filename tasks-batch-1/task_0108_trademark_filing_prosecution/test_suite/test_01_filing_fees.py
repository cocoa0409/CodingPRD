"""Application filing-fee accounting: USE vs INTENT divergence, the surcharge-
then-multiply evaluation order, and immediate visibility of the locked fee.

Sources: Difficulty/dual_variant_calc, Difficulty/combinatorial_formula,
Corner/consistency_model.
"""
from test_helpers import (
    api_client,
    validate_success,
    setup_base_parties,
    create_draft_application,
    add_item,
    make_attorney_headers,
    examiner_headers,
)


class TestFilingFeeUseVsIntent:
    """Two TEAS_PLUS / 2-distinct-class apps diverge by basis: USE=50000,
    INTENT=70000 (INTENT adds a 10000-per-class surcharge)."""

    def _build(self, basis, tier="TEAS_PLUS"):
        base = setup_base_parties(class_numbers=(9, 25))
        att_headers = base["att_headers"]
        pre_approved = True if tier == "TEAS_PLUS" else None
        app = create_draft_application(
            base["applicant"]["id"], att_headers, attorney_id=base["attorney"]["id"],
            mark_text="ZEPHYR", filing_basis=basis, filing_tier=tier)
        for nc in base["nice_classes"]:
            add_item(app["id"], nc["id"], att_headers, pre_approved=pre_approved)
        return app, att_headers

    def test_use_basis_two_class_teas_plus_fee_is_50000(self, api):
        """PRD §3.2: "the per-class base amount is 25,000 cents for a TEAS_PLUS
        application and 35,000 cents for a TEAS_STANDARD application. For a USE-basis
        application the per-class amount is used as-is."
        PRD §3.2: "The final filing_fee_cents is the resulting per-class amount
        multiplied by the class_count."

        Design: Difficulty/dual_variant_calc/filing_fee_use_vs_intent_diverges
        """
        app, att_headers = self._build("USE")
        filed = validate_success(api.file_application(app["id"], att_headers), 200)
        assert filed["filing_fee_cents"] == 50000, (
            f"USE TEAS_PLUS 2-class should be 25000*2=50000, got {filed['filing_fee_cents']}")

    def test_intent_basis_two_class_teas_plus_fee_is_70000(self, api):
        """PRD §3.2: "For an INTENT-basis application — which reserves the mark
        before use — the per-class amount is increased by an intent surcharge of
        10,000 cents before multiplication. The final filing_fee_cents is the
        resulting per-class amount multiplied by the class_count."

        Design: Difficulty/dual_variant_calc/filing_fee_use_vs_intent_diverges
        """
        app, att_headers = self._build("INTENT")
        filed = validate_success(api.file_application(app["id"], att_headers), 200)
        assert filed["filing_fee_cents"] == 70000, (
            f"INTENT TEAS_PLUS 2-class should be (25000+10000)*2=70000, "
            f"got {filed['filing_fee_cents']}")


class TestFilingFeeSurchargeOrder:
    """Evaluation order is pinned: INTENT surcharge is added to per_class BEFORE
    multiplying by class_count, so INTENT TEAS_STANDARD 3-class = (35000+10000)*3
    = 135000 (not 35000*3+10000=115000)."""

    def test_intent_teas_standard_three_class_fee_is_135000(self, api):
        """PRD §3.2: "the per-class amount is increased by an intent surcharge of
        10,000 cents before multiplication. The final filing_fee_cents is the
        resulting per-class amount multiplied by the class_count."

        Design: Difficulty/combinatorial_formula/filing_fee_surcharge_then_multiply_order_mode_c
        """
        base = setup_base_parties(class_numbers=(9, 25, 35))
        att_headers = base["att_headers"]
        app = create_draft_application(
            base["applicant"]["id"], att_headers, attorney_id=base["attorney"]["id"],
            mark_text="VANTAGE", filing_basis="INTENT", filing_tier="TEAS_STANDARD")
        for nc in base["nice_classes"]:
            add_item(app["id"], nc["id"], att_headers)
        filed = validate_success(api.file_application(app["id"], att_headers), 200)
        assert filed["filing_fee_cents"] == 135000, (
            f"INTENT TEAS_STANDARD 3-class should be (35000+10000)*3=135000, "
            f"got {filed['filing_fee_cents']}")

    def test_intent_teas_standard_three_class_excludes_wrong_order_value(self, api):
        """PRD §3.2: "the per-class amount is increased by an intent surcharge of
        10,000 cents before multiplication. The final filing_fee_cents is the
        resulting per-class amount multiplied by the class_count."

        Design: Difficulty/combinatorial_formula/filing_fee_surcharge_then_multiply_order_mode_c
        """
        base = setup_base_parties(class_numbers=(9, 25, 35))
        att_headers = base["att_headers"]
        app = create_draft_application(
            base["applicant"]["id"], att_headers, attorney_id=base["attorney"]["id"],
            mark_text="VANTAGE2", filing_basis="INTENT", filing_tier="TEAS_STANDARD")
        for nc in base["nice_classes"]:
            add_item(app["id"], nc["id"], att_headers)
        filed = validate_success(api.file_application(app["id"], att_headers), 200)
        # The wrong order (35000*3)+10000 = 115000 must be excluded.
        assert filed["filing_fee_cents"] != 115000, (
            "surcharge must be applied before multiply, not after")
        assert filed["filing_fee_cents"] == 135000


class TestFilingFeeImmediateConsistency:
    """The DRAFT->FILED response surfaces the computed filing_fee_cents
    immediately — no read-after-write lag."""

    def test_filing_fee_visible_in_file_response(self, api):
        """PRD §3.2: "the per-class base amount is 25,000 cents for a TEAS_PLUS
        application and 35,000 cents for a TEAS_STANDARD application. For a USE-basis
        application the per-class amount is used as-is."

        Design: Corner/consistency_model/immediate_consistency_filing_fee_visible_in_same_response
        """
        base = setup_base_parties(class_numbers=(9,))
        att_headers = base["att_headers"]
        app = create_draft_application(
            base["applicant"]["id"], att_headers, attorney_id=base["attorney"]["id"],
            mark_text="IMMEDIATE", filing_basis="USE", filing_tier="TEAS_STANDARD")
        add_item(app["id"], base["nice_classes"][0]["id"], att_headers)
        filed = validate_success(api.file_application(app["id"], att_headers), 200)
        assert filed["filing_fee_cents"] == 35000, (
            f"USE TEAS_STANDARD single-class should be 35000, got {filed['filing_fee_cents']}")
        assert filed["status"] == "FILED"
