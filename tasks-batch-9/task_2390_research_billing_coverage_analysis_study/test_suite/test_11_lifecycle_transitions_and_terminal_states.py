"""Declared transitions and the refusals that guard them: the analysis review
chain, calendar publication, the accrual close cascade, and terminal states.
"""

from test_helpers import (
    ANALYST_ONE,
    COORDINATOR_ONE,
    INITIAL_LOGICAL_CLOCK_STAMP,
    LIAISON_ONE,
    LIAISON_TWO,
    MANAGER_ONE,
    REVIEWER_ONE,
    add_item,
    api_client,
    close_accrual,
    complete_visit,
    create_coverage_analysis_payload,
    file_amendment,
    implement_amendment,
    item_spec,
    make_analyst_headers,
    make_coordinator_headers,
    make_liaison_headers,
    make_manager_headers,
    make_reviewer_headers,
    open_analysis,
    open_finding,
    post_charge,
    read_analysis,
    read_calendar,
    read_charge,
    read_study,
    read_summary,
    register_study,
    register_subject,
    resolve_finding,
    resolve_finding_payload,
    respond_finding,
    respond_finding_payload,
    return_analysis_payload,
    route_spec,
    schedule_visit,
    set_clock,
    setup_consented_subject,
    setup_open_to_accrual,
    setup_published_calendar,
    setup_scheduled_visit,
    setup_study_with_approved_analysis,
    setup_study_with_draft_grid,
    validate_error,
    validate_paginated,
    validate_success,
    visit_spec,
)

LAB_PANEL = item_spec(
    "80053",
    classification="ROUTINE_CARE",
    medicare_coverage_basis="STANDARD_OF_CARE",
    budget_category="PER_PATIENT",
    charge_master_unit_cents=9000,
    negotiated_unit_cents=9000,
    units_per_occurrence=1,
    expected_occurrences=3,
)
INFUSION = item_spec(
    "J9999",
    classification="RESEARCH_PAID",
    medicare_coverage_basis="NOT_COVERED",
    budget_category="PER_PATIENT",
    charge_master_unit_cents=50000,
    negotiated_unit_cents=40000,
    units_per_occurrence=2,
    expected_occurrences=1,
)


