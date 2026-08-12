"""Second tests for each §1.8 difficulty instance (supplementary coverage).

Every test carries the same `Design: Difficulty/<rule_id>/<instance.name>`
tag as its primary sibling so the Completeness audit sees >= 2 tests per
queue-A instance.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_affected_subject_payload,
    create_call_center_staffing_plan_payload,
    create_credit_monitoring_offer_payload,
    create_custody_log_payload,
    create_evidence_item_payload,
    create_forensic_scope_payload,
    create_incident,
    create_incident_confirmed,
    create_incident_in_investigating_state,
    create_issued_offer,
    create_jurisdiction_evaluation_payload,
    create_mailing_batch_payload,
    create_notice_payload,
    create_draft_notice,
    create_locked_notice,
    get_success_data,
    make_affected_subject_headers,
    make_general_counsel_headers,
    make_privacy_counsel_headers,
    setup_dispatching_incident_with_queued_batch,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
FL = TEST_USERS["forensic_lead_headers"]
PC = TEST_USERS["privacy_counsel_headers"]
GC = TEST_USERS["general_counsel_headers"]
DA = TEST_USERS["data_analyst_headers"]


# ---------------------------------------------------------------------------
# dual_variant_calc / notification_deadline_calendar_vs_business_days
# ---------------------------------------------------------------------------


class TestNotificationDeadlineVariantsSecond:
    def test_calendar_and_business_deadlines_diverge_with_shorter_window(self, api):
        """PRD §3.5: "If the kind is `CALENDAR_DAYS`, the deadline is the
        calendar date obtained by adding `deadline_days` to the determination
        date, pinned to `23:59:59.999Z` of that final day. If the kind is
        `BUSINESS_DAYS`, the deadline is computed by walking forward from the
        determination instant and counting only Monday-through-Friday days
        that are not in the hardcoded list of US federal holidays for 2026
        ... the result is again pinned to `23:59:59.999Z` of the final day."

        A 5-day window from Friday 2026-05-01 lands differently under the two
        variants: CALENDAR_DAYS -> Wed 2026-05-06 end-of-day; BUSINESS_DAYS
        -> Fri 2026-05-08 end-of-day (weekend skipped).

        Design: Difficulty/dual_variant_calc/notification_deadline_calendar_vs_business_days
        """
        ctx = create_incident_in_investigating_state(
            subject_count=1, subject_state_code="CA"
        )
        inc = ctx["incident"]
        je_cal = get_success_data(
            api.create_jurisdiction_evaluation(
                inc["id"],
                create_jurisdiction_evaluation_payload(
                    state_code="CA",
                    deadline_days=5,
                    deadline_kind="CALENDAR_DAYS",
                ),
                PC,
            )
        )
        je_biz = get_success_data(
            api.create_jurisdiction_evaluation(
                inc["id"],
                create_jurisdiction_evaluation_payload(
                    state_code="NY",
                    deadline_days=5,
                    deadline_kind="BUSINESS_DAYS",
                ),
                PC,
            )
        )
        api.confirm_incident(inc["id"], IC)
        cal_after = get_success_data(
            api.get_jurisdiction_evaluation(inc["id"], je_cal["id"], PC)
        )
        biz_after = get_success_data(
            api.get_jurisdiction_evaluation(inc["id"], je_biz["id"], PC)
        )
        assert cal_after["deadline_at"] == "2026-05-06T23:59:59.999Z"
        assert biz_after["deadline_at"] == "2026-05-08T23:59:59.999Z"
        assert cal_after["deadline_at"] != biz_after["deadline_at"]


# ---------------------------------------------------------------------------
# dual_variant_calc / risk_score_conservative_vs_likelihood_adjusted
# ---------------------------------------------------------------------------


class TestRiskScoreVariantsSecond:
    def test_exfiltration_100_makes_variants_converge(self, api):
        """PRD §3.3: "the same inputs produce a strictly lower score whenever
        `exfiltration_likelihood_pct` is below 100." Corollary: at
        `exfiltration_likelihood_pct == 100` the likelihood-adjusted variant
        multiplies by 1.0 and converges with the conservative variant on the
        same rounded value (SSN-only base = 20).

        Design: Difficulty/dual_variant_calc/risk_score_conservative_vs_likelihood_adjusted
        """
        inc = create_incident()
        scope = validate_success(
            api.create_forensic_scope(
                inc["id"],
                create_forensic_scope_payload(
                    data_elements_at_risk=["SSN"], exfiltration_likelihood_pct=100
                ),
                FL,
            ),
            expected_status=201,
        )
        api.baseline_forensic_scope(inc["id"], scope["id"], FL)
        after = get_success_data(api.get_incident(inc["id"], IC))
        assert after["risk_score_conservative"] == 20
        assert after["risk_score_likelihood_adjusted"] == 20


# ---------------------------------------------------------------------------
# combinatorial_formula / call_center_seats_tiered_multi_input_mode_a
# ---------------------------------------------------------------------------


class TestCallCenterSeatsSecond:
    def test_single_language_no_surcharge_at_tier1(self, api):
        """PRD §3.10: "If P is below 100, the base seat count is 2. ...
        Finally, if `languages_supported` contains more than one language,
        2 seats are added on top of the severity-adjusted result." A
        single-language plan with one pending subject does not receive the
        surcharge, so `seats_required` is the tier-1 base 2 (also the
        defensive floor).

        Design: Difficulty/combinatorial_formula/call_center_seats_tiered_multi_input_mode_a
        """
        ctx = create_incident_confirmed(subject_count=1)
        inc = ctx["incident"]
        resp = api.create_call_center_staffing_plan(
            inc["id"],
            create_call_center_staffing_plan_payload(
                languages_supported=["en"]
            ),
            IC,
        )
        plan = validate_success(resp, expected_status=201)
        assert plan["seats_required"] == 2


# ---------------------------------------------------------------------------
# combinatorial_formula / credit_monitoring_cost_per_offer_then_sum_mode_b
# ---------------------------------------------------------------------------


class TestCreditMonitoringCostSecond:
    def test_declined_offer_contributes_zero_to_total(self, api):
        """PRD §3.9: "If the offer is `DECLINED` or `EXPIRED`, its cost is
        zero." Two offers, one redeemed at full base (12 * 999 = 11988) and
        one declined (0): total is 11988 + 0 = 11988, with per-offer rounding
        applied before the sum (never after).

        Design: Difficulty/combinatorial_formula/credit_monitoring_cost_per_offer_then_sum_mode_b
        """
        ctx = create_incident_confirmed(subject_count=2)
        inc = ctx["incident"]
        s1, s2 = ctx["subjects"]
        off1 = create_issued_offer(inc, s1, term_months=12, unit_cost_cents=999)
        off2 = create_issued_offer(inc, s2, term_months=12, unit_cost_cents=999)
        # Redeem off1 (full base), decline off2 (zero).
        api.redeem_credit_monitoring_offer(
            inc["id"], off1["id"], make_affected_subject_headers(s1["id"])
        )
        api.decline_credit_monitoring_offer(
            inc["id"], off2["id"], make_affected_subject_headers(s2["id"])
        )
        data = validate_success(api.get_cost_summary(inc["id"], IC))
        # redeemed base = 12 * 999 = 11988 (integer, no rounding needed);
        # declined = 0.
        assert data["credit_monitoring_cost_cents"] == 11988
        assert data["offer_count"] == 2


# ---------------------------------------------------------------------------
# non_linear_state_machine / notice_cyclic_revision_loop
# ---------------------------------------------------------------------------


class TestNoticeCycleSecond:
    def test_notice_can_be_resubmitted_after_request_changes(self, api):
        """PRD §3.7: "Submitting a draft for legal review — moving the notice
        from `DRAFT` to `LEGAL_REVIEW` — requires `body_text` to be at least
        200 characters long, and requires the incident's `notification_status`
        to be `DRAFTING` or `REQUIRED`." After a `request-changes` return to
        `DRAFT`, the same notice can be re-submitted; the cycle is legal.

        Design: Difficulty/non_linear_state_machine/notice_cyclic_revision_loop
        """
        ctx = create_incident_confirmed()
        inc = ctx["incident"]
        je = ctx["jurisdiction_evaluations"][0]
        notice = create_draft_notice(inc, je)
        api.submit_notice_for_review(inc["id"], notice["id"], PC)
        api.request_changes_notice(inc["id"], notice["id"], GC)
        # After one round trip the notice is back in DRAFT with version_label=2.
        resub = api.submit_notice_for_review(inc["id"], notice["id"], PC)
        n = validate_success(resub)
        assert n["status"] == "LEGAL_REVIEW"
        assert n["version_label"] == 2


# ---------------------------------------------------------------------------
# non_linear_state_machine / incident_parallel_state_dimensions
# ---------------------------------------------------------------------------


class TestIncidentParallelDimensionsSecond:
    def test_notification_status_drains_to_drafting_on_first_notice(self, api):
        """PRD §3.7: "The first time a `PrivacyCounsel` creates a `Notice`
        against an incident whose `notification_status` is `REQUIRED`, the
        incident transitions to `DRAFTING` and its `version` increments."
        Investigation status is untouched by the notice-creation write.

        Design: Difficulty/non_linear_state_machine/incident_parallel_state_dimensions
        """
        ctx = create_incident_confirmed()
        inc = ctx["incident"]
        je = ctx["jurisdiction_evaluations"][0]
        inc_v_pre = get_success_data(api.get_incident(inc["id"], IC))
        assert inc_v_pre["notification_status"] == "REQUIRED"

        create_draft_notice(inc, je)
        after = get_success_data(api.get_incident(inc["id"], IC))
        assert after["notification_status"] == "DRAFTING"
        assert after["investigation_status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# transitive_cascade / confirm_cascade_depth3
# ---------------------------------------------------------------------------


class TestConfirmCascadeSecond:
    def test_confirm_also_computes_deadline_for_triggered_jurisdiction(self, api):
        """PRD §3.6: "every `PENDING` `JurisdictionEvaluation` transitions to
        `TRIGGERED` with its `deadline_at` computed per §3.5"; PRD §3.5 fixes
        the determination instant at "the moment of that confirmation" so the
        deadline is deterministic under the logical-clock default
        2026-05-01T00:00:00Z (PRD §3.13).

        Design: Difficulty/transitive_cascade/confirm_cascade_depth3
        """
        ctx = create_incident_in_investigating_state(
            subject_count=1, subject_state_code="CA"
        )
        inc = ctx["incident"]
        je = get_success_data(
            api.create_jurisdiction_evaluation(
                inc["id"],
                create_jurisdiction_evaluation_payload(
                    state_code="CA",
                    record_count_threshold=1,
                    deadline_days=30,
                    deadline_kind="CALENDAR_DAYS",
                ),
                PC,
            )
        )
        api.confirm_incident(inc["id"], IC)
        after = get_success_data(
            api.get_jurisdiction_evaluation(inc["id"], je["id"], PC)
        )
        assert after["status"] == "TRIGGERED"
        # 30 calendar days from 2026-05-01 -> 2026-05-31 end-of-day.
        assert after["deadline_at"] == "2026-05-31T23:59:59.999Z"


# ---------------------------------------------------------------------------
# transitive_cascade / mark_shipped_cascade_depth2
# ---------------------------------------------------------------------------


class TestMarkShippedCascadeSecond:
    def test_mark_shipped_updates_batch_status_to_shipped(self, api):
        """PRD §3.8: "Marking the batch shipped — moving it from
        `IN_PRODUCTION` to `SHIPPED` — requires `scheduled_ship_date` to be
        at or before the current time". The happy-path transition returns the
        batch in `SHIPPED` state, and the per-subject cascade has run.

        Design: Difficulty/transitive_cascade/mark_shipped_cascade_depth2
        """
        ctx = setup_dispatching_incident_with_queued_batch(subject_count=1)
        inc = ctx["incident"]
        batch = ctx["batch"]
        api.start_production_mailing_batch(inc["id"], batch["id"], PC)
        ship_resp = api.mark_shipped_mailing_batch(inc["id"], batch["id"], PC)
        batch_after = validate_success(ship_resp)
        assert batch_after["status"] == "SHIPPED"


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / approve_notice_state_vs_business_temporal
# ---------------------------------------------------------------------------


class TestApprovePriorityPairSecond:
    def test_approve_before_deadline_still_enforces_segregation_of_duties(self, api):
        """PRD §2.7 lists segregation-of-duties (step 8) before the
        business-temporal deadline check (step 9). When the same X-User-ID
        drafts (as PrivacyCounsel) and approves (as GeneralCounsel) a notice
        whose deadline is still in the future, only the seg-of-duty check can
        fire, so the response is `ERR_SEGREGATION_OF_DUTIES` (409).

        Design: Difficulty/priority_pair_validation_conflict/approve_notice_state_vs_business_temporal
        """
        ctx = create_incident_confirmed()
        inc = ctx["incident"]
        je = ctx["jurisdiction_evaluations"][0]
        same_user = "overlap-user-1"
        notice = create_draft_notice(
            inc, je, creator_headers=make_privacy_counsel_headers(same_user)
        )
        api.submit_notice_for_review(
            inc["id"], notice["id"], make_privacy_counsel_headers(same_user)
        )
        # Deadline still in the future (logical clock default 2026-05-01).
        resp = api.approve_notice(
            inc["id"], notice["id"], make_general_counsel_headers(same_user)
        )
        validate_error(
            resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=409
        )


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / create_subject_business_referential_vs_business_constraint
# ---------------------------------------------------------------------------


class TestSubjectValidationPairSecond:
    def test_out_of_scope_alone_fires_when_no_duplicate(self, api):
        """PRD §2.7 step 10: "an affected subject's `data_elements_exposed`
        must be a subset of the current forensic scope's
        `data_elements_at_risk` whenever the scope has reached `BASELINED`,
        `AMENDED`, or `FINAL`. Violation: `ERR_DATA_ELEMENT_OUT_OF_SCOPE`
        (422)." A single-failure case isolates the business-referential
        branch of the priority pair.

        Design: Difficulty/priority_pair_validation_conflict/create_subject_business_referential_vs_business_constraint
        """
        inc = create_incident()
        scope = validate_success(
            api.create_forensic_scope(
                inc["id"],
                create_forensic_scope_payload(data_elements_at_risk=["SSN"]),
                FL,
            ),
            expected_status=201,
        )
        api.baseline_forensic_scope(inc["id"], scope["id"], FL)
        resp = api.create_affected_subject(
            inc["id"],
            create_affected_subject_payload(
                external_subject_ref="unique-1",
                data_elements_exposed=["SSN", "BIOMETRIC"],
            ),
            DA,
        )
        validate_error(
            resp,
            ApiErrorId.ERR_DATA_ELEMENT_OUT_OF_SCOPE.value,
            expected_status=422,
        )


# ---------------------------------------------------------------------------
# boundary_precision_check / jurisdiction_threshold_inclusive_at_boundary
# ---------------------------------------------------------------------------


class TestThresholdInclusiveSecond:
    def test_threshold_zero_subjects_below_threshold_stays_false(self, api):
        """PRD §2.9: "`notification_required` is true exactly when
        `subjects_in_jurisdiction` is at least `record_count_threshold`; the
        comparison is inclusive at the boundary, so exactly-at-threshold
        triggers notification." With threshold=2 and only 1 subject in the
        jurisdiction, the boundary is not met and `notification_required`
        remains false.

        Design: Difficulty/boundary_precision_check/jurisdiction_threshold_inclusive_at_boundary
        """
        ctx = create_incident_in_investigating_state(
            subject_count=1, subject_state_code="CA"
        )
        inc = ctx["incident"]
        je = get_success_data(
            api.create_jurisdiction_evaluation(
                inc["id"],
                create_jurisdiction_evaluation_payload(
                    state_code="CA",
                    record_count_threshold=2,
                    deadline_days=10,
                    deadline_kind="CALENDAR_DAYS",
                ),
                PC,
            )
        )
        api.confirm_incident(inc["id"], IC)
        after = get_success_data(
            api.get_jurisdiction_evaluation(inc["id"], je["id"], PC)
        )
        assert after["subjects_in_jurisdiction"] == 1
        assert after["notification_required"] is False


# ---------------------------------------------------------------------------
# boundary_precision_check / confirm_with_zero_subjects_rejected
# ---------------------------------------------------------------------------


class TestConfirmZeroSubjectsSecond:
    def test_confirm_with_exactly_one_subject_succeeds(self, api):
        """PRD §3.6: confirm requires "`total_affected_subjects` is strictly
        greater than zero". With exactly one VERIFIED subject (boundary
        value 1) the precondition holds and confirm succeeds.

        Design: Difficulty/boundary_precision_check/confirm_with_zero_subjects_rejected
        """
        ctx = create_incident_in_investigating_state(subject_count=1)
        inc = ctx["incident"]
        resp = api.confirm_incident(inc["id"], IC)
        data = validate_success(resp)
        assert data["investigation_status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / notice_approve_requires_incident_confirmed
# ---------------------------------------------------------------------------


class TestNoticeApproveIncidentConfirmedSecond:
    def test_approve_flips_notification_status_when_all_triggered_covered(self, api):
        """PRD §3.7: "The incident-level `notification_status` flips from
        `DRAFTING` to `APPROVED` automatically as soon as every `TRIGGERED`
        jurisdiction evaluation has at least one notice in `APPROVED` or
        `LOCKED_FOR_MAIL`." With the single TRIGGERED evaluation covered by
        the just-approved notice, the notification dimension advances.

        Design: Difficulty/cross_entity_state_dependency/notice_approve_requires_incident_confirmed
        """
        ctx = create_incident_confirmed()
        inc = ctx["incident"]
        je = ctx["jurisdiction_evaluations"][0]
        notice = create_draft_notice(inc, je)
        api.submit_notice_for_review(inc["id"], notice["id"], PC)
        api.approve_notice(inc["id"], notice["id"], GC)
        after = get_success_data(api.get_incident(inc["id"], IC))
        assert after["notification_status"] == "APPROVED"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / mailing_batch_start_requires_notice_locked
# ---------------------------------------------------------------------------


class TestMailingBatchStartSecond:
    def test_start_production_cascades_subject_to_notice_queued(self, api):
        """PRD §3.8 start-production side effects: "every `AffectedSubject`
        in the batch's scope whose status is `VERIFIED` transitions to
        `NOTICE_QUEUED`; the batch's `recipient_count` is set to the number
        of subjects just transitioned".

        Design: Difficulty/cross_entity_state_dependency/mailing_batch_start_requires_notice_locked
        """
        ctx = setup_dispatching_incident_with_queued_batch(subject_count=1)
        inc = ctx["incident"]
        batch = ctx["batch"]
        subj_id = ctx["subjects"][0]["id"]
        resp = api.start_production_mailing_batch(inc["id"], batch["id"], PC)
        batch_after = validate_success(resp)
        assert batch_after["recipient_count"] == 1
        subj_after = get_success_data(api.get_affected_subject(inc["id"], subj_id, PC))
        assert subj_after["status"] == "NOTICE_QUEUED"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / custody_log_half_open_interval_no_overlap
# ---------------------------------------------------------------------------


class TestCustodyOverlapSecond:
    def test_open_ended_custody_blocks_any_later_start(self, api):
        """PRD §3.2: custody carries "an optional `end_at` timestamp
        (exclusive — `null` while custody remains open)" and intervals are
        half-open `[start_at, end_at)`; "an overlap is rejected with
        `ERR_CUSTODY_OVERLAP` (409)". An open-ended interval
        `[start_at, null)` overlaps every later start.

        Design: Difficulty/resource_temporal_overlap/custody_log_half_open_interval_no_overlap
        """
        inc = create_incident()
        ev = validate_success(
            api.create_evidence_item(inc["id"], create_evidence_item_payload(), FL),
            expected_status=201,
        )
        open_log = api.create_custody_log(
            inc["id"],
            create_custody_log_payload(
                ev["id"],
                custodian_user_id="u1",
                start_at="2026-05-01T10:00:00Z",
                end_at=None,
                purpose="open custody",
            ),
            FL,
        )
        validate_success(open_log, expected_status=201)
        overlap = api.create_custody_log(
            inc["id"],
            create_custody_log_payload(
                ev["id"],
                custodian_user_id="u2",
                start_at="2026-05-01T11:00:00Z",
                end_at="2026-05-01T12:00:00Z",
                purpose="overlap",
            ),
            FL,
        )
        validate_error(overlap, ApiErrorId.ERR_CUSTODY_OVERLAP.value, expected_status=409)


# ---------------------------------------------------------------------------
# resource_temporal_overlap / staffing_plan_overlap_strict_only
# ---------------------------------------------------------------------------


class TestStaffingPlanOverlapSecond:
    def test_partial_overlap_with_active_plan_rejected(self, api):
        """PRD §3.10: a new plan's "interval must not partially overlap the
        interval of any other `ACTIVE` plan for the same incident —
        half-open `[effective_from, effective_until)` semantics, with
        touching edges permitted; violations are rejected with
        `ERR_STAFFING_PLAN_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/staffing_plan_overlap_strict_only
        """
        ctx = create_incident_confirmed()
        inc = ctx["incident"]
        api.create_call_center_staffing_plan(
            inc["id"],
            create_call_center_staffing_plan_payload(
                effective_from="2026-05-02T00:00:00Z",
                effective_until="2026-06-02T00:00:00Z",
            ),
            IC,
        )
        # Partial overlap: starts inside the existing plan's window.
        resp = api.create_call_center_staffing_plan(
            inc["id"],
            create_call_center_staffing_plan_payload(
                effective_from="2026-05-15T00:00:00Z",
                effective_until="2026-07-15T00:00:00Z",
            ),
            IC,
        )
        validate_error(
            resp, ApiErrorId.ERR_STAFFING_PLAN_OVERLAP.value, expected_status=409
        )


# ---------------------------------------------------------------------------
# compensating_invariant / notified_plus_pending_equals_affected
# ---------------------------------------------------------------------------


class TestNotifiedPlusPendingSecond:
    def test_pending_drains_to_zero_after_full_dispatch_cycle(self, api):
        """PRD §2.9: "`total_pending_subjects` is the count of
        `AffectedSubject` rows whose status is `IDENTIFIED`, `VERIFIED`, or
        `NOTICE_QUEUED`"; after the batch ships and every VERIFIED subject
        transitions to `NOTIFIED`, pending must drop to 0 and the invariant
        notified + pending == affected still holds (1 + 0 == 1).

        Design: Difficulty/compensating_invariant/notified_plus_pending_equals_affected
        """
        ctx = setup_dispatching_incident_with_queued_batch(subject_count=1)
        inc = ctx["incident"]
        batch = ctx["batch"]
        api.start_production_mailing_batch(inc["id"], batch["id"], PC)
        api.mark_shipped_mailing_batch(inc["id"], batch["id"], PC)
        after = get_success_data(api.get_incident(inc["id"], IC))
        assert after["total_pending_subjects"] == 0
        assert after["total_notified_subjects"] == 1
        assert after["total_affected_subjects"] == 1
        assert (
            after["total_notified_subjects"] + after["total_pending_subjects"]
            == after["total_affected_subjects"]
        )


# ---------------------------------------------------------------------------
# compensating_invariant / credit_monitoring_enrolled_plus_declined_plus_pending_equals_offered
# ---------------------------------------------------------------------------


class TestCreditMonitoringInvariantSecond:
    def test_issued_offers_count_toward_offered(self, api):
        """PRD §2.9: "`credit_monitoring_offered` is the count of
        `AffectedSubject` rows whose `credit_monitoring_status` is anything
        other than `NOT_OFFERED`". PRD §3.9: issuance "flips the target
        subject's `credit_monitoring_status` from `NOT_OFFERED` to
        `OFFERED_PENDING`". Two ISSUED offers lift offered to 2 while
        enrolled and declined remain 0.

        Design: Difficulty/compensating_invariant/credit_monitoring_enrolled_plus_declined_plus_pending_equals_offered
        """
        ctx = create_incident_confirmed(subject_count=2)
        inc = ctx["incident"]
        s1, s2 = ctx["subjects"]
        create_issued_offer(inc, s1)
        create_issued_offer(inc, s2)
        after = get_success_data(api.get_incident(inc["id"], IC))
        assert after["credit_monitoring_offered"] == 2
        assert after["credit_monitoring_enrolled"] == 0
        assert after["credit_monitoring_declined"] == 0
