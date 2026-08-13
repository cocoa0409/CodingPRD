"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. All callers are responsible for their own assertions.

Identity threading: the Grower role is entity-backed — every Grower-role call
passes make_grower_headers(grower["id"]). ShellerRep calls anchor on the
contract's sheller_ref.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_TEST_CLOCK
from .factories import (
    create_aflatoxin_certificate_payload,
    create_buying_point_payload,
    create_delivery_call_payload,
    create_discount_schedule_payload,
    create_dryer_booking_payload,
    create_dryer_payload,
    create_grade_sheet_payload,
    create_grower_payload,
    create_load_payload,
    create_loan_pledge_payload,
    create_quota_history_payload,
    create_sheller_contract_payload,
    create_storage_receipt_payload,
    create_warehouse_payload,
    compute_settlement_payload,
)
from .test_users import (
    TEST_USERS,
    make_clerk_headers,
    make_grower_headers,
    make_inspector_headers,
    make_lab_technician_headers,
    make_sheller_rep_headers,
)

ADMIN = TEST_USERS["admin_headers"]
CLERK_1 = TEST_USERS["clerk_1_headers"]
CLERK_2 = TEST_USERS["clerk_2_headers"]
CLERK_3 = TEST_USERS["clerk_3_headers"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError:
        _fail(step, resp)


# ---------------------------------------------------------------------------
# Tier 1 — primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_TEST_CLOCK):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return _ok("set_clock", resp)


def setup_buying_point(clock=DEFAULT_TEST_CLOCK, **overrides):
    """Set the logical clock (unless None) and create a buying point."""
    if clock is not None:
        set_clock(clock)
    resp = api_client.create_buying_point(create_buying_point_payload(**overrides),
                                          ADMIN)
    return _ok("create_buying_point", resp)


def get_buying_point(bp_id):
    resp = api_client.get_buying_point(bp_id, ADMIN)
    return _ok("get_buying_point", resp)


def setup_active_schedule(**overrides):
    """Create the FALL-2026 discount schedule and activate it."""
    resp = api_client.create_discount_schedule(
        create_discount_schedule_payload(**overrides), ADMIN)
    schedule = _ok("create_discount_schedule", resp)
    resp = api_client.activate_discount_schedule(schedule["id"], ADMIN)
    return _ok("activate_discount_schedule", resp)


def setup_grower(name="Grower One", farm_number="F-1001", quota_tons=None,
                 crop_year=2026):
    """Register a grower; optionally record a quota history. Returns grower."""
    resp = api_client.create_grower(
        create_grower_payload(name=name, farm_number=farm_number), ADMIN)
    grower = _ok("create_grower", resp)
    if quota_tons is not None:
        resp = api_client.create_quota_history(
            create_quota_history_payload(grower_id=grower["id"],
                                         crop_year=crop_year,
                                         quota_tons=quota_tons), ADMIN)
        _ok("create_quota_history", resp)
    return grower


def add_warehouse(bp_id, name="WH-G", compartment="GENERAL", capacity_tons=2000):
    resp = api_client.create_warehouse(
        create_warehouse_payload(buying_point_id=bp_id, name=name,
                                 compartment=compartment,
                                 capacity_tons=capacity_tons), ADMIN)
    return _ok("create_warehouse", resp)


def add_dryer(bp_id, name="D1", cycle_capacity_tons=12, cycle_hours=6):
    resp = api_client.create_dryer(
        create_dryer_payload(buying_point_id=bp_id, name=name,
                             cycle_capacity_tons=cycle_capacity_tons,
                             cycle_hours=cycle_hours), ADMIN)
    return _ok("create_dryer", resp)


def report_load(grower_id, crop_year=2026, as_admin=False):
    """Report a load. Grower-role path uses the grower's own identity."""
    headers = ADMIN if as_admin else make_grower_headers(grower_id)
    resp = api_client.create_load(
        create_load_payload(grower_id=grower_id, crop_year=crop_year), headers)
    return _ok("create_load", resp)


def get_load(load_id):
    resp = api_client.get_load(load_id, ADMIN)
    return _ok("get_load", resp)


def weigh_load(load_id, gross_tons):
    resp = api_client.weigh_load(load_id, {"gross_tons": gross_tons}, ADMIN)
    return _ok("weigh_load", resp)


def create_sheet(load_id, load_version, moisture_pct=9.2, foreign_material_pct=5.5,
                 damage_pct=2.0, lsk_pct=1.0, inspector="insp-1"):
    resp = api_client.create_grade_sheet(
        load_id,
        create_grade_sheet_payload(
            load_version, moisture_pct=moisture_pct,
            foreign_material_pct=foreign_material_pct, damage_pct=damage_pct,
            lsk_pct=lsk_pct),
        make_inspector_headers(inspector))
    return _ok("create_grade_sheet", resp)


def finalize_sheet(sheet_id, inspector="insp-1"):
    resp = api_client.finalize_grade_sheet(sheet_id,
                                           make_inspector_headers(inspector))
    return _ok("finalize_grade_sheet", resp)


def grade_load(load_id, load_version, moisture_pct=9.2, foreign_material_pct=5.5,
               damage_pct=2.0, lsk_pct=1.0, inspector="insp-1"):
    """Create + finalize a grade sheet. Returns the FINALIZED sheet."""
    sheet = create_sheet(load_id, load_version, moisture_pct,
                         foreign_material_pct, damage_pct, lsk_pct, inspector)
    return finalize_sheet(sheet["id"], inspector)


def draw_certificate(load_id, sample_ref="SAMP-A1", tech="lab-1"):
    resp = api_client.create_aflatoxin_certificate(
        load_id, create_aflatoxin_certificate_payload(sample_ref=sample_ref),
        make_lab_technician_headers(tech))
    return _ok("create_aflatoxin_certificate", resp)


def record_result(cert_id, result_ppb, tech="lab-1"):
    resp = api_client.record_aflatoxin_result(cert_id, {"result_ppb": result_ppb},
                                              make_lab_technician_headers(tech))
    return _ok("record_aflatoxin_result", resp)


def confirm_certificate(cert_id, tech="lab-2"):
    resp = api_client.confirm_aflatoxin_certificate(
        cert_id, make_lab_technician_headers(tech))
    return _ok("confirm_aflatoxin_certificate", resp)


def clear_aflatoxin(load_id, result_ppb=8.0, sample_ref="SAMP-A1",
                    recorder="lab-1", confirmer="lab-2"):
    """Draw a sample, record a result, confirm with a second technician.
    Returns the CONFIRMED certificate."""
    cert = draw_certificate(load_id, sample_ref, recorder)
    record_result(cert["id"], result_ppb, recorder)
    return confirm_certificate(cert["id"], confirmer)


def store_load(load_id, warehouse_id):
    resp = api_client.create_storage_receipt(
        create_storage_receipt_payload(load_id=load_id, warehouse_id=warehouse_id),
        ADMIN)
    return _ok("create_storage_receipt", resp)


def get_storage_receipt(receipt_id):
    resp = api_client.get_storage_receipt(receipt_id, ADMIN)
    return _ok("get_storage_receipt", resp)


def get_warehouse(warehouse_id):
    resp = api_client.get_warehouse(warehouse_id, ADMIN)
    return _ok("get_warehouse", resp)


def get_grower(grower_id):
    resp = api_client.get_grower(grower_id, ADMIN)
    return _ok("get_grower", resp)


def get_quota_history(quota_history_id):
    resp = api_client.get_quota_history(quota_history_id, ADMIN)
    return _ok("get_quota_history", resp)


# ---------------------------------------------------------------------------
# Tier 2 — graded / stored load pipelines
# ---------------------------------------------------------------------------

def setup_graded_load(grower_id, gross_tons=25.0, moisture_pct=9.2,
                      foreign_material_pct=5.5, damage_pct=2.0, lsk_pct=1.0,
                      crop_year=2026):
    """Report + weigh + grade-finalize. Returns (load, sheet)."""
    load = report_load(grower_id, crop_year)
    weighed = weigh_load(load["id"], gross_tons)
    sheet = grade_load(load["id"], weighed["version"], moisture_pct,
                       foreign_material_pct, damage_pct, lsk_pct)
    return get_load(load["id"]), sheet


def setup_cleared_load(grower_id, result_ppb=8.0, **grade_kwargs):
    """Graded load + aflatoxin certificate CONFIRMED. Returns (load, sheet, cert)."""
    load, sheet = setup_graded_load(grower_id, **grade_kwargs)
    cert = clear_aflatoxin(load["id"], result_ppb)
    return get_load(load["id"]), sheet, cert


def setup_stored_load(grower_id, warehouse_id, **kwargs):
    """Full intake pipeline through storage. Returns (load, sheet, cert, receipt)."""
    load, sheet, cert = setup_cleared_load(grower_id, **kwargs)
    receipt = store_load(load["id"], warehouse_id)
    return get_load(load["id"]), sheet, cert, receipt


# ---------------------------------------------------------------------------
# Tier 3 — sheller contracts / delivery calls
# ---------------------------------------------------------------------------

def create_active_contract(bp_id, sheller_ref="sheller-acme", total_units_tons=40.0,
                           **overrides):
    resp = api_client.create_sheller_contract(
        create_sheller_contract_payload(buying_point_id=bp_id,
                                        sheller_ref=sheller_ref,
                                        total_units_tons=total_units_tons,
                                        **overrides), ADMIN)
    contract = _ok("create_sheller_contract", resp)
    resp = api_client.activate_sheller_contract(contract["id"], ADMIN)
    return _ok("activate_sheller_contract", resp)


def issue_call(contract_id, requested_tons=20.0, sheller_ref="sheller-acme",
               dock_window_start="2026-09-10T08:00:00Z",
               dock_window_end="2026-09-10T12:00:00Z"):
    resp = api_client.create_delivery_call(
        create_delivery_call_payload(contract_id=contract_id,
                                     requested_tons=requested_tons,
                                     dock_window_start=dock_window_start,
                                     dock_window_end=dock_window_end),
        make_sheller_rep_headers(sheller_ref))
    return _ok("create_delivery_call", resp)


def allocate_call(call_id, expected_version):
    resp = api_client.allocate_delivery_call(
        call_id, {"expected_delivery_call_version": expected_version}, ADMIN)
    return _ok("allocate_delivery_call", resp)


def deliver_call(call_id):
    resp = api_client.deliver_delivery_call(call_id, ADMIN)
    return _ok("deliver_delivery_call", resp)


def reconcile_call(call_id, shelled_kernel_tons, hull_tons,
                   sheller_ref="sheller-acme"):
    resp = api_client.reconcile_delivery_call(
        call_id, {"shelled_kernel_tons": shelled_kernel_tons,
                  "hull_tons": hull_tons},
        make_sheller_rep_headers(sheller_ref))
    return _ok("reconcile_delivery_call", resp)


def list_lines_for_call(call_id):
    resp = api_client.list_allocation_lines(ADMIN,
                                            params={"delivery_call_id": call_id})
    data, _meta = resp.json()["data"], resp.json()["meta"]
    assert resp.status_code == 200, f"list allocation lines failed: {resp.text}"
    return data


def list_hull_lots_for_call(call_id):
    resp = api_client.list_hull_lots(ADMIN, params={"delivery_call_id": call_id})
    assert resp.status_code == 200, f"list hull lots failed: {resp.text}"
    return resp.json()["data"]


def sell_hull_lot(lot_id, sale_price_cents_per_ton=4000):
    resp = api_client.list_hull_lot_for_sale(
        lot_id, {"sale_price_cents_per_ton": sale_price_cents_per_ton}, ADMIN)
    _ok("list_hull_lot_for_sale", resp)
    resp = api_client.sell_hull_lot(lot_id, ADMIN)
    return _ok("sell_hull_lot", resp)


def setup_reconciled_call(grower, warehouse, bp_id, gross_tons=25.0,
                          requested_tons=20.0, contract_total=40.0,
                          shelled_kernel_tons=16.0, hull_tons=3.8,
                          quota_tons=100, sheller_ref="sheller-acme"):
    """Stored load + ACTIVE contract + call ALLOCATED/DELIVERED/RECONCILED.
    Returns dict with all participants."""
    load, sheet, cert, receipt = setup_stored_load(grower["id"], warehouse["id"],
                                                   gross_tons=gross_tons)
    contract = create_active_contract(bp_id, sheller_ref=sheller_ref,
                                      total_units_tons=contract_total)
    call = issue_call(contract["id"], requested_tons, sheller_ref)
    allocated = allocate_call(call["id"], call["version"])
    deliver_call(call["id"])
    reconciled = reconcile_call(call["id"], shelled_kernel_tons, hull_tons,
                                sheller_ref)
    return {
        "load": load, "sheet": sheet, "cert": cert, "receipt": receipt,
        "contract": contract, "call": reconciled,
    }


# ---------------------------------------------------------------------------
# Tier 4 — loans
# ---------------------------------------------------------------------------

def pledge_full_receipt(grower_id, receipt_id, pledged_tons=25.0,
                        maturity_date="2026-12-01T00:00:00Z", as_admin=False):
    headers = ADMIN if as_admin else make_grower_headers(grower_id)
    resp = api_client.create_loan_pledge(
        create_loan_pledge_payload(grower_id=grower_id,
                                   storage_receipt_id=receipt_id,
                                   pledged_tons=pledged_tons,
                                   maturity_date=maturity_date), headers)
    return _ok("create_loan_pledge", resp)


def get_loan_pledge(pledge_id):
    resp = api_client.get_loan_pledge(pledge_id, ADMIN)
    return _ok("get_loan_pledge", resp)


# ---------------------------------------------------------------------------
# Tier 5 — settlements
# ---------------------------------------------------------------------------

def compute_settlement(grower_id, expected_grower_version, clerk="clerk-1"):
    resp = api_client.compute_settlement(
        grower_id, compute_settlement_payload(expected_grower_version),
        make_clerk_headers(clerk))
    return _ok("compute_settlement", resp)


def get_settlement(settlement_id):
    resp = api_client.get_settlement(settlement_id, ADMIN)
    return _ok("get_settlement", resp)


def approve_settlement(settlement_id, clerk="clerk-2"):
    resp = api_client.approve_settlement(settlement_id, make_clerk_headers(clerk))
    return _ok("approve_settlement", resp)


def pay_settlement(settlement_id, clerk="clerk-3"):
    resp = api_client.pay_settlement(settlement_id, make_clerk_headers(clerk))
    return _ok("pay_settlement", resp)


def setup_settlement_foundation(quota_tons=100, with_dryer=False,
                                warehouse_capacity=2000, clock=DEFAULT_TEST_CLOCK):
    """BP + FALL-2026 ACTIVE schedule + grower with quota + WH-G warehouse.
    Returns dict(bp, grower, warehouse, schedule[, dryer])."""
    bp = setup_buying_point(clock=clock)
    schedule = setup_active_schedule()
    grower = setup_grower(quota_tons=quota_tons)
    warehouse = add_warehouse(bp["id"], capacity_tons=warehouse_capacity)
    out = {"bp": bp, "grower": grower, "warehouse": warehouse,
           "schedule": schedule}
    if with_dryer:
        out["dryer"] = add_dryer(bp["id"])
    return out


def setup_computed_settlement(quota_tons=100, clerk="clerk-1", **store_kwargs):
    """Foundation + one stored load + a COMPUTED settlement for the grower.
    Returns dict(foundation..., load, sheet, cert, receipt, settlement)."""
    f = setup_settlement_foundation(quota_tons=quota_tons)
    load, sheet, cert, receipt = setup_stored_load(
        f["grower"]["id"], f["warehouse"]["id"], **store_kwargs)
    settlement = compute_settlement(f["grower"]["id"],
                                    f["grower"]["version"], clerk)
    return {**f, "load": load, "sheet": sheet, "cert": cert,
            "receipt": receipt, "settlement": settlement}
