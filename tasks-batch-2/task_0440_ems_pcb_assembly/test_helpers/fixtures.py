"""Composite setup helpers for the EMS PCB-assembly API.

These encapsulate the multi-step preambles that most test claims share: building a
part with an approved source and stock, authoring and releasing a BOM, planning a
work order, and walking it through kit / setup / start / serialize / test toward a
late lifecycle stage. Each helper builds its preconditions from scratch using only
PRD-declared endpoints (the server starts against an empty database before every
test) and uses get_success_data() so setup failures surface as clear "Setup failed"
errors rather than confusing assertions.

Identity note (PRD §2.1): every role uses an opaque X-User-ID never compared to an
entity id, so these fixtures use the shared role headers. The ECO authorship /
segregation-of-duties helpers thread explicit acting identities where the contract
demands an auditable actor (PRD §3.9).
"""
import itertools
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as f

PE = TEST_USERS["process_engineer_headers"]
PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]

# Monotonic counters so independently-built fixtures never collide on unique fields
# (internal_pn, vendor name, product_code, lot_code) within a single test.
_seq = itertools.count(1)


def _n() -> int:
    return next(_seq)


# ---------------------------------------------------------------------------
# Tier 1 / 2: parts, vendors, approvals, and stocked inventory
# ---------------------------------------------------------------------------

def create_part(standard_cost_cents=50, is_rohs_required=False,
                contains_conflict_minerals=False, package_type="0402", **overrides):
    """Create a part. RoHS defaults to false here to keep generic fixtures unblocked;
    callers that test compliance pass is_rohs_required / contains_conflict_minerals."""
    n = _n()
    payload = f.create_part_payload(
        internal_pn=overrides.pop("internal_pn", f"P-{n}"),
        description=overrides.pop("description", f"part {n}"),
        package_type=package_type,
        standard_cost_cents=standard_cost_cents,
        is_rohs_required=is_rohs_required,
        contains_conflict_minerals=contains_conflict_minerals,
        **overrides,
    )
    return get_success_data(api_client.create_part(payload, PE))


def create_vendor(**overrides):
    n = _n()
    payload = f.create_vendor_payload(
        name=overrides.pop("name", f"Vendor {n}"),
        cage_code=overrides.pop("cage_code", f"CG{n:03d}"),
        **overrides,
    )
    return get_success_data(api_client.create_vendor(payload, PE))


def create_approved_avl(part_id, vendor_id=None, **overrides):
    """Approve a part/vendor pairing; auto-creates a vendor when none is supplied."""
    if vendor_id is None:
        vendor_id = create_vendor()["id"]
    payload = f.create_avl_entry_payload(part_id, vendor_id, **overrides)
    return get_success_data(api_client.create_avl_entry(payload, PE))


def receive_one_lot(avl_id, expected_version, received_qty=100, unit_cost_cents=50,
                    is_rohs_compliant=True, has_cmrt=True, received_at=None, lot_code=None,
                    **overrides):
    """Receive a single lot against an approved AVL entry. RoHS+CMRT default true so
    generic fixtures pass both compliance gates; compliance tests override them."""
    n = _n()
    payload = f.receive_lot_payload(
        expected_version,
        lot_code=lot_code or f"LOT-{n}",
        received_qty=received_qty,
        unit_cost_cents=unit_cost_cents,
        is_rohs_compliant=is_rohs_compliant,
        has_cmrt=has_cmrt,
        received_at=received_at or f.DEFAULT_RECEIVED_AT,
        **overrides,
    )
    return get_success_data(api_client.receive_lot(avl_id, payload, PP))


def setup_part_with_stock(received_qty=100, unit_cost_cents=50, standard_cost_cents=50,
                          is_rohs_required=False, contains_conflict_minerals=False,
                          is_rohs_compliant=True, has_cmrt=True, package_type="0402"):
    """Part + vendor + APPROVED AvlEntry + one AVAILABLE lot. Returns
    (part, vendor, avl, lot)."""
    part = create_part(standard_cost_cents=standard_cost_cents,
                       is_rohs_required=is_rohs_required,
                       contains_conflict_minerals=contains_conflict_minerals,
                       package_type=package_type)
    vendor = create_vendor()
    avl = create_approved_avl(part["id"], vendor["id"])
    lot = receive_one_lot(avl["id"], avl["version"], received_qty=received_qty,
                          unit_cost_cents=unit_cost_cents,
                          is_rohs_compliant=is_rohs_compliant, has_cmrt=has_cmrt)
    return part, vendor, avl, lot


