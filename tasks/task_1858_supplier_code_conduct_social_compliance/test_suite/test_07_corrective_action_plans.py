"""Corrective action plans: review/resubmit and verification cycles."""
from test_helpers import (
    OFFICER,
    ApiErrorId,
    cap_action,
    cap_full_pass_cycle,
    create_cap,
    create_cap_payload,
    file_grievance,
    get_cap,
    get_finding,
    get_scorecard,
    get_supplier,
    make_auditor_headers,
    make_supplier_contact_headers,
    record_finding,
    request_cap_verification,
    resubmit_cap,
    review_cap,
    setup_in_progress_audit,
    validate_error,
    validate_paginated,
    verify_cap,
    create_facility,
    create_auditor,
    create_supplier,
    schedule_audit,
    begin_audit,
    create_code_version,
    acknowledge_code,
)


def cap_on_major_finding(supplier_name="Foxtrot Hardlines", sector="HARDLINES",
                         facility_name="Reno Warehouse"):
    """IN_PROGRESS audit with one OPEN MAJOR finding and its SUBMITTED plan;
    a second auditor stands by for independent verification."""
    ctx = setup_in_progress_audit(supplier_name=supplier_name, sector=sector,
                                  facility_name=facility_name)
    finding = record_finding(
        ctx["audit"]["id"], ctx["auditor"]["id"], classification="MAJOR",
        category="HEALTH_SAFETY", description="Machine guards missing",
    )
    cap = create_cap(finding["id"], ctx["supplier"]["id"])
    ctx["finding"] = finding
    ctx["cap"] = cap
    return ctx


class TestCapCycles:
    def test_cap_reject_resubmit_cycle_statuses(self, api):
        """PRD §3.5: "`REJECT` moves it `SUBMITTED → REJECTED` and requires a
        `rejection_reason` in the payload (`ERR_INVALID_REQUEST`), which is
        stored on the plan."
        PRD §3.5: "the plan's `actions` are replaced wholesale with the revised
        payload and it returns to `SUBMITTED`. This reject/resubmit cycle may
        repeat."
        PRD §3.5: "The request is valid from `APPROVED` and equally from
        `VERIFICATION_FAILED` — a failed verification can be retried"
        PRD §3.5: "When the `outcome` is `PASS`, the plan moves to
        `VERIFIED_PASSED`, which is terminal; the finding flips `OPEN →
        VERIFIED_CLOSED`"

        Design: Difficulty/non_linear_state_machine/cap_reject_resubmit_and_verify_fail_cycle
        """
        ctx = cap_on_major_finding()
        supplier_id = ctx["supplier"]["id"]
        verifier_id = ctx["verifier"]["id"]
        cap = ctx["cap"]
        assert cap["status"] == "SUBMITTED"
        assert cap["escalation_count"] == 0

        rejected = review_cap(cap["id"], "REJECT",
                              rejection_reason="Plan lacks timelines")
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "Plan lacks timelines"

        resubmitted = resubmit_cap(
            cap["id"], supplier_id,
            actions=[cap_action(description="Install guards v2 with milestones",
                                due_date="2026-10-15T00:00:00Z")],
        )
        assert resubmitted["status"] == "SUBMITTED", "reject/resubmit cycle edge"

        approved = review_cap(cap["id"], "APPROVE")
        assert approved["status"] == "APPROVED"

        requested = request_cap_verification(cap["id"], supplier_id)
        assert requested["status"] == "VERIFICATION_REQUESTED"

        failed = verify_cap(cap["id"], verifier_id, "FAIL",
                            "Guards not yet installed")
        assert failed["status"] == "VERIFICATION_FAILED"

        re_requested = request_cap_verification(cap["id"], supplier_id)
        assert re_requested["status"] == "VERIFICATION_REQUESTED", (
            "verify-fail loop edge: VERIFICATION_FAILED -> VERIFICATION_REQUESTED"
        )

        passed = verify_cap(cap["id"], verifier_id, "PASS",
                            "Guards verified installed")
        assert passed["status"] == "VERIFIED_PASSED"
        assert get_finding(ctx["finding"]["id"])["status"] == "VERIFIED_CLOSED", (
            "the plan pass cascades to the finding"
        )

    def test_cap_single_verify_fail_below_escalation_threshold(self, api):
        """PRD §3.5: "When the `outcome` is `FAIL`, the plan moves to
        `VERIFICATION_FAILED`; its `escalation_count` increments by one; once
        that count is 2 or more, the supplier's `escalation_penalty_points`
        grows by 5 per failure"

        Design: Difficulty/non_linear_state_machine/cap_reject_resubmit_and_verify_fail_cycle
        """
        ctx = cap_on_major_finding()
        supplier_id = ctx["supplier"]["id"]
        cap = ctx["cap"]
        review_cap(cap["id"], "APPROVE")
        request_cap_verification(cap["id"], supplier_id)
        failed = verify_cap(cap["id"], ctx["verifier"]["id"], "FAIL",
                            "Guards not yet installed")
        assert failed["status"] == "VERIFICATION_FAILED"
        assert failed["escalation_count"] == 1, (
            "a single FAIL increments the escalation count to 1"
        )
        supplier = get_supplier(supplier_id)
        assert supplier["escalation_penalty_points"] == 0, (
            "the sticky penalty applies only once the count reaches 2"
        )


