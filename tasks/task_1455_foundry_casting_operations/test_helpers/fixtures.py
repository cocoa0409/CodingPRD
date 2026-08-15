"""Composite setup helpers for multi-step test prerequisites.

All helpers use get_success_data() so setup failures surface as clear
"Setup step failed" errors. Every helper builds its preconditions from
scratch against PRD-declared endpoints (per-test server restarts mean the
database starts empty).
"""
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_AFTER_COOLING,
    CLOCK_MORNING,
    CLOCK_POUR,
    MA_CAP_MM,
    SHRINK,
    SIMPLE_READING,
    SIMPLE_SPEC,
    SLOT_END,
    SLOT_START,
    TEST_DEFAULTS,
)
from .factories import (
    create_claim_payload,
    create_customer_payload,
    create_foundry_payload,
    create_furnace_payload,
    create_heat_payload,
    create_inspection_payload,
    create_mold_payload,
    create_molding_line_payload,
    create_order_payload,
    create_pattern_payload,
    create_pour_slot_payload,
    create_return_lot_payload,
    create_sand_batch_payload,
    virgin_addition,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["foundry_admin_headers"]
PM = TEST_USERS["pattern_maker_headers"]
MELT = TEST_USERS["melt_supervisor_headers"]
LINE = TEST_USERS["line_operator_headers"]
QI = TEST_USERS["qi_1_headers"]
SPECTRO_1 = TEST_USERS["spectro_1_headers"]
WM_1 = TEST_USERS["wm_1_headers"]


def round_half_up(value, digits: int) -> float:
    """Round half-up per PRD §2.7 (binary floats never banker's-round)."""
    q = Decimal(1).scaleb(-digits)
    return float(Decimal(repr(float(value))).quantize(q, rounding=ROUND_HALF_UP))


def compute_pattern_dimensions(finish_dimensions_mm, machining_allowance_mm,
                               alloy_shrink_class="FERROUS", mold_process="SAND"):
    """PRD §3.2: per axis, (finish + min(ma, cap[process])) * (1 + shrink),
    rounded half-up to one decimal place per axis."""
    cap = MA_CAP_MM[mold_process]
    shrink = SHRINK[(alloy_shrink_class, mold_process)]
    eff = min(float(machining_allowance_mm), cap)
    return [round_half_up((float(d) + eff) * (1.0 + shrink), 1) for d in finish_dimensions_mm]


# ─── Primitive steps ──────────────────────────────────

def set_clock(to_iso: str):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso}, ADMIN))


def create_foundry(name: str = "F1") -> dict:
    return get_success_data(api_client.create_foundry(create_foundry_payload(name=name), ADMIN))


def get_foundry(foundry_id: str) -> dict:
    return get_success_data(api_client.get_foundry(foundry_id, ADMIN))


def run_ops(foundry_id: str) -> dict:
    """Advance the ops epoch, threading expected_foundry_version (PRD §2.6)."""
    current = get_foundry(foundry_id)
    return get_success_data(api_client.run_ops(
        foundry_id, {"expected_foundry_version": current["version"]}, ADMIN))


def create_customer(foundry_id: str, company_name: str = "Acme") -> dict:
    return get_success_data(api_client.create_customer(
        create_customer_payload(foundry_id, company_name=company_name), ADMIN))


def create_furnace(foundry_id: str, daily_tap_capacity_kg=None) -> dict:
    payload = create_furnace_payload(foundry_id)
    if daily_tap_capacity_kg is not None:
        payload["daily_tap_capacity_kg"] = daily_tap_capacity_kg
    return get_success_data(api_client.create_equipment(payload, ADMIN))


def create_molding_line(foundry_id: str, daily_minute_capacity=None,
                        cleanup_buffer_minutes=None) -> dict:
    payload = create_molding_line_payload(foundry_id)
    if daily_minute_capacity is not None:
        payload["daily_minute_capacity"] = daily_minute_capacity
    if cleanup_buffer_minutes is not None:
        payload["cleanup_buffer_minutes"] = cleanup_buffer_minutes
    return get_success_data(api_client.create_equipment(payload, ADMIN))


