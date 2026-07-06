"""Specimen chain-of-custody and toxicology screens."""
from flask import Blueprint

import calculations
import errors
import lookup
import validate
from db import db
from middleware import require, json_body, paginate
from records import make_record, touch, public
from response import object_response, array_response

bp = Blueprint("specimens", __name__)

SPECIMEN_TYPES = {"BLOOD", "URINE", "VITREOUS", "TISSUE"}
PANELS = {"BASIC", "EXPANDED", "CONFIRMATORY"}


# ---- Specimens ----
@bp.post("/bodies/<body_id>/specimens")
def collect_specimen(body_id):
    require({"Pathologist"})
    lookup.body(body_id)
    body = json_body()
    specimen_type = validate.req_enum(body, "specimen_type", SPECIMEN_TYPES)

    rec = make_record({
        "body_id": body_id,
        "specimen_type": specimen_type,
        "collected_at": db.clock.now_iso(),
        "chain_status": "COLLECTED",
    })
    db.specimens[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/bodies/<body_id>/specimens")
def list_body_specimens(body_id):
    require({"Admin", "Pathologist", "MedicalExaminer", "Investigator"})
    lookup.body(body_id)
    rows = [s for s in db.specimens.values() if s["body_id"] == body_id]
    page, limit, offset, total = paginate(rows)
    return array_response([public(s) for s in page], limit, offset, total)


@bp.get("/specimens/<id_>")
def get_specimen(id_):
    require({"Admin", "Pathologist", "MedicalExaminer", "LabTech"})
    rec = lookup.specimen(id_)
    return object_response(public(rec), 200)


@bp.post("/specimens/<id_>/send-to-lab")
def send_to_lab(id_):
    require({"Pathologist"})
    rec = lookup.specimen(id_)
    if rec["chain_status"] != "COLLECTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Send-to-lab only allowed from COLLECTED")
    rec["chain_status"] = "SENT_TO_LAB"
    touch(rec)
    return object_response(public(rec), 200)


@bp.post("/specimens/<id_>/discard")
def discard_specimen(id_):
    require({"Pathologist"})
    rec = lookup.specimen(id_)
    if rec["chain_status"] != "COLLECTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Discard only allowed from COLLECTED")
    rec["chain_status"] = "DISCARDED"
    touch(rec)
    return object_response(public(rec), 200)


# ---- Tox screens ----
@bp.post("/specimens/<specimen_id>/tox-screens")
def order_tox(specimen_id):
    require({"Pathologist", "LabTech"})
    lookup.specimen(specimen_id)
    body = json_body()
    panel = validate.req_enum(body, "panel", PANELS)

    rec = make_record({
        "specimen_id": specimen_id,
        "panel": panel,
        "result_status": "ORDERED",
        "ethanol_mg_dl": 0,
        "interpretation": "PENDING",
    })
    db.tox_screens[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/specimens/<specimen_id>/tox-screens")
def list_tox(specimen_id):
    require({"Admin", "Pathologist", "MedicalExaminer", "LabTech"})
    lookup.specimen(specimen_id)
    rows = [t for t in db.tox_screens.values() if t["specimen_id"] == specimen_id]
    page, limit, offset, total = paginate(rows)
    return array_response([public(t) for t in page], limit, offset, total)


@bp.get("/tox-screens/<id_>")
def get_tox(id_):
    require({"Admin", "Pathologist", "MedicalExaminer", "LabTech"})
    rec = lookup.tox_screen(id_)
    return object_response(public(rec), 200)


@bp.post("/tox-screens/<id_>/result")
def result_tox(id_):
    require({"LabTech"})
    rec = lookup.tox_screen(id_)
    body = json_body()
    ethanol = validate.req_number(body, "ethanol_mg_dl", minimum=0)

    if rec["result_status"] != "ORDERED":
        raise errors.err(errors.ERR_INVALID_STATE, "Result only allowed from ORDERED")
    specimen = db.specimens.get(rec["specimen_id"])
    if specimen is None or specimen["chain_status"] != "SENT_TO_LAB":
        raise errors.err(errors.ERR_INVALID_STATE, "Parent specimen must be SENT_TO_LAB")

    rec["ethanol_mg_dl"] = ethanol
    rec["result_status"] = "RESULTED"
    rec["interpretation"] = calculations.tox_interpretation(ethanol)
    touch(rec)

    # cascade: specimen SENT_TO_LAB -> CONSUMED
    specimen["chain_status"] = "CONSUMED"
    touch(specimen)

    return object_response(public(rec), 200)


@bp.post("/tox-screens/<id_>/amend")
def amend_tox(id_):
    require({"LabTech"})
    rec = lookup.tox_screen(id_)
    body = json_body()
    ethanol = validate.req_number(body, "ethanol_mg_dl", minimum=0)

    if rec["result_status"] not in ("RESULTED", "AMENDED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Amend only allowed from RESULTED or AMENDED")

    rec["ethanol_mg_dl"] = ethanol
    rec["interpretation"] = calculations.tox_interpretation(ethanol)
    rec["result_status"] = "AMENDED"
    touch(rec)
    return object_response(public(rec), 200)
