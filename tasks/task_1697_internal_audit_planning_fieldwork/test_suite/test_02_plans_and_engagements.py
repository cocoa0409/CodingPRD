"""Annual-plan approval cycle, engagement creation gates, OCC on plan version,
and engagement priority scoring (PRD §3.3, §3.4, §2.6)."""
from test_helpers import (
    ApiErrorId,
    assert_audit_plan,
    assert_engagement,
    build_user_headers,
    create_auditor,
    create_committee_pack_payload,
    create_engagement_payload,
    create_entity,
    create_plan,
    get_plan,
    get_success_data,
    is_iso8601_timestamp,
    make_manager_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPlanApprovalCycle:
    def test_plan_invalid_transitions_from_draft(self, api, committee_headers, cae_headers):
        """PRD §3.3: "While the plan is `SUBMITTED`, the `AuditCommittee`
        either approves or returns it."
        PRD §3.3: "Closing requires the plan to be `APPROVED` (else
        `ERR_PLAN_INVALID_STATE`) and requires every engagement of the plan to
        have reached a terminal state — `CLOSED` or `CANCELLED`; if any
        engagement remains open the close fails with
        `ERR_PLAN_HAS_OPEN_ENGAGEMENTS`."
        PRD §3.9: "Pack creation requires the plan to be in `APPROVED` or
        `CLOSED` status; reporting on a plan still under drafting or
        negotiation fails with `ERR_PLAN_NOT_APPROVED`."

        Design: Corner/state_machines/plan_invalid_transitions_from_draft
        """
        plan = create_plan()
        approve = api.approve_audit_plan(plan["id"], committee_headers)
        validate_error(approve, ApiErrorId.ERR_PLAN_INVALID_STATE, expected_status=409)
        ret = api.return_audit_plan(plan["id"], committee_headers)
        validate_error(ret, ApiErrorId.ERR_PLAN_INVALID_STATE, expected_status=409)
        close = api.close_audit_plan(plan["id"], cae_headers)
        validate_error(close, ApiErrorId.ERR_PLAN_INVALID_STATE, expected_status=409)
        pack = api.create_committee_pack(
            create_committee_pack_payload(plan["id"]), cae_headers
        )
        validate_error(pack, ApiErrorId.ERR_PLAN_NOT_APPROVED, expected_status=409)
        assert get_plan(plan["id"])["status"] == "DRAFT"

    def test_plan_return_resubmit_cycle(self, api, cae_headers, cae2_headers, committee_headers):
        """PRD §3.3: "Submitting the plan is a `ChiefAuditExecutive` action
        allowed from either `DRAFT` or `RETURNED` status — any other from-state
        fails with `ERR_PLAN_INVALID_STATE`"
        PRD §3.3: "On submission the server captures `submitted_by_user_id` from
        the caller's `X-User-ID` and stamps `submitted_at` from the logical
        clock; resubmission from `RETURNED` re-captures both, recording the
        latest round of the negotiation cycle."
        PRD §3.3: "if any engagement remains open the close fails with
        `ERR_PLAN_HAS_OPEN_ENGAGEMENTS`."

        Design: Corner/state_machines/plan_return_resubmit_cycle
        """
        set_clock()
        ent = create_entity(name="E")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        mgr_h = make_manager_headers(mgr["id"])
        plan = create_plan()
        get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent["id"], plan["version"], title="G"),
            mgr_h,
        ))
        get_success_data(api.submit_audit_plan(plan["id"], cae_headers))
        returned = get_success_data(api.return_audit_plan(plan["id"], committee_headers))
        assert returned["status"] == "RETURNED"

        # Resubmission from RETURNED succeeds and refreshes attribution.
        resubmitted = get_success_data(api.submit_audit_plan(plan["id"], cae2_headers))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["submitted_by_user_id"] == "cae-9"

        approved = get_success_data(api.approve_audit_plan(plan["id"], committee_headers))
        assert approved["status"] == "APPROVED"

        # Close is blocked while the engagement is still PLANNED.
        close = api.close_audit_plan(plan["id"], cae_headers)
        validate_error(close, ApiErrorId.ERR_PLAN_HAS_OPEN_ENGAGEMENTS, expected_status=409)

    def test_plan_self_approval_rejected(self, api, cae_headers, committee_headers, committee2_headers):
        """PRD §3.3: "Approval enforces segregation of duties: the committee
        caller's `X-User-ID` must differ from the plan's `submitted_by_user_id`,
        and a self-approval attempt is rejected with `ERR_PLAN_SELF_APPROVAL`
        (HTTP 403)."
        PRD §3.3: "A successful approval moves the plan to `APPROVED` and
        records `approved_by_user_id` and `approved_at`."

        Design: Corner/state_machines/plan_self_approval_rejected
        """
        set_clock()
        ent = create_entity(name="E")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        mgr_h = make_manager_headers(mgr["id"])
        plan = create_plan()
        get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent["id"], plan["version"], title="G"),
            mgr_h,
        ))
        get_success_data(api.submit_audit_plan(plan["id"], cae_headers))

        # The committee actor whose X-User-ID equals the submitter cannot approve.
        self_approve = api.approve_audit_plan(
            plan["id"], build_user_headers("cae-1", "AuditCommittee")
        )
        validate_error(self_approve, ApiErrorId.ERR_PLAN_SELF_APPROVAL, expected_status=403)

        approved = get_success_data(api.approve_audit_plan(plan["id"], committee2_headers))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "ac-2"
        assert_audit_plan(approved)


