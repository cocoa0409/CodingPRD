"""Margin call issuance: official-close cascade, severity order, deadlines."""
from test_helpers import (
    api_client,
    create_security_profile,
    get_account,
    place_order,
    post_mark,
    post_marks_both,
    run_sweep,
    set_clock,
    setup_account_with_open_house_call,
    setup_funded_account,
    TEST_USERS,
    validate_paginated,
    validate_success,
)


def test_official_mark_drop_cascades_to_house_call_and_restriction(api):
    """PRD §3.3: "An `OFFICIAL_CLOSE` mark updates `mv_official_cents` and the
    official equity and requirement fields of every holder, and then runs the
    full call evaluation described in §3.6: new calls may be issued, each
    freshly issued call flips its account from `ACTIVE` to `RESTRICTED` ..."
    PRD §3.7: "Otherwise, if the house excess is negative, a `HOUSE` call
    issues for the house deficiency."

    Design: Difficulty/transitive_cascade/official_mark_drop_cascades_mark_to_position_to_equity_to_call_to_restriction
    """
    ctx = setup_account_with_open_house_call()
    call = ctx["call"]
    account = get_account(ctx["account_id"])
    assert call["call_type"] == "HOUSE"
    # equity 400000; house req 700000 (200*7000*5000bps) -> deficiency 300000.
    assert call["call_amount_cents"] == 300_000
    assert account["equity_official_cents"] == 400_000
    assert account["account_status"] == "RESTRICTED"


def test_realtime_mark_drop_does_not_issue_call(api):
    """PRD §3.3: "A `REALTIME` mark updates `mv_realtime_cents` on every
    position in that security and recomputes the realtime equity, requirement,
    and buying-power fields of every holding account — nothing more."

    Design: Difficulty/transitive_cascade/official_mark_drop_cascades_mark_to_position_to_equity_to_call_to_restriction
    """
    security = create_security_profile(symbol="ABC")
    post_marks_both(security["id"], 10_000)
    customer, account_id = setup_funded_account(1_000_000)
    place_order(account_id, customer["id"], security["id"], "BUY", 200)
    # A realtime-only drop must NOT run call evaluation.
    post_mark(security["id"], "REALTIME", 7_000)
    resp = api_client.list_account_margin_calls(
        account_id, TEST_USERS["supervisor_headers"]
    )
    rows, meta = validate_paginated(resp)
    assert meta["total_count"] == 0
    assert rows == []
    account = get_account(account_id)
    assert account["account_status"] == "ACTIVE"


def test_call_severity_prefers_maintenance_over_house(api):
    """PRD §3.7: "Four call types exist, in a fixed severity order:
    `MAINTENANCE` is most severe, then `HOUSE`, then `FED_REG_T`, then
    `DAY_TRADE_MIN_EQUITY`. At most one call is issued per evaluation — the
    most severe applicable type wins ..."
    PRD §3.7: "If the regulatory excess is negative, a `MAINTENANCE` call
    issues for the larger of the regulatory deficiency and the house
    deficiency."

    Design: Corner/calculations/call_type_severity_prefers_maintenance_over_house
    """
    security = create_security_profile(symbol="ABC", concentration_threshold_bps=6000)
    post_marks_both(security["id"], 10_000)
    customer, account_id = setup_funded_account(1_000_000)
    place_order(account_id, customer["id"], security["id"], "BUY", 200)
    # Official drop to 6000: mv 1200000, equity 200000.
    # Reg: 1200000*2500/10000 = 300000 -> reg excess -100000.
    # House: 100% share -> 3000+2000=5000bps -> 600000 -> house excess -400000.
    post_mark(security["id"], "OFFICIAL_CLOSE", 6_000)
    resp = api_client.list_account_margin_calls(account_id, TEST_USERS["supervisor_headers"])
    rows, _meta = validate_paginated(resp)
    assert len(rows) == 1
    assert rows[0]["call_type"] == "MAINTENANCE"
    assert rows[0]["call_amount_cents"] == 400_000


def test_house_call_deadline_expires_at_48h_not_before(api):
    """PRD §3.7: "Every call carries a deadline: `due_at` is `issued_at` plus a
    per-type grace period — 96 hours for `FED_REG_T`, 72 hours for
    `MAINTENANCE`, 48 hours for `HOUSE`, and 120 hours for
    `DAY_TRADE_MIN_EQUITY`."
    PRD §3.7: "The daily sweep expires any `OPEN` call whose `due_at` has been
    reached or passed, moving it to `EXPIRED` ..."

    Design: Corner/cross_cutting_layers/scheduled_call_deadline_by_type
    """
    ctx = setup_account_with_open_house_call()
    call = ctx["call"]
    # Issued at the default clock 2026-05-01T00:00:00Z; due at +48h.
    set_clock("2026-05-02T23:59:59Z")
    run_sweep()
    early = validate_success(
        api_client.get_margin_call(call["id"], TEST_USERS["supervisor_headers"])
    )
    assert early["call_status"] == "OPEN"

    set_clock("2026-05-03T00:00:01Z")
    run_sweep()
    late = validate_success(
        api_client.get_margin_call(call["id"], TEST_USERS["supervisor_headers"])
    )
    assert late["call_status"] == "EXPIRED"


def test_waive_from_cured_returns_call_not_open(api):
    """PRD §3.7: "A `MarginSupervisor` may also waive a call outright, but only
    while it is `OPEN` or `EXPIRED` — waiving from any other state is rejected
    with `ERR_CALL_NOT_OPEN`."
    PRD §3.9: "A deposit or credit that satisfies an `OPEN` call's cure test
    resolves it with `cure_method` `DEPOSIT`, followed by the posture recheck."

    Design: Corner/state_machines/waive_from_cured_returns_invalid_state
    """
    from test_helpers import ApiErrorId, deposit, validate_error

    ctx = setup_account_with_open_house_call()
    # Deposit the deficiency (300000) -> binding excess restored -> CURED.
    deposit(ctx["account_id"], ctx["customer"]["id"], 300_000)
    call = validate_success(
        api_client.get_margin_call(ctx["call"]["id"], TEST_USERS["supervisor_headers"])
    )
    assert call["call_status"] == "CURED"
    assert call["cure_method"] == "DEPOSIT"

    resp = api_client.waive_margin_call(call["id"], TEST_USERS["supervisor_headers"])
    validate_error(resp, ApiErrorId.ERR_CALL_NOT_OPEN)
