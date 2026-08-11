"""Grant suspension cycle, freeze cascade, and cross-entity state gating
(PRD §3.8, §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_engagement_in_conducted,
    edit_report,
    file_finding,
    post_activity_in_period,
    resolve_finding,
    set_clock,
    setup_active_grant,
    start_report,
    suspend_grant_with_material_weakness,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestGrantSuspensionCycle:
    def test_grant_suspension_cycle_suspend_on_material_weakness(self, api):
        """PRD §3.8: "Filing a `MATERIAL_WEAKNESS` finding against an engagement
        of an `ACTIVE` grant has an immediate cross-aggregate cascade: the grant
        transitions automatically from `ACTIVE` to `SUSPENDED`."

        Design: Difficulty/non_linear_state_machine/grant_suspension_cycle
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        engagement = create_engagement_in_conducted(gid)

        file_finding(engagement["id"], severity="MATERIAL_WEAKNESS",
                     description="mw")
        grant = validate_success(api.get_grant(gid, OFFICER))
        assert grant["status"] == "SUSPENDED", (
            f"MATERIAL_WEAKNESS creation must suspend the grant, got "
            f"{grant['status']}"
        )

    def test_grant_suspension_cycle_reactivation_on_last_resolve(self, api):
        """PRD §3.8: "Resolution of a `MATERIAL_WEAKNESS` finding has the
        inverse cascade: if no other `OPEN` or `RESPONSE_SUBMITTED`
        `MATERIAL_WEAKNESS` finding remains on any engagement of the grant, the
        grant transitions automatically from `SUSPENDED` back to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/grant_suspension_cycle
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        _engagement, finding = suspend_grant_with_material_weakness(gid)
        assert validate_success(api.get_grant(gid, OFFICER))["status"] == "SUSPENDED"

        resolve_finding(finding["id"])
        grant = validate_success(api.get_grant(gid, OFFICER))
        assert grant["status"] == "ACTIVE", (
            f"resolving the last open MATERIAL_WEAKNESS must reactivate the "
            f"grant, got {grant['status']}"
        )


class TestMaterialWeaknessFreezeChain:
    def test_material_weakness_freeze_chain(self, api):
        """PRD §3.8: "the grant transitions automatically from `ACTIVE` to
        `SUSPENDED`, every report of that grant in `DRAFT` or `RETURNED` has
        `frozen` set to `true` (blocking both edits and submission), and every
        `VarianceExplanation` in `DRAFTED` on those reports transitions to
        `LOCKED`."

        Design: Difficulty/transitive_cascade/material_weakness_freeze_chain
        """
        ctx = setup_active_grant(
            lines=[{"category": "PERSONNEL", "budgeted_cents": 50_000_000}],
            variance_threshold_pct=3.0,
        )
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        fund = ctx["fund"]
        r1 = ctx["reports"][0]

        set_clock("2026-06-15T00:00:00Z")
        start_report(r1["id"])
        # 13000000 vs 12500000 period budget -> +4.00% >= 3.0 threshold.
        post_activity_in_period(gid, l1["id"], fund["id"], 13_000_000, "2026-06-20")
        ve = validate_success(api.create_variance_explanation(
            r1["id"],
            {"budget_line_id": l1["id"], "explanation_text": "hiring surge"},
            OFFICER,
        ), expected_status=201)
        assert ve["status"] == "DRAFTED"

        engagement = create_engagement_in_conducted(
            gid, engagement_type="FINANCIAL_AUDIT",
        )
        file_finding(engagement["id"], severity="MATERIAL_WEAKNESS",
                     description="mw")

        grant = validate_success(api.get_grant(gid, OFFICER))
        assert grant["status"] == "SUSPENDED"

        report = validate_success(api.get_report(r1["id"], OFFICER))
        assert report["frozen"] is True, (
            "suspension must freeze the DRAFT report"
        )

        ves, _ = validate_paginated(
            api.list_variance_explanations(r1["id"], OFFICER)
        )
        assert ves[0]["status"] == "LOCKED", (
            f"the DRAFTED explanation must be LOCKED by the freeze cascade, "
            f"got {ves[0]['status']}"
        )

    def test_frozen_report_rejects_edit(self, api):
        """PRD §3.4: "Editing is only possible while the report is in `DRAFT`
        and not frozen; an edit against a report in any other status, or a
        frozen one, is rejected with `ERR_REPORT_NOT_EDITABLE` (HTTP 409)."

        Design: Corner/validations/report_frozen_edit_rejected
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        r1 = ctx["reports"][0]
        set_clock("2026-06-15T00:00:00Z")
        start_report(r1["id"])
        suspend_grant_with_material_weakness(gid)

        resp = api.update_report(r1["id"], {"narrative_draft": "N"}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_EDITABLE)


class TestReportSubmitGatedOnGrantSuspension:
    def test_submit_blocked_while_suspended(self, api):
        """PRD §3.8: "While a grant is `SUSPENDED`, report submit and revise,
        expense create and post, match documentation, and modification submit
        are all rejected with `ERR_GRANT_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/report_submit_gated_on_grant_suspension
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        r1 = ctx["reports"][0]
        set_clock("2026-06-15T00:00:00Z")
        start_report(r1["id"])
        edit_report(r1["id"])
        _engagement, _finding = suspend_grant_with_material_weakness(
            gid, engagement_type="DESK_REVIEW",
        )

        resp = api.submit_report(r1["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_GRANT_SUSPENDED)

    def test_submit_succeeds_after_reactivation(self, api):
        """PRD §3.8: "if no other `OPEN` or `RESPONSE_SUBMITTED`
        `MATERIAL_WEAKNESS` finding remains on any engagement of the grant, the
        grant transitions automatically from `SUSPENDED` back to `ACTIVE`, every
        frozen report of the grant has `frozen` cleared to `false`, and every
        `VarianceExplanation` in `LOCKED` transitions back to `DRAFTED`."
        PRD §3.4: "Submitting the report to the funder is the gated transition,
        moving `DRAFT` to `SUBMITTED`."

        Design: Difficulty/cross_entity_state_dependency/report_submit_gated_on_grant_suspension
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        r1 = ctx["reports"][0]
        set_clock("2026-06-15T00:00:00Z")
        start_report(r1["id"])
        edit_report(r1["id"])
        _engagement, finding = suspend_grant_with_material_weakness(
            gid, engagement_type="DESK_REVIEW",
        )

        resolve_finding(finding["id"])
        assert validate_success(api.get_grant(gid, OFFICER))["status"] == "ACTIVE"
        report = validate_success(api.get_report(r1["id"], OFFICER))
        assert report["frozen"] is False

        data = validate_success(api.submit_report(r1["id"], OFFICER))
        assert data["status"] == "SUBMITTED"
