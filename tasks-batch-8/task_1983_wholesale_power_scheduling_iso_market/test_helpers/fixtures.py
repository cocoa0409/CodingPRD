"""Composite setup helpers: multi-step state builders used across tests.

Every fixture builds its preconditions from scratch via PRD-declared endpoints
and returns the entities (or ids) the tests need. Setup calls use the lenient
get_success_data() so setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_participant_payload, create_generator_payload,
    create_operating_day_payload, create_offer_payload,
    create_telemetry_payload, create_outage_payload,
    create_award_payload, create_obligation_payload,
    create_performance_event_payload, create_posting_payload,
    uniform_readings_24,
)
from .test_users import (
    make_trader_headers, make_analyst_headers, make_credit_headers,
    make_iso_headers,
)

ISO = make_iso_headers()


def set_clock(to_iso8601: str):
    """Advance the logical clock."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ISO)
    get_success_data(resp)


def create_participant(company_name="Test Co", tier="INVESTMENT_GRADE"):
    """Create a participant, return (participant_dict, participant_id)."""
    payload = create_participant_payload(company_name=company_name, credit_rating_tier=tier)
    resp = api_client.create_participant(payload, ISO)
    p = get_success_data(resp)
    return p, p["id"]


def create_generator(participant_id, unit_name="U1", pricing_node="WEST_HUB", capacity_mw=10):
    """Create a generator, return (generator_dict, generator_id, version)."""
    payload = create_generator_payload(
        market_participant_id=participant_id, unit_name=unit_name,
        pricing_node=pricing_node, capacity_mw=capacity_mw,
    )
    resp = api_client.create_generator(payload, ISO)
    g = get_success_data(resp)
    return g, g["id"], g["version"]


def create_operating_day(market_date="2026-08-03", gate_close="2026-08-02T10:30:00Z"):
    """Create an operating day, return (day_dict, day_id, version)."""
    payload = create_operating_day_payload(market_date=market_date, da_gate_close_at=gate_close)
    resp = api_client.create_operating_day(payload, ISO)
    d = get_success_data(resp)
    return d, d["id"], d["version"]


def create_offer(day_id, generator_id, offered_mw=10, offer_price=5000, day_version=1,
                 participant_id=None):
    """Create a DRAFT offer, return (offer_dict, offer_id)."""
    trader_h = make_trader_headers(participant_id) if participant_id else make_trader_headers("t")
    payload = create_offer_payload(
        generator_asset_id=generator_id, offered_mw=offered_mw,
        offer_price_cents_per_mwh=offer_price, expected_operating_day_version=day_version,
    )
    resp = api_client.create_offer(day_id, payload, trader_h)
    o = get_success_data(resp)
    return o, o["id"]


def submit_offer(offer_id, participant_id):
    resp = api_client.submit_offer(offer_id, make_trader_headers(participant_id))
    return get_success_data(resp)


def withdraw_offer(offer_id, participant_id):
    resp = api_client.withdraw_offer(offer_id, make_trader_headers(participant_id))
    return get_success_data(resp)


def run_da_market(day_id, node_prices=None):
    if node_prices is None:
        node_prices = []
    resp = api_client.run_day_ahead_market(day_id, {"node_prices": node_prices}, ISO)
    return get_success_data(resp)


def close_real_time(day_id, rt_node_prices_prelim=None):
    if rt_node_prices_prelim is None:
        rt_node_prices_prelim = []
    resp = api_client.close_real_time(day_id, {"rt_node_prices_prelim": rt_node_prices_prelim}, ISO)
    return get_success_data(resp)


def run_prelim_settlement(day_id):
    resp = api_client.run_preliminary_settlement(day_id, ISO)
    return get_success_data(resp)


def run_final_settlement(day_id, rt_node_prices_final=None):
    if rt_node_prices_final is None:
        rt_node_prices_final = []
    resp = api_client.run_final_settlement(day_id, {"rt_node_prices_final": rt_node_prices_final}, ISO)
    return get_success_data(resp)


def close_operating_day(day_id):
    resp = api_client.close_operating_day(day_id, ISO)
    return get_success_data(resp)


def submit_telemetry(generator_id, day_id, readings, gen_version, participant_id):
    payload = create_telemetry_payload(
        operating_day_id=day_id, readings=readings,
        expected_generator_asset_version=gen_version,
    )
    resp = api_client.submit_telemetry(generator_id, payload, make_trader_headers(participant_id))
    return get_success_data(resp)


