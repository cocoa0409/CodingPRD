"""Charging-session and reservation lifecycles: parallel dimensions, the
reservation fork (consumed vs no-show), the depth-3 stall-fault cascade, plus
invalid-transition and meter guards.

Queue A (Difficulty): non_linear_state_machine (parallel dims + reservation
branching) and transitive_cascade (stall fault -> session -> site).
Queue B (Corner): begin-from-completed, meter regression, fault recovery cycle,
and the consumed-branch refund.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_environment,
    setup_charging_pool,
    set_clock,
    start_session,
    post_meter,
    begin_charging,
    suspend_session,
    create_emsp,
    create_driver,
    create_site,
    create_stall,
    create_tariff,
    create_reservation,
    confirm_reservation,
    make_driver_headers,
    TEST_USERS,
)

CPO = TEST_USERS["cpo_headers"]
STATION = TEST_USERS["station_headers"]


def test_session_parallel_charging_and_billing_dimensions(api):
    """PRD §3.6: "The same begin-charging action resumes a suspended session,
    advancing it `SUSPENDED → CHARGING`".
    PRD §3.6: "The financial `billing_status` is one of `UNBILLED`, `RATED`,
    `SETTLED`, or `REVERSED`, starting at `UNBILLED`, and it evolves independently of
    the physical dimension."

    Design: Difficulty/non_linear_state_machine/session_parallel_charging_and_billing_dimensions
    """
    env = setup_environment(email="par@x.com")
    did = env["driver"]["id"]
    sess = start_session(env["stall"]["id"], did)
    post_meter(sess["id"], 0, "2026-06-01T00:00:00Z", "TRANSACTION_BEGIN")
    begin_charging(sess["id"])
    set_clock("2026-06-01T00:10:00Z")
    suspend_session(sess["id"])
    resumed = validate_success(api.begin_charging(sess["id"], STATION), expected_status=200)
    assert resumed["charging_status"] == "CHARGING", "resumed via SUSPENDED->CHARGING cycle edge"
    assert resumed["billing_status"] == "UNBILLED", (
        "billing dimension untouched by the charging-dimension cycle"
    )


def test_session_dimensions_diverge_at_completion(api):
    """PRD §3.6: "Within the same request the physical dimension auto-advances
    `FINISHING → COMPLETED`. That completion drives the financial dimension
    `UNBILLED → RATED`".
    PRD §3.6: "The financial `billing_status` is one of `UNBILLED`, `RATED`,
    `SETTLED`, or `REVERSED`, starting at `UNBILLED`, and it evolves independently of
    the physical dimension."

    Design: Difficulty/non_linear_state_machine/session_parallel_charging_and_billing_dimensions
    """
    env = setup_environment(email="par2@x.com")
    did = env["driver"]["id"]
    sess = start_session(env["stall"]["id"], did)
    post_meter(sess["id"], 0, "2026-06-01T00:00:00Z", "TRANSACTION_BEGIN")
    begin_charging(sess["id"])
    set_clock("2026-06-01T00:20:00Z")
    post_meter(sess["id"], 10, "2026-06-01T00:20:00Z", "TRANSACTION_END")
    stopped = validate_success(api.stop_session(sess["id"], make_driver_headers(did)),
                               expected_status=200)
    # The two dimensions reach independent terminal/financial states in one request.
    assert stopped["charging_status"] == "COMPLETED", "physical dimension auto-advances to COMPLETED"
    assert stopped["billing_status"] == "RATED", "financial dimension advances UNBILLED -> RATED"


def test_reservation_no_show_branch_forfeits_hold(api):
    """PRD §3.5: "If instead the clock passes `window_end` while the reservation is
    still `CONFIRMED` with no check-in, the system carries it `CONFIRMED → NO_SHOW`,
    and the deposit is forfeited: the wallet was already debited at confirmation and
    is deliberately not credited back".

    Design: Difficulty/non_linear_state_machine/reservation_branching_consumed_vs_no_show_divergent_effects
    """
    set_clock("2026-06-01T08:00:00Z")
    emsp = create_emsp()
    driver = create_driver(emsp["id"], email="ns@x.com", fund=100000)
    site = create_site(name="Site N")
    stall = create_stall(site["id"])
    env = {"driver": driver, "stall": stall}
    rid = create_reservation(env, window_start="2026-06-01T09:00:00Z",
                             window_end="2026-06-01T10:00:00Z", hold_fee_cents=500,
                             stall_version=stall["version"])["id"]
    confirm_reservation(rid, driver["id"])
    set_clock("2026-06-01T10:30:00Z")
    resv = validate_success(api.get_reservation(rid, make_driver_headers(driver["id"])),
                            expected_status=200)
    assert resv["status"] == "NO_SHOW", "clock past window_end with no check-in -> NO_SHOW"
    drv = validate_success(api.get_driver(driver["id"], make_driver_headers(driver["id"])),
                           expected_status=200)
    assert drv["wallet_balance_cents"] == 99500, (
        "hold 500 forfeited, NOT refunded: 100000 - 500 = 99500"
    )


def test_reservation_consumed_branch_refunds_hold_divergent_from_no_show(api):
    """PRD §3.5: "When a checked-in reservation's session completes, the system
    carries the reservation `CHECKED_IN → CONSUMED` and refunds the deposit by
    crediting the driver's `wallet_balance_cents` by `hold_fee_cents` — branch A, the
    fulfilled path."

    Design: Difficulty/non_linear_state_machine/reservation_branching_consumed_vs_no_show_divergent_effects
    """
    set_clock("2026-06-01T09:00:00Z")
    emsp = create_emsp(commission_pct=0.05)
    driver = create_driver(emsp["id"], email="cons@x.com", fund=100000)
    site = create_site(name="Site Cons")
    create_tariff(site["id"], connector_type="CCS")
    stall = create_stall(site["id"])
    did = driver["id"]
    env = {"driver": driver, "stall": stall}
    rid = create_reservation(env, window_start="2026-06-01T09:00:00Z",
                             window_end="2026-06-01T11:00:00Z", hold_fee_cents=500,
                             stall_version=stall["version"])["id"]
    confirm_reservation(rid, did)
    validate_success(api.check_in_reservation(rid, make_driver_headers(did)), expected_status=200)
    sess = start_session(stall["id"], did, reservation_id=rid)
    post_meter(sess["id"], 0, "2026-06-01T09:00:00Z", "TRANSACTION_BEGIN")
    begin_charging(sess["id"])
    set_clock("2026-06-01T09:30:00Z")
    post_meter(sess["id"], 10, "2026-06-01T09:30:00Z", "TRANSACTION_END")
    validate_success(api.stop_session(sess["id"], make_driver_headers(did)), expected_status=200)
    resv = validate_success(api.get_reservation(rid, make_driver_headers(did)), expected_status=200)
    # CONSUMED refunds the hold — the mirror image of the NO_SHOW forfeit branch.
    assert resv["status"] == "CONSUMED", "fulfilled path -> CONSUMED (not NO_SHOW)"
    drv = validate_success(api.get_driver(did, make_driver_headers(did)), expected_status=200)
    # 100000 - 500 hold + 500 refund - 400 session cost = 99600 (vs no-show 99500: refund occurred)
    assert drv["wallet_balance_cents"] == 99600, (
        f"hold refunded on CONSUMED: expected 99600, got {drv['wallet_balance_cents']}"
    )


def test_reservation_consumed_branch_refunds_hold(api):
    """PRD §3.5: "When a checked-in reservation's session completes, the system
    carries the reservation `CHECKED_IN → CONSUMED` and refunds the deposit by
    crediting the driver's `wallet_balance_cents` by `hold_fee_cents`".

    Design: Corner/state_machines/reservation_consumed_branch_refunds_hold
    """
    set_clock("2026-06-01T09:00:00Z")
    emsp = create_emsp(commission_pct=0.05)
    driver = create_driver(emsp["id"], email="cb@x.com", fund=100000)
    site = create_site(name="SCB")
    create_tariff(site["id"], connector_type="CCS")
    stall = create_stall(site["id"])
    did = driver["id"]
    env = {"driver": driver, "stall": stall}
    rid = create_reservation(env, window_start="2026-06-01T09:00:00Z",
                             window_end="2026-06-01T11:00:00Z", hold_fee_cents=500,
                             stall_version=stall["version"])["id"]
    confirm_reservation(rid, did)
    validate_success(api.check_in_reservation(rid, make_driver_headers(did)), expected_status=200)
    sess = start_session(stall["id"], did, reservation_id=rid)
    post_meter(sess["id"], 0, "2026-06-01T09:00:00Z", "TRANSACTION_BEGIN")
    begin_charging(sess["id"])
    set_clock("2026-06-01T09:30:00Z")
    post_meter(sess["id"], 10, "2026-06-01T09:30:00Z", "TRANSACTION_END")
    validate_success(api.stop_session(sess["id"], make_driver_headers(did)), expected_status=200)
    resv = validate_success(api.get_reservation(rid, make_driver_headers(did)), expected_status=200)
    assert resv["status"] == "CONSUMED", "checked-in session completion -> CONSUMED"
    drv = validate_success(api.get_driver(did, make_driver_headers(did)), expected_status=200)
    # 100000 - 500 hold + 500 refund - 400 session cost (10 kWh*30 + 100 fee) = 99600
    assert drv["wallet_balance_cents"] == 99600, (
        f"hold refunded then session cost debited: expected 99600, got {drv['wallet_balance_cents']}"
    )


def test_stall_fault_suspends_session_then_reallocates_site_depth3(api):
    """PRD §2.5: "When a `StationController` reports a station as faulted and a stall
    moves to `FAULTED` while one of its sessions is in `PREPARING`, `CHARGING`, or
    `SUSPENDED`, the system forces that session's `charging_status` to `SUSPENDED`,
    sets the session's `allocated_power_kw` to 0, and then re-runs the site
    load-balance computation with a trigger reason of `SESSION_SUSPEND` so the freed
    power flows to the remaining charging sessions".

    Design: Difficulty/transitive_cascade/stall_fault_suspends_session_then_reallocates_site_depth3
    """
    env = setup_charging_pool(
        circuit_limit_kw=60, allocation_policy="PRIORITY",
        stalls=[{"max_power_kw": 60, "reservation_priority": 1},
                {"max_power_kw": 60, "reservation_priority": 2}],
    )
    stall_a, stall_b = env["stalls"]
    sess_a, sess_b = env["sessions"]
    did = env["driver"]["id"]
    # hop1: fault stall A
    faulted = validate_success(
        api.post_stall_ocpp_status(stall_a["id"], {"reported_status": "FAULTED"}, STATION),
        expected_status=200,
    )
    assert faulted["ocpp_status"] == "FAULTED", "hop1: stall A -> FAULTED"
    # hop2: session A forced SUSPENDED with 0 kW
    sa = validate_success(api.get_session(sess_a["id"], make_driver_headers(did)), expected_status=200)
    assert sa["charging_status"] == "SUSPENDED", "hop2: session A forced to SUSPENDED"
    assert sa["allocated_power_kw"] == 0.0, "hop2: session A allocated_power_kw set to 0"
    # hop3: surviving session B gains the freed 60 kW
    sb = validate_success(api.get_session(sess_b["id"], make_driver_headers(did)), expected_status=200)
    assert sb["allocated_power_kw"] == 60.0, "hop3: freed 60 kW reallocated to session B"


def test_stall_fault_cascade_conserves_site_power(api):
    """PRD §2.5: "the system forces that session's `charging_status` to `SUSPENDED`,
    sets the session's `allocated_power_kw` to 0, and then re-runs the site
    load-balance computation with a trigger reason of `SESSION_SUSPEND` so the freed
    power flows to the remaining charging sessions — a three-level chain from stall to
    session to site."

    Design: Difficulty/transitive_cascade/stall_fault_suspends_session_then_reallocates_site_depth3
    """
    env = setup_charging_pool(
        circuit_limit_kw=60, allocation_policy="PRIORITY",
        stalls=[{"max_power_kw": 60, "reservation_priority": 1},
                {"max_power_kw": 60, "reservation_priority": 2}],
    )
    stall_a = env["stalls"][0]
    # Fault A; the site-level recompute (hop3) keeps allocated_total_kw at the cap.
    validate_success(
        api.post_stall_ocpp_status(stall_a["id"], {"reported_status": "FAULTED"}, STATION),
        expected_status=200,
    )
    site = validate_success(api.get_site(env["site"]["id"], CPO), expected_status=200)
    assert site["allocated_total_kw"] == 60.0, (
        "site recompute reassigns the freed 60 kW; allocated_total_kw stays at cap 60"
    )


def test_begin_charging_from_completed_returns_invalid_state(api):
    """PRD §2.7: "for any state-transition endpoint, that the target resource is in a
    state from which the requested transition is defined (`ERR_INVALID_STATE`)".
    PRD §3.6: "this transition requires the session's `charging_status` to be
    `PREPARING`".

    Design: Corner/state_machines/begin_charging_from_completed_returns_invalid_state
    """
    env = setup_environment(email="cmp@x.com")
    did = env["driver"]["id"]
    sess = start_session(env["stall"]["id"], did)
    post_meter(sess["id"], 0, "2026-06-01T00:00:00Z", "TRANSACTION_BEGIN")
    begin_charging(sess["id"])
    set_clock("2026-06-01T00:30:00Z")
    post_meter(sess["id"], 10, "2026-06-01T00:30:00Z", "TRANSACTION_END")
    validate_success(api.stop_session(sess["id"], make_driver_headers(did)), expected_status=200)
    resp = api.begin_charging(sess["id"], STATION)  # session is COMPLETED
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_meter_regression_rejected(api):
    """PRD §3.6: "a cumulative lifetime `meter_kwh` reading that must be at least 0
    and monotonically non-decreasing within the session".
    PRD §3.6: "A reading below the session's prior reading is rejected with
    `ERR_METER_REGRESSION`."

    Design: Corner/state_machines/meter_regression_rejected
    """
    env = setup_environment(email="mr@x.com")
    sess = start_session(env["stall"]["id"], env["driver"]["id"])
    post_meter(sess["id"], 10, "2026-06-01T00:00:00Z", "TRANSACTION_BEGIN")
    resp = api.create_meter_event(
        sess["id"], {"meter_kwh": 8, "sampled_at": "2026-06-01T00:05:00Z",
                     "reading_context": "SAMPLE_PERIODIC"}, STATION,
    )
    validate_error(resp, ApiErrorId.ERR_METER_REGRESSION.value)


def test_stall_fault_recovery_cycle_back_to_available(api):
    """PRD §3.1: "A station reporting a fault while the stall is `AVAILABLE` or
    `OCCUPIED` moves it to `FAULTED`; a station reporting availability again while
    the stall is `FAULTED` recovers it `FAULTED → AVAILABLE`".

    Design: Corner/state_machines/stall_fault_recovery_cycle_back_to_available
    """
    site = create_site(name="SFR", circuit_limit_kw=100, demand_charge_threshold_kw=100)
    stall = create_stall(site["id"])
    validate_success(
        api.post_stall_ocpp_status(stall["id"], {"reported_status": "FAULTED"}, STATION),
        expected_status=200,
    )
    recovered = validate_success(
        api.post_stall_ocpp_status(stall["id"], {"reported_status": "AVAILABLE"}, STATION),
        expected_status=200,
    )
    assert recovered["ocpp_status"] == "AVAILABLE", "FAULTED -> AVAILABLE recovery"
