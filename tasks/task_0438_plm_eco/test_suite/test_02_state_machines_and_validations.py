"""State-machine transitions, guarded preconditions, and business validations.

Breadth coverage of the state_machines / validations / rbac surface across part
revisions, documents, ECRs, ECOs, deviations, PCNs, and serialized units
(PRD 3.2-3.11).
"""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_change_admin_headers, make_approver_headers,
    factories, get_success_data, fixtures,
)

DESIGNER = TEST_USERS["designer_headers"]
SUPPLIER_MGR = TEST_USERS["supplier_manager_headers"]
QUALITY = TEST_USERS["quality_engineer_headers"]
VIEWER = TEST_USERS["viewer_headers"]
CA = "ca1"
CHANGE_ADMIN = make_change_admin_headers(CA)
AP1 = make_approver_headers("ap1")


class TestRevisionTransitions:
    def test_initial_state_working_on_revision_create(self, api):
        """PRD 3.2: "The create increments both the part's `revision_count` and its
        `version`, and the revision begins in `lifecycle_state` `WORKING`."
        PRD 3.2: "The system assigns the next `rev_label` in the per-part sequence — the
        first revision is `A`, then `B`, `C`, and so on — and the revision's `part_id`
        is set from the parent part."

        Design: Corner/state_machines/initial_state_working_on_revision_create
        """
        part = fixtures.create_part("MAKE", base_cost_cents=0)
        rev = validate_success(
            api.create_revision(part["id"],
                                factories.create_revision_payload(part["version"]), DESIGNER),
            expected_status=201)
        assert rev["lifecycle_state"] == "WORKING", rev
        assert rev["rev_label"] == "A", rev
        assert rev["supersedes_revision_id"] is None, rev

    # SKIPPED Corner/state_machines/submit_review_from_in_review_invalid_state:
    # the PRD never names an error_id (and never names ERR_INVALID_STATE) for calling
    # submit-review on a non-WORKING revision. ERR_INVALID_STATE appears in PRD prose
    # only for the approval-task IN_APPROVAL precondition (PRD 3.6); the PRD section 5
    # error table alone is not coverage. A faithful PRD-only implementer could return a
    # different 4xx, so the asserted outcome is not uniquely derivable. Gap left as a gap.

    def test_empty_bom_blocks_submit_review(self, api):
        """PRD 3.2: "before this is permitted, a revision whose part is of type `MAKE`
        or `PHANTOM` must have at least one bill-of-material line, otherwise the
        submission is rejected with `ERR_EMPTY_BOM`."

        Design: Corner/state_machines/empty_bom_blocks_submit_review
        """
        part = fixtures.create_part("MAKE", base_cost_cents=0)
        rev = fixtures.create_revision(part["id"])  # no BOM lines
        resp = api.submit_revision_review(rev["id"], DESIGNER)
        validate_error(resp, ApiErrorId.ERR_EMPTY_BOM)


class TestChangeRequestTransitions:
    def test_reopen_rejected_ecr_clears_submitter(self, api):
        """PRD 3.5: "A rejected request is not dead: a `Designer` may reopen it, which
        clears `submitted_by_user_id` and returns it `REJECTED → DRAFT`, closing the
        revision loop."

        Design: Corner/state_machines/ecr_return_to_draft_via_reopen_cycle
        """
        part = fixtures.create_part("PHANTOM")
        ecr = get_success_data(api.create_change_request(
            factories.create_change_request_payload(part["id"], reason_code="OBSOLESCENCE"),
            DESIGNER))
        get_success_data(api.submit_change_request(ecr["id"], DESIGNER))
        get_success_data(api.reject_change_request(ecr["id"], CHANGE_ADMIN))
        reopened = validate_success(api.reopen_change_request(ecr["id"], DESIGNER))
        assert reopened["status"] == "DRAFT", reopened
        assert reopened["submitted_by_user_id"] is None, reopened


class TestDocumentTransitions:
    # SKIPPED Corner/state_machines/terminal_state_obsolete_locked:
    # the PRD never names an error_id for re-obsoleting an already-OBSOLETE document.
    # ERR_INVALID_STATE appears in PRD prose only for the approval-task IN_APPROVAL
    # precondition (PRD 3.6); the PRD section 5 error table alone is not coverage, and
    # the terminal-lock outcome is not uniquely derivable from PRD prose. Gap as a gap.

    def test_release_document_requires_released_part(self, api):
        """PRD 3.9: "A `ChangeAdmin` releases a reviewed document (`IN_REVIEW →
        RELEASED`); if the document is attached to a part, that part must itself have a
        released revision (its `released_revision_id` must not be null), otherwise the
        release is rejected with `ERR_PART_NOT_RELEASED`."

        Design: Corner/state_machines/document_release_requires_released_part_cross_entity
        """
        part = fixtures.create_part("MAKE", base_cost_cents=0)  # no released revision
        doc = fixtures.create_in_review_document(part_id=part["id"], doc_type="CAD")
        resp = api.release_document(doc["id"], CHANGE_ADMIN)
        validate_error(resp, ApiErrorId.ERR_PART_NOT_RELEASED)


