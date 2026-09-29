"""InspectionRecord endpoints — third-party QC and the agency-hold cascade."""

from flask import Blueprint

import auth
import serialize
import services
import validate
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from store import base_row, db, now, sorted_rows, touch

bp = Blueprint("inspections", __name__)

STAGES = ("IN_PLANT", "FINAL_FACTORY")
RESULTS = ("PENDING", "PASS", "CONDITIONAL", "FAIL")
RECORDABLE = ("PASS", "CONDITIONAL", "FAIL")
HOLD_STATES = ("NONE", "AGENCY_HOLD", "CLEARED")


@bp.post("/modular/inspections")
@auth.endpoint("ThirdPartyInspector")
def create_inspection():
    data = validate.body(optional=False)
    module_id = validate.field_id(data, "module_id")
    agency_id = validate.field_id(data, "agency_id")
    stage = validate.field_enum(data, "stage", STAGES)

    # rank 5 — module_id then agency_id
    module = services.get_module(module_id)
    agency = services.get_agency(agency_id)

    # rank 6 — the inspector records only under its own agency
    auth.own_agency(agency_id)

    project = db.projects.get(module["project_id"])
    siblings = services.inspections_of_module(module_id)

    # rank 46 — QC cannot open before the module reaches the line
    if module["qc_status"] == "PENDING" and module["production_status"] not in (
        "IN_LINE",
        "LINE_COMPLETE",
    ):
        raise ApiError(
            "ERR_MODULE_NOT_ON_LINE",
            "production_status %s has not reached the line" % module["production_status"],
        )

    # rank 72 — inspection staging
    if any(s["result"] == "PENDING" for s in siblings):
        raise ApiError(
            "ERR_QC_STAGE_OUT_OF_ORDER",
            "another inspection of this module is still PENDING",
        )
    if stage == "FINAL_FACTORY":
        in_plant_ok = any(
            s["stage"] == "IN_PLANT" and s["result"] in ("PASS", "CONDITIONAL")
            for s in siblings
        )
        if not in_plant_ok:
            raise ApiError(
                "ERR_QC_STAGE_OUT_OF_ORDER",
                "the IN_PLANT stage has not passed on this module",
            )

    # rank 81
    if agency["accreditation_state"] not in ("ACCREDITED", "PROBATION"):
        raise ApiError(
            "ERR_AGENCY_NOT_ACCREDITED",
            "agency accreditation_state %s cannot record inspections"
            % agency["accreditation_state"],
        )

    # rank 82
    if project is not None and project["state_code"] not in agency["accredited_state_codes"]:
        raise ApiError(
            "ERR_AGENCY_JURISDICTION_MISMATCH",
            "the agency is not accredited in %s" % project["state_code"],
        )

    row = base_row()
    row.update(
        {
            "module_id": module_id,
            "agency_id": agency_id,
            "stage": stage,
            "result": "PENDING",
            "defect_count": 0,
            "severity_max": 0,
            "hold_state": "NONE",
            "corrective_note": None,
            "recorded_at": None,
            "recorded_by_user_id": None,
        }
    )
    db.inspections[row["id"]] = row

    if module["qc_status"] == "PENDING":
        module["qc_status"] = "IN_PROGRESS"
        services.recompute_wip(module)
        touch(module)
    return created(serialize.inspection(row))


@bp.get("/modular/inspections/<inspection_id>")
@auth.endpoint(
    "ProgramAdmin",
    "ThirdPartyInspector",
    "FactoryProductionManager",
    "StateProgramOfficer",
    "WarrantyAdjudicator",
)
def read_inspection(inspection_id):
    return ok(serialize.inspection(services.get_inspection(inspection_id)))


@bp.get("/modular/inspections")
@auth.endpoint(
    "ProgramAdmin",
    "ThirdPartyInspector",
    "FactoryProductionManager",
    "StateProgramOfficer",
    "WarrantyAdjudicator",
    "LenderDrawAdministrator",
)
def list_inspections():
    module_id = validate.field_str_query("module_id")
    agency_id = validate.field_str_query("agency_id")
    stage = validate.enum_query("stage", STAGES)
    result = validate.enum_query("result", RESULTS)
    hold_state = validate.enum_query("hold_state", HOLD_STATES)
    rows = sorted_rows(list(db.inspections.values()))
    if module_id is not None:
        rows = [r for r in rows if r["module_id"] == module_id]
    if agency_id is not None:
        rows = [r for r in rows if r["agency_id"] == agency_id]
    if stage is not None:
        rows = [r for r in rows if r["stage"] == stage]
    if result is not None:
        rows = [r for r in rows if r["result"] == result]
    if hold_state is not None:
        rows = [r for r in rows if r["hold_state"] == hold_state]
    page, meta = paginate(rows)
    return ok_list([serialize.inspection(r) for r in page], meta)


