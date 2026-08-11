"""Recovery intakes and match scanning (PRD §3.5, §3.7 disposition entry)."""
from datetime import timedelta

from flask import Blueprint, g, request

import db
from errors import fail
from middleware import body, require_roles
from models import intake_view
from response import list_response, ok_object
from routes.common import field, load
from services import calc
from util import normalize_serial

bp = Blueprint("intakes", __name__)


def _acting_org_active():
    """Stage 7 partner posture: the acting partner's org must be ACTIVE."""
    org = db.partner_orgs.get(g.user_id)
    if org is None or org["status"] != "ACTIVE":
        fail("ERR_PARTNER_ORG_NOT_ACTIVE", "The acting partner's organization is not ACTIVE")
    return org


@bp.post("/registry/recovery-intakes")
@require_roles("Partner")
def create_intake():
    data = body()
    serial_number_raw = field(data, "serial_number_raw", "string", required=True)
    primary_color = field(data, "primary_color", "string", required=True)
    found_at = field(data, "found_at", "datetime", required=True)
    found_location = field(data, "found_location", "string", required=True)
    appraised_value_cents = field(data, "appraised_value_cents", "integer", required=True, min_value=0)
    manufacturer = field(data, "manufacturer", "string", required=False, nullable=True)
    model = field(data, "model", "string", required=False, nullable=True)
    photo_url = field(data, "photo_url", "string", required=False, nullable=True)
    photo_hash = field(data, "photo_hash", "string", required=False, nullable=True, photo_hash=True)

    _acting_org_active()

    rec = db.new_record({
        "partner_org_id": g.user_id,
        "serial_number_raw": serial_number_raw,
        "serial_normalized": normalize_serial(serial_number_raw),
        "manufacturer": manufacturer,
        "model": model,
        "primary_color": primary_color,
        "photo_url": photo_url,
        "photo_hash": photo_hash,
        "found_at": found_at,
        "found_location": found_location,
        "appraised_value_cents": appraised_value_cents,
        "status": "INTAKE",
    })
    db.intakes[rec["id"]] = rec
    return ok_object(intake_view(rec), status=201)


@bp.get("/registry/recovery-intakes")
@require_roles("Partner", "Registrar", "Admin")
def list_intakes():
    recs = list(db.intakes.values())
    if g.role == "Partner":
        recs = [i for i in recs if i["partner_org_id"] == g.user_id]
    else:
        org_filter = request.args.get("partner_org_id")
        if org_filter is not None:
            recs = [i for i in recs if i["partner_org_id"] == org_filter]
    status = request.args.get("status")
    if status is not None:
        recs = [i for i in recs if i["status"] == status]
    return list_response(recs, intake_view)


@bp.get("/registry/recovery-intakes/<intake_id>")
@require_roles("Partner", "Registrar", "Admin")
def read_intake(intake_id):
    rec = load(db.intakes, intake_id, "ERR_RECOVERY_INTAKE_NOT_FOUND")
    if g.role == "Partner" and rec["partner_org_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Partners may read only their own organization's intakes")
    return ok_object(intake_view(rec))


