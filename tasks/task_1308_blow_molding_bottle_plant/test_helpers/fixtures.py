"""Composite setup helpers for multi-step test prerequisites.

Every fixture builds its preconditions from scratch against a freshly restarted
server, using only PRD-declared endpoints. Setup calls use the lenient
get_success_data() so failures surface as clear "Setup step failed" errors.

Layering:
  Tier 1  - single-entity creation (customer, line, mold, lot, rate card)
  Tier 2  - spec qualification loop (DRAFT -> QUALIFIED)
  Tier 3  - order lifecycle shortcuts (schedule, release, run, close)
  Tier 4  - quality lot shortcuts (sample, record, disposition)
  Tier 5  - full scenarios (released / running / closed / accepted / shipping)
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload, create_freight_rate_card_payload,
    create_machine_line_payload, create_mold_payload, create_bottle_spec_payload,
    create_qualification_run_payload, execute_qualification_run_payload,
    review_qualification_run_payload, create_cavity_blockout_payload,
    create_material_lot_payload, create_production_order_payload,
    schedule_order_payload, create_production_run_payload,
    close_production_run_payload, record_results_payload,
    create_shipment_payload, create_dock_appointment_payload,
)
from .constants import (
    SLOT_START, SLOT_END, RUN_CLOCK,
    DOCK_WINDOW_START, DOCK_WINDOW_END,
    MAIN_TIERS,
)
from .test_users import TEST_USERS, make_customer_quality_rep_headers, \
    make_quality_technician_headers

ADMIN = TEST_USERS["plant_admin"]
ENGINEER = TEST_USERS["process_engineer"]
TECH = TEST_USERS["quality_technician"]
SCHEDULER = TEST_USERS["production_scheduler"]
LOGISTICS = TEST_USERS["logistics_coordinator"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_customer(**overrides):
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), ADMIN))


def create_rate_card(tiers=None, lane_code="MAIN"):
    payload = create_freight_rate_card_payload(
        lane_code=lane_code, tiers=tiers if tiers is not None else list(MAIN_TIERS))
    return get_success_data(api_client.create_freight_rate_card(payload, ADMIN))


def create_line(**overrides):
    return get_success_data(
        api_client.create_machine_line(create_machine_line_payload(**overrides), ADMIN))


def create_mold(**overrides):
    return get_success_data(
        api_client.create_mold(create_mold_payload(**overrides), ADMIN))


def create_spec(customer_id, **overrides):
    return get_success_data(api_client.create_bottle_spec(
        create_bottle_spec_payload(customer_id, **overrides), ENGINEER))


def create_lot(release=False, **overrides):
    lot = get_success_data(
        api_client.create_material_lot(create_material_lot_payload(**overrides), ADMIN))
    if release:
        lot = get_success_data(api_client.release_material_lot(lot["id"], TECH))
    return lot


def install_mold(mold_id, line_id):
    """Install a mold; returns the updated mold (carrying its new version)."""
    return get_success_data(
        api_client.install_mold(mold_id, {"machine_line_id": line_id}, ENGINEER))


def open_blockout(mold_id, cavity_index, reason="DAMAGE", expected_mold_version=None):
    """Open a blockout, reading the current mold version when not supplied."""
    if expected_mold_version is None:
        expected_mold_version = get_success_data(
            api_client.get_mold(mold_id, ENGINEER))["version"]
    return get_success_data(api_client.create_cavity_blockout(
        mold_id,
        create_cavity_blockout_payload(cavity_index, reason, expected_mold_version),
        ENGINEER))


def set_clock(to_iso8601=RUN_CLOCK):
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: spec qualification loop
# ---------------------------------------------------------------------------

def submit_spec(spec_id):
    return get_success_data(api_client.submit_bottle_spec(spec_id, ENGINEER))


def begin_qualification(spec_id):
    """SUBMITTED -> IN_QUALIFICATION; returns the spec (note its version)."""
    return get_success_data(api_client.begin_qualification(spec_id, ENGINEER))


def create_qualification_run(spec_id, expected_bottle_spec_version,
                             sample_cavity_count=8):
    return get_success_data(api_client.create_qualification_run(
        create_qualification_run_payload(
            spec_id, expected_bottle_spec_version, sample_cavity_count),
        ENGINEER))


def execute_run(run_id, measured_mean_weight_g=22.1, weight_spread_g=0.4,
                visual_defects=0):
    return get_success_data(api_client.execute_qualification_run(
        run_id,
        execute_qualification_run_payload(
            measured_mean_weight_g=measured_mean_weight_g,
            weight_spread_g=weight_spread_g,
            visual_defects=visual_defects),
        ENGINEER))


def submit_review(run_id):
    return get_success_data(api_client.submit_qualification_review(run_id, TECH))


def review_run(run_id, decision, customer_id, review_note=None):
    payload = review_qualification_run_payload(decision)
    if review_note is not None:
        payload["review_note"] = review_note
    return get_success_data(api_client.review_qualification_run(
        run_id, payload, make_customer_quality_rep_headers(customer_id)))


def qualify_spec(spec_id, measured_mean_weight_g=22.1):
    """Walk a spec from DRAFT/SUBMITTED to QUALIFIED via one approved run.

    Requires the spec to be in DRAFT (submits) and its customer to exist.
    Returns the spec in QUALIFIED.
    """
    spec = get_success_data(api_client.get_bottle_spec(spec_id, ENGINEER))
    if spec["status"] == "DRAFT":
        submit_spec(spec_id)
    begin = begin_qualification(spec_id)
    qrun = create_qualification_run(spec_id, begin["version"])
    execute_run(qrun["id"], measured_mean_weight_g=measured_mean_weight_g)
    submit_review(qrun["id"])
    review_run(qrun["id"], "APPROVE", spec["customer_id"])
    return get_success_data(api_client.get_bottle_spec(spec_id, ENGINEER))


def setup_qualified_spec(customer=None, customer_overrides=None, **spec_overrides):
    """Customer + one QUALIFIED spec. Returns (customer, spec)."""
    if customer is None:
        customer = create_customer(**(customer_overrides or {}))
    spec = create_spec(customer["id"], **spec_overrides)
    spec = qualify_spec(spec["id"])
    return customer, spec


# ---------------------------------------------------------------------------
# Tier 3: order lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_draft_order(spec_id, **overrides):
    return get_success_data(api_client.create_production_order(
        create_production_order_payload(spec_id, **overrides), SCHEDULER))


def schedule_order(order, line_id, planned_start=SLOT_START, planned_end=SLOT_END,
                   expected_version=None):
    """Schedule (or re-slot) an order. `order` may be a dict (version read from
    it unless expected_version given) or a bare id (version re-read first)."""
    if isinstance(order, dict):
        order_id = order["id"]
        if expected_version is None:
            expected_version = order["version"]
    else:
        order_id = order
        if expected_version is None:
            expected_version = get_success_data(
                api_client.get_production_order(order_id, SCHEDULER))["version"]
    return get_success_data(api_client.schedule_production_order(
        order_id,
        schedule_order_payload(line_id, planned_start, planned_end, expected_version),
        SCHEDULER))


def release_order(order_id):
    return get_success_data(api_client.release_production_order(order_id, SCHEDULER))


def get_order(order_id):
    return get_success_data(api_client.get_production_order(order_id, SCHEDULER))


def get_order_summary(order_id):
    return get_success_data(
        api_client.get_production_order_summary(order_id, LOGISTICS))


def list_order_slots(order_id):
    return get_success_data(
        api_client.list_order_schedule_slots(order_id, SCHEDULER))


# ---------------------------------------------------------------------------
# Tier 4: production run + quality lot shortcuts
# ---------------------------------------------------------------------------

def start_run(order_id, line_id, mold_id, lot_id, colorant_lot_id=None):
    payload = create_production_run_payload(order_id, line_id, mold_id, lot_id)
    if colorant_lot_id is not None:
        payload["colorant_lot_id"] = colorant_lot_id
    return get_success_data(api_client.create_production_run(payload, ENGINEER))


def close_run(run_id, cycles_completed=2000, good_count=11880, scrap_count=120,
              actual_drawdown_kg=360.0):
    return get_success_data(api_client.close_production_run(
        run_id,
        close_production_run_payload(
            cycles_completed=cycles_completed, good_count=good_count,
            scrap_count=scrap_count, actual_drawdown_kg=actual_drawdown_kg),
        ENGINEER))


def get_qtl_id_for_run(run_id):
    lots = get_success_data(
        api_client.list_quality_test_lots(TECH, params={"production_run_id": run_id}))
    assert isinstance(lots, list) and len(lots) == 1, (
        f"expected exactly one quality lot for run {run_id}, got {lots}")
    return lots[0]["id"]


def sample_lot(qtl_id, user_id="qt-1"):
    return get_success_data(api_client.sample_quality_test_lot(
        qtl_id, make_quality_technician_headers(user_id)))


def record_results(qtl_id, leak_failures, drop_failures, user_id="qt-1"):
    return get_success_data(api_client.record_quality_test_results(
        qtl_id, record_results_payload(leak_failures, drop_failures),
        make_quality_technician_headers(user_id)))


def disposition_lot(qtl_id, action, user_id="qt-2"):
    return get_success_data(api_client.disposition_quality_test_lot(
        qtl_id, {"action": action}, make_quality_technician_headers(user_id)))


# ---------------------------------------------------------------------------
# Tier 5: full scenario builders
# ---------------------------------------------------------------------------

def setup_qualified_plant(customer_overrides=None, line_overrides=None,
                          mold_overrides=None, spec_overrides=None,
                          with_rate_card=False, with_mold=True):
    """Customer + line + mold + QUALIFIED spec (+ optional rate card).

    Returns a dict context: customer, line, mold, spec, rate_card.
    """
    ctx = {}
    ctx["customer"] = create_customer(**(customer_overrides or {}))
    ctx["line"] = create_line(**(line_overrides or {}))
    ctx["mold"] = create_mold(**(mold_overrides or {})) if with_mold else None
    spec = create_spec(ctx["customer"]["id"], **(spec_overrides or {}))
    ctx["spec"] = qualify_spec(spec["id"])
    ctx["rate_card"] = create_rate_card() if with_rate_card else None
    return ctx


def setup_scheduled_order(ctx, order_overrides=None, planned_start=SLOT_START,
                          planned_end=SLOT_END):
    """Adds a DRAFT order scheduled onto ctx's line. Returns the order."""
    order = create_draft_order(ctx["spec"]["id"], **(order_overrides or {}))
    return schedule_order(order, ctx["line"]["id"], planned_start, planned_end)


