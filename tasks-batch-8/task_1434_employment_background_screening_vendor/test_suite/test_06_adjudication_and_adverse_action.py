"""Adjudication decisions, individualized assessments, the adverse-action
waiting period, and segregation of duties on the final notice."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    create_assessment_payload,
    create_candidate_payload,
    create_order_payload,
    finding,
    get_success_data,
    list_cases_filtered,
    make_adjudicator_headers,
    make_compliance_officer_headers,
    setup_pre_adverse_case,
    setup_report_received,
    validate_error,
    validate_success,
    TEST_USERS,
)

HR = TEST_USERS["hr_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]

ADVERSE_FINDINGS = [finding()]


class TestIndividualizedAssessment:
    def test_ia_clear_candidate_closes_order(self, api):
        """PRD section "Adjudication": "A `CLEAR_CANDIDATE` decision immediately
        moves the order's adjudication to `CLEARED` and its fulfillment to
        `CLOSED`" and "an `Adjudicator` may record an individualized assessment
        on an order whose adjudication is `PENDING_REVIEW` (any other state
        rejects with `ERR_ORDER_ADJUDICATION_NOT_REVIEWABLE`)."

        Design: Corner/state_machines/ia_clear_candidate_closes_order
        """
        ctx = setup_report_received(
            tag="SM12",
            matrix_rules=[
                {
                    "offense_category": "NONVIOLENT_FELONY",
                    "min_severity": "LOW",
                    "max_recency_years": 99,
                    "action": "IA_REQUIRED",
                }
            ],
            findings=[
                finding(
                    offense_category="NONVIOLENT_FELONY", severity="MEDIUM",
                    offense_date="2024-02-01T00:00:00Z",
                )
            ],
            deliver_at="2026-08-06T10:00:00Z",
        )
        assessment = validate_success(
            api.create_assessment(
                ctx["order"]["id"],
                create_assessment_payload(
                    green_factor_nature_gravity="LOW",
                    green_factor_time_elapsed="HIGH",
                    green_factor_job_relatedness="LOW",
                    evidence_considered=True,
                    decision="CLEAR_CANDIDATE",
                ),
                make_adjudicator_headers("adj-sm12"),
            ),
            expected_status=201,
        )
        assert assessment["status"] == "DECIDED"
        assert assessment["adjudicator_user_id"] == "adj-sm12"

        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["adjudication_status"] == "CLEARED"
        assert order["fulfillment_status"] == "CLOSED"

        # The order is closed: no further adjudication decision is reviewable.
        resp = api.adjudication_decision(
            ctx["order"]["id"], "INITIATE_ADVERSE",
            make_adjudicator_headers("adj-sm12"),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_ADJUDICATION_NOT_REVIEWABLE)


class TestAdversePathGating:
    def test_adverse_not_recommended_and_ia_too_early(self, api):
        """PRD section "Adjudication": "First, the order's `recommended_outcome`
        must not be `CLEAR` — initiating adverse action against a clean
        recommendation is rejected with `ERR_ADVERSE_NOT_RECOMMENDED` (HTTP
        409)." and "an `Adjudicator` may record an individualized assessment on
        an order whose adjudication is `PENDING_REVIEW` (any other state rejects
        with `ERR_ORDER_ADJUDICATION_NOT_REVIEWABLE`)."

        Design: Corner/validations/adverse_not_recommended_and_ia_too_early
        """
        # Order 1: delivered with no findings -> recommended_outcome CLEAR.
        ctx = setup_report_received(
            tag="VL10", findings=[], deliver_at="2026-08-06T10:00:00Z"
        )
        resp1 = api.adjudication_decision(
            ctx["order"]["id"], "INITIATE_ADVERSE",
            make_adjudicator_headers("adj-vl10"),
        )
        validate_error(resp1, ApiErrorId.ERR_ADVERSE_NOT_RECOMMENDED)

        # Order 2: still DRAFT (adjudication NOT_STARTED) — an IA cannot be
        # recorded before any report exists.
        cand2 = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Vl TenB", email="vl10b@x.com"),
                HR,
            )
        )
        order2 = get_success_data(
            api.create_order(
                create_order_payload(cand2["id"], ctx["position"]["id"]), HM
            )
        )
        resp2 = api.create_assessment(
            order2["id"],
            create_assessment_payload(
                green_factor_nature_gravity="LOW",
                green_factor_time_elapsed="LOW",
                green_factor_job_relatedness="LOW",
                evidence_considered=False,
                decision="PROCEED_ADVERSE",
            ),
            make_adjudicator_headers("adj-vl10"),
        )
        validate_error(resp2, ApiErrorId.ERR_ORDER_ADJUDICATION_NOT_REVIEWABLE)

    def test_initiate_adverse_blocked_without_required_ia(self, api):
        """PRD section "Adjudication": "Second, whenever `recommended_outcome`
        is `IA_REQUIRED` or the jurisdiction's
        `individualized_assessment_required` flag is true, a decided
        individualized assessment with decision `PROCEED_ADVERSE` must already
        exist on the order; its absence is rejected with `ERR_IA_REQUIRED` (HTTP
        409)."

        Design: Difficulty/cross_entity_state_dependency/initiate_adverse_gated_by_individualized_assessment
        """
        ctx = setup_report_received(
            tag="CE2",
            jurisdiction_overrides={"individualized_assessment_required": True},
            findings=ADVERSE_FINDINGS,
            deliver_at="2026-08-04T10:00:00Z",
            dispatch_at="2026-08-03T09:00:00Z",
            consent_signed_at="2026-08-03T09:00:00Z",
        )
        resp = api.adjudication_decision(
            ctx["order"]["id"], "INITIATE_ADVERSE",
            make_adjudicator_headers("adj-ce2"),
        )
        validate_error(resp, ApiErrorId.ERR_IA_REQUIRED)
        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["adjudication_status"] == "PENDING_REVIEW"

    def test_initiate_adverse_succeeds_with_proceed_adverse_ia(self, api):
        """PRD section "Adjudication": "A successful `INITIATE_ADVERSE` stamps
        `adverse_initiated_by_user_id` with the acting adjudicator's identity
        and atomically creates the one-to-one `AdverseActionCase`." and "The
        case begins in `WAITING_PERIOD`"."

        Design: Difficulty/cross_entity_state_dependency/initiate_adverse_gated_by_individualized_assessment
        """
        ctx = setup_report_received(
            tag="CE2B",
            jurisdiction_overrides={"individualized_assessment_required": True},
            findings=ADVERSE_FINDINGS,
            deliver_at="2026-08-04T10:00:00Z",
            dispatch_at="2026-08-03T09:00:00Z",
            consent_signed_at="2026-08-03T09:00:00Z",
        )
        validate_success(
            api.create_assessment(
                ctx["order"]["id"],
                create_assessment_payload(
                    green_factor_nature_gravity="HIGH",
                    green_factor_time_elapsed="LOW",
                    green_factor_job_relatedness="HIGH",
                    evidence_considered=False,
                    decision="PROCEED_ADVERSE",
                ),
                make_adjudicator_headers("adj-ce2"),
            ),
            expected_status=201,
        )
        order = validate_success(
            api.adjudication_decision(
                ctx["order"]["id"], "INITIATE_ADVERSE",
                make_adjudicator_headers("adj-ce2"),
            )
        )
        assert order["adjudication_status"] == "PRE_ADVERSE_PENDING"
        assert order["adverse_initiated_by_user_id"] == "adj-ce2"

        cases, meta = list_cases_filtered(CO, order_id=ctx["order"]["id"])
        assert len(cases) == 1
        assert cases[0]["status"] == "WAITING_PERIOD"
        assert cases[0]["initiated_by_user_id"] == "adj-ce2"


class TestWaitingPeriodComputation:
    def test_jurisdictional_wait_override_max_with_fcra_base(self, api):
        """PRD section "Adjudication": "`wait_business_days_required` is set to
        the greater of five business days — the FCRA baseline — and the
        jurisdiction's `pre_adverse_wait_business_days`" and
        "`earliest_final_notice_at` is computed by adding the required wait to
        the pre-notice date under business-day arithmetic: the send day is
        excluded from the count, and the result is pinned to 00:00:00Z on the
        Nth following business day."

        Design: Corner/calculations/jurisdictional_wait_override_max_with_fcra_base
        """
        # Jurisdiction wait 7 > FCRA base 5. Pre-notice Monday
        # 2026-08-03T14:00:00Z; 7 business days: Aug 4,5,6,7,10,11,12.
        ctx = setup_pre_adverse_case(
            tag="CC6",
            adjudicator_id="adj-cc6",
            jurisdiction_code="US-NY-NYC",
            jurisdiction_overrides={"pre_adverse_wait_business_days": 7},
            findings=ADVERSE_FINDINGS,
            consent_signed_at="2026-08-03T09:00:00Z",
            dispatch_at="2026-08-03T09:00:00Z",
            deliver_at="2026-08-03T10:00:00Z",
            initiate_at="2026-08-03T14:00:00Z",
        )
        case = ctx["case"]
        assert case["wait_business_days_required"] == 7
        assert_instant_equals(
            case["earliest_final_notice_at"],
            "2026-08-12T00:00:00Z",
            "earliest_final_notice_at",
        )


class TestFinalNoticeBoundary:
    def _setup_case_bp2(self, api, tag):
        return setup_pre_adverse_case(
            tag=tag,
            adjudicator_id="adj-bp2",
            findings=ADVERSE_FINDINGS,
            consent_signed_at="2026-08-03T09:00:00Z",
            dispatch_at="2026-08-03T09:00:00Z",
            deliver_at="2026-08-04T10:00:00Z",
            initiate_at="2026-08-05T10:00:00Z",
        )

    def test_final_notice_one_second_before_boundary_rejected(self, api):
        """PRD section "The Adverse-Action Waiting Period and the Final Notice":
        "Only then does the temporal gate apply: the current logical time must
        be at or after `earliest_final_notice_at`, else
        `ERR_ADVERSE_WAIT_NOT_ELAPSED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/adverse_wait_exact_boundary_business_day
        """
        ctx = self._setup_case_bp2(api, "BP2")
        case = ctx["case"]
        # wait 5 from Wed 2026-08-05 -> earliest 2026-08-12T00:00:00Z.
        assert_instant_equals(
            case["earliest_final_notice_at"],
            "2026-08-12T00:00:00Z",
            "earliest_final_notice_at",
        )
        get_success_data(api.set_clock("2026-08-11T23:59:59Z"))
        resp = api.send_final_notice(
            case["id"], make_compliance_officer_headers("co-bp2")
        )
        validate_error(resp, ApiErrorId.ERR_ADVERSE_WAIT_NOT_ELAPSED)

    def test_final_notice_at_exact_boundary_succeeds(self, api):
        """PRD section "The Adverse-Action Waiting Period and the Final Notice":
        "A successful final notice stamps `final_notice_sent_at` and
        `final_notice_issuer_user_id`, moves the case to `FINAL_NOTICE_SENT`,
        and cascades to the order: adjudication becomes `FINAL_ADVERSE`,
        fulfillment becomes `CLOSED`."

        Design: Difficulty/boundary_precision_check/adverse_wait_exact_boundary_business_day
        """
        ctx = self._setup_case_bp2(api, "BP2B")
        case = ctx["case"]
        get_success_data(api.set_clock("2026-08-12T00:00:00Z"))
        done = validate_success(
            api.send_final_notice(
                case["id"], make_compliance_officer_headers("co-bp2")
            )
        )
        assert done["status"] == "FINAL_NOTICE_SENT"
        assert done["final_notice_issuer_user_id"] == "co-bp2"
        assert_instant_equals(
            done["final_notice_sent_at"], "2026-08-12T00:00:00Z",
            "final_notice_sent_at",
        )
        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["adjudication_status"] == "FINAL_ADVERSE"
        assert order["fulfillment_status"] == "CLOSED"


class TestFinalNoticeTerminalLockdown:
    def test_final_notice_twice_rejected(self, api):
        """PRD section "The Adverse-Action Waiting Period and the Final Notice":
        "A case not in `WAITING_PERIOD` or `ELIGIBLE_FOR_FINAL` rejects both
        operations with `ERR_CASE_NOT_AWAITING_FINAL`."

        Design: Corner/state_machines/final_notice_twice_rejected
        """
        ctx = setup_pre_adverse_case(
            tag="SM6",
            adjudicator_id="adj-sm6",
            findings=ADVERSE_FINDINGS,
            consent_signed_at="2026-08-03T09:00:00Z",
            dispatch_at="2026-08-03T09:00:00Z",
            deliver_at="2026-08-04T10:00:00Z",
            initiate_at="2026-08-05T10:00:00Z",
        )
        get_success_data(api.set_clock("2026-08-12T00:00:00Z"))
        done = validate_success(
            api.send_final_notice(
                ctx["case"]["id"], make_compliance_officer_headers("co-sm6")
            )
        )
        assert done["status"] == "FINAL_NOTICE_SENT"

        # FINAL_NOTICE_SENT is terminal: a second notice is rejected.
        resp = api.send_final_notice(
            ctx["case"]["id"], make_compliance_officer_headers("co-sm6b")
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_AWAITING_FINAL)
        case = get_success_data(api.get_case(ctx["case"]["id"], CO))
        assert case["status"] == "FINAL_NOTICE_SENT"


class TestSegregationOfDuties:
    def _setup_case_pp2(self, api, tag):
        ctx = setup_pre_adverse_case(
            tag=tag,
            adjudicator_id="adj-pp2",
            findings=ADVERSE_FINDINGS,
            consent_signed_at="2026-08-03T09:00:00Z",
            dispatch_at="2026-08-03T09:00:00Z",
            deliver_at="2026-08-04T10:00:00Z",
            initiate_at="2026-08-05T10:00:00Z",
        )
        get_success_data(api.set_clock("2026-08-10T09:00:00Z"))
        return ctx

    def test_sod_error_beats_waiting_period(self, api):
        """PRD section "The Adverse-Action Waiting Period and the Final Notice":
        "The segregation check runs first: the acting officer's identity must
        differ from the case's `initiated_by_user_id`, and a match is rejected
        with `ERR_SOD_ADVERSE_NOTICE_MISMATCH` (HTTP 403) regardless of how much
        time has passed. Only then does the temporal gate apply"."

        Design: Difficulty/priority_pair_validation_conflict/final_notice_sod_beats_waiting_period
        """
        ctx = self._setup_case_pp2(api, "PP2")
        case = ctx["case"]
        # Both violations hold: issuer == initiator AND now (2026-08-10) is
        # before the earliest final instant (2026-08-12). SoD must win.
        resp = api.send_final_notice(
            case["id"], make_compliance_officer_headers("adj-pp2")
        )
        validate_error(resp, ApiErrorId.ERR_SOD_ADVERSE_NOTICE_MISMATCH)

    def test_temporal_gate_fires_only_after_sod_passes(self, api):
        """PRD section "The Adverse-Action Waiting Period and the Final Notice":
        "Only then does the temporal gate apply: the current logical time must
        be at or after `earliest_final_notice_at`, else
        `ERR_ADVERSE_WAIT_NOT_ELAPSED` (HTTP 409)." and "A case not in
        `WAITING_PERIOD` or `ELIGIBLE_FOR_FINAL` rejects both operations with
        `ERR_CASE_NOT_AWAITING_FINAL`."

        Design: Difficulty/priority_pair_validation_conflict/final_notice_sod_beats_waiting_period
        """
        ctx = self._setup_case_pp2(api, "PP2B")
        case = ctx["case"]
        # Different issuer, but the wait has not elapsed: the temporal gate.
        resp = api.send_final_notice(
            case["id"], make_compliance_officer_headers("co-pp2")
        )
        validate_error(resp, ApiErrorId.ERR_ADVERSE_WAIT_NOT_ELAPSED)

        # The case is unchanged by both rejected attempts.
        case_now = get_success_data(api.get_case(case["id"], CO))
        assert case_now["status"] == "WAITING_PERIOD"
        assert case_now["final_notice_sent_at"] is None
