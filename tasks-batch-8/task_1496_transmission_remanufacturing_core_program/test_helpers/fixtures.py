"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database and the logical clock at the startup default of 2026-08-01T00:00:00Z,
PRD §2.5). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import FAIL_PRESSURES, PASS_PRESSURES
from .factories import (
    create_calibration_payload,
    create_core_unit_payload,
    create_dyno_booking_payload,
    create_dyno_run_payload,
    create_hard_part_payload,
    create_inspection_payload,
    create_interchange_mapping_payload,
    create_reman_order_payload,
    create_resolve_dispute_payload,
    create_stock_adjustment_payload,
    create_transmission_model_payload,
    create_warranty_claim_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]
INV_PLANNER = TEST_USERS["inventory_planner_headers"]
PLANNER = TEST_USERS["reman_planner_headers"]
TECH = TEST_USERS["reman_technician_headers"]
CAL_A = TEST_USERS["calibrator_a_headers"]
CAL_B = TEST_USERS["calibrator_b_headers"]
DYNO_OP = TEST_USERS["dyno_operator_headers"]
CLERK = TEST_USERS["core_intake_clerk_headers"]
INSPECTOR = TEST_USERS["core_inspector_headers"]
INSTALLER = TEST_USERS["installer_headers"]
ADJUSTER = TEST_USERS["warranty_adjuster_headers"]
ANY_H = TEST_USERS["any_headers"]


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at {step}: {exc}")


# ---------------------------------------------------------------------------
# Tier 1 — catalog primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the server's logical clock (PRD §2.5)."""
    return _ok("set_current_utc",
               api_client.set_current_utc(set_clock_payload(to_iso8601), ADMIN))


def create_min_model(**overrides):
    """The MIN-spec model: deposit 50000c, flat 6.0h, cap 90000c, no kit parts."""
    return _ok("create_transmission_model",
               api_client.create_transmission_model(
                   create_transmission_model_payload(**overrides), ADMIN))


def create_full_pump_model(required_qty=2, **overrides):
    """A model whose kit spec requires `required_qty` of part family PUMP."""
    overrides.setdefault("model_code", "FULL-6L80")
    overrides["required_parts"] = [{"part_family": "PUMP", "qty": required_qty}]
    return create_min_model(**overrides)


def create_hard_part_record(part_number="P-100", part_family="PUMP",
                            unit_cost_cents=1000, qty_on_hand=5, **overrides):
    return _ok("create_hard_part",
               api_client.create_hard_part(
                   create_hard_part_payload(part_number, part_family,
                                            unit_cost_cents, qty_on_hand,
                                            **overrides),
                   INV_PLANNER))


def create_mapping(part_id, model_id, tier="DIRECT"):
    return _ok("create_interchange_mapping",
               api_client.create_interchange_mapping(
                   create_interchange_mapping_payload(part_id, model_id, tier),
                   INV_PLANNER))


# ---------------------------------------------------------------------------
# Tier 1/3 — reman order lifecycle
# ---------------------------------------------------------------------------

def create_order(model_id, buyer_ref="BUYER-1"):
    return _ok("create_reman_order",
               api_client.create_reman_order(
                   create_reman_order_payload(model_id, buyer_ref), PLANNER))


def kit_reserve(order_id):
    return _ok("kit_reserve", api_client.kit_reserve(order_id, PLANNER))


def complete_assembly(order_id):
    return _ok("complete_assembly", api_client.complete_assembly(order_id, TECH))


def draft_calibration(order_id, tcm_flash_version="TF-2026.08",
                      solenoid_trims=None, drafter=CAL_A):
    return _ok("put_calibration",
               api_client.put_calibration(
                   order_id,
                   create_calibration_payload(solenoid_trims, tcm_flash_version),
                   drafter))


def verify_calibration(order_id, verifier=CAL_B):
    return _ok("verify_calibration",
               api_client.verify_calibration(order_id, verifier))


def drive_order_to_calibration(model_id, buyer_ref="BUYER-1"):
    """QUEUED -> ASSEMBLY -> CALIBRATION. Assumes kit allocation succeeds."""
    order = create_order(model_id, buyer_ref)
    order = kit_reserve(order["id"])
    assert order["status"] == "ASSEMBLY", (
        f"Setup failed: kit-reserve left order in {order['status']}, expected ASSEMBLY"
    )
    order = complete_assembly(order["id"])
    return order


