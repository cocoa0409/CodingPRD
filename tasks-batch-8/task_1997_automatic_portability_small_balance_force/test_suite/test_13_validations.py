"""Queue B corner tests: validation violations mapped to exact errors."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_participant_headers,
    make_provider_ops_headers,
    make_fiduciary_reviewer_headers,
    create_active_recordkeeper,
    create_plan,
    create_participant,
    create_open_batch,
    create_case,
    setup_locked_batch_one_case,
    setup_auto_expired_case,
    setup_established_ira,
    setup_ira_with_fee_disclosure,
    setup_matched_ira,
    setup_transfer_ready_ira,
    setup_reconciled_batch,
    setup_executed_batch_elected_cash,
)

OPS = TEST_USERS["provider_ops_headers"]
SPONSOR = TEST_USERS["plan_sponsor_headers"]


def test_missing_auth_header_returns_401():
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting
    user, and `X-User-Role`, declaring the caller's operational capacity. The system
    recognizes exactly four roles: `Participant`, `PlanSponsor`, `ProviderOps`, and
    `FiduciaryReviewer`. A request missing either header, or presenting a role outside
    this list, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_header_returns_401
    """
    rk = create_active_recordkeeper()
    res = api_client.get_recordkeeper(rk["id"], headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_invalid_outcome_enum_rejected():
    """PRD §3.4: "Mail-tracking outcomes are recorded per notice with an `outcome` of
    `DELIVERED`, `BOUNCED`, or `RETURNED_MAIL`; any other value is `ERR_INVALID_REQUEST`"

    Design: Corner/validations/invalid_outcome_enum_rejected
    """
    ctx = setup_locked_batch_one_case(balance=50000)
    notice = get_success_data(api_client.create_notice(
        ctx["case"]["id"], {"notice_type": "FORCE_OUT_ELECTION"}, OPS))
    res = api_client.record_notice_delivery(
        notice["id"], {"outcome": "LOST"}, OPS)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)
    notice_after = get_success_data(api_client.get_notice(notice["id"], OPS))
    assert notice_after["delivery_status"] == "SENT"


def test_plan_create_missing_required_field():
    """PRD §3.1: "A `PlanSponsor` registers an employer plan with a `plan_name`, a
    `sponsor_ein`, and the `recordkeeper_id` of the recordkeeper that houses it."
    PRD §2.9: "4. **Request shape** — required fields present, types valid, enum values in
    range (`election_type`, `notice_type`, `void_reason`, `outcome`, and similar); failure
    is `ERR_INVALID_REQUEST` (400)."

    Design: Corner/validations/plan_create_missing_required_field
    """
    res = api_client.create_plan(
        {"plan_name": "Plan X", "sponsor_ein": "11-1111111"}, SPONSOR)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_threshold_config_invalid_on_patch():
    """PRD §3.1: "An update that would push the cash-out threshold above the rollover
    threshold, or move the withholding rate outside its bounds, is rejected with
    `ERR_THRESHOLD_CONFIG_INVALID`"
    PRD §3.1: "A successful update recomputes `network_reachable` and increments the plan's
    `version`."

    Design: Corner/validations/threshold_config_invalid_on_patch
    """
    rk = create_active_recordkeeper()
    plan = create_plan(rk["id"])
    pv = plan["version"]
    res = api_client.patch_plan(
        plan["id"],
        {"expected_plan_version": pv, "cash_out_threshold_cents": 800000},
        SPONSOR,
    )
    validate_error(res, ApiErrorId.ERR_THRESHOLD_CONFIG_INVALID, 422)
    plan_after = get_success_data(api_client.get_plan(plan["id"], OPS))
    assert plan_after["cash_out_threshold_cents"] == 100000
    assert plan_after["version"] == pv


def test_review_period_invalid_rejected():
    """PRD §3.9: "the window must be non-empty — `period_start` before `period_end`,
    otherwise `ERR_REVIEW_PERIOD_INVALID`"

    Design: Corner/validations/review_period_invalid_rejected
    """
    ctx = setup_reconciled_batch()
    res = api_client.create_fiduciary_review(
        {"distribution_batch_id": ctx["batch"]["id"],
         "period_start": "2026-09-01T00:00:00Z",
         "period_end": "2026-09-01T00:00:00Z"},
        make_fiduciary_reviewer_headers("fid_rev_1"),
    )
    validate_error(res, ApiErrorId.ERR_REVIEW_PERIOD_INVALID, 422)


