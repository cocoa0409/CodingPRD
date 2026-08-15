"""Audit case lifecycle: advance gates, rollup variants, withdrawal, and the
evidence-reopen loop (PRD §3.5, §3.7)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    advance_case,
    approve_submission,
    assert_audit_case,
    confirm_scope_item,
    create_audit_case,
    create_confirmed_deployment,
    create_entitlement,
    create_product,
    create_submission,
    get_case,
    propose_scope_item,
    release_submission,
    setup_case_in_evidence_collection,
    setup_case_in_findings_review,
    setup_case_in_scope_negotiation,
    setup_product_with_gap,
    submit_for_review,
    validate_error,
    validate_success,
)


class TestCaseRollupVariants:
    def _setup_two_product_case(self):
        """P_A: gap 30 (self 300000, vendor-list 366000); P_B: gap 10
        (self 50000, vendor-list 60000); both CONFIRMED into one case's scope."""
        ctx_a = setup_product_with_gap(entitled=100, deployed=130,
                                       unit_list_price_cents=10000,
                                       support_rate_pct=0.22,
                                       name="DataGrid Server")
        product_b = create_product(ctx_a["vendor"]["id"], name="QueryTool Desktop",
                                   license_metric="PER_USER",
                                   unit_list_price_cents=5000, support_rate_pct=0.2)
        create_entitlement(product_b["id"], purchase_order_number="PO-B1",
                           quantity=50)
        create_confirmed_deployment(product_b["id"], 60)

        case = create_audit_case(ctx_a["vendor"]["id"])
        case = advance_case(case["id"], "SCOPE_NEGOTIATION")
        item_a = propose_scope_item(case["id"], ctx_a["product"]["id"],
                                    rationale="DataGrid believed deployed")
        confirm_scope_item(item_a["id"])
        item_b = propose_scope_item(case["id"], product_b["id"],
                                    rationale="QueryTool believed deployed")
        confirm_scope_item(item_b["id"])
        return case["id"]

    def test_case_provisional_rollup_uses_self_audit_basis(self, api,
                                                           legal_counsel_headers):
        """PRD §3.5: "`provisional_case_exposure_cents` sums the
        `self_audit_exposure_cents` of each confirmed product's position and
        represents the pure self-audit basis before any vendor finding is recorded."

        Design: Difficulty/dual_variant_calc/case_rollup_provisional_vs_worst_case
        """
        case_id = self._setup_two_product_case()
        case = validate_success(api.get_audit_case(case_id, legal_counsel_headers), 200)
        assert_audit_case(case)
        assert case["provisional_case_exposure_cents"] == 350000, \
            "300000 (DataGrid gap 30 at list) + 50000 (QueryTool gap 10 at list)"

    def test_case_worst_case_rollup_uses_vendor_list_basis(self, api,
                                                           legal_counsel_headers):
        """PRD §3.5: "`worst_case_exposure_cents` sums, per confirmed item, the
        recorded `vendor_finding_amount_cents` where one exists and the product's
        `vendor_list_exposure_cents` otherwise, mixing recorded findings with
        vendor-list estimates as the negotiation floor and cap."
        PRD §3.5: "Both totals add stored integer cents exactly, with no re-rounding
        at the total."

        Design: Difficulty/dual_variant_calc/case_rollup_provisional_vs_worst_case
        """
        case_id = self._setup_two_product_case()
        case = validate_success(api.get_audit_case(case_id, legal_counsel_headers), 200)
        # No findings recorded: worst case falls back to vendor-list exposures.
        # 366000 (30 * round_half_up(10000*1.22)) + 60000 (10 * round_half_up(5000*1.20)).
        assert case["worst_case_exposure_cents"] == 426000


class TestAdvanceGates:
    def test_advance_with_proposed_items_pending(self, api, legal_counsel_headers):
        """PRD §3.5: "Advancing from `SCOPE_NEGOTIATION` to `EVIDENCE_COLLECTION`
        requires that no scope item of the case remains in `PROPOSED` or `DISPUTED`
        status — otherwise the advance fails with `ERR_SCOPE_ITEMS_PENDING` — and
        that at least one scope item is `CONFIRMED`, otherwise
        `ERR_EMPTY_AUDIT_SCOPE`."

        Design: Corner/validations/advance_with_proposed_items_pending
        """
        ctx = setup_case_in_scope_negotiation()
        propose_scope_item(ctx["case"]["id"], ctx["product"]["id"],
                           rationale="undecided")

        resp = api.advance_audit_case(ctx["case"]["id"],
                                      {"to_state": "EVIDENCE_COLLECTION"},
                                      legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_SCOPE_ITEMS_PENDING)
        assert get_case(ctx["case"]["id"])["status"] == "SCOPE_NEGOTIATION"

    def test_advance_with_empty_scope(self, api, legal_counsel_headers):
        """PRD §3.5: "Advancing from `SCOPE_NEGOTIATION` to `EVIDENCE_COLLECTION`
        requires that no scope item of the case remains in `PROPOSED` or `DISPUTED`
        status — otherwise the advance fails with `ERR_SCOPE_ITEMS_PENDING` — and
        that at least one scope item is `CONFIRMED`, otherwise
        `ERR_EMPTY_AUDIT_SCOPE`."

        Design: Corner/validations/advance_with_empty_scope
        """
        ctx = setup_case_in_scope_negotiation()
        resp = api.advance_audit_case(ctx["case"]["id"],
                                      {"to_state": "EVIDENCE_COLLECTION"},
                                      legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_EMPTY_AUDIT_SCOPE)

    def test_case_skip_states_rejected(self, api, legal_counsel_headers):
        """PRD §3.5: "The case begins in `NOTICE_RECEIVED` and follows the lifecycle
        `NOTICE_RECEIVED` → `SCOPE_NEGOTIATION` → `EVIDENCE_COLLECTION` →
        `FINDINGS_REVIEW` → `SETTLEMENT_NEGOTIATION`, terminating in
        `CLOSED_SETTLED`, `CLOSED_NO_ACTION`, or `WITHDRAWN`."
        PRD §3.5: "Any advance that does not match the case's current status is
        rejected with `ERR_AUDIT_CASE_INVALID_STATE`."

        Design: Corner/state_machines/case_skip_states_rejected
        """
        ctx = setup_case_in_evidence_collection()
        resp = api.advance_audit_case(ctx["case"]["id"],
                                      {"to_state": "SETTLEMENT_NEGOTIATION"},
                                      legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_AUDIT_CASE_INVALID_STATE)


