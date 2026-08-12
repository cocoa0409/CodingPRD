"""Liquidation order creation, selection, filling, cancellation."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_liquidation_order_payload,
    create_security_profile,
    deposit,
    get_account,
    get_account_version,
    make_customer_headers,
    make_desk_headers,
    place_order,
    post_mark,
    post_marks_both,
    run_sweep,
    set_clock,
    setup_account_with_open_house_call,
    setup_expired_house_call,
    setup_funded_account,
    setup_liquidation_order,
    TEST_USERS,
    validate_error,
    validate_success,
)


def test_liquidation_requires_call_expired(api):
    """PRD §3.9: "The referenced call must stand in `EXPIRED` — any other state
    is rejected with `ERR_CALL_NOT_EXPIRED` ..."

    Design: Difficulty/cross_entity_state_dependency/liquidation_requires_call_expired_pair_liqorder_call
    """
    ctx = setup_account_with_open_house_call()
    version = get_account_version(ctx["account_id"])
    resp = api_client.create_liquidation_order(
        ctx["account_id"],
        create_liquidation_order_payload(ctx["call"]["id"], version),
        make_desk_headers("desk-1"),
    )
    validate_error(resp, ApiErrorId.ERR_CALL_NOT_EXPIRED)


def test_liquidation_after_expiry_selects_whole_position(api):
    """PRD §3.9: "The selector takes whole positions in rank order until the
    cumulative absolute official market value reaches at least
    `call_amount_cents`; each selected position is liquidated in full, the
    order's `quantity` being the absolute size of that position."

    Design: Difficulty/cross_entity_state_dependency/liquidation_requires_call_expired_pair_liqorder_call
    """
    ctx = setup_expired_house_call()
    version = get_account_version(ctx["account_id"])
    order = validate_success(
        api_client.create_liquidation_order(
            ctx["account_id"],
            create_liquidation_order_payload(ctx["call"]["id"], version),
            make_desk_headers("desk-1"),
        ),
        expected_status=201,
    )
    assert order["order_status"] == "PENDING"
    assert order["quantity"] == 200
    assert order["position_id"] == ctx["position"]["id"]


def test_liquidation_lock_blocks_second_create_until_cancel(api):
    """PRD §3.9: "the account must not already carry a non-terminal liquidation
    order: while any earlier order on the account remains `PENDING` or
    `PARTIALLY_FILLED`, a fresh creation is rejected with
    `ERR_LIQUIDATION_IN_PROGRESS`."

    Design: Difficulty/resource_temporal_overlap/liquidation_lock_half_open_lifetime_on_account
    """
    ctx = setup_liquidation_order()
    version = get_account_version(ctx["account_id"])
    resp = api_client.create_liquidation_order(
        ctx["account_id"],
        create_liquidation_order_payload(ctx["call"]["id"], version),
        make_desk_headers("desk-1"),
    )
    validate_error(resp, ApiErrorId.ERR_LIQUIDATION_IN_PROGRESS)

    # Cancel at the same clock instant -> lock releases.
    api_client.cancel_liquidation_order(ctx["order"]["id"], make_desk_headers("desk-1"))
    version = get_account_version(ctx["account_id"])
    second = validate_success(
        api_client.create_liquidation_order(
            ctx["account_id"],
            create_liquidation_order_payload(ctx["call"]["id"], version),
            make_desk_headers("desk-1"),
        ),
        expected_status=201,
    )
    assert second["order_status"] == "PENDING"


def test_liquidation_fill_cascades_to_cure_and_activation(api):
    """PRD §3.9: "After each fill the call's cure test runs: the call moves
    from `LIQUIDATION_IN_PROGRESS` to `CURED` with `cure_method` `LIQUIDATION`
    and `resolved_at` stamped when either the binding official maintenance
    excess is back at zero or above, or the cumulative `proceeds_cents` across
    the call's orders reaches `call_amount_cents`; the posture recheck
    follows."

    Design: Difficulty/transitive_cascade/liquidation_fill_cascades_fill_to_position_to_equity_to_cure_to_activation
    """
    ctx = setup_liquidation_order()
    filled = validate_success(
        api_client.fill_liquidation_order(
            ctx["order"]["id"],
            {"filled_quantity": 200, "fill_price_cents": 7_000},
            make_desk_headers("desk-2"),
        )
    )
    assert filled["order_status"] == "EXECUTED"
    account = get_account(ctx["account_id"])
    assert account["cash_balance_cents"] == 400_000  # -1000000 + 200*7000
    call = validate_success(
        api_client.get_margin_call(ctx["call"]["id"], TEST_USERS["supervisor_headers"])
    )
    assert call["call_status"] == "CURED"
    assert call["cure_method"] == "LIQUIDATION"
    assert account["account_status"] == "ACTIVE"


def test_liquidation_fill_partial_then_executed(api):
    """PRD §3.9: "the order's `order_status` advances to `PARTIALLY_FILLED` —
    or straight to `EXECUTED` when the fill completes the entire remaining
    quantity."

    Design: Difficulty/transitive_cascade/liquidation_fill_cascades_fill_to_position_to_equity_to_cure_to_activation
    """
    ctx = setup_liquidation_order()
    partial = validate_success(
        api_client.fill_liquidation_order(
            ctx["order"]["id"],
            {"filled_quantity": 100, "fill_price_cents": 7_000},
            make_desk_headers("desk-2"),
        )
    )
    assert partial["order_status"] == "PARTIALLY_FILLED"
    assert partial["filled_quantity"] == 100
    executed = validate_success(
        api_client.fill_liquidation_order(
            ctx["order"]["id"],
            {"filled_quantity": 100, "fill_price_cents": 7_000},
            make_desk_headers("desk-2"),
        )
    )
    assert executed["order_status"] == "EXECUTED"
    assert executed["filled_quantity"] == 200


def test_liquidation_create_then_cancel_conserves_position_shares(api):
    """PRD §3.9: "Cancelling is allowed from `PENDING` or `PARTIALLY_FILLED`
    (else `ERR_LIQUIDATION_INVALID_STATE`) and lands the order in its other
    terminal state, `CANCELLED`; the unfilled remainder is subtracted from the
    position's `reserved_qty`, while fills already applied are not reversed."

    Design: Difficulty/compensating_invariant/liquidation_create_then_cancel_conserves_position_shares
    """
    ctx = setup_liquidation_order()
    position_id = ctx["position"]["id"]
    mid = validate_success(
        api_client.get_position(position_id, TEST_USERS["supervisor_headers"])
    )
    assert mid["quantity"] == 200
    assert mid["reserved_qty"] == 200

    cancelled = validate_success(
        api_client.cancel_liquidation_order(ctx["order"]["id"], make_desk_headers("desk-1"))
    )
    assert cancelled["order_status"] == "CANCELLED"
    end = validate_success(
        api_client.get_position(position_id, TEST_USERS["supervisor_headers"])
    )
    assert end["quantity"] == 200
    assert end["reserved_qty"] == 0


def test_fill_on_cancelled_order_returns_invalid_state(api):
    """PRD §3.9: "the order must stand in `PENDING` or `PARTIALLY_FILLED`
    (else `ERR_LIQUIDATION_INVALID_STATE`) ..."

    Design: Corner/state_machines/fill_on_cancelled_order_returns_invalid_state
    """
    ctx = setup_liquidation_order()
    api_client.cancel_liquidation_order(ctx["order"]["id"], make_desk_headers("desk-1"))
    resp = api_client.fill_liquidation_order(
        ctx["order"]["id"],
        {"filled_quantity": 200, "fill_price_cents": 7_000},
        make_desk_headers("desk-2"),
    )
    validate_error(resp, ApiErrorId.ERR_LIQUIDATION_INVALID_STATE)


def test_fill_exceeds_remaining_quantity_rejected(api):
    """PRD §3.9: "`filled_quantity` must be positive and no greater than the
    remaining unfilled quantity (else `ERR_FILL_EXCEEDS_QUANTITY`)."

    Design: Corner/errors/error_fill_exceeds_quantity
    """
    ctx = setup_liquidation_order()
    resp = api_client.fill_liquidation_order(
        ctx["order"]["id"],
        {"filled_quantity": 201, "fill_price_cents": 7_000},
        make_desk_headers("desk-2"),
    )
    validate_error(resp, ApiErrorId.ERR_FILL_EXCEEDS_QUANTITY)


def test_desk_creator_cannot_fill_own_order(api):
    """PRD §2.1: "the desk user who fills a liquidation order must not be the
    desk user who created it ... Any such self-dealing attempt is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/segregation_desk_creator_cannot_fill_own_order
    """
    ctx = setup_liquidation_order(desk_user="desk-1")
    resp = api_client.fill_liquidation_order(
        ctx["order"]["id"],
        {"filled_quantity": 200, "fill_price_cents": 7_000},
        make_desk_headers("desk-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_selector_ranks_by_liquidity_tier_then_value(api):
    """PRD §3.9: "Eligible positions are ranked by their security's
    `liquidity_tier` ascending, then by absolute `mv_official_cents`
    descending, with ties broken by `opened_at` ascending — never by `id`."

    Design: Corner/calculations/liquidation_selector_ranks_by_liquidity_tier_then_value_then_opened_at
    """
    # Thresholds 2500bps make both positions concentrated after the mark drop
    # (shares 1400/4900 and 3500/4900 both strictly exceed 2500bps), so the
    # house requirement (4000bps incl. the 1000bps mid-band add-on) exceeds
    # equity and the cascade issues a HOUSE call — expiring at the +48h sweep
    # below. (At 9500bps no add-on applies and the same arithmetic issues a
    # FED_REG_T call with a 96h deadline instead.)
    abc = create_security_profile(
        symbol="ABC", liquidity_tier=1, concentration_threshold_bps=2500
    )
    xyz = create_security_profile(
        symbol="XYZ", liquidity_tier=5, concentration_threshold_bps=2500
    )
    post_marks_both(abc["id"], 10_000)
    post_marks_both(xyz["id"], 10_000)
    customer, account_id = setup_funded_account(4_000_000)
    pos_abc = place_order(account_id, customer["id"], abc["id"], "BUY", 200)
    place_order(account_id, customer["id"], xyz["id"], "BUY", 500)
    # Drop both official marks to 7000 -> ABC mv 1400000, XYZ mv 3500000.
    post_mark(abc["id"], "OFFICIAL_CLOSE", 7_000)
    post_mark(xyz["id"], "OFFICIAL_CLOSE", 7_000)
    from test_helpers import validate_paginated

    resp = api_client.list_account_margin_calls(account_id, TEST_USERS["supervisor_headers"])
    rows, _meta = validate_paginated(resp)
    assert rows, "Setup failed: expected a margin call"
    call = rows[0]
    set_clock("2026-05-03T00:00:01Z")
    run_sweep()
    version = get_account_version(account_id)
    order = validate_success(
        api_client.create_liquidation_order(
            account_id,
            create_liquidation_order_payload(call["id"], version),
            make_desk_headers("desk-1"),
        ),
        expected_status=201,
    )
    # Liquidity tier 1 (ABC) dominates despite smaller market value.
    assert order["position_id"] == pos_abc["id"]
    assert order["quantity"] == 200


def test_no_liquidatable_positions_on_flat_account(api):
    """PRD §3.9: "If no positions are eligible, or the total eligible official
    market value falls short of the call amount, creation is rejected with
    `ERR_NO_LIQUIDATABLE_POSITIONS`."

    Design: Corner/errors/error_no_liquidatable_positions
    """
    from test_helpers import setup_pdt_account, withdraw

    # PDT-flagged cash-only account; withdraw to push equity below 2500000 so
    # the sweep issues a DAY_TRADE_MIN_EQUITY call with zero positions held.
    ctx = setup_pdt_account()
    account_id = ctx["account_id"]
    customer_id = ctx["customer"]["id"]
    resp = withdraw(account_id, customer_id, 600_000)
    validate_success(resp, expected_status=201)
    set_clock("2026-05-02T00:00:00Z")
    run_sweep()
    from test_helpers import validate_paginated

    calls_resp = api_client.list_account_margin_calls(
        account_id, TEST_USERS["supervisor_headers"]
    )
    rows, _meta = validate_paginated(calls_resp)
    assert rows, "Setup failed: expected a DAY_TRADE_MIN_EQUITY call"
    call = rows[0]
    assert call["call_type"] == "DAY_TRADE_MIN_EQUITY"
    # DTME deadline is 120h; advance past it and sweep to EXPIRED.
    set_clock("2026-05-08T00:00:00Z")
    run_sweep()
    expired = validate_success(
        api_client.get_margin_call(call["id"], TEST_USERS["supervisor_headers"])
    )
    assert expired["call_status"] == "EXPIRED"
    version = get_account_version(account_id)
    resp = api_client.create_liquidation_order(
        account_id,
        create_liquidation_order_payload(call["id"], version),
        make_desk_headers("desk-1"),
    )
    validate_error(resp, ApiErrorId.ERR_NO_LIQUIDATABLE_POSITIONS)


def test_occ_stale_version_on_liquidation_create(api):
    """PRD §2.8: "If `expected_account_version` does not match the account's
    current `version` — because another writer has since posted a movement,
    filled an order, or run a sweep cascade against the same account, advancing
    its version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_liquidation_create
    """
    ctx = setup_account_with_open_house_call()
    # Capture the version BEFORE the expiry sweep; the sweep mutates the
    # account (expiry cascade) and bumps its version.
    stale_version = get_account_version(ctx["account_id"])
    set_clock("2026-05-03T00:00:01Z")
    run_sweep()
    resp = api_client.create_liquidation_order(
        ctx["account_id"],
        create_liquidation_order_payload(ctx["call"]["id"], stale_version),
        make_desk_headers("desk-1"),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