class TestSerializedUnitTransitions:
    def test_ship_nonconforming_unit_blocked(self, api):
        """PRD 3.11: "a unit may ship only when its `conformance_status` is either
        `CONFORMING` or `WAIVED`; shipping a `NONCONFORMING` unit is rejected with
        `ERR_UNIT_NONCONFORMING`."

        Design: Corner/state_machines/ship_nonconforming_unit_blocked
        """
        _part, rev, _leaf = fixtures.create_released_make_part()
        unit = fixtures.create_built_unit(rev["id"])
        get_success_data(api.flag_unit_nonconforming(unit["id"], QUALITY))
        resp = api.ship_serialized_unit(unit["id"], QUALITY)
        validate_error(resp, ApiErrorId.ERR_UNIT_NONCONFORMING)


class TestPcnTransitions:
    def test_accept_non_buy_part_blocked(self, api):
        """PRD 3.8: "Acceptance is only permitted when the `affected_part_id` part is of
        type `BUY`; accepting against a non-`BUY` part is rejected with
        `ERR_PART_NOT_BUY`."

        Design: Corner/state_machines/pcn_accept_non_buy_part_blocked
        """
        sup = fixtures.create_supplier()
        part = fixtures.create_part("MAKE", base_cost_cents=0)
        pcn = fixtures.create_assessed_pcn(sup["id"], part["id"])
        resp = api.accept_pcn(pcn["id"], SUPPLIER_MGR)
        validate_error(resp, ApiErrorId.ERR_PART_NOT_BUY)


class TestChangeOrderSubmitPreconditions:
    def test_submit_without_affected_items_blocked(self, api):
        """PRD 3.5: "first, the order must have at least one affected item, else
        `ERR_NO_AFFECTED_ITEMS`".

        Design: Corner/state_machines/eco_submit_without_affected_items_blocked
        """
        part = fixtures.create_part("PHANTOM")
        ecr = fixtures.create_approved_ecr(part["id"], reason_code="COST_REDUCTION")
        eco = get_success_data(api.create_change_order(
            factories.create_change_order_payload(
                ecr["id"], "2026-02-01T00:00:00Z", required_approvals=1), CHANGE_ADMIN))
        get_success_data(api.add_approval_task(
            eco["id"], factories.create_approval_task_payload("ap1"), CHANGE_ADMIN))
        resp = api.submit_eco_for_approval(eco["id"], CHANGE_ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_AFFECTED_ITEMS)

    def test_submit_insufficient_approvers_blocked(self, api):
        """PRD 3.5: "second, it must have at least `required_approvals` distinct approval
        tasks, else `ERR_INSUFFICIENT_APPROVERS`".

        Design: Corner/state_machines/eco_submit_insufficient_approvers_blocked
        """
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part, rev = fixtures.create_make_revision_with_bom(leaf["id"], base_cost_cents=0)
        get_success_data(api.submit_revision_review(rev["id"], DESIGNER))
        ecr = fixtures.create_approved_ecr(part["id"])
        eco = get_success_data(api.create_change_order(
            factories.create_change_order_payload(
                ecr["id"], "2026-02-01T00:00:00Z", required_approvals=2), CHANGE_ADMIN))
        get_success_data(api.add_affected_item(
            eco["id"], factories.create_affected_item_payload(rev["id"]), CHANGE_ADMIN))
        get_success_data(api.add_approval_task(
            eco["id"], factories.create_approval_task_payload("ap1"), CHANGE_ADMIN))
        resp = api.submit_eco_for_approval(eco["id"], CHANGE_ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_APPROVERS)

    def test_submit_with_unapproved_ecr_blocked(self, api):
        """PRD 3.5: "and third, the implemented change request identified by
        `change_request_id` must itself be in `APPROVED` status, else
        `ERR_ECR_NOT_APPROVED`."

        Design: Corner/state_machines/eco_submit_with_unapproved_ecr_blocked
        """
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part, rev = fixtures.create_make_revision_with_bom(leaf["id"], base_cost_cents=0)
        get_success_data(api.submit_revision_review(rev["id"], DESIGNER))
        # ECR submitted then rejected, so it is not APPROVED; the ECO is built against it.
        ecr = get_success_data(api.create_change_request(
            factories.create_change_request_payload(part["id"]), DESIGNER))
        get_success_data(api.submit_change_request(ecr["id"], DESIGNER))
        get_success_data(api.reject_change_request(ecr["id"], CHANGE_ADMIN))
        eco = get_success_data(api.create_change_order(
            factories.create_change_order_payload(
                ecr["id"], "2026-02-01T00:00:00Z", required_approvals=1), CHANGE_ADMIN))
        get_success_data(api.add_affected_item(
            eco["id"], factories.create_affected_item_payload(rev["id"]), CHANGE_ADMIN))
        get_success_data(api.add_approval_task(
            eco["id"], factories.create_approval_task_payload("ap1"), CHANGE_ADMIN))
        resp = api.submit_eco_for_approval(eco["id"], CHANGE_ADMIN)
        validate_error(resp, ApiErrorId.ERR_ECR_NOT_APPROVED)