def create_sand_batch_in_service(foundry_id: str, virgin_weight_kg=None,
                                 max_loi_pct=None, loi_pct=None) -> dict:
    """Mix a batch and admit it MIXED -> IN_SERVICE with a passing LOI test."""
    payload = create_sand_batch_payload(foundry_id)
    if virgin_weight_kg is not None:
        payload["virgin_weight_kg"] = virgin_weight_kg
    if max_loi_pct is not None:
        payload["max_loi_pct"] = max_loi_pct
    batch = get_success_data(api_client.create_sand_batch(payload, LINE))
    reading = TEST_DEFAULTS["PASSING_LOI_PCT"] if loi_pct is None else loi_pct
    return get_success_data(api_client.test_sand_batch(batch["id"], {"loi_pct": reading}, QI))


def create_active_pattern(foundry_id: str, part_number="PN-1", dimensions=None,
                          machining_allowance_mm=8.0, impressions=1,
                          alloy_shrink_class="FERROUS", mold_process="SAND",
                          parent_pattern_id=None) -> dict:
    """Create a pattern and qualify it with exactly its computed dimensions."""
    dims = dimensions if dimensions is not None else [100.0, 50.0, 25.0]
    payload = create_pattern_payload(
        foundry_id,
        part_number=part_number,
        alloy_shrink_class=alloy_shrink_class,
        mold_process=mold_process,
        finish_dimensions_mm=dims,
        machining_allowance_mm=machining_allowance_mm,
        impressions=impressions,
    )
    if parent_pattern_id is not None:
        payload["parent_pattern_id"] = parent_pattern_id
    pattern = get_success_data(api_client.create_pattern(payload, PM))
    measured = compute_pattern_dimensions(dims, machining_allowance_mm,
                                          alloy_shrink_class, mold_process)
    return get_success_data(api_client.qualify_pattern(
        pattern["id"], {"measured_dimensions_mm": measured}, PM))


def get_pattern(pattern_id: str) -> dict:
    return get_success_data(api_client.get_pattern(pattern_id, PM))


def create_order(foundry_id: str, customer_id: str, pattern_id: str, quantity=1,
                 overage_pct=None, warranty_budget_cents=None, warranty_months=None,
                 unit_price_cents=None, machining_allowance_pct=None) -> dict:
    payload = create_order_payload(foundry_id, customer_id, pattern_id, quantity=quantity)
    if overage_pct is not None:
        payload["overage_pct"] = overage_pct
    if warranty_budget_cents is not None:
        payload["warranty_budget_cents"] = warranty_budget_cents
    if warranty_months is not None:
        payload["warranty_months"] = warranty_months
    if unit_price_cents is not None:
        payload["unit_price_cents"] = unit_price_cents
    if machining_allowance_pct is not None:
        payload["machining_allowance_pct"] = machining_allowance_pct
    return get_success_data(api_client.create_order(payload, ADMIN))


# ─── Melt deck (OCC-threaded) ─────────────────────────

def create_heat(foundry_id: str, furnace_id: str, chemistry_spec=None) -> dict:
    payload = create_heat_payload(foundry_id, furnace_id)
    if chemistry_spec is not None:
        payload["chemistry_spec"] = chemistry_spec
    return get_success_data(api_client.create_heat(payload, MELT))


def get_heat(heat_id: str) -> dict:
    return get_success_data(api_client.get_heat(heat_id, MELT))


def add_charges(heat: dict, additions: list) -> dict:
    """Add charge material, threading expected_heat_version (PRD §2.6)."""
    return get_success_data(api_client.add_heat_charges(
        heat["id"],
        {"expected_heat_version": heat["version"], "additions": additions},
        MELT,
    ))


def auto_correct(heat: dict) -> dict:
    return get_success_data(api_client.add_heat_charges(
        heat["id"], {"expected_heat_version": heat["version"], "mode": "AUTO_CORRECT"}, MELT))


