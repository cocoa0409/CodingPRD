"""Array blocks, piles, racking completion, DC wiring and string testing."""

from flask import Blueprint

import calc
import clock
import envelope
import store
import validate
from clock import dec
from errors import fail
from routes.common import filter_eq, paginate, require_same_project, unique_check
from validate import ALL_ROLES, authorize, b, body, dt, e, i, n, s

bp = Blueprint("arrays", __name__)

REMEDIATION_METHODS = ("PREDRILL", "SPLICE", "RELOCATE")


@bp.post("/solar/projects/<project_id>/blocks")
def create_block(project_id):
    authorize("EpcProjectManager")
    data = body(
        s("grading_area_id"),
        s("block_code"),
        n("dc_capacity_kw", gt=0),
        i("planned_pile_count", ge=1),
        i("planned_string_count", ge=1),
    )
    project = store.require_project(project_id)
    area = store.require_grading_area(data["grading_area_id"])
    require_same_project(area["project_id"], project_id)
    unique_check(store.blocks, "project_id", project_id, "block_code", data["block_code"])
    row = store.base()
    row.update(
        {
            "project_id": project_id,
            "grading_area_id": area["id"],
            "block_code": data["block_code"],
            "dc_capacity_kw": data["dc_capacity_kw"],
            "planned_pile_count": data["planned_pile_count"],
            "planned_string_count": data["planned_string_count"],
            "mechanical_status": "PLANNED",
            "electrical_status": "PLANNED",
            "piles_accepted_count": 0,
            "piles_refused_count": 0,
            "circuits_wired_count": 0,
            "circuits_tested_count": 0,
            "circuits_failed_count": 0,
            "modules_installed_qty": None,
            "max_torque_tube_deviation_mm": None,
            "mc_ready": False,
        }
    )
    store.blocks[row["id"]] = row
    calc.sync_project(project, force=True)
    return envelope.created(row)


@bp.get("/solar/blocks/<block_id>")
def get_block(block_id):
    authorize(*ALL_ROLES)
    return envelope.ok(store.require_block(block_id))


@bp.get("/solar/blocks")
def list_blocks():
    authorize(*ALL_ROLES)
    rows = store.ordered(list(store.blocks.values()))
    rows = filter_eq(rows, "project_id", validate.q("project_id"))
    rows = filter_eq(rows, "grading_area_id", validate.q("grading_area_id"))
    rows = filter_eq(rows, "mechanical_status", validate.q("mechanical_status"))
    rows = filter_eq(rows, "electrical_status", validate.q("electrical_status"))
    rows = filter_eq(rows, "mc_ready", validate.qbool("mc_ready"))
    return paginate(rows)


@bp.post("/solar/blocks/<block_id>/piles")
def create_pile(block_id):
    authorize("InstallationForeman")
    data = body(
        i("row_index", ge=1),
        i("position_index", ge=1),
        i("design_embedment_mm", gt=0),
    )
    block = store.require_block(block_id)
    row = store.base()
    row.update(
        {
            "block_id": block["id"],
            "row_index": data["row_index"],
            "position_index": data["position_index"],
            "design_embedment_mm": data["design_embedment_mm"],
            "actual_embedment_mm": None,
            "plumb_deviation_mm": None,
            "blow_count": None,
            "refusal_flag": False,
            "status": "PLANNED",
            "remediated": False,
            "remediation_method": None,
            "driven_at": None,
        }
    )
    store.piles[row["id"]] = row
    return envelope.created(row)


@bp.get("/solar/blocks/<block_id>/piles")
def list_piles(block_id):
    authorize(*ALL_ROLES)
    store.require_block(block_id)
    rows = store.children(store.piles, "block_id", block_id)
    rows = filter_eq(rows, "status", validate.q("status"))
    return paginate(rows)


@bp.get("/solar/piles/<pile_id>")
def get_pile(pile_id):
    authorize(*ALL_ROLES)
    return envelope.ok(store.require_pile(pile_id))


def _require_accepted_area(block):
    area = store.grading_areas.get(block["grading_area_id"])
    if area is None or area["status"] != "ACCEPTED":
        fail("ERR_GRADING_AREA_NOT_ACCEPTED")


@bp.post("/solar/piles/<pile_id>/drive-results")
def drive_pile(pile_id):
    authorize("InstallationForeman")
    data = body(
        i("actual_embedment_mm", ge=0),
        n("plumb_deviation_mm", ge=0),
        i("blow_count", ge=0),
        b("refusal"),
        dt("driven_at", required=False),
    )
    pile = store.require_pile(pile_id)
    if pile["status"] != "PLANNED":
        fail("ERR_PILE_NOT_DRIVEABLE")
    block = store.require_block(pile["block_id"])
    _require_accepted_area(block)

    pile["actual_embedment_mm"] = data["actual_embedment_mm"]
    pile["plumb_deviation_mm"] = data["plumb_deviation_mm"]
    pile["blow_count"] = data["blow_count"]
    pile["refusal_flag"] = data["refusal"]
    pile["driven_at"] = data["driven_at"] or clock.now()
    pile["status"] = calc.pile_disposition(
        data["refusal"],
        data["actual_embedment_mm"],
        data["plumb_deviation_mm"],
        pile["design_embedment_mm"],
    )
    store.touch(pile)
    calc.cascade_from_block(block)
    return envelope.ok(pile)