class TestApprovalTaskCascades:
    def test_reject_task_cascades_eco_rejected(self, api):
        """PRD 3.6: "A rejection takes effect immediately and decisively: a single
        rejected task cascades the order `IN_APPROVAL → REJECTED`."

        Design: Corner/state_machines/approval_task_reject_cascades_eco_rejected
        """
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part, rev = fixtures.create_make_revision_with_bom(leaf["id"], base_cost_cents=0)
        get_success_data(api.submit_revision_review(rev["id"], DESIGNER))
        eco, task_ids = fixtures.create_in_approval_eco(
            part["id"], rev["id"], effectivity_date="2026-02-01T00:00:00Z",
            required_approvals=1, assignees=["ap1"])
        get_success_data(api.reject_task(task_ids[0], AP1))
        co = validate_success(api.get_change_order(eco["id"], CHANGE_ADMIN))
        assert co["status"] == "REJECTED", co


class TestBusinessValidations:
    def test_bom_cycle_rejected(self, api):
        """PRD 3.2: "An edge that would close a cycle is rejected with `ERR_BOM_CYCLE`."

        Design: Corner/validations/bom_cycle_rejected
        """
        pa = fixtures.create_part("MAKE", base_cost_cents=0)
        pb = fixtures.create_part("MAKE", base_cost_cents=0)
        ra = fixtures.create_revision(pa["id"])
        rb = fixtures.create_revision(pb["id"])
        # RA consumes PB
        fixtures.add_bom_line(ra["id"], pb["id"], 1)
        # RB consuming PA would close a cycle PA->PB->PA
        rb_now = get_success_data(api.get_revision(rb["id"], DESIGNER))
        resp = api.add_bom_line(
            rb["id"],
            factories.create_bom_line_payload(pa["id"], 1, rb_now["version"]),
            DESIGNER)
        validate_error(resp, ApiErrorId.ERR_BOM_CYCLE)

    def test_deviation_invalid_window_rejected(self, api):
        """PRD 3.10: "A `Designer` submits a draft deviation for quality review, but only
        when its `effective_to` is at or after its `effective_from`; an inverted window
        is rejected with `ERR_INVALID_WINDOW`, and the submission moves it `DRAFT →
        SUBMITTED`."

        Design: Corner/validations/deviation_invalid_window_rejected
        """
        part = fixtures.create_part("PHANTOM")
        dev = get_success_data(api.create_deviation(
            factories.create_deviation_payload(
                part["id"], "2026-06-01T00:00:00Z", "2026-05-01T00:00:00Z",
                defect_code="MATERIAL", max_units=1), DESIGNER))
        resp = api.submit_deviation(dev["id"], DESIGNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

    def test_disjoint_windows_both_grant(self, api):
        """PRD 3.10: "A grant is blocked if any other granted deviation for the same
        `part_id` and the same `defect_code` has a window that overlaps this one,
        treating both endpoints of the `effective_from`-to-`effective_to` window as
        inclusive; an overlap is rejected with `ERR_DEVIATION_WINDOW_OVERLAP`."

        Design: Corner/validations/deviation_disjoint_window_grants_ok
        """
        part = fixtures.create_part("PHANTOM")
        fixtures.create_granted_deviation(
            part["id"], "2026-01-01T00:00:00Z", "2026-03-31T00:00:00Z",
            defect_code="COSMETIC", max_units=2)
        dev2 = fixtures.create_submitted_deviation(
            part["id"], "2026-04-01T00:00:00Z", "2026-06-30T00:00:00Z",
            defect_code="COSMETIC", max_units=2)
        granted = validate_success(api.grant_deviation(dev2["id"], QUALITY))
        assert granted["status"] == "GRANTED", granted


class TestRbacIsolation:
    def test_designer_cannot_grant_deviation(self, api):
        """PRD 2.1: "A `QualityEngineer` grants, denies, and expires deviations and
        manages the build, ship, and conformance state of serialized units."
        PRD 2.1: "When the headers are present but the declared role is not permitted to
        perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/designer_cannot_grant_deviation
        """
        part = fixtures.create_part("PHANTOM")
        dev = fixtures.create_submitted_deviation(
            part["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
            defect_code="COSMETIC", max_units=1)
        resp = api.grant_deviation(dev["id"], DESIGNER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_approver_not_assignee_denied(self, api):
        """PRD 3.6: "the acting `X-User-ID` must equal the task's `assignee_user_id`
        (otherwise `ERR_NOT_TASK_ASSIGNEE`)".

        Design: Corner/rbac/approver_not_assignee_denied
        """
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part, rev = fixtures.create_make_revision_with_bom(leaf["id"], base_cost_cents=0)
        get_success_data(api.submit_revision_review(rev["id"], DESIGNER))
        _eco, task_ids = fixtures.create_in_approval_eco(
            part["id"], rev["id"], effectivity_date="2026-02-01T00:00:00Z",
            required_approvals=1, assignees=["ap1"])
        # ap2 (not the assignee) acts on ap1's task.
        resp = api.approve_task(task_ids[0], make_approver_headers("ap2"))
        validate_error(resp, ApiErrorId.ERR_NOT_TASK_ASSIGNEE)
