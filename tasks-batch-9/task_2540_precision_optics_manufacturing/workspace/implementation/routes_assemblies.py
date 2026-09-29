"""§3.8 Assembly and AssemblyComponent routes."""

from decimal import Decimal

from flask import Blueprint

import calc
import logic
from common import (ALL_ROLES, authenticate, filt, get_body, need_fk, occ, ok,
                    ok_list, pagination, path_row, v_fk, v_int, v_num, v_str)
from errors import ApiError
from store import ordered, store

bp = Blueprint("assemblies", __name__)


@bp.post("/optics/assemblies")
def create_assembly():
    authenticate(["ProcessTechnician"])
    body = get_body()

    design = v_fk(body, "design_id", store.designs, "ERR_DESIGN_NOT_FOUND")
    design = need_fk(body, "design_id", design)
    code = v_str(body, "assembly_code", True, min_len=1, max_len=40)

    row = store.new_row()
    row["design_id"] = design["id"]
    row["assembly_code"] = code
    row["element_rss_waves"] = None
    row["centration_error_waves"] = None
    row["subtotal_waves"] = None
    row["cement_derate_waves"] = None
    row["total_transmitted_wavefront_waves"] = None
    row["alignment_attempt_count"] = 0
    row["assembly_status"] = "KITTED"
    row["cement_lot_code"] = None
    row["mount_code"] = None
    row["released_at_utc"] = None
    store.assemblies[row["id"]] = row
    return ok(logic.ser_assembly(row), 201)


@bp.get("/optics/assemblies/<row_id>")
def get_assembly(row_id):
    authenticate(ALL_ROLES)
    row = path_row(store.assemblies, row_id, "ERR_ASSEMBLY_NOT_FOUND")
    return ok(logic.ser_assembly(row))


