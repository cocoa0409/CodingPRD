"""Intervention notice escalation, resolution guards, SOD, and corrective-plan
deadlines (PRD §2.8, §3.5)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, CLOCK,
    create_open_school, create_intervention, create_issued_notice,
    create_corrective_plan_payload, set_clock, assert_same_instant,
    make_staff_headers, make_board_headers, make_school_operator_headers,
    api_client,
)

STAFF = make_staff_headers("staff_1")


class TestNoticeEscalateChainToTerminalLevel:
    def test_escalation_chain_notice_probation_revocation_review_terminal(self, api):
        """PRD §3.5: "Escalation moves the notice `ISSUED` → `ESCALATED` and
        spawns its successor one level up — a `NOTICE` begets a `PROBATION`, a
        `PROBATION` begets a `REVOCATION_REVIEW` — created directly in `ISSUED`
        status with the same domain, the escalating board member as
        `issued_by_user_id`, and a fresh thirty-day `corrective_due_date`."
        PRD §3.5: "A `BoardMember` escalates an `ISSUED` notice; a notice in
        any other status, and a notice already at `REVOCATION_REVIEW` with
        nowhere higher to go, are both rejected with
        `ERR_NOTICE_INVALID_STATE`."

        Design: Corner/state_machines/sm_notice_escalate_chain_to_terminal_level
        """
        ctx = create_open_school(school_name="SM Escalation Academy",
                                 applicant_id="applicant_s7")
        n1 = create_issued_notice(ctx["school"]["id"], level="NOTICE",
                                  domain="OPERATIONAL",
                                  reason="Late enrollment report",
                                  issuer_id="staff_a")
        first = validate_success(
            api.escalate_intervention(n1["id"], make_board_headers("board_1")), 200)
        assert first["status"] == "ESCALATED"
        assert first["successor_notice_id"] is not None
        n2 = validate_success(
            api.get_intervention(first["successor_notice_id"], STAFF), 200)
        assert n2["level"] == "PROBATION"
        assert n2["status"] == "ISSUED"
        assert n2["domain"] == "OPERATIONAL"
        assert n2["issued_by_user_id"] == "board_1"

        second = validate_success(
            api.escalate_intervention(n2["id"], make_board_headers("board_1")), 200)
        n3 = validate_success(
            api.get_intervention(second["successor_notice_id"], STAFF), 200)
        assert n3["level"] == "REVOCATION_REVIEW"
        assert n3["status"] == "ISSUED"

        res = api.escalate_intervention(n3["id"], make_board_headers("board_1"))
        validate_error(res, ApiErrorId.ERR_NOTICE_INVALID_STATE, expected_status=409)


class TestNoticeResolutionRules:
    def test_notice_level_resolves_without_plan(self, api):
        """PRD §3.5: "The resolver must differ from the notice's
        `issued_by_user_id` — the segregation rule of §2.8, rejected as
        `ERR_SOD_NOTICE_SELF_RESOLVE` — and a notice at `PROBATION` or
        `REVOCATION_REVIEW` may not resolve until an `ACCEPTED` corrective plan
        exists for it (`ERR_NO_ACCEPTED_CORRECTIVE_PLAN`); a plain `NOTICE`
        resolves without one."
        PRD §3.5: "Resolution records the caller as `resolved_by_user_id` and
        lifts the school's standing in the notice's domain exactly one step"

        Design: Corner/state_machines/sm_notice_level_resolves_without_plan
        """
        ctx = create_open_school(school_name="SM Resolve Academy",
                                 applicant_id="applicant_s8")
        notice = create_issued_notice(ctx["school"]["id"], level="NOTICE",
                                      domain="COMPLIANCE",
                                      reason="Board minutes late",
                                      issuer_id="staff_a")
        resolved = validate_success(
            api.resolve_intervention(notice["id"], make_staff_headers("staff_b")), 200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_by_user_id"] == "staff_b"
        # COMPLIANCE is not one of the three standing dimensions.
        school = validate_success(api.get_school(ctx["school"]["id"], STAFF), 200)
        assert school["academic_standing"] == "GOOD"
        assert school["financial_standing"] == "GOOD"
        assert school["operational_standing"] == "GOOD"

    def test_probation_resolve_requires_accepted_plan(self, api):
        """PRD §3.5: "a notice at `PROBATION` or `REVOCATION_REVIEW` may not
        resolve until an `ACCEPTED` corrective plan exists for it
        (`ERR_NO_ACCEPTED_CORRECTIVE_PLAN`); a plain `NOTICE` resolves without
        one."

        Design: Corner/state_machines/sm_probation_resolve_requires_accepted_plan
        """
        ctx = create_open_school(school_name="SM Probation Academy",
                                 applicant_id="applicant_s9")
        notice = create_issued_notice(ctx["school"]["id"], level="PROBATION",
                                      domain="FINANCIAL",
                                      reason="Audit findings unresolved",
                                      issuer_id="staff_a")
        # Resolver differs from issuer (SOD satisfied); no plan exists.
        res = api.resolve_intervention(notice["id"], make_staff_headers("staff_b"))
        validate_error(res, ApiErrorId.ERR_NO_ACCEPTED_CORRECTIVE_PLAN,
                       expected_status=409)
        current = validate_success(api.get_intervention(notice["id"], STAFF), 200)
        assert current["status"] == "ISSUED"
        assert current["resolved_by_user_id"] is None

    def test_issuer_cannot_resolve_own_notice(self, api):
        """PRD §2.8: "The staff member who issued an intervention notice may
        not resolve it: the resolver's `X-User-ID` must differ from the
        notice's `issued_by_user_id`, else `ERR_SOD_NOTICE_SELF_RESOLVE`
        (HTTP 403)."

        Design: Corner/state_machines/sm_notice_self_resolve_sod_rejected
        """
        ctx = create_open_school(school_name="SM SOD Resolve Academy",
                                 applicant_id="applicant_s10")
        notice = create_issued_notice(ctx["school"]["id"], level="NOTICE",
                                      domain="COMPLIANCE",
                                      reason="Missing policy attestation",
                                      issuer_id="staff_a")
        res = api.resolve_intervention(notice["id"], make_staff_headers("staff_a"))
        validate_error(res, ApiErrorId.ERR_SOD_NOTICE_SELF_RESOLVE,
                       expected_status=403)
        current = validate_success(api.get_intervention(notice["id"], STAFF), 200)
        assert current["status"] == "ISSUED"


class TestCorrectivePlanOverdueRejected:
    def test_plan_submitted_after_due_date_rejected(self, api):
        """PRD §3.5: "Submission also requires the notice to be `ISSUED`
        (`ERR_NOTICE_INVALID_STATE`), the clock to read at or before the
        notice's `corrective_due_date` (`ERR_CORRECTIVE_PLAN_OVERDUE`), and no
        other plan in `SUBMITTED` or `ACCEPTED` to exist for the notice
        (`ERR_PLAN_ALREADY_ACTIVE`)"
        PRD §3.5: "Issuing a notice (`DRAFT` → `ISSUED`, with
        `ERR_NOTICE_INVALID_STATE` for any other status) stamps the caller as
        `issued_by_user_id` and sets the `corrective_due_date` thirty days out
        from the logical clock."

        Design: Corner/validations/val_corrective_plan_overdue_rejected
        """
        ctx = create_open_school(school_name="Val Overdue Academy",
                                 applicant_id="applicant_v7")
        notice = create_issued_notice(ctx["school"]["id"], level="PROBATION",
                                      domain="ACADEMIC",
                                      reason="Math floor breached",
                                      issuer_id="staff_a")
        # Issued at the default clock 2026-05-01 -> due 2026-05-31.
        assert_same_instant(notice["corrective_due_date"], "2026-05-31T00:00:00Z")
        set_clock(CLOCK["PLAN_OVERDUE"])
        res = api.create_corrective_plan(
            notice["id"],
            create_corrective_plan_payload(
                plan_text="Late plan",
                expected_intervention_version=notice["version"]),
            make_school_operator_headers(ctx["school"]["id"]))
        validate_error(res, ApiErrorId.ERR_CORRECTIVE_PLAN_OVERDUE, expected_status=422)
        plans = validate_success(api.list_corrective_plans(notice["id"], STAFF), 200)
        assert plans == []