def record_sample(heat: dict, reading: dict, spectro_headers=SPECTRO_1) -> dict:
    return get_success_data(api_client.add_heat_sample(
        heat["id"], {"expected_heat_version": heat["version"], "reading": reading},
        spectro_headers,
    ))


def certify_heat(heat: dict, reading=None, spectro_headers=SPECTRO_1) -> dict:
    return record_sample(heat, reading if reading is not None else SIMPLE_READING,
                         spectro_headers)


def create_certified_heat(foundry_id: str, furnace_id: str, charge_weight_kg=1000,
                          chemistry_spec=None, charge_composition=None,
                          reading=None) -> dict:
    """Open a heat, charge it, and certify it with a passing spectro sample."""
    spec = chemistry_spec if chemistry_spec is not None else SIMPLE_SPEC
    composition = charge_composition if charge_composition is not None else SIMPLE_READING
    heat = create_heat(foundry_id, furnace_id, chemistry_spec=spec)
    heat = add_charges(heat, [virgin_addition(charge_weight_kg, composition)])
    return certify_heat(heat, reading if reading is not None else composition)


def tap(heat: dict, tap_weight_kg) -> dict:
    return get_success_data(api_client.tap_heat(
        heat["id"], {"tap_weight_kg": tap_weight_kg}, MELT))


# ─── Return lots ───────────────────────────────────────

def create_return_lot(foundry_id: str, collected_weight_kg=500.0) -> dict:
    return get_success_data(api_client.create_return_lot(
        create_return_lot_payload(foundry_id, collected_weight_kg=collected_weight_kg), MELT))


def get_return_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_return_lot(lot_id, MELT))


def create_assayed_lot(foundry_id: str, collected_weight_kg=500.0,
                       assay_composition=None, chemistry_spec=None) -> dict:
    """Collect a lot and assay it ASSAYED with an in-spec composition."""
    lot = create_return_lot(foundry_id, collected_weight_kg=collected_weight_kg)
    composition = assay_composition if assay_composition is not None else {"C": 3.40}
    spec = chemistry_spec if chemistry_spec is not None else SIMPLE_SPEC
    return get_success_data(api_client.assay_return_lot(
        lot["id"], {"assay_composition": composition, "chemistry_spec": spec},
        TEST_USERS["spectro_1_headers"]))


# ─── Molding / pouring ─────────────────────────────────

def create_mold(pattern_id: str, sand_batch_id: str, order_id: str,
                sand_weight_kg=50, metal_weight_kg=200, cooling_hours=2) -> dict:
    return get_success_data(api_client.create_mold(
        create_mold_payload(pattern_id, sand_batch_id, order_id,
                            sand_weight_kg=sand_weight_kg,
                            metal_weight_kg=metal_weight_kg,
                            cooling_hours=cooling_hours),
        LINE,
    ))


def get_mold(mold_id: str) -> dict:
    return get_success_data(api_client.get_mold(mold_id, LINE))


def book_slot(molding_line_id: str, heat_id: str, mold_ids: list,
              start_at=SLOT_START, end_at=SLOT_END) -> dict:
    return get_success_data(api_client.create_pour_slot(
        create_pour_slot_payload(molding_line_id, heat_id, mold_ids, start_at, end_at),
        LINE,
    ))


def get_pour_slot(slot_id: str) -> dict:
    return get_success_data(api_client.get_pour_slot(slot_id, LINE))


def complete_slot(slot_id: str) -> dict:
    return get_success_data(api_client.complete_pour_slot(slot_id, LINE))


def list_castings(params: dict) -> list:
    return get_success_data(api_client.list_castings(LINE, params=params))


def advance_casting(casting_id: str, steps: int = 1) -> dict:
    casting = None
    for _ in range(steps):
        casting = get_success_data(api_client.advance_casting(casting_id, LINE))
    return casting


# ─── Tier 2/3 composite: full production chain ─────────