def setup_released_scenario(customer_overrides=None, line_overrides=None,
                            mold_overrides=None, spec_overrides=None,
                            order_overrides=None, lot_overrides=None,
                            release_lot=True, install=True, blockouts=None,
                            planned_start=SLOT_START, planned_end=SLOT_END,
                            clock=RUN_CLOCK, with_rate_card=False):
    """Full chain: qualified spec + scheduled order + lot + installed mold +
    released order + clock inside the slot window. Does NOT start a run."""
    ctx = setup_qualified_plant(
        customer_overrides=customer_overrides, line_overrides=line_overrides,
        mold_overrides=mold_overrides, spec_overrides=spec_overrides,
        with_rate_card=with_rate_card)
    ctx["order"] = setup_scheduled_order(
        ctx, order_overrides=order_overrides,
        planned_start=planned_start, planned_end=planned_end)
    ctx["lot"] = create_lot(release=release_lot, **(lot_overrides or {}))
    if install:
        ctx["mold"] = install_mold(ctx["mold"]["id"], ctx["line"]["id"])
    for cavity_index, reason in (blockouts or []):
        open_blockout(ctx["mold"]["id"], cavity_index, reason)
    ctx["order"] = release_order(ctx["order"]["id"])
    set_clock(clock)
    return ctx