# ---------------------------------------------------------------------------
# Tier 1: BOM authoring and release
# ---------------------------------------------------------------------------

def create_draft_bom(product_code=None, revision="A", supersedes_bom_id=None):
    n = _n()
    payload = f.create_bom_payload(
        product_code=product_code or f"BRD-{n}",
        revision=revision,
    )
    if supersedes_bom_id is not None:
        payload["supersedes_bom_id"] = supersedes_bom_id
    return get_success_data(api_client.create_bom(payload, PE))


def add_line(bom_id, part_id, ref_designators=None, qty_per_assembly=1, is_dnp=False):
    payload = f.add_bom_line_payload(
        part_id,
        ref_designators=ref_designators or ["R1"],
        qty_per_assembly=qty_per_assembly,
        is_dnp=is_dnp,
    )
    return get_success_data(api_client.add_bom_line(bom_id, payload, PE))


def create_released_bom_single_line(part_id, qty_per_assembly=1, ref_designators=None,
                                    product_code=None, revision="A", supersedes_bom_id=None):
    """Draft BOM + one non-DNP line + release. Returns the released BOM."""
    bom = create_draft_bom(product_code=product_code, revision=revision,
                           supersedes_bom_id=supersedes_bom_id)
    add_line(bom["id"], part_id, ref_designators=ref_designators,
             qty_per_assembly=qty_per_assembly)
    return get_success_data(api_client.release_bom(bom["id"], PE))


# ---------------------------------------------------------------------------
# Tier 1: line programs
# ---------------------------------------------------------------------------

def create_verified_program(bom_id, line_code="LINE-A", feeder_slot_count=4):
    n = _n()
    payload = f.create_line_program_payload(bom_id, line_code=line_code,
                                            feeder_slot_count=feeder_slot_count,
                                            program_checksum=f"CK{n}")
    prog = get_success_data(api_client.create_line_program(payload, PE))
    return get_success_data(api_client.verify_line_program(prog["id"], PE))


def create_unverified_program(bom_id, line_code="LINE-A", feeder_slot_count=4):
    n = _n()
    payload = f.create_line_program_payload(bom_id, line_code=line_code,
                                            feeder_slot_count=feeder_slot_count,
                                            program_checksum=f"CK{n}")
    return get_success_data(api_client.create_line_program(payload, PE))


# ---------------------------------------------------------------------------
# Tier 3: work-order lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_work_order(bom_id, planned_qty=1):
    payload = f.create_work_order_payload(bom_id, planned_qty=planned_qty)
    return get_success_data(api_client.create_work_order(payload, PP))


def create_kitted_work_order(part_id, bom_id, planned_qty=1):
    """Create a work order on an already-released BOM and kit it. Returns the WO."""
    wo = create_work_order(bom_id, planned_qty=planned_qty)
    return get_success_data(api_client.kit_work_order(wo["id"], PP))


def setup_kitted_for_start(bom_id, wo_id):
    """Take an already-KITTED work order through SETUP so it may be started
    (PRD §3.6: "A `ProductionPlanner` may start a work order only while it is
    `SETUP`"). Creates a verified line program targeting bom_id and assigns it.
    Returns the work order in SETUP status."""
    program = create_verified_program(bom_id)
    return get_success_data(
        api_client.setup_work_order(wo_id, f.setup_payload(program["id"]), PP))


def setup_kitted_work_order(received_qty=100, unit_cost_cents=50, standard_cost_cents=50,
                            qty_per_assembly=1, planned_qty=1, package_type="0402"):
    """Full chain to a KITTED work order (RoHS off so generic kitting passes).
    Returns (part, bom, work_order)."""
    part, _vendor, _avl, _lot = setup_part_with_stock(
        received_qty=received_qty, unit_cost_cents=unit_cost_cents,
        standard_cost_cents=standard_cost_cents, package_type=package_type)
    bom = create_released_bom_single_line(part["id"], qty_per_assembly=qty_per_assembly)
    wo = create_kitted_work_order(part["id"], bom["id"], planned_qty=planned_qty)
    return part, bom, wo