@bp.post("/registry/recovery-intakes/<intake_id>/scan")
@require_roles("Partner", "Registrar")
def scan_intake(intake_id):
    rec = load(db.intakes, intake_id, "ERR_RECOVERY_INTAKE_NOT_FOUND")
    if g.role == "Partner":
        if rec["partner_org_id"] != g.user_id:
            fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Partners may scan only their own organization's intakes")
        _acting_org_active()

    # Candidate set: every FLAGGED theft report, created_at ASC.
    reports = sorted(
        (r for r in db.theft_reports.values() if r["status"] == "FLAGGED"),
        key=lambda r: (r["created_at"], r["_seq"]),
    )
    created_match_ids = []
    for report in reports:
        bicycle = db.bicycles.get(report["bicycle_id"])
        if bicycle is None:
            continue
        screening, forensic = calc.match_scores(rec, bicycle, report)
        existing = next(
            (m for m in db.matches.values()
             if m["recovery_intake_id"] == rec["id"] and m["theft_report_id"] == report["id"]),
            None,
        )
        if existing is None:
            status = "NOTIFIED" if screening >= calc.NOTIFY_THRESHOLD_BP else "PROPOSED"
            match = db.new_record({
                "recovery_intake_id": rec["id"],
                "theft_report_id": report["id"],
                "bicycle_id": report["bicycle_id"],
                "screening_score": screening,
                "forensic_score": forensic,
                "status": status,
            })
            db.matches[match["id"]] = match
            created_match_ids.append(match["id"])
            if status == "NOTIFIED":
                db.notify(report["owner_id"], "MATCH_FOUND",
                          "A recovered bicycle may match your theft report.",
                          related_entity_type="MatchCandidate", related_entity_id=match["id"])
        elif existing["status"] in ("PROPOSED", "NOTIFIED"):
            changed = (existing["screening_score"] != screening
                       or existing["forensic_score"] != forensic)
            existing["screening_score"] = screening
            existing["forensic_score"] = forensic
            # Re-scan upgrade: PROPOSED crossing the notify threshold enters NOTIFIED.
            if existing["status"] == "PROPOSED" and screening >= calc.NOTIFY_THRESHOLD_BP:
                existing["status"] = "NOTIFIED"
                changed = True
                db.notify(report["owner_id"], "MATCH_FOUND",
                          "A recovered bicycle may match your theft report.",
                          related_entity_type="MatchCandidate", related_entity_id=existing["id"])
            if changed:
                db.bump(existing)

    return ok_object({
        "created_match_ids": created_match_ids,
        "scanned_report_count": len(reports),
    })


@bp.post("/registry/recovery-intakes/<intake_id>/mark-unclaimed")
@require_roles("Registrar")
def mark_unclaimed(intake_id):
    rec = load(db.intakes, intake_id, "ERR_RECOVERY_INTAKE_NOT_FOUND")
    if rec["status"] != "INTAKE":
        fail("ERR_RECOVERY_NOT_ACTIONABLE", "Intake is not in INTAKE status")
    # Stage-12 board-clear checks precede the stage-14 thirty-day temporal wait.
    if any(m["recovery_intake_id"] == rec["id"] and m["status"] in ("PROPOSED", "NOTIFIED")
           for m in db.matches.values()):
        fail("ERR_INTAKE_HAS_ACTIVE_MATCH", "Active match candidates exist for this intake")
    if any(c["recovery_intake_id"] == rec["id"] and c["status"] == "UNDER_REVIEW"
           for c in db.claims.values()):
        fail("ERR_CLAIM_ALREADY_EXISTS", "An under-review claim exists for this intake")
    if db.now() < rec["created_at"] + timedelta(days=30):
        fail("ERR_DISPOSITION_TOO_EARLY", "The thirty-day disposition wait has not elapsed")
    rec["status"] = "UNCLAIMED"
    db.bump(rec)
    return ok_object(intake_view(rec))


@bp.post("/registry/recovery-intakes/<intake_id>/complete-return")
@require_roles("Partner")
def complete_return(intake_id):
    rec = load(db.intakes, intake_id, "ERR_RECOVERY_INTAKE_NOT_FOUND")
    if rec["partner_org_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Only the holding partner completes the return")
    _acting_org_active()
    if rec["status"] != "CLAIM_PENDING":
        fail("ERR_RECOVERY_NOT_ACTIONABLE", "Intake is not awaiting a return handoff")

    rec["status"] = "RETURNED"
    db.bump(rec)
    confirmed = next((m for m in db.matches.values()
                      if m["recovery_intake_id"] == rec["id"] and m["status"] == "CONFIRMED"), None)
    if confirmed is not None:
        bicycle = db.bicycles.get(confirmed["bicycle_id"])
        if bicycle is not None:
            bicycle["registry_status"] = "RETURNED"
            db.bump(bicycle)
    return ok_object(intake_view(rec))
