"""Case pipeline: assignment, evidence-gated advancement, subject resolution,
merge semantics, case summary read, and case list filtering."""
from test_helpers import (
    ApiErrorId,
    attach_evidence,
    advance_case,
    assign_case,
    collect_and_seal,
    confirm_link,
    document_interview,
    draft_demand,
    get_case,
    hold_interview,
    issue_demand,
    make_analyst_headers,
    make_auditor_headers,
    make_employee,
    make_manager_headers,
    make_manual_case,
    make_orc_group,
    make_store,
    post_event,
    propose_link,
    schedule_interview,
    setup_case_investigating,
    setup_case_interviewed,
    setup_case_ready_for_interview,
    the_only_alert,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    ADMIN_1,
    ANALYST_1,
    ANALYST_2,
    AUDITOR_1,
    MANAGER_1,
)


class TestAssignment:
    def test_case_assign_from_investigating_returns_invalid_state(self, api):
        """PRD §3.3: "Work begins when an `LPManager` assigns the case: the
        request names an `analyst_id`, the case records it as
        `assigned_analyst_id`, and the case moves from `OPEN` to
        `INVESTIGATING` — attempting this on a case in any other state yields
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/case_assign_from_investigating_returns_invalid_state
        """
        store = make_store(store_number="S033", name="Store 33")
        ctx = setup_case_investigating(store["id"], manual_loss_cents=1000)
        resp = api.assign_case(
            ctx["case"]["id"], {"analyst_id": ANALYST_2},
            make_manager_headers(MANAGER_1),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_case(ctx["case"]["id"])
        assert after["assigned_analyst_id"] == ANALYST_1, "assignment unchanged"

    def test_case_advance_by_non_assignee_forbidden(self, api):
        """PRD §3.3: "Advancement is assignee-scoped — any other actor fails
        with `ERR_NOT_CASE_ASSIGNEE` — and gated on evidence: at least one
        evidence item of the case must be in `ACTIVE` or `SEALED` status, else
        `ERR_NO_ACTIVE_EVIDENCE`."

        The role is correct (LPAnalyst); the assignment is not.

        Design: Corner/state_machines/case_advance_by_non_assignee_forbidden
        """
        store = make_store(store_number="S034", name="Store 34")
        ctx = setup_case_investigating(store["id"], manual_loss_cents=1000)
        attach_evidence(ctx["case"]["id"], ANALYST_1)
        resp = api.advance_case(ctx["case"]["id"], {}, make_analyst_headers(ANALYST_2))
        validate_error(resp, ApiErrorId.ERR_NOT_CASE_ASSIGNEE)
        assert get_case(ctx["case"]["id"])["status"] == "INVESTIGATING"


class TestAdvanceEvidenceGate:
    def test_advance_without_evidence_rejected(self, api):
        """PRD §3.3: "Advancement is assignee-scoped — any other actor fails
        with `ERR_NOT_CASE_ASSIGNEE` — and gated on evidence: at least one
        evidence item of the case must be in `ACTIVE` or `SEALED` status, else
        `ERR_NO_ACTIVE_EVIDENCE`."

        Zero ACTIVE|SEALED items: the gate rejects and the case does not move.

        Design: Difficulty/boundary_precision_check/advance_evidence_empty_set_vs_singleton
        """
        store = make_store(store_number="S202", name="Store 202")
        ctx = setup_case_investigating(store["id"], manual_loss_cents=10000)
        resp = api.advance_case(ctx["case"]["id"], {}, make_analyst_headers(ANALYST_1))
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_EVIDENCE)
        assert get_case(ctx["case"]["id"])["status"] == "INVESTIGATING", (
            "no partial transition on the rejected advance"
        )

    def test_advance_with_single_evidence_item_succeeds(self, api):
        """PRD §3.3: "Advancement is assignee-scoped — any other actor fails
        with `ERR_NOT_CASE_ASSIGNEE` — and gated on evidence: at least one
        evidence item of the case must be in `ACTIVE` or `SEALED` status, else
        `ERR_NO_ACTIVE_EVIDENCE`."

        Exactly one ACTIVE evidence item crosses the gate.

        Design: Difficulty/boundary_precision_check/advance_evidence_empty_set_vs_singleton
        """
        store = make_store(store_number="S202", name="Store 202")
        ctx = setup_case_investigating(store["id"], manual_loss_cents=10000)
        attach_evidence(ctx["case"]["id"], ANALYST_1, evidence_type="AUDIO")
        advanced = advance_case(ctx["case"]["id"], ANALYST_1)
        assert advanced["status"] == "READY_FOR_INTERVIEW"