class TestPlanSubmissionBoundary:
    def test_plan_submit_empty_engagement_set_rejected(self, api, cae_headers):
        """PRD §3.3: "requires the plan to contain at least one engagement:
        submitting a plan whose `engagement_count` is zero fails with
        `ERR_PLAN_EMPTY`."

        Design: Difficulty/boundary_precision_check/plan_submit_empty_engagement_set_rejected
        """
        set_clock()
        ent = create_entity(name="Entity E0")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        plan = create_plan(title="Empty Plan")
        assert plan["engagement_count"] == 0

        # Zero-engagement submit is rejected.
        empty_submit = api.submit_audit_plan(plan["id"], cae_headers)
        validate_error(empty_submit, ApiErrorId.ERR_PLAN_EMPTY, expected_status=422)

        # Exactly one engagement flips the outcome to success.
        eng = get_success_data(api.create_engagement(
            create_engagement_payload(
                plan["id"], ent["id"], plan["version"], title="Eng E0", budget_hours=60,
            ),
            make_manager_headers(mgr["id"]),
        ))
        assert_engagement(eng)
        submitted = get_success_data(api.submit_audit_plan(plan["id"], cae_headers))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["engagement_count"] == 1

    def test_plan_submit_with_one_engagement_succeeds(self, api, cae_headers):
        """PRD §3.3: "requires the plan to contain at least one engagement:
        submitting a plan whose `engagement_count` is zero fails with
        `ERR_PLAN_EMPTY`."
        PRD §3.3: "On submission the server captures `submitted_by_user_id` from
        the caller's `X-User-ID` and stamps `submitted_at` from the logical
        clock"

        Design: Difficulty/boundary_precision_check/plan_submit_empty_engagement_set_rejected
        """
        set_clock()
        ent = create_entity(name="Entity E1")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        plan = create_plan(title="One-Engagement Plan")
        get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent["id"], plan["version"], title="G"),
            make_manager_headers(mgr["id"]),
        ))
        submitted = get_success_data(api.submit_audit_plan(plan["id"], cae_headers))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["engagement_count"] == 1
        assert submitted["submitted_by_user_id"] == "cae-1"
        assert is_iso8601_timestamp(submitted["submitted_at"])


class TestOccOnPlanVersion:
    def test_occ_stale_plan_version_rejected(self, api):
        """PRD §2.6: "Creating an engagement requires the request to carry
        `expected_audit_plan_version` holding the client last-observed `version`
        of the target audit plan; engagement creation mutates plan aggregates,
        so a mismatch with the plan's current `version` is rejected with
        `ERR_STALE_PLAN_VERSION` (HTTP 412), preventing a stale client from
        silently forking the plan roster."

        Design: Corner/complexity_layers/occ_stale_plan_version_rejected
        """
        set_clock()
        ent1 = create_entity(name="E1")
        ent2 = create_entity(name="E2")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        mgr_h = make_manager_headers(mgr["id"])
        plan = create_plan()

        # First creation against version 1 succeeds and advances the plan.
        get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent1["id"], plan["version"], title="G1"),
            mgr_h,
        ))
        assert get_plan(plan["id"])["version"] == 2

        # A second create carrying the stale observed version 1 is rejected.
        stale = api.create_engagement(
            create_engagement_payload(plan["id"], ent2["id"], plan["version"], title="G2"),
            mgr_h,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_PLAN_VERSION, expected_status=412)

        data, meta = validate_paginated(
            api.list_engagements(mgr_h, params={"audit_plan_id": plan["id"]})
        )
        assert meta["total_count"] == 1, "No second engagement may be persisted"