@bp.get("/optics/assemblies")
def list_assemblies():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = ordered(list(store.assemblies.values()))
    for name in ("design_id", "assembly_status"):
        value = filt(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    return ok_list(rows, logic.ser_assembly, limit, offset)


@bp.post("/optics/assembly-components")
def create_component():
    authenticate(["ProcessTechnician"])
    body = get_body()

    assembly = v_fk(body, "assembly_id", store.assemblies, "ERR_ASSEMBLY_NOT_FOUND")
    wo = v_fk(body, "work_order_id", store.work_orders, "ERR_WORK_ORDER_NOT_FOUND")

    assembly = need_fk(body, "assembly_id", assembly)
    wo = need_fk(body, "work_order_id", wo)
    slot_index = v_int(body, "slot_index", True, ge=1)
    decenter = v_num(body, "decenter_um", False, Decimal("0.0"), ge=0)
    tilt = v_num(body, "tilt_arcmin", False, Decimal("0.0"), ge=0)
    element_rms = v_num(body, "element_wavefront_rms_waves", False,
                        Decimal("0.0000"), ge=0)

    occ(body, "expected_assembly_version", assembly, "ERR_STALE_ASSEMBLY_VERSION")

    # priority 13 — the producing order must be released to assembly
    if wo["process_status"] != "RELEASED_TO_ASSEMBLY":
        raise ApiError("ERR_COMPONENT_NOT_RELEASED")

    # priority 22 — the slot must be free among the assembly's ACTIVE components
    for comp in logic.active_components(assembly["id"]):
        if int(comp["slot_index"]) == slot_index:
            raise ApiError("ERR_SLOT_ALREADY_OCCUPIED")

    # priority 23 — the order's element allocation must not be fully drawn
    drawn = len(logic.components_of_work_order(wo["id"], status="ACTIVE"))
    if drawn >= int(wo["element_count"]):
        raise ApiError("ERR_ELEMENT_ALLOCATION_EXCEEDED")

    comp = store.new_row()
    comp["assembly_id"] = assembly["id"]
    comp["work_order_id"] = wo["id"]
    comp["slot_index"] = slot_index
    comp["decenter_um"] = decenter
    comp["tilt_arcmin"] = tilt
    comp["element_wavefront_rms_waves"] = element_rms
    comp["component_status"] = "ACTIVE"
    store.components[comp["id"]] = comp

    store.touch(assembly)
    return ok(logic.ser_component(comp), 201)


@bp.get("/optics/assemblies/<row_id>/components")
def list_assembly_components(row_id):
    authenticate(ALL_ROLES)
    assembly = path_row(store.assemblies, row_id, "ERR_ASSEMBLY_NOT_FOUND")
    limit, offset = pagination()
    rows = ordered([c for c in store.components.values()
                    if c["assembly_id"] == assembly["id"]])
    value = filt("component_status")
    if value is not None:
        rows = [r for r in rows if r["component_status"] == value]
    return ok_list(rows, logic.ser_component, limit, offset)


@bp.get("/optics/assembly-components/<row_id>")
def get_component(row_id):
    authenticate(ALL_ROLES)
    row = path_row(store.components, row_id, "ERR_ASSEMBLY_COMPONENT_NOT_FOUND")
    return ok(logic.ser_component(row))


@bp.post("/optics/assemblies/<row_id>/cement")
def cement(row_id):
    authenticate(["ProcessTechnician"])
    assembly = path_row(store.assemblies, row_id, "ERR_ASSEMBLY_NOT_FOUND")
    body = get_body()

    cement_lot_code = v_str(body, "cement_lot_code", True, min_len=1, max_len=40)

    if assembly["assembly_status"] != "KITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if not logic.active_components(assembly["id"]):
        raise ApiError("ERR_ASSEMBLY_EMPTY")

    assembly["cement_lot_code"] = cement_lot_code
    assembly["assembly_status"] = "CEMENTED"
    store.touch(assembly)
    return ok(logic.ser_assembly(assembly))


@bp.post("/optics/assemblies/<row_id>/mount")
def mount(row_id):
    authenticate(["ProcessTechnician"])
    assembly = path_row(store.assemblies, row_id, "ERR_ASSEMBLY_NOT_FOUND")
    body = get_body()

    mount_code = v_str(body, "mount_code", True, min_len=1, max_len=40)

    if assembly["assembly_status"] != "CEMENTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    assembly["mount_code"] = mount_code
    assembly["assembly_status"] = "MOUNTED"
    store.touch(assembly)
    return ok(logic.ser_assembly(assembly))


@bp.post("/optics/assemblies/<row_id>/align")
def align(row_id):
    authenticate(["ProcessTechnician"])
    assembly = path_row(store.assemblies, row_id, "ERR_ASSEMBLY_NOT_FOUND")

    if assembly["assembly_status"] != "MOUNTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    comps = logic.active_components(assembly["id"])
    # priority 13 before priority 24 (vacuously true when the set is empty)
    for comp in comps:
        wo = store.work_orders.get(comp["work_order_id"])
        if wo is None or wo["process_status"] != "RELEASED_TO_ASSEMBLY":
            raise ApiError("ERR_COMPONENT_NOT_RELEASED")
    if not comps:
        raise ApiError("ERR_ASSEMBLY_EMPTY")

    total = logic.recompute_assembly(assembly)
    design = store.designs.get(assembly["design_id"])
    budget = Decimal(design["transmitted_wavefront_budget_waves"])

    if Decimal(total) <= budget:
        assembly["assembly_status"] = "ALIGNED"
    else:
        assembly["alignment_attempt_count"] = int(
            assembly["alignment_attempt_count"]) + 1
        if int(assembly["alignment_attempt_count"]) >= calc.MAX_ALIGNMENT_ATTEMPTS:
            assembly["assembly_status"] = "REJECTED"
        else:
            assembly["assembly_status"] = "MOUNTED"
    store.touch(assembly)
    return ok(logic.ser_assembly(assembly))


@bp.post("/optics/assemblies/<row_id>/seal")
def seal(row_id):
    authenticate(["ProcessTechnician", "QualityManager"])
    assembly = path_row(store.assemblies, row_id, "ERR_ASSEMBLY_NOT_FOUND")

    if assembly["assembly_status"] != "ALIGNED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if not logic.inspection_ok(assembly["id"]):
        raise ApiError("ERR_INSPECTION_NOT_PASSED")

    assembly["assembly_status"] = "SEALED"
    store.touch(assembly)
    return ok(logic.ser_assembly(assembly))


@bp.post("/optics/assemblies/<row_id>/release")
def release_assembly(row_id):
    authenticate(["QualityManager"])
    assembly = path_row(store.assemblies, row_id, "ERR_ASSEMBLY_NOT_FOUND")

    blocking, _facts = logic.release_gate(assembly)
    if blocking is not None:
        raise ApiError(blocking)

    assembly["assembly_status"] = "RELEASED"
    assembly["released_at_utc"] = store.now_str()
    store.touch(assembly)
    return ok(logic.ser_assembly(assembly))


@bp.get("/optics/assemblies/<row_id>/release-readiness")
def release_readiness(row_id):
    authenticate(ALL_ROLES)
    assembly = path_row(store.assemblies, row_id, "ERR_ASSEMBLY_NOT_FOUND")
    blocking, facts = logic.release_gate(assembly)

    pkg = facts["package"]
    completeness = None
    if pkg is not None:
        completeness = logic.package_view(pkg)[3]

    data = {
        "assembly_id": assembly["id"],
        "assembly_status": assembly["assembly_status"],
        "active_component_count": len(logic.active_components(assembly["id"])),
        "inspection_ok": bool(facts["inspection_ok"]),
        "export_ok": bool(facts["export_ok"]),
        "documentation_ok": bool(facts["documentation_ok"]),
        "wavefront_ok": bool(facts["wavefront_ok"]),
        "total_transmitted_wavefront_waves": facts["total"],
        "transmitted_wavefront_budget_waves": facts["budget"],
        "completeness_pct": completeness,
        "blocking_error_id": blocking,
    }
    return ok(data)


@bp.get("/optics/assemblies/<row_id>/inspection-records")
def list_assembly_inspections(row_id):
    authenticate(ALL_ROLES)
    assembly = path_row(store.assemblies, row_id, "ERR_ASSEMBLY_NOT_FOUND")
    limit, offset = pagination()
    rows = logic.inspections_of_assembly(assembly["id"])
    value = filt("inspection_status")
    if value is not None:
        rows = [r for r in rows if r["inspection_status"] == value]
    return ok_list(rows, logic.ser_inspection, limit, offset)


@bp.get("/optics/assemblies/<row_id>/documentation-packages")
def list_assembly_packages(row_id):
    authenticate(ALL_ROLES)
    assembly = path_row(store.assemblies, row_id, "ERR_ASSEMBLY_NOT_FOUND")
    limit, offset = pagination()
    rows = logic.packages_of_assembly(assembly["id"])
    value = filt("package_status")
    if value is not None:
        rows = [r for r in rows if r["package_status"] == value]
    return ok_list(rows, logic.ser_package, limit, offset)
