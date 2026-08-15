"""ColorStandard endpoints (PRD §3.1) including the three-level approve cascade."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_CUSTOMER_OWNERSHIP_MISMATCH,
    ERR_INVALID_STATE_TRANSITION,
)
from middleware import ALL_ROLES, authenticate
from response import ok_object
from routes.common import (
    fk_exists,
    get_body,
    get_or_404,
    list_response,
    release_job_reservation,
    req_enum,
    req_int,
    req_str,
    ser_plain,
)
from util import touch

bp = Blueprint("color_standards", __name__)

SUBSTRATE_CLASSES = ("COATED", "UNCOATED")
# Jobs at or beyond IN_PRODUCTION are immune to the invalidation cascade.
PRODUCTION_PLUS = ("IN_PRODUCTION", "FINISHING", "FINISHED", "COMPLETE", "CANCELLED")


@bp.post("/plant/color-standards")
def create_color_standard():
    authenticate(("PlantAdmin",))
    data = get_body()
    fk_exists(db.customers, data, "customer_id")
    customer_id = req_str(data, "customer_id")
    ink_slot = req_str(data, "ink_slot")
    l_target = req_int(data, "l_target")
    a_target = req_int(data, "a_target")
    b_target = req_int(data, "b_target")
    tolerance = req_int(data, "tolerance_delta_e_milli", 0)
    substrate_class = req_enum(data, "substrate_class", SUBSTRATE_CLASSES)
    rec = db.new_record()
    rec.update({
        "customer_id": customer_id,
        "ink_slot": ink_slot,
        "l_target": l_target,
        "a_target": a_target,
        "b_target": b_target,
        "tolerance_delta_e_milli": tolerance,
        "substrate_class": substrate_class,
        "status": "DRAFT",
    })
    db.color_standards[rec["id"]] = rec
    return ok_object(ser_plain(rec), 201)


@bp.get("/plant/color-standards")
def list_color_standards():
    authenticate(ALL_ROLES)
    return list_response(
        db.color_standards.values(),
        ser_plain,
        [("customer_id", "customer_id", "str"),
         ("status", "status", "str"),
         ("ink_slot", "ink_slot", "str")],
    )


@bp.get("/plant/color-standards/<standardId>")
def get_color_standard(standardId):
    authenticate(ALL_ROLES)
    return ok_object(ser_plain(get_or_404(db.color_standards, standardId)))


@bp.post("/plant/color-standards/<standardId>/submit")
def submit_color_standard(standardId):
    authenticate(("PlantAdmin",))
    rec = get_or_404(db.color_standards, standardId)
    if rec["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a DRAFT standard can be submitted")
    rec["status"] = "PENDING_BRAND"
    touch(rec)
    return ok_object(ser_plain(rec))


@bp.post("/plant/color-standards/<standardId>/approve")
def approve_color_standard(standardId):
    user_id, _role = authenticate(("BrandQuality",))
    rec = get_or_404(db.color_standards, standardId)
    if user_id != rec["customer_id"]:
        raise ApiError(ERR_CUSTOMER_OWNERSHIP_MISMATCH, 403,
                       "X-User-ID must equal the standard's customer_id")
    if rec["status"] != "PENDING_BRAND":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a PENDING_BRAND standard can be approved")
    rec["status"] = "ACTIVE"
    touch(rec)

    # CASCADE L1: other ACTIVE standards of same (customer_id, ink_slot) -> SUPERSEDED
    superseded = [s for s in db.color_standards.values()
                  if s["id"] != rec["id"]
                  and s["customer_id"] == rec["customer_id"]
                  and s["ink_slot"] == rec["ink_slot"]
                  and s["status"] == "ACTIVE"]
    for s in superseded:
        s["status"] = "SUPERSEDED"
        touch(s)

    # CASCADE L2: non-terminal PressApprovals pinned to newly superseded standards
    # whose job has not reached IN_PRODUCTION -> INVALIDATED
    invalidated = []
    superseded_ids = {s["id"] for s in superseded}
    for approval in db.press_approvals.values():
        if approval["color_standard_id"] not in superseded_ids:
            continue
        if approval["status"] not in ("SUBMITTED", "REJECTED", "APPROVED"):
            continue
        job = db.jobs.get(approval["job_id"])
        if job is None or job["status"] in PRODUCTION_PLUS:
            continue
        prior_status = approval["status"]
        approval["status"] = "INVALIDATED"
        touch(approval)
        invalidated.append((prior_status, job))

    # CASCADE L3: each PRESS_READY job that lost an APPROVED approval -> ENGINEERING,
    # releasing its board reservation in full.
    for prior_status, job in invalidated:
        if prior_status == "APPROVED" and job["status"] == "PRESS_READY":
            job["status"] = "ENGINEERING"
            release_job_reservation(job, clear_stock_ref=True)
            touch(job)

    return ok_object(ser_plain(rec))
