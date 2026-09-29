"""Cabinet endpoints: planning, module install/removal, QA approval, mounting."""

from flask import Blueprint

import aggregates
import auth
import calc
import envelope
import serializers
import store
import validators as v
from errors import ApiError

bp = Blueprint("cabinets", __name__)


@bp.route("/cabinets", methods=["POST"])
def plan_cabinet():
    auth.require("ProductionOperator")
    body = v.body()
    project_id = v.get_id(body, "project_id")
    grid_row = v.get_int(body, "grid_row", minimum=1)
    grid_col = v.get_int(body, "grid_col", minimum=1)
    project = store.display_projects.get(project_id)
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")
    # rung 42 — outside the declared grid or already taken
    if grid_row > project["cabinet_grid_rows"] or grid_col > project["cabinet_grid_cols"]:
        raise ApiError("ERR_CABINET_POSITION_TAKEN")
    for other in store.cabinets.values():
        if (other["project_id"] == project_id and other["grid_row"] == grid_row
                and other["grid_col"] == grid_col):
            raise ApiError("ERR_CABINET_POSITION_TAKEN")
    rec = store.new_record({
        "project_id": project_id,
        "grid_row": grid_row,
        "grid_col": grid_col,
        "cabinet_state": "PLANNED",
        "baseline_uniformity_score": None,
        "baseline_module_ids": [],
        "qa_approved_by_user_id": None,
    })
    store.cabinets[rec["id"]] = rec
    return envelope.object_response(serializers.cabinet(rec), 201)


@bp.route("/cabinets/<cabinet_id>/modules", methods=["POST"])
def install_module(cabinet_id):
    auth.require("ProductionOperator")
    body = v.body()
    module_id = v.get_id(body, "module_id")
    slot_index = v.get_int(body, "slot_index", minimum=1)
    expected = v.get_int(body, "expected_cabinet_version")

    cab = store.cabinets.get(cabinet_id)              # rung 7
    if cab is None:
        raise ApiError("ERR_CABINET_NOT_FOUND")
    module = store.modules.get(module_id)              # rung 8
    if module is None:
        raise ApiError("ERR_MODULE_NOT_FOUND")
    if expected != cab["version"]:                     # rung 14
        raise ApiError("ERR_STALE_CABINET_VERSION")
    project = aggregates.project_of_cabinet(cab)
    if project["engineering_state"] != "APPROVED":      # rung 18
        raise ApiError("ERR_ENGINEERING_NOT_APPROVED")
    if module["module_state"] != "CALIBRATED":         # rung 19
        raise ApiError("ERR_INVALID_MODULE_STATE")
    if cab["cabinet_state"] not in ("PLANNED", "IN_ASSEMBLY"):   # rung 20
        raise ApiError("ERR_INVALID_CABINET_STATE")
    model = aggregates.model_of_project(project)
    if module["display_model_id"] != project["display_model_id"]:  # rung 38
        raise ApiError("ERR_MODULE_MODEL_MISMATCH")
    occupied = aggregates.cabinet_derived(cab)["occupied_slot_indexes"]
    if slot_index > model["modules_per_cabinet"] or slot_index in occupied:  # rung 44
        raise ApiError("ERR_CABINET_SLOT_OCCUPIED")
    if module["reserved_service_contract_id"] is not None:         # rung 45
        raise ApiError("ERR_MODULE_RESERVED_AS_SPARE")

    module["cabinet_id"] = cab["id"]
    module["slot_index"] = slot_index
    module["module_state"] = "INSTALLED"
    store.touch(module)

    if cab["cabinet_state"] == "PLANNED":
        cab["cabinet_state"] = "IN_ASSEMBLY"
    installed = aggregates.cabinet_derived(cab)["installed_module_count"]
    if installed == model["modules_per_cabinet"]:
        cab["cabinet_state"] = "POPULATED"
    store.touch(cab)

    if project["production_state"] == "NOT_STARTED":
        project["production_state"] = "IN_ASSEMBLY"
        store.touch(project)
    return envelope.object_response(serializers.module(module), 201)


