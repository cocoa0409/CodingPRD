"""EUO scheduling, notice windows, temporal overlap, no-show cascade."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_manager_headers,
    create_adjuster, create_investigator, create_claim, create_referral,
    triage_referral, accept_referral, open_case, assign_investigator,
    log_evidence, submit_evidence_review, admit_evidence,
    setup_case_under_investigation, setup_case_with_admitted_evidence,
    create_euo_session_payload,
)
from test_helpers.api_client import api_client


def _setup_euo_ready_case(api, manager_headers=None):
    """Case UNDER_INVESTIGATION with euo_required=true (score >= 70) and one
    ADMITTED evidence item. Clock at 2026-08-01."""
    mh = manager_headers or make_manager_headers()
    get_success_data(api_client.set_clock("2026-08-01T00:00:00Z", mh))
    adj, ah = create_adjuster(manager_headers=mh)
    inv, ih = create_investigator(manager_headers=mh)
    claim = create_claim(adj, state_code="CA", claimed_amount_cents=100_000_000)
    ref = create_referral(
        claim,
        red_flag_codes=["PRIOR_FRAUD_CONVICTION", "STAGED_ACCIDENT_PATTERN",
                        "INFLATED_BILLING"],
        headers=ah)
    triage_referral(ref, manager_headers=mh)
    case = accept_referral(ref, manager_headers=mh)
    case = open_case(case, manager_headers=mh)
    asg, case = assign_investigator(case, inv, manager_headers=mh)
    ev = log_evidence(case, inv, evidence_type="RECORDS", materiality="SUBSTANTIVE",
                      fraud_amount_cents=1_000_000, collected_at="2026-08-01T00:00:00Z")
    ev = submit_evidence_review(case, ev, inv)
    ev, case = admit_evidence(case, ev, case["version"], manager_headers=mh)
    return {"manager_headers": mh, "adjuster": adj, "adjuster_headers": ah,
            "investigator": inv, "investigator_headers": ih,
            "claim": claim, "referral": ref, "case": case, "evidence": ev,
            "assignment": asg}


class TestEuoRequiredGate:
    def test_euo_required_boundary_high_score_true_low_score_false(self, api):
        """PRD §3.3: "computes the `euo_required` flag (true when the snapshotted
        score meets or exceeds the EUO score threshold; the flag can also turn true
        later if evidence admitted during the investigation raises the case above
        that threshold)"
        PRD §3.2: "70 or more is `CRITICAL`" (the threshold band).
        Score 60 (<70) → false; score 82 (>=70) → true.

        Design: Corner/cross_cutting_layers/rate_threshold_triggers_euo_required_boundary
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        # Low-score case (60)
        claim_lo = create_claim(adj, state_code="CA", claimed_amount_cents=1_000_000,
                                policy_number="P-LO")
        ref_lo = create_referral(claim_lo,
                                 red_flag_codes=["PRIOR_FRAUD_CONVICTION",
                                                 "STAGED_ACCIDENT_PATTERN"],
                                 headers=ah)
        triage_referral(ref_lo, manager_headers=mh)
        case_lo = accept_referral(ref_lo, manager_headers=mh)
        case_lo = open_case(case_lo, manager_headers=mh)
        # High-score case (82)
        claim_hi = create_claim(adj, state_code="CA", claimed_amount_cents=1_000_000,
                                policy_number="P-HI")
        ref_hi = create_referral(claim_hi,
                                 red_flag_codes=["STAGED_ACCIDENT_PATTERN",
                                                 "PHANTOM_TREATMENT",
                                                 "INFLATED_BILLING"],
                                 headers=ah)
        triage_referral(ref_hi, manager_headers=mh)
        case_hi = accept_referral(ref_hi, manager_headers=mh)
        case_hi = open_case(case_hi, manager_headers=mh)
        assert case_lo["euo_required"] is False, \
            f"score 60 < 70 → euo_required false, got {case_lo['euo_required']}"
        assert case_hi["euo_required"] is True, \
            f"score 82 >= 70 → euo_required true, got {case_hi['euo_required']}"