def setup_running_scenario(colorant_lot=False, **kwargs):
    """Released scenario + one OPEN production run (order RUNNING)."""
    ctx = setup_released_scenario(**kwargs)
    colorant_lot_id = None
    if colorant_lot:
        clot = create_lot(release=True, material_type="COLORANT",
                          color_code="BLK", lot_code="C-BLK", received_kg=50)
        ctx["colorant_lot"] = clot
        colorant_lot_id = clot["id"]
    ctx["run"] = start_run(ctx["order"]["id"], ctx["line"]["id"],
                           ctx["mold"]["id"], ctx["lot"]["id"],
                           colorant_lot_id=colorant_lot_id)
    return ctx


def setup_closed_run_scenario(close_overrides=None, **kwargs):
    """Running scenario + the run CLOSED + its auto-created quality lot id."""
    ctx = setup_running_scenario(**kwargs)
    ctx["run"] = close_run(ctx["run"]["id"], **(close_overrides or {}))
    ctx["qtl_id"] = get_qtl_id_for_run(ctx["run"]["id"])
    return ctx


def setup_accepted_stock_scenario(leak_failures=5, drop_failures=6,
                                  recorder="qt-1", **kwargs):
    """Closed run whose quality lot is SAMPLED then ACCEPTED (default counts
    accept a band-4 lot of 11880: c_leak 5, c_drop 6). Order gains accepted
    stock equal to the run's good_count (11880 by default)."""
    ctx = setup_closed_run_scenario(**kwargs)
    sample_lot(ctx["qtl_id"], user_id=recorder)
    ctx["qtl"] = record_results(ctx["qtl_id"], leak_failures, drop_failures,
                                user_id=recorder)
    assert ctx["qtl"]["status"] == "ACCEPTED", (
        f"accepted-stock scenario requires an ACCEPTED lot, got "
        f"{ctx['qtl']['status']}")
    return ctx