def get_generator_version(generator_id):
    resp = api_client.get_generator(generator_id, ISO)
    return get_success_data(resp)["version"]


def create_outage(generator_id, participant_id, outage_type="PARTIAL", derate_pct=50,
                  start_at="2026-08-05T00:00:00Z", end_at="2026-08-06T00:00:00Z",
                  reason="test outage"):
    payload = create_outage_payload(
        outage_type=outage_type, derate_pct=derate_pct,
        start_at=start_at, end_at=end_at, reason=reason,
    )
    resp = api_client.create_outage(generator_id, payload, make_trader_headers(participant_id))
    o = get_success_data(resp)
    return o, o["id"]


def create_award(day_id, generator_id, service_type="SYNC_RESERVE", awarded_mw=5,
                 capacity_price_cents=1200, start_interval=1, end_interval=4,
                 performance_price_cents=None, mileage_ratio=None):
    payload = create_award_payload(
        generator_asset_id=generator_id, service_type=service_type,
        awarded_mw=awarded_mw, capacity_price_cents=capacity_price_cents,
        start_interval=start_interval, end_interval=end_interval,
    )
    if performance_price_cents is not None:
        payload["performance_price_cents"] = performance_price_cents
    if mileage_ratio is not None:
        payload["mileage_ratio"] = mileage_ratio
    resp = api_client.create_award(day_id, payload, ISO)
    a = get_success_data(resp)
    return a, a["id"]


def create_obligation(generator_id, delivery_period="2026-08", obligated_mw=10,
                      capacity_rate=1000000):
    payload = create_obligation_payload(
        generator_asset_id=generator_id, delivery_period=delivery_period,
        obligated_mw=obligated_mw, capacity_rate_cents_per_mw=capacity_rate,
    )
    resp = api_client.create_obligation(payload, ISO)
    o = get_success_data(resp)
    return o, o["id"]


def create_posting(participant_id, amount_cents=100000, instrument_type="CASH"):
    payload = create_posting_payload(amount_cents=amount_cents, instrument_type=instrument_type)
    resp = api_client.create_posting(participant_id, payload, make_credit_headers(participant_id))
    p = get_success_data(resp)
    return p, p["id"]


def get_statement_by_day_and_type(day_id, participant_id, run_type):
    """Return the first statement matching (day, participant, run_type), or None."""
    resp = api_client.list_statements(ISO, params={
        "operating_day_id": day_id,
        "market_participant_id": participant_id,
        "run_type": run_type,
    })
    data = get_success_data(resp)
    rows = data if isinstance(data, list) else data.get("data", data)
    if isinstance(rows, dict):
        rows = rows.get("data", [])
    return rows[0] if rows else None


def get_open_margin_call(participant_id):
    """Return the first OPEN margin call for the participant, or None."""
    resp = api_client.list_margin_calls(ISO, params={
        "market_participant_id": participant_id, "status": "OPEN",
    })
    data = get_success_data(resp)
    rows = data if isinstance(data, list) else data.get("data", data)
    if isinstance(rows, dict):
        rows = rows.get("data", [])
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Tier 2 / Tier 3 composite fixtures
# ---------------------------------------------------------------------------

def setup_participant_generator(company="Setup Co", tier="INVESTMENT_GRADE",
                                unit="U1", node="WEST_HUB", capacity=10):
    """Participant + generator. Returns (p_id, g_id, g_version)."""
    _, p_id = create_participant(company_name=company, tier=tier)
    _, g_id, g_v = create_generator(p_id, unit_name=unit, pricing_node=node, capacity_mw=capacity)
    return p_id, g_id, g_v


def setup_day_with_offer(market_date="2026-08-03", gate_close="2026-08-02T10:30:00Z",
                         offered_mw=10, offer_price=5000, tier="INVESTMENT_GRADE",
                         capacity=10, node="WEST_HUB", clock="2026-08-01T00:00:00Z"):
    """Participant + generator + day + DRAFT offer.

    Returns (p_id, g_id, g_version, d_id, d_version, o_id).
    """
    set_clock(clock)
    p_id, g_id, g_v = setup_participant_generator(tier=tier, capacity=capacity, node=node)
    _, d_id, d_v = create_operating_day(market_date=market_date, gate_close=gate_close)
    _, o_id = create_offer(d_id, g_id, offered_mw=offered_mw, offer_price=offer_price,
                           day_version=d_v, participant_id=p_id)
    return p_id, g_id, g_v, d_id, d_v, o_id


