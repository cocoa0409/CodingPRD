"""Corner: state_machines — invalid transitions, terminal lockdown, valid
transitions, side-effect executions, precondition enforcements (§1.9
state_machines)."""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_risk, assert_control, assert_plan,
    create_category, create_risk, create_identified_risk,
    create_assessed_risk, create_residual_assessed_risk,
    create_active_control, create_active_mapping,
    create_approved_appetite, create_proposed_plan, approve_plan,
    create_in_progress_plan, create_approved_plan, start_plan,
    add_action, done_action, cancel_plan,
    create_active_kri, observe_kri, advance_clock, get_plan,
    create_emerging_risk, validate_emerging_risk, get_risk, get_risk_version,
    create_inherent_assessment, create_residual_assessment,
    create_report, finalize_report,
    make_risk_owner_headers, make_risk_manager_headers,
    make_control_owner_headers, make_board_reporter_headers,
    make_internal_auditor_headers,
    USER_RISK_OWNER, USER_RISK_MANAGER, USER_RISK_MANAGER_2,
    USER_CONTROL_OWNER, USER_BOARD_REPORTER, USER_INTERNAL_AUDITOR,
)


def _parse_instant(value: str):
    """Parse an ISO 8601 UTC timestamp to an aware datetime for
    representation-agnostic instant comparison."""
    from datetime import datetime, timezone
    t = value.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class TestRiskInvalidTransitions:
    def test_submit_from_identified_rejected(self):
        """PRD §2.8 #7: "the requested transition exists from the entity's
        current status... (`ERR_INVALID_STATE`...)".
        PRD §3.2: "Submission moves a risk `DRAFT` → `IDENTIFIED`".

        Design: Corner/state_machines/risk_submit_from_identified_returns_invalid_state
        """
        risk = create_identified_risk()
        res = api_client.submit_risk(
            risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_invalid_transition_does_not_bump_version(self):
        """PRD §3.2: "Submission, like every risk transition described below,
        increments the risk's `version` by 1." — a rejected transition performs
        no mutation, so version does not advance.

        Design: Corner/state_machines/risk_submit_from_identified_returns_invalid_state
        """
        risk = create_identified_risk()
        v_pre = risk["version"]
        api_client.submit_risk(risk["id"], make_risk_owner_headers(USER_RISK_OWNER))
        after = get_risk(risk["id"])
        assert after["version"] == v_pre


class TestResidualInIdentifiedRejected:
    def test_residual_before_inherent_fails(self):
        """PRD §3.2: "A `RESIDUAL` assessment never changes the risk's lifecycle
        status: it is a self-transition permitted from `ASSESSED`, `TREATMENT`,
        `MONITORING`, and `REASSESSMENT`, and rejected from `DRAFT`,
        `IDENTIFIED`, or `CLOSED` with `ERR_ASSESSMENT_KIND_NOT_ALLOWED`."

        Design: Corner/state_machines/residual_assessment_in_identified_returns_kind_not_allowed
        """
        risk = create_identified_risk()
        v = risk["version"]
        res = api_client.create_assessment(
            risk["id"],
            {"kind": "RESIDUAL", "expected_risk_version": v},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        validate_error(res, ApiErrorId.ERR_ASSESSMENT_KIND_NOT_ALLOWED.value)


class TestControlTerminalLockdown:
    def test_activate_from_retired_rejected(self):
        """PRD §3.3: "Activation moves it `PROPOSED` → `ACTIVE`"; "Retirement
        moves `ACTIVE` → `RETIRED`." RETIRED is terminal — no outgoing
        transitions are defined.
        PRD §2.8 #7: "the requested transition exists from the entity's current
        status... (`ERR_INVALID_STATE`...)".

        Design: Corner/state_machines/control_retired_terminal_lockdown
        """
        ctl = create_active_control(name="TC", effectiveness_pct=0.5)
        api_client.retire_control(
            ctl["id"], make_control_owner_headers(USER_CONTROL_OWNER),
        )
        res = api_client.activate_control(
            ctl["id"], make_control_owner_headers(USER_CONTROL_OWNER),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_status_remains_retired_after_rejected_transition(self):
        """PRD §3.3: "Retirement moves `ACTIVE` → `RETIRED`." No transitions
        out of RETIRED exist.

        Design: Corner/state_machines/control_retired_terminal_lockdown
        """
        ctl = create_active_control(name="TC", effectiveness_pct=0.5)
        api_client.retire_control(
            ctl["id"], make_control_owner_headers(USER_CONTROL_OWNER),
        )
        api_client.activate_control(
            ctl["id"], make_control_owner_headers(USER_CONTROL_OWNER),
        )
        api_client.review_control(
            ctl["id"], make_control_owner_headers(USER_CONTROL_OWNER),
        )
        res = api_client.get_control(
            ctl["id"], make_control_owner_headers(USER_CONTROL_OWNER),
        )
        assert validate_success(res, 200)["status"] == "RETIRED"


class TestPlanOverdueAndExtend:
    def test_clock_sweep_flips_in_progress_to_overdue(self):
        """PRD §2.4: "every treatment plan in `IN_PROGRESS` whose `due_date` is
        now in the past moves to `OVERDUE`."

        Design: Corner/state_machines/plan_overdue_sweep_and_extend_cycle
        """
        setup = create_residual_assessed_risk(treatment_budget_cents=500_000)
        plan = create_in_progress_plan(
            setup["id"], budget_cents=100_000,
            due_date="2026-08-10T00:00:00Z",
        )
        advance_clock("2026-08-15T00:00:00Z")
        got = validate_success(
            api_client.get_treatment_plan(
                plan["id"], make_risk_owner_headers(USER_RISK_OWNER),
            ), 200,
        )
        assert got["status"] == "OVERDUE"

    def test_extend_returns_to_in_progress_and_increments(self):
        """PRD §3.5: "Extending moves `OVERDUE` → `IN_PROGRESS` under two
        guards... A successful extension sets `due_date` to `new_due_date` and
        increments `extension_count` by 1."

        Design: Corner/state_machines/plan_overdue_sweep_and_extend_cycle
        """
        setup = create_residual_assessed_risk(treatment_budget_cents=500_000)
        plan = create_in_progress_plan(
            setup["id"], budget_cents=100_000,
            due_date="2026-08-10T00:00:00Z",
        )
        advance_clock("2026-08-15T00:00:00Z")
        res = api_client.extend_treatment_plan(
            plan["id"], {"new_due_date": "2026-09-30T00:00:00Z"},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        updated = validate_success(res, 200)
        assert updated["status"] == "IN_PROGRESS"
        assert updated["extension_count"] == 1
        # PRD §3.5 pins the instant ("sets `due_date` to `new_due_date`"),
        # not the serialization format; compare instants so a conformant
        # 3-fractional-digit rendering ("...T00:00:00.000Z", §2.5) passes.
        assert _parse_instant(updated["due_date"]) == _parse_instant(
            "2026-09-30T00:00:00Z")


class TestPlanExtensionLimit:
    def test_fourth_extension_rejected(self):
        """PRD §3.5: "the plan's `extension_count` must still be below 3,
        permitting at most three extensions and rejecting a fourth with
        `ERR_PLAN_EXTENSION_LIMIT`".

        Design: Corner/state_machines/plan_extension_limit_fourth_extension_rejected
        """
        risk = create_residual_assessed_risk(treatment_budget_cents=500_000,
                                               likelihood=2, impact=2)
        plan = create_in_progress_plan(
            risk["id"], budget_cents=50_000,
            due_date="2026-08-05T00:00:00Z",
        )
        # 3 extension cycles
        for clock, new_due in [
            ("2026-08-06T00:00:00Z", "2026-08-10T00:00:00Z"),
            ("2026-08-11T00:00:00Z", "2026-08-15T00:00:00Z"),
            ("2026-08-16T00:00:00Z", "2026-08-20T00:00:00Z"),
        ]:
            advance_clock(clock)
            res = api_client.extend_treatment_plan(
                plan["id"], {"new_due_date": new_due},
                make_risk_owner_headers(USER_RISK_OWNER),
            )
            validate_success(res, 200)
        advance_clock("2026-08-21T00:00:00Z")
        # 4th extension must fail
        res = api_client.extend_treatment_plan(
            plan["id"], {"new_due_date": "2026-09-01T00:00:00Z"},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        validate_error(res, ApiErrorId.ERR_PLAN_EXTENSION_LIMIT.value)

    def test_extension_count_stays_at_max(self):
        """PRD §3.5: "permitting at most three extensions and rejecting a
        fourth with `ERR_PLAN_EXTENSION_LIMIT`".

        Design: Corner/state_machines/plan_extension_limit_fourth_extension_rejected
        """
        risk = create_residual_assessed_risk(treatment_budget_cents=500_000,
                                               likelihood=2, impact=2)
        plan = create_in_progress_plan(
            risk["id"], budget_cents=50_000,
            due_date="2026-08-05T00:00:00Z",
        )
        for clock, new_due in [
            ("2026-08-06T00:00:00Z", "2026-08-10T00:00:00Z"),
            ("2026-08-11T00:00:00Z", "2026-08-15T00:00:00Z"),
            ("2026-08-16T00:00:00Z", "2026-08-20T00:00:00Z"),
        ]:
            advance_clock(clock)
            api_client.extend_treatment_plan(
                plan["id"], {"new_due_date": new_due},
                make_risk_owner_headers(USER_RISK_OWNER),
            )
        advance_clock("2026-08-21T00:00:00Z")
        api_client.extend_treatment_plan(
            plan["id"], {"new_due_date": "2026-09-01T00:00:00Z"},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        after = validate_success(
            api_client.get_treatment_plan(
                plan["id"], make_risk_owner_headers(USER_RISK_OWNER),
            ), 200,
        )
        assert after["extension_count"] == 3
        assert after["status"] == "OVERDUE"


class TestAcceptedBreachReopens:
    def test_accepted_breach_reopens_at_review_by(self):
        """PRD §3.4: "Once the logical clock reaches or passes `review_by`, an
        `ACCEPTED` breach automatically re-opens to `OPEN`".

        Design: Corner/state_machines/breach_accepted_reopens_after_review_by
        """
        setup = self._build_accepted_breach()
        advance_clock("2026-08-20T00:00:00Z")
        res = api_client.get_tolerance_breach(
            setup["breach_id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        assert validate_success(res, 200)["status"] == "OPEN"

    def _build_accepted_breach(self):
        """Category with appetite tolerance 5 cap 20; risk inherent 20 (no
        controls), RESIDUAL assessed -> residual 20 >= 5 -> OPEN breach;
        acknowledge, accept with review_by 2026-08-20."""
        cat = create_category(name="BR")
        create_approved_appetite(
            cat["id"], tolerance_score=5, acceptance_cap_score=20,
        )
        risk = create_assessed_risk(
            category_id=cat["id"], likelihood=4, impact=5,
        )
        # No controls → residual = inherent = 20 → breach fires on RESIDUAL
        create_residual_assessment(risk["id"])
        breaches_res = api_client.list_risk_tolerance_breaches(
            risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        breaches = validate_success(breaches_res, 200)
        assert len(breaches) == 1
        bid = breaches[0]["id"]
        api_client.acknowledge_breach(bid, make_risk_owner_headers(USER_RISK_OWNER))
        res = api_client.accept_breach(
            bid,
            {"rationale": "board waiver", "review_by": "2026-08-20T00:00:00Z"},
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_success(res, 200)
        return {"risk_id": risk["id"], "breach_id": bid}


class TestEmergingPromotion:
    def test_promote_creates_linked_risk_draft(self):
        """PRD §3.7: "Promotion materializes the threat on the register: a new
        Risk is created in `DRAFT` status with its `category_id` and `title`
        copied from the emerging risk, its `owner_user_id` taken from the
        promotion payload, and its `source_emerging_risk_id` set to the
        promoted emerging risk's `id`."

        Design: Corner/state_machines/emerging_promote_creates_linked_risk
        """
        cat = create_category(name="EM")
        er = create_emerging_risk(
            cat["id"], title="AI regulation shock",
            scenario_severity=4, scenario_probability=3,
        )
        assert er["scenario_score"] == 12
        validate_emerging_risk(er["id"])
        res = api_client.promote_emerging_risk(
            er["id"], {"owner_user_id": USER_RISK_OWNER},
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        new_risk = validate_success(res, 201)
        assert new_risk["status"] == "DRAFT"
        assert new_risk["source_emerging_risk_id"] == er["id"]

    def test_promoted_risk_discoverable_via_nested_list(self):
        """PRD §3.7: "An emerging risk's promoted-from risks can be listed,
        and the list holds at most one entry."

        Design: Corner/state_machines/emerging_promote_creates_linked_risk
        """
        cat = create_category(name="EM")
        er = create_emerging_risk(
            cat["id"], title="AI regulation shock",
            scenario_severity=4, scenario_probability=3,
        )
        validate_emerging_risk(er["id"])
        res = api_client.promote_emerging_risk(
            er["id"], {"owner_user_id": USER_RISK_OWNER},
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        new_risk = validate_success(res, 201)
        list_res = api_client.list_emerging_risks_promoted_risks(
            er["id"], make_internal_auditor_headers(USER_INTERNAL_AUDITOR),
        )
        risks = validate_success(list_res, 200)
        assert len(risks) == 1
        assert risks[0]["id"] == new_risk["id"]


class TestReportDraftSupersede:
    def test_overlapping_draft_auto_cancels_older(self):
        """PRD §3.8: "Creation also supersedes stale drafts: any older `DRAFT`
        report whose closed period overlaps the new report's closed period is
        automatically moved to `CANCELLED`".

        Design: Corner/state_machines/report_draft_superseded_by_new_overlapping_draft
        """
        rep_old = create_report(
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-31T00:00:00Z",
            variant="PROVISIONAL",
        )
        rep_new = create_report(
            period_start="2026-08-15T00:00:00Z",
            period_end="2026-09-15T00:00:00Z",
            variant="FINAL",
        )
        old_after = validate_success(
            api_client.get_report(
                rep_old["id"], make_board_reporter_headers(USER_BOARD_REPORTER),
            ), 200,
        )
        assert old_after["status"] == "CANCELLED"

    def test_superseding_draft_remains_draft(self):
        """PRD §3.8: "The superseding draft is always created successfully".

        Design: Corner/state_machines/report_draft_superseded_by_new_overlapping_draft
        """
        create_report(
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-31T00:00:00Z",
            variant="PROVISIONAL",
        )
        rep_new = create_report(
            period_start="2026-08-15T00:00:00Z",
            period_end="2026-09-15T00:00:00Z",
            variant="FINAL",
        )
        assert rep_new["status"] == "DRAFT"


class TestRiskCloseBlockedByPlan:
    def test_close_with_proposed_plan_rejected(self):
        """PRD §3.2: "Closing a risk is possible from `IDENTIFIED`, `ASSESSED`,
        `MONITORING`, or `REASSESSMENT` — never from `DRAFT` or `TREATMENT` —
        and is guarded by the same two conditions as monitoring: no treatment
        plan in `PROPOSED`, `APPROVED`, `IN_PROGRESS`, or `OVERDUE` may exist
        for the risk (`ERR_ACTIVE_PLAN_BLOCKING`)".

        Design: Corner/state_machines/risk_close_blocked_by_active_plan
        """
        risk = create_assessed_risk(likelihood=2, impact=2,
                                      treatment_budget_cents=100_000)
        create_proposed_plan(risk["id"], budget_cents=10_000)
        res = api_client.close_risk(
            risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        validate_error(res, ApiErrorId.ERR_ACTIVE_PLAN_BLOCKING.value)

    def test_rejected_close_leaves_status_unchanged(self):
        """PRD §3.2: "Closing a risk is possible from `IDENTIFIED`, `ASSESSED`,
        `MONITORING`, or `REASSESSMENT`".

        Design: Corner/state_machines/risk_close_blocked_by_active_plan
        """
        risk = create_assessed_risk(likelihood=2, impact=2,
                                      treatment_budget_cents=100_000)
        create_proposed_plan(risk["id"], budget_cents=10_000)
        api_client.close_risk(risk["id"], make_risk_owner_headers(USER_RISK_OWNER))
        after = get_risk(risk["id"])
        assert after["status"] == "ASSESSED"


class TestMappingApproveBumpsRiskVersion:
    def test_risk_version_increments_on_mapping_approve(self):
        """PRD §3.3: "Approving a mapping moves it `PROPOSED` → `ACTIVE`,
        increments `mapped_active_count` by 1, increments the control's
        `version` by 1, and — when the risk's inherent score is present —
        recomputes the risk's residual score and runs appetite-breach
        evaluation, incrementing the risk's `version` by 1."

        Design: Corner/state_machines/mapping_approve_bumps_risk_version
        """
        risk = create_assessed_risk(likelihood=3, impact=3)
        ctl = create_active_control(name="C", effectiveness_pct=0.5)
        from test_helpers import create_proposed_mapping
        m = create_proposed_mapping(risk["id"], ctl["id"], coverage_weight=0.5)
        v_pre = get_risk_version(risk["id"])
        res = api_client.approve_mapping(
            m["id"], make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_success(res, 200)
        after = get_risk(risk["id"])
        assert after["version"] == v_pre + 1

    def test_mapping_status_becomes_active(self):
        """PRD §3.3: "Approving a mapping moves it `PROPOSED` → `ACTIVE`".

        Design: Corner/state_machines/mapping_approve_bumps_risk_version
        """
        risk = create_assessed_risk(likelihood=3, impact=3)
        ctl = create_active_control(name="C", effectiveness_pct=0.5)
        from test_helpers import create_proposed_mapping
        m = create_proposed_mapping(risk["id"], ctl["id"], coverage_weight=0.5)
        res = api_client.approve_mapping(
            m["id"], make_risk_manager_headers(USER_RISK_MANAGER),
        )
        assert validate_success(res, 200)["status"] == "ACTIVE"
