"""Composite setup helpers for the Greenhouse Nursery Grower API.

Each helper builds the multi-step precondition state a test needs, using only
PRD-declared endpoints, and returns the live entity dicts. Setup calls go through
get_success_data() (lenient 2xx validator) so a broken precondition surfaces as a
clear "Setup step failed" message rather than a confusing assertion later.

The harness restarts the server (empty DB, clock reset to 2026-01-01T00:00:00Z)
before every test, so every helper rebuilds its world from scratch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_broker_headers
from .factories import (
    create_variety_payload, create_zone_payload, create_batch_payload,
    create_input_log_payload, create_broker_payload, create_availability_payload,
    create_order_payload, create_order_line_payload, create_phyto_payload,
)

# Opaque-role header shortcuts (safe to share; these roles are not entity-backed).
GM = TEST_USERS["grower_manager_headers"]
PT = TEST_USERS["production_tech_headers"]
SC = TEST_USERS["sales_coordinator_headers"]

# Conventional clocks used across the saleable-batch chains.
STICK_CLOCK = "2026-02-01T00:00:00Z"
GRADE_CLOCK = "2026-02-07T00:00:00Z"


# ─── Primitive step helpers ───────────────────────────
def set_clock(api, iso):
    """Advance the logical clock (GrowerManager-only)."""
    resp = api.set_clock({"to_iso8601": iso}, GM)
    assert 200 <= resp.status_code < 300, f"Setup set_clock failed: {resp.text}"
    return resp


def create_active_variety(api, *, cultivar_code="TESTVAR1", common_name="Test Variety",
                          propagation_form="LINER", grow_cycle_days=5,
                          container_footprint_units=1, ship_ready_grade_min_height_cm=8,
                          ship_ready_min_live_pct=0.5, requires_phyto=False):
    payload = create_variety_payload(
        common_name=common_name, cultivar_code=cultivar_code,
        propagation_form=propagation_form, grow_cycle_days=grow_cycle_days,
        container_footprint_units=container_footprint_units,
        ship_ready_grade_min_height_cm=ship_ready_grade_min_height_cm,
        ship_ready_min_live_pct=ship_ready_min_live_pct, requires_phyto=requires_phyto,
    )
    created = get_success_data(api.create_variety(payload, GM))
    get_success_data(api.activate_variety(created["id"], GM))
    return get_success_data(api.get_variety(created["id"], GM))


def create_zone(api, *, name="Test Zone", climate_class="MIXED", capacity_units=3000):
    payload = create_zone_payload(name=name, climate_class=climate_class,
                                  capacity_units=capacity_units)
    return get_success_data(api.create_zone(payload, GM))


def create_planned_batch(api, variety_id, zone_id, *, sourced_count=100,
                         source_supplier="PlugCo", headers=None):
    payload = create_batch_payload(variety_id=variety_id, zone_id=zone_id,
                                   source_supplier=source_supplier, sourced_count=sourced_count)
    return get_success_data(api.create_batch(payload, headers or PT))


def zone_version(api, zone_id):
    return get_success_data(api.get_zone(zone_id, PT))["version"]


def transplant(api, batch_id, zone_id, started_count):
    payload = {"started_count": started_count, "expected_zone_version": zone_version(api, zone_id)}
    return get_success_data(api.transplant_batch(batch_id, payload, PT))


def record_input_log(api, batch_id, event_type, **fields):
    payload = create_input_log_payload(event_type, **fields)
    return get_success_data(api.create_input_log(batch_id, payload, PT))


def record_grade(api, batch_id, mean_height_cm, dead_observed=0):
    return record_input_log(api, batch_id, "GRADE",
                            mean_height_cm=mean_height_cm, dead_observed=dead_observed)


def grade_to_saleable(api, batch_id):
    get_success_data(api.start_grading(batch_id, PT))
    return get_success_data(api.finalize_grade(batch_id, PT))


def publish_availability(api, batch_id, unit_price_cents):
    payload = create_availability_payload(batch_id=batch_id, unit_price_cents=unit_price_cents)
    return get_success_data(api.create_availability(payload, SC))


def create_broker(api, *, ship_to_state="OR", credit_limit_cents=5_000_000,
                  company_name="Test Broker", contact_email="broker@example.com"):
    payload = create_broker_payload(company_name=company_name, contact_email=contact_email,
                                    ship_to_state=ship_to_state, credit_limit_cents=credit_limit_cents)
    return get_success_data(api.create_broker(payload, SC))


def issue_phyto(api, broker_id, *, certificate_number="PC-1", origin_state="OR",
                valid_until="2026-12-31T00:00:00Z"):
    payload = create_phyto_payload(broker_id=broker_id, certificate_number=certificate_number,
                                   origin_state=origin_state, valid_until=valid_until)
    return get_success_data(api.create_phyto_certificate(payload, SC))


def create_draft_order(api, broker_id, *, requested_ship_date="2026-03-01T00:00:00Z", headers=None):
    payload = create_order_payload(broker_id=broker_id, requested_ship_date=requested_ship_date)
    return get_success_data(api.create_order(payload, headers or SC))


def add_line(api, order_id, entry_id, quantity, *, headers=None):
    payload = create_order_line_payload(availability_entry_id=entry_id, quantity=quantity)
    return get_success_data(api.add_order_line(order_id, payload, headers or SC))


def confirm_order(api, order_id):
    ov = get_success_data(api.get_order(order_id, SC))["version"]
    return get_success_data(api.confirm_order(order_id, {"expected_order_version": ov}, SC))


def create_shipment(api, order_id, lines, *, phyto_certificate_id=None):
    payload = {"order_id": order_id, "lines": lines}
    if phyto_certificate_id is not None:
        payload["phyto_certificate_id"] = phyto_certificate_id
    return get_success_data(api.create_shipment(payload, SC))


# ─── Tier 1/2: batch state-progression composites ─────
def setup_growing_batch(api, *, footprint=1, sourced=100, started=None, capacity=3000,
                        climate="MIXED", propagation_form="PLUG", grow_cycle_days=20,
                        min_live_pct=0.5, height_min=8, cultivar_code="GRW001",
                        stick_clock=STICK_CLOCK):
    """Active variety + open zone + one transplanted (GROWING) batch.

    Returns {"variety", "zone", "batch"}. The batch is GROWING with
    live_count == started_count; no grade events recorded yet.
    """
    if started is None:
        started = sourced
    set_clock(api, stick_clock)
    variety = create_active_variety(
        api, cultivar_code=cultivar_code, propagation_form=propagation_form,
        grow_cycle_days=grow_cycle_days, container_footprint_units=footprint,
        ship_ready_grade_min_height_cm=height_min, ship_ready_min_live_pct=min_live_pct,
    )
    zone = create_zone(api, climate_class=climate, capacity_units=capacity)
    batch = create_planned_batch(api, variety["id"], zone["id"], sourced_count=sourced)
    batch = transplant(api, batch["id"], zone["id"], started)
    return {"variety": variety, "zone": zone, "batch": batch}


def setup_batch_ready_to_grade(api, *, footprint=1, sourced=100, started=None, capacity=3000,
                               grow_cycle_days=5, min_live_pct=0.5, height_min=8,
                               grade_height=10, cultivar_code="RTG001",
                               stick_clock=STICK_CLOCK, grade_clock=GRADE_CLOCK):
    """GROWING batch with the clock past target_ship_date and one GRADE measurement
    recorded, i.e. ready for start-grading. Returns {"variety", "zone", "batch"}."""
    if started is None:
        started = sourced
    base = setup_growing_batch(
        api, footprint=footprint, sourced=sourced, started=started, capacity=capacity,
        propagation_form="LINER", grow_cycle_days=grow_cycle_days, min_live_pct=min_live_pct,
        height_min=height_min, cultivar_code=cultivar_code, stick_clock=stick_clock,
    )
    set_clock(api, grade_clock)
    record_grade(api, base["batch"]["id"], grade_height)
    base["batch"] = get_success_data(api.get_batch(base["batch"]["id"], PT))
    return base


def setup_saleable_batch(api, *, footprint=1, sourced=100, started=None, capacity=3000,
                         grow_cycle_days=5, min_live_pct=0.5, height_min=8, grade_height=10,
                         requires_phyto=False, cultivar_code="SAL001",
                         stick_clock=STICK_CLOCK, grade_clock=GRADE_CLOCK):
    """Full chain PLANNED -> GROWING -> GRADING -> SALEABLE. Returns
    {"variety", "zone", "batch"} with the batch in SALEABLE."""
    if started is None:
        started = sourced
    set_clock(api, stick_clock)
    variety = create_active_variety(
        api, cultivar_code=cultivar_code, propagation_form="LINER",
        grow_cycle_days=grow_cycle_days, container_footprint_units=footprint,
        ship_ready_grade_min_height_cm=height_min, ship_ready_min_live_pct=min_live_pct,
        requires_phyto=requires_phyto,
    )
    zone = create_zone(api, capacity_units=capacity)
    batch = create_planned_batch(api, variety["id"], zone["id"], sourced_count=sourced)
    transplant(api, batch["id"], zone["id"], started)
    set_clock(api, grade_clock)
    record_grade(api, batch["id"], grade_height)
    batch = grade_to_saleable(api, batch["id"])
    return {"variety": variety, "zone": zone, "batch": batch}


def setup_published_lot(api, *, unit_price_cents=300, **kwargs):
    """SALEABLE batch published to an OPEN availability entry.
    Returns {"variety", "zone", "batch", "entry"}."""
    base = setup_saleable_batch(api, **kwargs)
    entry = publish_availability(api, base["batch"]["id"], unit_price_cents)
    base["entry"] = entry
    return base


# ─── Tier 3: order / multi-line composites ────────────
def setup_multi_line_order(api=None, *, line_specs, ship_to_state="OR", credit_limit_cents=5_000_000,
                           footprint=1, capacity=20000, grow_cycle_days=5, min_live_pct=0.5,
                           height_min=8, grade_height=10, cultivar_code="MLO001", confirm=False):
    """Build one variety + zone, one SALEABLE published lot per line spec, a broker,
    and a DRAFT (or CONFIRMED) order with one line per spec.

    line_specs: list of {"quantity": int, "unit_price_cents": int, "started": int?}.
    Returns {"variety", "zone", "batches", "entries", "broker", "order", "lines"}.

    The test suite invokes this helper against the ambient session ApiClient
    (the same module-level singleton the `api` fixture returns), so `api`
    defaults to that singleton when not supplied positionally.
    """
    if api is None:
        api = api_client
    set_clock(api, STICK_CLOCK)
    variety = create_active_variety(
        api, cultivar_code=cultivar_code, propagation_form="LINER",
        grow_cycle_days=grow_cycle_days, container_footprint_units=footprint,
        ship_ready_grade_min_height_cm=height_min, ship_ready_min_live_pct=min_live_pct,
    )
    zone = create_zone(api, capacity_units=capacity)
    batches = []
    for spec in line_specs:
        started = spec.get("started", spec["quantity"])
        b = create_planned_batch(api, variety["id"], zone["id"], sourced_count=started)
        transplant(api, b["id"], zone["id"], started)
        batches.append(b)
    set_clock(api, GRADE_CLOCK)
    entries = []
    for b, spec in zip(batches, line_specs):
        record_grade(api, b["id"], grade_height)
        b_final = grade_to_saleable(api, b["id"])
        b.update(b_final)
        entries.append(publish_availability(api, b["id"], spec["unit_price_cents"]))
    broker = create_broker(api, ship_to_state=ship_to_state, credit_limit_cents=credit_limit_cents)
    order = create_draft_order(api, broker["id"])
    lines = []
    for e, spec in zip(entries, line_specs):
        lines.append(add_line(api, order["id"], e["id"], spec["quantity"]))
    result = {"variety": variety, "zone": zone, "batches": batches, "entries": entries,
              "broker": broker, "order": order, "lines": lines}
    if confirm:
        result["order"] = confirm_order(api, order["id"])
    return result


def setup_confirmed_single_line(api, *, quantity, unit_price_cents=300, started=None,
                                ship_to_state="OR", credit_limit_cents=5_000_000,
                                footprint=1, capacity=20000, requires_phyto=False,
                                grade_height=10, min_live_pct=0.5, height_min=8,
                                cultivar_code="CSL001"):
    """A CONFIRMED order with a single committed line drawing on one SALEABLE lot.

    Handles requires_phyto varieties (which setup_multi_line_order does not).
    Returns {"variety", "zone", "batch", "entry", "broker", "order", "line"}.
    """
    if started is None:
        started = quantity
    lot = setup_published_lot(
        api, unit_price_cents=unit_price_cents, footprint=footprint, sourced=started,
        started=started, capacity=capacity, requires_phyto=requires_phyto,
        grade_height=grade_height, min_live_pct=min_live_pct, height_min=height_min,
        cultivar_code=cultivar_code,
    )
    broker = create_broker(api, ship_to_state=ship_to_state, credit_limit_cents=credit_limit_cents)
    order = create_draft_order(api, broker["id"])
    line = add_line(api, order["id"], lot["entry"]["id"], quantity)
    confirmed = confirm_order(api, order["id"])
    return {"variety": lot["variety"], "zone": lot["zone"], "batch": lot["batch"],
            "entry": lot["entry"], "broker": broker, "order": confirmed, "line": line}


# ─── Broker-owned order (entity-backed identity threading) ────
def setup_broker_owned_draft_order(api, *, quantity=10, unit_price_cents=300, ship_to_state="OR"):
    """A DRAFT order created and lined by the entity-backed Broker acting as itself.

    Returns {"broker", "order", "line", "entry", "batch"}. The broker's own headers
    (make_broker_headers(broker_id)) are used for all ownership-gated calls.
    """
    lot = setup_published_lot(api, unit_price_cents=unit_price_cents, sourced=max(quantity, 30),
                              started=max(quantity, 30), cultivar_code="BOD001")
    broker = create_broker(api, ship_to_state=ship_to_state)
    bh = make_broker_headers(broker["id"])
    order = create_draft_order(api, broker["id"], headers=bh)
    line = add_line(api, order["id"], lot["entry"]["id"], quantity, headers=bh)
    return {"broker": broker, "order": order, "line": line, "entry": lot["entry"], "batch": lot["batch"]}
