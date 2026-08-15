"""Queue B corner tests: state-machine invalid transitions, terminal lockdowns, side effects."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_participant_headers,
    make_provider_ops_headers,
    create_active_recordkeeper,
    create_plan,
    create_participant,
    create_open_batch,
    create_case,
    setup_locked_batch_one_case,
    setup_notified_case,
    setup_elected_case,
    setup_executed_batch_elected_cash,
    setup_established_ira,
    setup_matched_ira,
)

OPS = TEST_USERS["provider_ops_headers"]
SPONSOR = TEST_USERS["plan_sponsor_headers"]


def test_check_reissue_from_issued_rejected():
    """PRD §3.8: "A `VOIDED` check can be reissued — unless it was voided for escheatment,
    which is final."

    Design: Corner/state_machines/check_reissue_from_issued_rejected
    """
    ctx = setup_executed_batch_elected_cash(balance=100000)
    chk = get_success_data(api_client.create_check(
        {"distribution_case_id": ctx["case"]["id"]}, OPS))
    assert chk["check_status"] == "ISSUED"
    res = api_client.reissue_check(chk["id"], OPS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)
    chk_after = get_success_data(api_client.get_check(chk["id"], OPS))
    assert chk_after["check_status"] == "ISSUED"
    successors, meta = validate_paginated(api_client.list_checks(
        OPS, params={"supersedes_check_id": chk["id"]}))
    assert meta["total_count"] == 0


def test_recordkeeper_exit_terminal_lockdown():
    """PRD §3.1: "Exit is terminal. Exiting an `ACTIVE` or `SUSPENDED` recordkeeper moves
    it to `EXITED`, stamps `exited_at`, increments its `version`"
    PRD §2.9: "6. **State permits the transition** — the target entity's current state must
    allow the requested transition, including state guards such as an IRA not being
    `MATCHED` or a case not being `NOTIFIED`; failure is `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/recordkeeper_exit_terminal_lockdown
    """
    rk = create_active_recordkeeper()
    get_success_data(api_client.exit_recordkeeper(rk["id"], OPS))
    res1 = api_client.activate_recordkeeper(rk["id"], OPS)
    validate_error(res1, ApiErrorId.ERR_INVALID_STATE, 409)
    res2 = api_client.suspend_recordkeeper(rk["id"], OPS)
    validate_error(res2, ApiErrorId.ERR_INVALID_STATE, 409)
    rk_after = get_success_data(api_client.get_recordkeeper(rk["id"], OPS))
    assert rk_after["network_status"] == "EXITED"


def test_cancelled_case_lockdown():
    """PRD §3.3: "A case can be withdrawn while it is `IDENTIFIED` or `NOTIFIED` — a rehire
    or a census error — through sponsor cancellation, which moves `case_status` to
    `CANCELLED`"
    PRD §3.4: "a `FORCE_OUT_ELECTION` notice requires the case `IDENTIFIED` and its batch
    `LOCKED`"
    PRD §3.4: "Which type may be sent depends on where the case stands, and a violation of
    these gates is rejected with `ERR_INVALID_STATE`"

    Design: Corner/state_machines/cancelled_case_lockdown
    """
    ctx = setup_locked_batch_one_case(balance=50000)
    cancelled = validate_success(api_client.cancel_distribution_case(
        ctx["case"]["id"], SPONSOR))
    assert cancelled["case_status"] == "CANCELLED"
    res = api_client.create_notice(
        ctx["case"]["id"], {"notice_type": "FORCE_OUT_ELECTION"}, OPS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)


def test_election_void_after_window_closed():
    """PRD §3.4: "Voiding the case's only `SUBMITTED` election — again within the window,
    and again only by the owning participant — moves the election to `VOIDED`"
    PRD §3.4: "a submission at exactly the deadline instant succeeds, and one second later
    it fails with `ERR_ELECTION_WINDOW_CLOSED`."

    Design: Corner/state_machines/election_void_after_window_closed
    """
    ctx = setup_elected_case(balance=100000, election_type="LUMP_SUM_CASH")
    election = ctx["election"]
    get_success_data(api_client.set_clock("2026-09-01T00:00:00Z", OPS))
    res = api_client.void_election(
        election["id"], make_participant_headers(ctx["participant"]["id"]))
    validate_error(res, ApiErrorId.ERR_ELECTION_WINDOW_CLOSED, 422)
    election_after = get_success_data(api_client.get_election(election["id"], OPS))
    assert election_after["election_status"] == "SUBMITTED"


def test_notice_bounced_marks_bad_address():
    """PRD §3.4: "Recording `BOUNCED` moves the notice to `BOUNCED`, marks the participant
    `BAD_ADDRESS`, and leaves the case `IDENTIFIED`."
    PRD §3.4: "Every notice starts `SENT` with `sent_at` stamped from the logical clock;
    `delivered_at` and `response_deadline` remain null until delivery is recorded."

    Design: Corner/state_machines/notice_bounced_marks_bad_address
    """
    ctx = setup_locked_batch_one_case(balance=50000)
    notice = get_success_data(api_client.create_notice(
        ctx["case"]["id"], {"notice_type": "FORCE_OUT_ELECTION"}, OPS))
    validate_success(api_client.record_notice_delivery(
        notice["id"], {"outcome": "BOUNCED"}, OPS))
    notice_after = get_success_data(api_client.get_notice(notice["id"], OPS))
    assert notice_after["delivery_status"] == "BOUNCED"
    assert notice_after["response_deadline"] is None
    case = get_success_data(
        api_client.get_distribution_case(ctx["case"]["id"], OPS))
    assert case["case_status"] == "IDENTIFIED"
    participant = get_success_data(
        api_client.get_participant(ctx["participant"]["id"], OPS))
    assert participant["address_quality"] == "BAD_ADDRESS"


def test_double_execute_rejected():
    """PRD §3.5: "A successful execution moves the batch from `LOCKED` to `EXECUTED`,
    records the caller's `X-User-ID` as `executed_by_user_id`"
    PRD §2.9: "6. **State permits the transition** — the target entity's current state must
    allow the requested transition, including state guards such as an IRA not being
    `MATCHED` or a case not being `NOTIFIED`; failure is `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/double_execute_rejected
    """
    from test_helpers import setup_elected_case
    ctx = setup_elected_case(balance=300000, election_type="SAFE_HARBOR_IRA")
    get_success_data(api_client.execute_distribution_batch(
        ctx["batch"]["id"], make_provider_ops_headers("ops_exec_1")))
    res = api_client.execute_distribution_batch(
        ctx["batch"]["id"], make_provider_ops_headers("ops_exec_2"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)
    batch = get_success_data(
        api_client.get_distribution_batch(ctx["batch"]["id"], OPS))
    assert batch["executed_by_user_id"] == "ops_exec_1"


def test_match_reject_from_rejected_rejected():
    """PRD §3.7: "Rejection simply moves the candidate to `REJECTED`."
    PRD §2.9: "6. **State permits the transition** — the target entity's current state must
    allow the requested transition, including state guards such as an IRA not being
    `MATCHED` or a case not being `NOTIFIED`; failure is `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/match_reject_from_rejected_rejected
    """
    ctx = setup_established_ira(balance=300000)
    from test_helpers import setup_second_active_recordkeeper_and_plan
    rk_b, plan_y = setup_second_active_recordkeeper_and_plan()
    m1 = get_success_data(api_client.create_match_search(
        ctx["ira"]["id"],
        {"new_plan_id": plan_y["id"], "new_recordkeeper_id": rk_b["id"],
         "employment_start_date": "2026-08-10", "ssn_exact": True,
         "name_similarity": 0.34, "dob_match": False},
        OPS,
    ))
    assert m1["match_status"] == "CANDIDATE"
    validate_success(api_client.reject_match_candidate(m1["id"], OPS))
    res = api_client.reject_match_candidate(m1["id"], OPS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)
    m1_after = get_success_data(api_client.get_match_candidate(m1["id"], OPS))
    assert m1_after["match_status"] == "REJECTED"


def test_ira_close_expires_match_and_pays_full_balance():
    """PRD §3.6: "Closure pays the entire remaining `balance_cents` by check: a check with
    `origin` `IRA_CLOSE` is created for the full balance with no withholding at all — both
    withholding components are zero and the payable equals the gross — and the balance
    falls to zero through the in-flight check linkage. If the IRA was `MATCHED`, its
    confirmed match expires to `EXPIRED`. The IRA lands in `CLOSED_BY_PARTICIPANT`"

    Design: Corner/state_machines/ira_close_expires_match_and_pays_full_balance
    """
    ctx = setup_matched_ira(balance=250000)
    ira = ctx["ira"]
    m1 = ctx["match"]
    validate_success(api_client.close_safe_harbor_ira(
        ira["id"], make_participant_headers(ctx["participant"]["id"])))
    ira_after = get_success_data(api_client.get_safe_harbor_ira(ira["id"], OPS))
    assert ira_after["ira_status"] == "CLOSED_BY_PARTICIPANT"
    assert ira_after["balance_cents"] == 0
    m1_after = get_success_data(api_client.get_match_candidate(m1["id"], OPS))
    assert m1_after["match_status"] == "EXPIRED"
    checks, meta = validate_paginated(api_client.list_checks(
        OPS, params={"distribution_case_id": ctx["case"]["id"]}))
    assert meta["total_count"] == 1
    close_check = checks[0]
    assert close_check["origin"] == "IRA_CLOSE"
    assert close_check["amount_cents"] == 250000
    assert close_check["fed_withholding_cents"] == 0
    assert close_check["state_withholding_cents"] == 0


def test_sweep_expires_open_window():
    """PRD §3.8: "it expires open election windows whose deadline has passed (a `NOTIFIED`
    case with no `SUBMITTED` election moves to `WINDOW_EXPIRED`)"
    PRD §3.8: "Nothing in the system transitions on the clock alone — only on a sweep."
    PRD §3.8: "It reports how much it did through four counters: `cases_window_expired`,
    `checks_staled`, `matches_expired`, and `iras_escheated`."

    Design: Corner/state_machines/sweep_expires_open_window
    """
    ctx = setup_notified_case(balance=50000)
    get_success_data(api_client.set_clock("2026-08-31T00:00:01Z", OPS))
    # Clock alone does not transition the case.
    case = get_success_data(
        api_client.get_distribution_case(ctx["case"]["id"], OPS))
    assert case["case_status"] == "NOTIFIED"
    result = validate_success(api_client.run_sweep(OPS))
    assert result["cases_window_expired"] == 1
    case = get_success_data(
        api_client.get_distribution_case(ctx["case"]["id"], OPS))
    assert case["case_status"] == "WINDOW_EXPIRED"
