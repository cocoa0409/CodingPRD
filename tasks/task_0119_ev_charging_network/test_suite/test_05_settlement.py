"""Roaming settlement: round-then-sum batch total, the settle cascade, receivable
conservation on reversal, line-item settleability, OCC, and version increments.

Queue A (Difficulty): combinatorial_formula (round-then-sum), transitive_cascade
(settle depth-2), compensating_invariant (receivable conservation),
cross_entity_state_dependency (line-item requires RATED), boundary_precision_check
(empty-batch lock).
Queue B (Corner): settle-open invalid state, duplicate line item, OCC stale
versions, and per-mutation version increments.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_environment,
    setup_locked_batch_with_rated_session,
    rate_roaming_session,
    run_energy_session,
    open_batch,
    add_line_item,
    lock_batch,
    create_emsp,
    create_driver,
    create_site,
    create_tariff,
    create_stall,
    set_clock,
    start_session,
    make_driver_headers,
    TEST_USERS,
)

CPO = TEST_USERS["cpo_headers"]
STATION = TEST_USERS["station_headers"]


def test_settlement_batch_total_round_then_sum_order(api):
    """PRD §3.8: "The batch's `total_amount_cents` is then the plain integer sum of
    the net amounts of the batch's line items whose `status` is `PENDING` or
    `SETTLED`; reversed line items are excluded. This round-then-sum order — rounding
    each line's commission to whole cents before deriving and summing the nets — can
    differ by a cent from a sum-then-round order, and the round-then-sum order is the
    only sanctioned one."

    Design: Difficulty/combinatorial_formula/settlement_round_then_sum_order
    """
    env = setup_environment(commission_pct=0.075, email="rts@x.com")
    # Three extra CCS stalls so each roaming session has its own stall.
    s1 = create_stall(env["site"]["id"], connector_type="CCS", max_power_kw=60)
    s2 = create_stall(env["site"]["id"], connector_type="CCS", max_power_kw=60)
    s3 = create_stall(env["site"]["id"], connector_type="CCS", max_power_kw=60)
    # Session 1 -> 1825 (35 kWh, 50 charge min, 25 idle min)
    sess1 = run_energy_session(env, stall_id=s1["id"], begin_at="2026-06-01T00:00:00Z",
                               suspend_at="2026-06-01T00:50:00Z", end_at="2026-06-01T01:15:00Z",
                               end_kwh=35, is_roaming=True, stop_by_station=True)
    # Session 2 -> 2850 (75 kWh energy 1850, 28 idle min -> 18 billable -> 900, fee 100)
    sess2 = run_energy_session(env, stall_id=s2["id"], begin_at="2026-06-01T02:00:00Z",
                               suspend_at="2026-06-01T02:40:00Z", end_at="2026-06-01T03:08:00Z",
                               end_kwh=75, is_roaming=True, stop_by_station=True)
    # Session 3 -> 450 (10 kWh energy 300, 11 idle min -> 1 billable -> 50, fee 100)
    sess3 = run_energy_session(env, stall_id=s3["id"], begin_at="2026-06-01T04:00:00Z",
                               suspend_at="2026-06-01T04:30:00Z", end_at="2026-06-01T04:41:00Z",
                               end_kwh=10, is_roaming=True, stop_by_station=True)
    assert sess1["total_cost_cents"] == 1825
    assert sess2["total_cost_cents"] == 2850
    assert sess3["total_cost_cents"] == 450
    batch = open_batch(env["emsp"]["id"])
    add_line_item(batch["id"], sess1["id"])
    add_line_item(batch["id"], sess2["id"])
    add_line_item(batch["id"], sess3["id"])
    final = validate_success(api.get_settlement_batch(batch["id"], CPO), expected_status=200)
    # nets: 1825-137=1688, 2850-214=2636, 450-34=416 -> round-then-sum 4740 (NOT 4741)
    assert final["total_amount_cents"] == 4740, (
        f"round-then-sum total must be 4740, got {final['total_amount_cents']}"
    )
    assert final["line_item_count"] == 3, "three line items in the batch"


def test_line_item_commission_and_net_rounded_half_up(api):
    """PRD §3.7: "computes `commission_cents` as the gross multiplied by the eMSP's
    `commission_pct` rounded half up to whole cents, and derives `net_amount_cents`
    as the gross minus the commission — the amount remitted to the eMSP."

    Design: Difficulty/combinatorial_formula/settlement_round_then_sum_order
    """
    env = setup_environment(commission_pct=0.075, email="comm@x.com")
    sess = rate_roaming_session(env)  # 1825
    batch = open_batch(env["emsp"]["id"])
    li = add_line_item(batch["id"], sess["id"])
    # 1825 * 0.075 = 136.875 -> 137; net 1825 - 137 = 1688
    assert li["gross_amount_cents"] == 1825, f"gross == session total, got {li['gross_amount_cents']}"
    assert li["commission_cents"] == 137, f"commission round-half-up 136.875 -> 137, got {li['commission_cents']}"
    assert li["net_amount_cents"] == 1688, f"net 1825-137 = 1688, got {li['net_amount_cents']}"


def test_batch_settle_cascade_lineitems_then_sessions_depth2(api):
    """PRD §3.7: "Settling cascades two levels: each member line item moves
    `PENDING → SETTLED`, and each of those line items' sessions has its
    `billing_status` carried `RATED → SETTLED`".

    Design: Difficulty/transitive_cascade/batch_settle_cascade_lineitems_then_sessions_depth2
    """
    s = setup_locked_batch_with_rated_session()
    resp = api.settle_batch(s["batch"]["id"], {"expected_settlementbatch_version": s["batch_version"]}, CPO)
    batch = validate_success(resp, expected_status=200)
    assert batch["status"] == "SETTLED", "hop1: batch LOCKED -> SETTLED"
    li = validate_success(api.get_settlement_line_item(s["line_item"]["id"], CPO), expected_status=200)
    assert li["status"] == "SETTLED", "hop2: line item PENDING -> SETTLED"
    sess = validate_success(
        api.get_session(s["session"]["id"], make_driver_headers(s["driver"]["id"])),
        expected_status=200,
    )
    assert sess["billing_status"] == "SETTLED", "hop3: session billing_status RATED -> SETTLED"


def test_batch_settle_collects_receivable(api):
    """PRD §3.7: "the eMSP's `receivable_balance_cents` is decremented by
    `total_amount_cents` because the receivable has now been collected; and the
    batch's `version` increments."

    Design: Difficulty/transitive_cascade/batch_settle_cascade_lineitems_then_sessions_depth2
    """
    s = setup_locked_batch_with_rated_session()
    emsp_id = s["emsp"]["id"]
    locked = validate_success(api.get_settlement_batch(s["batch"]["id"], CPO), expected_status=200)
    before = validate_success(api.get_emsp(emsp_id, CPO), expected_status=200)["receivable_balance_cents"]
    assert before == locked["total_amount_cents"], "receivable holds the locked total before settle"
    settled = validate_success(
        api.settle_batch(s["batch"]["id"], {"expected_settlementbatch_version": s["batch_version"]}, CPO),
        expected_status=200,
    )
    after = validate_success(api.get_emsp(emsp_id, CPO), expected_status=200)["receivable_balance_cents"]
    assert after == before - locked["total_amount_cents"], (
        f"receivable decremented by total_amount_cents on settle: {before} - "
        f"{locked['total_amount_cents']} -> expected {before - locked['total_amount_cents']}, got {after}"
    )
    assert settled["version"] == s["batch_version"] + 1, "batch version increments on settle"


def test_emsp_receivable_conserved_on_lineitem_reverse(api):
    """PRD §3.7: "the eMSP's `receivable_balance_cents` is decremented by each
    reversed line item's `net_amount_cents` so the receivable returns exactly to its
    pre-add value with no drift".
    PRD §3.7: "Adding a line item recomputes the batch's `total_amount_cents` and
    `line_item_count` and increments the eMSP's `receivable_balance_cents` by the
    line item's `net_amount_cents`."

    Design: Difficulty/compensating_invariant/emsp_receivable_conservation_on_lineitem_reverse
    """
    env = setup_environment(commission_pct=0.075, email="rc@x.com")
    emsp_id = env["emsp"]["id"]
    sess = rate_roaming_session(env)  # 1825 -> net 1688
    batch = open_batch(emsp_id)
    add_line_item(batch["id"], sess["id"])
    after_add = validate_success(api.get_emsp(emsp_id, CPO), expected_status=200)
    assert after_add["receivable_balance_cents"] == 1688, (
        f"after add receivable == net 1688, got {after_add['receivable_balance_cents']}"
    )
    lock_batch(batch["id"])
    validate_success(api.dispute_batch(batch["id"], CPO), expected_status=200)
    validate_success(api.reopen_batch(batch["id"], CPO), expected_status=200)
    after_reverse = validate_success(api.get_emsp(emsp_id, CPO), expected_status=200)
    assert after_reverse["receivable_balance_cents"] == 0, (
        f"reversal returns receivable to pre-add 0 (no drift), got {after_reverse['receivable_balance_cents']}"
    )


def test_lineitem_reversal_carries_session_to_reversed(api):
    """PRD §3.7: "reopening reverses every line item still `PENDING`, moving each
    `PENDING → REVERSED` and carrying each reversed line item's session
    `billing_status` `RATED → REVERSED`".

    Design: Difficulty/compensating_invariant/emsp_receivable_conservation_on_lineitem_reverse
    """
    env = setup_environment(commission_pct=0.075, email="rev@x.com")
    sess = rate_roaming_session(env)
    batch = open_batch(env["emsp"]["id"])
    li = add_line_item(batch["id"], sess["id"])
    lock_batch(batch["id"])
    validate_success(api.dispute_batch(batch["id"], CPO), expected_status=200)
    validate_success(api.reopen_batch(batch["id"], CPO), expected_status=200)
    li_after = validate_success(api.get_settlement_line_item(li["id"], CPO), expected_status=200)
    assert li_after["status"] == "REVERSED", "pending line item reversed on reopen"
    sess_after = validate_success(
        api.get_session(sess["id"], make_driver_headers(env["driver"]["id"])), expected_status=200,
    )
    assert sess_after["billing_status"] == "REVERSED", (
        "reversed line item carries its session billing_status RATED -> REVERSED"
    )


def test_batch_lineitem_requires_session_rated(api):
    """PRD §3.7: "A line item may be added only for a session whose `billing_status`
    is `RATED`, whose `is_roaming` is true, and whose `emsp_id` matches the batch's
    `emsp_id`, and the session must not already appear in another line item; a session
    that fails any of these is rejected with `ERR_SESSION_NOT_SETTLEABLE`".

    Design: Difficulty/cross_entity_state_dependency/batch_lineitem_requires_session_rated
    """
    env = setup_environment(commission_pct=0.075, email="ns@x.com")
    did = env["driver"]["id"]
    # Started but never stopped -> billing_status UNBILLED.
    sess = start_session(env["stall"]["id"], did, is_roaming=True)
    batch = open_batch(env["emsp"]["id"])
    resp = api.add_line_item(batch["id"], {"session_id": sess["id"]}, CPO)
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_SETTLEABLE.value)


def test_batch_lineitem_rejects_home_rated_session(api):
    """PRD §3.7: "A line item may be added only for a session whose `billing_status`
    is `RATED`, whose `is_roaming` is true, and whose `emsp_id` matches the batch's
    `emsp_id`, and the session must not already appear in another line item; a session
    that fails any of these is rejected with `ERR_SESSION_NOT_SETTLEABLE`".

    Design: Difficulty/cross_entity_state_dependency/batch_lineitem_requires_session_rated
    """
    env = setup_environment(commission_pct=0.075, email="home@x.com")
    # A RATED but home (is_roaming false) session fails the roaming precondition.
    sess = run_energy_session(env, begin_at="2026-06-01T00:00:00Z",
                              suspend_at="2026-06-01T00:50:00Z", end_at="2026-06-01T01:15:00Z",
                              end_kwh=35, is_roaming=False, stop_by_station=True)
    assert sess["billing_status"] == "RATED", "session is RATED but not roaming"
    batch = open_batch(env["emsp"]["id"])
    resp = api.add_line_item(batch["id"], {"session_id": sess["id"]}, CPO)
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_SETTLEABLE.value)


def test_empty_batch_lock_zero_lineitems(api):
    """PRD §3.7: "locking requires the batch to be `OPEN` and to hold at least one
    line item — an attempt to lock a batch with zero line items is rejected with
    `ERR_EMPTY_BATCH`".

    Design: Difficulty/boundary_precision_check/empty_batch_lock_zero_lineitems
    """
    emsp = create_emsp(commission_pct=0.075)
    batch = open_batch(emsp["id"])
    resp = api.lock_batch(batch["id"], CPO)
    validate_error(resp, ApiErrorId.ERR_EMPTY_BATCH.value)
    after = validate_success(api.get_settlement_batch(batch["id"], CPO), expected_status=200)
    assert after["status"] == "OPEN", "rejected lock leaves the batch OPEN"


def test_non_empty_batch_locks_successfully(api):
    """PRD §3.7: "The operator locks a batch, moving it `OPEN → LOCKED`; locking
    requires the batch to be `OPEN` and to hold at least one line item — an attempt to
    lock a batch with zero line items is rejected with `ERR_EMPTY_BATCH` — and it
    freezes `total_amount_cents` by recomputing the round-then-sum of member net
    amounts described in §3.8".

    Design: Difficulty/boundary_precision_check/empty_batch_lock_zero_lineitems
    """
    env = setup_environment(commission_pct=0.075, email="nelb@x.com")
    sess = rate_roaming_session(env)  # 1825 -> net 1688
    batch = open_batch(env["emsp"]["id"])
    add_line_item(batch["id"], sess["id"])  # line_item_count == 1, just above the boundary
    locked = validate_success(api.lock_batch(batch["id"], CPO), expected_status=200)
    assert locked["status"] == "LOCKED", "a batch with >= 1 line item locks"
    assert locked["total_amount_cents"] == 1688, "lock freezes the round-then-sum total"


def test_settle_open_batch_returns_invalid_state(api):
    """PRD §2.7: "for any state-transition endpoint, that the target resource is in a
    state from which the requested transition is defined (`ERR_INVALID_STATE`)".
    PRD §3.7: "From `LOCKED` the operator settles the batch, moving it
    `LOCKED → SETTLED`".

    Design: Corner/state_machines/settle_open_batch_returns_invalid_state
    """
    env = setup_environment(commission_pct=0.075, email="sob@x.com")
    sess = rate_roaming_session(env)
    batch = open_batch(env["emsp"]["id"])
    add_line_item(batch["id"], sess["id"])
    current = validate_success(api.get_settlement_batch(batch["id"], CPO), expected_status=200)
    resp = api.settle_batch(batch["id"], {"expected_settlementbatch_version": current["version"]}, CPO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_duplicate_line_item_for_same_session_rejected(api):
    """PRD §3.7: "a session that already appears in a non-reversed line item is
    rejected with `ERR_DUPLICATE_LINE_ITEM`."

    Design: Corner/validations/duplicate_line_item_for_same_session_rejected
    """
    env = setup_environment(commission_pct=0.075, email="dl@x.com")
    sess = rate_roaming_session(env)
    batch = open_batch(env["emsp"]["id"])
    add_line_item(batch["id"], sess["id"])
    resp = api.add_line_item(batch["id"], {"session_id": sess["id"]}, CPO)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_LINE_ITEM.value)


def test_reservation_create_stale_stall_version(api):
    """PRD §2.9: "A request to create a reservation must carry `expected_stall_version`,
    and its value must equal the target stall's current `version`."
    PRD §2.9: "the client's view of stall availability is stale, and the create is
    rejected with `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/reservation_create_stale_stall_version
    """
    set_clock("2026-06-01T08:00:00Z")
    emsp = create_emsp(commission_pct=0.05)
    driver = create_driver(emsp["id"], email="occ@x.com", fund=100000)
    site = create_site(name="SOCC")
    stall = create_stall(site["id"])
    stv0 = stall["version"]
    did = driver["id"]
    # First create succeeds and advances the stall version.
    validate_success(
        api.create_reservation(
            {"stall_id": stall["id"], "driver_id": did,
             "window_start": "2026-06-01T20:00:00Z", "window_end": "2026-06-01T21:00:00Z",
             "hold_fee_cents": 0, "expected_stall_version": stv0},
            make_driver_headers(did),
        ),
        expected_status=201,
    )
    # Second create reuses the now-stale stv0.
    resp = api.create_reservation(
        {"stall_id": stall["id"], "driver_id": did,
         "window_start": "2026-06-01T22:00:00Z", "window_end": "2026-06-01T23:00:00Z",
         "hold_fee_cents": 0, "expected_stall_version": stv0},
        make_driver_headers(did),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_settle_batch_stale_version(api):
    """PRD §2.9: "A request to settle a settlement batch must carry
    `expected_settlementbatch_version`, and its value must equal the target batch's
    current `version`."
    PRD §2.9: "the client's view of the settlement total is stale, and the settle is
    rejected with `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/settle_batch_stale_version
    """
    s = setup_locked_batch_with_rated_session()
    stale = s["batch_version"] - 1
    resp = api.settle_batch(s["batch"]["id"], {"expected_settlementbatch_version": stale}, CPO)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_settlement_version_increments_per_mutation(api):
    """PRD §2.4: "The `version` field is an integer that begins at its initial value
    when the resource is created and increments by one on every mutation of that
    resource".
    PRD §3.7: "Adding a line item recomputes the batch's `total_amount_cents` and
    `line_item_count`". PRD §3.7: "locking ... freezes `total_amount_cents` ... then
    increments the batch's `version`."

    Design: Corner/cross_cutting_complexity_layers/settlement_version_increments_per_mutation
    """
    env = setup_environment(commission_pct=0.075, email="vi@x.com")
    sess = rate_roaming_session(env)
    batch = open_batch(env["emsp"]["id"])
    v_create = batch["version"]
    add_line_item(batch["id"], sess["id"])
    locked = lock_batch(batch["id"])
    # add (+1) and lock (+1) are each a batch mutation -> after lock == create + 2
    assert locked["version"] == v_create + 2, (
        f"version must advance by 2 across add+lock (create {v_create} -> {v_create + 2}), "
        f"got {locked['version']}"
    )


def test_immediate_consistency_cost_and_wallet_in_same_request(api):
    """PRD §2.5: "The system applies every such cascade immediately and synchronously
    within the triggering request".
    PRD §3.6: "For a home session (`is_roaming` false) the driver's
    `wallet_balance_cents` is debited by `total_cost_cents`".

    Design: Corner/consistency_model/immediate_consistency_cost_and_wallet_in_same_request
    """
    env = setup_environment(commission_pct=0.05, email="im@x.com")
    did = env["driver"]["id"]
    # 35 kWh / 50 charge / 25 idle home session -> 1825.
    sess = run_energy_session(env, begin_at="2026-06-01T00:00:00Z",
                              suspend_at="2026-06-01T00:50:00Z", end_at="2026-06-01T01:15:00Z",
                              end_kwh=35)
    assert sess["total_cost_cents"] == 1825, "stop response already carries total_cost_cents 1825"
    drv = validate_success(api.get_driver(did, make_driver_headers(did)), expected_status=200)
    assert drv["wallet_balance_cents"] == 98175, (
        f"wallet debited in the same request: 100000 - 1825 = 98175, got {drv['wallet_balance_cents']}"
    )