class TestEngagementListingAndLinks:
    def test_engagement_list_pagination_and_filtering(self, api):
        """PRD §2.3: "The `meta` object of a list response carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; it defaults to 10 when omitted, accepts a minimum of 1, and
        is capped at a maximum of 100. The `offset` parameter specifies how many
        items to skip and defaults to 0."

        Design: Corner/entities/engagement_list_pagination_and_filtering
        """
        set_clock()
        ent1 = create_entity(name="E1")
        ent2 = create_entity(name="E2")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        mgr_h = make_manager_headers(mgr["id"])
        plan = create_plan()
        get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent1["id"], plan["version"], title="G1"),
            mgr_h,
        ))
        plan_v2 = get_plan(plan["id"])["version"]
        get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent2["id"], plan_v2, title="G2"),
            mgr_h,
        ))

        page1, meta1 = validate_paginated(api.list_engagements(
            mgr_h, params={"audit_plan_id": plan["id"], "limit": 1, "offset": 0}
        ))
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_engagements(
            mgr_h, params={"audit_plan_id": plan["id"], "limit": 1, "offset": 1}
        ))
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page2[0]["id"] != page1[0]["id"]

    def test_engagement_supersedes_self_reference(self, api):
        """PRD §3.4: "An optional `supersedes_engagement_id` links the
        engagement to a prior one as a follow-up reference; when supplied, it
        must resolve to an existing engagement or the create fails with
        `ERR_ENGAGEMENT_NOT_FOUND`."
        PRD §3.4: "Engagements may be listed filtered by `audit_plan_id`,
        `auditable_entity_id`, `supersedes_engagement_id`, or `status`."

        Design: Corner/entities/engagement_supersedes_self_reference
        """
        set_clock()
        ent1 = create_entity(name="E1")
        ent2 = create_entity(name="E2")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        mgr_h = make_manager_headers(mgr["id"])
        plan = create_plan()
        eng1 = get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent1["id"], plan["version"], title="G1"),
            mgr_h,
        ))
        plan_v2 = get_plan(plan["id"])["version"]
        eng2 = get_success_data(api.create_engagement(
            create_engagement_payload(
                plan["id"], ent2["id"], plan_v2, title="G2 follow-up",
                supersedes_engagement_id=eng1["id"],
            ),
            mgr_h,
        ))
        assert eng2["supersedes_engagement_id"] == eng1["id"]

        data, meta = validate_paginated(api.list_engagements(
            mgr_h, params={"supersedes_engagement_id": eng1["id"]}
        ))
        assert meta["total_count"] == 1
        assert [row["id"] for row in data] == [eng2["id"]]

    def test_engagement_window_invalid_rejected(self, api):
        """PRD §3.4: "Both window bounds are inclusive, and the window must be
        non-empty: an `end_date` that is not strictly after the `start_date` is
        rejected with `ERR_ENGAGEMENT_WINDOW_INVALID`."

        Design: Corner/validations/engagement_window_invalid_rejected
        """
        ent = create_entity(name="E")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        plan = create_plan()
        resp = api.create_engagement(
            create_engagement_payload(
                plan["id"], ent["id"], plan["version"], title="G",
                start_date="2026-02-01T00:00:00Z", end_date="2026-02-01T00:00:00Z",
            ),
            make_manager_headers(mgr["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_WINDOW_INVALID, expected_status=422)


class TestPriorityScore:
    def test_priority_score_caps_at_100_for_36_month_recency(self, api):
        """PRD §3.4: "Thirty-six months or more contributes 30 points,
        twenty-four through thirty-five months contributes 20 points, twelve
        through twenty-three months contributes 10 points, and fewer than twelve
        months contributes nothing."
        PRD §3.4: "The priority score is the sum of the three components,
        capped at 100, and uses integer arithmetic with no rounding."

        Design: Difficulty/combinatorial_formula/priority_score_tiered_recency_with_cap
        """
        set_clock()  # 2026-01-15
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        mgr_h = make_manager_headers(mgr["id"])
        # Entity audited 2023-01-15 -> exactly 36 months at the fixture clock.
        ent = create_entity(name="Entity A", last_audit_completed_at="2023-01-15T00:00:00Z")
        ra = get_success_data(api.create_risk_assessment(
            {"auditable_entity_id": ent["id"], "fiscal_year": 2026, "likelihood": 3,
             "impact": 4, "expected_auditable_entity_version": ent["version"]},
            mgr_h,
        ))
        get_success_data(api.finalize_risk_assessment(ra["id"], mgr_h))
        plan = create_plan()

        eng = get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent["id"], plan["version"], title="Eng A",
                                      budget_hours=80),
            mgr_h,
        ))
        # 72 risk + 30 recency (exactly 36 months, boundary >=) = 102, capped.
        assert eng["priority_score"] == 100

    def test_priority_score_35_month_recency_below_cap(self, api):
        """PRD §3.4: "the whole calendar months between the entity's
        `last_audit_completed_at` and the current logical-clock date, computed
        as twelve times the difference in calendar years plus the difference in
        calendar month numbers, minus one when the clock date's day-of-month is
        earlier than the last-audit date's day-of-month"
        PRD §3.4: "Thirty-six months or more contributes 30 points,
        twenty-four through thirty-five months contributes 20 points"

        Design: Difficulty/combinatorial_formula/priority_score_tiered_recency_with_cap
        """
        set_clock()  # 2026-01-15
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        mgr_h = make_manager_headers(mgr["id"])
        # Entity audited 2023-02-15 -> 35 months at the fixture clock.
        ent = create_entity(name="Entity B", last_audit_completed_at="2023-02-15T00:00:00Z")
        ra = get_success_data(api.create_risk_assessment(
            {"auditable_entity_id": ent["id"], "fiscal_year": 2026, "likelihood": 3,
             "impact": 4, "expected_auditable_entity_version": ent["version"]},
            mgr_h,
        ))
        get_success_data(api.finalize_risk_assessment(ra["id"], mgr_h))
        plan = create_plan()

        eng = get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent["id"], plan["version"], title="Eng B",
                                      budget_hours=80),
            mgr_h,
        ))
        # 72 risk + 20 recency (35 months falls in the 24..35 tier) = 92.
        assert eng["priority_score"] == 92
        # Engagement creation advanced the plan version (OCC-visible mutation).
        assert get_plan(plan["id"])["version"] == 2