class TestEuoNotRequired:
    def test_schedule_euo_when_not_required_returns_422(self, api):
        """PRD §3.5: "If the flag is false, scheduling is rejected with
        `ERR_EUO_NOT_REQUIRED`"

        Design: Corner/errors/err_euo_not_required_trigger
        """
        mh = make_manager_headers()
        get_success_data(api_client.set_clock("2026-08-01T00:00:00Z", mh))
        ctx = setup_case_under_investigation(
            claimed_amount_cents=1_000_000, red_flag_codes=["UNWITNESSED_LOSS"])
        assert ctx["case"]["euo_required"] is False
        resp = api_client.create_euo_session(
            ctx["case"]["id"],
            create_euo_session_payload(scheduled_start_at="2026-08-20T10:00:00Z",
                                       scheduled_end_at="2026-08-20T12:00:00Z"),
            ctx["investigator_headers"])
        validate_error(resp, ApiErrorId.ERR_EUO_NOT_REQUIRED)


class TestEuoNoticeWindow:
    """Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_fiscal"""

    def test_send_notice_inside_10_day_window_rejected(self, api):
        """PRD §3.5: "The investigator dispatches notice, moving the session from
        `SCHEDULED` to `NOTICE_SENT` and stamping `notice_sent_at`, only when at
        least 10 full days remain before the scheduled start; inside that window
        the dispatch is rejected with `ERR_EUO_NOTICE_WINDOW_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_fiscal
        """
        ctx = _setup_euo_ready_case(api)
        # Clock is 2026-08-01; schedule start 2026-08-06 (5 days away) — violates 10d minimum
        get_success_data(api_client.set_clock("2026-08-10T00:00:00Z",
                                              ctx["manager_headers"]))
        # Start is 2026-08-15, only 5 days from now (2026-08-10)
        resp = api_client.create_euo_session(
            ctx["case"]["id"],
            create_euo_session_payload(scheduled_start_at="2026-08-15T10:00:00Z",
                                       scheduled_end_at="2026-08-15T12:00:00Z"),
            ctx["investigator_headers"])
        euo = validate_success(resp, expected_status=201)
        # now=2026-08-10, start=2026-08-15, delta=5d < 10d
        resp2 = api_client.send_euo_notice(ctx["case"]["id"], euo["id"],
                                           ctx["investigator_headers"])
        validate_error(resp2, ApiErrorId.ERR_EUO_NOTICE_WINDOW_VIOLATION)

    def test_send_notice_with_sufficient_window_succeeds(self, api):
        """PRD §3.5: "The investigator dispatches notice ... only when at least 10
        full days remain before the scheduled start"

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_fiscal
        """
        ctx = _setup_euo_ready_case(api)
        # Clock 2026-08-01; start 2026-08-20 (19 days away)
        resp = api_client.create_euo_session(
            ctx["case"]["id"],
            create_euo_session_payload(scheduled_start_at="2026-08-20T10:00:00Z",
                                       scheduled_end_at="2026-08-20T12:00:00Z"),
            ctx["investigator_headers"])
        euo = validate_success(resp, expected_status=201)
        resp2 = api_client.send_euo_notice(ctx["case"]["id"], euo["id"],
                                           ctx["investigator_headers"])
        data = validate_success(resp2)
        assert data["status"] == "NOTICE_SENT"
        assert data["notice_sent_at"] is not None


