"""§3.9 InspectionRecord routes."""

from flask import Blueprint

import calc
import logic
from common import (ALL_ROLES, authenticate, get_body, need_fk, ok, path_row,
                    v_fk, v_int, v_str)
from errors import ApiError
from store import store

bp = Blueprint("inspection", __name__)


@bp.post("/optics/inspection-records")
def create_inspection():
    user_id, _role = authenticate(["MetrologyTechnician", "QualityManager"])
    body = get_body()

    # priority 4 — body foreign keys
    assembly = v_fk(body, "assembly_id", store.assemblies, "ERR_ASSEMBLY_NOT_FOUND")

    # priority 5 — field validation, in the endpoint's declared field order
    assembly = need_fk(body, "assembly_id", assembly)
    max_scratch = v_int(body, "max_scratch_number", True, ge=0)
    max_dig = v_int(body, "max_dig_number", True, ge=0)
    particles = v_int(body, "particle_count_per_cm2", True, ge=0)
    at_limit = v_int(body, "scratch_count_at_limit", False, 1, ge=0)

    # priority 7 — the assembly must be far enough along to be inspected
    if assembly["assembly_status"] not in ("MOUNTED", "ALIGNED", "SEALED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    design = store.designs.get(assembly["design_id"])

    record = store.new_row()
    record["assembly_id"] = assembly["id"]
    record["max_scratch_number"] = max_scratch
    record["max_dig_number"] = max_dig
    record["scratch_count_at_limit"] = at_limit
    record["particle_count_per_cm2"] = particles

    scratch_dig_pass, cleanliness_pass, status = calc.cleanliness_verdict(record, design)
    record["scratch_dig_pass"] = scratch_dig_pass
    record["cleanliness_pass"] = cleanliness_pass
    record["inspection_status"] = status
    record["inspected_by_user_id"] = user_id
    record["waived_by_user_id"] = None
    record["waiver_justification"] = None
    store.inspections[record["id"]] = record
    return ok(logic.ser_inspection(record), 201)


@bp.get("/optics/inspection-records/<row_id>")
def get_inspection(row_id):
    authenticate(ALL_ROLES)
    record = path_row(store.inspections, row_id, "ERR_INSPECTION_RECORD_NOT_FOUND")
    return ok(logic.ser_inspection(record))


@bp.post("/optics/inspection-records/<row_id>/waiver")
def waive_inspection(row_id):
    user_id, _role = authenticate(["QualityManager"])
    record = path_row(store.inspections, row_id, "ERR_INSPECTION_RECORD_NOT_FOUND")
    body = get_body()

    # priority 5 — a justification of at least twenty characters
    justification = v_str(body, "justification", True, min_len=20, max_len=2000)

    # priority 7 — only a FAILED record may be waived
    if record["inspection_status"] != "FAILED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    assembly = store.assemblies.get(record["assembly_id"])
    design = store.designs.get(assembly["design_id"]) if assembly else None

    # priority 11 — the defect must be waivable at all
    if design is None or not calc.waivable(record, design):
        raise ApiError("ERR_DEFECT_NOT_WAIVABLE")

    # priority 12 — segregation of duties
    if user_id == record["inspected_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    record["inspection_status"] = "WAIVED"
    record["waived_by_user_id"] = user_id
    record["waiver_justification"] = justification
    store.touch(record)

    # Hop two: every documentation package of the assembly re-derives its
    # required document set, which now includes INSPECTION_WAIVER. That set is
    # derived, never declared, so the re-derivation happens on the next read of
    # the package and no stored package field is written here.
    return ok(logic.ser_inspection(record))