def setup_running_work_order(received_qty=100, unit_cost_cents=50, standard_cost_cents=50,
                            qty_per_assembly=1, planned_qty=1, package_type="0402"):
    """Full chain through to RUNNING (kitted + setup + start). Returns
    (part, bom, program, work_order)."""
    part, _vendor, _avl, _lot = setup_part_with_stock(
        received_qty=received_qty, unit_cost_cents=unit_cost_cents,
        standard_cost_cents=standard_cost_cents, package_type=package_type)
    bom = create_released_bom_single_line(part["id"], qty_per_assembly=qty_per_assembly)
    program = create_verified_program(bom["id"])
    wo = create_kitted_work_order(part["id"], bom["id"], planned_qty=planned_qty)
    get_success_data(api_client.setup_work_order(wo["id"], f.setup_payload(program["id"]), PP))
    wo = get_success_data(api_client.start_work_order(wo["id"], PP))
    return part, bom, program, wo


def serialize_all_units(wo_id, count):
    """Serialize `count` units under a RUNNING work order. Returns the unit dicts."""
    units = []
    for _ in range(count):
        units.append(get_success_data(api_client.serialize_unit(wo_id, PP)))
    return units


def setup_at_test_work_order(planned_qty=1, received_qty=100, unit_cost_cents=50,
                             standard_cost_cents=50, qty_per_assembly=1):
    """RUNNING work order with all planned units serialized (advances to AT_TEST).
    Returns (part, bom, program, work_order, units)."""
    part, bom, program, wo = setup_running_work_order(
        received_qty=received_qty, unit_cost_cents=unit_cost_cents,
        standard_cost_cents=standard_cost_cents, qty_per_assembly=qty_per_assembly,
        planned_qty=planned_qty)
    units = serialize_all_units(wo["id"], planned_qty)
    wo = get_success_data(api_client.get_work_order(wo["id"], PP))
    return part, bom, program, wo, units


def record_result(unit_id, result, defect_code=None):
    payload = f.test_result_payload(result, **({"defect_code": defect_code} if defect_code else {}))
    return get_success_data(api_client.record_test_result(unit_id, payload, QE))


def setup_failed_unit_at_test(planned_qty=1, received_qty=100, unit_cost_cents=50,
                              standard_cost_cents=50, defect_code="OPEN",
                              is_rohs_required=False, contains_conflict_minerals=False):
    """A single-unit work order at AT_TEST whose only unit is FAIL. Returns
    (part, bom, program, work_order, unit). For rework-close tests, the same part is
    reused as the replacement source so its stock is the FIFO draw."""
    part, _vendor, _avl, _lot = setup_part_with_stock(
        received_qty=received_qty, unit_cost_cents=unit_cost_cents,
        standard_cost_cents=standard_cost_cents,
        is_rohs_required=is_rohs_required,
        contains_conflict_minerals=contains_conflict_minerals)
    bom = create_released_bom_single_line(part["id"], qty_per_assembly=1,
                                          ref_designators=["U1"])
    program = create_verified_program(bom["id"])
    wo = create_kitted_work_order(part["id"], bom["id"], planned_qty=planned_qty)
    get_success_data(api_client.setup_work_order(wo["id"], f.setup_payload(program["id"]), PP))
    get_success_data(api_client.start_work_order(wo["id"], PP))
    units = serialize_all_units(wo["id"], planned_qty)
    unit = units[0]
    record_result(unit["id"], "FAIL", defect_code=defect_code)
    unit = get_success_data(api_client.get_unit(unit["id"], PP))
    wo = get_success_data(api_client.get_work_order(wo["id"], PP))
    return part, bom, program, wo, unit


def open_rework_order(unit_id, defect_code="OPEN", eco_id=None):
    payload = f.create_rework_order_payload(unit_id, defect_code,
                                            **({"eco_id": eco_id} if eco_id else {}))
    return get_success_data(api_client.create_rework_order(payload, PP))