def drive_order_to_dyno_queue(model_id, buyer_ref="BUYER-1",
                              flash="TF-2026.08"):
    """QUEUED -> DYNO_QUEUE with a verified calibration (drafter cal-a,
    verifier cal-b per the segregation-of-duties rule, PRD §3.3)."""
    order = drive_order_to_calibration(model_id, buyer_ref)
    order = draft_calibration(order["id"], tcm_flash_version=flash)
    order = verify_calibration(order["id"])
    assert order["status"] == "DYNO_QUEUE", (
        f"Setup failed: verify-calibration left order in {order['status']}"
    )
    return order


def book_dyno_window(order_id, cell="DYNO-1", start="2026-08-01T00:00:00Z",
                     end="2026-08-02T00:00:00Z"):
    return _ok("create_dyno_booking",
               api_client.create_dyno_booking(
                   create_dyno_booking_payload(order_id, cell, start, end), TECH))


def record_dyno_run(order_id, pressures=None):
    return _ok("create_dyno_test_run",
               api_client.create_dyno_test_run(
                   create_dyno_run_payload(order_id, pressures), DYNO_OP))


def fail_run_and_recalibrate(order_id, flash):
    """Record one FAIL run (order -> REWORK) then re-draft and re-verify,
    looping the order back to DYNO_QUEUE (PRD §3.4)."""
    run = record_dyno_run(order_id, FAIL_PRESSURES)
    assert run["verdict"] == "FAIL", "Setup failed: expected a FAIL verdict"
    draft_calibration(order_id, tcm_flash_version=flash)
    order = verify_calibration(order_id)
    assert order["status"] == "DYNO_QUEUE"
    return order


def drive_order_to_shipped(model=None, buyer_ref="BUYER-1", cell="DYNO-1"):
    """Full happy path at the default logical clock: model -> order ->
    DYNO_QUEUE -> covering booking -> PASS run -> SHIPPED, then the
    ship-cascade invoice. Returns (model, shipped_order, invoice)."""
    model = model or create_min_model()
    order = drive_order_to_dyno_queue(model["id"], buyer_ref)
    book_dyno_window(order["id"], cell)
    record_dyno_run(order["id"], PASS_PRESSURES)
    shipped = _ok("ship_order", api_client.ship_order(order["id"], PLANNER))
    assert shipped["status"] == "SHIPPED"
    invoice = get_invoice_for_order(order["id"])
    return model, shipped, invoice


def get_invoice_for_order(order_id):
    resp = api_client.list_core_deposit_invoices(
        ANY_H, params={"reman_order_id": order_id})
    data = _ok("list_core_deposit_invoices", resp)
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: expected exactly 1 invoice for order {order_id}, "
        f"got {len(data) if isinstance(data, list) else data}"
    )
    return data[0]


def get_order(order_id):
    return _ok("get_reman_order", api_client.get_reman_order(order_id, ANY_H))


def get_part(part_id):
    return _ok("get_hard_part", api_client.get_hard_part(part_id, ANY_H))


def get_invoice(invoice_id):
    return _ok("get_core_deposit_invoice",
               api_client.get_core_deposit_invoice(invoice_id, ANY_H))


def get_claim(claim_id):
    return _ok("get_warranty_claim",
               api_client.get_warranty_claim(claim_id, ANY_H))


# ---------------------------------------------------------------------------
# Tier 3/5 — core intake, grading, disputes
# ---------------------------------------------------------------------------

def register_core(invoice_id, dock_code="DOCK-1",
                  start="2026-08-01T10:00:00Z", end="2026-08-01T11:00:00Z"):
    return _ok("create_core_unit",
               api_client.create_core_unit(
                   create_core_unit_payload(invoice_id, dock_code, start, end),
                   CLERK))


def inspect_core(core_id, case_cracked=False, findings=()):
    return _ok("inspect_core_unit",
               api_client.inspect_core_unit(
                   core_id, create_inspection_payload(case_cracked, list(findings)),
                   INSPECTOR))


def setup_registered_core(model=None, buyer_ref="BUYER-1", dock_code="DOCK-1",
                          start="2026-08-01T10:00:00Z", end="2026-08-01T11:00:00Z",
                          cell="DYNO-1"):
    """Shipped order + registered core (invoice AWAITING_GRADE).
    Returns (model, order, invoice, core). Callers building several shipped
    orders must pass distinct `cell` values: identical windows on one cell
    overlap (PRD §3.4 half-open cell windows)."""
    model, order, invoice = drive_order_to_shipped(model=model, buyer_ref=buyer_ref,
                                                   cell=cell)
    core = register_core(invoice["id"], dock_code, start, end)
    return model, order, invoice, core