# --- shipping helpers --------------------------------------------------------

def create_shipment(order_id, quantity, shipment_mode="FINISHED_BOTTLES"):
    return get_success_data(api_client.create_shipment(
        create_shipment_payload(order_id, quantity, shipment_mode), LOGISTICS))


def create_appointment(shipment_id, dock_door=1,
                       window_start=DOCK_WINDOW_START, window_end=DOCK_WINDOW_END):
    return get_success_data(api_client.create_dock_appointment(
        create_dock_appointment_payload(shipment_id, dock_door, window_start,
                                        window_end),
        LOGISTICS))


def book_shipment(shipment_id, appointment_id):
    return get_success_data(api_client.book_shipment(
        shipment_id, {"dock_appointment_id": appointment_id}, LOGISTICS))


def setup_shipment_with_appointment(quantity=1000, appointment_kwargs=None,
                                    **scenario_kwargs):
    """Accepted-stock scenario + one QUOTED shipment + one RESERVED dock
    appointment for it. Requires the ACTIVE rate card (created by default)."""
    scenario_kwargs.setdefault("with_rate_card", True)
    ctx = setup_accepted_stock_scenario(**scenario_kwargs)
    ctx["shipment"] = create_shipment(ctx["order"]["id"], quantity)
    ctx["appointment"] = create_appointment(ctx["shipment"]["id"],
                                            **(appointment_kwargs or {}))
    return ctx


def setup_booked_shipment(quantity=1000, appointment_kwargs=None,
                          **scenario_kwargs):
    """Quoted shipment + RESERVED appointment, then booked."""
    ctx = setup_shipment_with_appointment(
        quantity=quantity, appointment_kwargs=appointment_kwargs, **scenario_kwargs)
    ctx["shipment"] = book_shipment(ctx["shipment"]["id"], ctx["appointment"]["id"])
    return ctx
