"""Biopsies: pathology lifecycle + recall cascade (PRD 3.5)."""
from flask import Blueprint, request

import clock
import db
import errors
import helpers
import response
import services
from middleware import require

bp = Blueprint("biopsies", __name__)

BIOPSY_RESULTS = {"BENIGN", "MALIGNANT", "INDETERMINATE"}


@bp.post("/biopsies")
@require("Provider")
def collect_biopsy():
    data = helpers.body()
    encounter_id = helpers.require_str(data, "encounter_id")
    body_site = helpers.require_str(data, "body_site")
    enc = helpers.get_or_404(db.encounters, encounter_id, "encounter")
    # PRD 3.5: the encounter must be IN_PROGRESS.
    if enc["clinical_status"] != "IN_PROGRESS":
        raise errors.bad_state("ERR_ENCOUNTER_NOT_IN_PROGRESS")
    row = {
        "encounter_id": encounter_id,
        "patient_id": enc["patient_id"],  # copied from encounter at creation
        "body_site": body_site,
        "status": "COLLECTED",
        "result": None,
        "recall_months": None,
    }
    db.stamp_new(row)
    db.biopsies[row["id"]] = row
    services.recompute_open_biopsy_count(enc)
    return response.created(row)


@bp.get("/biopsies/<bid>")
@require("Provider", "PathLab", "PracticeAdmin", "BillingSpecialist")
def get_biopsy(bid):
    row = helpers.get_or_404(db.biopsies, bid, "biopsy")
    return response.ok(row)


@bp.get("/biopsies")
@require("Provider", "PathLab", "PracticeAdmin", "BillingSpecialist")
def list_biopsies():
    rows = list(db.biopsies.values())
    eid = request.args.get("encounter_id")
    if eid is not None:
        rows = [b for b in rows if b["encounter_id"] == eid]
    pid = request.args.get("patient_id")
    if pid is not None:
        rows = [b for b in rows if b["patient_id"] == pid]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing(page, limit, offset, total)


@bp.post("/biopsies/<bid>/send-to-lab")
@require("Provider")
def send_to_lab(bid):
    b = helpers.get_or_404(db.biopsies, bid, "biopsy")
    if b["status"] != "COLLECTED":
        raise errors.bad_state("ERR_BIOPSY_BAD_STATE")
    b["status"] = "AT_LAB"
    db.touch(b)
    # open_biopsy_count unchanged: both COLLECTED and AT_LAB count as open.
    return response.ok(b)


@bp.post("/biopsies/<bid>/result")
@require("PathLab")
def result_biopsy(bid):
    b = helpers.get_or_404(db.biopsies, bid, "biopsy")
    data = helpers.body()
    # State check (priority 6) before business-specific result validation.
    if b["status"] != "AT_LAB":
        raise errors.bad_state("ERR_BIOPSY_BAD_STATE")
    helpers.require_fields(data, "result")
    result = data["result"]
    if result not in BIOPSY_RESULTS:
        raise errors.invalid_biopsy_result()
    b["status"] = "RESULTED"
    b["result"] = result
    db.touch(b)
    # Bubble-up: RESULTED no longer counts as open.
    enc = db.encounters.get(b["encounter_id"])
    if enc is not None:
        services.recompute_open_biopsy_count(enc)
    return response.ok(b)


@bp.post("/biopsies/<bid>/sign-out")
@require("Provider")
def sign_out(bid):
    b = helpers.get_or_404(db.biopsies, bid, "biopsy")
    if b["status"] != "RESULTED":
        raise errors.bad_state("ERR_BIOPSY_BAD_STATE")
    b["status"] = "SIGNED_OUT"
    recall_months = services.BIOPSY_RECALL_MONTHS[b["result"]]
    b["recall_months"] = recall_months
    db.touch(b)
    # Spawn BIOPSY_FOLLOWUP recall.
    now = clock.now()
    due = helpers.add_months(now, recall_months)
    services.spawn_recall(b["patient_id"], "BIOPSY_FOLLOWUP", due, biopsy_id=b["id"])
    # Creating that reminder refreshes the patient's updated_at.
    patient = db.patients.get(b["patient_id"])
    if patient is not None:
        db.touch(patient)
    # MALIGNANT supersedes routine surveillance.
    if b["result"] == "MALIGNANT":
        for r in db.recall_reminders.values():
            if (r["patient_id"] == b["patient_id"]
                    and r["reason"] == "ROUTINE_SKIN_CHECK"
                    and r["status"] == "PENDING"):
                r["status"] = "DISMISSED"
                db.touch(r)
    return response.ok(b)


@bp.post("/biopsies/<bid>/cancel")
@require("Provider")
def cancel_biopsy(bid):
    b = helpers.get_or_404(db.biopsies, bid, "biopsy")
    if b["status"] != "COLLECTED":
        raise errors.bad_state("ERR_BIOPSY_BAD_STATE")
    b["status"] = "CANCELLED"
    db.touch(b)
    enc = db.encounters.get(b["encounter_id"])
    if enc is not None:
        services.recompute_open_biopsy_count(enc)
    return response.ok(b)
