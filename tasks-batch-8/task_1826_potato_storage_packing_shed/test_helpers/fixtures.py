"""Composite setup helpers for the potato storage & packing workflows.

Every helper builds its preconditions from scratch via PRD-declared endpoints and
returns plain dicts of created resources. Setup calls use get_success_data() so
failures surface as clear setup errors rather than assertion noise.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_grower_payload, create_shed_payload, create_bin_payload,
    create_field_lot_payload, create_assessment_payload, create_contract_payload,
    create_pack_order_payload, create_wash_check_payload, make_draw,
)
from .test_users import TEST_USERS, make_grower_headers, make_clerk_headers

ADMIN = TEST_USERS["admin_headers"]
INTAKE = TEST_USERS["intake_headers"]
STORAGE = TEST_USERS["storage_headers"]
QA = TEST_USERS["qa_headers"]
SALES = TEST_USERS["sales_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
CLERK = TEST_USERS["clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creates
# ---------------------------------------------------------------------------

def create_grower(name="Test Grower", grower_code="G-TEST", **overrides):
    """Register a grower. Returns the Grower resource."""
    payload = create_grower_payload(name=name, grower_code=grower_code, **overrides)
    return get_success_data(api_client.create_grower(payload, ADMIN))


def create_shed(name="Test Shed"):
    return get_success_data(api_client.create_shed(create_shed_payload(name=name), ADMIN))


def create_bin(shed_id, bin_code="B-1", capacity_cwt=2000.00):
    return get_success_data(
        api_client.create_bin(shed_id, create_bin_payload(bin_code=bin_code, capacity_cwt=capacity_cwt), ADMIN)
    )


def create_lot(grower_id, variety="RUSSET_BURBANK", harvest_date="2026-07-20",
               original_weight_cwt=500.00, **overrides):
    payload = create_field_lot_payload(
        variety=variety, harvest_date=harvest_date,
        original_weight_cwt=original_weight_cwt, **overrides,
    )
    return get_success_data(api_client.create_field_lot(grower_id, payload, INTAKE))


def bin_lot(lot_id, bin_id):
    """Assign an INTAKE lot to a bin. Returns the updated (BINNED) lot."""
    return get_success_data(api_client.assign_bin(lot_id, {"bin_id": bin_id}, INTAKE))


def create_binned_lot(grower_id, bin_id, variety="RUSSET_BURBANK", harvest_date="2026-07-20",
                      original_weight_cwt=500.00, **overrides):
    """Create + bin-assign. Returns the BINNED lot."""
    lot = create_lot(grower_id, variety=variety, harvest_date=harvest_date,
                     original_weight_cwt=original_weight_cwt, **overrides)
    return bin_lot(lot["id"], bin_id)


def assess_lot(lot_id, expected_field_lot_version, us1_pct=70.0, us2_pct=20.0, cull_pct=10.0,
               cumulative_shrink_cwt=0.00, assessment_date="2026-08-02"):
    payload = create_assessment_payload(
        expected_field_lot_version, us1_pct=us1_pct, us2_pct=us2_pct, cull_pct=cull_pct,
        cumulative_shrink_cwt=cumulative_shrink_cwt, assessment_date=assessment_date,
    )
    return get_success_data(api_client.create_assessment(lot_id, payload, STORAGE))


def apply_inhibitor(lot_id, applied_at):
    return get_success_data(
        api_client.apply_sprout_inhibitor(lot_id, {"applied_at": applied_at}, STORAGE)
    )


def hold_lot(lot_id):
    return get_success_data(api_client.quality_transition(lot_id, {"to_status": "ON_HOLD"}, QA))


def condemn_lot(lot_id, diversion_channel="WASTE"):
    """ON_HOLD -> CONDEMNED; books available into condemned and auto-closes the lot."""
    return get_success_data(api_client.quality_transition(
        lot_id, {"to_status": "CONDEMNED", "diversion_channel": diversion_channel}, QA
    ))


def hold_and_condemn_lot(lot_id, diversion_channel="WASTE"):
    hold_lot(lot_id)
    return condemn_lot(lot_id, diversion_channel)


def create_contract(variety="RUSSET_BURBANK", committed_volume_cwt=300.00,
                    price_cents_per_cwt=2000, grade_min_us1_pct=50.0,
                    delivery_window_start="2026-08-01T00:00:00Z",
                    delivery_window_end="2026-12-01T00:00:00Z",
                    priority_rank=1, buyer_name="Test Buyer"):
    payload = create_contract_payload(
        buyer_name=buyer_name, variety=variety, committed_volume_cwt=committed_volume_cwt,
        price_cents_per_cwt=price_cents_per_cwt, grade_min_us1_pct=grade_min_us1_pct,
        delivery_window_start=delivery_window_start, delivery_window_end=delivery_window_end,
        priority_rank=priority_rank,
    )
    return get_success_data(api_client.create_contract(payload, SALES))


def create_order(shed_id, order_type="CONTRACT", contract_id=None, variety="RUSSET_BURBANK",
                 requested_packed_cwt=75.00, allocation_policy="LOT_ASSESSMENT",
                 grade_min_us1_pct=50.0, pack_unit_weight_lbs=50,
                 market_price_cents_per_cwt=None):
    payload = create_pack_order_payload(
        shed_id, order_type=order_type, variety=variety,
        requested_packed_cwt=requested_packed_cwt, allocation_policy=allocation_policy,
        grade_min_us1_pct=grade_min_us1_pct, pack_unit_weight_lbs=pack_unit_weight_lbs,
    )
    if contract_id is not None:
        payload["contract_id"] = contract_id
    if market_price_cents_per_cwt is not None:
        payload["market_price_cents_per_cwt"] = market_price_cents_per_cwt
    return get_success_data(api_client.create_pack_order(payload, SALES))


def allocate_order(order_id):
    return get_success_data(api_client.allocate_order(order_id, SALES))


def create_allocated_order(shed_id, **kwargs):
    order = create_order(shed_id, **kwargs)
    return allocate_order(order["id"])


def record_wash_check(shed_id, measured_at="2026-08-02T06:00:00Z", turbidity_ntu=2.0,
                      chlorine_ppm=100, water_temp_f=50):
    payload = create_wash_check_payload(
        measured_at=measured_at, turbidity_ntu=turbidity_ntu,
        chlorine_ppm=chlorine_ppm, water_temp_f=water_temp_f,
    )
    return get_success_data(api_client.record_wash_check(shed_id, payload, QA))


def record_pass_wash(shed_id, measured_at):
    return record_wash_check(shed_id, measured_at=measured_at,
                             turbidity_ntu=2.0, chlorine_ppm=100, water_temp_f=50)


def record_fail_wash(shed_id, measured_at, turbidity_ntu=5.0):
    return record_wash_check(shed_id, measured_at=measured_at,
                             turbidity_ntu=turbidity_ntu, chlorine_ppm=100, water_temp_f=50)


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_settlement(grower_id, expected_grower_version, season_label="2026-storage"):
    return get_success_data(api_client.create_settlement(
        grower_id,
        {"season_label": season_label, "expected_grower_version": expected_grower_version},
        CLERK,
    ))


# ---------------------------------------------------------------------------
# Tier 2: grower + shed + bin + lot hierarchy
# ---------------------------------------------------------------------------

def setup_grower_shed_bin_lot(grower_name="Grower", grower_code="G-X", shed_name="Shed",
                              bin_code="B-1", bin_capacity_cwt=2000.00,
                              variety="RUSSET_BURBANK", harvest_date="2026-07-20",
                              lot_weight_cwt=500.00, set_clock_to=None):
    """Grower + shed + bin + one BINNED lot. Returns dict of resources."""
    if set_clock_to:
        set_clock(set_clock_to)
    grower = create_grower(grower_name, grower_code)
    shed = create_shed(shed_name)
    bin_ = create_bin(shed["id"], bin_code, bin_capacity_cwt)
    lot = create_binned_lot(grower["id"], bin_["id"], variety=variety,
                            harvest_date=harvest_date, original_weight_cwt=lot_weight_cwt)
    return {"grower": grower, "shed": shed, "bin": bin_, "lot": lot}


# ---------------------------------------------------------------------------
# Tier 3: full allocation / pack-run lifecycles
# ---------------------------------------------------------------------------

def setup_allocated_contract_order(lot_weight_cwt=500.00, committed_cwt=300.00,
                                   requested_packed_cwt=75.00, grade_min_us1_pct=50.0,
                                   allocation_policy="LOT_ASSESSMENT", assess=None,
                                   variety="RUSSET_BURBANK", price_cents_per_cwt=2000,
                                   set_clock_to="2026-08-02T00:00:00Z",
                                   harvest_date="2026-07-20"):
    """Grower + shed + bin + BINNED lot (+ optional assessment) + ACTIVE contract +
    one CONTRACT order already ALLOCATED. Returns dict of resources."""
    if set_clock_to:
        set_clock(set_clock_to)
    grower = create_grower()
    shed = create_shed()
    bin_ = create_bin(shed["id"])
    lot = create_binned_lot(grower["id"], bin_["id"], variety=variety,
                            harvest_date=harvest_date, original_weight_cwt=lot_weight_cwt)
    if assess is not None:
        assess_lot(lot["id"], lot["version"], **assess)
        lot = get_success_data(api_client.get_field_lot(lot["id"], STORAGE))
    contract = create_contract(variety=variety, committed_volume_cwt=committed_cwt,
                               price_cents_per_cwt=price_cents_per_cwt,
                               grade_min_us1_pct=grade_min_us1_pct)
    order = create_order(shed["id"], contract_id=contract["id"], variety=variety,
                         requested_packed_cwt=requested_packed_cwt,
                         allocation_policy=allocation_policy,
                         grade_min_us1_pct=grade_min_us1_pct)
    order = allocate_order(order["id"])
    return {"grower": grower, "shed": shed, "bin": bin_, "lot": lot,
            "contract": contract, "order": order}


def create_scheduled_run(order_id, scheduled_start, scheduled_end):
    """ALLOCATED -> PACKING with a SCHEDULED run. Returns the run."""
    return get_success_data(api_client.create_pack_run(
        order_id, {"scheduled_start": scheduled_start, "scheduled_end": scheduled_end},
        SUPERVISOR,
    ))


def complete_run(run_id, draws):
    return get_success_data(api_client.close_pack_run(
        run_id, {"outcome": "COMPLETED", "draws": draws}, SUPERVISOR
    ))


def abort_run(run_id):
    return get_success_data(api_client.close_pack_run(run_id, {"outcome": "ABORTED"}, SUPERVISOR))


def setup_packing_order_with_run(set_clock_to="2026-08-02T00:00:00Z",
                                 wash_measured_at="2026-08-02T06:00:00Z",
                                 run_start="2026-08-02T08:00:00Z",
                                 run_end="2026-08-02T10:00:00Z",
                                 **allocate_kwargs):
    """Allocated order + fresh PASS wash check + SCHEDULED run. Returns full context."""
    ctx = setup_allocated_contract_order(set_clock_to=set_clock_to, **allocate_kwargs)
    record_pass_wash(ctx["shed"]["id"], wash_measured_at)
    run = create_scheduled_run(ctx["order"]["id"], run_start, run_end)
    ctx["run"] = run
    return ctx


def ship_order(order_id, lot_id, raw_drawn_cwt, packed_cwt, us1_cwt, us2_cwt, cull_cwt,
               run_start, run_end, cull_channel="WASTE"):
    """Create a run on a PACKING-ready order and complete it with one draw.
    Caller is responsible for wash freshness and the order being ALLOCATED."""
    run = create_scheduled_run(order_id, run_start, run_end)
    return complete_run(run["id"], [make_draw(lot_id, raw_drawn_cwt, packed_cwt, us1_cwt,
                                              us2_cwt, cull_cwt, cull_channel)])


# ---------------------------------------------------------------------------
# Tier 4: settlement-targeting helpers
# ---------------------------------------------------------------------------

def setup_grower_with_closed_lot(lot_weight_cwt=100.00, diversion_channel="WASTE",
                                 close_at="2026-08-02T00:00:00Z", bin_at="2026-08-02T00:00:00Z",
                                 inhibitor_at=None):
    """Grower + shed + bin + lot that has been condemned (auto-closing it).
    Returns dict of resources. All weight lands in condemned; nothing packed."""
    set_clock(bin_at)
    grower = create_grower()
    shed = create_shed()
    bin_ = create_bin(shed["id"])
    lot = create_binned_lot(grower["id"], bin_["id"], original_weight_cwt=lot_weight_cwt)
    if inhibitor_at is not None:
        apply_inhibitor(lot["id"], inhibitor_at)
    if close_at != bin_at:
        set_clock(close_at)
    hold_lot(lot["id"])
    lot = condemn_lot(lot["id"], diversion_channel)
    return {"grower": grower, "shed": shed, "bin": bin_, "lot": lot}


def refresh_grower(grower_id):
    return get_success_data(api_client.get_grower(grower_id, CLERK))


def refresh_lot(lot_id):
    return get_success_data(api_client.get_field_lot(lot_id, STORAGE))


def refresh_order(order_id):
    return get_success_data(api_client.get_pack_order(order_id, SALES))


def refresh_contract(contract_id):
    return get_success_data(api_client.get_contract(contract_id, SALES))


def refresh_shed(shed_id):
    return get_success_data(api_client.get_shed(shed_id, QA))


def refresh_settlement(settlement_id):
    return get_success_data(api_client.get_settlement(settlement_id, CLERK))
