"""Composite setup helpers.

Multi-step setup sequences shared by the test suite. Every helper builds its
preconditions from scratch via the public API; setup calls use the lenient
get_success_data() validator so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_aflatoxin_test_payload,
    create_bin_payload,
    create_buyer_payload,
    create_contract_payload,
    create_dryer_payload,
    create_drying_batch_payload,
    create_grower_payload,
    create_kernel_grade_test_payload,
    create_lot_payload,
    create_moisture_kernel_test_payload,
    create_placement_payload,
)
from .test_users import (
    make_admin_headers,
    make_intake_headers,
    make_lab_headers,
    make_operator_headers,
)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators
# ---------------------------------------------------------------------------

def create_grower(**overrides):
    """Create a grower. Returns the Grower dict."""
    resp = api_client.create_grower(create_grower_payload(**overrides), make_admin_headers())
    return get_success_data(resp)


def create_buyer(**overrides):
    """Create a buyer. Returns the Buyer dict."""
    resp = api_client.create_buyer(create_buyer_payload(**overrides), make_admin_headers())
    return get_success_data(resp)


def create_lot(grower_id, **overrides):
    """Create a field lot in RECEIVED. Returns the FieldLot dict."""
    payload = create_lot_payload(grower_id=grower_id, **overrides)
    resp = api_client.create_lot(payload, make_intake_headers())
    return get_success_data(resp)


def create_dryer(**overrides):
    resp = api_client.create_dryer(create_dryer_payload(**overrides), make_admin_headers())
    return get_success_data(resp)


def create_bin(**overrides):
    resp = api_client.create_bin(create_bin_payload(**overrides), make_admin_headers())
    return get_success_data(resp)


def create_contract(buyer_id, **overrides):
    payload = create_contract_payload(buyer_id=buyer_id, **overrides)
    resp = api_client.create_contract(payload, make_admin_headers())
    return get_success_data(resp)


def set_clock(to_iso8601):
    """Advance the logical clock."""
    resp = api_client.set_clock(to_iso8601, make_admin_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: lot lifecycle progression
# ---------------------------------------------------------------------------

def record_moisture_kernel(lot_id, moisture_pct=6.0, kernel_pct=0.50,
                           foreign_material_pct=0.01):
    """Record a MOISTURE_KERNEL lab test (advances RECEIVED -> SAMPLED)."""
    payload = create_moisture_kernel_test_payload(
        lot_id=lot_id,
        moisture_pct=moisture_pct,
        kernel_pct=kernel_pct,
        foreign_material_pct=foreign_material_pct,
    )
    resp = api_client.create_lab_test(payload, make_lab_headers())
    return get_success_data(resp)


def record_aflatoxin(lot_id, aflatoxin_ppb=2.0):
    """Record an AFLATOXIN lab test."""
    payload = create_aflatoxin_test_payload(lot_id=lot_id, aflatoxin_ppb=aflatoxin_ppb)
    resp = api_client.create_lab_test(payload, make_lab_headers())
    return get_success_data(resp)


def record_kernel_grade(lot_id, edible_kernel_pct=0.80, size_spec="SPEC_23_25"):
    """Record a KERNEL_GRADE lab test (lot must be PROCESSED)."""
    payload = create_kernel_grade_test_payload(
        lot_id=lot_id, edible_kernel_pct=edible_kernel_pct, size_spec=size_spec
    )
    resp = api_client.create_lab_test(payload, make_lab_headers())
    return get_success_data(resp)


def get_lot(lot_id):
    resp = api_client.get_lot(lot_id, make_operator_headers())
    return get_success_data(resp)


def route_lot(lot_id, route="KERNEL"):
    resp = api_client.route_lot(lot_id, {"route": route}, make_intake_headers())
    return get_success_data(resp)


def create_sampled_lot(grower_id=None, moisture_pct=6.0, kernel_pct=0.50,
                       foreign_material_pct=0.01, **lot_overrides):
    """Grower (unless given) + lot + MOISTURE_KERNEL test. Returns (grower, lot)."""
    grower = None
    if grower_id is None:
        grower = create_grower()
        grower_id = grower["id"]
    lot = create_lot(grower_id, **lot_overrides)
    record_moisture_kernel(
        lot["id"],
        moisture_pct=moisture_pct,
        kernel_pct=kernel_pct,
        foreign_material_pct=foreign_material_pct,
    )
    return grower, get_lot(lot["id"])


def create_graded_lot(grower_id=None, aflatoxin_ppb=2.0, **kwargs):
    """Sampled lot + AFLATOXIN PASS. Returns (grower, lot in GRADED)."""
    grower, lot = create_sampled_lot(grower_id=grower_id, **kwargs)
    record_aflatoxin(lot["id"], aflatoxin_ppb=aflatoxin_ppb)
    return grower, get_lot(lot["id"])


def create_routed_lot(grower_id=None, route="KERNEL", **kwargs):
    """Graded lot routed to the given route. Returns (grower, lot)."""
    grower, lot = create_graded_lot(grower_id=grower_id, **kwargs)
    route_lot(lot["id"], route=route)
    return grower, get_lot(lot["id"])


# ---------------------------------------------------------------------------
# Tier 3: drying
# ---------------------------------------------------------------------------

def create_completed_drying_batch(lot_id, dryer_id=None, final_moisture_pct=6.0,
                                  start_at="2026-05-02T00:00:00Z",
                                  end_at="2026-05-03T00:00:00Z"):
    """Reserve + start + complete a drying batch for the lot. Returns the batch."""
    if dryer_id is None:
        dryer_id = create_dryer()["id"]
    payload = create_drying_batch_payload(
        dryer_id=dryer_id, lot_id=lot_id, start_at=start_at, end_at=end_at
    )
    batch = get_success_data(api_client.create_drying_batch(payload, make_operator_headers()))
    set_clock(start_at)
    get_success_data(api_client.start_drying_batch(batch["id"], make_operator_headers()))
    set_clock(end_at)
    get_success_data(
        api_client.complete_drying_batch(
            batch["id"], {"final_moisture_pct": final_moisture_pct}, make_operator_headers()
        )
    )
    resp = api_client.get_drying_batch(batch["id"], make_operator_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: processing
# ---------------------------------------------------------------------------

def create_processing_run(lot_id):
    """Create a run against the lot using its current version (OCC). Returns the run."""
    lot = get_lot(lot_id)
    resp = api_client.create_processing_run(
        {"lot_id": lot_id, "expected_lot_version": lot["version"]},
        make_operator_headers(),
    )
    return get_success_data(resp)


def create_completed_run(lot_id, kernel_out_lbs=2400, shell_out_lbs=1300,
                         hull_out_lbs=900):
    """Create + start + complete a run. Returns the completed run."""
    run = create_processing_run(lot_id)
    get_success_data(api_client.start_processing_run(run["id"], make_operator_headers()))
    resp = api_client.complete_processing_run(
        run["id"],
        {
            "kernel_out_lbs": kernel_out_lbs,
            "shell_out_lbs": shell_out_lbs,
            "hull_out_lbs": hull_out_lbs,
        },
        make_operator_headers(),
    )
    return get_success_data(resp)


def create_processed_lot(grower_id=None, route="KERNEL",
                         kernel_out_lbs=2400, shell_out_lbs=1300, hull_out_lbs=900,
                         edible_kernel_pct=0.80, size_spec="SPEC_23_25",
                         record_grade=True, **lot_kwargs):
    """Full chain to PROCESSED: sampled -> graded -> routed -> one completed run.

    Returns dict with keys: grower, lot (post-completion), run.
    When record_grade is True, also records a KERNEL_GRADE test and the returned
    lot reflects the post-grade state.
    """
    grower, lot = create_routed_lot(grower_id=grower_id, route=route, **lot_kwargs)
    run = create_completed_run(
        lot["id"],
        kernel_out_lbs=kernel_out_lbs,
        shell_out_lbs=shell_out_lbs,
        hull_out_lbs=hull_out_lbs,
    )
    if record_grade:
        record_kernel_grade(
            lot["id"], edible_kernel_pct=edible_kernel_pct, size_spec=size_spec
        )
    return {"grower": grower, "lot": get_lot(lot["id"]), "run": run}


# ---------------------------------------------------------------------------
# Tier 5: storage / shipments
# ---------------------------------------------------------------------------

def create_placement(bin_id, lot_id, product_form="KERNEL", quantity_lbs=1000):
    payload = create_placement_payload(
        bin_id=bin_id, lot_id=lot_id, product_form=product_form, quantity_lbs=quantity_lbs
    )
    resp = api_client.create_placement(payload, make_operator_headers())
    return get_success_data(resp)


def setup_bin_with_stored_placement(bin_capacity_lbs=5000,
                                    allowed_product_forms=("KERNEL",),
                                    placement_quantity=1000,
                                    product_form="KERNEL",
                                    **processed_lot_kwargs):
    """Processed lot + bin + one STORED placement.

    Returns dict with keys: grower, lot, run, bin, placement.
    """
    processed = create_processed_lot(**processed_lot_kwargs)
    bin_ = create_bin(
        capacity_lbs=bin_capacity_lbs,
        allowed_product_forms=list(allowed_product_forms),
    )
    placement = create_placement(
        bin_["id"], processed["lot"]["id"],
        product_form=product_form, quantity_lbs=placement_quantity,
    )
    processed.update({"bin": bin_, "placement": placement})
    return processed


def setup_planned_shipment(required_qty_lbs=10000, shipment_quantity=1000,
                           contract_size_spec="SPEC_23_25",
                           contract_product_form="KERNEL",
                           **storage_kwargs):
    """Storage scenario + buyer + OPEN contract + one PLANNED shipment.

    Returns dict with keys: grower, lot, run, bin, placement, buyer, contract, shipment.
    """
    scenario = setup_bin_with_stored_placement(**storage_kwargs)
    buyer = create_buyer()
    contract = create_contract(
        buyer["id"],
        product_form=contract_product_form,
        size_spec=contract_size_spec,
        required_qty_lbs=required_qty_lbs,
    )
    resp = api_client.create_shipment(
        {
            "contract_id": contract["id"],
            "bin_id": scenario["bin"]["id"],
            "quantity_lbs": shipment_quantity,
            "expected_contract_version": contract["version"],
        },
        make_operator_headers(),
    )
    shipment = get_success_data(resp)
    scenario.update({"buyer": buyer, "contract": contract, "shipment": shipment})
    return scenario


# ---------------------------------------------------------------------------
# Tier 6: settlement chains
# ---------------------------------------------------------------------------

def setup_settlement_draft(grower_overrides=None, lot_kwargs=None,
                           run_outputs=None, grade_overrides=None):
    """Processed lot with KERNEL_GRADE + DRAFT settlement.

    Returns dict with keys: grower, lot, run, settlement.
    """
    grower_overrides = dict(grower_overrides or {})
    lot_kwargs = dict(lot_kwargs or {})
    run_outputs = dict(run_outputs or {})
    grade_overrides = dict(grade_overrides or {})
    grower = create_grower(**grower_overrides)
    processed = create_processed_lot(
        grower_id=grower["id"],
        kernel_out_lbs=run_outputs.get("kernel_out_lbs", 2400),
        shell_out_lbs=run_outputs.get("shell_out_lbs", 1300),
        hull_out_lbs=run_outputs.get("hull_out_lbs", 900),
        edible_kernel_pct=grade_overrides.get("edible_kernel_pct", 0.80),
        size_spec=grade_overrides.get("size_spec", "SPEC_23_25"),
        **lot_kwargs,
    )
    settlement = get_success_data(
        api_client.create_settlement(
            {"lot_id": processed["lot"]["id"]}, make_admin_headers()
        )
    )
    # create_processed_lot() leaves "grower" as None when a grower_id is passed
    # in; this helper created the grower itself, so restore the real record.
    processed["grower"] = grower
    processed["settlement"] = settlement
    return processed