def setup_graded_core(findings=("SENSOR_HARNESS_MISSING",), case_cracked=False,
                      model=None, buyer_ref="BUYER-1"):
    """Shipped order + core registered on-time + one inspection.
    Returns (model, order, invoice, graded_core)."""
    model, order, invoice, core = setup_registered_core(model=model,
                                                        buyer_ref=buyer_ref)
    graded = inspect_core(core["id"], case_cracked=case_cracked, findings=findings)
    invoice = get_invoice(invoice["id"])
    return model, order, invoice, graded


def setup_disputed_invoice(findings=("SENSOR_HARNESS_MISSING",)):
    """Grade-B partial settlement (37500c of 50000c) moved to DISPUTED.
    Returns (model, order, invoice, core)."""
    model, order, invoice, core = setup_graded_core(findings=findings)
    invoice = _ok("dispute_invoice", api_client.dispute_invoice(invoice["id"], CLERK))
    assert invoice["status"] == "DISPUTED"
    return model, order, invoice, core


# ---------------------------------------------------------------------------
# Tier 2/4 — part-hold and promotion scenarios
# ---------------------------------------------------------------------------

def setup_single_part_hold_order(p1_qty=1, required_qty=2):
    """FULL pump model; one DIRECT part short of the kit requirement; the
    order's kit-reserve slides it to PART_HOLD (PRD §3.2).
    Returns (model, part, order)."""
    model = create_full_pump_model(required_qty=required_qty)
    part = create_hard_part_record(qty_on_hand=p1_qty)
    create_mapping(part["id"], model["id"], "DIRECT")
    order = create_order(model["id"], "BUYER-1")
    order = kit_reserve(order["id"])
    assert order["status"] == "PART_HOLD", (
        f"Setup failed: expected PART_HOLD, got {order['status']}"
    )
    return model, part, order


def setup_kitted_pair(p1_qty=2, required_qty=2):
    """FULL pump model; order1 kitted into ASSEMBLY holding the stock; order2
    shorted into PART_HOLD. Returns (model, part, order1, order2)."""
    model = create_full_pump_model(required_qty=required_qty)
    part = create_hard_part_record(qty_on_hand=p1_qty)
    create_mapping(part["id"], model["id"], "DIRECT")
    o1 = create_order(model["id"], "BUYER-1")
    o1 = kit_reserve(o1["id"])
    assert o1["status"] == "ASSEMBLY", (
        f"Setup failed: order1 expected ASSEMBLY, got {o1['status']}"
    )
    o2 = create_order(model["id"], "BUYER-2")
    o2 = kit_reserve(o2["id"])
    assert o2["status"] == "PART_HOLD", (
        f"Setup failed: order2 expected PART_HOLD, got {o2['status']}"
    )
    return model, part, o1, o2


def setup_third_fail_cascade():
    """Depth-3 cascade setup (PRD §3.4): FULL model needing 2x PUMP; P1 DIRECT
    on_hand 3; P2 ADAPTED on_hand 1. order1 kitted (2x P1) and sitting in
    DYNO_QUEUE with two FAILs already consumed and a fresh verified
    calibration; order2 waiting in PART_HOLD. Returns dict of entities."""
    model = create_full_pump_model(required_qty=2)
    p1 = create_hard_part_record(part_number="P-100", unit_cost_cents=1000,
                                 qty_on_hand=3)
    p2 = create_hard_part_record(part_number="P-200", unit_cost_cents=900,
                                 qty_on_hand=1)
    create_mapping(p1["id"], model["id"], "DIRECT")
    create_mapping(p2["id"], model["id"], "ADAPTED")
    o1 = create_order(model["id"], "BUYER-1")
    o1 = kit_reserve(o1["id"])
    assert o1["status"] == "ASSEMBLY"
    o2 = create_order(model["id"], "BUYER-2")
    o2 = kit_reserve(o2["id"])
    assert o2["status"] == "PART_HOLD"
    o1 = complete_assembly(o1["id"])
    draft_calibration(o1["id"], tcm_flash_version="TF-2026.08")
    verify_calibration(o1["id"])
    book_dyno_window(o1["id"], "DYNO-1", "2026-08-01T00:00:00Z",
                     "2026-08-05T00:00:00Z")
    fail_run_and_recalibrate(o1["id"], "TF-2026.08b")
    fail_run_and_recalibrate(o1["id"], "TF-2026.08c")
    o1 = get_order(o1["id"])
    assert o1["dyno_attempts_used"] == 2 and o1["status"] == "DYNO_QUEUE"
    return {"model": model, "p1": p1, "p2": p2, "o1": o1, "o2": o2}


