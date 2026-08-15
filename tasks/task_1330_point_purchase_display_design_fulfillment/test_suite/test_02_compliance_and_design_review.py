"""Compliance rules, the design review cycle, and the revision loop."""
import pytest

from test_helpers import (
    COMPLIANCE_OFFICER,
    DESIGNER,
    PROGRAM_MANAGER,
    ApiErrorId,
    api_client,
    assert_design,
    begin_review,
    create_design_entity,
    get_design,
    reject_design,
    revise_design,
    setup_program_in_design,
    submit_design,
    validate_error,
    validate_success,
    walk_design_to_approved,
)


class TestComplianceResultComputation:

    def test_compliance_result_recomputed_fail_on_submit(self):
        """PRD §3.2: "Submission is the `Designer`'s act and is permitted only
        while the parent program is in `DESIGN` — submitting under a program in
        any other stage is rejected with `ERR_INVALID_STATE` — and it triggers a
        fresh recomputation of `compliance_result` against the active rules as
        the design enters `SUBMITTED`."
        PRD §3.2: "A design satisfies a `MAX_*` rule when the corresponding
        measurement does not exceed the rule's numeric limit, and satisfies an
        `ALLOWED_MATERIAL` rule when its `material` matches the rule's material
        token; `compliance_result` is `PASS` when every active rule is satisfied
        and `FAIL` otherwise."

        Design: Corner/entities/computed_field_compliance_result_recomputed_on_submit
        """
        _client, program = setup_program_in_design()
        design = create_design_entity(program["id"], width_in=60)
        submitted = submit_design(design["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["compliance_result"] == "FAIL", \
            f"width 60 exceeds active MAX_WIDTH_IN 48, got {submitted['compliance_result']}"

    def test_duplicate_design_code_rejected(self):
        """PRD §3.2: "Each of the three dimensions and the weight must be greater
        than zero, and `design_code` must be unique within its program: a
        colliding code is rejected with `ERR_DUPLICATE`, while non-positive
        measurements are rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/violation_duplicate_design_code
        """
        _client, program = setup_program_in_design()
        create_design_entity(program["id"], design_code="D1")
        resp = api_client.create_design(
            {
                "program_id": program["id"],
                "design_code": "D1",
                "width_in": 42,
                "height_in": 62,
                "depth_in": 26,
                "weight_lb": 32,
                "material": "ACRYLIC",
            },
            DESIGNER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)


class TestDesignReviewGate:

    def test_approve_rejected_when_compliance_failed(self):
        """PRD §3.2: "the design must be in `COMPLIANCE_REVIEW` (else
        `ERR_INVALID_STATE`), its `compliance_result` must be `PASS` (else
        `ERR_COMPLIANCE_FAILED`), and the request must carry
        `expected_design_version` matching the design's current `version` (else
        `ERR_STALE_VERSION`, per §2.7)."

        Design: Corner/errors/error_compliance_failed_on_approve
        """
        _client, program = setup_program_in_design()
        design = create_design_entity(program["id"], width_in=60)
        design = submit_design(design["id"])
        assert design["compliance_result"] == "FAIL"
        design = begin_review(design["id"])

        resp = api_client.approve_design(
            design["id"], {"expected_design_version": design["version"]},
            COMPLIANCE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_FAILED)

    def test_submit_from_approved_rejected(self):
        """PRD §3.2: "The review cycle runs `DRAFT` → `SUBMITTED` →
        `COMPLIANCE_REVIEW` → `APPROVED`, with a rejection loop back to the
        drawing board."
        PRD §2.9: "4. State — the target resource is in a state that permits the
        requested transition; otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/design_submit_from_approved_rejected
        """
        _client, program = setup_program_in_design()
        design = walk_design_to_approved(program["id"])
        assert design["status"] == "APPROVED"

        resp = api_client.submit_design(design["id"], DESIGNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_designer_cannot_approve_design(self):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_UNAUTHORIZED`."
        PRD §3.2: "A `ComplianceOfficer` then begins review, moving the design
        from `SUBMITTED` to `COMPLIANCE_REVIEW`, and from there either approves
        or rejects it."

        Design: Corner/rbac/designer_cannot_approve_own_design
        """
        _client, program = setup_program_in_design()
        design = create_design_entity(program["id"])
        design = submit_design(design["id"])
        design = begin_review(design["id"])

        resp = api_client.approve_design(
            design["id"], {"expected_design_version": design["version"]},
            DESIGNER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestValidationPriorityOnApprove:
    """State (priority 4) is evaluated before compliance gating (priority 5)."""

    def test_approve_draft_design_with_failing_compliance_returns_invalid_state(self):
        """PRD §2.9: "More generally, when several checks apply to a single
        request they are evaluated in a fixed priority order, and the first
        failing check determines the error returned:"
        PRD §2.9: "4. State — the target resource is in a state that permits the
        requested transition; otherwise `ERR_INVALID_STATE`."
        PRD §2.9: "5. Compliance gating — a design's `compliance_result` is
        `PASS` before approval, and a program has at least one active compliance
        rule before design work begins; otherwise `ERR_COMPLIANCE_FAILED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_design_approve
        """
        _client, program = setup_program_in_design()
        # DRAFT design whose width 60 violates the active MAX_WIDTH_IN=48 rule:
        # both the state check and the compliance gate would fail; state wins.
        design = create_design_entity(program["id"], width_in=60)

        resp = api_client.approve_design(
            design["id"], {"expected_design_version": design["version"]},
            COMPLIANCE_OFFICER)
        error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert error["error_id"] != "ERR_COMPLIANCE_FAILED"

    def test_approve_submitted_design_with_failing_compliance_returns_invalid_state(self):
        """PRD §2.9: "4. State — the target resource is in a state that permits
        the requested transition; otherwise `ERR_INVALID_STATE`."
        PRD §3.2: "the design must be in `COMPLIANCE_REVIEW` (else
        `ERR_INVALID_STATE`), its `compliance_result` must be `PASS` (else
        `ERR_COMPLIANCE_FAILED`)".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_design_approve
        """
        _client, program = setup_program_in_design()
        # SUBMITTED (not COMPLIANCE_REVIEW) and compliance_result == FAIL after
        # the submit-time recomputation; the state check still fires first.
        design = create_design_entity(program["id"], width_in=60)
        design = submit_design(design["id"])
        assert design["compliance_result"] == "FAIL"

        resp = api_client.approve_design(
            design["id"], {"expected_design_version": design["version"]},
            COMPLIANCE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDesignRevisionLoop:

    def test_revise_returns_rejected_design_to_draft_and_increments_revision(self):
        """PRD §3.2: "While the parent program remains in `DESIGN`, the
        `Designer` may send the design back from `REJECTED` to `DRAFT` through
        the revision loop, which increments `revision_number` by one — so a
        design's third pass through review carries `revision_number` 3 — and
        lets the cycle begin again."
        PRD §3.2: "A new design starts in `DRAFT` status with `revision_number`
        set to 1".

        Design: Difficulty/non_linear_state_machine/design_revision_loop_cycle
        """
        _client, program = setup_program_in_design()
        design = create_design_entity(program["id"])
        assert design["revision_number"] == 1
        design = submit_design(design["id"])
        design = begin_review(design["id"])
        rejected = validate_success(
            api_client.reject_design(design["id"], COMPLIANCE_OFFICER), 200)
        assert rejected["status"] == "REJECTED"

        revised = revise_design(design["id"])
        assert_design(revised)
        assert revised["status"] == "DRAFT", \
            f"revision loop must return the design to DRAFT, got {revised['status']}"
        assert revised["revision_number"] == 2, \
            f"revision_number must increment by one, got {revised['revision_number']}"

    def test_second_revision_loop_reaches_revision_number_3(self):
        """PRD §3.2: "While the parent program remains in `DESIGN`, the
        `Designer` may send the design back from `REJECTED` to `DRAFT` through
        the revision loop, which increments `revision_number` by one — so a
        design's third pass through review carries `revision_number` 3 — and
        lets the cycle begin again."

        Design: Difficulty/non_linear_state_machine/design_revision_loop_cycle
        """
        _client, program = setup_program_in_design()
        design = create_design_entity(program["id"])

        # First pass: reject + revise -> revision_number 2.
        design = submit_design(design["id"])
        design = begin_review(design["id"])
        reject_design(design["id"])
        design = revise_design(design["id"])
        assert design["revision_number"] == 2

        # Second pass through the whole cycle -> revision_number 3.
        design = submit_design(design["id"])
        design = begin_review(design["id"])
        reject_design(design["id"])
        design = revise_design(design["id"])
        assert design["status"] == "DRAFT"
        assert design["revision_number"] == 3, \
            f"third pass through review must carry revision_number 3, got {design['revision_number']}"
