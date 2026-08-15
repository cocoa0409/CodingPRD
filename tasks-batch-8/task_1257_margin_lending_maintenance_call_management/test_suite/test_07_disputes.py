"""Dispute lifecycle and its interaction with the disputed margin call."""
from test_helpers import (
    ApiErrorId,
    api_client,
    make_analyst_headers,
    make_customer_headers,
    run_sweep,
    set_clock,
    setup_account_with_open_house_call,
    TEST_USERS,
    validate_error,
    validate_success,
)


def test_dispute_initial_state_is_open_and_call_flips_disputed(api):
    """PRD §3.8: "Filing creates the dispute with `dispute_status` `OPEN` ...
    with `reviewed_by_user_id`, `decided_by_user_id`, and `decision` all null,
    and simultaneously moves the call from `OPEN` to `DISPUTED`, pausing its
    expiry clock for the duration."

    Design: Corner/state_machines/dispute_initial_state_is_open_and_call_flips_disputed
    """
    ctx = setup_account_with_open_house_call()
    dispute = validate_success(
        api_client.create_dispute(
            {"call_id": ctx["call"]["id"], "reason": "Dispute the mark"},
            make_customer_headers(ctx["customer"]["id"]),
        ),
        expected_status=201,
    )
    assert dispute["dispute_status"] == "OPEN"
    assert dispute["reviewed_by_user_id"] is None
    assert dispute["decided_by_user_id"] is None
    assert dispute["decision"] is None
    call = validate_success(
        api_client.get_margin_call(ctx["call"]["id"], TEST_USERS["supervisor_headers"])
    )
    assert call["call_status"] == "DISPUTED"


def test_disputed_call_does_not_expire_at_sweep(api):
    """PRD §3.7: "The daily sweep expires any `OPEN` call whose `due_at` has
    been reached or passed, moving it to `EXPIRED`; calls in `DISPUTED` never
    expire — the deadline clock pauses for as long as a dispute is in flight."

    Design: Corner/state_machines/disputed_call_does_not_expire_at_sweep
    """
    ctx = setup_account_with_open_house_call()
    api_client.create_dispute(
        {"call_id": ctx["call"]["id"], "reason": "Pause the clock"},
        make_customer_headers(ctx["customer"]["id"]),
    )
    # 72h past issuance — well beyond the 48h HOUSE deadline.
    set_clock("2026-05-04T00:00:01Z")
    run_sweep()
    call = validate_success(
        api_client.get_margin_call(ctx["call"]["id"], TEST_USERS["supervisor_headers"])
    )
    assert call["call_status"] == "DISPUTED"


def test_dispute_upheld_cycles_call_back_to_open_with_due_at_unchanged(api):
    """PRD §3.8: "When the dispute is upheld, the call returns from `DISPUTED`
    to `OPEN` with its `due_at` unchanged — no extension is granted, so if the
    clock has already passed `due_at`, the next daily sweep will expire it."
    PRD §3.8: "the dispute then closes itself automatically: `UPHELD` and
    `OVERTURNED` are momentary states that transition immediately to the
    terminal `CLOSED`."

    Design: Difficulty/non_linear_state_machine/margin_call_dispute_cycle_open_disputed_open
    """
    ctx = setup_account_with_open_house_call()
    due_at_0 = ctx["call"]["due_at"]
    dispute = validate_success(
        api_client.create_dispute(
            {"call_id": ctx["call"]["id"], "reason": "Mark was erroneous"},
            make_customer_headers(ctx["customer"]["id"]),
        ),
        expected_status=201,
    )
    api_client.start_dispute_review(dispute["id"], make_analyst_headers("analyst-2"))
    decided = validate_success(
        api_client.decide_dispute(
            dispute["id"], {"decision": "UPHELD"}, TEST_USERS["supervisor_headers"]
        )
    )
    assert decided["decision"] == "UPHELD"
    assert decided["dispute_status"] == "CLOSED"

    call = validate_success(
        api_client.get_margin_call(ctx["call"]["id"], TEST_USERS["supervisor_headers"])
    )
    assert call["call_status"] == "OPEN"
    assert call["due_at"] == due_at_0


def test_dispute_overturned_waives_call_and_recovers_account(api):
    """PRD §3.8: "When the dispute is overturned, the call moves from
    `DISPUTED` to `WAIVED` with `cure_method` `WAIVER` and `resolved_at`
    stamped, followed by the account posture recheck."
    PRD §2.11: "whenever the account's last non-terminal call resolves — a call
    is non-terminal while `OPEN`, `DISPUTED`, `EXPIRED`, or
    `LIQUIDATION_IN_PROGRESS` — the account automatically returns from
    `RESTRICTED` to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/margin_call_dispute_cycle_open_disputed_open
    """
    ctx = setup_account_with_open_house_call()
    dispute = validate_success(
        api_client.create_dispute(
            {"call_id": ctx["call"]["id"], "reason": "Mark was erroneous"},
            make_customer_headers(ctx["customer"]["id"]),
        ),
        expected_status=201,
    )
    api_client.start_dispute_review(dispute["id"], make_analyst_headers("analyst-2"))
    decided = validate_success(
        api_client.decide_dispute(
            dispute["id"], {"decision": "OVERTURNED"}, TEST_USERS["supervisor_headers"]
        )
    )
    assert decided["decision"] == "OVERTURNED"
    assert decided["dispute_status"] == "CLOSED"

    call = validate_success(
        api_client.get_margin_call(ctx["call"]["id"], TEST_USERS["supervisor_headers"])
    )
    assert call["call_status"] == "WAIVED"
    assert call["cure_method"] == "WAIVER"
    assert call["resolved_at"] is not None

    from test_helpers import get_account

    account = get_account(ctx["account_id"])
    assert account["account_status"] == "ACTIVE"


def test_duplicate_dispute_on_same_call_rejected(api):
    """PRD §3.8: "a call may carry at most one dispute in `OPEN` or
    `UNDER_REVIEW` at a time, a second in-flight filing failing with
    `ERR_DUPLICATE_DISPUTE`."

    Design: Corner/validations/duplicate_dispute_on_same_call_rejected
    """
    ctx = setup_account_with_open_house_call()
    cust = make_customer_headers(ctx["customer"]["id"])
    first = api_client.create_dispute(
        {"call_id": ctx["call"]["id"], "reason": "First"}, cust
    )
    validate_success(first, expected_status=201)
    second = api_client.create_dispute(
        {"call_id": ctx["call"]["id"], "reason": "Second"}, cust
    )
    validate_error(second, ApiErrorId.ERR_DUPLICATE_DISPUTE)
