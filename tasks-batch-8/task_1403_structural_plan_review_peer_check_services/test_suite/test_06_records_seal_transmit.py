"""Approval cascade, review record lifecycle (create/refresh, seal gates,
transmit), revision loops, cancellation cascade, validation-layer priority
pairs, deferred submittals, and amendment lockdown (PRD §3.6-§3.8, §2.4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_cycle,
    assign_cycle,
    get_assignment,
    get_comment,
    get_cycle,
    get_deferred,
    get_engagement,
    get_record_for_engagement,
    get_reviewer,
    issue_comments,
    make_applicant_headers,
    make_chief,
    make_chief_reviewer_headers,
    make_engagement,
    make_jurisdiction,
    make_reviewer,
    make_reviewer_headers,
    open_cycle,
    raise_comment,
    register_deferred,
    respond_to_comment,
    set_clock,
    setup_approved_engagement,
    setup_in_review_cycle,
    setup_registered_engagement,
    setup_sealed_record,
    submit_deferred,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestApproveCascade:
    def test_approve_cascade_reaches_engagement(self, api):
        """PRD §3.7: "On success the cycle moves `IN_REVIEW → APPROVED`;
        `completed_at` is stamped and `is_on_time` computed per §3.3; both
        attestation booleans are stored on the cycle; the cycle's `ACTIVE`
        assignments move to `COMPLETED` with `ended_at` stamped and reviewer
        counts decremented; and the engagement cascades `IN_PROGRESS →
        APPROVED`."

        Design: Difficulty/transitive_cascade/approve_cascade_cycle_to_engagement_to_record
        """
        bundle = setup_in_review_cycle(
            jur_overrides={"state_code": "OR", "sla_mode": "CALENDAR"})
        rev, cyc, asg = bundle["reviewer"], bundle["cycle"], bundle["assignment"]
        approved = approve_cycle(cyc["id"], rev["id"])
        assert approved["status"] == "APPROVED"                       # link 1
        assert approved["load_path_confirmed"] is True
        assert approved["lateral_system_confirmed"] is True
        assert approved["completed_at"] is not None
        assert get_engagement(bundle["engagement"]["id"])["status"] == "APPROVED"  # link 2
        assert get_assignment(asg["id"])["status"] == "COMPLETED"
        assert get_reviewer(rev["id"])["active_assignment_count"] == 0

    def test_approve_cascade_creates_draft_record(self, api):
        """PRD §3.7: "If no record exists yet for the engagement, one is
        created in `DRAFT` carrying snapshots of the engagement's
        `pinned_ibc_edition` and `pinned_asce7_edition` and a
        `cycle_count_snapshot` equal to the engagement's `cycle_count` at that
        moment."

        Design: Difficulty/transitive_cascade/approve_cascade_cycle_to_engagement_to_record
        """
        bundle = setup_in_review_cycle(
            jur_overrides={"state_code": "OR", "sla_mode": "CALENDAR"})
        approve_cycle(bundle["cycle"]["id"], bundle["reviewer"]["id"])
        rec = get_record_for_engagement(bundle["engagement"]["id"])
        assert rec["status"] == "DRAFT"                               # link 3
        assert rec["pinned_ibc_edition"] == "IBC_2021"
        assert rec["cycle_count_snapshot"] == 1
        assert rec["sealed_by_reviewer_id"] is None
        assert rec["sealed_at"] is None


class TestCancelCascade:
    def _setup(self, api):
        return setup_in_review_cycle(
            jur_overrides={"state_code": "CO", "sla_mode": "BUSINESS",
                           "ibc_edition": "IBC_2018",
                           "asce7_edition": "ASCE7_16"})

    def test_cancel_cascade_reaches_cycle(self, api):
        """PRD §3.8: "Cancellation cascades downward to keep the hierarchy
        consistent: every non-terminal cycle of the engagement — `OPEN`,
        `IN_REVIEW`, or `COMMENTS_ISSUED` — moves to `CANCELLED`, and every
        `ACTIVE` assignment on those cycles moves to `RELEASED`, with
        `ended_at` stamped and the affected reviewers'
        `active_assignment_count` decremented, freeing their capacity."

        Design: Difficulty/transitive_cascade/cancel_cascade_engagement_to_cycle_to_assignment
        """
        bundle = self._setup(api)
        resp = api.cancel_engagement(bundle["engagement"]["id"], COORD)
        eng = validate_success(resp, 200)
        assert eng["status"] == "CANCELLED"                           # link 1
        assert get_cycle(bundle["cycle"]["id"])["status"] == "CANCELLED"  # link 2

    def test_cancel_cascade_releases_assignment_and_restores_capacity(self, api):
        """PRD §3.8: "Cancellation cascades downward to keep the hierarchy
        consistent: every non-terminal cycle of the engagement — `OPEN`,
        `IN_REVIEW`, or `COMMENTS_ISSUED` — moves to `CANCELLED`, and every
        `ACTIVE` assignment on those cycles moves to `RELEASED`, with
        `ended_at` stamped and the affected reviewers'
        `active_assignment_count` decremented, freeing their capacity."

        Design: Difficulty/transitive_cascade/cancel_cascade_engagement_to_cycle_to_assignment
        """
        bundle = self._setup(api)
        assert get_reviewer(bundle["reviewer"]["id"])["active_assignment_count"] == 1
        api.cancel_engagement(bundle["engagement"]["id"], COORD)
        asg = get_assignment(bundle["assignment"]["id"])
        assert asg["status"] == "RELEASED"                            # link 3
        assert asg["ended_at"] is not None
        assert get_reviewer(bundle["reviewer"]["id"])["active_assignment_count"] == 0


class TestRevisionLoop:
    def _setup_first_approval(self, api):
        return setup_approved_engagement(
            jur_overrides={"state_code": "UT", "sla_mode": "CALENDAR"})

    def test_revision_cycle_reopens_approved_engagement(self, api):
        """PRD §3.3: "The engagement must be `REGISTERED`, `IN_PROGRESS`, or
        `APPROVED`; from any other status the request fails with
        `ERR_ENGAGEMENT_NOT_ACTIVE`, and from `APPROVED` there is a further
        gate — the engagement's review record must still be `DRAFT`, because
        revision is impossible once the record is `SEALED` or `TRANSMITTED`
        (`ERR_RECORD_ALREADY_SEALED`)."
        PRD §3.3: "opening a revision cycle on an `APPROVED` engagement walks
        it `APPROVED → IN_PROGRESS`."

        Design: Difficulty/non_linear_state_machine/engagement_revision_loop_in_progress_approved_in_progress
        """
        bundle = self._setup_first_approval(api)
        eng, rev = bundle["engagement"], bundle["reviewer"]
        # Applicant may open the resubmittal cycle (shared permission).
        resp = api.create_cycle(
            {"engagement_id": eng["id"], "documents_ref": "s3://rev-v2"},
            make_applicant_headers("app-1"))
        cyc2 = validate_success(resp, 201)
        assert cyc2["cycle_number"] == 2
        assert get_engagement(eng["id"])["status"] == "IN_PROGRESS"
        # Prior approval is terminal — not superseded.
        assert get_cycle(bundle["cycle"]["id"])["status"] == "APPROVED"
        assign_cycle(cyc2, rev["id"])
        approve_cycle(cyc2["id"], rev["id"])
        assert get_engagement(eng["id"])["status"] == "APPROVED"

    def test_reapproval_refreshes_record_snapshot(self, api):
        """PRD §3.7: "If a `DRAFT` record already exists — this is a
        re-approval after a revision cycle — its pinned edition snapshots and
        `cycle_count_snapshot` are refreshed to the current values instead."

        Design: Difficulty/non_linear_state_machine/engagement_revision_loop_in_progress_approved_in_progress
        """
        bundle = self._setup_first_approval(api)
        eng, rev = bundle["engagement"], bundle["reviewer"]
        assert bundle["record"]["cycle_count_snapshot"] == 1
        cyc2 = open_cycle(eng["id"], documents_ref="s3://rev-v2",
                          as_applicant=True)
        assign_cycle(cyc2, rev["id"])
        approve_cycle(cyc2["id"], rev["id"])
        rec = get_record_for_engagement(eng["id"])
        assert rec["status"] == "DRAFT"
        assert rec["cycle_count_snapshot"] == 2

    def test_revision_cycle_blocked_after_record_sealed(self, api):
        """PRD §3.3: "from `APPROVED` there is a further gate — the
        engagement's review record must still be `DRAFT`, because revision is
        impossible once the record is `SEALED` or `TRANSMITTED`
        (`ERR_RECORD_ALREADY_SEALED`)."

        Design: Corner/validations/revision_cycle_blocked_after_record_sealed
        """
        bundle = setup_sealed_record()
        eng = bundle["engagement"]
        resp = api.create_cycle(
            {"engagement_id": eng["id"], "documents_ref": "s3://sr-v2"}, COORD)
        validate_error(resp, ApiErrorId.ERR_RECORD_ALREADY_SEALED, 409)
        eng_after = get_engagement(eng["id"])
        assert eng_after["status"] == "APPROVED"
        assert eng_after["cycle_count"] == 1


class TestApprovalValidationPriority:
    def _setup_issued_with_open_comment(self, api):
        bundle = setup_in_review_cycle(
            jur_overrides={"state_code": "TX", "sla_mode": "CALENDAR"})
        rev = bundle["reviewer"]
        raise_comment(bundle["cycle"]["id"], rev["id"],
                      code_section_ref="2308.6.1", severity="MINOR",
                      category="DETAILING",
                      comment_text="Anchor bolt spacing missing")
        issue_comments(bundle["cycle"]["id"], rev["id"])
        return bundle

    def test_state_error_beats_unresolved_comments_error(self, api):
        """PRD §2.4: "Every request passes through a fixed sequence of
        validation layers, and the order is part of the contract: a failure at
        an earlier layer masks every later check, so the caller always sees the
        error from the highest-priority failing layer."
        PRD §2.4 layer 7: "the target entity must be in a state from which the
        requested transition is defined".
        PRD §3.7: "Approval also requires the engagement's
        `unresolved_comment_count` to be exactly zero
        (`ERR_UNRESOLVED_COMMENTS_REMAIN` while any comment remains `OPEN`,
        `ADDRESSED`, or `REOPENED`)."

        Design: Difficulty/priority_pair_validation_conflict/approve_state_error_beats_unresolved_comments_error
        """
        bundle = self._setup_issued_with_open_comment(api)
        # COMMENTS_ISSUED cycle with an OPEN comment violates both the layer-7
        # state gate and the layer-9 unresolved-comments gate; layer 7 wins.
        resp = api.approve_cycle(
            bundle["cycle"]["id"],
            {"load_path_confirmed": True, "lateral_system_confirmed": True},
            make_reviewer_headers(bundle["reviewer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_IN_REVIEW, 409)

    def test_failed_approval_leaves_cycle_unchanged(self, api):
        """PRD §2.4: "Every request passes through a fixed sequence of
        validation layers, and the order is part of the contract: a failure at
        an earlier layer masks every later check, so the caller always sees the
        error from the highest-priority failing layer."

        Design: Difficulty/priority_pair_validation_conflict/approve_state_error_beats_unresolved_comments_error
        """
        bundle = self._setup_issued_with_open_comment(api)
        api.approve_cycle(
            bundle["cycle"]["id"],
            {"load_path_confirmed": True, "lateral_system_confirmed": True},
            make_reviewer_headers(bundle["reviewer"]["id"]))
        assert get_cycle(bundle["cycle"]["id"])["status"] == "COMMENTS_ISSUED"


class TestSealValidationPriority:
    def _setup(self, api):
        """Approved engagement; reviewer's license expires 2026-09-30 (valid
        through the CALENDAR due date 2026-08-16 from the default clock);
        one deferred item left REGISTERED; clock then advanced past expiry."""
        jur = make_jurisdiction(state_code="FL", sla_mode="CALENDAR",
                                turnaround_days=15)
        rev = make_reviewer(name="R Ten", state_code="FL",
                            expires_on="2026-09-30")
        eng = make_engagement(jur, rev, project_name="Priority Two")
        cyc = open_cycle(eng["id"], documents_ref="s3://fl-v1")
        assign_cycle(cyc, rev["id"])
        approve_cycle(cyc["id"], rev["id"])
        register_deferred(eng["id"], item_type="TRUSS",
                          description="Truss package")
        rec = get_record_for_engagement(eng["id"])
        set_clock("2026-10-15T00:00:00Z")
        return eng, rev, rec

    def test_license_error_beats_deferred_outstanding_error(self, api):
        """PRD §2.4: "Every request passes through a fixed sequence of
        validation layers, and the order is part of the contract: a failure at
        an earlier layer masks every later check, so the caller always sees the
        error from the highest-priority failing layer."
        PRD §3.7: "The sealer must hold a license whose `state_code` equals the
        engagement's `pinned_state_code` (`ERR_LICENSE_STATE_MISMATCH`), that
        license's `expires_on` must be on or after the current logical date
        (`ERR_LICENSE_WINDOW_INSUFFICIENT`)."
        PRD §3.7: "Finally — the referential-completeness layer — the
        engagement's `deferred_pending_count` must be exactly zero: every
        deferred item approved, none outstanding
        (`ERR_DEFERRED_SUBMITTALS_OUTSTANDING`)."

        Design: Difficulty/priority_pair_validation_conflict/seal_license_error_beats_deferred_outstanding_error
        """
        eng, rev, rec = self._setup(api)
        resp = api.seal_record(rec["id"], make_reviewer_headers(rev["id"]))
        validate_error(resp, ApiErrorId.ERR_LICENSE_WINDOW_INSUFFICIENT, 422)

    def test_failed_seal_leaves_record_draft_and_fee_null(self, api):
        """PRD §3.2: "The new engagement is born `REGISTERED` with
        `cycle_count`, `unresolved_comment_count`, and `deferred_pending_count`
        all at 0, the pinned snapshot of §2.6 copied from its jurisdiction, and
        `final_fee_cents` null — it stays null until the record is sealed."

        Design: Difficulty/priority_pair_validation_conflict/seal_license_error_beats_deferred_outstanding_error
        """
        eng, rev, rec = self._setup(api)
        api.seal_record(rec["id"], make_reviewer_headers(rev["id"]))
        rec_after = validate_success(api.get_record(rec["id"], COORD), 200)
        assert rec_after["status"] == "DRAFT"
        assert get_engagement(eng["id"])["final_fee_cents"] is None


class TestSealGatedByDeferred:
    def _setup(self, api):
        bundle = setup_approved_engagement(
            jur_overrides={"state_code": "MN", "sla_mode": "CALENDAR"})
        def1 = register_deferred(bundle["engagement"]["id"],
                                 item_type="ANCHOR",
                                 description="Post-installed anchor design")
        bundle["deferred"] = def1
        return bundle

    def test_registered_deferred_item_blocks_seal(self, api):
        """PRD §3.7: "Finally — the referential-completeness layer — the
        engagement's `deferred_pending_count` must be exactly zero: every
        deferred item approved, none outstanding
        (`ERR_DEFERRED_SUBMITTALS_OUTSTANDING`)."

        Design: Difficulty/cross_entity_state_dependency/record_seal_gated_by_deferred_submittal_states
        """
        bundle = self._setup(api)
        rev = bundle["reviewer"]
        resp = api.seal_record(bundle["record"]["id"],
                               make_reviewer_headers(rev["id"]))
        validate_error(resp, ApiErrorId.ERR_DEFERRED_SUBMITTALS_OUTSTANDING, 409)
        rec = validate_success(api.get_record(bundle["record"]["id"], COORD), 200)
        assert rec["status"] == "DRAFT"

    def test_seal_succeeds_after_deferred_item_approved(self, api):
        """PRD §3.6: "Approving moves a `SUBMITTED` item to `APPROVED` and
        decrements `deferred_pending_count` by 1."
        PRD §3.7: "On success the record moves `DRAFT → SEALED`,
        `sealed_by_reviewer_id` is set from the caller, `sealed_at` is stamped,
        and the engagement's `version` increments by 1."

        Design: Difficulty/cross_entity_state_dependency/record_seal_gated_by_deferred_submittal_states
        """
        bundle = self._setup(api)
        rev = bundle["reviewer"]
        def1 = bundle["deferred"]
        submit_deferred(def1["id"], documents_ref="s3://anchor-calcs")
        validate_success(
            api.approve_deferred(def1["id"], make_reviewer_headers(rev["id"])), 200)
        assert get_engagement(bundle["engagement"]["id"])["deferred_pending_count"] == 0
        resp = api.seal_record(bundle["record"]["id"],
                               make_reviewer_headers(rev["id"]))
        sealed = validate_success(resp, 200)
        assert sealed["status"] == "SEALED"
        assert sealed["sealed_by_reviewer_id"] == rev["id"]
        assert sealed["sealed_at"] is not None


class TestSealGuards:
    def test_seal_by_non_responsible_charge_rejected(self, api):
        """PRD §3.7: "The caller must be the engagement's
        `reviewer_of_record_id` (`ERR_NOT_RESPONSIBLE_CHARGE`)."

        Design: Corner/validations/seal_by_non_responsible_charge_rejected
        """
        bundle = setup_approved_engagement()
        other = make_reviewer(name="Other Reviewer", state_code="CA",
                              license_type="SE")
        resp = api.seal_record(bundle["record"]["id"],
                               make_reviewer_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESPONSIBLE_CHARGE, 403)
        rec = validate_success(api.get_record(bundle["record"]["id"], COORD), 200)
        assert rec["status"] == "DRAFT"

    def test_seal_with_pe_license_when_se_required_rejected(self, api):
        """PRD §3.7: "where the engagement's `pinned_requires_se_seal` is true
        the license's `license_type` must be `SE` rather than `PE`
        (`ERR_SE_SEAL_REQUIRED`)."

        Design: Corner/validations/seal_with_pe_license_when_se_required_rejected
        """
        bundle = setup_approved_engagement(
            jur_overrides={"requires_se_seal": True})
        resp = api.seal_record(
            bundle["record"]["id"],
            make_reviewer_headers(bundle["reviewer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SE_SEAL_REQUIRED, 422)
        rec = validate_success(api.get_record(bundle["record"]["id"], COORD), 200)
        assert rec["status"] == "DRAFT"

    def test_seal_while_engagement_reopened_rejected(self, api):
        """PRD §3.7: "The engagement must currently be `APPROVED` — an
        engagement reopened to `IN_PROGRESS` by a revision cycle cannot have
        its record sealed (`ERR_ENGAGEMENT_NOT_APPROVED`)."

        Design: Corner/validations/seal_while_engagement_reopened_rejected
        """
        bundle = setup_approved_engagement()
        eng, rev = bundle["engagement"], bundle["reviewer"]
        open_cycle(eng["id"], documents_ref="s3://swr-v2")
        assert get_engagement(eng["id"])["status"] == "IN_PROGRESS"
        resp = api.seal_record(bundle["record"]["id"],
                               make_reviewer_headers(rev["id"]))
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_APPROVED, 409)
        rec = validate_success(api.get_record(bundle["record"]["id"], COORD), 200)
        assert rec["status"] == "DRAFT"

    def test_coordinator_cannot_seal_record(self, api):
        """PRD §2.1: "If the role is valid but not among the roles authorized
        for the targeted endpoint, the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /plan-review/records/{id}/seal is authorized for Reviewer
        only.

        Design: Corner/rbac/coordinator_cannot_seal_record
        """
        bundle = setup_approved_engagement()
        resp = api.seal_record(bundle["record"]["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
        rec = validate_success(api.get_record(bundle["record"]["id"], COORD), 200)
        assert rec["status"] == "DRAFT"


class TestTransmit:
    def test_record_transmit_completes_engagement_and_locks(self, api):
        """PRD §3.7: "A `ReviewCoordinator` closes the loop by transmitting the
        sealed record to the building department. The record must be `SEALED`
        (`ERR_RECORD_INVALID_STATE` otherwise); on success it moves `SEALED →
        TRANSMITTED`, `transmitted_at` is stamped, and the engagement cascades
        `APPROVED → COMPLETED`, its terminal resting state."

        Design: Corner/state_machines/record_transmit_completes_engagement_and_locks
        """
        bundle = setup_sealed_record()
        rec = bundle["record"]
        resp = api.transmit_record(rec["id"], COORD)
        transmitted = validate_success(resp, 200)
        assert transmitted["status"] == "TRANSMITTED"
        assert transmitted["transmitted_at"] is not None
        assert get_engagement(bundle["engagement"]["id"])["status"] == "COMPLETED"
        resp2 = api.transmit_record(rec["id"], COORD)
        validate_error(resp2, ApiErrorId.ERR_RECORD_INVALID_STATE, 409)


class TestDeferredSubmittals:
    def test_deferred_registration_not_permitted_rejected(self, api):
        """PRD §3.6: "Registration is applicant-scoped
        (`ERR_NOT_ENGAGEMENT_APPLICANT`), requires the engagement to be
        `IN_PROGRESS` or `APPROVED` (`ERR_ENGAGEMENT_NOT_ACTIVE`), and requires
        the engagement's `pinned_allows_deferred_submittals` to be true
        (`ERR_DEFERRED_NOT_PERMITTED`)."

        Design: Corner/validations/deferred_registration_not_permitted_rejected
        """
        bundle = setup_registered_engagement(
            jur_overrides={"allows_deferred_submittals": False})
        open_cycle(bundle["engagement"]["id"], documents_ref="s3://nd-v1")
        resp = api.create_deferred(
            {"engagement_id": bundle["engagement"]["id"], "item_type": "TRUSS",
             "description": "trusses"},
            make_applicant_headers("app-1"))
        validate_error(resp, ApiErrorId.ERR_DEFERRED_NOT_PERMITTED, 422)
        assert get_engagement(bundle["engagement"]["id"])["deferred_pending_count"] == 0

    def test_deferred_submittal_full_resubmit_cycle(self, api):
        """PRD §3.6: "The applicant then submits the deferred design documents
        by supplying the `documents_ref` URI, moving the item to `SUBMITTED` —
        from `REGISTERED` on first submission, or from `REJECTED` on
        resubmission, in which case the stored `rejection_reason` is cleared
        back to null; the pending count is unchanged either way, since
        `SUBMITTED` is still pending."
        PRD §3.6: "Approving moves a `SUBMITTED` item to `APPROVED` and
        decrements `deferred_pending_count` by 1; rejecting moves it to
        `REJECTED`, stores the supplied `rejection_reason` (its absence is an
        `ERR_INVALID_REQUEST`), and leaves the count unchanged, since
        `REJECTED` remains pending while awaiting resubmittal."

        Design: Corner/state_machines/deferred_submittal_full_resubmit_cycle
        """
        bundle = setup_in_review_cycle(
            jur_overrides={"allows_deferred_submittals": True})
        eng, rev = bundle["engagement"], bundle["reviewer"]
        rh = make_reviewer_headers(rev["id"])
        def1 = register_deferred(eng["id"], item_type="TRUSS",
                                 description="Floor truss package")
        assert get_engagement(eng["id"])["deferred_pending_count"] == 1
        submitted = submit_deferred(def1["id"], documents_ref="s3://truss-v1")
        assert submitted["status"] == "SUBMITTED"
        rejected = validate_success(api.reject_deferred(
            def1["id"],
            {"rejection_reason": "Truss calcs missing connector design"}, rh), 200)
        assert rejected["status"] == "REJECTED"
        assert get_engagement(eng["id"])["deferred_pending_count"] == 1
        resubmitted = submit_deferred(def1["id"], documents_ref="s3://truss-v2")
        assert resubmitted["status"] == "SUBMITTED"
        approved = validate_success(api.approve_deferred(def1["id"], rh), 200)
        assert approved["status"] == "APPROVED"
        final = get_deferred(def1["id"])
        assert final["documents_ref"] == "s3://truss-v2"
        assert final["rejection_reason"] is None
        assert get_engagement(eng["id"])["deferred_pending_count"] == 0


class TestAmendmentAndCancellationLockdown:
    def test_amend_after_approval_rejected(self, api):
        """PRD §3.2: "Once the engagement reaches `APPROVED`, `COMPLETED`, or
        `CANCELLED`, amendment is rejected with
        `ERR_ENGAGEMENT_NOT_AMENDABLE`."

        Design: Corner/validations/amend_after_approval_rejected
        """
        bundle = setup_approved_engagement()
        eng = bundle["engagement"]
        resp = api.update_engagement(
            eng["id"], {"declared_valuation_cents": 60_000_000}, COORD)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_AMENDABLE, 409)
        assert get_engagement(eng["id"])["declared_valuation_cents"] == 30_000_000

    def test_cancelled_engagement_is_terminal_lockdown(self, api):
        """PRD §3.8: "A `ReviewCoordinator` may cancel an engagement while it
        is `REGISTERED` or `IN_PROGRESS`; from `APPROVED`, `COMPLETED`, or
        `CANCELLED` the attempt is rejected with `ERR_ENGAGEMENT_NOT_ACTIVE`."
        PRD §3.3: "The engagement must be `REGISTERED`, `IN_PROGRESS`, or
        `APPROVED`; from any other status the request fails with
        `ERR_ENGAGEMENT_NOT_ACTIVE`."
        PRD §3.2: "Once the engagement reaches `APPROVED`, `COMPLETED`, or
        `CANCELLED`, amendment is rejected with
        `ERR_ENGAGEMENT_NOT_AMENDABLE`."

        Design: Corner/state_machines/cancelled_engagement_is_terminal_lockdown
        """
        bundle = setup_registered_engagement()
        eng = bundle["engagement"]
        validate_success(api.cancel_engagement(eng["id"], COORD), 200)
        resp1 = api.create_cycle(
            {"engagement_id": eng["id"], "documents_ref": "s3://term-v1"}, COORD)
        validate_error(resp1, ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE, 409)
        resp2 = api.update_engagement(
            eng["id"], {"declared_valuation_cents": 40_000_000}, COORD)
        validate_error(resp2, ApiErrorId.ERR_ENGAGEMENT_NOT_AMENDABLE, 409)
        assert get_engagement(eng["id"])["status"] == "CANCELLED"

    def test_approve_without_verification_booleans_rejected(self, api):
        """PRD §3.7: "The assigned reviewer approves a cycle with an
        attestation payload: `load_path_confirmed` and
        `lateral_system_confirmed` must both be true — anything less is
        rejected with `ERR_VERIFICATION_INCOMPLETE`."

        Design: Corner/validations/approve_without_verification_booleans_rejected
        """
        bundle = setup_in_review_cycle()
        rev = bundle["reviewer"]
        resp = api.approve_cycle(
            bundle["cycle"]["id"],
            {"load_path_confirmed": False, "lateral_system_confirmed": True},
            make_reviewer_headers(rev["id"]))
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_INCOMPLETE, 422)
        assert get_cycle(bundle["cycle"]["id"])["status"] == "IN_REVIEW"
        assert get_engagement(bundle["engagement"]["id"])["status"] == "IN_PROGRESS"


class TestReverseReachability:
    def test_fk_reverse_reachability_filtered_lists(self, api):
        """PRD §3.3: "The cycles listing accepts optional `engagement_id` and
        `status` filters."
        PRD §3.4: "The assignments listing accepts optional `cycle_id`,
        `reviewer_id`, and `status` filters."
        PRD §3.5: "The comments listing accepts optional `engagement_id`,
        `raised_in_cycle_id`, `raised_by_reviewer_id`, and `status` filters."
        PRD §3.5: "Responses to a comment can be listed in chronological order
        with `limit` and `offset`."
        PRD §3.7: "Exactly one record ever exists per engagement; the records
        listing accepts optional `engagement_id`, `sealed_by_reviewer_id`, and
        `status` filters."

        Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
        """
        bundle = setup_in_review_cycle()
        eng, rev = bundle["engagement"], bundle["reviewer"]
        cyc1 = bundle["cycle"]
        com = raise_comment(cyc1["id"], rev["id"], code_section_ref="1604.3",
                            comment_text="drift check missing")
        issue_comments(cyc1["id"], rev["id"])
        respond_to_comment(com["id"], response_text="drift check added")
        cyc2 = open_cycle(eng["id"], documents_ref="s3://fk-v2")
        asg2 = assign_cycle(cyc2, rev["id"])
        validate_success(
            api.verify_comment(com["id"], make_reviewer_headers(rev["id"])), 200)
        approve_cycle(cyc2["id"], rev["id"])

        cycles, cyc_meta = validate_paginated(
            api.list_cycles(COORD, params={"engagement_id": eng["id"]}))
        assert cyc_meta["total_count"] == 2
        asgs, _ = validate_paginated(
            api.list_assignments(COORD, params={"cycle_id": cyc2["id"]}))
        assert [a["id"] for a in asgs] == [asg2["id"]]
        coms, com_meta = validate_paginated(
            api.list_comments(COORD, params={"raised_in_cycle_id": cyc1["id"]}))
        assert com_meta["total_count"] == 1
        assert coms[0]["id"] == com["id"]
        recs, rec_meta = validate_paginated(
            api.list_records(COORD, params={"engagement_id": eng["id"]}))
        assert rec_meta["total_count"] == 1
        assert recs[0]["status"] == "DRAFT"
        responses, resp_meta = validate_paginated(
            api.list_responses(com["id"], COORD))
        assert resp_meta["total_count"] == 1
        assert responses[0]["comment_id"] == com["id"]


class TestImmediateConsistency:
    def test_mutations_immediately_visible_in_reads(self, api):
        """PRD §3.5: "The new comment's `engagement_id` is copied from its
        cycle, `raised_by_reviewer_id` is set from the caller's `X-User-ID`,
        `response_count` starts at 0, and the comment is born `OPEN` — and the
        engagement's `unresolved_comment_count` increments by 1."

        Design: Corner/consistency_model/mutations_immediately_visible_in_reads
        """
        bundle = setup_in_review_cycle()
        eng, rev = bundle["engagement"], bundle["reviewer"]
        com = raise_comment(bundle["cycle"]["id"], rev["id"],
                            code_section_ref="1604.3",
                            comment_text="immediate check")
        # The write is visible in the computed count on the immediate next read.
        assert get_engagement(eng["id"])["unresolved_comment_count"] == 1
        assert com["raised_by_reviewer_id"] == rev["id"]
        assert com["status"] == "OPEN"


class TestJurisdictionUpdatePinning:
    def test_jurisdiction_update_does_not_repin_existing_engagements(self, api):
        """PRD §2.6: "These pinned fields never change afterwards, even when
        the jurisdiction itself is later updated; jurisdiction updates apply
        only to engagements created afterwards. Every downstream rule — fee
        computation, turnaround computation, comment edition checks, seal
        licensing, deferred-submittal permission — reads the pinned snapshot,
        never the live jurisdiction row."
        PRD §3.5: "Because the engagement is reviewed against its pinned
        editions, the `reference_edition` must equal the engagement's
        `pinned_ibc_edition`; a mismatch is rejected with
        `ERR_CODE_EDITION_MISMATCH`."

        Design: Corner/cross_cutting_complexity_layers/jurisdiction_update_does_not_repin_existing_engagements
        """
        jur = make_jurisdiction(state_code="CA", ibc_edition="IBC_2021")
        rev = make_reviewer(name="Pin Reviewer", state_code="CA")
        eng1 = make_engagement(jur, rev, project_name="Old Pin")
        validate_success(
            api.update_jurisdiction(jur["id"], {"ibc_edition": "IBC_2024"},
                                    ADMIN), 200)
        eng2 = make_engagement(jur, rev, project_name="New Pin")
        cyc1 = open_cycle(eng1["id"], documents_ref="s3://pin-old")
        assign_cycle(cyc1, rev["id"])
        cyc2 = open_cycle(eng2["id"], documents_ref="s3://pin-new")
        assign_cycle(cyc2, rev["id"])
        assert get_engagement(eng1["id"])["pinned_ibc_edition"] == "IBC_2021"
        assert get_engagement(eng2["id"])["pinned_ibc_edition"] == "IBC_2024"
        # The old engagement still accepts IBC_2021 citations.
        com_old = raise_comment(cyc1["id"], rev["id"],
                                reference_edition="IBC_2021",
                                comment_text="old edition citation on old engagement")
        assert com_old["status"] == "OPEN"
        # The new engagement demands IBC_2024 citations.
        resp = api.create_comment(
            {"raised_in_cycle_id": cyc2["id"], "code_section_ref": "1604.3",
             "reference_edition": "IBC_2021", "severity": "MINOR",
             "category": "CALCULATION",
             "comment_text": "old edition citation on new engagement"},
            make_reviewer_headers(rev["id"]))
        validate_error(resp, ApiErrorId.ERR_CODE_EDITION_MISMATCH, 422)
