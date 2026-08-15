"""The final compliance letter: posture gates, issuance, the completion
lockdown, voiding back to ACTIVE, and the void compensating cascade that
strips letter readiness."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    certification_entry,
    complete_assignment,
    create_assignment,
    create_assignment_payload,
    create_project,
    create_technician,
    dispatch_assignment,
    get_project,
    get_scope_items,
    issue_letter,
    record_soil_test,
    setup_approved_project,
    setup_dispatched_assignment,
    setup_ready_for_letter,
    soil_scope_item,
    submit_daily_report,
    validate_error,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]
BUILDING_OFFICIAL = TEST_USERS["building_official_headers"]


def _satisfy_item(ctx, tech_id, item_id, work_date, summary):
    asg = create_assignment(ctx["project"]["id"], item_id, tech_id,
                            work_date, "09:00", "10:00")
    dispatch_assignment(asg["id"])
    record_soil_test(asg["id"], tech_id, 118.0)
    complete_assignment(asg["id"], tech_id)
    submit_daily_report(ctx["project"]["id"], tech_id, work_date, [asg["id"]], summary)
    return asg


def _two_item_project(api):
    ctx = setup_approved_project(
        [soil_scope_item(description="pad north"), soil_scope_item(description="pad south")],
        project_overrides={"name": "LetterGate", "permit_number": "P-XED-2"},
    )
    tech = create_technician(certifications=[
        certification_entry("SOIL_COMPACTION", level=2)
    ])
    return ctx, tech


class TestLetterRequiresAllItemsSatisfied:
    def test_letter_rejected_while_scope_item_open(self, api):
        """PRD §3.9: "Otherwise, readiness requires all of: an approved
        revision exists (`current_approved_ssi_id` is not null), every scope
        item of that revision is `SATISFIED`, no discrepancy ticket of the
        project sits in `RAISED` or `RESPONSE_SUBMITTED`, and every `COMPLETED`
        assignment of the project has a non-null `covered_by_dir_id`; when all
        four hold, the posture is `READY_FOR_LETTER`."
        PRD §3.9: "Issuance is the `ProjectManager`'s act and is doubly gated:
        the posture must be exactly `READY_FOR_LETTER` (otherwise
        `ERR_POSTURE_NOT_READY`) and `letter_status` must not already be
        `ISSUED` (otherwise `ERR_LETTER_ALREADY_ISSUED`)."

        Design: Difficulty/cross_entity_state_dependency/letter_requires_all_scope_items_satisfied
        """
        ctx, tech = _two_item_project(api)
        _satisfy_item(ctx, tech["id"], ctx["scope_items"][0]["id"], "2026-05-04",
                      "north pad tested")

        resp = api.issue_letter(ctx["project"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_POSTURE_NOT_READY)
        project = get_project(ctx["project"]["id"])
        assert project["compliance_posture"] == "IN_PROGRESS", (
            "the second item is still OPEN, so readiness cannot hold"
        )
        assert project["letter_status"] == "NONE"

    def test_letter_issues_once_all_items_satisfied(self, api):
        """PRD §3.9: "Issuance is the `ProjectManager`'s act and is doubly
        gated: the posture must be exactly `READY_FOR_LETTER` (otherwise
        `ERR_POSTURE_NOT_READY`) and `letter_status` must not already be
        `ISSUED` (otherwise `ERR_LETTER_ALREADY_ISSUED`). Issuing sets
        `letter_status` to `ISSUED`, stamps `letter_issued_at` from the clock,
        records the caller as `letter_issued_by`, moves the project's `status`
        to `COMPLETED` — which activates the completion gate of §2.10 — and the
        posture becomes `LETTER_ISSUED`."

        Design: Difficulty/cross_entity_state_dependency/letter_requires_all_scope_items_satisfied
        """
        ctx, tech = _two_item_project(api)
        _satisfy_item(ctx, tech["id"], ctx["scope_items"][0]["id"], "2026-05-04",
                      "north pad tested")
        blocked = api.issue_letter(ctx["project"]["id"], PM)
        validate_error(blocked, ApiErrorId.ERR_POSTURE_NOT_READY)

        _satisfy_item(ctx, tech["id"], ctx["scope_items"][1]["id"], "2026-05-05",
                      "south pad tested")
        issued = validate_success(api.issue_letter(ctx["project"]["id"], PM), 200)
        assert issued["letter_status"] == "ISSUED"
        assert issued["status"] == "COMPLETED"
        assert issued["compliance_posture"] == "LETTER_ISSUED"
        assert issued["letter_issued_by"] == PM["X-User-ID"]
        assert issued["letter_issued_at"] is not None


class TestVoidCompensationCascade:
    def test_voiding_conforming_test_reopens_scope_item(self, api):
        """PRD §3.4: "Voiding is a compensating action: the scope item's
        `completed_count` decrements by one, the item reopens to `OPEN` if the
        count falls back below its requirement, and posture is recomputed."

        Design: Difficulty/transitive_cascade/void_conforming_test_compensation_cascade
        """
        ctx = setup_ready_for_letter(
            project_overrides={"name": "Cascade B", "permit_number": "P-CAS-2"}
        )
        voided = validate_success(api.void_field_test(ctx["field_test"]["id"], PM), 200)
        assert voided["status"] == "VOIDED"
        item = get_scope_items(ctx["ssi"]["id"])[0]
        assert item["completed_count"] == 0, "compensating decrement removes the voided test"
        assert item["status"] == "OPEN", "count dropped back below required_count 1"

    def test_voided_test_drops_ready_posture_to_in_progress(self, api):
        """PRD §3.4: "Voiding is a compensating action: the scope item's
        `completed_count` decrements by one, the item reopens to `OPEN` if the
        count falls back below its requirement, and posture is recomputed."
        PRD §3.9: "Otherwise, readiness requires all of: an approved revision
        exists (`current_approved_ssi_id` is not null), every scope item of
        that revision is `SATISFIED`, no discrepancy ticket of the project sits
        in `RAISED` or `RESPONSE_SUBMITTED`, and every `COMPLETED` assignment
        of the project has a non-null `covered_by_dir_id`; when all four hold,
        the posture is `READY_FOR_LETTER`. Failing that, the posture is
        `IN_PROGRESS`."

        Design: Difficulty/transitive_cascade/void_conforming_test_compensation_cascade
        """
        ctx = setup_ready_for_letter(
            project_overrides={"name": "Cascade B", "permit_number": "P-CAS-2"}
        )
        before = get_project(ctx["project"]["id"])
        assert before["compliance_posture"] == "READY_FOR_LETTER"

        validate_success(api.void_field_test(ctx["field_test"]["id"], PM), 200)
        after = get_project(ctx["project"]["id"])
        assert after["compliance_posture"] == "IN_PROGRESS", (
            "the reopened scope item strips letter readiness purely through the "
            "compensation chain"
        )


class TestLetterGates:
    def test_letter_blocked_by_missing_daily_report_coverage(self, api):
        """PRD §3.9: "Otherwise, readiness requires all of: an approved
        revision exists (`current_approved_ssi_id` is not null), every scope
        item of that revision is `SATISFIED`, no discrepancy ticket of the
        project sits in `RAISED` or `RESPONSE_SUBMITTED`, and every `COMPLETED`
        assignment of the project has a non-null `covered_by_dir_id`; when all
        four hold, the posture is `READY_FOR_LETTER`."
        PRD §3.9: "Issuance is the `ProjectManager`'s act and is doubly gated:
        the posture must be exactly `READY_FOR_LETTER` (otherwise
        `ERR_POSTURE_NOT_READY`) and `letter_status` must not already be
        `ISSUED` (otherwise `ERR_LETTER_ALREADY_ISSUED`)."

        Design: Corner/endpoints/letter_blocked_when_dir_coverage_missing
        """
        ctx = setup_dispatched_assignment(
            project_overrides={"name": "NoDIR", "permit_number": "P-EP-3"}
        )
        tech_id = ctx["technician"]["id"]
        record_soil_test(ctx["assignment"]["id"], tech_id, 118.0)
        complete_assignment(ctx["assignment"]["id"], tech_id)
        # Deliberately no daily report: the completed assignment lacks coverage.

        resp = api.issue_letter(ctx["project"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_POSTURE_NOT_READY)
        project = get_project(ctx["project"]["id"])
        assert project["compliance_posture"] == "IN_PROGRESS", (
            "the uncovered completed assignment blocks readiness even though the "
            "scope item is SATISFIED"
        )

    def test_double_issue_letter_rejected(self, api):
        """PRD §3.9: "Issuance is the `ProjectManager`'s act and is doubly
        gated: the posture must be exactly `READY_FOR_LETTER` (otherwise
        `ERR_POSTURE_NOT_READY`) and `letter_status` must not already be
        `ISSUED` (otherwise `ERR_LETTER_ALREADY_ISSUED`)."

        Design: Corner/endpoints/double_issue_letter_rejected
        """
        ctx = setup_ready_for_letter(
            project_overrides={"name": "DoubleIssue", "permit_number": "P-EP-6"}
        )
        issue_letter(ctx["project"]["id"])
        resp = api.issue_letter(ctx["project"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_LETTER_ALREADY_ISSUED)

    def test_mutations_frozen_after_letter_issued(self, api):
        """PRD §2.10: "A project whose final compliance letter has been issued
        is closed for business: every mutation attempted under a project in
        `COMPLETED` status — submitting a revision, approving one, dispatching
        an assignment, recording results — is rejected with
        `ERR_PROJECT_COMPLETED`."

        Design: Corner/endpoints/mutation_blocked_after_project_completed
        """
        ctx = setup_ready_for_letter(
            project_overrides={"name": "Frozen", "permit_number": "P-EP-7"}
        )
        issue_letter(ctx["project"]["id"])
        assert get_project(ctx["project"]["id"])["status"] == "COMPLETED"

        resp = api.create_assignment(
            create_assignment_payload(
                ctx["project"]["id"], ctx["scope_items"][0]["id"],
                ctx["technician"]["id"], "2026-05-06", "09:00", "10:00",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_COMPLETED)


class TestVoidLetterCycle:
    def test_voided_letter_returns_project_to_active_and_reissues(self, api):
        """PRD §3.9: "The `BuildingOfficial` may void an issued letter by
        supplying a `void_reason`, which is stored as `letter_void_reason`;
        voiding requires `letter_status` to be `ISSUED` (otherwise
        `ERR_NO_LETTER_TO_VOID`). The letter flips to `VOIDED`, the project
        returns to `ACTIVE`, and the posture is recomputed from the current
        evidence — landing back at `READY_FOR_LETTER` or lower — leaving the
        project open for remediation and a possible re-issue."

        Design: Corner/endpoints/void_letter_cycles_project_back_to_active
        """
        ctx = setup_ready_for_letter(
            project_overrides={"name": "VoidCycle", "permit_number": "P-EP-4"}
        )
        issue_letter(ctx["project"]["id"])
        assert get_project(ctx["project"]["id"])["letter_status"] == "ISSUED"

        voided = validate_success(
            api.void_letter(
                ctx["project"]["id"],
                {"void_reason": "late NCR discovered by audit"},
                BUILDING_OFFICIAL,
            ),
            200,
        )
        assert voided["status"] == "ACTIVE"
        assert voided["letter_status"] == "VOIDED"
        assert voided["letter_void_reason"] == "late NCR discovered by audit"

        project = get_project(ctx["project"]["id"])
        assert project["compliance_posture"] == "READY_FOR_LETTER", (
            "all readiness gates still hold, so the recompute lands at READY_FOR_LETTER"
        )
        reissued = validate_success(api.issue_letter(ctx["project"]["id"], PM), 200)
        assert reissued["letter_status"] == "ISSUED", "the cycle closes with a re-issue"

    def test_void_letter_without_issued_letter_rejected(self, api):
        """PRD §3.9: "The `BuildingOfficial` may void an issued letter by
        supplying a `void_reason`, which is stored as `letter_void_reason`;
        voiding requires `letter_status` to be `ISSUED` (otherwise
        `ERR_NO_LETTER_TO_VOID`)."

        Design: Corner/endpoints/void_letter_when_none_issued_rejected
        """
        project = create_project(name="NoLetter", permit_number="P-EP-5")
        resp = api.void_letter(
            project["id"], {"void_reason": "premature"}, BUILDING_OFFICIAL
        )
        validate_error(resp, ApiErrorId.ERR_NO_LETTER_TO_VOID)
