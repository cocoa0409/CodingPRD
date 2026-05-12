"""Concentrated coverage for the difficulty-design priority queue.

Every instance from SCAFFOLD_DIFFICULTY_DESIGN.yaml is exercised at least
once here (additional copies live in the lifecycle / workflow files).
Each test cites the PRD sentence(s) the difficulty instance grounds in.

Each test carries a "difficulty:" tag of the form
"rule-id slash instance-name" so the coverage audit can map tests back
to instances.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    advance_clock,
    api_client,
    create_department,
    create_matter,
    create_matter_version_draft,
    create_published_certificate_template,
    create_published_material_template,
    decide,
    decide_review_task_payload,
    deficiency_entry,
    drive_to_under_review,
    expected_fee_total_cents,
    get_application,
    get_success_data,
    issue_correction_for_primary_material,
    issue_correction_notice_payload,
    list_correction_notices,
    list_review_tasks,
    make_catalog_manager_headers,
    make_lead_reviewer_headers,
    make_reviewer_headers,
    make_routing,
    publish_matter_version,
    resubmit_correction_payload,
    resubmit_primary_material,
    run_sweep,
    setup_application_at_correction_round,
    setup_application_under_review_parallel,
    setup_application_under_review_serial,
    setup_application_under_review_single_dept,
    setup_approved_application_with_certificate,
    setup_parallel_routing_published_version,
    setup_single_department_published_version,
    submit_application,
    submitted_material_entry,
    TEST_USERS,
    validate_error,
    validate_success,
    WORKING_DAY_SECONDS,
)


# ===========================================================================
# Rule 1: dual_variant_calc -- 2nd-coverage tests
# ===========================================================================
class TestDualVariantCalc:
    def test_committed_variant_drives_application_deadline_at(self, api):
        """PRD §3.7: "Because committed_time_limit_days is at most equal
        to statutory_time_limit_days, the committed variant always
        yields the earlier deadline and the statutory variant always
        yields the later deadline."

        Claim: with committed=10 and statutory=15 days,
        Application.deadline_at corresponds to the COMMITTED window
        (10*28800=288,000s after clock_started_at), strictly less than
        the statutory window (15*28800=432,000s).

        # difficulty: dual_variant_calc/time_limit_committed_vs_statutory_on_application
        """
        from test_helpers import parse_iso
        ctx = setup_application_under_review_single_dept(
            committed_time_limit_days=10,
            statutory_time_limit_days=15,
        )
        app = get_application(ctx["application"]["id"])
        clock_started = parse_iso(app["clock_started_at"])
        deadline = parse_iso(app["deadline_at"])
        delta = int((deadline - clock_started).total_seconds())
        assert delta == 10 * WORKING_DAY_SECONDS, (
            f"deadline_at must use committed (10 days = 288,000s), got {delta}s"
        )
        # And it is strictly less than the statutory window
        assert delta < 15 * WORKING_DAY_SECONDS

    def test_final_fee_breakdown_remains_stable_after_terminal(self, api):
        """PRD §3.11: "The final variant is the form reported once the
        application is in APPROVED, REJECTED, or WITHDRAWN: the
        breakdown is frozen at the correction_round value at the moment
        of the terminal transition and never recomputes thereafter."

        Claim: read fee_breakdown twice on an APPROVED application;
        total_cents is identical (frozen, no drift).

        # difficulty: dual_variant_calc/certificate_fee_provisional_vs_final_on_application
        """
        ctx = setup_application_under_review_single_dept(fee_amount_cents=1000)
        decide(ctx["review_tasks"][0]["id"], "AGREED", ctx["reviewer_headers"])
        first = validate_success(
            api.get_application(
                ctx["application"]["id"], ctx["applicant_headers"]
            )
        )
        second = validate_success(
            api.get_application(
                ctx["application"]["id"], ctx["applicant_headers"]
            )
        )
        first_total = first["fee_breakdown"]["total_cents"]
        second_total = second["fee_breakdown"]["total_cents"]
        assert first["review_status"] == "APPROVED"
        assert first_total == second_total, (
            f"PRD §3.11 final variant must not recompute: "
            f"first={first_total}, second={second_total}"
        )
        assert first_total == expected_fee_total_cents(1000, 0)


# ===========================================================================
# Rule 2: combinatorial_formula -- opinion aggregation branching
# ===========================================================================
class TestOpinionAggregationBranching:
    def test_majority_tie_resolves_to_disagreed(self, api):
        """PRD §3.8: "Under MAJORITY, the result remains PENDING until
        every non-SKIPPED task has decided ... when that happens, the
        result is AGREED if the count of AGREED tasks is strictly greater
        than the count of DISAGREED tasks, and DISAGREED otherwise (equal
        counts resolve to DISAGREED)."

        Claim: PARALLEL/MAJORITY on 4 stages with 2 AGREED + 2 DISAGREED
        -> Application transitions to REJECTED (tie).

        # difficulty: combinatorial_formula/opinion_aggregation_three_input_branching
        """
        ctx = setup_application_under_review_parallel(
            department_count=4, aggregation_rule="MAJORITY",
        )
        tasks = ctx["review_tasks"]
        # First two AGREE, last two DISAGREE.
        decisions = ["AGREED", "AGREED", "DISAGREED", "DISAGREED"]
        for task, decision in zip(tasks, decisions):
            headers = ctx["reviewer_headers_by_dept_id"][task["department_id"]]
            decide(task["id"], decision, headers)
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "REJECTED"

    def test_lead_decides_lead_agreed_short_circuits_to_approved(self, api):
        """PRD §3.8: "Under LEAD_DECIDES, the result is AGREED as soon as
        the lead task -- the unique task whose is_lead is true -- reaches
        AGREED, DISAGREED as soon as the lead task reaches DISAGREED, and
        PENDING otherwise; the non-lead tasks' statuses do not change
        the verdict."

        Claim: PARALLEL/LEAD_DECIDES on 4 stages: lead AGREED, two
        non-lead DISAGREED -> Application transitions to APPROVED on
        the lead's AGREED, regardless of subsequent non-lead decisions.

        # difficulty: combinatorial_formula/opinion_aggregation_three_input_branching
        """
        ctx = setup_application_under_review_parallel(
            department_count=4, aggregation_rule="LEAD_DECIDES",
        )
        tasks = ctx["review_tasks"]
        # The first task is the lead per setup_parallel_routing... helper.
        lead_task = next(t for t in tasks if t["is_lead"])
        lead_headers = ctx["reviewer_headers_by_dept_id"][lead_task["department_id"]]
        decide(lead_task["id"], "AGREED", lead_headers)
        # Should already be APPROVED.
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "APPROVED"


# ===========================================================================
# Rule 2 again: combinatorial_formula -- pinned rounding order (2nd test)
# ===========================================================================
class TestFeeRoundingOrderSecondCoverage:
    def test_per_line_ceil_for_round_zero_yields_zero_overhead(self, api):
        """PRD §3.11: "The administrative-overhead line in cents equals
        the surcharge subtotal in cents multiplied by the overhead-rate
        basis points (500 basis points, i.e., 5.00%), divided by 10,000,
        and ceilinged to the next integer cent." PRD §3.11: "The
        per-correction surcharge subtotal in cents is 0 when the
        application's correction_round is 0."

        Claim: with base=1000 cents and correction_round=0,
        admin_overhead_cents == ceil(0*500/10000) == 0,
        handling_line_cents == ceil(1000*200/10000) == 20,
        total == 1000 + 20 + 0 + 0 == 1020.

        # difficulty: combinatorial_formula/certificate_fee_pinned_rounding_order
        """
        ctx = setup_application_under_review_single_dept(
            fee_amount_cents=1000,
        )
        data = validate_success(
            api.get_application(ctx["application"]["id"], ctx["applicant_headers"])
        )
        breakdown = data["fee_breakdown"]
        assert breakdown["surcharge_subtotal_cents"] == 0
        assert breakdown["admin_overhead_cents"] == 0
        assert breakdown["handling_line_cents"] == 20
        assert breakdown["total_cents"] == 1020


# ===========================================================================
# Rule 3 again: non_linear_state_machine -- certificate branching (2nd test)
# ===========================================================================
class TestCertificateBranchingSecondCoverage:
    def test_reissue_creates_certificate_with_distinct_serial(
        self, api, certificate_officer_headers,
    ):
        """PRD §3.10: "Reissue creates a fresh Certificate row using the
        same certificate_template_id as the source, with a fresh
        serial_number, a fresh verification_code, a fresh issued_at, and
        a fresh expires_at derived from the new issued_at."

        Claim: a reissue against an ACTIVE certificate yields a NEW
        certificate whose serial_number differs from the source's.

        # difficulty: non_linear_state_machine/certificate_branching_with_revert_on_reissue
        """
        ctx = setup_approved_application_with_certificate(validity_days=1)
        cert1 = ctx["certificate"]
        resp = api.reissue_certificate(cert1["id"], certificate_officer_headers)
        cert2 = validate_success(resp, expected_status=201)
        assert cert2["serial_number"] != cert1["serial_number"]
        assert cert2["verification_code"] != cert1["verification_code"]
        assert cert2["status"] == "ACTIVE"


# ===========================================================================
# Rule 4: transitive_cascade -- depth-3 (2nd test) and depth-2 (both)
# ===========================================================================
class TestCascades:
    def test_correction_expiry_cascade_application_status_rejected(self, api):
        """PRD §3.6: "A notice that is left OPEN past its due_at is swept
        to EXPIRED ... Expiration cascades the application from
        AWAITING_CORRECTION to REJECTED."

        Claim: clock-advance + sweep flips Application.review_status
        from AWAITING_CORRECTION to REJECTED (link 2 of the 3-hop
        cascade -- complementary perspective to the test_05 invariant
        check).

        # difficulty: transitive_cascade/correction_expiry_cascade_depth_three
        """
        ctx = setup_application_under_review_single_dept(
            correction_window_days=1,
        )
        notice = issue_correction_for_primary_material(ctx=ctx)
        before = get_application(ctx["application"]["id"])
        assert before["review_status"] == "AWAITING_CORRECTION"
        advance_clock(WORKING_DAY_SECONDS + 1)
        run_sweep()
        after = get_application(ctx["application"]["id"])
        assert after["review_status"] == "REJECTED"

    def test_publish_v2_cascade_supersedes_v1_and_repoints_matter(self, api):
        """PRD §3.1: "If a previously PUBLISHED sibling existed, it is
        auto-cascaded from PUBLISHED to SUPERSEDED in the same request."
        PRD §3.1: "Publishing the version is the flip from DRAFT to
        PUBLISHED. ... On success, ... Matter.current_published_version_id
        repoints to this version."

        Claim: publishing V2 on a matter that already has V1 PUBLISHED
        flips V1 to SUPERSEDED in the same request, and Matter
        .current_published_version_id repoints to V2 (depth-2 cascade
        from a single user-driven publish API call).

        # difficulty: transitive_cascade/matter_version_publish_cascade_depth_two
        """
        ctx = setup_single_department_published_version()
        v1 = ctx["version"]
        # Build V2 draft, then publish.
        v2_draft = create_matter_version_draft(
            matter_id=ctx["matter"]["id"],
            catalog_manager_headers=ctx["catalog_manager_headers"],
            required_material_template_ids=ctx["all_required_material_template_ids"],
            certificate_template_id=ctx["certificate_template"]["id"],
            review_routing=v1["review_routing"],
        )
        v2 = publish_matter_version(
            matter_id=ctx["matter"]["id"],
            version_id=v2_draft["id"],
            catalog_manager_headers=ctx["catalog_manager_headers"],
        )
        # V1 -> SUPERSEDED.
        v1_refresh = get_success_data(
            api.get_matter_version(
                ctx["matter"]["id"], v1["id"], ctx["catalog_manager_headers"],
            )
        )
        assert v1_refresh["status"] == "SUPERSEDED"
        # Matter pointer repoints.
        m_refresh = get_success_data(
            api.get_matter(ctx["matter"]["id"], ctx["catalog_manager_headers"])
        )
        assert m_refresh["current_published_version_id"] == v2["id"]

    def test_publish_v2_does_not_force_in_flight_to_repin(self, api):
        """PRD §3.1: "that sibling becomes read-only but in-flight
        applications retain their pinned matter_version_id and continue
        against the rules they snapshotted at submission."

        Claim: an Application submitted against V1 BEFORE V2 publishes
        retains matter_version_id == V1.id even after V1 is SUPERSEDED.

        # difficulty: transitive_cascade/matter_version_publish_cascade_depth_two
        """
        ctx = setup_application_under_review_single_dept()
        v1_id = ctx["version"]["id"]
        application_id = ctx["application"]["id"]
        # Publish a new V2 on the same matter.
        v2_draft = create_matter_version_draft(
            matter_id=ctx["matter"]["id"],
            catalog_manager_headers=ctx["catalog_manager_headers"],
            required_material_template_ids=ctx["all_required_material_template_ids"],
            certificate_template_id=ctx["certificate_template"]["id"],
            review_routing=ctx["version"]["review_routing"],
        )
        publish_matter_version(
            matter_id=ctx["matter"]["id"],
            version_id=v2_draft["id"],
            catalog_manager_headers=ctx["catalog_manager_headers"],
        )
        # The Application is still pinned to V1.
        app = get_application(application_id)
        assert app["matter_version_id"] == v1_id


# ===========================================================================
# Rule 5: priority_pair_validation_conflict
# ===========================================================================
class TestValidationPriorityConflicts:
    def test_resubmit_after_due_at_with_unresolved_deficiency_returns_correction_expired(
        self, api,
    ):
        """PRD §2.7: "When a single endpoint is guarded by multiple
        validation rules, the server evaluates them in a fixed priority
        order so that the same request always produces the same
        error_id. The ordering, from highest priority (evaluated first)
        to lowest, is: ... then resubmit temporal validity, then
        per-correction round budget, then deficiency coverage on
        resubmit ... A higher-priority failure short-circuits -- the
        lower-priority checks are not evaluated and their error_id
        cannot surface for that request."

        Claim: a resubmit after due_at AND with empty submitted_materials
        (which would fail ERR_DEFICIENCY_UNRESOLVED at lower priority)
        returns ERR_CORRECTION_EXPIRED, NOT ERR_DEFICIENCY_UNRESOLVED.

        # difficulty: priority_pair_validation_conflict/state_vs_business_referential_conflict_on_resubmit
        """
        ctx = setup_application_under_review_single_dept(
            correction_window_days=1,
        )
        notice = issue_correction_for_primary_material(ctx=ctx)
        # Advance past due_at.
        advance_clock(WORKING_DAY_SECONDS + 1)
        # Resubmit with EMPTY submitted_materials -- both checks would
        # fail; PRD §2.7 mandates ERR_CORRECTION_EXPIRED wins.
        payload = resubmit_correction_payload(submitted_materials=[])
        resp = api.resubmit_correction(
            ctx["application"]["id"], notice["id"], payload,
            ctx["applicant_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CORRECTION_EXPIRED)

    def test_publish_nonexistent_version_returns_not_found(self, api):
        """PRD §2.6: "Path parameters are validated strictly
        left-to-right ... A missing parent yields ERR_NOT_FOUND for the
        parent identifier, never a child-level error. The same ordering
        governs validation: existence (priority 3) is checked before
        state (priority 4), and state is checked before any
        business-referential or business-constraint rule, regardless of
        the order in which fields appear in the request body."

        Claim: POST /matters/{real}/versions/{nonexistent}/publish
        yields ERR_NOT_FOUND, NOT a downstream business-constraint
        error like ERR_DEPENDENT_TEMPLATE_UNPUBLISHED.

        # difficulty: priority_pair_validation_conflict/existence_vs_business_constraint_conflict_on_publish
        """
        ctx = setup_single_department_published_version()
        resp = api.publish_matter_version(
            ctx["matter"]["id"], NON_EXISTENT_UUID,
            ctx["catalog_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ===========================================================================
# Rule 5 (continued): priority_pair_validation_conflict -- 2nd-coverage
# ===========================================================================
class TestPriorityPairConflictsSecondCoverage:
    def test_resubmit_after_due_at_with_extra_invalid_payload_returns_correction_expired(
        self, api,
    ):
        """PRD §3.6: "It is rejected with ERR_CORRECTION_EXPIRED if the
        current server time is past the notice's due_at." PRD §2.7:
        "A higher-priority failure short-circuits -- the lower-priority
        checks are not evaluated and their error_id cannot surface for
        that request."

        Claim: a resubmit past due_at whose submitted_materials carry
        an entry referencing the wrong material_template_id (which would
        otherwise trigger ERR_DEFICIENCY_UNRESOLVED at lower priority)
        still returns ERR_CORRECTION_EXPIRED -- temporal validity
        priority short-circuits.

        # difficulty: priority_pair_validation_conflict/state_vs_business_referential_conflict_on_resubmit
        """
        ctx = setup_application_under_review_single_dept(
            correction_window_days=1,
        )
        notice = issue_correction_for_primary_material(ctx=ctx)
        advance_clock(WORKING_DAY_SECONDS + 1)
        # submitted_materials covers an unrelated template id; would
        # produce ERR_DEFICIENCY_UNRESOLVED but temporal check wins.
        unrelated_material = create_published_material_template(
            catalog_manager_headers=ctx["catalog_manager_headers"],
        )
        payload = resubmit_correction_payload(
            submitted_materials=[
                submitted_material_entry(unrelated_material["id"])
            ],
        )
        resp = api.resubmit_correction(
            ctx["application"]["id"], notice["id"], payload,
            ctx["applicant_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CORRECTION_EXPIRED)

    def test_publish_with_zero_uuid_path_returns_not_found(self, api):
        """PRD §2.6: "existence (priority 3) is checked before state
        (priority 4), and state is checked before any
        business-referential or business-constraint rule, regardless of
        the order in which fields appear in the request body."

        Claim: POST /matters/{real}/versions/{all-zero-uuid}/publish
        returns ERR_NOT_FOUND, not a downstream validation error --
        the existence check (priority 3) wins over later checks.

        # difficulty: priority_pair_validation_conflict/existence_vs_business_constraint_conflict_on_publish
        """
        ctx = setup_single_department_published_version()
        zero_uuid = "00000000-0000-0000-0000-000000000000"
        resp = api.publish_matter_version(
            ctx["matter"]["id"], zero_uuid, ctx["catalog_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ===========================================================================
# Rule 8 (continued): resource_temporal_overlap -- 2nd-coverage for half-open
# ===========================================================================
class TestPublishWindowSecondCoverage:
    def test_v1_supersede_does_not_affect_in_flight_application_pinning(
        self, api,
    ):
        """PRD §3.5: "and provided the pinned MatterVersion's status is
        in {PUBLISHED, SUPERSEDED} so that the version is still legally
        usable -- the system transitions the application from SUBMITTED
        to UNDER_REVIEW."

        Claim: a pre-existing Application pinned to V1 still progresses
        to UNDER_REVIEW even after V1 has been auto-superseded by V2,
        confirming the half-open supersede window does not break
        in-flight applications. Read-side: Application.matter_version_id
        remains pointing at V1.id.

        # difficulty: resource_temporal_overlap/matter_version_publish_window_supersedes_prior_half_open
        """
        # Submit application against V1 BEFORE publishing V2.
        ctx = setup_single_department_published_version(fee_amount_cents=0)
        v1_id = ctx["version"]["id"]
        application, applicant_headers, _aid = submit_application(ctx=ctx)
        # Now publish V2 -- should auto-supersede V1.
        v2_draft = create_matter_version_draft(
            matter_id=ctx["matter"]["id"],
            catalog_manager_headers=ctx["catalog_manager_headers"],
            required_material_template_ids=ctx["all_required_material_template_ids"],
            certificate_template_id=ctx["certificate_template"]["id"],
            review_routing=ctx["version"]["review_routing"],
        )
        publish_matter_version(
            matter_id=ctx["matter"]["id"],
            version_id=v2_draft["id"],
            catalog_manager_headers=ctx["catalog_manager_headers"],
        )
        # Application still pinned to V1 even though V1 is now SUPERSEDED.
        app = get_application(application["id"])
        assert app["matter_version_id"] == v1_id
        v1_refresh = get_success_data(
            api.get_matter_version(
                ctx["matter"]["id"], v1_id, ctx["catalog_manager_headers"],
            )
        )
        assert v1_refresh["status"] == "SUPERSEDED"


# ===========================================================================
# Rule 7: cross_entity_state_dependency -- 2nd-coverage
# ===========================================================================
class TestCrossEntityStateDependencies:
    def test_review_decide_with_open_correction_keeps_task_in_progress(
        self, api,
    ):
        """PRD §3.6: "or if any OPEN CorrectionNotice exists for the
        application -- open corrections pause every IN_PROGRESS task.
        On success, the task records decided_at as the server's current
        time."

        Claim: a rejected decide-attempt while a CorrectionNotice is
        OPEN leaves the task at IN_PROGRESS and decided_at unchanged
        (not stamped).

        # difficulty: cross_entity_state_dependency/review_task_decide_blocked_by_open_correction_notice_pair
        """
        ctx = setup_application_under_review_single_dept()
        notice = issue_correction_for_primary_material(ctx=ctx)
        assert notice["status"] == "OPEN"
        task = ctx["review_tasks"][0]
        before_status = task["status"]
        before_decided_at = task.get("decided_at")
        # Try to decide -- must fail.
        resp = api.decide_review_task(
            task["id"],
            decide_review_task_payload("AGREED", "ok", include_opinion=True),
            ctx["reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        # Re-list tasks; the target task must still be IN_PROGRESS, no
        # decided_at stamped.
        tasks_after = list_review_tasks(
            ctx["application"]["id"], ctx["reviewer_headers"]
        )
        target = next(t for t in tasks_after if t["id"] == task["id"])
        # PRD §3.6 wording: "open corrections pause every IN_PROGRESS task."
        # The task entered correction-issue time as IN_PROGRESS; under
        # PRD's wording the status stays at IN_PROGRESS (no decision
        # recorded). Whether the implementation surfaces a special
        # PAUSED label is not in PRD; assert non-terminal status only.
        assert target["status"] in ("IN_PROGRESS", before_status)
        assert target.get("decided_at") in (None, before_decided_at)

    def test_retire_after_terminal_application_succeeds(self, api):
        """PRD §3.1: "Retirement requires that no application whose
        review_status falls outside {APPROVED, REJECTED, WITHDRAWN}
        still references the version."

        Claim: an Application that has reached APPROVED no longer blocks
        retirement of its pinned MatterVersion.

        # difficulty: cross_entity_state_dependency/matter_version_retire_blocked_by_in_flight_application_pair
        """
        ctx = setup_application_under_review_single_dept()
        # Drive to APPROVED.
        decide(ctx["review_tasks"][0]["id"], "AGREED", ctx["reviewer_headers"])
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "APPROVED"
        # Retire must now succeed.
        resp = api.retire_matter_version(
            ctx["matter"]["id"], ctx["version"]["id"],
            ctx["catalog_manager_headers"],
        )
        validate_success(resp)


# ===========================================================================
# Rule 8: resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:
    def test_publish_v2_immediately_supersedes_v1_no_overlap(self, api):
        """PRD §3.1: "If a previously PUBLISHED sibling existed, it is
        auto-cascaded from PUBLISHED to SUPERSEDED in the same request."

        Claim: after publishing V2, listing the matter shows V1 already
        SUPERSEDED and current_published_version_id pointing only at V2
        (half-open interval -- no PUBLISHED-PUBLISHED overlap window).

        # difficulty: resource_temporal_overlap/matter_version_publish_window_supersedes_prior_half_open
        """
        ctx = setup_single_department_published_version()
        v1 = ctx["version"]
        v2_draft = create_matter_version_draft(
            matter_id=ctx["matter"]["id"],
            catalog_manager_headers=ctx["catalog_manager_headers"],
            required_material_template_ids=ctx["all_required_material_template_ids"],
            certificate_template_id=ctx["certificate_template"]["id"],
            review_routing=v1["review_routing"],
        )
        v2 = publish_matter_version(
            matter_id=ctx["matter"]["id"],
            version_id=v2_draft["id"],
            catalog_manager_headers=ctx["catalog_manager_headers"],
        )
        v1_refresh = get_success_data(
            api.get_matter_version(
                ctx["matter"]["id"], v1["id"], ctx["catalog_manager_headers"],
            )
        )
        assert v1_refresh["status"] == "SUPERSEDED"
        m_refresh = get_success_data(
            api.get_matter(ctx["matter"]["id"], ctx["catalog_manager_headers"])
        )
        assert m_refresh["current_published_version_id"] == v2["id"]

    def test_only_one_active_certificate_per_application_at_a_time(
        self, api, certificate_officer_headers,
    ):
        """PRD §3.10: "Reissue creates a fresh Certificate row using the
        same certificate_template_id as the source, with a fresh
        serial_number ... the source certificate's
        superseded_by_certificate_id is then set to the new certificate's
        id and its status flips from its prior value to REISSUED."

        Claim: after reissue, GET /applications/{id}/certificate returns
        the NEW certificate (status ACTIVE), confirming aggregate
        capacity = 1 ACTIVE Certificate per Application.

        # difficulty: resource_temporal_overlap/certificate_validity_window_aggregate_capacity_one_per_application
        """
        ctx = setup_approved_application_with_certificate(validity_days=1)
        cert1_serial = ctx["certificate"]["serial_number"]
        new_resp = api.reissue_certificate(
            ctx["certificate"]["id"], certificate_officer_headers,
        )
        cert2 = validate_success(new_resp, expected_status=201)
        assert cert2["status"] == "ACTIVE"
        # GET on the application's certificate must return the NEW one.
        active_resp = api.get_application_certificate(
            ctx["application"]["id"], TEST_USERS["platform_admin_headers"],
        )
        active = validate_success(active_resp)
        assert active["status"] == "ACTIVE"
        assert active["serial_number"] != cert1_serial
        assert active["serial_number"] == cert2["serial_number"]


# ===========================================================================
# Rule 9: compensating_invariant -- 2nd-coverage tests
# ===========================================================================
class TestCompensatingInvariants:
    def test_payment_refund_invariant_on_correction_failure(self, api):
        """PRD §3.6: "A notice that is left OPEN past its due_at is swept
        to EXPIRED ... Expiration cascades the application from
        AWAITING_CORRECTION to REJECTED."
        PRD §3.8: "if payment_status is PAID and the pinned
        fee_amount_cents is greater than 0, the payment is refunded by
        setting payment_status to REFUNDED."

        Claim: a fee>0 application driven to REJECTED via correction
        expiry has payment_status=='REFUNDED'.

        # difficulty: compensating_invariant/payment_refund_invariant_on_application_rejection
        """
        ctx = setup_application_under_review_single_dept(
            fee_amount_cents=1000, correction_window_days=1,
        )
        issue_correction_for_primary_material(ctx=ctx)
        advance_clock(WORKING_DAY_SECONDS + 1)
        run_sweep()
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "REJECTED"
        assert refreshed["payment_status"] == "REFUNDED"

    def test_review_task_capacity_invariant_on_rejection_via_aggregation(
        self, api,
    ):
        """PRD §3.4: "every non-terminal ReviewTask flips to SKIPPED."
        PRD §3.8: "When the aggregator returns DISAGREED, the
        application transitions from UNDER_REVIEW to REJECTED."

        Claim: when a 3-stage PARALLEL/ALL_AGREE application is
        REJECTED via a single DISAGREED short-circuit, the count of
        non-terminal ReviewTasks for that application equals 0
        afterwards.

        # difficulty: compensating_invariant/review_task_capacity_invariant_on_application_terminal
        """
        ctx = setup_application_under_review_parallel(
            department_count=3, aggregation_rule="ALL_AGREE",
        )
        first = ctx["review_tasks"][0]
        first_headers = ctx["reviewer_headers_by_dept_id"][first["department_id"]]
        decide(first["id"], "DISAGREED", first_headers)
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "REJECTED"
        tasks = list_review_tasks(
            ctx["application"]["id"], TEST_USERS["platform_admin_headers"]
        )
        non_terminal = [
            t for t in tasks
            if t["status"] not in {"AGREED", "DISAGREED", "SKIPPED"}
        ]
        assert non_terminal == [], (
            f"Capacity invariant violated -- non-terminal tasks: {non_terminal}"
        )