class TestCoolingPeriod:
    def test_cooling_period_89_day_gap_rejected(self, api):
        """PRD §3.4: "Precisely, creation is rejected with
        `ERR_ENGAGEMENT_COOLING_PERIOD` unless, for each such existing
        engagement, either the existing engagement's `end_date` plus ninety days
        falls on or before the new `start_date`, or the new engagement's
        `end_date` plus ninety days falls on or before the existing engagement's
        `start_date`; any pair of windows closer than ninety days — including
        adjacency anywhere inside the buffer — is rejected."

        Design: Difficulty/resource_temporal_overlap/auditable_entity_cooling_period_buffer_gap
        """
        set_clock()
        ent = create_entity(name="Entity C1")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        mgr_h = make_manager_headers(mgr["id"])
        plan = create_plan()
        base = get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent["id"], plan["version"], title="Eng base",
                                      budget_hours=60),
            mgr_h,
        ))
        plan_v2 = get_plan(plan["id"])["version"]

        # Start 2026-05-28 is 89 days after the base window's 2026-02-28 end —
        # inside the 90-day buffer, so it is rejected.
        early = api.create_engagement(
            create_engagement_payload(
                plan["id"], ent["id"], plan_v2, title="Eng early", budget_hours=60,
                start_date="2026-05-28T00:00:00Z", end_date="2026-06-15T00:00:00Z",
            ),
            mgr_h,
        )
        validate_error(early, ApiErrorId.ERR_ENGAGEMENT_COOLING_PERIOD, expected_status=409)

    def test_cooling_period_exactly_90_day_gap_accepted(self, api):
        """PRD §3.4: "either the existing engagement's `end_date` plus ninety
        days falls on or before the new `start_date`, or the new engagement's
        `end_date` plus ninety days falls on or before the existing engagement's
        `start_date`"

        Design: Difficulty/resource_temporal_overlap/auditable_entity_cooling_period_buffer_gap
        """
        set_clock()
        ent = create_entity(name="Entity C1")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        mgr_h = make_manager_headers(mgr["id"])
        plan = create_plan()
        get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent["id"], plan["version"], title="Eng base",
                                      budget_hours=60),
            mgr_h,
        ))
        plan_v2 = get_plan(plan["id"])["version"]

        # Start 2026-05-29 is exactly 90 days after 2026-02-28: boundary
        # "falls on or before" is satisfied, so the create succeeds.
        boundary = get_success_data(api.create_engagement(
            create_engagement_payload(
                plan["id"], ent["id"], plan_v2, title="Eng boundary", budget_hours=60,
                start_date="2026-05-29T00:00:00Z", end_date="2026-06-30T00:00:00Z",
            ),
            mgr_h,
        ))
        assert boundary["status"] == "PLANNED"
        # The failed attempt did not advance the plan version; the accepted one
        # consumed version 2 and bumped the plan to 3.
        assert get_plan(plan["id"])["version"] == 3