def test_recordkeeper_plan_mismatch_rejected():
    """PRD §3.7: "Referential integrity is checked before scoring: the new plan's
    recordkeeper must equal `new_recordkeeper_id` (`ERR_RECORDKEEPER_PLAN_MISMATCH`)"

    Design: Corner/validations/recordkeeper_plan_mismatch_rejected
    """
    ctx = setup_established_ira(balance=300000)
    rk_b = create_active_recordkeeper(code="RK-B", legal_name="Recordkeeper B")
    rk_c = create_active_recordkeeper(code="RK-C", legal_name="Recordkeeper C")
    plan_y = create_plan(rk_b["id"], plan_name="Plan Y", sponsor_ein="33-3333333")
    res = api_client.create_match_search(
        ctx["ira"]["id"],
        {"new_plan_id": plan_y["id"], "new_recordkeeper_id": rk_c["id"],
         "employment_start_date": "2026-08-10", "ssn_exact": True,
         "name_similarity": 0.90, "dob_match": True},
        OPS,
    )
    validate_error(res, ApiErrorId.ERR_RECORDKEEPER_PLAN_MISMATCH, 422)
    ira = get_success_data(api_client.get_safe_harbor_ira(ctx["ira"]["id"], OPS))
    assert ira["ira_status"] == "OPEN"


def test_prenotice_window_open_blocks_transfer():
    """PRD §3.7: "its opt-out window must already have closed — the prenotice's
    `response_deadline` must be before the current instant, otherwise
    `ERR_PRENOTICE_WINDOW_OPEN`."

    Design: Corner/validations/prenotice_window_open_blocks_transfer
    """
    # MATCHED IRA; prenotice DELIVERED at the default clock (deadline 2026-08-31);
    # clock advanced only to 2026-08-15, so the opt-out window is still open.
    ctx = setup_matched_ira(balance=300000)
    prenotice = get_success_data(api_client.create_notice(
        ctx["case"]["id"], {"notice_type": "AUTO_PORTABILITY_PRENOTICE"}, OPS))
    get_success_data(api_client.record_notice_delivery(
        prenotice["id"], {"outcome": "DELIVERED"}, OPS))
    get_success_data(api_client.set_clock("2026-08-15T00:00:00Z", OPS))
    ira = get_success_data(api_client.get_safe_harbor_ira(ctx["ira"]["id"], OPS))
    res = api_client.create_transfer(
        ira["id"], {"expected_ira_version": ira["version"]}, OPS)
    validate_error(res, ApiErrorId.ERR_PRENOTICE_WINDOW_OPEN, 422)
    ira_after = get_success_data(api_client.get_safe_harbor_ira(ira["id"], OPS))
    assert ira_after["ira_status"] == "MATCHED"
    from test_helpers import validate_paginated
    _, meta = validate_paginated(api_client.list_transfers(
        OPS, params={"safe_harbor_ira_id": ira["id"]}))
    assert meta["total_count"] == 0


def test_ira_establish_wrong_path_fiscal():
    """PRD §3.6: "`ProviderOps` establishes a safe harbor IRA for a case that is `ELECTED`
    with a `SUBMITTED` `SAFE_HARBOR_IRA` election, or `WINDOW_EXPIRED` with
    `force_out_path` `SAFE_HARBOR_IRA`; a window-expired case locked into a different path
    is rejected with `ERR_CASE_BALANCE_INELIGIBLE`"

    Design: Corner/validations/ira_establish_wrong_path_fiscal
    """
    # Auto-path case with vested 50000 (<= 100000 cash-out threshold): CASH_OUT band.
    ctx = setup_auto_expired_case(balance=50000)
    assert ctx["case"]["case_status"] == "WINDOW_EXPIRED"
    assert ctx["case"]["force_out_path"] == "CASH_OUT"
    res = api_client.create_safe_harbor_ira(
        {"distribution_case_id": ctx["case"]["id"]}, OPS)
    validate_error(res, ApiErrorId.ERR_CASE_BALANCE_INELIGIBLE, 422)


