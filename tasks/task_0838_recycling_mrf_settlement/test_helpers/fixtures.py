"""Composite setup helpers.

Each function takes the ApiClient as its first argument and drives the PRD's
declared endpoints to reach a target state, returning the created resources.
Setup calls use get_success_data() (lenient) so setup failures surface clearly.

The test harness restarts the server (empty DB, logical clock reset to
2026-03-01T00:00:00Z) before every test, so every helper builds its
preconditions from scratch.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS

SCALE = TEST_USERS["scale_operator_headers"]
SORT = TEST_USERS["sort_manager_headers"]
TRADER = TEST_USERS["commodity_trader_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]

# A March window that covers the common test clock 2026-03-10.
MARCH_START = "2026-03-01T00:00:00Z"
APRIL_START = "2026-04-01T00:00:00Z"
DEFAULT_TEST_CLOCK = "2026-03-10T00:00:00Z"


# --- Primitive creators ------------------------------------------------------

def set_clock(api, to_iso8601, headers=TRADER):
    return get_success_data(api.set_clock(to_iso8601, headers))


def create_municipality(api, revenue_share_pct=0.50, name="City A", **overrides):
    payload = {"name": name, "revenue_share_pct": revenue_share_pct}
    payload.update(overrides)
    return get_success_data(api.create_municipality(payload, CLERK))


def create_mill(api, commodity_focus="OCC", freight_rate_cents_per_ton=0, name="Mill 1"):
    payload = {"name": name, "commodity_focus": commodity_focus,
               "freight_rate_cents_per_ton": freight_rate_cents_per_ton}
    return get_success_data(api.create_mill(payload, TRADER))


def create_sort_line(api, name="Line 1", rated_tph=10, scheduled_shift_minutes=None):
    payload = {"name": name, "rated_tph": rated_tph}
    if scheduled_shift_minutes is not None:
        payload["scheduled_shift_minutes"] = scheduled_shift_minutes
    return get_success_data(api.create_sort_line(payload, SORT))


def create_index(api, commodity="OCC", price_cents_per_ton=8000,
                 effective_start=MARCH_START, effective_end=APRIL_START):
    payload = {"commodity": commodity, "price_cents_per_ton": price_cents_per_ton,
               "effective_start": effective_start, "effective_end": effective_end}
    return get_success_data(api.create_commodity_index(payload, TRADER))


def publish_index(api, index_id):
    return get_success_data(api.publish_commodity_index(index_id, TRADER))


def create_and_publish_index(api, commodity="OCC", price_cents_per_ton=8000,
                             effective_start=MARCH_START, effective_end=APRIL_START):
    idx = create_index(api, commodity, price_cents_per_ton, effective_start, effective_end)
    publish_index(api, idx["id"])
    return idx


def create_downtime_event(api, sort_line_id, start_at, end_at, reason="jam"):
    payload = {"sort_line_id": sort_line_id, "start_at": start_at,
               "end_at": end_at, "reason": reason}
    return get_success_data(api.create_downtime_event(payload, SORT))


def create_load(api, municipality_id, sort_line_id, gross_tons=22, tare_tons=2, hauler="H1"):
    payload = {"source_municipality_id": municipality_id, "sort_line_id": sort_line_id,
               "hauler": hauler, "gross_tons": gross_tons, "tare_tons": tare_tons}
    return get_success_data(api.create_inbound_load(payload, SCALE))


def audit_load(api, load_id, sampled_contamination_pct=3.0, audited_composition=None):
    if audited_composition is None:
        audited_composition = [{"commodity": "OCC", "pct": 99}]
    payload = {"sampled_contamination_pct": sampled_contamination_pct,
               "audited_composition": audited_composition}
    return get_success_data(api.audit_inbound_load(load_id, payload, SCALE))


def close_load(api, load_id, residual_tons=0):
    return get_success_data(
        api.close_inbound_load(load_id, {"residual_tons": residual_tons}, SORT))


def create_bale(api, source_load_id, commodity="OCC", net_tons=10,
                moisture_pct=0, quality_grade="A"):
    payload = {"source_load_id": source_load_id, "commodity": commodity,
               "net_tons": net_tons, "moisture_pct": moisture_pct,
               "quality_grade": quality_grade}
    return get_success_data(api.create_bale(payload, SORT))


def create_shipment(api, mill_id, commodity="OCC", freight_cost_cents=0):
    payload = {"mill_id": mill_id, "commodity": commodity,
               "freight_cost_cents": freight_cost_cents}
    return get_success_data(api.create_mill_shipment(payload, TRADER))


def assign_bale(api, shipment_id, bale_id):
    return get_success_data(
        api.assign_bale_to_shipment(shipment_id, {"bale_id": bale_id}, TRADER))


def ship_shipment(api, shipment_id):
    return get_success_data(api.ship_mill_shipment(shipment_id, TRADER))


def settle_shipment(api, shipment_id):
    return get_success_data(api.settle_mill_shipment(shipment_id, TRADER))


def dispute_shipment(api, shipment_id, reason="dispute"):
    return get_success_data(
        api.dispute_mill_shipment(shipment_id, {"reason": reason}, TRADER))


def create_statement(api, municipality_id, expected_municipality_version,
                     period_start=MARCH_START, period_end=APRIL_START):
    payload = {"municipality_id": municipality_id, "period_start": period_start,
               "period_end": period_end,
               "expected_municipality_version": expected_municipality_version}
    return get_success_data(api.create_municipal_statement(payload, CLERK))


def finalize_statement(api, statement_id):
    return get_success_data(api.finalize_municipal_statement(statement_id, CLERK))


def get_municipality(api, municipality_id):
    return get_success_data(api.get_municipality(municipality_id, CLERK))


# --- Tier 1/2: audited + closed loads ---------------------------------------

def setup_received_load(api, revenue_share_pct=0.50, gross_tons=22, tare_tons=2):
    """Municipality + SortLine + a RECEIVED InboundLoad. Returns a context dict."""
    muni = create_municipality(api, revenue_share_pct=revenue_share_pct)
    line = create_sort_line(api)
    load = create_load(api, muni["id"], line["id"], gross_tons, tare_tons)
    return {"municipality": muni, "sort_line": line, "load": load,
            "m_id": muni["id"], "sl_id": line["id"], "load_id": load["id"]}


def setup_audited_load(api, revenue_share_pct=0.50, gross_tons=22, tare_tons=2,
                       sampled_contamination_pct=3.0, audited_composition=None):
    """Municipality + SortLine + an AUDITED InboundLoad."""
    ctx = setup_received_load(api, revenue_share_pct, gross_tons, tare_tons)
    ctx["load"] = audit_load(api, ctx["load_id"], sampled_contamination_pct,
                             audited_composition)
    return ctx


# --- Tier 3: closed load with a single bale, index published ----------------

def setup_closed_load_with_bale(api, clock=DEFAULT_TEST_CLOCK,
                                index_price_cents_per_ton=8000,
                                revenue_share_pct=0.50,
                                gross_tons=12, tare_tons=2,
                                bale_net_tons=10, moisture_pct=0, quality_grade="A",
                                residual_tons=0,
                                index_start=MARCH_START, index_end=APRIL_START):
    """Clock set; PUBLISHED OCC index; audited load; one OCC bale; load CLOSED.

    Returns a context dict with municipality, index, sort_line, load, bale.
    """
    set_clock(api, clock)
    muni = create_municipality(api, revenue_share_pct=revenue_share_pct)
    idx = create_and_publish_index(api, "OCC", index_price_cents_per_ton,
                                   index_start, index_end)
    line = create_sort_line(api)
    load = create_load(api, muni["id"], line["id"], gross_tons, tare_tons)
    audit_load(api, load["id"])
    bale = create_bale(api, load["id"], "OCC", bale_net_tons, moisture_pct, quality_grade)
    load = close_load(api, load["id"], residual_tons)
    return {"municipality": muni, "index": idx, "sort_line": line, "load": load,
            "bale": bale, "m_id": muni["id"], "sl_id": line["id"],
            "load_id": load["id"], "bale_id": bale["id"], "idx_id": idx["id"]}


# --- Tier 3: single-bale shipment at various lifecycle stages ----------------

def setup_shipped_single_bale(api, clock=DEFAULT_TEST_CLOCK,
                              index_price_cents_per_ton=8000,
                              revenue_share_pct=0.50,
                              bale_net_tons=10, moisture_pct=0, quality_grade="A",
                              freight_cost_cents=0,
                              index_start=MARCH_START, index_end=APRIL_START):
    """Full flow up to a SHIPPED single-bale OCC shipment (bale is SHIPPED)."""
    ctx = setup_closed_load_with_bale(
        api, clock, index_price_cents_per_ton, revenue_share_pct,
        bale_net_tons=bale_net_tons, moisture_pct=moisture_pct,
        quality_grade=quality_grade, index_start=index_start, index_end=index_end)
    mill = create_mill(api, "OCC")
    ship = create_shipment(api, mill["id"], "OCC", freight_cost_cents)
    assign_bale(api, ship["id"], ctx["bale_id"])
    ship = ship_shipment(api, ship["id"])
    ctx["mill"] = mill
    ctx["shipment"] = ship
    ctx["ship_id"] = ship["id"]
    ctx["mill_id"] = mill["id"]
    return ctx


def setup_settled_single_bale(api, clock=DEFAULT_TEST_CLOCK,
                              index_price_cents_per_ton=8000,
                              revenue_share_pct=0.50,
                              bale_net_tons=10, moisture_pct=0, quality_grade="A",
                              freight_cost_cents=0):
    """Full flow through a SETTLED single-bale OCC shipment."""
    ctx = setup_shipped_single_bale(
        api, clock, index_price_cents_per_ton, revenue_share_pct,
        bale_net_tons, moisture_pct, quality_grade, freight_cost_cents)
    ctx["shipment"] = settle_shipment(api, ctx["ship_id"])
    return ctx


# --- Municipal statement setup ----------------------------------------------

def setup_two_window_shipped_bale(api, revenue_share_pct=0.60,
                                  freight_cost_cents=5000):
    """Two adjacent OCC index windows (8000 for [03-01,03-15), 9000 for
    [03-16,04-01)), both PUBLISHED. Clock 03-10 at baling: a single net-10,
    moisture-5, grade-A bale off a closed load is staged onto a shipment with the
    given freight and shipped; the clock is then advanced to 03-20 so the
    settle-time index (9000) differs from the snapshot (8000).

    Returns a context dict; the shipment is SHIPPED and ready to settle.
    """
    set_clock(api, "2026-03-10T00:00:00Z")
    muni = create_municipality(api, revenue_share_pct=revenue_share_pct)
    mill = create_mill(api, "OCC", freight_rate_cents_per_ton=1000)
    idx1 = create_and_publish_index(api, "OCC", 8000,
                                    "2026-03-01T00:00:00Z", "2026-03-15T00:00:00Z")
    idx2 = create_and_publish_index(api, "OCC", 9000,
                                    "2026-03-16T00:00:00Z", "2026-04-01T00:00:00Z")
    line = create_sort_line(api)
    load = create_load(api, muni["id"], line["id"], gross_tons=22, tare_tons=2)
    audit_load(api, load["id"], 4.0, [{"commodity": "OCC", "pct": 98}])
    bale = create_bale(api, load["id"], "OCC", net_tons=10, moisture_pct=5,
                       quality_grade="A")
    close_load(api, load["id"], residual_tons=2.0)
    ship = create_shipment(api, mill["id"], "OCC", freight_cost_cents)
    assign_bale(api, ship["id"], bale["id"])
    ship = ship_shipment(api, ship["id"])
    set_clock(api, "2026-03-20T00:00:00Z")
    return {"municipality": muni, "mill": mill, "sort_line": line, "load": load,
            "bale": bale, "shipment": ship, "m_id": muni["id"],
            "mill_id": mill["id"], "load_id": load["id"], "bale_id": bale["id"],
            "ship_id": ship["id"]}


def setup_municipality_with_statement(api, revenue_share_pct=0.50):
    """Create a municipality and one OPEN statement using its version-1.
    Returns (municipality_dict, statement_dict)."""
    muni = create_municipality(api, revenue_share_pct=revenue_share_pct)
    stmt = create_statement(api, muni["id"], muni["version"])
    return muni, stmt