class TestEuoTemporalOverlap:
    """Difficulty/resource_temporal_overlap/euo_session_overlap_same_case"""

    def test_overlapping_second_session_rejected(self, api):
        """PRD §3.5: "the end must be later than the start, and the window must not
        overlap another active session for the same case — violations are
        `ERR_EUO_TEMPORAL_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/euo_session_overlap_same_case
        """
        ctx = _setup_euo_ready_case(api)
        # First session 2026-08-20 10:00-12:00
        resp1 = api_client.create_euo_session(
            ctx["case"]["id"],
            create_euo_session_payload(scheduled_start_at="2026-08-20T10:00:00Z",
                                       scheduled_end_at="2026-08-20T12:00:00Z"),
            ctx["investigator_headers"])
        validate_success(resp1, expected_status=201)
        # Second overlapping 11:00-13:00
        resp2 = api_client.create_euo_session(
            ctx["case"]["id"],
            create_euo_session_payload(scheduled_start_at="2026-08-20T11:00:00Z",
                                       scheduled_end_at="2026-08-20T13:00:00Z"),
            ctx["investigator_headers"])
        validate_error(resp2, ApiErrorId.ERR_EUO_TEMPORAL_CONFLICT)

    def test_adjacent_sessions_allowed(self, api):
        """PRD §3.5: "the window must not overlap another active session for the
        same case"
        Adjacent windows (end == start) do not overlap.

        Design: Difficulty/resource_temporal_overlap/euo_session_overlap_same_case
        """
        ctx = _setup_euo_ready_case(api)
        # First session 10:00-12:00
        resp1 = api_client.create_euo_session(
            ctx["case"]["id"],
            create_euo_session_payload(scheduled_start_at="2026-08-20T10:00:00Z",
                                       scheduled_end_at="2026-08-20T12:00:00Z"),
            ctx["investigator_headers"])
        euo1 = validate_success(resp1, expected_status=201)
        # Cancel first so the case returns to UNDER_INVESTIGATION (a case in
        # EUO_PENDING cannot accept a new session per §3.5: "Scheduling is
        # possible only while the case is `UNDER_INVESTIGATION`").
        # Then schedule adjacent at 12:00-14:00.
        api_client.send_euo_notice(ctx["case"]["id"], euo1["id"],
                                   ctx["investigator_headers"])
        api_client.cancel_euo(ctx["case"]["id"], euo1["id"], {"reason": "x"},
                              ctx["manager_headers"])
        # Adjacent session starting exactly when first ended
        resp2 = api_client.create_euo_session(
            ctx["case"]["id"],
            create_euo_session_payload(scheduled_start_at="2026-08-20T12:00:00Z",
                                       scheduled_end_at="2026-08-20T14:00:00Z"),
            ctx["investigator_headers"])
        validate_success(resp2, expected_status=201)


class TestEuoAdmitFreeze:
    """Difficulty/cross_entity_state_dependency/evidence_admit_blocked_during_euo_pending"""

    def test_admit_blocked_while_case_in_euo_pending(self, api):
        """PRD §3.4: "the case must not be `EUO_PENDING`, because admissions are
        frozen while an examination is pending (`ERR_CASE_NOT_IN_REQUIRED_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/evidence_admit_blocked_during_euo_pending
        """
        ctx = _setup_euo_ready_case(api)
        # Move case to EUO_PENDING by scheduling a session
        resp = api_client.create_euo_session(
            ctx["case"]["id"],
            create_euo_session_payload(scheduled_start_at="2026-08-20T10:00:00Z",
                                       scheduled_end_at="2026-08-20T12:00:00Z"),
            ctx["investigator_headers"])
        validate_success(resp, expected_status=201)
        # Log and submit new evidence
        ev2 = log_evidence(ctx["case"], ctx["investigator"],
                           evidence_type="SURVEILLANCE", materiality="SUPPORTING",
                           fraud_amount_cents=0, collected_at="2026-08-02T00:00:00Z")
        ev2 = submit_evidence_review(ctx["case"], ev2, ctx["investigator"])
        # Refresh case version
        case = get_success_data(api_client.get_case(ctx["case"]["id"],
                                                    ctx["manager_headers"]))
        assert case["status"] == "EUO_PENDING"
        resp2 = api_client.admit_evidence(
            case["id"], ev2["id"], {"expected_case_version": case["version"]},
            ctx["manager_headers"])
        validate_error(resp2, ApiErrorId.ERR_CASE_NOT_IN_REQUIRED_STATE)

    def test_case_status_euo_pending_after_first_session_scheduled(self, api):
        """PRD §3.5: "The first session on a case moves it from
        `UNDER_INVESTIGATION` to `EUO_PENDING`"

        Design: Difficulty/cross_entity_state_dependency/evidence_admit_blocked_during_euo_pending
        """
        ctx = _setup_euo_ready_case(api)
        resp = api_client.create_euo_session(
            ctx["case"]["id"],
            create_euo_session_payload(scheduled_start_at="2026-08-20T10:00:00Z",
                                       scheduled_end_at="2026-08-20T12:00:00Z"),
            ctx["investigator_headers"])
        validate_success(resp, expected_status=201)
        case = get_success_data(api_client.get_case(ctx["case"]["id"],
                                                    ctx["manager_headers"]))
        assert case["status"] == "EUO_PENDING"


