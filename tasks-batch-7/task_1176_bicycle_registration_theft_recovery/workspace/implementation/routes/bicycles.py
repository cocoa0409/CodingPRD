"""Bicycle registration (fees, waivers, duplicate auto-scan), reads, OCC PATCH
(PRD §3.2)."""
from datetime import timedelta

from flask import Blueprint, g, request

import db
from errors import fail
from middleware import body, require_roles
from models import bicycle_view
from response import list_response, ok_object
from routes.common import field, load
from services import calc
from util import normalize_serial

bp = Blueprint("bicycles", __name__)


def _scan_duplicates(new_serial_norm, new_mfr, new_model):
    """Stage-12 scan against pre-existing non-MERGED bicycles (created_at ASC).
    Returns (exact_collision_with_clear, flag_candidates[])."""
    candidates = sorted(
        (b for b in db.bicycles.values() if b["integrity_status"] != "MERGED"),
        key=lambda b: (b["created_at"], b["_seq"]),
    )
    flag_candidates = []
    for existing in candidates:
        probe = {"serial_normalized": new_serial_norm, "manufacturer": new_mfr, "model": new_model}
        exact = existing["serial_normalized"] == new_serial_norm
        if exact and existing["integrity_status"] == "CLEAR":
            return True, []
        confidence = calc.duplicate_confidence(probe, existing)
        if not exact and confidence >= calc.AUTO_FLAG_THRESHOLD_BP:
            flag_candidates.append((existing, confidence))
    return False, flag_candidates


def _validate_waiver(code):
    """A waiver is valid when it resolves, is unused, its event is not CANCELLED,
    and now <= event.ends_at + 30 days (PRD §3.2)."""
    reg = next((r for r in db.event_registrations.values() if r["waiver_code"] == code), None)
    if reg is None or reg["waiver_used"]:
        fail("ERR_WAIVER_CODE_INVALID", "Waiver code is unknown or already used")
    event = db.events.get(reg["event_id"])
    if event is None or event["status"] == "CANCELLED":
        fail("ERR_WAIVER_CODE_INVALID", "Waiver issuing event is cancelled")
    if db.now() > event["ends_at"] + timedelta(days=30):
        fail("ERR_WAIVER_CODE_INVALID", "Waiver code is past its freshness window")
    return reg


@bp.post("/registry/bicycles")
@require_roles("Owner")
def register_bicycle():
    data = body()
    serial_number = field(data, "serial_number", "string", required=True)
    manufacturer = field(data, "manufacturer", "string", required=True)
    model = field(data, "model", "string", required=True)
    primary_color = field(data, "primary_color", "string", required=True)
    declared_value_cents = field(data, "declared_value_cents", "integer", required=True, min_value=0)
    photo_url = field(data, "photo_url", "string", required=True)
    photo_hash = field(data, "photo_hash", "string", required=False, nullable=True, photo_hash=True)
    engraving_opt_in = field(data, "engraving_opt_in", "boolean", required=False) or False
    insurance_opt_in = field(data, "insurance_opt_in", "boolean", required=False) or False
    waiver_code = field(data, "waiver_code", "string", required=False, nullable=True)

    serial_normalized = normalize_serial(serial_number)

    # Stage 12: duplicate auto-scan (exact collision rejected outright).
    collision, flag_candidates = _scan_duplicates(serial_normalized, manufacturer, model)
    if collision:
        fail("ERR_DUPLICATE_SERIAL_ACTIVE",
             "A CLEAR bicycle with the same normalized serial already exists")

    # Stage 13: waiver validity.
    waiver_reg = None
    if waiver_code is not None:
        waiver_reg = _validate_waiver(waiver_code)

    fee = calc.registration_fee(declared_value_cents, insurance_opt_in, engraving_opt_in)
    waived = waiver_reg is not None
    if waived:
        fee = 0  # waiver applies a 100% discount AFTER per-component computation

    rec = db.new_record({
        "serial_number": serial_number,
        "serial_normalized": serial_normalized,
        "manufacturer": manufacturer,
        "model": model,
        "primary_color": primary_color,
        "declared_value_cents": declared_value_cents,
        "photo_url": photo_url,
        "photo_hash": photo_hash,
        "registration_fee_cents": fee,
        "waiver_code_used": waiver_code if waived else None,
        "current_owner_id": g.user_id,
        "registry_status": "REGISTERED",
        "integrity_status": "CLEAR",
    })
    db.bicycles[rec["id"]] = rec

    # Balanced ledger pair (PRD §2.8): REGISTRATION_FEE, or FEE_WAIVER 0 when waived.
    entry_type = "FEE_WAIVER" if waived else "REGISTRATION_FEE"
    db.post_ledger(entry_type, "DEBIT", "OWNER", fee,
                   owner_id=g.user_id, bicycle_id=rec["id"],
                   reference_note=f"Bicycle {rec['id']} registration fee")
    db.post_ledger(entry_type, "CREDIT", "PROGRAM", fee,
                   bicycle_id=rec["id"],
                   reference_note=f"Bicycle {rec['id']} registration fee")

    if waived:
        waiver_reg["waiver_used"] = True
        db.bump(waiver_reg)

    # Auto-flag side effects: OPEN flag + both bicycles CLEAR -> DUPLICATE_SUSPECT.
    for existing, confidence in flag_candidates:
        flag = db.new_record({
            "bicycle_a_id": existing["id"],   # pre-existing bicycle
            "bicycle_b_id": rec["id"],        # newly created bicycle
            "confidence_score": confidence,
            "status": "OPEN",
            "merged_into_bicycle_id": None,
            "note": None,
        })
        db.duplicate_flags[flag["id"]] = flag
        for bike in (existing, rec):
            if bike["integrity_status"] == "CLEAR":
                bike["integrity_status"] = "DUPLICATE_SUSPECT"
                db.bump(bike)

    return ok_object(bicycle_view(rec), status=201)