def test_execute_with_open_window_blocked():
    """PRD §3.5: "it is likewise blocked while any `NOTIFIED` case's window has not yet
    closed, meaning the current notice's `response_deadline` is at or after the current
    instant, rejected with `ERR_CASE_WINDOW_STILL_OPEN`."

    Design: Corner/validations/execute_with_open_window_blocked
    """
    ctx = setup_locked_batch_one_case(balance=50000)
    from test_helpers import send_force_out_notice_and_deliver
    send_force_out_notice_and_deliver(ctx["case"]["id"])
    # Clock still at the default 2026-08-01; the 2026-08-31 deadline is in the future.
    res = api_client.execute_distribution_batch(
        ctx["batch"]["id"], make_provider_ops_headers("ops_exec_1"))
    validate_error(res, ApiErrorId.ERR_CASE_WINDOW_STILL_OPEN, 422)
    batch = get_success_data(
        api_client.get_distribution_batch(ctx["batch"]["id"], OPS))
    assert batch["batch_status"] == "LOCKED"


def test_execute_with_unnotified_case_blocked():
    """PRD §3.5: "Execution is blocked while any attached case is still `IDENTIFIED` — its
    force-out notice was never delivered — and such an attempt is rejected with
    `ERR_CASE_NOTICE_OUTSTANDING`"

    Design: Corner/validations/execute_with_unnotified_case_blocked
    """
    ctx = setup_locked_batch_one_case(balance=50000)
    notice = get_success_data(api_client.create_notice(
        ctx["case"]["id"], {"notice_type": "FORCE_OUT_ELECTION"}, OPS))
    # BOUNCED leaves the case IDENTIFIED (never delivered).
    get_success_data(api_client.record_notice_delivery(
        notice["id"], {"outcome": "BOUNCED"}, OPS))
    res = api_client.execute_distribution_batch(
        ctx["batch"]["id"], make_provider_ops_headers("ops_exec_1"))
    validate_error(res, ApiErrorId.ERR_CASE_NOTICE_OUTSTANDING, 422)
    batch = get_success_data(
        api_client.get_distribution_batch(ctx["batch"]["id"], OPS))
    assert batch["batch_status"] == "LOCKED"


def test_escheat_void_without_warning_blocked():
    """PRD §3.8: "Escheatment is the heavy path: it is permitted only on a `STALE_DATED`
    check, and only when an `ESCHEAT_WARNING` notice for the case was delivered at least
    ninety days earlier — otherwise the void is rejected with
    `ERR_ESCHEAT_WARNING_REQUIRED`."

    Design: Corner/validations/escheat_void_without_warning_blocked
    """
    ctx = setup_auto_expired_case(balance=100000)
    chk = get_success_data(api_client.create_check(
        {"distribution_case_id": ctx["case"]["id"]}, OPS))
    # Advance past stale_after and sweep so the check is STALE_DATED.
    get_success_data(api_client.set_clock("2027-02-28T00:00:00Z", OPS))
    get_success_data(api_client.run_sweep(OPS))
    chk = get_success_data(api_client.get_check(chk["id"], OPS))
    assert chk["check_status"] == "STALE_DATED"
    # No ESCHEAT_WARNING ever delivered.
    res = api_client.void_check(chk["id"], {"void_reason": "ESCHEATMENT"}, OPS)
    validate_error(res, ApiErrorId.ERR_ESCHEAT_WARNING_REQUIRED, 422)
    chk_after = get_success_data(api_client.get_check(chk["id"], OPS))
    assert chk_after["check_status"] == "STALE_DATED"
    case = get_success_data(
        api_client.get_distribution_case(ctx["case"]["id"], OPS))
    assert case["case_status"] == "EXECUTED"


def test_fee_assess_without_disclosure_blocked():
    """PRD §3.6: "Assessment is gated on disclosure: unless a `FEE_DISCLOSURE` notice for
    the case has reached `DELIVERED`, the assessment is rejected with
    `ERR_FEE_DISCLOSURE_NOT_DELIVERED`."
    PRD §3.6: "an August-1-to-September-1 period bills 510 cents under `ACTUAL_365`
    (thirty-one days)"

    Design: Corner/validations/fee_assess_without_disclosure_blocked
    """
    ctx = setup_established_ira(balance=300000)
    get_success_data(api_client.set_clock("2026-09-01T00:00:00Z", OPS))
    res = api_client.assess_ira_fee(ctx["ira"]["id"], OPS)
    validate_error(res, ApiErrorId.ERR_FEE_DISCLOSURE_NOT_DELIVERED, 422)
    from test_helpers import validate_paginated
    _, meta = validate_paginated(api_client.list_fee_assessments(
        OPS, params={"safe_harbor_ira_id": ctx["ira"]["id"]}))
    assert meta["total_count"] == 0
    # Deliver the disclosure, then the same call succeeds.
    fd = get_success_data(api_client.create_notice(
        ctx["case"]["id"], {"notice_type": "FEE_DISCLOSURE"}, OPS))
    get_success_data(api_client.record_notice_delivery(
        fd["id"], {"outcome": "DELIVERED"}, OPS))
    fee = validate_success(api_client.assess_ira_fee(ctx["ira"]["id"], OPS), 201)
    assert fee["amount_cents"] == 510
    ira = get_success_data(api_client.get_safe_harbor_ira(ctx["ira"]["id"], OPS))
    assert ira["balance_cents"] == 299490