@bp.route("/cabinets/<cabinet_id>/module-removals", methods=["POST"])
def remove_module(cabinet_id):
    auth.require("ProductionOperator")
    body = v.body()
    module_id = v.get_id(body, "module_id")
    expected = v.get_int(body, "expected_cabinet_version")

    cab = store.cabinets.get(cabinet_id)              # rung 7
    if cab is None:
        raise ApiError("ERR_CABINET_NOT_FOUND")
    module = store.modules.get(module_id)              # rung 8
    if module is None:
        raise ApiError("ERR_MODULE_NOT_FOUND")
    if expected != cab["version"]:                     # rung 14
        raise ApiError("ERR_STALE_CABINET_VERSION")
    if module["module_state"] != "INSTALLED" or module["cabinet_id"] != cab["id"]:  # rung 19
        raise ApiError("ERR_INVALID_MODULE_STATE")
    if cab["cabinet_state"] not in ("IN_ASSEMBLY", "POPULATED", "QUARANTINED"):     # rung 20
        raise ApiError("ERR_INVALID_CABINET_STATE")

    module["cabinet_id"] = None
    module["slot_index"] = None
    module["module_state"] = "CALIBRATED"
    store.touch(module)

    # POPULATED and QUARANTINED both fall back to IN_ASSEMBLY; IN_ASSEMBLY self-loops
    # and the cabinet never returns to PLANNED.
    cab["cabinet_state"] = "IN_ASSEMBLY"
    store.touch(cab)

    project = aggregates.project_of_cabinet(cab)
    if project is not None and project["production_state"] == "BLOCKED":
        _, _, quarantined = aggregates.project_counters(project)
        if quarantined == 0:
            project["production_state"] = "IN_ASSEMBLY"
            store.touch(project)
    return envelope.object_response(serializers.module(module), 201)


@bp.route("/cabinets/<cabinet_id>/qa-approve", methods=["POST"])
def qa_approve(cabinet_id):
    user_id, _ = auth.require("QAEngineer")
    v.body()
    cab = store.cabinets.get(cabinet_id)              # rung 7
    if cab is None:
        raise ApiError("ERR_CABINET_NOT_FOUND")
    if cab["cabinet_state"] != "BURN_IN_PASSED":       # rung 20
        raise ApiError("ERR_INVALID_CABINET_STATE")
    for mod in aggregates.installed_modules(cab["id"]):            # rung 26
        if mod["calibrated_by_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    cab["qa_approved_by_user_id"] = user_id
    cab["cabinet_state"] = "QA_PASSED"
    store.touch(cab)

    project = aggregates.project_of_cabinet(cab)
    if project is not None:
        qa_passed, _, quarantined = aggregates.project_counters(project)
        if (project["production_state"] == "IN_ASSEMBLY"
                and qa_passed == project["cabinet_count"] and quarantined == 0):
            project["production_state"] = "QA_COMPLETE"
        store.touch(project)
    return envelope.object_response(serializers.cabinet(cab))


@bp.route("/cabinets/<cabinet_id>/mount", methods=["POST"])
def mount(cabinet_id):
    auth.require("FieldEngineer")
    v.body()
    cab = store.cabinets.get(cabinet_id)              # rung 7
    if cab is None:
        raise ApiError("ERR_CABINET_NOT_FOUND")
    project = aggregates.project_of_cabinet(cab)
    if project["engineering_state"] != "APPROVED":     # rung 18
        raise ApiError("ERR_ENGINEERING_NOT_APPROVED")
    if cab["cabinet_state"] != "QA_PASSED":            # rung 20
        raise ApiError("ERR_INVALID_CABINET_STATE")

    cab["cabinet_state"] = "MOUNTED"
    store.touch(cab)
    _, mounted, _ = aggregates.project_counters(project)
    if (project["production_state"] == "QA_COMPLETE"
            and mounted == project["cabinet_count"]):
        project["production_state"] = "INSTALLED"
    store.touch(project)
    return envelope.object_response(serializers.cabinet(cab))


@bp.route("/cabinets/<cabinet_id>", methods=["GET"])
def get_cabinet(cabinet_id):
    auth.require(*auth.ALL_ROLES)
    cab = store.cabinets.get(cabinet_id)
    if cab is None:
        raise ApiError("ERR_CABINET_NOT_FOUND")
    return envelope.object_response(serializers.cabinet(cab))


@bp.route("/cabinets", methods=["GET"])
def list_cabinets():
    auth.require(*auth.ALL_ROLES)
    limit, offset = v.pagination()
    project_id = v.query_str("project_id")
    state = v.query_enum("cabinet_state", calc.CABINET_STATES)
    rows = aggregates.by_created(store.cabinets.values())
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if state is not None:
        rows = [r for r in rows if r["cabinet_state"] == state]
    return envelope.paginated(rows, limit, offset, serializers.cabinet)
