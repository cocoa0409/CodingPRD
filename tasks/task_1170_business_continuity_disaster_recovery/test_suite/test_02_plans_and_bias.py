"""BIA revision cycles, plan approval gates, adoption cascades, OCC (PRD §3.2, §3.3, §2.8)."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    TEST_USERS,
    ApiErrorId,
    api_client,
    approve_plan,
    create_active_process,
    create_approved_bia,
    create_bia,
    create_contact,
    create_plan,
    create_plan_with_sections,
    decide_bia,
    make_plan_approver_headers,
    make_plan_author_headers,
    make_risk_committee_headers,
    setup_approved_program,
    submit_bia,
    submit_plan,
    validate_error,
    validate_success,
)

ANALYST_HEADERS = TEST_USERS["bia_analyst_headers"]


class TestBiaRevisionCycle:
    def _setup_rejected_resubmitted_bia(self):
        c1 = create_contact("Cm One", "Risk Committee")
        c2 = create_contact("Cm Two", "Risk Committee")
        process = create_active_process(c1["id"], name="Onboarding",
                                        criticality_tier="TIER_3")
        bia = create_bia(process["id"], rto_target_hours=8, rpo_target_hours=2,
                         impact_financial_per_hour=300)
        submit_bia(bia["id"])
        decide_bia(bia["id"], "REJECT", c1["id"])
        resubmitted = submit_bia(bia["id"])
        return c1, c2, process, bia, resubmitted

    def test_bia_rejected_resubmit_loop_rejects_same_decider(self, api):
        """PRD §3.2: "A `REJECTED` analysis may be revised and re-submitted along the same guarded transition — the source state may be `DRAFT` or `REJECTED`, and any other source fails with `ERR_INVALID_STATE`."
        PRD §2.11: "The contact deciding a business impact analysis must differ from the contact recorded in that analysis's `decided_by_contact_id` (which is empty until the first decision, so a first decision is never self-blocked)."

        The committee contact who rejected round one cannot decide round two.

        Design: Difficulty/non_linear_state_machine/bia_revision_cycle_decided_by_tracking
        """
        c1, _, _, bia, resubmitted = self._setup_rejected_resubmitted_bia()
        assert resubmitted["status"] == "SUBMITTED", (
            "the REJECTED -> SUBMITTED revision loop leg must succeed"
        )
        response = api_client.decide_bia(
            bia["id"], {"decision": "APPROVE"}, make_risk_committee_headers(c1["id"]))
        validate_error(response, ApiErrorId.ERR_SOD_VIOLATION)

    def test_bia_revision_cycle_approves_with_new_decider(self, api):
        """PRD §2.11: "The contact deciding a business impact analysis must differ from the contact recorded in that analysis's `decided_by_contact_id` (which is empty until the first decision, so a first decision is never self-blocked)."
        PRD §3.2: "An approval moves `SUBMITTED` → `APPROVED` and is the heaviest single operation in the analysis workflow. It records `decided_by_contact_id`, flips `score_variant` to `FINAL` with the score frozen, and increments the analysis's `version`."

        A different committee contact decides round two: APPROVED with FINAL score.

        Design: Difficulty/non_linear_state_machine/bia_revision_cycle_decided_by_tracking
        """
        _, c2, _, bia, resubmitted = self._setup_rejected_resubmitted_bia()
        decided = decide_bia(bia["id"], "APPROVE", c2["id"])
        assert decided["status"] == "APPROVED"
        assert decided["score_variant"] == "FINAL"
        assert decided["decided_by_contact_id"] == c2["id"]


class TestPlanRejectLoop:
    def _setup_rejected_plan(self):
        author = create_contact("Author Ann", "Plan Author")
        approver = create_contact("Approver Al", "Plan Approver")
        process = create_active_process(author["id"], name="Claims")
        create_approved_bia(process["id"], approver["id"],
                            rto_target_hours=8, rpo_target_hours=2)
        plan = create_plan_with_sections(
            process["id"], author["id"], title="Claims DR", version_no=1,
            strategy_type="COLD_SITE", rto_committed_hours=8, rpo_committed_hours=2)
        submit_plan(plan["id"], author["id"])
        rejected = validate_success(
            api_client.reject_plan(plan["id"], make_plan_approver_headers(approver["id"])))
        return author, approver, process, plan, rejected

    def test_plan_reject_returns_to_draft_and_allows_section_edits(self, api):
        """PRD §3.3: "The approver may instead return the plan to the author, moving `IN_REVIEW` → `DRAFT` with no further ceremony."
        PRD §3.3: "Sections may be created, edited (their `content` and `order_index`), or deleted only while the owning plan is in `DRAFT`; attempts against a plan in any other state are refused with `ERR_INVALID_STATE`, and a section edit increments that section's `version`."

        After rejection the plan is DRAFT and accepts a new SCOPE section.

        Design: Difficulty/non_linear_state_machine/plan_in_review_reject_loop_back_to_draft
        """
        author, _, _, plan, rejected = self._setup_rejected_plan()
        assert rejected["status"] == "DRAFT", "rejection must return the plan to DRAFT"

        author_headers = make_plan_author_headers(author["id"])
        added = validate_success(
            api_client.create_plan_section(
                plan["id"],
                {"section_type": "SCOPE", "content": "added after rejection",
                 "order_index": 4},
                author_headers),
            expected_status=201)
        assert added["section_type"] == "SCOPE"
        sections = validate_success(api_client.list_plan_sections(plan["id"], author_headers))
        assert len(sections) == 4, f"expected 4 sections after the DRAFT edit, got {len(sections)}"

    def test_plan_resubmit_and_approve_records_approved_version(self, api):
        """PRD §3.3: "On success the server records `approved_version_no` equal to the plan's `version_no`, increments the plan's `version`, and makes the plan the process's activatable plan for future crisis activations."
        PRD §3.3: "The approver may instead return the plan to the author, moving `IN_REVIEW` → `DRAFT` with no further ceremony."

        The rejected plan can be resubmitted and approved; approved_version_no mirrors version_no.

        Design: Difficulty/non_linear_state_machine/plan_in_review_reject_loop_back_to_draft
        """
        author, approver, _, plan, _ = self._setup_rejected_plan()
        submit_plan(plan["id"], author["id"])
        approved = approve_plan(plan["id"], approver["id"])
        assert approved["status"] == "APPROVED"
        assert approved["approved_version_no"] == 1, (
            "approved_version_no must equal the plan's author-declared version_no"
        )


class TestBiaApprovalCascade:
    def _setup_two_bias_and_plan(self):
        committee = create_contact("Cm One", "Risk Committee")
        author = create_contact("Author Ann", "Plan Author")
        process = create_active_process(author["id"], name="Payroll")
        bia1 = create_approved_bia(process["id"], committee["id"],
                                   cycle_label="FY2026-H1", rto_target_hours=8,
                                   rpo_target_hours=2, impact_financial_per_hour=300)
        plan = create_plan(process["id"], author["id"], title="Payroll DR",
                           version_no=1, strategy_type="WARM_SITE",
                           rto_committed_hours=8, rpo_committed_hours=2)
        bia2 = create_bia(process["id"], cycle_label="FY2026-H2",
                          rto_target_hours=8, rpo_target_hours=2,
                          impact_financial_per_hour=350)
        submit_bia(bia2["id"])
        return committee, author, process, bia1, bia2, plan

    def test_bia_approval_supersedes_prior_approved_bia(self, api):
        """PRD §3.2: "First, the **supersede hop**: the previously `APPROVED` analysis of the same process, if one exists, moves `APPROVED` → `SUPERSEDED` with its own `version` increment — its score remains `FINAL` and readable, and plans pinned to it keep their pin until the second cascade reaches them."

        Approving the newer analysis supersedes the previously APPROVED one.

        Design: Difficulty/transitive_cascade/bia_approval_supersede_adoption_cascade
        """
        committee, _, _, bia1, bia2, plan = self._setup_two_bias_and_plan()
        assert plan["target_bia_id"] == bia1["id"], (
            "plan created while only BIA-1 was APPROVED must pin BIA-1"
        )
        decide_bia(bia2["id"], "APPROVE", committee["id"])
        reread = validate_success(
            api_client.get_bia(bia1["id"], make_risk_committee_headers(committee["id"])))
        assert reread["status"] == "SUPERSEDED"
        assert reread["score_variant"] == "FINAL"

    def test_bia_approval_adoption_refresh_repins_draft_plan(self, api):
        """PRD §3.2: "Second, the **adoption refresh**: every plan of the same process in `DRAFT` or `IN_REVIEW` whose `target_bia_id` resolves to a different analysis than the newly approved one is re-pinned to the newly approved analysis, with `last_adoption_check_cycle` set to the approved analysis's `cycle_label` and a `version` increment per re-pinned plan."

        The DRAFT plan is re-pinned to the newly approved analysis without any plan-endpoint call.

        Design: Difficulty/transitive_cascade/bia_approval_supersede_adoption_cascade
        """
        committee, author, _, bia1, bia2, plan = self._setup_two_bias_and_plan()
        assert plan["target_bia_id"] == bia1["id"]
        assert plan["version"] == 1
        decide_bia(bia2["id"], "APPROVE", committee["id"])
        reread = validate_success(
            api_client.get_plan(plan["id"], make_plan_author_headers(author["id"])))
        assert reread["target_bia_id"] == bia2["id"], (
            "adoption refresh must re-pin target_bia_id to the newly approved analysis"
        )
        assert reread["last_adoption_check_cycle"] == "FY2026-H2"
        assert reread["version"] == plan["version"] + 1, (
            "the re-pin increments Plan.version without any plan endpoint call"
        )


class TestPlanApprovalTargetGates:
    def test_plan_approve_rejected_when_target_bia_submitted(self, api):
        """PRD §3.3: "Its `target_bia_id` must be non-empty and must resolve to an analysis currently in `APPROVED`; otherwise approval fails with `ERR_PLAN_TARGETS_UNAPPROVED_BIA` — a plan pinned to a merely `SUBMITTED` analysis, or to nothing, cannot be approved."
        PRD §3.3: "At creation the server pins the plan's governing analysis, `target_bia_id`: the process's latest `APPROVED` analysis if one exists, else its latest `SUBMITTED` one, else the pin stays empty."

        A plan pinned to a SUBMITTED analysis cannot be approved.

        Design: Difficulty/cross_entity_state_dependency/plan_approve_gated_by_target_bia_state
        """
        committee = create_contact("Cm One", "Risk Committee")
        approver = create_contact("Approver Al", "Plan Approver")
        process = create_active_process(committee["id"], name="KYC",
                                        criticality_tier="TIER_3")
        bia = create_bia(process["id"], rto_target_hours=8, rpo_target_hours=2)
        submit_bia(bia["id"])
        plan = create_plan_with_sections(
            process["id"], approver["id"], title="KYC DR", version_no=1,
            strategy_type="MANUAL_WORKAROUND", rto_committed_hours=8,
            rpo_committed_hours=2)
        assert plan["target_bia_id"] == bia["id"], (
            "with no APPROVED analysis, creation must pin the latest SUBMITTED one"
        )
        submit_plan(plan["id"], approver["id"])
        response = api_client.approve_plan(plan["id"], make_plan_approver_headers(approver["id"]))
        validate_error(response, ApiErrorId.ERR_PLAN_TARGETS_UNAPPROVED_BIA)

    def test_plan_approve_succeeds_after_target_bia_approved(self, api):
        """PRD §3.3: "Its `target_bia_id` must be non-empty and must resolve to an analysis currently in `APPROVED`; otherwise approval fails with `ERR_PLAN_TARGETS_UNAPPROVED_BIA` — a plan pinned to a merely `SUBMITTED` analysis, or to nothing, cannot be approved."

        Once the pinned analysis is APPROVED, the identical approve call succeeds.

        Design: Difficulty/cross_entity_state_dependency/plan_approve_gated_by_target_bia_state
        """
        committee = create_contact("Cm One", "Risk Committee")
        approver = create_contact("Approver Al", "Plan Approver")
        process = create_active_process(committee["id"], name="KYC",
                                        criticality_tier="TIER_3")
        bia = create_bia(process["id"], rto_target_hours=8, rpo_target_hours=2)
        submit_bia(bia["id"])
        plan = create_plan_with_sections(
            process["id"], approver["id"], title="KYC DR", version_no=1,
            strategy_type="MANUAL_WORKAROUND", rto_committed_hours=8,
            rpo_committed_hours=2)
        submit_plan(plan["id"], approver["id"])
        decide_bia(bia["id"], "APPROVE", committee["id"])
        approved = approve_plan(plan["id"], approver["id"])
        assert approved["status"] == "APPROVED", (
            "approval must succeed once the pinned analysis is APPROVED"
        )


class TestPlanApprovalCommittedBoundary:
    def _setup_in_review_plan(self, name, title, version_no, rto_committed):
        committee = create_contact("Cm One", "Risk Committee")
        approver = create_contact("Approver Al", "Plan Approver")
        process = create_active_process(committee["id"], name=name)
        create_approved_bia(process["id"], committee["id"],
                            rto_target_hours=8, rpo_target_hours=2)
        plan = create_plan_with_sections(
            process["id"], approver["id"], title=title, version_no=version_no,
            strategy_type="WARM_SITE", rto_committed_hours=rto_committed,
            rpo_committed_hours=2)
        submit_plan(plan["id"], approver["id"])
        return approver, plan

    def test_plan_approval_allows_committed_rto_equal_to_target(self, api):
        """PRD §3.3: "The plan's `rto_committed_hours` must not exceed the target analysis's `rto_target_hours` (`ERR_PLAN_EXCEEDS_BIA_RTO`), and its `rpo_committed_hours` must not exceed the target analysis's `rpo_target_hours` (`ERR_PLAN_EXCEEDS_BIA_RPO`)."
        PRD §2.7: "All comparison boundaries in scoring and target checks are inclusive: a measured value exactly equal to its target passes."

        rto_committed 8 against an 8-hour target passes the inclusive boundary.

        Design: Difficulty/boundary_precision_check/plan_approval_rto_committed_equal_to_target
        """
        approver, plan = self._setup_in_review_plan("ATM", "ATM DR equal", 1, 8)
        approved = approve_plan(plan["id"], approver["id"])
        assert approved["status"] == "APPROVED", "8 <= 8 must pass the inclusive boundary"

    def test_plan_approval_rejects_committed_rto_above_target(self, api):
        """PRD §3.3: "The plan's `rto_committed_hours` must not exceed the target analysis's `rto_target_hours` (`ERR_PLAN_EXCEEDS_BIA_RTO`), and its `rpo_committed_hours` must not exceed the target analysis's `rpo_target_hours` (`ERR_PLAN_EXCEEDS_BIA_RPO`)."

        rto_committed 9 against an 8-hour target breaches the gate.

        Design: Difficulty/boundary_precision_check/plan_approval_rto_committed_equal_to_target
        """
        approver, plan = self._setup_in_review_plan("ATM", "ATM DR over", 1, 9)
        response = api_client.approve_plan(plan["id"], make_plan_approver_headers(approver["id"]))
        validate_error(response, ApiErrorId.ERR_PLAN_EXCEEDS_BIA_RTO)


class TestPlanApprovalPrecedence:
    def _setup_draft_over_target_plan(self):
        committee = create_contact("Cm One", "Risk Committee")
        approver = create_contact("Approver Al", "Plan Approver")
        process = create_active_process(committee["id"], name="Loans")
        bia = create_approved_bia(process["id"], committee["id"],
                                  rto_target_hours=4, rpo_target_hours=1,
                                  mtpd_hours=12)
        plan = create_plan(process["id"], approver["id"], title="Loans DR",
                           version_no=1, strategy_type="COLD_SITE",
                           rto_committed_hours=100, rpo_committed_hours=1)
        return committee, approver, process, bia, plan

    def test_plan_approve_in_draft_fails_state_before_rto_check(self, api):
        """PRD §2.10: "The layers are evaluated in this fixed sequence, and the first failing layer wins"
        PRD §2.10: "6. **State legality** — the target resource is in a state from which the invoked transition exists, terminal states are locked, and state-guarded writes are honored"
        PRD §2.10: "13. **Plan approval target checks** — governing analysis approved (`ERR_PLAN_TARGETS_UNAPPROVED_BIA`, HTTP 422), committed recovery time within target (`ERR_PLAN_EXCEEDS_BIA_RTO`, HTTP 422), and committed recovery point within target (`ERR_PLAN_EXCEEDS_BIA_RPO`, HTTP 422), in that order within the approval evaluation."

        A DRAFT plan over its target fails state legality (layer 6), not the RTO gate (layer 13).

        Design: Difficulty/priority_pair_validation_conflict/approve_wrong_state_beats_rto_overage
        """
        _, approver, _, bia, plan = self._setup_draft_over_target_plan()
        assert plan["target_bia_id"] == bia["id"], (
            "the fiscal rule would fire if the evaluation ever reached it"
        )
        response = api_client.approve_plan(plan["id"], make_plan_approver_headers(approver["id"]))
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    def test_plan_approve_wrong_state_leaves_plan_unchanged(self, api):
        """PRD §3.3: "The plan must be `IN_REVIEW` (`ERR_INVALID_STATE`)."
        PRD §2.10: "The layers are evaluated in this fixed sequence, and the first failing layer wins"

        The rejected approval mutates nothing: the plan stays DRAFT at its captured version.

        Design: Difficulty/priority_pair_validation_conflict/approve_wrong_state_beats_rto_overage
        """
        _, approver, _, _, plan = self._setup_draft_over_target_plan()
        response = api_client.approve_plan(plan["id"], make_plan_approver_headers(approver["id"]))
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        reread = validate_success(
            api_client.get_plan(plan["id"], make_plan_approver_headers(approver["id"])))
        assert reread["status"] == "DRAFT"
        assert reread["version"] == plan["version"]


class TestProcessRetireCascade:
    def test_process_retire_cascades_nonterminal_children(self, api):
        """PRD §3.1: "When retirement does proceed, it cascades: every plan of the process still in `DRAFT` or `IN_REVIEW` moves to `RETIRED` with a `version` increment on each, and every analysis still in `DRAFT` or `REJECTED` moves to `SUPERSEDED`, likewise with a `version` increment on each. The process's own `version` increments as well."

        Retiring the process force-retires the DRAFT plan and supersedes the DRAFT analysis.

        Design: Corner/entities/process_retire_cascades_nonterminal_children
        """
        owner = create_contact("Owner Ora", "Owner")
        process = create_active_process(owner["id"], name="RetireMe",
                                        criticality_tier="TIER_3")
        bia = create_bia(process["id"], rto_target_hours=8, rpo_target_hours=2,
                         impact_financial_per_hour=100)
        plan = create_plan(process["id"], owner["id"], title="T", version_no=1,
                           strategy_type="COLD_SITE", rto_committed_hours=8,
                           rpo_committed_hours=2)
        retired = validate_success(api_client.retire_process(process["id"], ADMIN_HEADERS))
        assert retired["status"] == "RETIRED"
        bia_after = validate_success(api_client.get_bia(bia["id"], ADMIN_HEADERS))
        assert bia_after["status"] == "SUPERSEDED", (
            "retirement must move the DRAFT analysis to SUPERSEDED"
        )
        plan_after = validate_success(api_client.get_plan(plan["id"], ADMIN_HEADERS))
        assert plan_after["status"] == "RETIRED", (
            "retirement must move the DRAFT plan to RETIRED"
        )


class TestBiaUniquenessAndShape:
    def test_bia_create_mtpd_below_rto_rejected(self, api):
        """PRD §3.2: "The tolerable period must be at least the recovery time target; an analysis whose `mtpd_hours` falls below its `rto_target_hours` is rejected with `ERR_MTPD_BELOW_RTO`."

        mtpd_hours 4 below rto_target_hours 8 is rejected at creation.

        Design: Corner/validations/bia_create_mtpd_below_rto_rejected
        """
        analyst = create_contact("Analyst Amy", "BIA Analyst")
        process = create_active_process(analyst["id"], name="MTPDProc")
        payload = {
            "process_id": process["id"], "cycle_label": "FY2026-H1",
            "rto_target_hours": 8, "rpo_target_hours": 2, "mtpd_hours": 4,
            "peak_period_flag": False, "impact_financial_per_hour": 100,
            "impact_regulatory": "NONE", "impact_reputational": "NONE",
            "impact_operational": "NONE",
        }
        response = api_client.create_bia(payload, ANALYST_HEADERS)
        validate_error(response, ApiErrorId.ERR_MTPD_BELOW_RTO)

    def test_duplicate_bia_cycle_label_per_process(self, api):
        """PRD §2.11: "Uniqueness is enforced across the registry as follows, each violation failing with `ERR_DUPLICATE` (HTTP 409): a vendor's `name` is globally unique; a site's `name` is globally unique; a contact's `email` is globally unique; among analyses of one process that are not `SUPERSEDED`, the `cycle_label` is unique per process; among plans of one process that are not `RETIRED`, the author-declared `version_no` is unique per process; within one plan, a section's `order_index` is unique; and within one communication tree, the triple of `tree_label`, `parent_node_id`, and `order_index` is unique among sibling nodes."

        A second live FY2026-H1 analysis for the same process is refused; the same
        label on a different process succeeds.

        Design: Corner/validations/duplicate_bia_cycle_label_per_process
        """
        analyst_headers = ANALYST_HEADERS
        analyst = create_contact("Analyst Amy", "BIA Analyst")
        p1 = create_active_process(analyst["id"], name="DupP1")
        p2 = create_active_process(analyst["id"], name="DupP2")
        create_bia(p1["id"], cycle_label="FY2026-H1", rto_target_hours=8,
                   rpo_target_hours=2, impact_financial_per_hour=100)

        dup_payload = {
            "process_id": p1["id"], "cycle_label": "FY2026-H1",
            "rto_target_hours": 4, "rpo_target_hours": 1, "mtpd_hours": 12,
            "peak_period_flag": False, "impact_financial_per_hour": 200,
            "impact_regulatory": "LOW", "impact_reputational": "NONE",
            "impact_operational": "NONE",
        }
        response = api_client.create_bia(dup_payload, analyst_headers)
        validate_error(response, ApiErrorId.ERR_DUPLICATE)

        ok_payload = dict(dup_payload, process_id=p2["id"])
        created = validate_success(
            api_client.create_bia(ok_payload, analyst_headers), expected_status=201)
        assert created["process_id"] == p2["id"], (
            "the same cycle_label on a different process is allowed"
        )


class TestPlanOptimisticConcurrency:
    def test_stale_plan_version_after_adoption_refresh(self, api):
        """PRD §2.8: "Updating a recovery plan requires the request to carry `expected_plan_version`, holding the plan `version` the author last observed; if the plan's current `version` has advanced since then — most commonly because a BIA approval's adoption refresh re-pinned the plan's governing analysis in the meantime — the update is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.2: "Second, the **adoption refresh**: every plan of the same process in `DRAFT` or `IN_REVIEW` whose `target_bia_id` resolves to a different analysis than the newly approved one is re-pinned to the newly approved analysis, with `last_adoption_check_cycle` set to the approved analysis's `cycle_label` and a `version` increment per re-pinned plan."

        The adoption refresh bumps the plan's version, so the author's stale PUT is
        rejected 412; retrying with the freshly read version succeeds.

        Design: Corner/validations/stale_plan_version_after_adoption_refresh
        """
        committee = create_contact("Cm One", "Risk Committee")
        author = create_contact("Author Ann", "Author")
        process = create_active_process(author["id"], name="OccProc")
        bia1 = create_bia(process["id"], cycle_label="FY2026-H1",
                          rto_target_hours=8, rpo_target_hours=2,
                          impact_financial_per_hour=100)
        submit_bia(bia1["id"])
        author_headers = make_plan_author_headers(author["id"])
        plan = create_plan(process["id"], author["id"], title="OCC DR",
                           version_no=1, strategy_type="WARM_SITE",
                           rto_committed_hours=8, rpo_committed_hours=2)
        captured_version = plan["version"]

        bia2 = create_bia(process["id"], cycle_label="FY2026-H2",
                          rto_target_hours=8, rpo_target_hours=2,
                          impact_financial_per_hour=120)
        submit_bia(bia2["id"])
        decide_bia(bia2["id"], "APPROVE", committee["id"])

        stale = api_client.update_plan(
            plan["id"], {"title": "OCC DR renamed",
                         "expected_plan_version": captured_version},
            author_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(api_client.get_plan(plan["id"], author_headers))
        assert fresh["version"] > captured_version
        retried = validate_success(
            api_client.update_plan(
                plan["id"], {"title": "OCC DR renamed",
                             "expected_plan_version": fresh["version"]},
                author_headers))
        assert retried["title"] == "OCC DR renamed"
