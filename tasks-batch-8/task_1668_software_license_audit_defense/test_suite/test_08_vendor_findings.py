"""Vendor findings: per-line rounding discipline, basis flip, case rollup refresh,
and the two exits from FINDINGS_REVIEW (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    advance_case,
    confirm_scope_item,
    create_audit_case,
    create_confirmed_deployment,
    create_entitlement,
    create_product,
    create_submission,
    get_case,
    get_license_position,
    propose_scope_item,
    record_vendor_finding,
    release_submission,
    setup_case_in_findings_review,
    setup_product_with_gap,
    submit_for_review,
    approve_submission,
    validate_error,
    validate_success,
)


def _setup_two_item_findings_case():
    """Two products (unit 333, support 0.22), each entitled 10 with 11 CONFIRMED
    deployed (gap 1). One audit case carries both scope items CONFIRMED and sits in
    FINDINGS_REVIEW with a RELEASED package covering both items."""
    ctx1 = setup_product_with_gap(entitled=10, deployed=11,
                                  unit_list_price_cents=333, support_rate_pct=0.22,
                                  name="Prod One")
    vendor = ctx1["vendor"]
    product_2 = create_product(vendor["id"], name="Prod Two",
                               unit_list_price_cents=333, support_rate_pct=0.22)
    create_entitlement(product_2["id"], purchase_order_number="PO-P2", quantity=10)
    create_confirmed_deployment(product_2["id"], 11)

    case = create_audit_case(vendor["id"])
    case = advance_case(case["id"], "SCOPE_NEGOTIATION")
    item_1 = propose_scope_item(case["id"], ctx1["product"]["id"],
                                rationale="scope p1")
    confirm_scope_item(item_1["id"])
    item_2 = propose_scope_item(case["id"], product_2["id"], rationale="scope p2")
    confirm_scope_item(item_2["id"])
    case = advance_case(case["id"], "EVIDENCE_COLLECTION")

    sub = create_submission(case["id"], [item_1["id"], item_2["id"]],
                            preparer_user_id="sam-mgr-1",
                            submission_label="Deployment extracts")
    submit_for_review(sub["id"], "sam-mgr-1")
    approve_submission(sub["id"], "counsel-1")
    release_submission(sub["id"], "counsel-1")
    case = advance_case(case["id"], "FINDINGS_REVIEW")
    return {"case": case, "item_1": item_1, "item_2": item_2}


class TestPerLineRoundingOrder:
    def test_vendor_finding_line_rounded_half_up_per_line(self, api,
                                                          vendor_auditor_headers):
        """PRD §3.7: "The assessed amount is priced from the product's license
        position at the moment of the finding: the current `gap_quantity` multiplied
        by `unit_list_price_cents`, multiplied by one plus twice the
        `support_rate_pct` — that is, two years of back-support per missing unit —
        with the result rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/vendor_finding_per_line_rounding_order
        """
        ctx = _setup_two_item_findings_case()
        f1 = validate_success(
            api.record_vendor_finding(ctx["item_1"]["id"], vendor_auditor_headers), 200)
        # round_half_up(1 * 333 * (1 + 2*0.22)) = round_half_up(479.52) = 480.
        assert f1["vendor_finding_amount_cents"] == 480

        f2 = validate_success(
            api.record_vendor_finding(ctx["item_2"]["id"], vendor_auditor_headers), 200)
        assert f2["vendor_finding_amount_cents"] == 480

    def test_case_worst_case_sums_stored_lines(self, api, vendor_auditor_headers,
                                               legal_counsel_headers):
        """PRD §3.7: "The rounding order is pinned: each line is rounded to cents
        first and the lines are then summed; summing first and rounding the total
        once is a different, rejected algorithm that yields different totals
        whenever per-line fractions accumulate below half a cent."
        PRD §3.7: "The rounded per-line value is stored on the item as
        `vendor_finding_amount_cents` and is never recomputed retroactively; the
        case's `worst_case_exposure_cents` sums the stored per-line values exactly."

        Design: Difficulty/combinatorial_formula/vendor_finding_per_line_rounding_order
        """
        ctx = _setup_two_item_findings_case()
        api.record_vendor_finding(ctx["item_1"]["id"], vendor_auditor_headers)
        api.record_vendor_finding(ctx["item_2"]["id"], vendor_auditor_headers)

        case = validate_success(api.get_audit_case(ctx["case"]["id"],
                                                   legal_counsel_headers), 200)
        # Per-line round-then-sum: 480 + 480 = 960. Sum-then-round would give
        # round_half_up(2 * 479.52) = 959 — the one-cent delta proves the order.
        assert case["worst_case_exposure_cents"] == 960


class TestVendorFindingCascade:
    def _setup_single_item_case(self):
        """Product unit 5000, support 0.20, entitled 50, deployed 60 CONFIRMED
        (gap 10; vendor-list estimate 60000); case in FINDINGS_REVIEW."""
        product_ctx = setup_product_with_gap(entitled=50, deployed=60,
                                             unit_list_price_cents=5000,
                                             support_rate_pct=0.2,
                                             license_metric="PER_USER")
        return setup_case_in_findings_review(product_ctx)

    def test_vendor_finding_priced_with_two_year_back_support(
            self, api, vendor_auditor_headers, legal_counsel_headers):
        """PRD §3.7: "The assessed amount is priced from the product's license
        position at the moment of the finding: the current `gap_quantity` multiplied
        by `unit_list_price_cents`, multiplied by one plus twice the
        `support_rate_pct` — that is, two years of back-support per missing unit —
        with the result rounded half up to whole cents."
        PRD §3.5: "`worst_case_exposure_cents` sums, per confirmed item, the
        recorded `vendor_finding_amount_cents` where one exists and the product's
        `vendor_list_exposure_cents` otherwise, mixing recorded findings with
        vendor-list estimates as the negotiation floor and cap."

        Design: Difficulty/transitive_cascade/vendor_finding_cascade
        """
        ctx = self._setup_single_item_case()
        case_pre = get_case(ctx["case"]["id"])
        assert case_pre["worst_case_exposure_cents"] == 60000, \
            "no finding yet: worst case falls back to the vendor-list estimate " \
            "(10 * round_half_up(5000 * 1.20))"

        finding = validate_success(
            api.record_vendor_finding(ctx["scope_item"]["id"], vendor_auditor_headers),
            200)
        # round_half_up(10 * 5000 * (1 + 2 * 0.20)) = 70000 exactly.
        assert finding["vendor_finding_amount_cents"] == 70000

        case_post = get_case(ctx["case"]["id"])
        assert case_post["worst_case_exposure_cents"] == 70000, \
            "the recorded finding replaces the vendor-list estimate in the rollup"

    def test_vendor_finding_flips_position_basis_and_bumps_case_version(
            self, api, vendor_auditor_headers, legal_counsel_headers,
            sam_manager_headers):
        """PRD §3.7: "The first finding recorded on any confirmed item of a product
        flips that product's `position_basis` from `SELF_AUDIT` to
        `VENDOR_MEASURED`; the case rollups recompute and the case `version`
        increments by one."

        Design: Difficulty/transitive_cascade/vendor_finding_cascade
        """
        ctx = self._setup_single_item_case()
        case_pre = get_case(ctx["case"]["id"])
        assert ctx["position"]["position_basis"] == "SELF_AUDIT"

        validate_success(
            api.record_vendor_finding(ctx["scope_item"]["id"], vendor_auditor_headers),
            200)

        position = get_license_position(ctx["product"]["id"])
        assert position["position_basis"] == "VENDOR_MEASURED"

        case_post = get_case(ctx["case"]["id"])
        assert case_post["version"] == case_pre["version"] + 1, \
            "recording the finding increments the case version by exactly one"


class TestFindingsReviewExits:
    def test_advance_settlement_without_findings(self, api, legal_counsel_headers):
        """PRD §3.7: "Advancing to `SETTLEMENT_NEGOTIATION` requires every
        `CONFIRMED` scope item of the case to carry a recorded
        `vendor_finding_amount_cents`, failing with `ERR_FINDINGS_INCOMPLETE`
        otherwise."

        Design: Corner/validations/advance_settlement_without_findings
        """
        ctx = setup_case_in_findings_review()
        resp = api.advance_audit_case(ctx["case"]["id"],
                                      {"to_state": "SETTLEMENT_NEGOTIATION"},
                                      legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_FINDINGS_INCOMPLETE)

    def test_close_no_action_requires_zero_exposure(self, api, legal_counsel_headers):
        """PRD §3.7: "Advancing directly to `CLOSED_NO_ACTION` is permitted only
        when the case's `worst_case_exposure_cents` is exactly zero, failing with
        `ERR_EXPOSURE_NOT_ZERO` otherwise."

        Design: Corner/validations/close_no_action_requires_zero_exposure
        """
        product_ctx = setup_product_with_gap(entitled=100, deployed=130,
                                             unit_list_price_cents=10000,
                                             support_rate_pct=0.22)
        ctx = setup_case_in_findings_review(product_ctx)
        case = get_case(ctx["case"]["id"])
        assert case["worst_case_exposure_cents"] == 366000, \
            "30 * round_half_up(10000 * 1.22) = 366000"

        resp = api.advance_audit_case(ctx["case"]["id"],
                                      {"to_state": "CLOSED_NO_ACTION"},
                                      legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_EXPOSURE_NOT_ZERO)