def setup_shop(*, sand_virgin_kg=1000.0, order_quantity=1, impressions=1,
               pattern_dimensions=None, machining_allowance_mm=8.0,
               warranty_budget_cents=None, warranty_months=None,
               overage_pct=None, unit_price_cents=None,
               machining_allowance_pct=None, chemistry_spec=None,
               line_minute_capacity=None, line_buffer=None,
               furnace_tap_capacity=None, clock=CLOCK_MORNING,
               part_number="PN-1") -> dict:
    """Commission a site: clock + foundry + customer + furnace + molding line +
    IN_SERVICE sand batch + ACTIVE pattern + order. Returns a context dict."""
    set_clock(clock)
    foundry = create_foundry()
    customer = create_customer(foundry["id"])
    furnace = create_furnace(foundry["id"], daily_tap_capacity_kg=furnace_tap_capacity)
    line = create_molding_line(foundry["id"], daily_minute_capacity=line_minute_capacity,
                               cleanup_buffer_minutes=line_buffer)
    batch = create_sand_batch_in_service(foundry["id"], virgin_weight_kg=sand_virgin_kg)
    pattern = create_active_pattern(
        foundry["id"], part_number=part_number, dimensions=pattern_dimensions,
        machining_allowance_mm=machining_allowance_mm, impressions=impressions)
    order = create_order(foundry["id"], customer["id"], pattern["id"],
                         quantity=order_quantity, overage_pct=overage_pct,
                         warranty_budget_cents=warranty_budget_cents,
                         warranty_months=warranty_months,
                         unit_price_cents=unit_price_cents,
                         machining_allowance_pct=machining_allowance_pct)
    return {
        "foundry": foundry, "customer": customer, "furnace": furnace,
        "line": line, "batch": batch, "pattern": pattern, "order": order,
        "chemistry_spec": chemistry_spec,
    }


def pour_molds(ctx: dict, mold_specs: list, *, tap_weight_kg=1000,
               slot_start=SLOT_START, slot_end=SLOT_END,
               complete_at=CLOCK_POUR) -> dict:
    """Certify + tap a heat, assemble molds, book one slot, complete the pour.

    mold_specs: list of dicts with sand_weight_kg / metal_weight_kg / cooling_hours.
    Populates ctx with heat, molds, slot, castings (one list per mold)."""
    spec = ctx.get("chemistry_spec") or SIMPLE_SPEC
    heat = create_certified_heat(ctx["foundry"]["id"], ctx["furnace"]["id"],
                                 chemistry_spec=spec)
    heat = tap(heat, tap_weight_kg)
    molds = [create_mold(ctx["pattern"]["id"], ctx["batch"]["id"], ctx["order"]["id"],
                         **mold_spec) for mold_spec in mold_specs]
    slot = book_slot(ctx["line"]["id"], heat["id"], [m["id"] for m in molds],
                     start_at=slot_start, end_at=slot_end)
    set_clock(complete_at)
    slot = complete_slot(slot["id"])
    castings = [list_castings({"mold_id": m["id"]}) for m in molds]
    ctx.update({"heat": heat, "molds": molds, "slot": slot, "castings": castings})
    return ctx


def cool_and_shakeout(ctx: dict, at=CLOCK_AFTER_COOLING) -> dict:
    """Advance the clock past cooling, run the ops epoch, shake out every mold."""
    set_clock(at)
    run_ops(ctx["foundry"]["id"])
    for mold in ctx["molds"]:
        api_resp = api_client.shakeout_mold(mold["id"], LINE)
        get_success_data(api_resp)
    return ctx


def advance_all_castings_to_final_inspection(ctx: dict) -> dict:
    for casting_list in ctx["castings"]:
        for casting in casting_list:
            advance_casting(casting["id"], steps=3)
    return ctx