class TestRecoveredValueGate:
    def test_recovered_value_exceeds_attributable_loss_rejected(self, api):
        """PRD §3.3: "The advance request may record a `recovered_value_cents`
        figure for recovered merchandise, which must not exceed the
        member-alert event sum plus `manual_loss_cents`
        (`ERR_RECOVERED_EXCEEDS_LOSS`); the value is stored and
        `total_loss_cents` recomputed."
        PRD §3.3: "The case's headline figure, `total_loss_cents`, is always
        derived the same way: take the sum of `amount_cents` over every
        exception event aggregated into alerts whose `case_id` points at this
        case, add `manual_loss_cents` (zero for alert-sourced cases, the
        variance magnitude for shrink auto-cases), subtract
        `recovered_value_cents`, and floor the result at zero."

        Design: Corner/validations/recovered_value_exceeds_attributable_loss_rejected
        """
        store = make_store(store_number="S065", name="Store 65")
        ctx = setup_case_investigating(store["id"], manual_loss_cents=10000)
        attach_evidence(ctx["case"]["id"], ANALYST_1)
        resp = api.advance_case(
            ctx["case"]["id"], {"recovered_value_cents": 10001},
            make_analyst_headers(ANALYST_1),
        )
        validate_error(resp, ApiErrorId.ERR_RECOVERED_EXCEEDS_LOSS)
        ok = advance_case(ctx["case"]["id"], ANALYST_1, recovered_value_cents=5000)
        assert ok["status"] == "READY_FOR_INTERVIEW"
        assert ok["total_loss_cents"] == 5000, "10000 manual loss - 5000 recovered"