class TestCapVerifyFailEscalationCascade:
    def escalation_scenario(self):
        """3 OPEN MAJOR + 1 OPEN MINOR + one unresolved CRITICAL grievance:
        verified_score 62 (QUALIFIED, ACTIVE); a plan on the first MAJOR sits
        in VERIFICATION_REQUESTED."""
        ctx = setup_in_progress_audit(supplier_name="Hotel Foods", sector="FOOD",
                                      facility_name="Boise Plant")
        audit_id = ctx["audit"]["id"]
        auditor_id = ctx["auditor"]["id"]
        f1 = record_finding(audit_id, auditor_id, "MAJOR", "WAGES",
                            "Wage issue A")
        record_finding(audit_id, auditor_id, "MAJOR", "WORKING_HOURS",
                       "Hours issue B")
        record_finding(audit_id, auditor_id, "MAJOR", "HEALTH_SAFETY",
                       "Safety issue C")
        record_finding(audit_id, auditor_id, "MINOR", "ENVIRONMENT",
                       "Minor issue D")
        file_grievance(ctx["facility"]["id"], channel="WORKER_COMMITTEE",
                       category="SAFETY", severity="CRITICAL",
                       description="Ammonia leak unaddressed")
        cap = create_cap(f1["id"], ctx["supplier"]["id"])
        review_cap(cap["id"], "APPROVE")
        request_cap_verification(cap["id"], ctx["supplier"]["id"])
        ctx["finding"] = f1
        ctx["cap"] = get_cap(cap["id"])
        scorecard = get_scorecard(ctx["supplier"]["id"])
        assert scorecard["verified_score"] == 62, "100 - 30 - 3 - 5"
        assert scorecard["consequence_tier"] == "QUALIFIED"
        assert get_supplier(ctx["supplier"]["id"])["status"] == "ACTIVE"
        return ctx

    def test_cap_first_verify_fail_no_downstream_movement(self, api):
        """PRD §3.5: "When the `outcome` is `FAIL`, the plan moves to
        `VERIFICATION_FAILED`; its `escalation_count` increments by one; once
        that count is 2 or more, the supplier's `escalation_penalty_points`
        grows by 5 per failure"

        Design: Difficulty/transitive_cascade/cap_verify_fail_escalation_cascade
        """
        ctx = self.escalation_scenario()
        failed = verify_cap(ctx["cap"]["id"], ctx["verifier"]["id"], "FAIL",
                            "Not remediated")
        assert failed["status"] == "VERIFICATION_FAILED"
        assert failed["escalation_count"] == 1
        scorecard = get_scorecard(ctx["supplier"]["id"])
        assert scorecard["verified_score"] == 62, (
            "count 1 is below the penalty threshold: nothing downstream moves"
        )
        assert scorecard["consequence_tier"] == "QUALIFIED"
        assert scorecard["escalation_penalty_points"] == 0
        assert get_supplier(ctx["supplier"]["id"])["status"] == "ACTIVE"

    def test_cap_second_verify_fail_triggers_escalation_cascade(self, api):
        """PRD §3.5: "once that count is 2 or more, the supplier's
        `escalation_penalty_points` grows by 5 per failure; the scorecard
        recomputes with the penalty flowing into both variants; if the verified
        score has fallen below 60 the supplier moves `ACTIVE → PROBATION`"
        PRD §3.6: "a supplier moves `ACTIVE → PROBATION` whenever the verified
        score drops below 60 or any `OPEN` zero-tolerance finding exists across
        its facilities"

        Design: Difficulty/transitive_cascade/cap_verify_fail_escalation_cascade
        """
        ctx = self.escalation_scenario()
        supplier_id = ctx["supplier"]["id"]
        verify_cap(ctx["cap"]["id"], ctx["verifier"]["id"], "FAIL",
                   "Not remediated")
        request_cap_verification(ctx["cap"]["id"], supplier_id)
        failed2 = verify_cap(ctx["cap"]["id"], ctx["verifier"]["id"], "FAIL",
                             "Still not remediated")
        assert failed2["escalation_count"] == 2

        scorecard = get_scorecard(supplier_id)
        assert scorecard["escalation_penalty_points"] == 5, (
            "the sticky penalty lands on the second failure"
        )
        assert scorecard["verified_score"] == 57, "62 - 5 penalty"
        assert scorecard["provisional_score"] == 57, (
            "the penalty flows into both variants"
        )
        assert scorecard["consequence_tier"] == "PROBATION_WATCH"
        assert get_supplier(supplier_id)["status"] == "PROBATION", (
            "57 < 60 crosses the standing threshold"
        )


