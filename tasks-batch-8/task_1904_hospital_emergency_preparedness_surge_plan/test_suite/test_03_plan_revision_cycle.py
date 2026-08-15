"""Plan update cycle: draft state, review loop, approval guards, supersession,
and segregation of duties."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_plan,
    assert_plan_revision,
    create_approved_plan,
    create_manager_admin_pair,
    create_plan_draft,
    create_plan_revision_payload,
    make_hospital_administrator_headers,
    submit_plan_for_review,
    validate_error,
    validate_paginated,
    validate_success,
)

EM = TEST_USERS["emergency_manager_headers"]
HA = TEST_USERS["hospital_administrator_headers"]


class TestPlanLifecycle:
    def test_plan_revision_initial_state_draft(self, api):
        """PRD §3.2: "The author is recorded in `created_by_id`, and the draft
        enters `DRAFT`."
        PRD §3.2: "On a successful approval the server stamps `approved_by_id`
        and `approved_at`, and the superseded predecessor — if any — automatically
        transitions `APPROVED` → `SUPERSEDED`, preserving the invariant that at
        most one plan revision is ever `APPROVED` at a time."

        Design: Corner/state_machines/plan_revision_initial_state_draft
        """
        plan = create_plan_draft(revision_label="EOP-init", change_summary="first")
        assert_plan_revision(plan)
        assert plan["status"] == "DRAFT"
        assert plan["approved_by_id"] is None, "approval stamp absent until approved"
        assert plan["approved_at"] is None

    def test_plan_approve_from_draft_rejected_invalid_state(self, api):
        """PRD §3.2: "Approval moves it `IN_REVIEW` → `APPROVED` subject to two
        guards, evaluated in the pipeline order of §2.11".
        PRD §2.11: "8. State-transition legality on the target resource — the
        generic guard that rejects any action whose target's current state does
        not permit it: `ERR_INVALID_STATE`."

        Design: Corner/state_machines/plan_approve_from_draft_rejected_invalid_state
        """
        plan = create_plan_draft(revision_label="EOP-draft")
        resp = api.approve_plan_revision(plan["id"], HA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        reread = validate_success(api.get_plan_revision(plan["id"], EM))
        assert reread["status"] == "DRAFT", "rejected approval leaves the draft DRAFT"

    def test_plan_approval_supersedes_predecessor(self, api):
        """PRD §3.2: "On a successful approval the server stamps `approved_by_id`
        and `approved_at`, and the superseded predecessor — if any — automatically
        transitions `APPROVED` → `SUPERSEDED`, preserving the invariant that at
        most one plan revision is ever `APPROVED` at a time."

        Design: Corner/state_machines/plan_approval_supersedes_predecessor
        """
        plan_a, ctx = create_approved_plan(revision_label="EOP-A")
        assert plan_a["status"] == "APPROVED"

        plan_b = create_plan_draft(
            creator_id=ctx["creator"]["id"],
            revision_label="EOP-B",
            supersedes_revision_id=plan_a["id"],
        )
        submit_plan_for_review(plan_b["id"], user_id=ctx["creator"]["id"])
        approved_b = approve_plan(plan_b["id"], ctx["approver"]["id"])
        assert approved_b["status"] == "APPROVED"

        reread_a = validate_success(api.get_plan_revision(plan_a["id"], EM))
        assert reread_a["status"] == "SUPERSEDED", (
            "the superseded predecessor flips APPROVED → SUPERSEDED"
        )


class TestApprovalGuards:
    def test_plan_supersede_non_approved_target_rejected(self, api):
        """PRD §3.2: "Two optional links give the revision context: `source_hva_id`
        points back to the hazard assessment cycle that motivated the rewrite, and
        `supersedes_revision_id` names the currently approved revision this draft
        intends to replace; when present, the supersede target must currently be
        `APPROVED`, otherwise the create is rejected with
        `ERR_SUPERSEDE_TARGET_NOT_APPROVED`."

        Design: Corner/validations/plan_supersede_non_approved_target_rejected
        """
        plan_a = create_plan_draft(revision_label="EOP-draft-A")
        resp = api.create_plan_revision(
            create_plan_revision_payload(
                revision_label="EOP-draft-B",
                supersedes_revision_id=plan_a["id"],
            ),
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_SUPERSEDE_TARGET_NOT_APPROVED)

    def test_plan_approve_with_other_approved_conflict(self, api):
        """PRD §3.2: "the single-approved-plan invariant — no other revision may
        currently be `APPROVED` except the one named by this draft's
        `supersedes_revision_id`, otherwise approval fails with
        `ERR_OTHER_PLAN_APPROVED`."

        Design: Corner/validations/plan_approve_with_other_approved_conflict
        """
        plan_a, ctx = create_approved_plan(revision_label="EOP-A")

        plan_c = create_plan_draft(creator_id=ctx["creator"]["id"],
                                   revision_label="EOP-C")
        submit_plan_for_review(plan_c["id"], user_id=ctx["creator"]["id"])
        resp = api.approve_plan_revision(
            plan_c["id"], make_hospital_administrator_headers(ctx["approver"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_OTHER_PLAN_APPROVED)
        reread = validate_success(api.get_plan_revision(plan_c["id"], EM))
        assert reread["status"] == "IN_REVIEW", "rejected approval leaves C IN_REVIEW"

    def test_plan_approve_by_creator_rejected_segregation(self, api):
        """PRD §2.7: "A plan revision records its author's identity in
        `created_by_id`; approval is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403) when the approver's `X-User-ID` equals that `created_by_id`."

        Design: Corner/rbac/plan_approve_by_creator_rejected_segregation
        """
        manager, admin = create_manager_admin_pair()
        plan = create_plan_draft(creator_id=manager["id"], revision_label="EOP-sod")
        submit_plan_for_review(plan["id"], user_id=manager["id"])

        resp = api.approve_plan_revision(
            plan["id"], make_hospital_administrator_headers(manager["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        approved = approve_plan(plan["id"], admin["id"])
        assert approved["status"] == "APPROVED", "an independent approver succeeds"
        assert approved["approved_by_id"] == admin["id"]


class TestSupersedesLink:
    def test_plan_revision_self_referential_supersedes_link_queryable(self, api):
        """PRD §3.2: "Two optional links give the revision context: `source_hva_id`
        points back to the hazard assessment cycle that motivated the rewrite, and
        `supersedes_revision_id` names the currently approved revision this draft
        intends to replace".
        PRD §3.2: "The revisions list supports optional `supersedes_revision_id`,
        `source_hva_id`, and `status` filters."

        Design: Corner/entities/plan_revision_self_referential_supersedes_link_queryable
        """
        plan_a, ctx = create_approved_plan(revision_label="EOP-A")
        plan_b = create_plan_draft(
            creator_id=ctx["creator"]["id"],
            revision_label="EOP-B",
            supersedes_revision_id=plan_a["id"],
        )
        assert plan_b["supersedes_revision_id"] == plan_a["id"]

        rows, meta = validate_paginated(
            api.list_plan_revisions(EM, params={"supersedes_revision_id": plan_a["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == plan_b["id"], (
            "the successor is found via the supersedes_revision_id filter"
        )
