"""Violation notices: reads, extensions, voiding and abatement authority."""

from flask import Blueprint, g, request

import calc
import domain
from auth import auth, owner_must_match
from db import db, insert, sort_created
from errors import fail
from response import created, jsonable, ok, ok_list, touch
from validate import body, get_int, get_str, lookup, page, pagination

bp = Blueprint("notices", __name__, url_prefix="/fire-district")


def _notice(notice_id):
    return lookup("notices", notice_id, "ERR_NOTICE_NOT_FOUND")


@bp.get("/violation-notices/<notice_id>")
def read_notice(notice_id):
    auth("ProgramAdmin", "FireMarshal", "Inspector", "PropertyOwner")
    return ok(jsonable(_notice(notice_id)))


@bp.get("/violation-notices")
def list_notices():
    auth("ProgramAdmin", "FireMarshal", "PropertyOwner")
    limit, offset = pagination()
    supersedes = request.args.get("supersedes_notice_id")
    if supersedes is not None and supersedes not in db.notices:
        # PRD section 2.6: this filter value participates in reference integrity.
        fail("ERR_NOTICE_NOT_FOUND", "No such notice: %r." % supersedes)
    records = sort_created(list(db.notices.values()))
    for field in ("parcel_id", "inspection_id", "supersedes_notice_id", "status"):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r[field] == value]
    return ok_list(
        [jsonable(r) for r in page(records, limit, offset)], limit, offset, len(records)
    )


@bp.post("/violation-notices/<notice_id>/extend")
def extend_notice(notice_id):
    auth("ProgramAdmin", "PropertyOwner")
    notice = _notice(notice_id)
    owner_must_match(notice["parcel_id"])
    b = body()
    get_str(b, "reason")
    if notice["status"] not in ("ISSUED", "EXTENDED"):
        fail("ERR_INVALID_STATE", "This notice can no longer be extended.")
    if db.clock > notice["deadline_utc"]:
        fail("ERR_INVALID_STATE", "The compliance deadline has already lapsed.")
    if notice["extension_count"] >= calc.MAX_EXTENSIONS:
        fail(
            "ERR_EXTENSION_LIMIT_REACHED",
            "The single permitted extension has already been granted.",
        )
    notice["deadline_utc"] = calc.end_of_day(notice["deadline_utc"], calc.EXTENSION_DAYS)
    notice["extension_count"] += 1
    notice["status"] = "EXTENDED"
    touch(notice)
    return ok(jsonable(notice))


@bp.post("/violation-notices/<notice_id>/void")
def void_notice(notice_id):
    auth("FireMarshal")
    notice = _notice(notice_id)
    b = body()
    reason = get_str(b, "reason")
    if notice["status"] not in ("ISSUED", "EXTENDED", "OVERDUE"):
        fail("ERR_INVALID_STATE", "Only an open notice can be voided.")
    for order in domain.notice_orders(notice["id"]):
        if order["verified_by_inspector_id"] and order["verified_by_inspector_id"] == g.user_id:
            fail(
                "ERR_SEGREGATION_OF_DUTIES",
                "The recorded verifier of the abatement work may not void this notice.",
            )
    notice["status"] = "VOIDED"
    notice["void_reason"] = reason
    touch(notice)
    parcel = db.parcels.get(notice["parcel_id"])
    domain.recompute_parcel_posture(parcel)
    touch(parcel)
    domain.cascade_parcel_posture(parcel)
    return ok(jsonable(notice))


@bp.post("/violation-notices/<notice_id>/authorize-abatement")
def authorize_abatement(notice_id):
    auth("FireMarshal")
    notice = _notice(notice_id)
    b = body()
    estimated = get_int(b, "estimated_cost_cents", minimum=0)
    if notice["status"] != "OVERDUE":
        fail("ERR_NOTICE_NOT_OVERDUE", "Abatement authority attaches only to an OVERDUE notice.")
    if domain.notice_order(notice["id"]) is not None:
        fail("ERR_INVALID_STATE", "This notice already carries a live abatement order.")
    if estimated > calc.ABATEMENT_CAP_CENTS:
        fail(
            "ERR_ABATEMENT_CAP_EXCEEDED",
            "The estimate exceeds the per-order ceiling of %d cents."
            % calc.ABATEMENT_CAP_CENTS,
        )
    order = insert(db.orders, {
        "violation_notice_id": notice["id"],
        "contractor_id": None,
        "verified_by_inspector_id": None,
        "status": "AUTHORIZED",
        "estimated_cost_cents": estimated,
        "crew_hours": None,
        "work_start_utc": None,
        "work_end_utc": None,
        "actual_crew_hours": None,
        "green_waste_tons": None,
        "labor_line_cents": None,
        "disposal_line_cents": None,
        "mobilization_line_cents": None,
        "admin_overhead_cents": None,
        "pre_subsidy_total_cents": None,
        "subsidy_pct": None,
        "district_subsidy_cents": None,
        "total_recoverable_cents": None,
        "recovery_basis": None,
        "paid_cents": 0,
        "lien_amount_cents": 0,
        "invoice_due_utc": None,
        "cancel_reason": None,
    })
    notice["status"] = "ABATEMENT_AUTHORIZED"
    touch(notice)
    parcel = db.parcels.get(notice["parcel_id"])
    domain.recount_open_violations(parcel)
    parcel["compliance_status"] = "ABATEMENT_PENDING"
    touch(parcel)
    domain.cascade_parcel_posture(parcel)
    return created(jsonable(order))