# ---------------------------------------------------------------------------
# Tier 5: shipped unit / RMA preconditions
# ---------------------------------------------------------------------------

def setup_shipped_unit(planned_qty=2, received_qty=100, unit_cost_cents=50,
                       standard_cost_cents=50, qty_per_assembly=1,
                       ref_designators=None):
    """Drive a work order to a state where every unit PASSes, finalize-test ->
    PASSED, then ship. Returns (part, bom, work_order, units). All units end SHIPPED.

    material_cost_cents == received-draw cost; with qty_per_assembly placements per
    unit consumed at unit_cost_cents, the build cost per unit is deterministic."""
    part, _vendor, _avl, _lot = setup_part_with_stock(
        received_qty=received_qty, unit_cost_cents=unit_cost_cents,
        standard_cost_cents=standard_cost_cents)
    bom = create_released_bom_single_line(
        part["id"], qty_per_assembly=qty_per_assembly,
        ref_designators=ref_designators or (["R1", "R2"] if qty_per_assembly == 2 else ["R1"]))
    program = create_verified_program(bom["id"])
    wo = create_kitted_work_order(part["id"], bom["id"], planned_qty=planned_qty)
    get_success_data(api_client.setup_work_order(wo["id"], f.setup_payload(program["id"]), PP))
    get_success_data(api_client.start_work_order(wo["id"], PP))
    units = serialize_all_units(wo["id"], planned_qty)
    for u in units:
        record_result(u["id"], "PASS")
    wo = get_success_data(api_client.finalize_test(wo["id"], QE))
    wo = get_success_data(api_client.ship_work_order(
        wo["id"], f.ship_payload(wo["version"]), PP))
    units = [get_success_data(api_client.get_unit(u["id"], PP)) for u in units]
    return part, bom, wo, units


def setup_rma_for_shipped_unit(failure_class=None, planned_qty=2, received_qty=100,
                               unit_cost_cents=50, qty_per_assembly=1):
    """A SHIPPED unit with an RMA opened against it; optionally triaged.
    Returns (part, work_order, unit, rma)."""
    part, _bom, wo, units = setup_shipped_unit(
        planned_qty=planned_qty, received_qty=received_qty,
        unit_cost_cents=unit_cost_cents, qty_per_assembly=qty_per_assembly)
    unit = units[0]
    rma = get_success_data(api_client.create_rma(f.create_rma_payload(unit["id"]), QE))
    if failure_class is not None:
        rma = get_success_data(api_client.triage_rma(
            rma["id"], f.triage_rma_payload(failure_class), QE))
    return part, wo, unit, rma


# ---------------------------------------------------------------------------
# ECO authoring / segregation-of-duties helpers (PRD §3.9)
# ---------------------------------------------------------------------------

def author_eco(bom_id, author_user_id="pe-1", title="Test ECO", change_summary="change"):
    """Create an ECO whose authored_by_user_id == author_user_id (PRD §2.1)."""
    from .test_users import make_process_engineer_headers
    payload = f.create_eco_payload(bom_id, title=title, change_summary=change_summary)
    return get_success_data(
        api_client.create_eco(payload, make_process_engineer_headers(author_user_id)))


def submit_eco(eco_id, author_user_id="pe-1"):
    from .test_users import make_process_engineer_headers
    return get_success_data(api_client.submit_eco(
        eco_id, f.eco_action_payload(author_user_id),
        make_process_engineer_headers(author_user_id)))


def submitted_eco(bom_id, author_user_id="pe-1"):
    """An ECO in SUBMITTED status authored by author_user_id."""
    eco = author_eco(bom_id, author_user_id=author_user_id)
    return submit_eco(eco["id"], author_user_id=author_user_id)


def approved_eco(bom_id, author_user_id="pe-1", approver_user_id="qe-1"):
    """An ECO in APPROVED status (author != approver, satisfying SoD)."""
    from .test_users import make_quality_engineer_headers
    eco = submitted_eco(bom_id, author_user_id=author_user_id)
    return get_success_data(api_client.approve_eco(
        eco["id"], f.eco_action_payload(approver_user_id),
        make_quality_engineer_headers(approver_user_id)))