def setup_casting_at_final_inspection(*, sand_virgin_kg=1000.0, order_quantity=1,
                                      mold_sand_kg=50, mold_metal_kg=200,
                                      tap_weight_kg=1000, chemistry_spec=None,
                                      warranty_budget_cents=None, warranty_months=None,
                                      unit_price_cents=None,
                                      machining_allowance_pct=None) -> dict:
    """Full chain: one poured mold whose single-impression casting stands at
    routing FINAL_INSPECTION with quality PENDING. Returns the context dict."""
    ctx = setup_shop(sand_virgin_kg=sand_virgin_kg, order_quantity=order_quantity,
                     warranty_budget_cents=warranty_budget_cents,
                     warranty_months=warranty_months,
                     unit_price_cents=unit_price_cents,
                     machining_allowance_pct=machining_allowance_pct,
                     chemistry_spec=chemistry_spec)
    pour_molds(ctx, [{"sand_weight_kg": mold_sand_kg, "metal_weight_kg": mold_metal_kg,
                      "cooling_hours": 2}], tap_weight_kg=tap_weight_kg)
    cool_and_shakeout(ctx)
    advance_all_castings_to_final_inspection(ctx)
    return ctx


# ─── Inspection / disposition ──────────────────────────

def record_inspection(casting_id: str, porosity_grade=1, defect_type="NONE", zone="C") -> dict:
    return get_success_data(api_client.create_inspection(
        create_inspection_payload(casting_id, porosity_grade=porosity_grade,
                                  defect_type=defect_type, zone=zone),
        QI,
    ))


def disposition(inspection_id: str, decision: str, qi_headers=QI, **extra) -> dict:
    payload = {"disposition": decision}
    payload.update(extra)
    return get_success_data(api_client.disposition_inspection(inspection_id, payload,
                                                              qi_headers))


def accept_casting(casting_id: str) -> dict:
    """Record a clean inspection and ACCEPT it (drives order fulfillment)."""
    insp = record_inspection(casting_id, porosity_grade=1, defect_type="NONE", zone="C")
    disposition(insp["id"], "ACCEPT")
    return insp


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, ADMIN))


def setup_fulfilled_order(**kwargs) -> dict:
    """Production chain plus one ACCEPTED casting: the order is FULFILLED."""
    ctx = setup_casting_at_final_inspection(**kwargs)
    accept_casting(ctx["castings"][0][0]["id"])
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


# ─── Warranty claims ───────────────────────────────────

def file_claim(ctx: dict, claim_type="DEFECT", claim_qty=1, claimed_amount_cents=50000,
               freight_cents=None) -> dict:
    payload = create_claim_payload(ctx["order"]["id"], claim_type=claim_type,
                                   claim_qty=claim_qty,
                                   claimed_amount_cents=claimed_amount_cents)
    if freight_cents is not None:
        payload["freight_cents"] = freight_cents
    return get_success_data(api_client.create_claim(
        payload, make_customer_headers(ctx["customer"]["id"])))


def review(claim_id: str, action: str, headers) -> dict:
    return get_success_data(api_client.review_claim(claim_id, {"action": action}, headers))


def setup_approved_claim(*, claim_type="DEFECT", claim_qty=1,
                         claimed_amount_cents=50000, freight_cents=None,
                         warranty_budget_cents=None, warranty_months=None,
                         unit_price_cents=None, machining_allowance_pct=None) -> dict:
    """FULFILLED order + claim reviewed to APPROVED by WarrantyManager wm_1."""
    ctx = setup_fulfilled_order(warranty_budget_cents=warranty_budget_cents,
                                warranty_months=warranty_months,
                                unit_price_cents=unit_price_cents,
                                machining_allowance_pct=machining_allowance_pct)
    claim = file_claim(ctx, claim_type=claim_type, claim_qty=claim_qty,
                       claimed_amount_cents=claimed_amount_cents,
                       freight_cents=freight_cents)
    review(claim["id"], "START", WM_1)
    review(claim["id"], "APPROVE", WM_1)
    ctx["claim"] = claim
    return ctx


def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, TEST_USERS["wm_2_headers"]))


def get_sand_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_sand_batch(batch_id, LINE))


def get_casting(casting_id: str) -> dict:
    return get_success_data(api_client.get_casting(casting_id, QI))


def get_inspection(inspection_id: str) -> dict:
    return get_success_data(api_client.get_inspection(inspection_id, QI))


def get_scrap_records_for_casting(casting_id: str) -> list:
    return get_success_data(api_client.list_scrap_records(
        QI, params={"casting_id": casting_id}))
