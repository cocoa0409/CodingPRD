"""Pathway registration and the regulator review cycle (PRD 3.8)."""
from decimal import Decimal

from flask import Blueprint

import response
import store
import validate
from constants import FEEDSTOCK_TYPES, MAX_REVISION_ROUNDS, PROGRAMS
from errors import (
    ERR_INVALID_PATHWAY_STATE,
    ERR_INVALID_REQUEST,
    ERR_NO_VERIFIED_SUPPLIER,
    ERR_REVISION_LIMIT_EXCEEDED,
    fail,
)
from routes.helpers import body_ref, find, listing
from store import bump, q

bp = Blueprint("pathways", __name__)
ZERO = Decimal("0")


@bp.post("/pathway-registrations")
def create_pathway():
    user_id, _role = validate.auth("ComplianceOfficer")
    data = validate.body()
    unit = body_ref("unit", data, "unit_id")
    program = validate.get_enum(data, "program", PROGRAMS)
    feedstock_type = validate.get_enum(data, "feedstock_type", FEEDSTOCK_TYPES)
    proposed_ci = validate.get_num(data, "proposed_ci_gco2e_per_mj", 0, 120, 2)

    row = store.new_row()
    row.update({
        "unit_id": unit["id"],
        "program": program,
        "feedstock_type": feedstock_type,
        "proposed_ci_gco2e_per_mj": q(proposed_ci, 2),
        "certified_ci_gco2e_per_mj": None,
        "status": "DRAFT",
        "revision_round": 0,
        "info_request": None,
        "registered_by_user_id": user_id,
        "variance_strikes": 0,
        "credits_outstanding_mtco2e": q(ZERO, 3),
    })
    store.pathways[row["id"]] = row
    return response.ok(row, 201)


@bp.get("/pathway-registrations/<pathway_id>")
def read_pathway(pathway_id):
    validate.auth("ComplianceOfficer", "IndependentVerifier")
    return response.ok(find("pathway", pathway_id))


@bp.get("/pathway-registrations")
def list_pathways():
    validate.auth("ComplianceOfficer", "IndependentVerifier")
    rows, limit, offset = listing(store.table_rows(store.pathways), {
        "unit_id": "unit_id",
        "program": "program",
        "feedstock_type": "feedstock_type",
        "status": "status",
    })
    return response.page(rows, limit, offset)


def _has_verified_supplier(feedstock_type):
    clock = store.now()
    for supplier in store.suppliers.values():
        if supplier["dd_status"] != "VERIFIED":
            continue
        if supplier["dd_expires_at"] is None or supplier["dd_expires_at"] <= clock:
            continue
        if feedstock_type in supplier["feedstock_types"]:
            return True
    return False


@bp.post("/pathway-registrations/<pathway_id>/submissions")
def submit_pathway(pathway_id):
    validate.auth("ComplianceOfficer")
    pathway = find("pathway", pathway_id)
    if pathway["status"] not in ("DRAFT", "RETURNED_FOR_INFO"):
        fail(ERR_INVALID_PATHWAY_STATE,
             "A registration at %s cannot be submitted." % pathway["status"])

    if not _has_verified_supplier(pathway["feedstock_type"]):
        fail(ERR_NO_VERIFIED_SUPPLIER,
             "No verified, unexpired supplier can deliver %s."
             % pathway["feedstock_type"])

    if pathway["status"] == "RETURNED_FOR_INFO":
        if pathway["revision_round"] >= MAX_REVISION_ROUNDS:
            fail(ERR_REVISION_LIMIT_EXCEEDED,
                 "The registration has already used its %d revision rounds."
                 % MAX_REVISION_ROUNDS)
        pathway["revision_round"] = pathway["revision_round"] + 1

    pathway["status"] = "SUBMITTED"
    pathway["info_request"] = None
    bump(pathway)
    return response.ok(pathway)


@bp.post("/pathway-registrations/<pathway_id>/review-starts")
def start_review(pathway_id):
    validate.auth("IndependentVerifier")
    pathway = find("pathway", pathway_id)
    if pathway["status"] != "SUBMITTED":
        fail(ERR_INVALID_PATHWAY_STATE,
             "Only a SUBMITTED registration may enter review; this one is %s."
             % pathway["status"])
    pathway["status"] = "UNDER_REVIEW"
    bump(pathway)
    return response.ok(pathway)


@bp.post("/pathway-registrations/<pathway_id>/review-decisions")
def decide_review(pathway_id):
    validate.auth("IndependentVerifier")
    pathway = find("pathway", pathway_id)
    data = validate.body()
    decision = validate.get_enum(data, "decision", ("REGISTER", "RETURN", "DENY"))
    certified_ci = None
    info_request = None
    if decision == "REGISTER":
        certified_ci = validate.get_num(data, "certified_ci", 0)
    elif decision == "RETURN":
        info_request = validate.get_str(data, "info_request", 1, 500)

    if pathway["status"] != "UNDER_REVIEW":
        fail(ERR_INVALID_PATHWAY_STATE,
             "Only an UNDER_REVIEW registration may be decided; this one is %s."
             % pathway["status"])

    if decision == "REGISTER":
        pathway["certified_ci_gco2e_per_mj"] = q(certified_ci, 2)
        pathway["status"] = "REGISTERED"
    elif decision == "RETURN":
        pathway["info_request"] = info_request
        pathway["status"] = "RETURNED_FOR_INFO"
    else:
        pathway["status"] = "DENIED"
    bump(pathway)
    return response.ok(pathway)