class TestCapGuards:
    def test_cap_review_after_verified_passed_rejected(self, api):
        """PRD §3.5: "When the `outcome` is `PASS`, the plan moves to
        `VERIFIED_PASSED`, which is terminal"
        PRD §3.5: "Either decision from any other state is an
        `ERR_CAP_INVALID_STATE`."

        Design: Corner/state_machines/cap_review_after_verified_passed_rejected
        """
        ctx = cap_on_major_finding(supplier_name="Charlie Goods", sector="FOOD",
                                   facility_name="Site S")
        # Drive the plan created by the fixture through its pass cycle; the
        # finding already has an open plan, so creating a second one via
        # cap_full_pass_cycle would violate PRD §3.5 (ERR_CAP_ALREADY_OPEN).
        review_cap(ctx["cap"]["id"], "APPROVE")
        request_cap_verification(ctx["cap"]["id"], ctx["supplier"]["id"])
        passed = verify_cap(ctx["cap"]["id"], ctx["verifier"]["id"], "PASS",
                            "Verified on site")
        assert passed["status"] == "VERIFIED_PASSED"
        resp = api.review_corrective_action_plan(
            ctx["cap"]["id"], {"decision": "APPROVE"}, OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_CAP_INVALID_STATE, 409)
        assert get_cap(ctx["cap"]["id"])["status"] == "VERIFIED_PASSED"

    def test_cap_already_open_for_finding(self, api):
        """PRD §3.5: "at most one open plan may exist per finding — open here
        meaning `SUBMITTED`, `APPROVED`, `REJECTED`, `VERIFICATION_REQUESTED`,
        or `VERIFICATION_FAILED` (`ERR_CAP_ALREADY_OPEN`)."

        Design: Corner/validations/cap_already_open_for_finding
        """
        ctx = cap_on_major_finding(supplier_name="Xray B", sector="FOOD",
                                   facility_name="Site A2")
        resp = api.create_corrective_action_plan(
            create_cap_payload(
                ctx["finding"]["id"],
                actions=[cap_action(description="Alternative fix", owner="Ops",
                                    due_date="2026-10-05T00:00:00Z")],
            ),
            make_supplier_contact_headers(ctx["supplier"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CAP_ALREADY_OPEN, 409)
        listed, meta = validate_paginated(
            api.list_corrective_action_plans(
                OFFICER, params={"finding_id": ctx["finding"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert [c["id"] for c in listed] == [ctx["cap"]["id"]]

    def test_cap_create_on_closed_finding_rejected(self, api):
        """PRD §3.5: "The finding must be `OPEN` (`ERR_FINDING_NOT_OPEN`)"

        Design: Corner/validations/cap_create_on_closed_finding_rejected
        """
        ctx = cap_on_major_finding(supplier_name="Yankee B", sector="FOOD",
                                   facility_name="Site Z2")
        # Drive the fixture's existing plan to VERIFIED_PASSED (which closes
        # the finding); a second cap_full_pass_cycle on the same finding would
        # violate PRD §3.5's one-open-plan rule (ERR_CAP_ALREADY_OPEN).
        review_cap(ctx["cap"]["id"], "APPROVE")
        request_cap_verification(ctx["cap"]["id"], ctx["supplier"]["id"])
        verify_cap(ctx["cap"]["id"], ctx["verifier"]["id"], "PASS",
                   "Verified on site")
        assert get_finding(ctx["finding"]["id"])["status"] == "VERIFIED_CLOSED"
        resp = api.create_corrective_action_plan(
            create_cap_payload(ctx["finding"]["id"]),
            make_supplier_contact_headers(ctx["supplier"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FINDING_NOT_OPEN, 409)

    def test_cap_create_ownership_violation_rejected(self, api):
        """PRD §3.5: "The plan's `supplier_id` is derived from the chain finding
        → audit → facility → supplier and must equal the caller's `X-User-ID`
        (`ERR_OWNERSHIP_VIOLATION`)."

        Design: Corner/validations/cap_create_ownership_violation_rejected
        """
        cv = create_code_version()
        sup_a = create_supplier(legal_name="Oscar A", sector="FOOD")
        acknowledge_code(sup_a, cv["id"])
        sup_b = create_supplier(legal_name="Oscar B", sector="FOOD")
        acknowledge_code(sup_b, cv["id"])
        fac_b = create_facility(sup_b["id"], name="B Site")
        auditor = create_auditor()
        audit = begin_audit(schedule_audit(fac_b["id"], auditor["id"]))
        finding_b = record_finding(audit["id"], auditor["id"], "MAJOR", "WAGES",
                                   "B wage issue")

        resp = api.create_corrective_action_plan(
            create_cap_payload(finding_b["id"]),
            make_supplier_contact_headers(sup_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION, 403)
        listed, _ = validate_paginated(
            api.list_corrective_action_plans(
                OFFICER, params={"finding_id": finding_b["id"]}
            )
        )
        assert listed == [], "no plan is created for another supplier's finding"

    def test_cap_reject_without_reason_rejected(self, api):
        """PRD §3.5: "`REJECT` moves it `SUBMITTED → REJECTED` and requires a
        `rejection_reason` in the payload (`ERR_INVALID_REQUEST`), which is
        stored on the plan."

        Design: Corner/validations/cap_reject_without_reason_returns_invalid_request
        """
        ctx = cap_on_major_finding(supplier_name="Oscar C", sector="FOOD",
                                   facility_name="Site K2")
        resp = api.review_corrective_action_plan(
            ctx["cap"]["id"], {"decision": "REJECT"}, OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        assert get_cap(ctx["cap"]["id"])["status"] == "SUBMITTED"

    def test_verify_by_lead_auditor_rejected(self, api):
        """PRD §2.9: "the auditor who verifies a corrective action plan must be
        an `ACTIVE` auditor whose identity differs from the originating audit's
        lead `auditor_id`, or the verify is refused with
        `ERR_VERIFICATION_AUDITOR_CONFLICT` (403)."
        PRD §3.5: "the plan's `verified_by_auditor_id` records the verifying
        auditor from `X-User-ID`"

        Design: Corner/validations/verification_by_lead_auditor_rejected
        """
        ctx = cap_on_major_finding(supplier_name="Bravo C", sector="FOOD",
                                   facility_name="Site W2")
        cap = review_cap(ctx["cap"]["id"], "APPROVE")
        cap = request_cap_verification(cap["id"], ctx["supplier"]["id"])

        conflict = api.verify_corrective_action_plan(
            cap["id"],
            {"outcome": "PASS", "verification_note": "Self-verify attempt"},
            make_auditor_headers(ctx["auditor"]["id"]),
        )
        validate_error(conflict, ApiErrorId.ERR_VERIFICATION_AUDITOR_CONFLICT,
                       403)

        passed = verify_cap(cap["id"], ctx["verifier"]["id"], "PASS",
                            "Independent verification")
        assert passed["status"] == "VERIFIED_PASSED"
        assert passed["verified_by_auditor_id"] == ctx["verifier"]["id"], (
            "the independent verifying auditor is recorded"
        )