@bp.post("/solar/piles/<pile_id>/remediations")
def remediate_pile(pile_id):
    authorize("InstallationForeman")
    data = body(
        e("remediation_method", REMEDIATION_METHODS),
        i("actual_embedment_mm", ge=0),
        n("plumb_deviation_mm", ge=0),
    )
    pile = store.require_pile(pile_id)
    if pile["status"] not in ("OUT_OF_TOLERANCE", "REFUSED"):
        fail("ERR_PILE_NOT_REMEDIABLE")
    block = store.require_block(pile["block_id"])
    _require_accepted_area(block)
    if not calc.remediation_clears(
        data["actual_embedment_mm"], data["plumb_deviation_mm"], pile["design_embedment_mm"]
    ):
        fail("ERR_REMEDIATION_STILL_OUT_OF_TOLERANCE")

    pile["actual_embedment_mm"] = data["actual_embedment_mm"]
    pile["plumb_deviation_mm"] = data["plumb_deviation_mm"]
    pile["remediation_method"] = data["remediation_method"]
    pile["remediated"] = True
    pile["refusal_flag"] = False
    pile["status"] = "ACCEPTED"
    store.touch(pile)
    calc.cascade_from_block(block)
    return envelope.ok(pile)


@bp.post("/solar/blocks/<block_id>/mechanical-completion")
def complete_block_mechanically(block_id):
    authorize("InstallationForeman")
    data = body(i("modules_installed_qty", ge=0), n("max_torque_tube_deviation_mm", ge=0))
    block = store.require_block(block_id)
    if block["mechanical_status"] != "PILES_COMPLETE":
        fail("ERR_BLOCK_PILES_INCOMPLETE")
    if dec(data["max_torque_tube_deviation_mm"]) > calc.TORQUE_TUBE_TOLERANCE_MM:
        fail("ERR_TORQUE_TUBE_TOLERANCE_EXCEEDED")
    delivered, installed = calc.module_availability(block)
    if data["modules_installed_qty"] > delivered - installed:
        fail("ERR_INSUFFICIENT_ACCEPTED_MODULES")

    block["modules_installed_qty"] = data["modules_installed_qty"]
    block["max_torque_tube_deviation_mm"] = data["max_torque_tube_deviation_mm"]
    block["mechanical_status"] = "MECH_COMPLETE"
    calc.sync_block(block, force=True)
    project = store.projects.get(block["project_id"])
    if project is not None:
        calc.sync_project(project)
    return envelope.ok(block)


@bp.post("/solar/blocks/<block_id>/string-circuits")
def create_circuit(block_id):
    authorize("InstallationForeman")
    data = body(s("circuit_code"), i("modules_in_series", ge=1))
    block = store.require_block(block_id)
    unique_check(store.circuits, "block_id", block_id, "circuit_code", data["circuit_code"])
    row = store.base()
    row.update(
        {
            "block_id": block["id"],
            "circuit_code": data["circuit_code"],
            "modules_in_series": data["modules_in_series"],
            "combiner_position": None,
            "status": "PLANNED",
            "insulation_resistance_mohm": None,
            "measured_voc_v": None,
            "expected_voc_v": None,
            "polarity_ok": None,
            "test_failure_reason": None,
            "tested_at": None,
        }
    )
    store.circuits[row["id"]] = row
    return envelope.created(row)


@bp.get("/solar/blocks/<block_id>/string-circuits")
def list_circuits(block_id):
    authorize(*ALL_ROLES)
    store.require_block(block_id)
    rows = store.children(store.circuits, "block_id", block_id)
    rows = filter_eq(rows, "status", validate.q("status"))
    return paginate(rows)


@bp.get("/solar/string-circuits/<circuit_id>")
def get_circuit(circuit_id):
    authorize(*ALL_ROLES)
    return envelope.ok(store.require_circuit(circuit_id))


@bp.post("/solar/string-circuits/<circuit_id>/wiring")
def wire_circuit(circuit_id):
    authorize("InstallationForeman")
    data = body(s("combiner_position"))
    circuit = store.require_circuit(circuit_id)
    if circuit["status"] != "PLANNED":
        fail("ERR_CIRCUIT_STATE_INVALID")
    block = store.require_block(circuit["block_id"])
    if block["mechanical_status"] != "MECH_COMPLETE":
        fail("ERR_BLOCK_NOT_MECHANICALLY_COMPLETE")
    circuit["combiner_position"] = data["combiner_position"]
    circuit["status"] = "WIRED"
    store.touch(circuit)
    calc.cascade_from_block(block)
    return envelope.ok(circuit)


@bp.post("/solar/string-circuits/<circuit_id>/test-results")
def test_circuit(circuit_id):
    authorize("InstallationForeman")
    data = body(
        n("insulation_resistance_mohm", ge=0),
        n("measured_voc_v", ge=0),
        n("ambient_c"),
        b("polarity_ok"),
    )
    circuit = store.require_circuit(circuit_id)
    if circuit["status"] not in ("WIRED", "TESTED", "FAILED"):
        fail("ERR_CIRCUIT_STATE_INVALID")
    block = store.require_block(circuit["block_id"])

    expected, passed, reason = calc.string_test_disposition(
        circuit["modules_in_series"],
        data["insulation_resistance_mohm"],
        data["measured_voc_v"],
        data["ambient_c"],
        data["polarity_ok"],
    )
    circuit["insulation_resistance_mohm"] = data["insulation_resistance_mohm"]
    circuit["measured_voc_v"] = data["measured_voc_v"]
    circuit["expected_voc_v"] = expected
    circuit["polarity_ok"] = data["polarity_ok"]
    circuit["test_failure_reason"] = None if passed else reason
    circuit["status"] = "TESTED" if passed else "FAILED"
    circuit["tested_at"] = clock.now()
    store.touch(circuit)
    calc.cascade_from_block(block)
    return envelope.ok(circuit)