def test_reissue_with_bad_address_blocked():
    """PRD §3.8: "Reissue requires the underlying case still `EXECUTED` — not `ESCHEATED`
    or `CANCELLED`, otherwise `ERR_INVALID_STATE` — and a deliverable address: a
    participant whose `address_quality` is `BAD_ADDRESS` blocks reissue with
    `ERR_UNDELIVERABLE_ADDRESS`, while `UNVERIFIED` remains acceptable."
    PRD §3.2: "Any successful address update — touching `mailing_address_line1`,
    `mailing_city`, `mailing_state`, `mailing_zip`, or `email`, performed by a
    `PlanSponsor`, a `ProviderOps` operator, or the participant — marks `address_quality`
    `VALID`"

    Design: Corner/validations/reissue_with_bad_address_blocked
    """
    ctx = setup_executed_batch_elected_cash(balance=100000)
    chk = get_success_data(api_client.create_check(
        {"distribution_case_id": ctx["case"]["id"]}, OPS))
    get_success_data(api_client.void_check(chk["id"], {"void_reason": "DAMAGED"}, OPS))
    # Bounce an ESCHEAT_WARNING to flip the participant to BAD_ADDRESS.
    warn = get_success_data(api_client.create_notice(
        ctx["case"]["id"], {"notice_type": "ESCHEAT_WARNING"}, OPS))
    get_success_data(api_client.record_notice_delivery(
        warn["id"], {"outcome": "BOUNCED"}, OPS))
    participant = get_success_data(
        api_client.get_participant(ctx["participant"]["id"], OPS))
    assert participant["address_quality"] == "BAD_ADDRESS"

    res = api_client.reissue_check(chk["id"], OPS)
    validate_error(res, ApiErrorId.ERR_UNDELIVERABLE_ADDRESS, 422)

    # Repair the address; reissue now succeeds.
    get_success_data(api_client.patch_participant(
        ctx["participant"]["id"], {"mailing_address_line1": "9 New Ave"}, OPS))
    chk2 = validate_success(api_client.reissue_check(chk["id"], OPS), 201)
    assert chk2["check_status"] == "ISSUED"
    assert chk2["supersedes_check_id"] == chk["id"]


def test_transfer_with_tiny_balance_blocked():
    """PRD §3.7: "If the difference is not positive, initiation is rejected with
    `ERR_INSUFFICIENT_IRA_BALANCE`."
    PRD §3.6: "an August-1-to-September-1 period bills 510 cents under `ACTUAL_365`
    (thirty-one days)"

    Design: Corner/validations/transfer_with_tiny_balance_blocked
    """
    # Funded 400; the 31-day unbilled accrual is 510, so 400 - 510 <= 0.
    ctx = setup_transfer_ready_ira(balance=400, clock="2026-09-01T00:00:00Z")
    ira = ctx["ira"]
    res = api_client.create_transfer(
        ira["id"], {"expected_ira_version": ira["version"]}, OPS)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_IRA_BALANCE, 422)
    ira_after = get_success_data(api_client.get_safe_harbor_ira(ira["id"], OPS))
    assert ira_after["ira_status"] == "MATCHED"
    assert ira_after["balance_cents"] == 400


def test_batch_create_on_terminated_plan_blocked():
    """PRD §3.3: "The plan must be `ACTIVE` — a terminated plan rejects batch creation
    with `ERR_PLAN_NOT_ACTIVE`"

    Design: Corner/validations/batch_create_on_terminated_plan_blocked
    """
    rk = create_active_recordkeeper()
    plan = create_plan(rk["id"])
    get_success_data(api_client.terminate_plan(plan["id"], SPONSOR))
    res = api_client.create_distribution_batch({"plan_id": plan["id"]}, SPONSOR)
    validate_error(res, ApiErrorId.ERR_PLAN_NOT_ACTIVE, 422)


