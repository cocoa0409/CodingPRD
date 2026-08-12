"""Manual duplicate flags and merge resolution (PRD §3.8)."""
from flask import Blueprint, g, request

import db
from errors import fail
from middleware import body, require_roles
from models import duplicate_flag_view
from response import list_response, ok_object
from routes.common import field, load
from services import calc

bp = Blueprint("duplicate_flags", __name__)


@bp.post("/registry/duplicate-flags")
@require_roles("Partner", "Registrar")
def create_duplicate_flag():
    data = body()
    bicycle_a_id = field(data, "bicycle_a_id", "string", required=True)
    bicycle_b_id = field(data, "bicycle_b_id", "string", required=True)
    note = field(data, "note", "string", required=False, nullable=True)
    if bicycle_a_id == bicycle_b_id:
        fail("ERR_INVALID_REQUEST", "bicycle_a_id and bicycle_b_id must differ")

    if g.role == "Partner":
        org = db.partner_orgs.get(g.user_id)
        if org is None or org["status"] != "ACTIVE":
            fail("ERR_PARTNER_ORG_NOT_ACTIVE", "The acting partner's organization is not ACTIVE")

    bike_a = load(db.bicycles, bicycle_a_id, "ERR_BICYCLE_NOT_FOUND")
    bike_b = load(db.bicycles, bicycle_b_id, "ERR_BICYCLE_NOT_FOUND")
    for bike in (bike_a, bike_b):
        if bike["integrity_status"] == "MERGED":
            fail("ERR_BICYCLE_MERGED", "Merged bicycles accept no further operations")

    confidence = calc.duplicate_confidence(bike_a, bike_b)
    rec = db.new_record({
        "bicycle_a_id": bicycle_a_id,
        "bicycle_b_id": bicycle_b_id,
        "confidence_score": confidence,
        "status": "OPEN",
        "merged_into_bicycle_id": None,
        "note": note,
    })
    db.duplicate_flags[rec["id"]] = rec
    for bike in (bike_a, bike_b):
        if bike["integrity_status"] == "CLEAR":
            bike["integrity_status"] = "DUPLICATE_SUSPECT"
            db.bump(bike)
    return ok_object(duplicate_flag_view(rec), status=201)


@bp.get("/registry/duplicate-flags")
@require_roles("Partner", "Registrar", "Admin")
def list_duplicate_flags():
    recs = list(db.duplicate_flags.values())
    for param, key in (("bicycle_a_id", "bicycle_a_id"), ("bicycle_b_id", "bicycle_b_id"),
                       ("merged_into_bicycle_id", "merged_into_bicycle_id"),
                       ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            recs = [f for f in recs if f[key] == value]
    return list_response(recs, duplicate_flag_view)


@bp.get("/registry/duplicate-flags/<flag_id>")
@require_roles("Partner", "Registrar", "Admin")
def read_duplicate_flag(flag_id):
    rec = load(db.duplicate_flags, flag_id, "ERR_DUPLICATE_FLAG_NOT_FOUND")
    return ok_object(duplicate_flag_view(rec))


@bp.post("/registry/duplicate-flags/<flag_id>/confirm")
@require_roles("Registrar")
def confirm_duplicate_flag(flag_id):
    merged_into = field(body(), "merged_into_bicycle_id", "string", required=True)
    rec = load(db.duplicate_flags, flag_id, "ERR_DUPLICATE_FLAG_NOT_FOUND")
    if merged_into not in (rec["bicycle_a_id"], rec["bicycle_b_id"]):
        fail("ERR_INVALID_REQUEST", "merged_into_bicycle_id must name one of the flag pair")
    if rec["status"] != "OPEN":
        fail("ERR_FLAG_NOT_OPEN", "Only an OPEN flag can be confirmed")

    survivor_id = merged_into
    loser_id = (rec["bicycle_b_id"] if merged_into == rec["bicycle_a_id"]
                else rec["bicycle_a_id"])
    survivor = db.bicycles.get(survivor_id)
    loser = db.bicycles.get(loser_id)

    rec["merged_into_bicycle_id"] = merged_into
    rec["status"] = "CONFIRMED"
    db.bump(rec)

    if loser is not None and loser["integrity_status"] == "DUPLICATE_SUSPECT":
        loser["integrity_status"] = "MERGED"
        db.bump(loser)
        # Merge cascade: strip the loser's open obligations.
        for report in db.theft_reports.values():
            if report["bicycle_id"] == loser["id"] and report["status"] in ("UNDER_REVIEW", "NEEDS_INFO"):
                report["status"] = "WITHDRAWN"
                db.bump(report)
        for transfer in db.transfers.values():
            if transfer["bicycle_id"] == loser["id"] and transfer["status"] == "PENDING_ACCEPTANCE":
                transfer["status"] = "CANCELLED"
                db.bump(transfer)

    if survivor is not None and survivor["integrity_status"] == "DUPLICATE_SUSPECT":
        survivor["integrity_status"] = "CLEAR"
        db.bump(survivor)
    return ok_object(duplicate_flag_view(rec))


@bp.post("/registry/duplicate-flags/<flag_id>/dismiss")
@require_roles("Registrar")
def dismiss_duplicate_flag(flag_id):
    rec = load(db.duplicate_flags, flag_id, "ERR_DUPLICATE_FLAG_NOT_FOUND")
    if rec["status"] != "OPEN":
        fail("ERR_FLAG_NOT_OPEN", "Only an OPEN flag can be dismissed")
    rec["status"] = "DISMISSED"
    db.bump(rec)
    for bike_id in (rec["bicycle_a_id"], rec["bicycle_b_id"]):
        bike = db.bicycles.get(bike_id)
        if bike is not None and bike["integrity_status"] == "DUPLICATE_SUSPECT":
            bike["integrity_status"] = "CLEAR"
            db.bump(bike)
    return ok_object(duplicate_flag_view(rec))