@bp.post("/modular/inspections/<inspection_id>/record-result")
@auth.endpoint("ThirdPartyInspector")
def record_result(inspection_id):
    data = validate.body(optional=False)
    result = validate.field_enum(data, "result", RECORDABLE)
    defect_count = validate.field_int(
        data, "defect_count", required=False, default=0, minimum=0
    )
    severity_max = validate.field_int(
        data, "severity_max", required=False, default=0, minimum=0, maximum=5
    )
    corrective_note = validate.field_str(
        data, "corrective_note", required=False, allow_blank=True
    )

    row = services.get_inspection(inspection_id)
    auth.own_agency(row["agency_id"])
    module = services.get_module(row["module_id"])
    project = db.projects.get(module["project_id"])
    agency = db.agencies.get(row["agency_id"])

    # rank 55
    if row["result"] != "PENDING" or module["qc_status"] not in (
        "IN_PROGRESS",
        "CONDITIONAL_RELEASE",
    ):
        raise ApiError(
            "ERR_INSPECTION_NOT_PENDING",
            "the record is not awaiting a result in an inspectable QC state",
        )

    row["result"] = result
    row["defect_count"] = defect_count
    row["severity_max"] = severity_max
    if corrective_note is not None:
        row["corrective_note"] = corrective_note
    row["recorded_at"] = now()
    row["recorded_by_user_id"] = auth.user_id()

    before_qc = module["qc_status"]
    before_wip = module["wip_earned_cents"]
    unloaded = None
    held = False

    if result == "FAIL":
        if agency is not None and agency["hold_authority"]:
            row["hold_state"] = "AGENCY_HOLD"
            module["qc_status"] = "HOLD"
            held = True
            unloaded = services.qc_hold_cascade(module, project)
    elif row["stage"] == "FINAL_FACTORY":
        module["qc_status"] = "RELEASED" if result == "PASS" else "CONDITIONAL_RELEASE"

    touch(row)
    services.recompute_wip(module)
    # only a hold arriving pulls the module out of the DRAFT draw basis
    if held and project is not None:
        services.recompute_draft_draws(project)
    if module["qc_status"] != before_qc or module["wip_earned_cents"] != before_wip:
        touch(module)
    if unloaded is not None:
        services.refresh_project(project)
    return ok(serialize.inspection(row))


@bp.post("/modular/inspections/<inspection_id>/clear-hold")
@auth.endpoint("ThirdPartyInspector")
def clear_hold(inspection_id):
    data = validate.body(optional=False)
    corrective_note = validate.field_str(data, "corrective_note", allow_blank=True)

    row = services.get_inspection(inspection_id)
    auth.own_agency(row["agency_id"])
    module = services.get_module(row["module_id"])
    project = db.projects.get(module["project_id"])
    agency = db.agencies.get(row["agency_id"])

    # rank 56
    if row["hold_state"] != "AGENCY_HOLD" or module["qc_status"] != "HOLD":
        raise ApiError("ERR_HOLD_NOT_ACTIVE", "no agency hold is active on this module")

    # the HOLD -> IN_PROGRESS arm requires a still-accredited agency
    if agency is None or agency["accreditation_state"] not in ("ACCREDITED", "PROBATION"):
        raise ApiError(
            "ERR_AGENCY_NOT_ACCREDITED",
            "a suspended agency cannot clear its own hold",
        )

    row["hold_state"] = "CLEARED"
    row["result"] = "PENDING"
    row["defect_count"] = 0
    row["severity_max"] = 0
    row["corrective_note"] = corrective_note
    touch(row)

    module["qc_status"] = "IN_PROGRESS"
    services.recompute_wip(module)
    touch(module)
    if project is not None:
        services.recompute_draft_draws(project)
    return ok(serialize.inspection(row))
