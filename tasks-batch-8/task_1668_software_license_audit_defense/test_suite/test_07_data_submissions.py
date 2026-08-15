"""Evidence packages: privilege review loop, release gates, segregation of duties,
and the auditor's RELEASED-only read window (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_case,
    approve_submission,
    assert_submission,
    api_client,
    confirm_scope_item,
    create_audit_case,
    create_data_submission_payload,
    create_product,
    create_submission,
    create_vendor_and_product,
    make_legal_counsel_headers,
    make_sam_manager_headers,
    propose_scope_item,
    release_submission,
    setup_case_in_evidence_collection,
    setup_case_with_confirmed_item,
    setup_product_with_gap,
    submit_for_review,
    validate_error,
    validate_success,
)


def _setup_submission_in_review():
    """Product with gap 5 (self-audit exposure 50000); case in
    EVIDENCE_COLLECTION with the product's item CONFIRMED; one package prepared
    by sam-mgr-1 and sent to privilege review."""
    product_ctx = setup_product_with_gap(entitled=100, deployed=105,
                                         unit_list_price_cents=10000,
                                         support_rate_pct=0.22)
    ctx = setup_case_in_evidence_collection(product_ctx)
    sub = create_submission(ctx["case"]["id"], [ctx["scope_item"]["id"]],
                            preparer_user_id="sam-mgr-1")
    submit_for_review(sub["id"], "sam-mgr-1")
    return ctx, sub


def _setup_zero_confirmed_coverage():
    """Two products, both CONFIRMED into scope; a package covering ONLY item B
    is approved; item B is then excluded while the case is still in
    SCOPE_NEGOTIATION; the case advances to EVIDENCE_COLLECTION on item A alone."""
    product_ctx_a = setup_product_with_gap(entitled=100, deployed=100,
                                           name="Prod A")
    vendor = product_ctx_a["vendor"]
    product_b = create_product(vendor["id"], name="Prod B",
                               unit_list_price_cents=5000, support_rate_pct=0.2)

    case = create_audit_case(vendor["id"])
    case = advance_case(case["id"], "SCOPE_NEGOTIATION")
    item_a = propose_scope_item(case["id"], product_ctx_a["product"]["id"],
                                rationale="A in scope")
    confirm_scope_item(item_a["id"])
    item_b = propose_scope_item(case["id"], product_b["id"],
                                rationale="B in scope")
    confirm_scope_item(item_b["id"])

    sub = create_submission(case["id"], [item_b["id"]],
                            preparer_user_id="sam-mgr-1",
                            submission_label="B-only package")
    submit_for_review(sub["id"], "sam-mgr-1")
    approve_submission(sub["id"], "counsel-1")

    validate_success(
        api_client.exclude_scope_item(item_b["id"],
                                      TEST_USERS["legal_counsel_headers"]), 200)
    advance_case(case["id"], "EVIDENCE_COLLECTION")
    return case, sub


class TestPrivilegeReturnCycle:
    def test_submission_return_loop_restores_draft(self, api, legal_counsel_headers):
        """PRD §3.6: "Sending a `DRAFT` package to privilege review moves it to
        `PRIVILEGE_REVIEW`. `LegalCounsel` then approves it — moving it to
        `APPROVED` — or returns it to `DRAFT` with a recorded `return_reason` so the
        preparer can redact and resubmit through the same loop."
        PRD §3.6: "`RELEASED` is the package's terminal state, and both
        `released_on` and `released_exposure_cents` remain null until it is
        reached."

        Design: Difficulty/non_linear_state_machine/submission_privilege_return_cycle
        """
        ctx, sub = _setup_submission_in_review()
        assert sub["status"] == "DRAFT"
        assert sub["released_on"] is None
        assert sub["released_exposure_cents"] is None

        returned = validate_success(
            api.return_submission(
                sub["id"],
                {"return_reason": "Contains internal legal memo; redact page 3"},
                legal_counsel_headers), 200)
        assert_submission(returned)
        assert returned["id"] == sub["id"], "the review loop runs on one row"
        assert returned["status"] == "DRAFT"

        resubmitted = validate_success(
            api.submit_for_review(sub["id"], make_sam_manager_headers("sam-mgr-1")),
            200)
        assert resubmitted["status"] == "PRIVILEGE_REVIEW"

    def test_submission_release_after_loop_freezes_exposure_snapshot(
            self, api, legal_counsel_headers):
        """PRD §3.6: "A successful release stamps `released_on` with the current
        logical clock and freezes `released_exposure_cents` as the sum of the
        `self_audit_exposure_cents` over the covered items that are `CONFIRMED` at
        that instant — a snapshot that never changes thereafter — and increments
        the parent case's `version` by one."

        Design: Difficulty/non_linear_state_machine/submission_privilege_return_cycle
        """
        ctx, sub = _setup_submission_in_review()
        api.return_submission(sub["id"], {"return_reason": "redact page 3"},
                              legal_counsel_headers)
        submit_for_review(sub["id"], "sam-mgr-1")

        approved = approve_submission(sub["id"], "counsel-1")
        assert approved["status"] == "APPROVED"

        released = release_submission(sub["id"], "counsel-1")
        assert released["id"] == sub["id"]
        assert released["status"] == "RELEASED"
        # Gap is 5 units at a 10000-cent list price.
        assert released["released_exposure_cents"] == 50000, \
            "the snapshot prices only the covered CONFIRMED item's self-audit exposure"
        assert released["released_on"] is not None


class TestReleaseCoverageGate:
    def test_release_with_no_confirmed_covered_items_rejected(
            self, api, legal_counsel_headers):
        """PRD §3.6: "And at least one covered scope item must be `CONFIRMED` at the
        moment of release, otherwise the release fails with
        `ERR_EMPTY_SUBMISSION_PACKAGE`."

        Design: Difficulty/boundary_precision_check/release_with_zero_confirmed_coverage_boundary
        """
        _case, sub = _setup_zero_confirmed_coverage()
        resp = api.release_submission(sub["id"], {}, legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_EMPTY_SUBMISSION_PACKAGE)

    def test_failed_release_preserves_approved_status(self, api,
                                                      legal_counsel_headers,
                                                      sam_manager_headers):
        """PRD §3.6: "And at least one covered scope item must be `CONFIRMED` at the
        moment of release, otherwise the release fails with
        `ERR_EMPTY_SUBMISSION_PACKAGE`."
        PRD §3.6: "`RELEASED` is the package's terminal state, and both
        `released_on` and `released_exposure_cents` remain null until it is
        reached."

        Design: Difficulty/boundary_precision_check/release_with_zero_confirmed_coverage_boundary
        """
        case, sub = _setup_zero_confirmed_coverage()
        resp = api.release_submission(sub["id"], {}, legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_EMPTY_SUBMISSION_PACKAGE)

        rows = validate_success(
            api.list_data_submissions(case["id"], sam_manager_headers), 200)
        still = next(r for r in rows if r["id"] == sub["id"])
        assert still["status"] == "APPROVED", \
            "a rejected release leaves the package APPROVED"
        assert still["released_on"] is None
        assert still["released_exposure_cents"] is None


class TestSegregationOfDuties:
    def test_sod_submission_approve_by_preparer_rejected(self, api):
        """PRD §3.6: "Each of these transitions requires the package to be in the
        expected prior status, failing with `ERR_SUBMISSION_INVALID_STATE`
        otherwise, and approval enforces segregation of duties: the approver's
        `X-User-ID` must differ from `prepared_by_user_id`, otherwise the request is
        rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

        Design: Corner/validations/sod_submission_approve_by_preparer_rejected
        """
        ctx = setup_case_with_confirmed_item()
        sub = create_submission(ctx["case"]["id"], [ctx["scope_item"]["id"]],
                                preparer_user_id="sam-mgr-1")
        submit_for_review(sub["id"], "sam-mgr-1")

        # The preparer carries a LegalCounsel role header but the same user id.
        resp = api.approve_submission(sub["id"], make_legal_counsel_headers("sam-mgr-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

        rows = validate_success(
            api.list_data_submissions(ctx["case"]["id"],
                                      make_sam_manager_headers("sam-mgr-1")), 200)
        still = next(r for r in rows if r["id"] == sub["id"])
        assert still["status"] == "PRIVILEGE_REVIEW", \
            "segregation of duties compares user ids, not roles"


class TestPrivilegedRelease:
    def test_privileged_release_requires_waiver_then_succeeds(
            self, api, legal_counsel_headers):
        """PRD §3.6: "A package whose `contains_privileged` is true may be released
        only when the request explicitly carries `privilege_waiver_confirmed` set to
        true, otherwise the release is rejected with
        `ERR_PRIVILEGED_CONTENT_REQUIRES_WAIVER`."

        Design: Corner/validations/privileged_release_requires_waiver_then_succeeds
        """
        ctx = setup_case_in_evidence_collection()
        sub = create_submission(ctx["case"]["id"], [ctx["scope_item"]["id"]],
                                preparer_user_id="sam-mgr-1",
                                submission_label="privileged pkg",
                                contains_privileged=True)
        assert sub["contains_privileged"] is True
        submit_for_review(sub["id"], "sam-mgr-1")
        approve_submission(sub["id"], "counsel-1")

        blocked = api.release_submission(sub["id"], {}, legal_counsel_headers)
        validate_error(blocked, ApiErrorId.ERR_PRIVILEGED_CONTENT_REQUIRES_WAIVER)

        released = validate_success(
            api.release_submission(sub["id"], {"privilege_waiver_confirmed": True},
                                   legal_counsel_headers), 200)
        assert released["status"] == "RELEASED", \
            "the identical release succeeds once the waiver is supplied"


class TestSubmissionCreateRules:
    def test_submission_scope_mismatch_across_cases(self, api, sam_manager_headers):
        """PRD §3.6: "A `SAMManager` prepares a DataSubmission for a case that is
        not yet `CLOSED_SETTLED`, `CLOSED_NO_ACTION`, or `WITHDRAWN` by supplying
        the `audit_case_id`, a human-readable `submission_label`, and a non-empty
        `covered_scope_item_ids` array naming the scope items whose position data
        the package covers; every named item must exist (`ERR_SCOPE_ITEM_NOT_FOUND`)
        and must belong to the same audit case as the package
        (`ERR_SUBMISSION_SCOPE_MISMATCH`)."

        Design: Corner/validations/submission_scope_mismatch_across_cases
        """
        vendor, product = create_vendor_and_product()
        case_1 = create_audit_case(vendor["id"])
        case_2 = create_audit_case(vendor["id"])
        item_1 = propose_scope_item(case_1["id"], product["id"],
                                    rationale="case 1 scope")

        resp = api.create_data_submission(
            create_data_submission_payload(case_2["id"], [item_1["id"]],
                                           submission_label="wrong-case pkg"),
            sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_SUBMISSION_SCOPE_MISMATCH)

    def test_submission_not_found_on_submit_for_review(self, api, sam_manager_headers):
        """PRD §3.6: "When a case's submissions are listed, a `VendorAuditor` sees
        only `RELEASED` rows through a server-side filter, while internal roles see
        all states and may apply a `status` filter; unknown submission identifiers
        surface as `ERR_SUBMISSION_NOT_FOUND`."

        Design: Corner/errors/submission_not_found_on_submit_for_review
        """
        resp = api.submit_for_review(NON_EXISTENT_UUID, sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_SUBMISSION_NOT_FOUND)


class TestAuditorReadWindow:
    def test_vendor_auditor_reads_only_released_submissions(
            self, api, vendor_auditor_headers, legal_counsel_headers):
        """PRD §2.1: "The `VendorAuditor` is an external party with a narrower
        window: it may read audit cases, scope items, and settlement offers, and it
        sees only `RELEASED` rows when listing a case's data submissions through a
        server-side filter; every other read attempted by the auditor is rejected
        with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §3.6: "When a case's submissions are listed, a `VendorAuditor` sees only
        `RELEASED` rows through a server-side filter, while internal roles see all
        states and may apply a `status` filter"

        Design: Corner/endpoints/vendor_auditor_reads_only_released_submissions
        """
        ctx = setup_case_in_evidence_collection()
        # S1 goes all the way to RELEASED.
        s1 = create_submission(ctx["case"]["id"], [ctx["scope_item"]["id"]],
                               preparer_user_id="sam-mgr-1", submission_label="S1")
        submit_for_review(s1["id"], "sam-mgr-1")
        approve_submission(s1["id"], "counsel-1")
        release_submission(s1["id"], "counsel-1")
        # S2 stays in DRAFT.
        s2 = create_submission(ctx["case"]["id"], [ctx["scope_item"]["id"]],
                               preparer_user_id="sam-mgr-1",
                               submission_label="S2 draft")
        assert s2["status"] == "DRAFT"

        auditor_rows = validate_success(
            api.list_data_submissions(ctx["case"]["id"], vendor_auditor_headers), 200)
        assert [r["id"] for r in auditor_rows] == [s1["id"]], \
            "the auditor sees exactly the RELEASED row"
        assert auditor_rows[0]["status"] == "RELEASED"

        counsel_rows = validate_success(
            api.list_data_submissions(ctx["case"]["id"], legal_counsel_headers), 200)
        assert {r["id"] for r in counsel_rows} == {s1["id"], s2["id"]}, \
            "internal roles see all states"
