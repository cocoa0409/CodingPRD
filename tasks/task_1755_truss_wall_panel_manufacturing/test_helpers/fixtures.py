"""Composite setup helpers.

Every fixture builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup calls use get_success_data so a
failed precondition surfaces as a clear "Setup step failed" error.

Identity threading: DesignEngineer calls use make_design_engineer_headers with
the acting Engineer's id; CustomerContact calls use make_customer_contact_headers
with the owning CustomerAccount's id (both roles are entity-backed).
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_customer_payload,
    create_engineer_payload,
    create_job_payload,
    create_design_payload,
    cut_list_line_payload,
    create_cut_list_payload,
    create_jig_payload,
    create_lumber_lot_payload,
    create_plate_lot_payload,
    create_lumber_reservation_payload,
    create_plate_reservation_payload,
    create_crane_payload,
    create_crane_slot_payload,
    create_batch_payload,
    create_load_payload,
    create_bundle_payload,
    create_claim_payload,
    create_change_order_payload,
)
from .test_users import (
    TEST_USERS,
    make_design_engineer_headers,
    make_customer_contact_headers,
    make_claims_adjuster_headers,
)

PM = TEST_USERS["plant_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
IM = TEST_USERS["inventory_manager_headers"]
SFL = TEST_USERS["shop_floor_lead_headers"]
SC = TEST_USERS["shipping_coordinator_headers"]
ADJ1 = make_claims_adjuster_headers("adj-1")
ADJ2 = make_claims_adjuster_headers("adj-2")

# Standard cut-list line specs for a ROOF_TRUSS design (totals 198.67 bf / 15 pcs / 280 plates).
STANDARD_LINES = [
    cut_list_line_payload("TC-1", "L2X6", 12.0, 10),   # required 126.00 bf
    cut_list_line_payload("BC-1", "L2X4", 20.0, 5),    # required 72.67 bf
]
WALL_PANEL_LINES = [
    cut_list_line_payload("PS-1", "L2X4", 10.0, 20),   # required 140.01 bf
]


# ---------------------------------------------------------------------------
# Fresh reads (version-safe re-reads for OCC-guarded calls)
# ---------------------------------------------------------------------------

def job_fresh(job_id):
    return get_success_data(api.get_job(job_id, PM))


def lot_fresh(lot_id):
    return get_success_data(api.get_inventory_lot(lot_id, IM))


def crane_fresh(crane_id):
    return get_success_data(api.get_crane(crane_id, PM))


def load_fresh(load_id):
    return get_success_data(api.get_load(load_id, PM))


def batch_fresh(batch_id):
    return get_success_data(api.get_batch(batch_id, PM))


def design_fresh(design_id):
    return get_success_data(api.get_design(design_id, PM))


def cut_list_fresh(cut_list_id):
    return get_success_data(api.get_cut_list(cut_list_id, PM))


def line_fresh(line_id):
    return get_success_data(api.get_cut_list_line(line_id, PM))


def bundle_fresh(bundle_id):
    return get_success_data(api.get_bundle(bundle_id, PM))


def claim_fresh(claim_id):
    return get_success_data(api.get_claim(claim_id, PM))


def change_order_fresh(order_id):
    return get_success_data(api.get_change_order(order_id, PM))


def reservation_fresh(reservation_id):
    return get_success_data(api.get_reservation(reservation_id, IM))


def set_clock(iso):
    return get_success_data(api.set_clock({"to_iso8601": iso}, PM))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creators
# ---------------------------------------------------------------------------

def make_customer(**overrides):
    return get_success_data(api.create_customer_account(create_customer_payload(**overrides), PM))


def make_engineer(suffix="1", **overrides):
    payload = create_engineer_payload(
        full_name=f"E{suffix}", license_number=f"PE-{suffix}", **overrides
    )
    return get_success_data(api.create_engineer(payload, PM))


def make_engineer_pair():
    """Two GA-licensed TRUSS_AND_PANEL engineers with long-lived licenses."""
    return make_engineer("1"), make_engineer("2")


def make_job(customer, confirm=False, **overrides):
    job = get_success_data(api.create_job(create_job_payload(customer["id"], **overrides), PM))
    if confirm:
        job = get_success_data(api.confirm_job(job["id"], PM))
    return job


def make_jig(code="JIG-ROOF-A", ctype="ROOF_TRUSS", plate_class="P20", changeover=None):
    payload = create_jig_payload(
        setup_code=code,
        component_type_supported=ctype,
        plate_class=plate_class,
        changeover_minutes_from=changeover if changeover is not None else {},
    )
    return get_success_data(api.create_jig_setup(payload, PM))


def make_crane(**overrides):
    return get_success_data(api.create_crane(create_crane_payload(**overrides), PM))


def make_design(job_id, engineer, **overrides):
    """Create a DRAFT design; reads the job fresh for the OCC version field."""
    job = job_fresh(job_id)
    payload = create_design_payload(job["version"], **overrides)
    return get_success_data(
        api.create_design(job_id, payload, make_design_engineer_headers(engineer["id"]))
    )


def submit_design(design_id, engineer):
    return get_success_data(
        api.transition_design(design_id, {"to_state": "SEAL_REQUESTED"},
                              make_design_engineer_headers(engineer["id"]))
    )


def seal_submitted_design(design_id, sealer):
    return get_success_data(
        api.transition_design(design_id, {"to_state": "SEALED"},
                              make_design_engineer_headers(sealer["id"]))
    )


def make_sealed_design(job_id, submitter, sealer, **overrides):
    design = make_design(job_id, submitter, **overrides)
    submit_design(design["id"], submitter)
    return design_fresh(design["id"]) if sealer is None else seal_submitted_design(design["id"], sealer)


def explode_cut_list(design_id, jig_id, lines):
    """Explode a design into a cut list; returns (cut_list, {member_label: line})."""
    cut_list = get_success_data(
        api.create_cut_list(design_id, create_cut_list_payload(jig_id, lines), PP)
    )
    return cut_list, lines_of(cut_list["id"])


def lines_of(cut_list_id):
    data, _meta = _list_all(api.list_cut_list_lines(PP, params={"cut_list_id": cut_list_id, "limit": 100}))
    return {line["member_label"]: line for line in data}


def _list_all(response):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)


def make_lumber_lot(**overrides):
    return get_success_data(api.create_inventory_lot(create_lumber_lot_payload(**overrides), IM))


def make_plate_lot(**overrides):
    return get_success_data(api.create_inventory_lot(create_plate_lot_payload(**overrides), IM))


def make_standard_lots():
    """lot6: L2X6 MSR 500.0 bf; lot4: L2X4 MSR 400.0 bf; plot: P20 x1000 plates."""
    lot6 = make_lumber_lot(lumber_dimension="L2X6", received_board_feet=500.0)
    lot4 = make_lumber_lot(lumber_dimension="L2X4", received_board_feet=400.0)
    plot = make_plate_lot(received_plates=1000)
    return SimpleNamespace(lot6=lot6, lot4=lot4, plot=plot)


def reserve_lumber(lot_id, line_id, bf):
    lot = lot_fresh(lot_id)
    return get_success_data(api.create_reservation(
        create_lumber_reservation_payload(lot_id, lot["version"], line_id, bf), PP
    ))


def reserve_plates(lot_id, cut_list_id, plates):
    lot = lot_fresh(lot_id)
    return get_success_data(api.create_reservation(
        create_plate_reservation_payload(lot_id, lot["version"], cut_list_id, plates), PP
    ))


def reserve_standard_cl1(lots, lines, cut_list_id):
    """Full coverage for the standard two-line list: 126.00 + 72.67 bf, 280 plates."""
    r1 = reserve_lumber(lots.lot6["id"], lines["TC-1"]["id"], 126.00)
    r2 = reserve_lumber(lots.lot4["id"], lines["BC-1"]["id"], 72.67)
    r3 = reserve_plates(lots.plot["id"], cut_list_id, 280)
    return SimpleNamespace(r1=r1, r2=r2, r3=r3)


def book_slot(crane_id, purpose, start_at, end_at, **overrides):
    crane = crane_fresh(crane_id)
    return get_success_data(api.create_crane_slot(
        create_crane_slot_payload(crane_id, purpose, start_at, end_at, crane["version"], **overrides),
        PP,
    ))


def complete_slot(slot_id):
    return get_success_data(api.transition_crane_slot(slot_id, {"to_state": "COMPLETED"}, PP))


def cancel_slot(slot_id):
    return get_success_data(api.transition_crane_slot(slot_id, {"to_state": "CANCELLED"}, PP))


def make_batch(job_id, cut_list_id, jig_id, completion="2026-08-15T00:00:00Z"):
    return get_success_data(
        api.create_batch(job_id, create_batch_payload(cut_list_id, jig_id, completion), PP)
    )


def transition_batch(batch_id, to_state):
    return get_success_data(api.transition_batch(batch_id, {"to_state": to_state}, SFL))


def drive_batch_to_staged(batch_id, lines, crane_id, slot_start="2026-08-12T10:00:00Z", slot_end="2026-08-12T12:00:00Z"):
    """Book + complete a BUILD_PICK slot, then CUTTING -> ASSEMBLY -> BUILT -> QC_PASSED -> STAGED."""
    slot = book_slot(crane_id, "BUILD_PICK", slot_start, slot_end, production_batch_id=batch_id)
    complete_slot(slot["id"])
    transition_batch(batch_id, "CUTTING")
    for line in lines:
        get_success_data(api.mark_cut_line(line["id"], SFL))
    transition_batch(batch_id, "ASSEMBLY")
    transition_batch(batch_id, "BUILT")
    transition_batch(batch_id, "QC_PASSED")
    transition_batch(batch_id, "STAGED")
    return batch_fresh(batch_id), slot


def make_load(job_id, scheduled_date="2026-08-21T00:00:00Z", planned_weight_est_lbs=8000):
    return get_success_data(
        api.create_load(job_id, create_load_payload(scheduled_date, planned_weight_est_lbs), SC)
    )


def transition_load(load_id, to_state, **fields):
    payload = {"to_state": to_state}
    payload.update(fields)
    return get_success_data(api.transition_load(load_id, payload, SC))


def make_bundle(load_id, batch_id, stack_position, weight_lbs):
    return get_success_data(
        api.create_bundle(load_id, create_bundle_payload(batch_id, stack_position, weight_lbs), SC)
    )


def file_claim(load_id, bundle_id, customer, **overrides):
    return get_success_data(api.create_claim(
        load_id, create_claim_payload(bundle_id, **overrides),
        make_customer_contact_headers(customer["id"]),
    ))


# ---------------------------------------------------------------------------
# Tier 2/3: composite preambles
# ---------------------------------------------------------------------------

def setup_confirmed_job(job_name="Job", contract=1000000, customer_overrides=None):
    customer = make_customer(**(customer_overrides or {}))
    eng1, eng2 = make_engineer_pair()
    job = make_job(customer, confirm=True, job_name=job_name, contracted_value_cents=contract)
    return SimpleNamespace(customer=customer, eng1=eng1, eng2=eng2, job=job)


def setup_sealed_roof_design(base=None, job_name="Job", contract=1000000, **design_overrides):
    """Confirmed job + SEALED ROOF_TRUSS design TR-01 (submitted by eng1, sealed by eng2)."""
    if base is None:
        base = setup_confirmed_job(job_name=job_name, contract=contract)
    dsg = make_sealed_design(base.job["id"], base.eng1, base.eng2, **design_overrides)
    base.dsg1 = dsg
    return base


def setup_released_cl1(job_name="Job", contract=1000000, with_lots=True):
    """Confirmed job + sealed TR-01 + standard cut list exploded and RELEASED (job IN_PRODUCTION)."""
    ns = setup_sealed_roof_design(job_name=job_name, contract=contract)
    ns.jig_roof = make_jig()
    ns.cl1, ns.lines = explode_cut_list(ns.dsg1["id"], ns.jig_roof["id"], STANDARD_LINES)
    ns.cl1 = get_success_data(api.release_cut_list(ns.cl1["id"], PP))
    ns.job = job_fresh(ns.job["id"])
    if with_lots:
        ns.lots = make_standard_lots()
    return ns


def setup_production_preamble(job_name="Job", contract=1000000, crane_overrides=None):
    """Full chain through bat1 STAGED: sealed design, RELEASED cut list, full
    coverage reservations, batch driven CUTTING -> ... -> STAGED via a completed
    BUILD_PICK slot. Job is IN_PRODUCTION."""
    ns = setup_released_cl1(job_name=job_name, contract=contract)
    ns.crane = make_crane(**(crane_overrides or {}))
    ns.rsv = reserve_standard_cl1(ns.lots, ns.lines, ns.cl1["id"])
    ns.bat1 = make_batch(ns.job["id"], ns.cl1["id"], ns.jig_roof["id"])
    ns.bat1, ns.slot_a = drive_batch_to_staged(
        ns.bat1["id"], [ns.lines["TC-1"], ns.lines["BC-1"]], ns.crane["id"]
    )
    ns.job = job_fresh(ns.job["id"])
    return ns


def setup_load_loading(job_name="Job", planned_est=8000, bundle_weight=9000):
    """Production preamble + load with a 9000-lb bundle, driven STAGED -> LOADING
    (completed LOAD_PICK slot D). Clock left at 2026-08-19 after LOADING."""
    ns = setup_production_preamble(job_name=job_name)
    ns.load = make_load(ns.job["id"], planned_weight_est_lbs=planned_est)
    ns.slot_d = book_slot(ns.crane["id"], "LOAD_PICK", "2026-08-20T13:00:00Z",
                          "2026-08-20T14:00:00Z", delivery_load_id=ns.load["id"])
    set_clock("2026-08-19T00:00:00Z")
    ns.bundle = make_bundle(ns.load["id"], ns.bat1["id"], 1, bundle_weight)
    transition_load(ns.load["id"], "STAGED")
    complete_slot(ns.slot_d["id"])
    transition_load(ns.load["id"], "LOADING")
    ns.load = load_fresh(ns.load["id"])
    ns.job = job_fresh(ns.job["id"])
    return ns


def setup_load_dispatched(job_name="Job", planned_est=8000, bundle_weight=9000):
    """As setup_load_loading, then DISPATCHED at clock 2026-08-20. Job SHIPPING."""
    ns = setup_load_loading(job_name=job_name, planned_est=planned_est, bundle_weight=bundle_weight)
    set_clock("2026-08-20T00:00:00Z")
    transition_load(ns.load["id"], "DISPATCHED")
    ns.load = load_fresh(ns.load["id"])
    ns.job = job_fresh(ns.job["id"])
    ns.bat1 = batch_fresh(ns.bat1["id"])
    ns.bundle = bundle_fresh(ns.bundle["id"])
    return ns


def setup_delivered_load(job_name="Job", planned_est=8000, bundle_weight=9000):
    """As setup_load_dispatched, then DELIVERED."""
    ns = setup_load_dispatched(job_name=job_name, planned_est=planned_est, bundle_weight=bundle_weight)
    transition_load(ns.load["id"], "DELIVERED")
    ns.load = load_fresh(ns.load["id"])
    ns.bundle = bundle_fresh(ns.bundle["id"])
    return ns


# ---------------------------------------------------------------------------
# Claims fixtures
# ---------------------------------------------------------------------------

def setup_claim_preamble(triage=True, claimed=500000, job_name="Claim Job"):
    """Delivered load + claim filed by the owning customer (load CLAIM_HOLD);
    optionally triaged by adjuster adj-1."""
    ns = setup_delivered_load(job_name=job_name)
    ns.claim = file_claim(ns.load["id"], ns.bundle["id"], ns.customer, claimed_amount_cents=claimed)
    ns.load = load_fresh(ns.load["id"])
    if triage:
        ns.claim = get_success_data(api.triage_claim(ns.claim["id"], ADJ1))
    return ns


def setup_claim_approved_credit():
    """Claim TRIAGED by adj-1 then APPROVE_CREDIT 0.30 decided by adj-2 (cap 50661)."""
    ns = setup_claim_preamble()
    ns.claim = get_success_data(api.decide_claim(
        ns.claim["id"], {"decision": "APPROVE_CREDIT", "damage_pct": 0.30}, ADJ2
    ))
    ns.load = load_fresh(ns.load["id"])
    return ns


def setup_claim_rebuild_in_progress():
    """Claim decided APPROVE_REBUILD 0.30 by adj-2: bundle DAMAGED, rebuild cut-list
    clone + rebuild batch created, claim REBUILD_IN_PROGRESS."""
    ns = setup_claim_preamble()
    ns.claim = get_success_data(api.decide_claim(
        ns.claim["id"], {"decision": "APPROVE_REBUILD", "damage_pct": 0.30}, ADJ2
    ))
    clones, _ = _list_all(api.list_cut_lists(PP, params={"rebuild_for_claim_id": ns.claim["id"]}))
    ns.cl_clone = clones[0] if clones else None
    rb, _ = _list_all(api.list_batches(PP, params={"source_claim_id": ns.claim["id"]}))
    ns.bat_r = rb[0] if rb else None
    ns.load = load_fresh(ns.load["id"])
    ns.bundle = bundle_fresh(ns.bundle["id"])
    return ns


def setup_claim_fork():
    """Two claims on one delivered bundle: c1 TRIAGED by adj-1 then APPROVE_CREDIT
    0.30 by adj-2; c2 filed afterwards and TRIAGED by adj-1."""
    ns = setup_delivered_load(job_name="Fork Job")
    ns.c1 = file_claim(ns.load["id"], ns.bundle["id"], ns.customer, claimed_amount_cents=500000)
    ns.c1 = get_success_data(api.triage_claim(ns.c1["id"], ADJ1))
    ns.c1 = get_success_data(api.decide_claim(
        ns.c1["id"], {"decision": "APPROVE_CREDIT", "damage_pct": 0.30}, ADJ2
    ))
    ns.c2 = file_claim(ns.load["id"], ns.bundle["id"], ns.customer,
                       claim_type="SHORT_SHIPMENT", description="alleged short bundle count",
                       claimed_amount_cents=75000)
    ns.c2 = get_success_data(api.triage_claim(ns.c2["id"], ADJ1))
    ns.load = load_fresh(ns.load["id"])
    return ns


# ---------------------------------------------------------------------------
# Mega chain: two designs, two batches, one load, design change after cut
# ---------------------------------------------------------------------------

def setup_mega_chain_prefix():
    """Job Mega: bat1 (roof) STAGED, bat2 (wall panel) STAGED, load1 STAGED at
    clock 2026-08-10 with bundles bnd1 (12000 lbs) and bnd2 (8160 lbs)."""
    customer = make_customer(storage_free_days=2, storage_daily_fee_cents=15000,
                             storage_fee_cap_cents=300000, max_drops_per_day=2)
    eng1, eng2 = make_engineer_pair()
    job = make_job(customer, confirm=True, job_name="Mega", contracted_value_cents=5000000)
    jig_roof = make_jig("JIG-ROOF-A", "ROOF_TRUSS", "P20", {"JIG-WALL-A": 45})
    jig_wall = make_jig("JIG-WALL-A", "WALL_PANEL", "P20", {"JIG-ROOF-A": 30})
    crane = make_crane()

    dsg1 = make_sealed_design(job["id"], eng1, eng2)  # TR-01 ROOF_TRUSS MSR P20 qty 10
    cl1, lines1 = explode_cut_list(dsg1["id"], jig_roof["id"], STANDARD_LINES)
    cl1 = get_success_data(api.release_cut_list(cl1["id"], PP))

    lots = make_standard_lots()
    reserve_standard_cl1(lots, lines1, cl1["id"])
    bat1 = make_batch(job["id"], cl1["id"], jig_roof["id"])
    bat1, slot_a = drive_batch_to_staged(bat1["id"], [lines1["TC-1"], lines1["BC-1"]], crane["id"])

    dsg2 = make_sealed_design(job["id"], eng1, eng2, component_ref="WP-01",
                              component_type="WALL_PANEL", span_ft=8.0, pitch_degrees=0.0,
                              design_load_psf=20.0, quantity_required=5)
    cl2, lines2 = explode_cut_list(dsg2["id"], jig_wall["id"], WALL_PANEL_LINES)
    cl2 = get_success_data(api.release_cut_list(cl2["id"], PP))
    reserve_lumber(lots.lot4["id"], lines2["PS-1"]["id"], 140.01)
    reserve_plates(lots.plot["id"], cl2["id"], 60)
    bat2 = make_batch(job["id"], cl2["id"], jig_wall["id"])
    bat2, slot_b = drive_batch_to_staged(
        bat2["id"], [lines2["PS-1"]], crane["id"],
        slot_start="2026-08-12T12:30:00Z", slot_end="2026-08-12T14:00:00Z",
    )

    load1 = make_load(job["id"], planned_weight_est_lbs=10000)
    slot_c = book_slot(crane["id"], "LOAD_PICK", "2026-08-20T09:00:00Z",
                       "2026-08-20T11:00:00Z", delivery_load_id=load1["id"])
    set_clock("2026-08-10T00:00:00Z")
    bnd1 = make_bundle(load1["id"], bat1["id"], 1, 12000)
    bnd2 = make_bundle(load1["id"], bat2["id"], 2, 8160)
    transition_load(load1["id"], "STAGED")

    return SimpleNamespace(
        customer=customer, eng1=eng1, eng2=eng2, job=job_fresh(job["id"]),
        jig_roof=jig_roof, jig_wall=jig_wall, crane=crane,
        dsg1=dsg1, cl1=cut_list_fresh(cl1["id"]), lines1=lines1,
        dsg2=dsg2, cl2=cut_list_fresh(cl2["id"]), lines2=lines2,
        lots=lots, bat1=batch_fresh(bat1["id"]), bat2=batch_fresh(bat2["id"]),
        slot_a=slot_a, slot_b=slot_b, slot_c=slot_c,
        load1=load_fresh(load1["id"]), bnd1=bnd1, bnd2=bnd2,
    )


def _mega_seal_r2_and_create_order(ns):
    """WP-01 revision 2 sealed; change order over r1 -> r2 created by the customer."""
    dsg2r2 = make_sealed_design(ns.job["id"], ns.eng1, ns.eng2, component_ref="WP-01",
                                component_type="WALL_PANEL", span_ft=8.0, pitch_degrees=0.0,
                                design_load_psf=25.0, quantity_required=5,
                                supersedes_design_id=ns.dsg2["id"])
    job = job_fresh(ns.job["id"])
    co1 = get_success_data(api.create_change_order(
        ns.job["id"],
        create_change_order_payload(ns.dsg2["id"], job["version"], new_design_id=dsg2r2["id"]),
        make_customer_contact_headers(ns.customer["id"]),
    ))
    ns.dsg2r2 = dsg2r2
    ns.co1 = co1
    return ns


def setup_mega_chain_approved():
    """Mega prefix + change order assessed (impact computed) and APPROVED."""
    ns = _mega_seal_r2_and_create_order(setup_mega_chain_prefix())
    ns.co1 = get_success_data(api.assess_change_order(ns.co1["id"], {}, PP))
    ns.co1 = get_success_data(api.approve_change_order(ns.co1["id"], PM))
    ns.job = job_fresh(ns.job["id"])
    return ns


def setup_mega_chain_delivered():
    """Mega chain through change-order apply, reconcile, re-stage at 2026-08-15,
    then LOADING -> DISPATCHED (clock 2026-08-21) -> DELIVERED."""
    ns = _mega_seal_r2_and_create_order(setup_mega_chain_prefix())
    get_success_data(api.assess_change_order(ns.co1["id"], {}, PP))
    get_success_data(api.approve_change_order(ns.co1["id"], PM))
    ns.co1 = get_success_data(api.apply_change_order(ns.co1["id"], PM))
    ns.cl2 = get_success_data(api.reconcile_cut_list(ns.cl2["id"], PP))
    set_clock("2026-08-15T00:00:00Z")
    transition_load(ns.load1["id"], "STAGED")
    complete_slot(ns.slot_c["id"])
    transition_load(ns.load1["id"], "LOADING")
    set_clock("2026-08-21T00:00:00Z")
    transition_load(ns.load1["id"], "DISPATCHED")
    transition_load(ns.load1["id"], "DELIVERED")
    ns.load1 = load_fresh(ns.load1["id"])
    ns.job = job_fresh(ns.job["id"])
    ns.dsg2 = design_fresh(ns.dsg2["id"])
    ns.cl2 = cut_list_fresh(ns.cl2["id"])
    ns.bat1 = batch_fresh(ns.bat1["id"])
    ns.bat2 = batch_fresh(ns.bat2["id"])
    ns.bnd1 = bundle_fresh(ns.bnd1["id"])
    ns.bnd2 = bundle_fresh(ns.bnd2["id"])
    return ns


# ---------------------------------------------------------------------------
# Two-load storage fixture
# ---------------------------------------------------------------------------

def setup_two_loads_delivered():
    """One STAGED batch referenced by two loads: loady STAGED at 2026-08-18,
    loadx STAGED at 2026-08-19, both DISPATCHED + DELIVERED at clock 2026-08-21."""
    ns = setup_production_preamble(job_name="Storage Job")
    ns.loadx = make_load(ns.job["id"], planned_weight_est_lbs=3000)
    ns.loady = make_load(ns.job["id"], planned_weight_est_lbs=3000)
    ns.slot_x = book_slot(ns.crane["id"], "LOAD_PICK", "2026-08-20T09:00:00Z",
                          "2026-08-20T10:00:00Z", delivery_load_id=ns.loadx["id"])
    ns.slot_y = book_slot(ns.crane["id"], "LOAD_PICK", "2026-08-20T10:30:00Z",
                          "2026-08-20T11:30:00Z", delivery_load_id=ns.loady["id"])
    ns.bx = make_bundle(ns.loadx["id"], ns.bat1["id"], 1, 3000)
    ns.by = make_bundle(ns.loady["id"], ns.bat1["id"], 1, 3000)
    set_clock("2026-08-18T00:00:00Z")
    transition_load(ns.loady["id"], "STAGED")
    set_clock("2026-08-19T00:00:00Z")
    transition_load(ns.loadx["id"], "STAGED")
    complete_slot(ns.slot_x["id"])
    complete_slot(ns.slot_y["id"])
    transition_load(ns.loadx["id"], "LOADING")
    transition_load(ns.loady["id"], "LOADING")
    set_clock("2026-08-21T00:00:00Z")
    transition_load(ns.loadx["id"], "DISPATCHED")
    transition_load(ns.loadx["id"], "DELIVERED")
    transition_load(ns.loady["id"], "DISPATCHED")
    transition_load(ns.loady["id"], "DELIVERED")
    ns.loadx = load_fresh(ns.loadx["id"])
    ns.loady = load_fresh(ns.loady["id"])
    ns.job = job_fresh(ns.job["id"])
    return ns


# ---------------------------------------------------------------------------
# Change-order request fixture
# ---------------------------------------------------------------------------

def setup_change_order_requested(by_customer=True):
    """Confirmed job + SEALED design + one REQUESTED change order against it."""
    ns = setup_sealed_roof_design(job_name="CO Job", contract=100000)
    job = job_fresh(ns.job["id"])
    headers = make_customer_contact_headers(ns.customer["id"]) if by_customer else PP
    ns.co1 = get_success_data(api.create_change_order(
        ns.job["id"], create_change_order_payload(ns.dsg1["id"], job["version"]), headers
    ))
    ns.job = job_fresh(ns.job["id"])
    return ns


# ---------------------------------------------------------------------------
# Additional targeted fixtures
# ---------------------------------------------------------------------------

def drive_batch_to_built(batch_id, lines, crane_id):
    """Book + complete a BUILD_PICK slot, then CUTTING -> mark lines -> ASSEMBLY -> BUILT."""
    slot = book_slot(crane_id, "BUILD_PICK", "2026-08-12T10:00:00Z", "2026-08-12T12:00:00Z",
                     production_batch_id=batch_id)
    complete_slot(slot["id"])
    transition_batch(batch_id, "CUTTING")
    for line in lines:
        get_success_data(api.mark_cut_line(line["id"], SFL))
    transition_batch(batch_id, "ASSEMBLY")
    transition_batch(batch_id, "BUILT")
    return batch_fresh(batch_id), slot


def setup_batch_built(job_name="QC Job"):
    """Production preamble stopped at BUILT (completed BUILD_PICK slot exists)."""
    ns = setup_released_cl1(job_name=job_name)
    ns.crane = make_crane()
    ns.rsv = reserve_standard_cl1(ns.lots, ns.lines, ns.cl1["id"])
    ns.bat1 = make_batch(ns.job["id"], ns.cl1["id"], ns.jig_roof["id"])
    ns.bat1, ns.slot_a = drive_batch_to_built(
        ns.bat1["id"], [ns.lines["TC-1"], ns.lines["BC-1"]], ns.crane["id"]
    )
    ns.job = job_fresh(ns.job["id"])
    return ns


def setup_exploded_list_with_lot(job_name="Lot Job"):
    """Confirmed job + sealed TR-01 + one-line cut list EXPLODED (never released)
    + an L2X6 MSR lumber lot of 500.0 bf. Reservations may target the PENDING line."""
    ns = setup_sealed_roof_design(job_name=job_name, contract=100000)
    ns.jig_roof = make_jig()
    ns.cl1, ns.lines = explode_cut_list(
        ns.dsg1["id"], ns.jig_roof["id"], [cut_list_line_payload("TC-1", "L2X6", 12.0, 10)]
    )
    ns.lot6 = make_lumber_lot(lumber_dimension="L2X6", received_board_feet=500.0)
    return ns


def setup_load_with_light_crane(job_name="Weight Job"):
    """Production preamble on a 4000-lb LIGHT crane + PLANNED load with a BOOKED
    LOAD_PICK slot (the weight-guard reference crane)."""
    ns = setup_production_preamble(
        job_name=job_name,
        crane_overrides={"crane_code": "CR-LIGHT", "capacity_lbs": 4000,
                         "crane_class": "LIGHT", "hourly_rate_cents": 10000},
    )
    ns.load = make_load(ns.job["id"], planned_weight_est_lbs=4000)
    ns.slot_l = book_slot(ns.crane["id"], "LOAD_PICK", "2026-08-20T09:00:00Z",
                          "2026-08-20T10:00:00Z", delivery_load_id=ns.load["id"])
    return ns


def setup_crane_with_booked_slot(crane_overrides=None):
    """A crane with one BOOKED BUILD_PICK slot on 2026-08-12 10:00-12:00."""
    crane = make_crane(**(crane_overrides or {"crane_code": "CR-B", "capacity_lbs": 4000,
                                              "crane_class": "LIGHT", "hourly_rate_cents": 10000}))
    slot = book_slot(crane["id"], "BUILD_PICK", "2026-08-12T10:00:00Z", "2026-08-12T12:00:00Z")
    return SimpleNamespace(crane=crane_fresh(crane["id"]), slot=slot)


def seal_revision(job_id, submitter, sealer, superseded_design, **overrides):
    """Create + seal the next revision of a component_ref."""
    return make_sealed_design(job_id, submitter, sealer,
                              supersedes_design_id=superseded_design["id"], **overrides)
