"""Disputes and re-investigation: parallel-dimension hold cycle, deadline
extension, amendment cascades, windows, and pinned-matrix re-evaluation."""
from test_helpers import (
    ApiErrorId,
    assert_dispute,
    assert_instant_equals,
    create_candidate_payload,
    create_dispute_payload,
    create_matrix_payload,
    create_order_payload,
    create_report_payload,
    finding,
    get_success_data,
    make_candidate_headers,
    make_compliance_officer_headers,
    make_vendor_agent_headers,
    setup_disputed_order,
    setup_pre_adverse_case,
    setup_report_received,
    setup_screening_config,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    TEST_USERS,
)

HR = TEST_USERS["hr_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]

IA_FINDINGS = [
    finding(
        offense_category="NONVIOLENT_FELONY", severity="MEDIUM",
        offense_date="2024-02-01T00:00:00Z",
    )
]
IA_MATRIX_RULES = [
    {
        "offense_category": "NONVIOLENT_FELONY",
        "min_severity": "LOW",
        "max_recency_years": 99,
        "action": "IA_REQUIRED",
    }
]
ADVERSE_FINDINGS = [finding()]


class TestParallelDimensionsDisputeCycle:
    def _setup(self, api, tag):
        return setup_report_received(
            tag=tag,
            matrix_rules=IA_MATRIX_RULES,
            findings=IA_FINDINGS,
            deliver_at="2026-08-06T10:00:00Z",
        )

    def test_dispute_moves_only_adjudication_dimension(self, api):
        """PRD section "Parallel State Dimensions and Hierarchical Cascades":
        "a candidate dispute moves only `adjudication_status` to `DISPUTE_HOLD`
        while fulfillment stays at `REPORT_RECEIVED`." and PRD section
        "Disputes and Re-Investigation": "moves the report to `DISPUTED`"."

        Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_dispute_cycle
        """
        ctx = self._setup(api, "NL1")
        dispute = validate_success(
            api.create_dispute(
                create_dispute_payload(
                    ctx["order"]["id"], reason="record belongs to someone else"
                ),
                make_candidate_headers(ctx["candidate"]["id"]),
            ),
            expected_status=201,
        )
        assert_dispute(dispute)
        assert dispute["status"] == "UNDER_REINVESTIGATION"

        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["adjudication_status"] == "DISPUTE_HOLD"
        assert order["fulfillment_status"] == "REPORT_RECEIVED"
        report = get_success_data(api.get_report(ctx["report"]["id"], HR))
        assert report["status"] == "DISPUTED"

    def test_resolve_upheld_closes_the_cycle(self, api):
        """PRD section "Disputes and Re-Investigation": "Upholding returns the
        report from `DISPUTED` to `UPHELD`, returns the order's adjudication
        from `DISPUTE_HOLD` to `PENDING_REVIEW`, stamps the dispute's
        `resolved_at`"."

        Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_dispute_cycle
        """
        ctx = self._setup(api, "NL1B")
        dispute = get_success_data(
            api.create_dispute(
                create_dispute_payload(
                    ctx["order"]["id"], reason="record belongs to someone else"
                ),
                make_candidate_headers(ctx["candidate"]["id"]),
            )
        )
        resolved = validate_success(
            api.resolve_dispute(
                dispute["id"], {"outcome": "UPHELD"},
                make_vendor_agent_headers(ctx["vendor"]["id"]),
            )
        )
        assert resolved["status"] == "RESOLVED_UPHELD"
        assert resolved["outcome"] == "UPHELD"
        assert resolved["resolved_at"] is not None

        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["adjudication_status"] == "PENDING_REVIEW"
        assert order["fulfillment_status"] == "REPORT_RECEIVED"
        report = get_success_data(api.get_report(ctx["report"]["id"], HR))
        assert report["status"] == "UPHELD"


class TestHoldCycleDeadlineExtension:
    def _setup(self, api, tag):
        """Case created Wed 2026-08-05T10:00 (earliest 2026-08-12); dispute
        filed Thu 2026-08-06T09:00; resolved UPHELD Tue 2026-08-11T15:00."""
        ctx = setup_pre_adverse_case(
            tag=tag,
            adjudicator_id="adj-nl2",
            findings=ADVERSE_FINDINGS,
            consent_signed_at="2026-08-03T09:00:00Z",
            dispatch_at="2026-08-03T09:00:00Z",
            deliver_at="2026-08-04T10:00:00Z",
            initiate_at="2026-08-05T10:00:00Z",
        )
        get_success_data(api.set_clock("2026-08-06T09:00:00Z"))
        ctx["dispute"] = get_success_data(
            api.create_dispute(
                create_dispute_payload(
                    ctx["order"]["id"], reason="contesting the felony record"
                ),
                make_candidate_headers(ctx["candidate"]["id"]),
            )
        )
        return ctx

    def test_hold_close_restores_waiting_period_with_hold_days(self, api):
        """PRD section "Disputes and Re-Investigation": "if a case was on hold —
        moves it back to `WAITING_PERIOD` while extending the deadline: the
        business days spanned by the hold, counting from the day after the
        hold-start date through the resolution date inclusive, are added into
        `total_hold_business_days`, `hold_started_at` clears to null"."

        Design: Difficulty/non_linear_state_machine/adverse_case_waiting_hold_cycle_with_deadline_extension
        """
        ctx = self._setup(api, "NL2")
        case = get_success_data(api.get_case(ctx["case"]["id"], CO))
        assert case["status"] == "DISPUTE_HOLD"
        assert case["hold_started_at"] is not None

        get_success_data(api.set_clock("2026-08-11T15:00:00Z"))
        validate_success(
            api.resolve_dispute(
                ctx["dispute"]["id"], {"outcome": "UPHELD"},
                make_vendor_agent_headers(ctx["vendor"]["id"]),
            )
        )
        case = get_success_data(api.get_case(ctx["case"]["id"], CO))
        assert case["status"] == "WAITING_PERIOD"
        # Business days in (2026-08-06, 2026-08-11] = Aug 7, 10, 11 -> 3.
        assert case["total_hold_business_days"] == 3
        assert case["hold_started_at"] is None

    def test_deadline_recomputed_with_accumulated_hold(self, api):
        """PRD section "Disputes and Re-Investigation": "`earliest_final_notice_at`
        is recomputed from `pre_notice_sent_at` using the required wait plus the
        accumulated hold days."

        Design: Difficulty/non_linear_state_machine/adverse_case_waiting_hold_cycle_with_deadline_extension
        """
        ctx = self._setup(api, "NL2B")
        get_success_data(api.set_clock("2026-08-11T15:00:00Z"))
        validate_success(
            api.resolve_dispute(
                ctx["dispute"]["id"], {"outcome": "UPHELD"},
                make_vendor_agent_headers(ctx["vendor"]["id"]),
            )
        )
        case = get_success_data(api.get_case(ctx["case"]["id"], CO))
        # business_day_add(2026-08-05, 5 + 3): Aug 6,7,10,11,12,13,14,17.
        assert_instant_equals(
            case["earliest_final_notice_at"],
            "2026-08-17T00:00:00Z",
            "earliest_final_notice_at after hold",
        )


class TestAmendedCascadeChain:
    def _setup(self, api, tag):
        ctx = setup_pre_adverse_case(
            tag=tag,
            adjudicator_id="adj-tc1",
            findings=ADVERSE_FINDINGS,
            consent_signed_at="2026-08-03T09:00:00Z",
            dispatch_at="2026-08-03T09:00:00Z",
            deliver_at="2026-08-04T10:00:00Z",
            initiate_at="2026-08-05T10:00:00Z",
        )
        get_success_data(api.set_clock("2026-08-06T09:00:00Z"))
        ctx["dispute"] = get_success_data(
            api.create_dispute(
                create_dispute_payload(
                    ctx["order"]["id"], reason="felony record is not mine"
                ),
                make_candidate_headers(ctx["candidate"]["id"]),
            )
        )
        return ctx

    CORRECTED = [
        finding(
            offense_category="INFRACTION", severity="LOW",
            offense_date="2024-01-01T00:00:00Z", disposition="DISMISSED",
        )
    ]

    def test_amendment_mutates_report_and_dispute(self, api):
        """PRD section "Disputes and Re-Investigation": "Amendment replaces the
        report's findings with the corrected set ... The report becomes
        `AMENDED`" and "the dispute's own status lands in the corresponding
        terminal state: ... `RESOLVED_AMENDED` after an amended one" and "the
        dispute's `overdue` flag is computed: true when `resolved_at` falls
        later than thirty calendar days after `filed_at`"."

        Design: Difficulty/transitive_cascade/dispute_amended_report_case_abort_chain
        """
        ctx = self._setup(api, "TC1")
        get_success_data(api.set_clock("2026-08-07T10:00:00Z"))
        resolved = validate_success(
            api.resolve_dispute(
                ctx["dispute"]["id"],
                {"outcome": "AMENDED", "corrected_findings": self.CORRECTED},
                make_vendor_agent_headers(ctx["vendor"]["id"]),
            )
        )
        assert resolved["status"] == "RESOLVED_AMENDED"
        assert resolved["outcome"] == "AMENDED"
        # Filed 2026-08-06T09:00, resolved 2026-08-07T10:00: within 30 days.
        assert resolved["overdue"] is False

        report = get_success_data(api.get_report(ctx["report"]["id"], HR))
        assert report["status"] == "AMENDED"

    def test_amendment_reevaluates_order_and_aborts_case(self, api):
        """PRD section "Disputes and Re-Investigation": "re-computes every
        finding's `considerable` flag and `matched_action` against the currently
        active jurisdiction rule but — critically — against the order's pinned
        matrix" and "any held adverse-action case cascades to `ABORTED` — the
        pre-adverse process must restart on the amended report — while the
        order's adjudication returns to `PENDING_REVIEW`."

        Design: Difficulty/transitive_cascade/dispute_amended_report_case_abort_chain
        """
        ctx = self._setup(api, "TC1B")
        get_success_data(api.set_clock("2026-08-07T10:00:00Z"))
        validate_success(
            api.resolve_dispute(
                ctx["dispute"]["id"],
                {"outcome": "AMENDED", "corrected_findings": self.CORRECTED},
                make_vendor_agent_headers(ctx["vendor"]["id"]),
            )
        )
        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["adjudication_status"] == "PENDING_REVIEW"
        # The amended INFRACTION finding matches no matrix rule -> CLEAR.
        assert order["recommended_outcome"] == "CLEAR"

        case = get_success_data(api.get_case(ctx["case"]["id"], CO))
        assert case["status"] == "ABORTED"


class TestDisputeTerminalAndWindowRules:
    def test_double_resolve_dispute_rejected(self, api):
        """PRD section "Disputes and Re-Investigation": "may resolve the dispute
        as `UPHELD`, requiring the dispute to be `UNDER_REINVESTIGATION` (else
        `ERR_DISPUTE_NOT_OPEN`)."

        Design: Corner/state_machines/double_resolve_dispute_rejected
        """
        ctx = setup_disputed_order(
            tag="SM5",
            matrix_rules=IA_MATRIX_RULES,
            findings=IA_FINDINGS,
            dispute_reason="record is inaccurate here",
            deliver_at="2026-08-06T10:00:00Z",
        )
        get_success_data(api.set_clock("2026-08-07T10:00:00Z"))
        validate_success(
            api.resolve_dispute(
                ctx["dispute"]["id"], {"outcome": "UPHELD"},
                make_vendor_agent_headers(ctx["vendor"]["id"]),
            )
        )
        resp = api.resolve_dispute(
            ctx["dispute"]["id"], {"outcome": "UPHELD"},
            make_vendor_agent_headers(ctx["vendor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_NOT_OPEN)
        dispute = get_success_data(api.get_dispute(ctx["dispute"]["id"], HR))
        assert dispute["status"] == "RESOLVED_UPHELD"

    def test_redispatch_dispute_of_amended_report_allowed(self, api):
        """PRD section "Disputes and Re-Investigation": "An amended report may
        be disputed once more: the report state machine permits `AMENDED` back
        to `DISPUTED` on a fresh filing."

        Design: Corner/state_machines/redispatch_dispute_of_amended_report_allowed
        """
        ctx = setup_disputed_order(
            tag="SM10",
            matrix_rules=IA_MATRIX_RULES,
            findings=IA_FINDINGS,
            dispute_reason="wrong disposition reported",
            deliver_at="2026-08-06T10:00:00Z",
        )
        get_success_data(api.set_clock("2026-08-07T10:00:00Z"))
        validate_success(
            api.resolve_dispute(
                ctx["dispute"]["id"],
                {
                    "outcome": "AMENDED",
                    "corrected_findings": [
                        finding(
                            offense_category="NONVIOLENT_FELONY",
                            severity="MEDIUM",
                            offense_date="2024-02-01T00:00:00Z",
                            disposition="DISMISSED",
                        )
                    ],
                },
                make_vendor_agent_headers(ctx["vendor"]["id"]),
            )
        )
        # Fresh dispute on the AMENDED report succeeds.
        dispute2 = validate_success(
            api.create_dispute(
                create_dispute_payload(
                    ctx["order"]["id"], reason="amended record still wrong"
                ),
                make_candidate_headers(ctx["candidate"]["id"]),
            ),
            expected_status=201,
        )
        assert dispute2["status"] == "UNDER_REINVESTIGATION"
        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["adjudication_status"] == "DISPUTE_HOLD"
        report = get_success_data(api.get_report(ctx["report"]["id"], HR))
        assert report["status"] == "DISPUTED"

    def test_dispute_window_thirty_day_boundary(self, api):
        """PRD section "Disputes and Re-Investigation": "The dispute window is
        thirty calendar days: filing is permitted only while the current logical
        time is no later than `delivered_at` plus thirty days, else
        `ERR_DISPUTE_WINDOW_CLOSED`."

        Design: Corner/calculations/dispute_window_thirty_day_boundary
        """
        # Two independent orders, both delivered 2026-08-10T09:00:00Z; the
        # window closes at 2026-09-09T09:00:00Z. Exercise the boundary success
        # first so the clock never moves backward.
        ctx = setup_screening_config(tag="CC7", matrix_rules=IA_MATRIX_RULES)
        get_success_data(api.set_clock("2026-08-10T08:00:00Z"))
        orders = []
        for name, email in (("Cc SevenA", "cc7a@x.com"), ("Cc SevenB", "cc7b@x.com")):
            cand = get_success_data(
                api.create_candidate(
                    create_candidate_payload(full_name=name, email=email), HR
                )
            )
            order = get_success_data(
                api.create_order(
                    create_order_payload(cand["id"], ctx["position"]["id"]), HM
                )
            )
            get_success_data(
                api.capture_consent(
                    order["id"],
                    {
                        "disclosure_form_id": "DISC-1",
                        "contains_extraneous_terms": False,
                        "authorization_signed_at": "2026-08-10T08:00:00Z",
                    },
                    make_candidate_headers(cand["id"]),
                )
            )
            get_success_data(
                api.dispatch_order(order["id"], ctx["vendor"]["id"], HM)
            )
            orders.append((order, cand))
        get_success_data(api.set_clock("2026-08-10T09:00:00Z"))
        for order, _cand in orders:
            get_success_data(
                api.create_report(
                    create_report_payload(order["id"], findings=list(IA_FINDINGS)),
                    make_vendor_agent_headers(ctx["vendor"]["id"]),
                )
            )

        # Exactly at delivered_at + 30 days: accepted.
        get_success_data(api.set_clock("2026-09-09T09:00:00Z"))
        at_edge = validate_success(
            api.create_dispute(
                create_dispute_payload(
                    orders[0][0]["id"], reason="exactly at the window edge"
                ),
                make_candidate_headers(orders[0][1]["id"]),
            ),
            expected_status=201,
        )
        assert at_edge["status"] == "UNDER_REINVESTIGATION"

        # One second past the window: closed.
        get_success_data(api.set_clock("2026-09-09T09:00:01Z"))
        resp = api.create_dispute(
            create_dispute_payload(
                orders[1][0]["id"], reason="one second past the window"
            ),
            make_candidate_headers(orders[1][1]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED)

    def test_dispute_after_final_adverse_rejected(self, api):
        """PRD section "Disputes and Re-Investigation": "the order's
        adjudication must be `PENDING_REVIEW` or `PRE_ADVERSE_PENDING`, else
        `ERR_ORDER_ADJUDICATION_TERMINAL`."

        Design: Corner/state_machines/dispute_after_final_adverse_rejected
        """
        ctx = setup_pre_adverse_case(
            tag="SM7",
            adjudicator_id="adj-sm7",
            findings=ADVERSE_FINDINGS,
            consent_signed_at="2026-08-03T09:00:00Z",
            dispatch_at="2026-08-03T09:00:00Z",
            deliver_at="2026-08-04T10:00:00Z",
            initiate_at="2026-08-05T10:00:00Z",
        )
        get_success_data(api.set_clock("2026-08-12T00:00:00Z"))
        validate_success(
            api.send_final_notice(
                ctx["case"]["id"], make_compliance_officer_headers("co-sm7")
            )
        )
        resp = api.create_dispute(
            create_dispute_payload(
                ctx["order"]["id"], reason="too late but trying anyway"
            ),
            make_candidate_headers(ctx["candidate"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_ADJUDICATION_TERMINAL)


class TestSingleActiveInvariants:
    def test_double_finalize_and_double_open_dispute(self, api):
        """PRD section "Accuracy Audits and the Re-Screen Sweep": "Finalization,
        the `Auditor`'s second exclusive act, requires `DRAFT` status (else
        `ERR_AUDIT_NOT_DRAFT`)" and PRD section "Disputes and Re-Investigation":
        "Only one open dispute per order is permitted: a second filing while one
        is `UNDER_REINVESTIGATION` is rejected with `ERR_DISPUTE_ALREADY_OPEN`."

        Design: Corner/validations/double_finalize_and_double_open_dispute
        """
        vendor = get_success_data(
            api.create_vendor(
                {"name": "V-VL7", "base_tat_business_hours": 40,
                 "max_concurrent_orders": 5},
                HR,
            )
        )
        audit = get_success_data(
            api.create_audit(
                {
                    "vendor_id": vendor["id"],
                    "period_start": "2026-01-01T00:00:00Z",
                    "period_end": "2026-02-01T00:00:00Z",
                    "sample_size": 50,
                    "mismatches_found": 1,
                },
                TEST_USERS["auditor_headers"],
            )
        )
        validate_success(api.finalize_audit(audit["id"], TEST_USERS["auditor_headers"]))
        resp1 = api.finalize_audit(audit["id"], TEST_USERS["auditor_headers"])
        validate_error(resp1, ApiErrorId.ERR_AUDIT_NOT_DRAFT)

        ctx = setup_disputed_order(
            tag="VL7B",
            matrix_rules=IA_MATRIX_RULES,
            findings=IA_FINDINGS,
            dispute_reason="first dispute filing here",
            deliver_at="2026-08-06T10:00:00Z",
        )
        resp2 = api.create_dispute(
            create_dispute_payload(
                ctx["order"]["id"], reason="second concurrent dispute"
            ),
            make_candidate_headers(ctx["candidate"]["id"]),
        )
        # PRD section "Disputes and Re-Investigation" names
        # ERR_DISPUTE_ALREADY_OPEN for a second filing while one is open, but
        # an open dispute also leaves the report DISPUTED and the order's
        # adjudication in DISPUTE_HOLD, so the section "Validation Ordering"
        # pipeline (state preconditions, sixth, before uniqueness, eighth)
        # permits either state error to surface first. All three are faithful.
        validate_error_is_one_of(
            resp2,
            [
                ApiErrorId.ERR_DISPUTE_ALREADY_OPEN,
                ApiErrorId.ERR_REPORT_NOT_ACTIONABLE,
                ApiErrorId.ERR_ORDER_ADJUDICATION_TERMINAL,
            ],
        )

    def test_dispute_before_report_and_consent_revoke_twice(self, api):
        """PRD section "Disputes and Re-Investigation": "Filing requires an
        existing report in `DELIVERED` or `AMENDED` status for the order —
        otherwise `ERR_REPORT_NOT_ACTIONABLE`" and PRD section "Consent
        Capture": "revoking a consent not in `CAPTURED` status is rejected with
        `ERR_CONSENT_NOT_ACTIVE`"."

        Design: Corner/validations/dispute_before_report_and_consent_revoke_twice
        """
        ctx = setup_screening_config(tag="VL11", with_matrix=False)
        candidate = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Vl Eleven", email="vl11@x.com"),
                HR,
            )
        )
        get_success_data(api.set_clock("2026-08-05T10:00:00Z"))
        order = get_success_data(
            api.create_order(
                create_order_payload(candidate["id"], ctx["position"]["id"]), HM
            )
        )
        cand_headers = make_candidate_headers(candidate["id"])

        # No report exists for a DRAFT order.
        resp1 = api.create_dispute(
            create_dispute_payload(order["id"], reason="nothing to dispute yet here"),
            cand_headers,
        )
        validate_error(resp1, ApiErrorId.ERR_REPORT_NOT_ACTIONABLE)

        consent = get_success_data(
            api.capture_consent(
                order["id"],
                {
                    "disclosure_form_id": "DISC-1",
                    "contains_extraneous_terms": False,
                    "authorization_signed_at": "2026-08-04T09:00:00Z",
                },
                cand_headers,
            )
        )
        revoked = validate_success(api.revoke_consent(consent["id"], cand_headers))
        assert revoked["status"] == "REVOKED"
        order_now = get_success_data(api.get_order(order["id"], HR))
        assert order_now["fulfillment_status"] == "CANCELLED"

        resp2 = api.revoke_consent(consent["id"], cand_headers)
        validate_error(resp2, ApiErrorId.ERR_CONSENT_NOT_ACTIVE)


class TestImmediateConsistency:
    def test_dispute_hold_visible_atomically(self, api):
        """PRD section "Introduction": "Every mutation is atomically visible in
        the response that performs it." and PRD section "Disputes and
        Re-Investigation": "Filing creates the dispute in
        `UNDER_REINVESTIGATION` with `filed_at` stamped and `candidate_id`
        copied from the order, moves the report to `DISPUTED`, and moves the
        order's adjudication to `DISPUTE_HOLD` while fulfillment stays unchanged
        at `REPORT_RECEIVED`. If an adverse-action case exists in
        `WAITING_PERIOD` or `ELIGIBLE_FOR_FINAL`, it moves to `DISPUTE_HOLD`
        with `hold_started_at` stamped"."

        Design: Corner/consistency_model/dispute_hold_visible_atomically
        """
        ctx = setup_pre_adverse_case(
            tag="CM1",
            adjudicator_id="adj-cm1",
            findings=ADVERSE_FINDINGS,
            consent_signed_at="2026-08-03T09:00:00Z",
            dispatch_at="2026-08-03T09:00:00Z",
            deliver_at="2026-08-04T10:00:00Z",
            initiate_at="2026-08-05T10:00:00Z",
        )
        get_success_data(api.set_clock("2026-08-06T09:00:00Z"))
        dispute = validate_success(
            api.create_dispute(
                create_dispute_payload(
                    ctx["order"]["id"], reason="immediate consistency probe"
                ),
                make_candidate_headers(ctx["candidate"]["id"]),
            ),
            expected_status=201,
        )
        assert dispute["status"] == "UNDER_REINVESTIGATION"
        assert dispute["candidate_id"] == ctx["candidate"]["id"]
        assert_instant_equals(
            dispute["filed_at"], "2026-08-06T09:00:00Z", "dispute.filed_at"
        )

        report = get_success_data(api.get_report(ctx["report"]["id"], HR))
        assert report["status"] == "DISPUTED"
        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["adjudication_status"] == "DISPUTE_HOLD"
        case = get_success_data(api.get_case(ctx["case"]["id"], CO))
        assert case["status"] == "DISPUTE_HOLD"
        assert_instant_equals(
            case["hold_started_at"], "2026-08-06T09:00:00Z", "case.hold_started_at"
        )


class TestPinnedMatrixReevaluation:
    def test_pinned_matrix_governs_amendment_reevaluation(self, api):
        """PRD section "Disputes and Re-Investigation": "re-computes every
        finding's `considerable` flag and `matched_action` against the currently
        active jurisdiction rule but — critically — against the order's pinned
        matrix, the `pinned_matrix_id` and `pinned_matrix_version` frozen at
        delivery, even if that matrix has since been retired"."

        Design: Corner/cross_cutting_layers/pinned_matrix_governs_amendment_reevaluation
        """
        ctx = setup_disputed_order(
            tag="XC3",
            findings=ADVERSE_FINDINGS,
            dispute_reason="contesting severity coding",
            deliver_at="2026-08-06T10:00:00Z",
        )
        pinned_id = ctx["matrix"]["id"]
        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["pinned_matrix_id"] == pinned_id
        assert order["recommended_outcome"] == "ADVERSE_ELIGIBLE"

        # Retire the pinned matrix and activate a replacement that would CLEAR
        # the same finding.
        validate_success(api.retire_matrix(pinned_id, CO))
        m2 = get_success_data(
            api.create_matrix(
                create_matrix_payload(
                    rules=[
                        {
                            "offense_category": "VIOLENT_FELONY",
                            "min_severity": "HIGH",
                            "max_recency_years": 99,
                            "action": "CLEAR",
                        }
                    ]
                ),
                CO,
            )
        )
        get_success_data(api.activate_matrix(m2["id"], CO))

        get_success_data(api.set_clock("2026-08-07T10:00:00Z"))
        validate_success(
            api.resolve_dispute(
                ctx["dispute"]["id"],
                {
                    "outcome": "AMENDED",
                    "corrected_findings": [
                        finding(
                            offense_category="VIOLENT_FELONY", severity="HIGH",
                            offense_date="2024-06-01T00:00:00Z",
                        )
                    ],
                },
                make_vendor_agent_headers(ctx["vendor"]["id"]),
            )
        )
        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        # The PINNED (now retired) matrix still governs: ADVERSE_ELIGIBLE,
        # not the CLEAR the replacement matrix would have produced.
        assert order["recommended_outcome"] == "ADVERSE_ELIGIBLE"
        assert order["pinned_matrix_id"] == pinned_id