class TestFindingsReviewGate:
    def test_advance_to_findings_review_without_release_rejected(
            self, api, legal_counsel_headers):
        """PRD §3.5: "Advancing from `EVIDENCE_COLLECTION` to `FINDINGS_REVIEW`
        requires that the case has at least one data submission in `RELEASED`
        status, otherwise `ERR_NO_RELEASED_SUBMISSION`."

        Design: Difficulty/cross_entity_state_dependency/findings_review_requires_released_submission
        """
        ctx = setup_case_in_evidence_collection()
        sub = create_submission(ctx["case"]["id"], [ctx["scope_item"]["id"]])
        assert sub["status"] == "DRAFT"

        resp = api.advance_audit_case(ctx["case"]["id"],
                                      {"to_state": "FINDINGS_REVIEW"},
                                      legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_NO_RELEASED_SUBMISSION)

    def test_failed_advance_leaves_case_and_submission_unchanged(
            self, api, legal_counsel_headers, sam_manager_headers):
        """PRD §3.5: "Advancing from `EVIDENCE_COLLECTION` to `FINDINGS_REVIEW`
        requires that the case has at least one data submission in `RELEASED`
        status, otherwise `ERR_NO_RELEASED_SUBMISSION`."

        Design: Difficulty/cross_entity_state_dependency/findings_review_requires_released_submission
        """
        ctx = setup_case_in_evidence_collection()
        sub = create_submission(ctx["case"]["id"], [ctx["scope_item"]["id"]])

        resp = api.advance_audit_case(ctx["case"]["id"],
                                      {"to_state": "FINDINGS_REVIEW"},
                                      legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_NO_RELEASED_SUBMISSION)
        assert get_case(ctx["case"]["id"])["status"] == "EVIDENCE_COLLECTION", \
            "the rejected advance does not move the case"

        rows = validate_success(
            api.list_data_submissions(ctx["case"]["id"], sam_manager_headers), 200)
        still = next(r for r in rows if r["id"] == sub["id"])
        assert still["status"] == "DRAFT"

        # Positive companion: once the package is RELEASED the same advance succeeds.
        submit_for_review(sub["id"])
        approve_submission(sub["id"])
        release_submission(sub["id"])
        advanced = advance_case(ctx["case"]["id"], "FINDINGS_REVIEW")
        assert advanced["status"] == "FINDINGS_REVIEW"


class TestWithdrawalAndReopen:
    def test_case_withdraw_then_advance_rejected(self, api, legal_counsel_headers,
                                                 vendor_auditor_headers):
        """PRD §3.7: "The vendor may abandon the audit entirely: a `VendorAuditor`
        withdrawal moves the case from any non-terminal state to `WITHDRAWN` —
        attempting it on a closed or already withdrawn case fails with
        `ERR_AUDIT_CASE_INVALID_STATE` — and cascades through the case's open work"
        PRD §3.5: "Any advance that does not match the case's current status is
        rejected with `ERR_AUDIT_CASE_INVALID_STATE`."

        Design: Corner/state_machines/case_withdraw_then_advance_rejected
        """
        ctx = setup_case_in_scope_negotiation()
        withdrawn = validate_success(
            api.withdraw_audit_case(ctx["case"]["id"], vendor_auditor_headers), 200)
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api.advance_audit_case(ctx["case"]["id"],
                                      {"to_state": "SCOPE_NEGOTIATION"},
                                      legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_AUDIT_CASE_INVALID_STATE)

    def test_case_reopen_evidence_cycle(self, api, vendor_auditor_headers):
        """PRD §3.7: "The vendor may also push the case back for more data: a
        `VendorAuditor` request for supplemental evidence reopens the case from
        `FINDINGS_REVIEW` to `EVIDENCE_COLLECTION`, incrementing the case `version`
        by one."

        Design: Corner/state_machines/case_reopen_evidence_cycle
        """
        ctx = setup_case_in_findings_review()
        version_pre = ctx["case"]["version"]

        resp = api.reopen_evidence(ctx["case"]["id"], vendor_auditor_headers)
        reopened = validate_success(resp, 200)
        assert_audit_case(reopened)
        assert reopened["status"] == "EVIDENCE_COLLECTION"
        assert reopened["version"] == version_pre + 1, \
            "reopening evidence increments the case version by exactly one"


class TestCaseReadErrors:
    def test_audit_case_not_found_returns_404(self, api, legal_counsel_headers):
        """PRD §3.5: "Case listings support optional `vendor_id` and `status`
        filters, and unknown case identifiers surface as
        `ERR_AUDIT_CASE_NOT_FOUND`."

        Design: Corner/errors/audit_case_not_found_returns_404
        """
        resp = api.get_audit_case(NON_EXISTENT_UUID, legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_AUDIT_CASE_NOT_FOUND)