class TestCoverageAnalysisReviewChain:
    """DRAFT to UNDER_REVIEW to APPROVED, and the guards on each step."""

    def test_01_a_first_analysis_opens_in_draft_and_moves_the_study_in_the_same_request(self):
        """Revision 1 with every counter at zero, and the study is dragged from
        `DRAFT` to `COVERAGE_PENDING` before the response is returned.

        PRD §3.2: "The first analysis for a protocol leaves
        `supersedes_analysis_id` null and takes `revision_number` 1; a revision
        takes one more than the `revision_number` of the analysis it supersedes."

        Design: Corner/state_machines/new_coverage_analysis_starts_in_draft_revision_one
        """
        set_clock("2026-08-01T00:00:00Z")
        study = register_study(protocol_number="AMC-2390-C12", title="Corner state probe")
        assert study["lifecycle_status"] == "DRAFT"
        assert study["version"] == 1

        analysis = validate_success(
            api_client.create_coverage_analysis(
                create_coverage_analysis_payload(study["id"], study["version"]),
                make_analyst_headers(ANALYST_ONE),
            ),
            201,
        )
        assert analysis["status"] == "DRAFT"
        assert analysis["revision_number"] == 1
        assert analysis["supersedes_analysis_id"] is None
        assert analysis["return_count"] == 0
        assert analysis["version"] == 1
        assert analysis["item_count"] == 0
        assert analysis["routine_care_item_count"] == 0
        assert analysis["research_paid_item_count"] == 0
        assert analysis["promotional_item_count"] == 0
        assert analysis["qct_conditional_item_count"] == 0
        assert analysis["prepared_by_user_id"] == ANALYST_ONE
        assert analysis["approved_by_user_id"] is None
        assert analysis["approved_at"] is None
        assert analysis["returned_by_user_id"] is None

        after = read_study(study["id"])
        assert after["lifecycle_status"] == "COVERAGE_PENDING"
        assert after["version"] == 2
        # The budget dimension is independent and did not move.
        assert after["budget_status"] == "NOT_BUILT"

    def test_02_submission_moves_the_analysis_only_and_leaves_the_study_pending(self):
        """The transition bumps the analysis to its third version and stops
        there: advancing the study is approval's job, not submission's.

        PRD §3.3: "Once the grid has at least one item, the analyst sends it to
        compliance, moving the analysis `DRAFT → UNDER_REVIEW`."

        Design: Corner/state_machines/submit_moves_analysis_from_draft_to_under_review
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = setup_study_with_draft_grid(
            [LAB_PANEL], study_overrides={"protocol_number": "AMC-2390-C13"}
        )
        assert ctx["analysis"]["version"] == 2

        submitted = validate_success(
            api_client.submit_coverage_analysis(
                ctx["analysis"]["id"], make_analyst_headers(ANALYST_ONE)
            ),
            200,
        )
        assert submitted["status"] == "UNDER_REVIEW"
        assert submitted["version"] == 3
        assert submitted["item_count"] == 1
        assert submitted["routine_care_item_count"] == 1
        assert submitted["approved_at"] is None
        assert submitted["approved_by_user_id"] is None

        study = read_study(ctx["study"]["id"])
        assert study["lifecycle_status"] == "COVERAGE_PENDING"
        assert study["version"] == 2

    def test_03_submitting_an_empty_grid_fails_the_state_guard(self):
        """The analysis is `DRAFT`, so the refusal can only come from the empty
        grid — and it comes back as the generic transition code.

        PRD §3.3: "A submission from any other status, or with an empty grid, is
        refused — an empty grid on a `DRAFT` analysis fails the state guard for
        this transition."

        Design: Corner/state_machines/submitting_an_analysis_with_zero_items_is_refused
        """
        set_clock("2026-08-01T00:00:00Z")
        study = register_study(protocol_number="AMC-2390-C14", title="Corner empty grid")
        analysis = open_analysis(study["id"])
        assert analysis["item_count"] == 0

        validate_error(
            api_client.submit_coverage_analysis(
                analysis["id"], make_analyst_headers(ANALYST_ONE)
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        unchanged = read_analysis(analysis["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["version"] == 1

        add_item(analysis["id"], **LAB_PANEL)
        accepted = validate_success(
            api_client.submit_coverage_analysis(
                analysis["id"], make_analyst_headers(ANALYST_ONE)
            ),
            200,
        )
        assert accepted["status"] == "UNDER_REVIEW"

    def test_04_neither_approval_nor_return_reaches_a_draft_analysis(self):
        """Both review-side actions are declared from `UNDER_REVIEW` only, and
        neither of approval's side effects runs.

        PRD §2.11: "The target's own state permits the transition —
        `ERR_INVALID_STATE_TRANSITION` (409) on every action endpoint, except
        that the domain-specific codes `ERR_ANALYSIS_NOT_EDITABLE`,
        `ERR_ANALYSIS_NOT_UNDER_REVIEW`, `ERR_CALENDAR_NOT_DRAFT`,
        `ERR_CHARGE_ALREADY_ROUTED`, `ERR_CHARGE_NOT_BILLED_TO_PAYER`,
        `ERR_INVOICE_NOT_SUBMITTABLE`, `ERR_FINDING_NOT_OPEN`,
        `ERR_FINDING_NOT_RESPONDED`, `ERR_AMENDMENT_NOT_SUBMITTED`, and
        `ERR_SUBJECT_NOT_SCREENING` take precedence over the generic code on
        their own endpoints."

        Design: Corner/state_machines/approving_a_draft_analysis_is_refused_as_not_under_review
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = setup_study_with_draft_grid(
            [LAB_PANEL], study_overrides={"protocol_number": "AMC-2390-C16"}
        )
        assert ctx["analysis"]["status"] == "DRAFT"

        validate_error(
            api_client.approve_coverage_analysis(
                ctx["analysis"]["id"], make_reviewer_headers(REVIEWER_ONE)
            ),
            "ERR_ANALYSIS_NOT_UNDER_REVIEW",
            409,
        )

        unchanged = read_analysis(ctx["analysis"]["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["approved_at"] is None
        assert unchanged["approved_by_user_id"] is None
        assert unchanged["version"] == 2
        # The approval cascade that advances the study never ran.
        assert read_study(ctx["study"]["id"])["lifecycle_status"] == "COVERAGE_PENDING"

        # §3.3 states the same code for a return from any other status.
        validate_error(
            api_client.return_coverage_analysis(
                ctx["analysis"]["id"],
                return_analysis_payload(),
                make_reviewer_headers(REVIEWER_ONE),
            ),
            "ERR_ANALYSIS_NOT_UNDER_REVIEW",
            409,
        )
        assert read_analysis(ctx["analysis"]["id"])["return_count"] == 0


class TestCalendarPublicationIsNotReplayable:
    """`PUBLISHED` is not a state publication can be applied to."""

    def test_05_a_second_publish_of_the_same_generation_is_refused(self):
        """The retire-siblings side effect cannot fire twice, and nothing about
        the published generation moves.

        PRD §3.4: "A `ComplianceReviewer` moves a calendar `DRAFT → PUBLISHED`
        only when its source analysis stands at `APPROVED`, it has at least one
        visit, and nothing is left unrouted — a calendar with
        `unrouted_per_patient_item_count` above zero or with `visit_count` at
        zero is refused with `ERR_UNROUTED_PER_PATIENT_ITEM`, and publishing
        something that is not `DRAFT` is `ERR_CALENDAR_NOT_DRAFT`."

        Design: Corner/state_machines/second_publish_of_the_same_calendar_is_refused
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = setup_published_calendar(
            study_overrides={"protocol_number": "AMC-2390-C17"},
            qct_registry_number="NCT10000117",
        )
        published = ctx["calendar"]
        assert published["status"] == "PUBLISHED"
        assert published["published_at"] == INITIAL_LOGICAL_CLOCK_STAMP
        version_after_publish = published["version"]

        validate_error(
            api_client.publish_study_calendar(
                published["id"], make_reviewer_headers(REVIEWER_ONE)
            ),
            "ERR_CALENDAR_NOT_DRAFT",
            409,
        )

        unchanged = read_calendar(published["id"])
        assert unchanged["status"] == "PUBLISHED"
        assert unchanged["published_at"] == published["published_at"]
        assert unchanged["version"] == version_after_publish

        rows, meta = validate_paginated(
            api_client.list_study_calendars(
                make_analyst_headers(ANALYST_ONE),
                params={"study_id": ctx["study"]["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["build_generation"] == 1
        assert rows[0]["status"] == "PUBLISHED"


class TestVisitCompletionAndAccrualClose:
    """The two cascades that reach subject visits."""

    def test_06_completing_one_visit_creates_one_charge_per_route(self):
        """Two routes on the completed visit produce two charges, each priced
        from its own snapshot and each opening unrouted and unbilled.

        PRD §3.6: "On success the server walks the visit charge routes of the
        referenced calendar visit oldest-created first and creates one charge
        per route."

        Design: Corner/state_machines/visit_completion_drops_one_charge_per_visit_charge_route
        """
        ctx = setup_open_to_accrual(
            [LAB_PANEL, INFUSION],
            [visit_spec("Cycle 1 Day 1", 1, 0, 0, 3)],
            [
                route_spec("Cycle 1 Day 1", "80053", occurrences=3),
                route_spec("Cycle 1 Day 1", "J9999"),
            ],
            indirect_rate_pct=32.0,
            clock="2026-09-01T08:00:00Z",
            qct_registry_number="NCT10000118",
            study_overrides={
                "protocol_number": "AMC-2390-C18",
                "funding_source": "INDUSTRY_SPONSORED",
            },
        )
        lab_route, infusion_route = ctx["routes"]
        # 3 occurrences * 1 unit * 9,000 charge-master cents on the payer route.
        assert lab_route["routing_target"] == "PAYER"
        assert lab_route["expected_amount_cents"] == 27000
        # 1 occurrence * 2 units * 40,000 negotiated cents on the sponsor route.
        assert infusion_route["routing_target"] == "SPONSOR"
        assert infusion_route["expected_amount_cents"] == 80000

        setup_consented_subject(ctx, consent_date="2026-09-01")
        setup_scheduled_visit(ctx, actual_service_date="2026-09-02")

        completed = validate_success(
            api_client.complete_subject_visit(
                ctx["subject_visit"]["id"], make_coordinator_headers(COORDINATOR_ONE)
            ),
            200,
        )
        assert completed["status"] == "OCCURRED"
        assert completed["generated_charge_count"] == 2

        rows, meta = validate_paginated(
            api_client.list_charges(
                make_manager_headers(MANAGER_ONE),
                params={"study_id": ctx["study"]["id"]},
            )
        )
        assert meta["total_count"] == 2
        by_item = {row["coverage_item_id"]: row for row in rows}
        lab_charge = by_item[ctx["item_by_code"]["80053"]["id"]]
        infusion_charge = by_item[ctx["item_by_code"]["J9999"]["id"]]

        assert lab_charge["amount_cents"] == 27000
        assert lab_charge["suggested_routing_target"] == "PAYER"
        assert infusion_charge["amount_cents"] == 80000
        assert infusion_charge["suggested_routing_target"] == "SPONSOR"
        for charge in (lab_charge, infusion_charge):
            assert charge["source"] == "VISIT_CASCADE"
            assert charge["routing_state"] == "UNROUTED"
            assert charge["billing_state"] == "UNBILLED"
            assert charge["posted_by_user_id"] is None
            assert charge["subject_visit_id"] == ctx["subject_visit"]["id"]
            assert charge["unbilled_since"] == "2026-09-01T08:00:00.000Z"

        subject = validate_success(
            api_client.get_study_subject(
                ctx["subject"]["id"], make_coordinator_headers(COORDINATOR_ONE)
            )
        )
        assert subject["charge_count"] == 2

        summary = read_summary(ctx["study"]["id"])
        assert summary["unrouted_charge_count"] == 2
        # A cascade-created charge is not routed money yet.
        assert summary["sponsor_unbilled_cents"] == 0
        assert summary["payer_billed_cents"] == 0

    def test_07_closing_accrual_moves_subjects_off_study_and_misses_only_scheduled_visits(self):
        """One request reaches a screening subject, a consented subject and a
        scheduled visit, while the occurred visit and its charge are skipped.

        PRD §3.6: "With `target_status` of `CLOSED_TO_ACCRUAL` the study moves
        `OPEN_TO_ACCRUAL → CLOSED_TO_ACCRUAL`, which is the terminal lifecycle
        state, and cascades downward: every subject of the study whose `status`
        is `SCREENING` or `CONSENTED` moves to `OFF_STUDY`, and for the consented
        ones every subject visit still standing at `SCHEDULED` moves to
        `MISSED`."

        Design: Corner/state_machines/closing_accrual_cascades_subjects_off_study_and_misses_only_scheduled_visits
        """
        ctx = setup_open_to_accrual(
            [item_spec(
                "J9999",
                classification="RESEARCH_PAID",
                budget_category="PER_PATIENT",
                charge_master_unit_cents=50000,
                negotiated_unit_cents=40000,
                expected_occurrences=1,
            )],
            [
                visit_spec("Cycle 1 Day 1", 1, 0, 0, 3),
                visit_spec("Cycle 2 Day 1", 2, 7, 2, 3),
            ],
            [route_spec("Cycle 1 Day 1", "J9999")],
            indirect_rate_pct=32.0,
            clock="2026-09-01T08:00:00Z",
            qct_registry_number="NCT10000119",
            study_overrides={"protocol_number": "AMC-2390-C19"},
        )
        consented = setup_consented_subject(ctx, consent_date="2026-09-01")
        first_visit = setup_scheduled_visit(
            ctx, visit_name="Cycle 1 Day 1", actual_service_date="2026-09-02"
        )
        completed = complete_visit(first_visit["id"])
        assert completed["generated_charge_count"] == 1
        second_visit = schedule_visit(
            consented["id"],
            ctx["visit_by_name"]["Cycle 2 Day 1"]["id"],
            "2026-09-07",
        )
        assert second_visit["status"] == "SCHEDULED"
        screening = register_subject(ctx["study"]["id"], subject_number="S-002")
        assert screening["status"] == "SCREENING"

        closed = close_accrual(ctx["study"]["id"])
        assert closed["lifecycle_status"] == "CLOSED_TO_ACCRUAL"
        # The budget dimension is untouched by the lifecycle close.
        assert closed["budget_status"] == "EXECUTED"

        headers = make_coordinator_headers(COORDINATOR_ONE)
        assert validate_success(
            api_client.get_study_subject(consented["id"], headers)
        )["status"] == "OFF_STUDY"
        assert validate_success(
            api_client.get_study_subject(screening["id"], headers)
        )["status"] == "OFF_STUDY"
        assert validate_success(
            api_client.get_subject_visit(second_visit["id"], headers)
        )["status"] == "MISSED"

        occurred = validate_success(
            api_client.get_subject_visit(first_visit["id"], headers)
        )
        assert occurred["status"] == "OCCURRED"
        assert occurred["generated_charge_count"] == 1

        rows, meta = validate_paginated(
            api_client.list_charges(
                make_manager_headers(MANAGER_ONE),
                params={"study_id": ctx["study"]["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["amount_cents"] == 40000
        assert rows[0]["routing_state"] == "UNROUTED"
        assert rows[0]["billing_state"] == "UNBILLED"
        assert read_calendar(ctx["calendar"]["id"])["status"] == "PUBLISHED"


class TestTerminalStatesRefuseEveryTrigger:
    """A closed finding and an administrative amendment: nothing further fires."""

    def test_08_a_closed_finding_refuses_both_respond_and_resolve(self):
        """`CLOSED_NO_ACTION` is terminal, and the rejected calls neither bump
        the row nor re-decrement the study's finding counter.

        PRD §3.9: "Resolution then takes a `disposition` and forks into two
        disjoint outcomes; resolving a finding that is not `RESPONDED` is
        `ERR_FINDING_NOT_RESPONDED`."

        Design: Corner/state_machines/resolving_a_closed_finding_again_is_refused
        """
        set_clock("2026-08-01T00:00:00Z")
        study = register_study(
            protocol_number="AMC-2390-C15", title="Corner terminal finding"
        )
        finding = open_finding(
            study["id"],
            finding_type="MISSING_REGISTRY_NUMBER",
            claimed_amount_cents=0,
            user_id=LIAISON_ONE,
        )
        assert finding["charge_id"] is None
        respond_finding(finding["id"], user_id=LIAISON_TWO)
        closed = resolve_finding(finding["id"], "NO_ACTION", user_id=LIAISON_TWO)
        assert closed["status"] == "CLOSED_NO_ACTION"
        closed_version = closed["version"]

        validate_error(
            api_client.resolve_audit_finding(
                finding["id"],
                resolve_finding_payload("NO_ACTION"),
                make_liaison_headers(LIAISON_TWO),
            ),
            "ERR_FINDING_NOT_RESPONDED",
            409,
        )
        still = validate_success(
            api_client.get_audit_finding(finding["id"], make_liaison_headers(LIAISON_TWO))
        )
        assert still["status"] == "CLOSED_NO_ACTION"
        assert still["refund_amount_cents"] == 0
        assert still["version"] == closed_version

        # §3.9: "responding to anything not `OPEN` is `ERR_FINDING_NOT_OPEN`".
        validate_error(
            api_client.respond_audit_finding(
                finding["id"],
                respond_finding_payload(),
                make_liaison_headers(LIAISON_ONE),
            ),
            "ERR_FINDING_NOT_OPEN",
            409,
        )
        validate_error(
            api_client.resolve_audit_finding(
                finding["id"],
                resolve_finding_payload("REFUND_AND_REROUTE"),
                make_liaison_headers(LIAISON_TWO),
            ),
            "ERR_FINDING_NOT_RESPONDED",
            409,
        )

        after = read_study(study["id"])
        assert after["open_finding_count"] == 0
        # Clause 3 of the posture rule, not the finding clause.
        assert after["billing_hold_posture"] == "PAYER_BLOCKED"

    def test_09_an_administrative_amendment_fires_only_the_first_cascade_link(self):
        """Both derived booleans are false, so the study's lifecycle, its budget
        dimension and its pending charge all stand still.

        PRD §3.9: "`reanalysis_required` is true for every scope other than
        `ADMINISTRATIVE` — that is, for `ITEM_CHANGE`, `VISIT_SCHEDULE_CHANGE`,
        and `ITEM_AND_SCHEDULE_CHANGE`."

        Design: Corner/state_machines/administrative_amendment_implements_without_rebuilding_anything
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = setup_study_with_approved_analysis(
            [item_spec(
                "J9999",
                classification="RESEARCH_PAID",
                budget_category="PER_PATIENT",
                charge_master_unit_cents=50000,
                negotiated_unit_cents=40000,
                expected_occurrences=1,
            )],
            qct_basis=None,
            study_overrides={"protocol_number": "AMC-2390-C20"},
        )
        assert ctx["study"]["lifecycle_status"] == "COVERAGE_APPROVED"
        charge = post_charge(
            ctx["study"]["id"],
            charge_code="J9999",
            service_date="2026-08-01",
            amount_cents=40000,
        )
        assert charge["hold_reason"] == "NONE"

        amendment = file_amendment(
            ctx["study"]["id"], scope="ADMINISTRATIVE", effective_date="2026-08-01"
        )
        assert amendment["status"] == "SUBMITTED"
        assert amendment["amendment_number"] == 1
        assert amendment["reanalysis_required"] is False
        assert amendment["calendar_rebuild_required"] is False

        implemented = implement_amendment(amendment["id"])
        assert implemented["status"] == "IMPLEMENTED"

        study = read_study(ctx["study"]["id"])
        assert study["lifecycle_status"] == "COVERAGE_APPROVED"
        assert study["budget_status"] == "NOT_BUILT"
        assert study["rebuild_required_calendar_count"] == 0
        assert study["billing_hold_posture"] == "PAYER_BLOCKED"

        assert read_charge(charge["id"])["hold_reason"] == "NONE"
        assert read_analysis(ctx["analysis"]["id"])["status"] == "APPROVED"

        rows, meta = validate_paginated(
            api_client.list_study_amendments(
                ctx["study"]["id"], make_manager_headers(MANAGER_ONE)
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "IMPLEMENTED"