class TestEuoSecondNoShowCascade:
    """Difficulty/transitive_cascade/euo_second_noshow_cascade_depth2"""

    def _drive_one_no_show(self, ctx, case, start_at, end_at, advance_clock_to):
        """Schedule session, send notice, advance clock past end, record no-show."""
        ih = ctx["investigator_headers"]
        mh = ctx["manager_headers"]
        resp = api_client.create_euo_session(
            case["id"],
            create_euo_session_payload(scheduled_start_at=start_at,
                                       scheduled_end_at=end_at),
            ih)
        euo = validate_success(resp, expected_status=201)
        resp2 = api_client.send_euo_notice(case["id"], euo["id"], ih)
        validate_success(resp2)
        get_success_data(api_client.set_clock(advance_clock_to, mh))
        resp3 = api_client.no_show_euo(case["id"], euo["id"], ih)
        return validate_success(resp3)

    def test_second_no_show_sets_euo_nonappearance_and_delays_claim(self, api):
        """PRD §3.5: "When a session's `no_show_count` reaches two, the claim's
        `payment_hold_reason` becomes `EUO_NONAPPEARANCE` and the claim itself
        moves to `PAYMENT_DELAYED` — statutory cover for the continued hold."

        Design: Difficulty/transitive_cascade/euo_second_noshow_cascade_depth2
        """
        ctx = _setup_euo_ready_case(api)
        case = ctx["case"]
        # First EUO cycle: session 2026-08-15
        self._drive_one_no_show(ctx, case, "2026-08-15T10:00:00Z",
                                "2026-08-15T12:00:00Z", "2026-08-15T13:00:00Z")
        # Second EUO cycle: session 2026-08-25
        euo2 = self._drive_one_no_show(ctx, case, "2026-08-25T10:00:00Z",
                                       "2026-08-25T12:00:00Z", "2026-08-25T13:00:00Z")
        claim = get_success_data(api_client.get_claim(ctx["claim"]["id"],
                                                      ctx["manager_headers"]))
        assert euo2["no_show_count"] == 2
        assert claim["payment_hold_reason"] == "EUO_NONAPPEARANCE"
        assert claim["status"] == "PAYMENT_DELAYED"

    def test_first_no_show_does_not_yet_delay_claim(self, api):
        """PRD §3.5: "When a session's `no_show_count` reaches two, the claim's
        `payment_hold_reason` becomes `EUO_NONAPPEARANCE` and the claim itself
        moves to `PAYMENT_DELAYED`"
        (After the first no-show the count is 1, below the trigger of 2.)

        Design: Difficulty/transitive_cascade/euo_second_noshow_cascade_depth2
        """
        ctx = _setup_euo_ready_case(api)
        case = ctx["case"]
        euo1 = self._drive_one_no_show(ctx, case, "2026-08-15T10:00:00Z",
                                       "2026-08-15T12:00:00Z", "2026-08-15T13:00:00Z")
        claim = get_success_data(api_client.get_claim(ctx["claim"]["id"],
                                                      ctx["manager_headers"]))
        assert euo1["no_show_count"] == 1
        # Claim must still be UNDER_SIU_REVIEW with SIU_INVESTIGATION hold
        assert claim["status"] == "UNDER_SIU_REVIEW"
        assert claim["payment_hold_reason"] == "SIU_INVESTIGATION"
