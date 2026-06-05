"""Validation precedence pairs, cross-entity state dependencies, and tariff/site
business constraints at session start.

Queue A (Difficulty): priority_pair_validation_conflict, cross_entity_state_dependency
(session-start requires stall AVAILABLE), resource_temporal_overlap (tariff window).
Queue B (Corner): insufficient wallet on stop, no active tariff.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_environment,
    create_emsp,
    create_driver,
    create_site,
    create_stall,
    create_tariff,
    set_clock,
    start_session,
    post_meter,
    begin_charging,
    create_reservation,
    confirm_reservation,
    make_driver_headers,
    create_tariff_payload,
    TEST_USERS,
)

CPO = TEST_USERS["cpo_headers"]
STATION = TEST_USERS["station_headers"]


def test_session_start_requires_stall_available(api):
    """PRD §3.6: "Starting requires the target stall's `ocpp_status` to be
    `AVAILABLE`; a start against a stall in any other posture is rejected with
    `ERR_STALL_NOT_AVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/session_start_requires_stall_available
    """
    env = setup_environment(email="sa@x.com")
    did = env["driver"]["id"]
    # Take the stall to UNAVAILABLE.
    validate_success(
        api.post_stall_ocpp_status(env["stall"]["id"], {"reported_status": "UNAVAILABLE"}, STATION),
        expected_status=200,
    )
    resp = api.create_session({"stall_id": env["stall"]["id"], "driver_id": did},
                              make_driver_headers(did))
    validate_error(resp, ApiErrorId.ERR_STALL_NOT_AVAILABLE.value)


def test_session_start_on_occupied_stall_rejected(api):
    """PRD §3.6: "Starting requires the target stall's `ocpp_status` to be
    `AVAILABLE`; a start against a stall in any other posture is rejected with
    `ERR_STALL_NOT_AVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/session_start_requires_stall_available
    """
    env = setup_environment(email="sa2@x.com")
    did = env["driver"]["id"]
    # First session occupies the stall (AVAILABLE -> OCCUPIED).
    start_session(env["stall"]["id"], did)
    # A second start against the now-OCCUPIED stall is rejected.
    resp = api.create_session({"stall_id": env["stall"]["id"], "driver_id": did},
                              make_driver_headers(did))
    validate_error(resp, ApiErrorId.ERR_STALL_NOT_AVAILABLE.value)


def test_state_vs_fiscal_faulted_stall_beats_capacity(api):
    """PRD §3.6: "Starting requires the target stall's `ocpp_status` to be
    `AVAILABLE`; a start against a stall in any other posture is rejected with
    `ERR_STALL_NOT_AVAILABLE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_faulted_stall_beats_capacity
    """
    set_clock("2026-06-01T00:00:00Z")
    emsp = create_emsp(commission_pct=0.075)
    driver = create_driver(emsp["id"], email="pf@x.com")  # wallet 0
    site = create_site(name="Site PF")
    create_tariff(site["id"], connector_type="CCS")
    stall = create_stall(site["id"])
    did = driver["id"]
    # Fault the stall; the empty wallet would only matter at stop, never reached.
    validate_success(
        api.post_stall_ocpp_status(stall["id"], {"reported_status": "FAULTED"}, STATION),
        expected_status=200,
    )
    resp = api.create_session({"stall_id": stall["id"], "driver_id": did, "is_roaming": False},
                              make_driver_headers(did))
    # Start fails on stall availability; wallet sufficiency is never evaluated at start.
    validate_error(resp, ApiErrorId.ERR_STALL_NOT_AVAILABLE.value)


def test_state_check_independent_of_wallet_funding(api):
    """PRD §3.6: "Starting requires the target stall's `ocpp_status` to be
    `AVAILABLE`; a start against a stall in any other posture is rejected with
    `ERR_STALL_NOT_AVAILABLE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_faulted_stall_beats_capacity
    """
    set_clock("2026-06-01T00:00:00Z")
    emsp = create_emsp(commission_pct=0.075)
    # Same FAULTED-stall scenario but with a FULLY FUNDED wallet: the state-check
    # rejection is identical, proving wallet sufficiency does not gate session start.
    driver = create_driver(emsp["id"], email="pf2@x.com", fund=100000)
    site = create_site(name="Site PF2")
    create_tariff(site["id"], connector_type="CCS")
    stall = create_stall(site["id"])
    did = driver["id"]
    validate_success(
        api.post_stall_ocpp_status(stall["id"], {"reported_status": "FAULTED"}, STATION),
        expected_status=200,
    )
    resp = api.create_session({"stall_id": stall["id"], "driver_id": did, "is_roaming": False},
                              make_driver_headers(did))
    validate_error(resp, ApiErrorId.ERR_STALL_NOT_AVAILABLE.value)


def test_temporal_window_closed_check_in_after_window(api):
    """PRD §3.5: "check-in is permitted only when the current clock lies within the
    window from `window_start` up to but not including `window_end`".
    PRD §3.5: "A check-in attempted outside that window is rejected with
    `ERR_RESERVATION_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_window_closed_beats_overlap
    """
    set_clock("2026-06-01T08:00:00Z")
    emsp = create_emsp(commission_pct=0.075)
    driver = create_driver(emsp["id"], email="tw@x.com", fund=100000)
    site = create_site(name="Site TW")
    stall = create_stall(site["id"])
    did = driver["id"]
    env = {"driver": driver, "stall": stall}
    rid = create_reservation(env, window_start="2026-06-01T09:00:00Z",
                             window_end="2026-06-01T10:00:00Z", hold_fee_cents=0,
                             stall_version=stall["version"])["id"]
    confirm_reservation(rid, did)
    # Advance the clock past window_end, then attempt check-in.
    set_clock("2026-06-01T10:30:00Z")
    resp = api.check_in_reservation(rid, make_driver_headers(did))
    validate_error(resp, ApiErrorId.ERR_RESERVATION_WINDOW_CLOSED.value)


def test_temporal_window_closed_check_in_before_window(api):
    """PRD §3.5: "check-in is permitted only when the current clock lies within the
    window from `window_start` up to but not including `window_end`".
    PRD §3.5: "A check-in attempted outside that window is rejected with
    `ERR_RESERVATION_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_window_closed_beats_overlap
    """
    set_clock("2026-06-01T08:00:00Z")
    emsp = create_emsp(commission_pct=0.075)
    driver = create_driver(emsp["id"], email="tw2@x.com", fund=100000)
    site = create_site(name="Site TW2")
    stall = create_stall(site["id"])
    did = driver["id"]
    env = {"driver": driver, "stall": stall}
    rid = create_reservation(env, window_start="2026-06-01T09:00:00Z",
                             window_end="2026-06-01T10:00:00Z", hold_fee_cents=0,
                             stall_version=stall["version"])["id"]
    confirm_reservation(rid, did)
    # Clock is still 08:00, before window_start 09:00 -> outside the window.
    resp = api.check_in_reservation(rid, make_driver_headers(did))
    validate_error(resp, ApiErrorId.ERR_RESERVATION_WINDOW_CLOSED.value)


def test_tariff_effective_window_overlap_on_site(api):
    """PRD §3.3: "no two tariffs for the same `site_id` and `connector_type`
    combination may have overlapping effective windows; the interval is treated as
    closed, so windows that merely touch at an endpoint are permitted, but any
    genuine overlap is rejected with `ERR_TARIFF_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/tariff_effective_window_overlap_on_site
    """
    site = create_site(name="Site TWO")
    create_tariff(site["id"], connector_type="CCS",
                  effective_from="2026-01-01T00:00:00Z", effective_to="2026-09-01T00:00:00Z")
    resp = api.create_tariff(
        create_tariff_payload(site["id"], connector_type="CCS", pricing_mode="TIME_BASED",
                              effective_from="2026-06-01T00:00:00Z",
                              effective_to="2026-12-31T00:00:00Z"),
        CPO,
    )
    validate_error(resp, ApiErrorId.ERR_TARIFF_WINDOW_OVERLAP.value)


def test_tariff_touching_endpoints_permitted(api):
    """PRD §3.3: "no two tariffs for the same `site_id` and `connector_type`
    combination may have overlapping effective windows; the interval is treated as
    closed, so windows that merely touch at an endpoint are permitted, but any
    genuine overlap is rejected with `ERR_TARIFF_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/tariff_effective_window_overlap_on_site
    """
    site = create_site(name="Site TWT")
    create_tariff(site["id"], connector_type="CCS",
                  effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z")
    # Second window starts exactly where the first ends — touching, so permitted.
    resp = api.create_tariff(
        create_tariff_payload(site["id"], connector_type="CCS", pricing_mode="TIME_BASED",
                              effective_from="2026-06-01T00:00:00Z",
                              effective_to="2026-12-01T00:00:00Z"),
        CPO,
    )
    validate_success(resp, expected_status=201)


def test_insufficient_wallet_on_home_session_stop(api):
    """PRD §3.6: "For a home session (`is_roaming` false) the driver's
    `wallet_balance_cents` is debited by `total_cost_cents`; if that debit would
    drive the wallet below zero, the rating is rejected with
    `ERR_INSUFFICIENT_WALLET`."

    Design: Corner/validations/insufficient_wallet_on_home_session_stop
    """
    env = setup_environment(email="iw@x.com", fund=100)  # wallet 100, cost will exceed it
    did = env["driver"]["id"]
    sess = start_session(env["stall"]["id"], did, is_roaming=False)
    post_meter(sess["id"], 0, "2026-06-01T00:00:00Z", "TRANSACTION_BEGIN")
    begin_charging(sess["id"])
    set_clock("2026-06-01T00:50:00Z")
    post_meter(sess["id"], 35, "2026-06-01T00:50:00Z", "TRANSACTION_END")
    resp = api.stop_session(sess["id"], make_driver_headers(did))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_WALLET.value)


def test_no_active_tariff_for_stall_connector(api):
    """PRD §3.6: "the system resolves the session's `tariff_id` by finding the tariff
    matching the stall's `site_id` and `connector_type` whose effective window
    contains the session start clock; if no such tariff exists the start is rejected
    with `ERR_NO_ACTIVE_TARIFF`".

    Design: Corner/validations/no_active_tariff_for_stall_connector
    """
    set_clock("2026-06-01T00:00:00Z")
    emsp = create_emsp(commission_pct=0.05)
    driver = create_driver(emsp["id"], email="cm@x.com", fund=100000)
    site = create_site(name="SCM")
    # Only a CCS tariff exists.
    create_tariff(site["id"], connector_type="CCS")
    # The stall is CHADEMO -> no matching tariff.
    stall = create_stall(site["id"], connector_type="CHADEMO", max_power_kw=50)
    did = driver["id"]
    resp = api.create_session({"stall_id": stall["id"], "driver_id": did},
                              make_driver_headers(did))
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_TARIFF.value)
