"""Findings: severity banding, config pinning, issue SoD, and the management
negotiation cycle with its rounds boundary (PRD §3.2, §3.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_finding,
    create_active_rating_config,
    create_rating_criteria_config_payload,
    create_auditor,
    create_finding_payload,
    create_issued_finding,
    create_management_response_payload,
    create_workpaper_payload,
    get_success_data,
    make_field_auditor_headers,
    make_manager_headers,
    respond_to_finding,
    accept_response,
    setup_agreed_finding,
    setup_engagement_in_fieldwork,
    validate_error,
    validate_success,
)


class TestSeverityBands:
    def test_finding_severity_band_boundaries(self, api):
        """PRD §3.6: "The `composite_score` is the `likelihood` multiplied by
        the `impact`, an integer from 1 to 25. The `severity` then follows the
        pinned config's bands, with every boundary inclusive: a composite at or
        above `critical_min` is `CRITICAL`; otherwise at or above `high_min` is
        `HIGH`; otherwise at or above `moderate_min` is `MODERATE`; anything
        lower is `LOW`."
        PRD §3.6: "At creation the server captures `created_by_user_id` from the
        caller, pins `rating_criteria_config_id` to the currently `ACTIVE`
        config, and computes the rating."

        Design: Corner/calculations/finding_severity_band_boundaries
        """
        ctx = setup_engagement_in_fieldwork(entity_name="E", budget_hours=100)
        cfg = create_active_rating_config(critical_min=20, high_min=12, moderate_min=6)
        staff_h = make_field_auditor_headers(ctx["staff"]["id"])

        cases = [
            ("F-cr", 4, 5, 20, "CRITICAL"),  # at the >= 20 boundary
            ("F-hi", 3, 4, 12, "HIGH"),      # at the >= 12 boundary
            ("F-mo", 2, 3, 6, "MODERATE"),   # at the >= 6 boundary
            ("F-lo", 1, 5, 5, "LOW"),        # below moderate_min
        ]
        for title, likelihood, impact, composite, severity in cases:
            finding = get_success_data(api.create_finding(
                create_finding_payload(ctx["engagement"]["id"], title=title,
                                       likelihood=likelihood, impact=impact),
                staff_h,
            ))
            assert finding["composite_score"] == composite
            assert finding["severity"] == severity, (
                f"composite {composite} must land in {severity} (boundary is inclusive)"
            )
            assert finding["rating_criteria_config_id"] == cfg["id"]
            assert finding["status"] == "DRAFT"
            assert_finding(finding)


class TestFindingCreationGates:
    def test_finding_create_requires_active_config(self, api):
        """PRD §3.6: "Two further gates apply at creation: an `ACTIVE` rating
        criteria config must exist, since severity cannot be computed without
        one (`ERR_NO_ACTIVE_RATING_CONFIG`)"

        Design: Corner/validations/finding_create_requires_active_config
        """
        ctx = setup_engagement_in_fieldwork(entity_name="E", budget_hours=100)
        # A config that exists only in DRAFT (never activated) does not count.
        get_success_data(api.create_rating_criteria_config(
            create_rating_criteria_config_payload(
                name="dormant", critical_min=20, high_min=12, moderate_min=6,
            ),
            TEST_USERS["admin_headers"],
        ))
        resp = api.create_finding(
            create_finding_payload(ctx["engagement"]["id"], title="F",
                                   likelihood=3, impact=4),
            make_field_auditor_headers(ctx["staff"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_RATING_CONFIG, expected_status=422)


class TestConfigVersionPinning:
    def test_version_pinning_config_supersede(self, api, admin_headers):
        """PRD §2.6: "A finding pins its `rating_criteria_config_id` — and
        therefore its severity bands — to the config that is `ACTIVE` at the
        moment of creation, and is never re-rated when that config is later
        superseded."
        PRD §3.2: "when a config becomes `ACTIVE`, the previously `ACTIVE`
        config, if one exists, automatically transitions to the terminal
        `SUPERSEDED` status."
        PRD §3.2: "Activation moves a `DRAFT` config to `ACTIVE` — attempting
        to activate a config in any other status fails with
        `ERR_RATING_CONFIG_INVALID_STATE`"

        Design: Corner/complexity_layers/version_pinning_config_supersede
        """
        ctx = setup_engagement_in_fieldwork(entity_name="E", budget_hours=100)
        staff_h = make_field_auditor_headers(ctx["staff"]["id"])
        cfg1 = create_active_rating_config(critical_min=20, high_min=12, moderate_min=6,
                                           name="cfg1")

        f1 = get_success_data(api.create_finding(
            create_finding_payload(ctx["engagement"]["id"], title="F1", likelihood=4, impact=5),
            staff_h,
        ))
        assert f1["severity"] == "CRITICAL"
        assert f1["rating_criteria_config_id"] == cfg1["id"]

        # Activating cfg2 (critical_min 24) supersedes cfg1.
        cfg2 = get_success_data(api.create_rating_criteria_config(
            create_rating_criteria_config_payload(
                name="cfg2", critical_min=24, high_min=12, moderate_min=6,
            ),
            admin_headers,
        ))
        get_success_data(api.activate_rating_criteria_config(cfg2["id"], admin_headers))
        cfg1_after = get_success_data(api.get_rating_criteria_config(cfg1["id"], admin_headers))
        assert cfg1_after["status"] == "SUPERSEDED"

        # f1 keeps its pinned rating; f2 (same composite 20) rates under cfg2.
        f1_after = get_success_data(api.get_finding(f1["id"], staff_h))
        assert f1_after["severity"] == "CRITICAL"
        assert f1_after["rating_criteria_config_id"] == cfg1["id"]

        f2 = get_success_data(api.create_finding(
            create_finding_payload(ctx["engagement"]["id"], title="F2", likelihood=4, impact=5),
            staff_h,
        ))
        assert f2["composite_score"] == 20
        assert f2["severity"] == "HIGH", "20 < critical_min 24 under cfg2"
        assert f2["rating_criteria_config_id"] == cfg2["id"]

        # The superseded config cannot be re-activated.
        reactivate = api.activate_rating_criteria_config(cfg1["id"], admin_headers)
        validate_error(reactivate, ApiErrorId.ERR_RATING_CONFIG_INVALID_STATE, expected_status=409)


class TestNegotiationCycle:
    def test_finding_response_negotiation_cycle(self, api, owner_headers):
        """PRD §3.6: "A successful rebuttal moves the response to `REBUTTED`,
        records `reviewed_by_user_id`, and bubbles up: the finding returns from
        `UNDER_REVIEW` to `REBUTTED` and its `negotiation_rounds` increments by
        one."
        PRD §3.6: "Creating a response has an automatic upward effect: the
        parent finding transitions to `UNDER_REVIEW` — from `PENDING_RESPONSE`
        on the first response, or from `REBUTTED` on each fresh response of the
        negotiation cycle."
        PRD §3.6: "Accepting the response moves it to `ACCEPTED`, records the
        caller as `reviewed_by_user_id`, and bubbles up: the parent finding
        transitions from `UNDER_REVIEW` to `AGREED`."

        Design: Difficulty/non_linear_state_machine/finding_response_negotiation_cycle
        """
        ctx = setup_engagement_in_fieldwork(entity_name="Entity N", budget_hours=100)
        create_active_rating_config()
        mgr2 = create_auditor(full_name="Mike Mgr2", grade="MANAGER")
        mgr2_h = make_manager_headers(mgr2["id"])
        finding = create_issued_finding(ctx, title="Control gap", likelihood=4, impact=5,
                                        issuer=mgr2)

        resp1 = respond_to_finding(finding["id"], response_text="Will fix by Q3",
                                   proposed_due_date="2026-09-01T00:00:00Z")
        # The cycle turns: rebut (round 1) -> fresh response -> accept.
        rebutted = get_success_data(api.rebut_management_response(
            resp1["id"], {"rebuttal_note": "Insufficient evidence"}, mgr2_h,
        ))
        assert rebutted["status"] == "REBUTTED"

        resp2 = respond_to_finding(finding["id"], response_text="Revised plan attached",
                                   proposed_due_date="2026-08-01T00:00:00Z")
        accepted = get_success_data(api.accept_management_response(resp2["id"], mgr2_h))
        assert accepted["status"] == "ACCEPTED"

        finding_after = get_success_data(api.get_finding(finding["id"], mgr2_h))
        assert finding_after["status"] == "AGREED"
        assert finding_after["negotiation_rounds"] == 1, (
            "Exactly one rebuttal traversed the cycle"
        )

    def test_finding_negotiation_cycle_second_round_increments_again(self, api):
        """PRD §3.6: "Rebutting the response carries a `rebuttal_note` and is
        subject to the negotiation-rounds cap: the parent finding's
        `negotiation_rounds` must be below three at rebuttal time, else the
        rebuttal fails with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/finding_response_negotiation_cycle
        """
        ctx = setup_engagement_in_fieldwork(entity_name="Entity N2", budget_hours=100)
        create_active_rating_config()
        mgr2 = create_auditor(full_name="Mike Mgr2", grade="MANAGER")
        mgr2_h = make_manager_headers(mgr2["id"])
        finding = create_issued_finding(ctx, title="Gap", likelihood=3, impact=4, issuer=mgr2)

        # Two full negotiation rounds.
        for round_no in (1, 2):
            resp = respond_to_finding(finding["id"], response_text=f"r{round_no}")
            get_success_data(api.rebut_management_response(
                resp["id"], {"rebuttal_note": f"n{round_no}"}, mgr2_h,
            ))
        after_two = get_success_data(api.get_finding(finding["id"], mgr2_h))
        assert after_two["status"] == "REBUTTED"
        assert after_two["negotiation_rounds"] == 2

        # A fresh response still reopens review (REBUTTED -> UNDER_REVIEW).
        resp3 = respond_to_finding(finding["id"], response_text="r3")
        under_review = get_success_data(api.get_finding(finding["id"], mgr2_h))
        assert under_review["status"] == "UNDER_REVIEW"
        accept_response(resp3["id"], mgr2)
        agreed = get_success_data(api.get_finding(finding["id"], mgr2_h))
        assert agreed["status"] == "AGREED"
        assert agreed["negotiation_rounds"] == 2


class TestNegotiationExhaustionBoundary:
    def test_finding_negotiation_exhaustion_boundary(self, api, cae_headers):
        """PRD §3.6: "The finding must be awaiting a response — in
        `PENDING_RESPONSE` or `REBUTTED`; otherwise creation fails with
        `ERR_FINDING_NOT_AWAITING_RESPONSE`."
        PRD §3.6: "Escalation moves a finding from `REBUTTED` to `ESCALATED` —
        any other from-state fails with `ERR_FINDING_INVALID_STATE` — and
        requires the negotiation rounds to be exhausted: `negotiation_rounds`
        must be at least three, and exactly three suffices. Escalating earlier
        fails with `ERR_NEGOTIATION_ROUNDS_NOT_EXHAUSTED`."
        PRD §3.6: "if the finding is `REBUTTED` and its `negotiation_rounds`
        has already reached three, a further response is rejected with
        `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`, because escalation is the only
        remaining path."

        Design: Corner/state_machines/finding_negotiation_exhaustion_boundary
        """
        ctx = setup_engagement_in_fieldwork(entity_name="E", budget_hours=100)
        create_active_rating_config()
        mgr2 = create_auditor(full_name="Mike Mgr2", grade="MANAGER")
        mgr2_h = make_manager_headers(mgr2["id"])
        f1 = create_issued_finding(ctx, title="F1", likelihood=4, impact=5, issuer=mgr2)
        f2 = get_success_data(api.create_finding(
            create_finding_payload(ctx["engagement"]["id"], title="F2", likelihood=2, impact=2),
            make_field_auditor_headers(ctx["staff"]["id"]),
        ))

        # A response for a DRAFT finding is rejected (not awaiting response).
        premature = api.create_management_response(
            create_management_response_payload(f2["id"], response_text="premature"),
            TEST_USERS["owner_headers"],
        )
        validate_error(premature, ApiErrorId.ERR_FINDING_NOT_AWAITING_RESPONSE, expected_status=409)

        # Two negotiation rounds.
        for round_no in (1, 2):
            resp = respond_to_finding(f1["id"], response_text=f"r{round_no}")
            get_success_data(api.rebut_management_response(
                resp["id"], {"rebuttal_note": f"n{round_no}"}, mgr2_h,
            ))

        # Escalation at rounds == 2 is too early.
        early = api.escalate_finding(f1["id"], cae_headers)
        validate_error(early, ApiErrorId.ERR_NEGOTIATION_ROUNDS_NOT_EXHAUSTED, expected_status=422)

        # Third rebuttal brings rounds to exactly 3; escalation now succeeds.
        resp3 = respond_to_finding(f1["id"], response_text="r3")
        get_success_data(api.rebut_management_response(resp3["id"], {"rebuttal_note": "n3"}, mgr2_h))
        at_three = get_success_data(api.get_finding(f1["id"], mgr2_h))
        assert at_three["status"] == "REBUTTED"
        assert at_three["negotiation_rounds"] == 3

        # A fourth response is rejected once the rounds are exhausted.
        fourth = api.create_management_response(
            create_management_response_payload(f1["id"], response_text="r4"),
            TEST_USERS["owner_headers"],
        )
        validate_error(fourth, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED, expected_status=422)

        escalated = get_success_data(api.escalate_finding(f1["id"], cae_headers))
        assert escalated["status"] == "ESCALATED"
        assert escalated["negotiation_rounds"] == 3

        # Re-issue of an ESCALATED finding is an invalid-state error.
        reissue = api.issue_finding(f1["id"], mgr2_h)
        validate_error(reissue, ApiErrorId.ERR_FINDING_INVALID_STATE, expected_status=409)


class TestResponseDecisionLockdown:
    def test_management_response_double_decision_rejected(self, api):
        """PRD §3.6: "An `AuditManager` then adjudicates each `SUBMITTED`
        response; a response in any other status rejects both actions with
        `ERR_RESPONSE_INVALID_STATE`."
        PRD §3.6: "Accepting the response moves it to `ACCEPTED`, records the
        caller as `reviewed_by_user_id`, and bubbles up: the parent finding
        transitions from `UNDER_REVIEW` to `AGREED`."

        Design: Corner/state_machines/management_response_double_decision_rejected
        """
        ctx = setup_agreed_finding(entity_name="E")
        mgr2_h = make_manager_headers(ctx["mgr2"]["id"])
        resp = ctx["response"]

        # The fixture already accepted the response; a second accept is rejected.
        double = api.accept_management_response(resp["id"], mgr2_h)
        validate_error(double, ApiErrorId.ERR_RESPONSE_INVALID_STATE, expected_status=409)

        resp_after = get_success_data(api.get_management_response(resp["id"], mgr2_h))
        assert resp_after["status"] == "ACCEPTED"
        assert resp_after["reviewed_by_user_id"] == ctx["mgr2"]["id"]
        finding_after = get_success_data(api.get_finding(ctx["finding"]["id"], mgr2_h))
        assert finding_after["status"] == "AGREED"


class TestFindingIssueSegregation:
    def test_finding_issue_self_issue_beats_unsigned_workpaper(self, api):
        """PRD §3.6: "The issuer must not be the finding's creator: an
        `X-User-ID` equal to `created_by_user_id` is rejected with
        `ERR_FINDING_SELF_ISSUE`, and this segregation check is evaluated before
        any referential gate, so a self-issue attempt surfaces
        `ERR_FINDING_SELF_ISSUE` even when other problems exist."
        PRD §3.6: "When the finding carries a `workpaper_id`, issuance
        re-verifies that the linked workpaper is still `SIGNED_OFF`; a link that
        has been returned to the preparer in the meantime blocks issuance with
        `ERR_WORKPAPER_NOT_SIGNED`."

        Design: Difficulty/priority_pair_validation_conflict/finding_issue_self_issue_beats_unsigned_workpaper
        """
        ctx = setup_engagement_in_fieldwork(entity_name="Entity P", budget_hours=100)
        create_active_rating_config()
        mgr2 = create_auditor(full_name="Mike Mgr2", grade="MANAGER")
        mgr1, staff = ctx["mgr"], ctx["staff"]
        mgr2_h = make_manager_headers(mgr2["id"])
        staff_h = make_field_auditor_headers(staff["id"])

        # Workpaper signed off by mgr2, then returned (falls out of SIGNED_OFF).
        wp = get_success_data(api.create_workpaper(
            create_workpaper_payload(ctx["engagement"]["id"], reference="A-1",
                                     title="WP A", hours_worked=6),
            staff_h,
        ))
        get_success_data(api.submit_workpaper(wp["id"], staff_h))
        get_success_data(api.sign_off_workpaper(wp["id"], mgr2_h))

        # Finding created by mgr1 acting as FieldAuditor (MANAGER is
        # dual-eligible) and linked to the workpaper while it was SIGNED_OFF.
        finding = get_success_data(api.create_finding(
            create_finding_payload(ctx["engagement"]["id"], title="Gap", likelihood=3,
                                   impact=4, workpaper_id=wp["id"]),
            make_field_auditor_headers(mgr1["id"]),
        ))
        get_success_data(api.return_workpaper(wp["id"], {"note": "Reopen evidence"}, mgr2_h))

        # The issuer equals the creator AND the linked workpaper is RETURNED:
        # the segregation error wins over the referential error.
        resp = api.issue_finding(finding["id"], make_manager_headers(mgr1["id"]))
        validate_error(resp, ApiErrorId.ERR_FINDING_SELF_ISSUE, expected_status=403)
        assert get_success_data(api.get_finding(finding["id"], mgr2_h))["status"] == "DRAFT"

    def test_finding_issue_by_other_manager_succeeds(self, api):
        """PRD §3.6: "Issuing a finding to management is an `AuditManager`
        action from `DRAFT` to `PENDING_RESPONSE`."
        PRD §3.6: "The issuer must not be the finding's creator: an `X-User-ID`
        equal to `created_by_user_id` is rejected with `ERR_FINDING_SELF_ISSUE`"

        Design: Difficulty/priority_pair_validation_conflict/finding_issue_self_issue_beats_unsigned_workpaper
        """
        ctx = setup_engagement_in_fieldwork(entity_name="Entity P2", budget_hours=100)
        create_active_rating_config()
        mgr2 = create_auditor(full_name="Mike Mgr2", grade="MANAGER")
        finding = get_success_data(api.create_finding(
            create_finding_payload(ctx["engagement"]["id"], title="Gap", likelihood=3, impact=4),
            make_field_auditor_headers(ctx["staff"]["id"]),
        ))
        issued = get_success_data(api.issue_finding(finding["id"], make_manager_headers(mgr2["id"])))
        assert issued["status"] == "PENDING_RESPONSE"
        assert_finding(issued)
