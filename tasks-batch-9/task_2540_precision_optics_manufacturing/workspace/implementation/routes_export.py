"""§3.7 ExportClassification routes."""

import re

from flask import Blueprint

import calc
import logic
from common import (ALL_ROLES, authenticate, bad, get_body, need_fk, ok, path_row,
                    v_enum, v_fk, v_str)
from errors import ApiError
from store import store

bp = Blueprint("export", __name__)

COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
DECISIONS = ["APPROVED", "DENIED"]


@bp.post("/optics/export-classifications")
def create_classification():
    authenticate(["ExportComplianceOfficer"])
    body = get_body()

    # priority 4 — body foreign keys
    design = v_fk(body, "design_id", store.designs, "ERR_DESIGN_NOT_FOUND")

    # priority 5 — field validation, in the endpoint's declared field order
    design = need_fk(body, "design_id", design)
    destination = v_str(body, "destination_country", True, min_len=2, max_len=2)
    if not COUNTRY_RE.match(destination):
        bad("destination_country", "must be exactly two upper-case letters.")
    end_use = v_str(body, "end_use_statement", False, None, min_len=1, max_len=1000)

    # priority 22 — at most one governing classification per design
    if logic.governing_classification(design["id"]) is not None:
        raise ApiError("ERR_EXPORT_CLASSIFICATION_EXISTS")

    fom, eccn, license_required, status = calc.export_classification(design, destination)

    row = store.new_row()
    row["design_id"] = design["id"]
    row["destination_country"] = destination
    row["end_use_statement"] = end_use
    row["figure_of_merit"] = fom
    row["eccn"] = eccn
    row["license_required"] = license_required
    row["license_number"] = None
    row["decided_by_user_id"] = None
    row["decision_note"] = None
    row["classification_status"] = status
    store.classifications[row["id"]] = row
    return ok(logic.ser_classification(row), 201)


@bp.get("/optics/export-classifications/<row_id>")
def get_classification(row_id):
    authenticate(ALL_ROLES)
    row = path_row(store.classifications, row_id, "ERR_EXPORT_CLASSIFICATION_NOT_FOUND")
    return ok(logic.ser_classification(row))


@bp.post("/optics/export-classifications/<row_id>/license-decision")
def license_decision(row_id):
    user_id, _role = authenticate(["ExportComplianceOfficer"])
    row = path_row(store.classifications, row_id, "ERR_EXPORT_CLASSIFICATION_NOT_FOUND")
    body = get_body()

    decision = v_enum(body, "decision", DECISIONS, True)
    license_number = v_str(body, "license_number", False, None, min_len=1, max_len=60)

    # priority 7 — only a classification awaiting the authority may be decided
    if row["classification_status"] != "LICENSE_REQUIRED":
        raise ApiError("ERR_EXPORT_ALREADY_DECIDED")

    if decision == "APPROVED":
        row["classification_status"] = "LICENSE_APPROVED"
        row["license_number"] = license_number
        row["decided_by_user_id"] = user_id
        store.touch(row)
        # the design's backlog is swept in created_at ascending order
        for wo in logic.work_orders_of_design(row["design_id"]):
            if wo["compliance_status"] == "SCREENED":
                wo["compliance_status"] = "CLEARED"
                store.touch(wo)
    else:
        row["classification_status"] = "LICENSE_DENIED"
        row["decided_by_user_id"] = user_id
        store.touch(row)
        logic.export_block_cascade(row["design_id"])

    return ok(logic.ser_classification(row))


@bp.post("/optics/export-classifications/<row_id>/revocation")
def revocation(row_id):
    authenticate(["ExportComplianceOfficer"])
    row = path_row(store.classifications, row_id, "ERR_EXPORT_CLASSIFICATION_NOT_FOUND")
    body = get_body()

    reason = v_str(body, "revocation_reason", True, min_len=1, max_len=500)

    # priority 7 — only an approved licence can be revoked
    if row["classification_status"] != "LICENSE_APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    row["classification_status"] = "LICENSE_DENIED"
    row["decision_note"] = reason
    store.touch(row)
    logic.export_block_cascade(row["design_id"])

    return ok(logic.ser_classification(row))