class TestInterviewDocumentGate:
    def test_advance_blocked_while_interview_only_held(self, api):
        """PRD §3.3: "There is deliberately no advancement out of
        `READY_FOR_INTERVIEW` through this capability — only the interview
        pipeline, described next, moves the case past that point."

        A HELD (not yet DOCUMENTED) interview does not move the parent case;
        calling advance on READY_FOR_INTERVIEW is rejected.

        Design: Difficulty/cross_entity_state_dependency/case_interviewed_gate_driven_by_interview_document
        """
        store = make_store(store_number="S210", name="Store 210")
        ctx = setup_case_ready_for_interview(store["id"], manual_loss_cents=20000)
        interview = schedule_interview(ctx["case"]["id"], ANALYST_1, ANALYST_1)
        hold_interview(interview["id"], ANALYST_1, outcome="ADMITTED")
        resp = api.advance_case(ctx["case"]["id"], {}, make_analyst_headers(ANALYST_1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_documented_interview_drives_case_to_interviewed(self, api):
        """PRD §3.4: "If the parent case is sitting in `READY_FOR_INTERVIEW`,
        documenting the interview advances the case to `INTERVIEWED`; this
        system-driven transition is the only road out of `READY_FOR_INTERVIEW`."
        PRD §3.5: "With at least one documented interview in hand, the assigned
        analyst advances the case from `INTERVIEWED` to `ADJUDICATING`."

        Design: Difficulty/cross_entity_state_dependency/case_interviewed_gate_driven_by_interview_document
        """
        store = make_store(store_number="S210", name="Store 210")
        ctx = setup_case_ready_for_interview(store["id"], manual_loss_cents=20000)
        interview = schedule_interview(ctx["case"]["id"], ANALYST_1, ANALYST_1)
        hold_interview(interview["id"], ANALYST_1, outcome="ADMITTED")
        document_interview(interview["id"], ANALYST_1, notes="Now documented.")
        assert get_case(ctx["case"]["id"])["status"] == "INTERVIEWED"
        advanced = advance_case(ctx["case"]["id"], ANALYST_1)
        assert advanced["status"] == "ADJUDICATING"


class TestSubjectResolution:
    def test_unknown_subject_blocks_adjudicating_until_resolved(self, api):
        """PRD §3.5: "One further gate applies here: the case's `subject_type`
        must by then be `EMPLOYEE` or `EXTERNAL` — advancing a still-`UNKNOWN`
        case fails with `ERR_SUBJECT_UNRESOLVED`."
        PRD §3.3: "While a case is `INVESTIGATING` or `READY_FOR_INTERVIEW`, an
        `LPManager` may resolve or correct its subject, updating `subject_type`
        and `employee_id` without any status change."
        PRD §3.3: "This is how an `UNKNOWN`-subject shrink auto-case becomes
        adjudicable."

        An INTERVIEWED-but-UNKNOWN case cannot advance; resolving the subject
        while a second case is still INVESTIGATING (a legal resolve-subject
        state) lets that case complete the path to ADJUDICATING.

        Design: Corner/errors/unknown_subject_blocks_adjudicating_until_resolved
        """
        store = make_store(store_number="S091", name="Store 91")
        ctx = setup_case_interviewed(
            store["id"], subject_type="UNKNOWN", manual_loss_cents=10000,
            outcome="DENIED",
        )
        resp = api.advance_case(ctx["case"]["id"], {}, make_analyst_headers(ANALYST_1))
        validate_error(resp, ApiErrorId.ERR_SUBJECT_UNRESOLVED)
        # The resolution path: resolve while INVESTIGATING, then walk the case
        # through evidence/interview to ADJUDICATING.
        ctx2 = setup_case_investigating(
            store["id"], subject_type="UNKNOWN", manual_loss_cents=10000,
        )
        resolved = validate_success(api.resolve_case_subject(
            ctx2["case"]["id"], {"subject_type": "EXTERNAL"},
            make_manager_headers(MANAGER_1),
        ))
        assert resolved["subject_type"] == "EXTERNAL"
        assert resolved["status"] == "INVESTIGATING", "no status change"
        attach_evidence(ctx2["case"]["id"], ANALYST_1)
        advance_case(ctx2["case"]["id"], ANALYST_1)
        interview = schedule_interview(ctx2["case"]["id"], ANALYST_1, ANALYST_1)
        hold_interview(interview["id"], ANALYST_1, outcome="ADMITTED")
        document_interview(interview["id"], ANALYST_1)
        advanced = advance_case(ctx2["case"]["id"], ANALYST_1)
        assert advanced["status"] == "ADJUDICATING"


class TestMerge:
    def _setup_merge_pair(self, api, store_id):
        """C1: alert-sourced (event sum 75000), recovered 5000 -> total 70000.
        C2: manual 30000 -> total 30000. Returns (c1, c2, alert_id)."""
        post_event(store_id, "HIGH_VALUE_VOID", 40000, "2026-07-12T10:00:00Z",
                   register_ref="R09", txn_ref="TX1")
        post_event(store_id, "HIGH_VALUE_VOID", 35000, "2026-07-12T11:00:00Z",
                   register_ref="R09", txn_ref="TX2")
        alert = the_only_alert(store_id)
        resp = api.convert_alert(
            alert["id"], {"subject_type": "EXTERNAL"},
            make_analyst_headers(ANALYST_1),
        )
        c1 = validate_success(resp, expected_status=201)
        assign_case(c1["id"], ANALYST_1)
        attach_evidence(c1["id"], ANALYST_1, evidence_type="VIDEO_CLIP",
                        captured_at="2026-07-12T10:00:00Z")
        c1 = advance_case(c1["id"], ANALYST_1, recovered_value_cents=5000)
        c2 = make_manual_case(store_id, manual_loss_cents=30000)
        assign_case(c2["id"], ANALYST_1)
        return c1, c2, alert["id"]

    def test_merge_conserves_total_loss(self, api):
        """PRD §3.5: "The target absorbs the source's `manual_loss_cents` and
        `recovered_value_cents` into its own and recomputes `total_loss_cents`."
        PRD §3.5: "Because the advance-time gate guarantees each case's
        recovered value never exceeds its event sum plus manual loss, every
        case's raw figure is non-negative, so the merge conserves loss exactly:
        the target's total afterwards equals the sum of the two cases' totals
        beforehand."

        Design: Difficulty/compensating_invariant/merge_conserves_attributed_loss_sum
        """
        store = make_store(store_number="S231", name="Store 231")
        c1, c2, _alert_id = self._setup_merge_pair(api, store["id"])
        assert c1["total_loss_cents"] == 70000, "75000 event sum - 5000 recovered"
        assert get_case(c2["id"])["total_loss_cents"] == 30000
        resp = api.merge_case(
            c1["id"], {"target_case_id": c2["id"]}, make_manager_headers(MANAGER_1)
        )
        validate_success(resp)
        target = get_case(c2["id"])
        assert target["total_loss_cents"] == 100000, "70000 + 30000 conserved exactly"
        assert target["manual_loss_cents"] == 30000, "30000 + 0 absorbed"
        assert target["recovered_value_cents"] == 5000, "0 + 5000 absorbed"

    def test_merge_marks_source_and_repoints_alerts(self, api):
        """PRD §3.5: "The merge stamps the source's `merged_into_case_id` to
        the target, re-points the source's alerts so their `case_id` names the
        target, re-parents the source's evidence items onto the target, cancels
        the source's `SCHEDULED` interviews (its `HELD` and `DOCUMENTED`
        interviews stay on the source for audit), and cancels its `DRAFT`
        demands."
        PRD §3.5: "The source ends in `MERGED`, a terminal state, and from then
        on contributes to ORC exposure only through its surviving target."

        Design: Difficulty/compensating_invariant/merge_conserves_attributed_loss_sum
        """
        store = make_store(store_number="S231", name="Store 231")
        c1, c2, _alert_id = self._setup_merge_pair(api, store["id"])
        resp = api.merge_case(
            c1["id"], {"target_case_id": c2["id"]}, make_manager_headers(MANAGER_1)
        )
        source = validate_success(resp)
        assert source["status"] == "MERGED"
        assert source["merged_into_case_id"] == c2["id"]
        headers = make_manager_headers(MANAGER_1)
        d_src, m_src = validate_paginated(
            api.list_alerts(headers, params={"case_id": c1["id"]})
        )
        d_tgt, m_tgt = validate_paginated(
            api.list_alerts(headers, params={"case_id": c2["id"]})
        )
        assert m_src["total_count"] == 0 and d_src == []
        assert m_tgt["total_count"] == 1 and d_tgt[0]["id"] == _alert_id

    def test_merge_into_terminal_or_self_rejected(self, api):
        """PRD §3.5: "An `LPManager` merges a source case that is
        `INVESTIGATING` or `READY_FOR_INTERVIEW` into a surviving target named
        by `target_case_id`; the merge is refused with `ERR_MERGE_NOT_ALLOWED`
        when the source is in any other state, when the target does not exist,
        equals the source, or is terminal or already `MERGED`."

        Design: Corner/errors/merge_into_terminal_or_self_rejected
        """
        store = make_store(store_number="S086", name="Store 86")
        c1 = make_manual_case(store["id"], manual_loss_cents=1000)
        c3 = make_manual_case(store["id"], manual_loss_cents=2000)
        assign_case(c1["id"], ANALYST_1)
        assign_case(c3["id"], ANALYST_1)
        # C3 dismissed early -> CLOSED_UNSUBSTANTIATED (terminal for merge targeting).
        validate_success(api.dismiss_case(
            c3["id"], {"reason": "no evidence"}, make_manager_headers(MANAGER_1)
        ))
        resp1 = api.merge_case(
            c1["id"], {"target_case_id": c3["id"]}, make_manager_headers(MANAGER_1)
        )
        validate_error(resp1, ApiErrorId.ERR_MERGE_NOT_ALLOWED)
        resp2 = api.merge_case(
            c1["id"], {"target_case_id": c1["id"]}, make_manager_headers(MANAGER_1)
        )
        validate_error(resp2, ApiErrorId.ERR_MERGE_NOT_ALLOWED)
        assert get_case(c1["id"])["status"] == "INVESTIGATING"

    def test_case_merged_terminal_lockdown(self, api):
        """PRD §3.5: "The source ends in `MERGED`, a terminal state, and from
        then on contributes to ORC exposure only through its surviving target."
        PRD §2.7: "6. The target entity's own state machine must permit the
        requested transition (`ERR_INVALID_STATE_TRANSITION`, or
        `ERR_DEMAND_NOT_PAYABLE` for a payment posting against a demand that is
        not payable)."

        Design: Corner/state_machines/case_merged_terminal_lockdown
        """
        store = make_store(store_number="S036", name="Store 36")
        c1 = make_manual_case(store["id"], manual_loss_cents=1000)
        c2 = make_manual_case(store["id"], manual_loss_cents=2000)
        assign_case(c1["id"], ANALYST_1)
        assign_case(c2["id"], ANALYST_1)
        validate_success(api.merge_case(
            c1["id"], {"target_case_id": c2["id"]}, make_manager_headers(MANAGER_1)
        ))
        resp1 = api.advance_case(c1["id"], {}, make_analyst_headers(ANALYST_1))
        validate_error(resp1, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        resp2 = api.dismiss_case(
            c1["id"], {"reason": "try"}, make_manager_headers(MANAGER_1)
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_case(c1["id"])["status"] == "MERGED"
        assert get_case(c2["id"])["status"] == "INVESTIGATING"


class TestCaseSummaryAndFilters:
    def test_case_summary_computed_read(self, api):
        """PRD §3.3: "A computed summary read accompanies the detail read and
        reports the case's `case_id`, current `total_loss_cents`,
        `evidence_count`, `sealed_evidence_count`,
        `documented_interview_count`, `demand_outstanding_cents`,
        `confirmed_link_count`, and `restitution_status`."
        PRD §3.6: "Issuance stamps `issued_at` and flips the case's
        `restitution_status` to `OUTSTANDING`."

        Design: Corner/endpoints/case_summary_computed_read
        """
        store = make_store(store_number="S214", name="Store 214")
        group = make_orc_group("Ring Eta")
        ctx = setup_case_ready_for_interview(store["id"], manual_loss_cents=30000,
                                             evidence_type="VIDEO_CLIP")
        ev1 = ctx["evidence"]
        ev2 = attach_evidence(ctx["case"]["id"], ANALYST_1,
                              captured_at="2026-07-15T11:00:00Z")
        collect_and_seal(ev1["id"], ANALYST_1)
        interview = schedule_interview(ctx["case"]["id"], ANALYST_1, ANALYST_1)
        hold_interview(interview["id"], ANALYST_1)
        document_interview(interview["id"], ANALYST_1)
        demand = draft_demand(ctx["case"]["id"], ANALYST_1, basis="STATUTORY",
                              priors_offense_count=0)
        issue_demand(demand["id"], MANAGER_1)
        link = propose_link(ctx["case"]["id"], group["id"], link_score=80)
        confirm_link(link["id"], MANAGER_1)

        resp = api.get_case_summary(ctx["case"]["id"], make_auditor_headers(AUDITOR_1))
        summary = validate_success(resp)
        assert summary["case_id"] == ctx["case"]["id"]
        assert summary["total_loss_cents"] == 30000
        assert summary["evidence_count"] == 2
        assert summary["sealed_evidence_count"] == 1
        assert summary["documented_interview_count"] == 1
        # STATUTORY on 30000: tier1 penalty 10000 -> amount_due 40000.
        assert summary["demand_outstanding_cents"] == 40000
        assert summary["confirmed_link_count"] == 1
        assert summary["restitution_status"] == "OUTSTANDING"

    def test_list_filter_cases_by_status_and_subject(self, api):
        """PRD §3.3: "Cases can be listed with filters on `store_id`,
        `employee_id`, `status`, `subject_type`, `source`,
        `merged_into_case_id`, `loss_posted_period_id`, and `priority`."
        PRD §2.2: "The `data` field contains the resource object or an array of
        resource objects."

        Filters compose; a filter matching nothing is an empty success.

        Design: Corner/endpoints/list_filter_cases_by_status_and_subject
        """
        store = make_store(store_number="S212", name="Store 212")
        emp = make_employee(store["id"], employee_ref="E-212", full_name="Emp 212")
        c1 = make_manual_case(store["id"], subject_type="EMPLOYEE",
                              employee_id=emp["id"], manual_loss_cents=1000)
        make_manual_case(store["id"], subject_type="EXTERNAL", manual_loss_cents=2000)
        c3 = make_manual_case(store["id"], subject_type="EMPLOYEE",
                              employee_id=emp["id"], manual_loss_cents=3000)
        assign_case(c3["id"], ANALYST_1)
        headers = make_analyst_headers(ANALYST_1)
        data, meta = validate_paginated(api.list_cases(
            headers,
            params={"store_id": store["id"], "status": "OPEN",
                    "subject_type": "EMPLOYEE"},
        ))
        assert meta["total_count"] == 1 and data[0]["id"] == c1["id"]
        data2, meta2 = validate_paginated(api.list_cases(
            headers, params={"store_id": store["id"], "status": "MERGED"}
        ))
        assert meta2["total_count"] == 0 and data2 == []