@bp.get("/registry/bicycles")
@require_roles("Owner", "Partner", "Registrar", "Admin")
def list_bicycles():
    recs = list(db.bicycles.values())
    if g.role == "Owner":
        recs = [b for b in recs if b["current_owner_id"] == g.user_id]
    else:
        owner_filter = request.args.get("current_owner_id")
        if owner_filter is not None:
            recs = [b for b in recs if b["current_owner_id"] == owner_filter]
    serial_q = request.args.get("serial_number")
    if serial_q is not None:
        norm_q = normalize_serial(serial_q)
        recs = [b for b in recs
                if b["serial_number"] == serial_q or b["serial_normalized"] == norm_q]
    registry_status = request.args.get("registry_status")
    if registry_status is not None:
        recs = [b for b in recs if b["registry_status"] == registry_status]
    integrity_status = request.args.get("integrity_status")
    if integrity_status is not None:
        recs = [b for b in recs if b["integrity_status"] == integrity_status]
    return list_response(recs, bicycle_view)


@bp.get("/registry/bicycles/<bicycle_id>")
@require_roles("Owner", "Partner", "Registrar", "Admin")
def read_bicycle(bicycle_id):
    rec = load(db.bicycles, bicycle_id, "ERR_BICYCLE_NOT_FOUND")
    if g.role == "Owner" and rec["current_owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Owners may read only their own bicycles")
    if g.role == "Partner" and rec["registry_status"] != "STOLEN":
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS",
             "Partners may read a bicycle only while it is STOLEN")
    return ok_object(bicycle_view(rec))


@bp.patch("/registry/bicycles/<bicycle_id>")
@require_roles("Owner")
def update_bicycle(bicycle_id):
    data = body()
    expected = field(data, "expected_bicycle_version", "integer", required=True)
    model = field(data, "model", "string", required=False)
    primary_color = field(data, "primary_color", "string", required=False)
    photo_url = field(data, "photo_url", "string", required=False)
    photo_hash = field(data, "photo_hash", "string", required=False, nullable=True, photo_hash=True)

    rec = load(db.bicycles, bicycle_id, "ERR_BICYCLE_NOT_FOUND")
    if rec["current_owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Owners may update only their own bicycles")
    # OCC guard (stage 8) precedes the bicycle state guards (stage 9).
    if expected != rec["version"]:
        fail("ERR_STALE_VERSION", "Bicycle version has advanced; re-read before updating")
    if rec["integrity_status"] == "MERGED":
        fail("ERR_BICYCLE_MERGED", "Merged bicycles accept no further operations")

    if "model" in data and model is not None:
        rec["model"] = model
    if "primary_color" in data and primary_color is not None:
        rec["primary_color"] = primary_color
    if "photo_url" in data and photo_url is not None:
        rec["photo_url"] = photo_url
    if "photo_hash" in data:
        rec["photo_hash"] = photo_hash
    db.bump(rec)
    return ok_object(bicycle_view(rec))