def setup_attempt_budget_order():
    """MIN-model order in DYNO_QUEUE with a long covering booking and two
    FAIL runs already consumed (dyno_attempts_used == 2). Returns order."""
    model = create_min_model()
    order = drive_order_to_dyno_queue(model["id"], "BUYER-1")
    book_dyno_window(order["id"], "DYNO-1", "2026-08-01T00:00:00Z",
                     "2026-08-05T00:00:00Z")
    fail_run_and_recalibrate(order["id"], "TF-2026.08b")
    fail_run_and_recalibrate(order["id"], "TF-2026.08c")
    order = get_order(order["id"])
    assert order["dyno_attempts_used"] == 2
    return order


# ---------------------------------------------------------------------------
# Tier 3 — warranty claims
# ---------------------------------------------------------------------------

def submit_claim(order_id, failure_code="GEAR_CLUNK", claimed_labor_hours=5.0,
                 installer_labor_rate_cents=12000, allowance_policy="BOOK_HOURS",
                 installer_headers=None):
    return _ok("create_warranty_claim",
               api_client.create_warranty_claim(
                   create_warranty_claim_payload(
                       order_id, failure_code, claimed_labor_hours,
                       installer_labor_rate_cents, allowance_policy),
                   installer_headers or INSTALLER))


def setup_submitted_claim(model=None, **claim_kwargs):
    """Shipped order + one SUBMITTED claim filed by inst-1.
    Returns (model, order, claim)."""
    model, order, _invoice = drive_order_to_shipped(model=model)
    claim = submit_claim(order["id"], **claim_kwargs)
    assert claim["claim_status"] == "SUBMITTED"
    return model, order, claim


def setup_approved_claim(model=None, **claim_kwargs):
    """Shipped order + claim APPROVED by the adjuster.
    Returns (model, order, claim)."""
    model, order, claim = setup_submitted_claim(model=model, **claim_kwargs)
    claim = _ok("approve_claim", api_client.approve_claim(claim["id"], ADJUSTER))
    assert claim["claim_status"] == "APPROVED"
    return model, order, claim


def setup_claim_in_transit(**claim_kwargs):
    """Approved claim (routing RETURN_TO_PLANT via the default 72000c
    allowance) with the return leg shipped by the filing installer.
    Returns (model, order, claim)."""
    model, order, claim = setup_approved_claim(**claim_kwargs)
    assert claim["return_status"] == "ISSUED"
    claim = _ok("return_ship_claim",
                api_client.return_ship_claim(claim["id"], INSTALLER))
    assert claim["return_status"] == "IN_TRANSIT"
    return model, order, claim


def setup_salvage_promotion_scenario():
    """FULL pump model; P1 on_hand 2 fully kitted to order1 (then shipped, so
    the units are consumed); order2 waiting in PART_HOLD; an approved
    RETURN_TO_PLANT claim on order1 with the return leg IN_TRANSIT.
    Returns dict of entities."""
    model, part, o1, o2 = setup_kitted_pair(p1_qty=2, required_qty=2)
    o1 = complete_assembly(o1["id"])
    draft_calibration(o1["id"])
    verify_calibration(o1["id"])
    book_dyno_window(o1["id"], "DYNO-1")
    record_dyno_run(o1["id"], PASS_PRESSURES)
    o1 = _ok("ship_order", api_client.ship_order(o1["id"], PLANNER))
    claim = submit_claim(o1["id"])
    claim = _ok("approve_claim", api_client.approve_claim(claim["id"], ADJUSTER))
    assert claim["routing_type"] == "RETURN_TO_PLANT"
    claim = _ok("return_ship_claim",
                api_client.return_ship_claim(claim["id"], INSTALLER))
    return {"model": model, "part": part, "o1": o1, "o2": o2, "claim": claim}
