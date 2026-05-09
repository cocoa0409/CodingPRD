"""Reimbursement lifecycle tests: create + submit + multi-step approval + mark-paid.

PRD §3.3 (active operations: reimbursements and reject-rework loop).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_reimbursement,
    create_and_approve_reimbursement,
    create_and_pay_reimbursement,
    create_and_submit_reimbursement,
    dept_approve_reimbursement,
    finance_approve_reimbursement,
    get_budget_item,
    get_project,
    get_reimbursement,
    list_audit_logs,
    make_principal_investigator_headers,
    mark_paid_reimbursement,
    pi_approve_reimbursement,
    setup_active_project_with_budget,
    submit_reimbursement,
    validate_error,
    validate_success,
)


class TestReimbursementCreate:
    """PRD §3.3 creation invariants."""

    def test_create_category_mismatch(self, api):
        """PRD §3.3: "The expense_category must equal the linked BudgetItem's category
        (otherwise ERR_CATEGORY_MISMATCH)."

        Claim: expense_category != BudgetItem.category at create returns ERR_CATEGORY_MISMATCH.
        """
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-cat-mis", funding_source="NATIONAL",
            categories=[("MATERIALS", 1000.00)],
        )
        item = items[0]  # category=MATERIALS
        # Try to create reimbursement under TRAVEL even though linked item is MATERIALS.
        from test_helpers import create_reimbursement_payload, make_principal_investigator_headers
        from test_helpers import now_epoch
        payload = create_reimbursement_payload(
            project_id=project["id"], budget_item_id=item["id"],
            expense_category="TRAVEL", amount=100.00,
            invoice_date=now_epoch(api) - 60,
        )
        headers = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.create_reimbursement(payload, headers)
        validate_error(resp, ApiErrorId.ERR_CATEGORY_MISMATCH.value)

    def test_create_invoice_date_before_planned_start(self, api):
        """PRD §3.3: "The invoice_date must lie within the inclusive range from the
        project's planned_start_date up to the current server time
        (otherwise ERR_INVOICE_DATE_OUT_OF_RANGE)."

        # difficulty: resource_temporal_overlap/reimbursement_invoice_date_must_lie_in_project_active_window

        Claim: invoice_date strictly before planned_start_date returns ERR_INVOICE_DATE_OUT_OF_RANGE.
        """
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-inv-before", funding_source="NATIONAL",
            categories=[("MATERIALS", 1000.00)],
        )
        from test_helpers import create_reimbursement_payload, make_principal_investigator_headers
        # invoice_date = planned_start_date - 1 (one second before window)
        payload = create_reimbursement_payload(
            project_id=project["id"], budget_item_id=items[0]["id"],
            expense_category="MATERIALS", amount=100.00,
            invoice_date=project["planned_start_date"] - 1,
        )
        headers = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.create_reimbursement(payload, headers)
        validate_error(resp, ApiErrorId.ERR_INVOICE_DATE_OUT_OF_RANGE.value)

    def test_create_invoice_date_in_future_rejected(self, api):
        """PRD §3.3: "The invoice_date must lie within the inclusive range from the
        project's planned_start_date up to the current server time
        (otherwise ERR_INVOICE_DATE_OUT_OF_RANGE)."

        # difficulty: resource_temporal_overlap/reimbursement_invoice_date_must_lie_in_project_active_window

        Claim: invoice_date strictly after now() returns ERR_INVOICE_DATE_OUT_OF_RANGE.
        """
        from test_helpers import create_reimbursement_payload, make_principal_investigator_headers, now_epoch
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-inv-future", funding_source="NATIONAL",
            categories=[("MATERIALS", 1000.00)],
        )
        future_invoice_date = now_epoch(api) + 86400  # 1 day in the future
        payload = create_reimbursement_payload(
            project_id=project["id"], budget_item_id=items[0]["id"],
            expense_category="MATERIALS", amount=100.00,
            invoice_date=future_invoice_date,
        )
        headers = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.create_reimbursement(payload, headers)
        validate_error(resp, ApiErrorId.ERR_INVOICE_DATE_OUT_OF_RANGE.value)

    def test_create_duplicate_invoice_number_case_insensitive(self, api):
        """PRD §3.3: "The invoice_number must be unique within the parent project,
        compared case-insensitively (otherwise ERR_DUPLICATE_INVOICE_NUMBER)."

        # difficulty: resource_temporal_overlap/reimbursement_invoice_number_uniqueness_per_project

        Claim: a second reimbursement under the same project with invoice_number that
        differs only in case returns ERR_DUPLICATE_INVOICE_NUMBER.
        """
        from test_helpers import create_reimbursement_payload, make_principal_investigator_headers, now_epoch
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-dup-inv", funding_source="NATIONAL",
            categories=[("MATERIALS", 1000.00)],
        )
        # First create with INV-001 (uppercase)
        create_reimbursement(api, project=project, budget_item=items[0], amount=50.00,
                              invoice_number="INV-001")
        # Second create with inv-001 (lowercase) — should clash case-insensitively.
        payload = create_reimbursement_payload(
            project_id=project["id"], budget_item_id=items[0]["id"],
            expense_category="MATERIALS", amount=80.00,
            invoice_number="inv-001",
            invoice_date=now_epoch(api) - 60,
        )
        headers = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.create_reimbursement(payload, headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVOICE_NUMBER.value)

    def test_duplicate_invoice_allowed_across_different_projects(self, api):
        """PRD §3.3: "The invoice_number must be unique within the parent project,
        compared case-insensitively (otherwise ERR_DUPLICATE_INVOICE_NUMBER)."

        # difficulty: resource_temporal_overlap/reimbursement_invoice_number_uniqueness_per_project

        Claim: identical invoice_number across two different projects is allowed (control case).
        """
        p1, items1 = setup_active_project_with_budget(api, pi_id="pi-cross-1",
                                                        funding_source="NATIONAL",
                                                        categories=[("MATERIALS", 1000.00)])
        p2, items2 = setup_active_project_with_budget(api, pi_id="pi-cross-2",
                                                        funding_source="NATIONAL",
                                                        categories=[("MATERIALS", 1000.00)])
        # Both use the same invoice_number — both should succeed.
        r1 = create_reimbursement(api, project=p1, budget_item=items1[0], amount=50.00,
                                    invoice_number="INV-CROSS-001")
        r2 = create_reimbursement(api, project=p2, budget_item=items2[0], amount=50.00,
                                    invoice_number="INV-CROSS-001")
        assert r1["id"] != r2["id"]


class TestReimbursementSubmit:
    """PRD §3.3 submit preconditions."""

    def test_submit_requires_active_project(self, api):
        """PRD §3.3: "Submitting the reimbursement advances DRAFT → SUBMITTED.
        Submission requires that the parent project is ACTIVE
        (otherwise ERR_PROJECT_NOT_ACTIVE)..."

        # difficulty: cross_entity_state_dependency/reimbursement_submit_requires_project_active

        Claim: submitting a reimbursement when project.status != ACTIVE returns ERR_PROJECT_NOT_ACTIVE.
        Setup pattern: project APPROVED but not yet activated; budget item APPROVED.
        """
        from test_helpers import create_and_approve_project, make_principal_investigator_headers
        # APPROVED but not ACTIVE.
        project, items = create_and_approve_project(
            api, pi_id="pi-not-active",
            funding_source="NATIONAL",
            budget_items=[("MATERIALS", 1000.00)],
            start_offset_days=365,  # far-future start so cannot be activated yet
        )
        # We can create the reimbursement (no state check on create), but submit will fail.
        # Actually, the PRD says Reimbursement.create takes a project_id; nothing in
        # the create-time invariants references project state. Try create + submit.
        from test_helpers import create_reimbursement_payload, now_epoch
        # invoice_date must be in [planned_start_date, now()] — but planned_start_date is in
        # the future so the window is empty. Use planned_start_date itself if create allows it.
        # In APPROVED state we cannot have a valid invoice_date, so we need to first
        # construct a project where it's APPROVED but planned_start_date is also <= now.
        # Approach: build with a current start date but skip activation.
        # Easier: re-build with start_offset_days=0 and just don't activate.
        from test_helpers import create_draft_project, add_budget_item, submit_project
        from test_helpers import add_three_approving_reviews, approve_project, get_project
        from test_helpers import advance_clock_by_days
        # Build a project whose planned_start_date is slightly in the future (so submit
        # passes: planned_start_date >= now()), then advance the server clock past
        # planned_start_date so that we have a non-empty [planned_start_date, now()]
        # window for invoice_date. We deliberately do NOT activate, leaving the
        # project in APPROVED state.
        proj = create_draft_project(api, pi_id="pi-not-active-2", start_offset_days=1)
        item = add_budget_item(api, proj, category="MATERIALS", requested_amount=1000.00)
        proj = submit_project(api, proj)
        add_three_approving_reviews(api, proj["id"])
        approve_project(api, proj["id"])
        # Advance clock past planned_start_date so invoice_date window is non-empty.
        advance_clock_by_days(api, days=2)
        proj = get_project(api, proj["id"])  # status=APPROVED, not yet ACTIVE
        # Now create reimbursement
        from test_helpers import make_principal_investigator_headers
        item = get_budget_item(api, item["id"])
        # Even if BudgetItem is still PENDING (we didn't activate), we create then submit.
        from test_helpers import create_reimbursement_payload
        payload = create_reimbursement_payload(
            project_id=proj["id"], budget_item_id=item["id"],
            expense_category="MATERIALS", amount=100.00,
            invoice_date=max(proj["planned_start_date"], now_epoch(api) - 60),
        )
        headers = make_principal_investigator_headers("pi-not-active-2")
        rcreate = api.create_reimbursement(payload, headers)
        # If creation fails due to other reasons, fall back to assertion on the create.
        from test_helpers import get_success_data
        r = get_success_data(rcreate)
        # Now submit; expect ERR_PROJECT_NOT_ACTIVE.
        resp = api.submit_reimbursement(r["id"], headers)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_ACTIVE.value)
        # And reimbursement should still be in DRAFT.
        r_after = get_reimbursement(api, r["id"])
        assert r_after["status"] == "DRAFT"

    def test_submit_invoice_not_authentic(self, api):
        """PRD §3.3: "The invoice_authenticated flag must be true — a falsy value is
        treated as a BLOCK-severity safety violation and rejected with ERR_INVOICE_NOT_AUTHENTIC."

        Claim: submit with invoice_authenticated=false returns ERR_INVOICE_NOT_AUTHENTIC.
        """
        project, items = setup_active_project_with_budget(api, pi_id="pi-fake-inv")
        r = create_reimbursement(api, project=project, budget_item=items[0],
                                  amount=100.00, invoice_authenticated=False)
        from test_helpers import make_principal_investigator_headers
        headers = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.submit_reimbursement(r["id"], headers)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_AUTHENTIC.value)

    def test_submit_attachments_incomplete_missing_invoice(self, api):
        """PRD §3.3: "The attachments array must contain at least one entry whose kind
        is INVOICE and at least one entry whose kind is RECEIPT; if either kind is absent,
        the request is rejected with ERR_ATTACHMENTS_INCOMPLETE."

        Claim: missing kind=INVOICE returns ERR_ATTACHMENTS_INCOMPLETE.
        """
        project, items = setup_active_project_with_budget(api, pi_id="pi-no-inv")
        r = create_reimbursement(
            api, project=project, budget_item=items[0], amount=100.00,
            attachments=[{"filename": "rec.pdf", "kind": "RECEIPT"}],  # no INVOICE
        )
        from test_helpers import make_principal_investigator_headers
        headers = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.submit_reimbursement(r["id"], headers)
        validate_error(resp, ApiErrorId.ERR_ATTACHMENTS_INCOMPLETE.value)

    def test_submit_attachments_incomplete_missing_receipt(self, api):
        """PRD §3.3: "The attachments array must contain at least one entry whose kind
        is INVOICE and at least one entry whose kind is RECEIPT; if either kind is absent,
        the request is rejected with ERR_ATTACHMENTS_INCOMPLETE."

        Claim: missing kind=RECEIPT returns ERR_ATTACHMENTS_INCOMPLETE.
        """
        project, items = setup_active_project_with_budget(api, pi_id="pi-no-rec")
        r = create_reimbursement(
            api, project=project, budget_item=items[0], amount=100.00,
            attachments=[{"filename": "inv.pdf", "kind": "INVOICE"}],  # no RECEIPT
        )
        from test_helpers import make_principal_investigator_headers
        headers = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.submit_reimbursement(r["id"], headers)
        validate_error(resp, ApiErrorId.ERR_ATTACHMENTS_INCOMPLETE.value)

    def test_submit_succeeds_advances_to_submitted(self, api):
        """PRD §3.3: "the produced findings ... are written to compliance_findings on the
        reimbursement, the status advances to SUBMITTED, and rejection_reason is cleared
        (set to null)."

        Claim: a clean submit transitions DRAFT → SUBMITTED with rejection_reason=null.
        """
        project, items = setup_active_project_with_budget(api, pi_id="pi-submit-ok")
        r = create_reimbursement(api, project=project, budget_item=items[0], amount=100.00)
        from test_helpers import make_principal_investigator_headers
        headers = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.submit_reimbursement(r["id"], headers)
        data = validate_success(resp)
        assert data["status"] == "SUBMITTED"
        assert data.get("rejection_reason") is None


class TestApprovalChain:
    """PRD §3.3 approval chain."""

    def test_pi_approve_not_owner(self, api):
        """PRD §3.3: "The acting X-User-ID must equal the project's principal_investigator_id
        (otherwise ERR_NOT_PROJECT_OWNER)."

        Claim: pi-approve by a non-owner returns ERR_NOT_PROJECT_OWNER.
        """
        project, items = setup_active_project_with_budget(api, pi_id="pi-real-owner-pi")
        r = create_reimbursement(api, project=project, budget_item=items[0], amount=100.00)
        from test_helpers import make_principal_investigator_headers
        owner_headers = make_principal_investigator_headers(project["principal_investigator_id"])
        api.submit_reimbursement(r["id"], owner_headers)
        wrong = make_principal_investigator_headers("pi-other")
        resp = api.pi_approve_reimbursement(r["id"], wrong)
        validate_error(resp, ApiErrorId.ERR_NOT_PROJECT_OWNER.value)

    def test_dept_approve_requires_pi_approved(self, api, dept_headers):
        """PRD §3.3: "The precondition is that pi_decision already equals APPROVED;
        otherwise the request is rejected with ERR_PI_DECISION_PENDING."

        PRD §2.7 puts state-machine eligibility ahead of business preconditions, and
        in this scenario the reimbursement is also still in SUBMITTED (not UNDER_REVIEW)
        because pi-approve is the only transition to UNDER_REVIEW. PRD does not
        explicitly state that the pi_decision check pre-empts the status check, so
        a faithful implementer may surface either ERR_INVALID_STATE (per §2.7) or
        ERR_PI_DECISION_PENDING (per §3.3). Both are PRD-named.

        Claim: dept-approve before pi-approve returns ERR_PI_DECISION_PENDING or
        ERR_INVALID_STATE.
        """
        from test_helpers import validate_error_is_one_of
        project, items = setup_active_project_with_budget(api, pi_id="pi-dept-early")
        r = create_reimbursement(api, project=project, budget_item=items[0], amount=100.00)
        submit_reimbursement(api, r)
        # Skip pi-approve; go straight to dept-approve.
        resp = api.dept_approve_reimbursement(r["id"], dept_headers)
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_PI_DECISION_PENDING.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])

    def test_finance_approve_budget_insufficient(self, api):
        """PRD §3.3: "...that the linked BudgetItem's remaining_amount is at or above
        the reimbursement's amount (otherwise ERR_BUDGET_INSUFFICIENT, HTTP 402)."

        Claim: a reimbursement amount > BudgetItem.remaining_amount returns ERR_BUDGET_INSUFFICIENT.
        """
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-bud-insufficient", funding_source="NATIONAL",
            categories=[("MATERIALS", 100.00)],  # only 100 available
        )
        # Create reimbursement for amount=200 (more than 100 remaining)
        r = create_reimbursement(api, project=project, budget_item=items[0], amount=200.00)
        from test_helpers import make_principal_investigator_headers
        owner = make_principal_investigator_headers(project["principal_investigator_id"])
        api.submit_reimbursement(r["id"], owner)
        api.pi_approve_reimbursement(r["id"], owner)
        from test_helpers import DEPT_HEADERS, FINANCE_HEADERS
        api.dept_approve_reimbursement(r["id"], DEPT_HEADERS)
        resp = api.finance_approve_reimbursement(r["id"], FINANCE_HEADERS)
        validate_error(resp, ApiErrorId.ERR_BUDGET_INSUFFICIENT.value)


class TestMarkPaid:
    """PRD §3.3 mark-paid side effects."""

    def test_mark_paid_debits_budget_item(self, api):
        """PRD §3.3: "On commit, the reimbursement's amount is added to the linked
        BudgetItem's spent_amount, the item's remaining_amount is recomputed (it equals
        approved_amount minus spent_amount), the item's version increments by 1, and its
        updated_at is refreshed. The same amount is added to the parent project's total_reimbursed."

        Claim: mark-paid debits BudgetItem.spent_amount, refreshes remaining_amount, bumps
        version, and increments Project.total_reimbursed by the amount.
        """
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-pay-debit", funding_source="NATIONAL",
            categories=[("MATERIALS", 1000.00)],
        )
        item = items[0]
        version_before = item["version"]
        amount = 250.00
        token = r_token()
        r = create_and_pay_reimbursement(api, project=project, budget_item=item,
                                          amount=amount,
                                          invoice_number=f"INV-PAY-{token}")
        # Read budget item after payment.
        item_after = get_budget_item(api, item["id"])
        assert item_after["spent_amount"] == pytest.approx(amount, abs=0.01)
        assert item_after["remaining_amount"] == pytest.approx(1000.00 - amount, abs=0.01)
        assert item_after["version"] == version_before + 1
        # Project.total_reimbursed
        project_after = get_project(api, project["id"])
        assert project_after["total_reimbursed"] == pytest.approx(amount, abs=0.01)

    def test_mark_paid_appends_audit_logs(self, api):
        """PRD §3.3: "Two AuditLog rows are appended: one with subject_type set to
        REIMBURSEMENT and action set to PAY, and one with subject_type set to BUDGET_ITEM
        and action set to UPDATE capturing the spent-amount delta."

        Claim: mark-paid emits one REIMBURSEMENT/PAY log and one BUDGET_ITEM/UPDATE log.
        """
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-pay-log", funding_source="NATIONAL",
            categories=[("MATERIALS", 1000.00)],
        )
        item = items[0]
        r = create_and_pay_reimbursement(api, project=project, budget_item=item,
                                          amount=300.00, invoice_number=f"INV-LOG-{r_token()}")
        # PAY log on the reimbursement
        reimb_logs = list_audit_logs(api, subject_type="REIMBURSEMENT", subject_id=r["id"])
        assert any(l.get("action") == "PAY" for l in reimb_logs), \
            f"Expected at least one REIMBURSEMENT/PAY log; got {reimb_logs}"
        # UPDATE log on the budget item
        bi_logs = list_audit_logs(api, subject_type="BUDGET_ITEM", subject_id=item["id"])
        assert any(l.get("action") == "UPDATE" for l in bi_logs), \
            f"Expected at least one BUDGET_ITEM/UPDATE log; got {bi_logs}"


def r_token() -> str:
    """Tiny helper to generate unique invoice tokens within a test session."""
    import uuid
    return uuid.uuid4().hex[:6]