def setup_cleared_offer_day(market_date="2026-08-03", gate_close="2026-08-02T10:30:00Z",
                            offered_mw=10, offer_price=5000, da_deck=None,
                            telemetry_mw=10, rt_prelim=None, tier="INVESTMENT_GRADE",
                            capacity=10, node="WEST_HUB", clock="2026-08-01T00:00:00Z"):
    """Full day through DA run + telemetry + close-real-time.

    Returns (p_id, g_id, d_id, o_id).
    """
    if da_deck is None:
        da_deck = [{"node_name": node, "da_energy_cents_per_mwh": 5000,
                    "da_congestion_cents_per_mwh": 200, "da_loss_cents_per_mwh": 100}]
    if rt_prelim is None:
        rt_prelim = [{"node_name": node, "rt_prelim_energy_cents_per_mwh": 4000,
                      "rt_prelim_congestion_cents_per_mwh": 50, "rt_prelim_loss_cents_per_mwh": 25}]
    p_id, g_id, g_v, d_id, d_v, o_id = setup_day_with_offer(
        market_date=market_date, gate_close=gate_close, offered_mw=offered_mw,
        offer_price=offer_price, tier=tier, capacity=capacity, node=node, clock=clock,
    )
    submit_offer(o_id, p_id)
    run_da_market(d_id, da_deck)
    readings = uniform_readings_24(telemetry_mw) if telemetry_mw is not None else []
    if readings:
        submit_telemetry(g_id, d_id, readings, g_v, p_id)
    close_real_time(d_id, rt_prelim)
    return p_id, g_id, d_id, o_id


def setup_preliminary_settled(market_date="2026-08-03", gate_close="2026-08-02T10:30:00Z",
                              offered_mw=10, offer_price=5000, da_deck=None,
                              telemetry_mw=10, rt_prelim=None, tier="INVESTMENT_GRADE",
                              capacity=10, node="WEST_HUB", clock="2026-08-01T00:00:00Z"):
    """Full day through preliminary settlement. Returns (p_id, g_id, d_id, statement)."""
    p_id, g_id, d_id, o_id = setup_cleared_offer_day(
        market_date=market_date, gate_close=gate_close, offered_mw=offered_mw,
        offer_price=offer_price, da_deck=da_deck, telemetry_mw=telemetry_mw,
        rt_prelim=rt_prelim, tier=tier, capacity=capacity, node=node, clock=clock,
    )
    run_prelim_settlement(d_id)
    s = get_statement_by_day_and_type(d_id, p_id, "PRELIMINARY")
    return p_id, g_id, d_id, s


def setup_final_settled(market_date="2026-08-03", gate_close="2026-08-02T10:30:00Z",
                        offered_mw=10, offer_price=5000, da_deck=None,
                        telemetry_mw=10, rt_prelim=None, rt_final=None,
                        tier="INVESTMENT_GRADE", capacity=10, node="WEST_HUB",
                        clock="2026-08-01T00:00:00Z"):
    """Full day through final settlement. Returns (p_id, g_id, d_id, final_statement)."""
    p_id, g_id, d_id, s_pre = setup_preliminary_settled(
        market_date=market_date, gate_close=gate_close, offered_mw=offered_mw,
        offer_price=offer_price, da_deck=da_deck, telemetry_mw=telemetry_mw,
        rt_prelim=rt_prelim, tier=tier, capacity=capacity, node=node, clock=clock,
    )
    run_final_settlement(d_id, rt_final or [])
    s_fin = get_statement_by_day_and_type(d_id, p_id, "FINAL")
    return p_id, g_id, d_id, s_fin


def setup_capacity_event_with_telemetry(p_id, g_id, g_v, day_id, event_start=1, event_end=2,
                                        actual_mw=6, participant_id=None):
    """Submit telemetry for event intervals and complete the event.

    Returns the completed event dict.
    """
    readings = [{"interval_index": i, "actual_mw": actual_mw}
                for i in range(event_start, event_end + 1)]
    submit_telemetry(g_id, day_id, readings, g_v, p_id)
    _, ev_id = None, None
    resp = api_client.create_performance_event(day_id, create_performance_event_payload(
        start_interval=event_start, end_interval=event_end,
    ), ISO)
    ev = get_success_data(resp)
    ev_id = ev["id"]
    api_client.activate_event(ev_id, ISO)
    api_client.complete_event(ev_id, ISO)
    resp = api_client.get_event(ev_id, ISO)
    return get_success_data(resp)