def test_match_search_to_non_accepting_plan_blocked():
    """PRD §2.8: "A plan's `network_reachable` flag is derived, never stored by hand: it is
    true exactly when the plan's recordkeeper has `network_status` `ACTIVE` and the plan's
    own `accepts_incoming_transfers` flag is true."
    PRD §3.7: "the new plan must be `network_reachable`
    (`ERR_DESTINATION_PLAN_NOT_ACCEPTING`)"

    Design: Corner/validations/match_search_to_non_accepting_plan_blocked
    """
    ctx = setup_established_ira(balance=300000)
    rk_b = create_active_recordkeeper(code="RK-B", legal_name="Recordkeeper B")
    plan_y = create_plan(rk_b["id"], plan_name="Plan Y", sponsor_ein="33-3333333",
                         accepts_incoming_transfers=False)
    plan_y_fresh = get_success_data(api_client.get_plan(plan_y["id"], OPS))
    assert plan_y_fresh["network_reachable"] is False
    res = api_client.create_match_search(
        ctx["ira"]["id"],
        {"new_plan_id": plan_y["id"], "new_recordkeeper_id": rk_b["id"],
         "employment_start_date": "2026-08-10", "ssn_exact": True,
         "name_similarity": 0.90, "dob_match": True},
        OPS,
    )
    validate_error(res, ApiErrorId.ERR_DESTINATION_PLAN_NOT_ACCEPTING, 422)


def test_confirm_below_confirm_floor_rejected():
    """PRD §3.7: "a `match_score` below 0.650 is rejected with
    `ERR_MATCH_SCORE_BELOW_THRESHOLD`, so a candidate sitting between 0.400 and 0.650 can
    be reviewed but never confirmed."
    PRD §3.7: "A score of at least 0.400 but below 0.850 parks the candidate in
    `CANDIDATE`, the manual-review queue"

    Design: Corner/validations/confirm_below_confirm_floor_rejected
    """
    ctx = setup_established_ira(balance=300000)
    from test_helpers import setup_second_active_recordkeeper_and_plan
    rk_b, plan_y = setup_second_active_recordkeeper_and_plan()
    # 0.55 + 0.30*0.20 = 0.610: in [0.400, 0.650) — reviewable but never confirmable.
    m1 = validate_success(api_client.create_match_search(
        ctx["ira"]["id"],
        {"new_plan_id": plan_y["id"], "new_recordkeeper_id": rk_b["id"],
         "employment_start_date": "2026-08-10", "ssn_exact": True,
         "name_similarity": 0.20, "dob_match": False},
        OPS,
    ), 201)
    assert m1["match_score"] == 0.610
    assert m1["match_status"] == "CANDIDATE"
    res = api_client.confirm_match_candidate(m1["id"], OPS)
    validate_error(res, ApiErrorId.ERR_MATCH_SCORE_BELOW_THRESHOLD, 422)
    m1_after = get_success_data(api_client.get_match_candidate(m1["id"], OPS))
    assert m1_after["match_status"] == "CANDIDATE"


def test_confirm_without_ssn_gate_rejected():
    """PRD §3.7: "A manual confirm checks the SSN gate first — a candidate without an
    exact SSN is rejected with `ERR_SSN_GATE_FAILED`"
    PRD §3.7: "the SSN gate caps non-SSN feeds at 0.45 and they can never auto-confirm"

    Design: Corner/validations/confirm_without_ssn_gate_rejected
    """
    ctx = setup_established_ira(balance=300000)
    from test_helpers import setup_second_active_recordkeeper_and_plan
    rk_b, plan_y = setup_second_active_recordkeeper_and_plan()
    # ssn_exact=false caps the score: 0.30*1.00 + 0.15 = 0.450 — CANDIDATE band.
    m1 = validate_success(api_client.create_match_search(
        ctx["ira"]["id"],
        {"new_plan_id": plan_y["id"], "new_recordkeeper_id": rk_b["id"],
         "employment_start_date": "2026-08-10", "ssn_exact": False,
         "name_similarity": 1.00, "dob_match": True},
        OPS,
    ), 201)
    assert m1["match_score"] == 0.450
    assert m1["match_status"] == "CANDIDATE"
    res = api_client.confirm_match_candidate(m1["id"], OPS)
    validate_error(res, ApiErrorId.ERR_SSN_GATE_FAILED, 422)
    m1_after = get_success_data(api_client.get_match_candidate(m1["id"], OPS))
    assert m1_after["match_status"] == "CANDIDATE"
    ira_after = get_success_data(api_client.get_safe_harbor_ira(ctx["ira"]["id"], OPS))
    assert ira_after["ira_status"] == "OPEN"
