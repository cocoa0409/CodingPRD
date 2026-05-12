"""Nurse profile + certification logic."""
from datetime import timedelta

import db
from clock import now, parse_iso, iso
from errors import err
from services.audit import audit
from services.constants import (
    MIN_TRAINING_HOURS, MIN_RECERT_TRAINING_HOURS,
    RECERT_VALIDITY_DAYS, EXPIRY_WARNING_DAYS, SPECIALTY_TAGS,
)
from services.util import require_str, require_enum, require_list, check_occ


GENDERS = {"M", "F", "O"}
KIND_VALUES = {"INITIAL", "RECERTIFICATION", "TRAINING", "DISQUALIFICATION"}
OUTCOMES = {"PASS", "FAIL"}


# ---------------------------------------------------------------- Helpers --
def _validate_specialty_tags(tags) -> list:
    if not isinstance(tags, list) or not tags:
        raise err("ERR_INVALID_REQUEST", "specialty_tags must be a non-empty array")
    for t in tags:
        if not isinstance(t, str) or t not in SPECIALTY_TAGS:
            raise err("ERR_INVALID_REQUEST", f"invalid specialty tag: {t}")
    return list(tags)


def _validate_languages(langs) -> list:
    if not isinstance(langs, list) or not langs:
        raise err("ERR_INVALID_REQUEST", "languages must be a non-empty array")
    for code in langs:
        if not isinstance(code, str) or not code.strip():
            raise err("ERR_INVALID_REQUEST", "languages must contain non-empty strings")
    return list(langs)


# ------------------------------------------------------------- Public API --
def create_nurse(body: dict) -> dict:
    full_name = require_str(body, "full_name")
    gender = require_enum(body, "gender", GENDERS)
    languages = _validate_languages(body.get("languages"))
    license_number = require_str(body, "license_number")
    specialty_tags = _validate_specialty_tags(body.get("specialty_tags"))

    if "home_lat" not in body or not isinstance(body["home_lat"], (int, float)) or isinstance(body["home_lat"], bool):
        raise err("ERR_INVALID_REQUEST", "home_lat is required and must be a number")
    if "home_lng" not in body or not isinstance(body["home_lng"], (int, float)) or isinstance(body["home_lng"], bool):
        raise err("ERR_INVALID_REQUEST", "home_lng is required and must be a number")
    home_lat = float(body["home_lat"])
    home_lng = float(body["home_lng"])
    if not (-90.0 <= home_lat <= 90.0) or not (-180.0 <= home_lng <= 180.0):
        raise err("ERR_INVALID_REQUEST", "home_lat/home_lng out of range")

    max_daily = body.get("max_daily_orders", 6)
    if isinstance(max_daily, bool) or not isinstance(max_daily, int):
        raise err("ERR_INVALID_REQUEST", "max_daily_orders must be an integer")
    if max_daily < 1:
        raise err("ERR_INVALID_REQUEST", "max_daily_orders must be >= 1")

    revenue_share = body.get("revenue_share_bps", 7000)
    if isinstance(revenue_share, bool) or not isinstance(revenue_share, int):
        raise err("ERR_INVALID_REQUEST", "revenue_share_bps must be an integer")
    if revenue_share < 0 or revenue_share > 10000:
        raise err("ERR_INVALID_REQUEST", "revenue_share_bps out of range")

    # Uniqueness on license_number
    for n in db.nurses.values():
        if n.get("license_number") == license_number:
            raise err("ERR_INVALID_REQUEST", "license_number already used")

    nurse = {
        "full_name": full_name,
        "gender": gender,
        "languages": languages,
        "license_number": license_number,
        "license_verified": False,
        "hospital_affiliation_verified": False,
        "specialty_tags": specialty_tags,
        "home_lat": home_lat,
        "home_lng": home_lng,
        "max_daily_orders": max_daily,
        "revenue_share_bps": revenue_share,
        "rating": 5.00,
        "certification_status": "PENDING",
        "certified_until": None,
    }
    db.stamp_create(nurse, common_fields=True)
    db.nurses[nurse["id"]] = nurse
    return nurse


def list_nurses(limit: int, offset: int, certification_status=None, specialty=None):
    rows = list(db.nurses.values())
    if certification_status is not None:
        rows = [r for r in rows if r.get("certification_status") == certification_status]
    if specialty is not None:
        rows = [r for r in rows if specialty in (r.get("specialty_tags") or [])]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset: offset + limit]
    return page, total


def get_nurse(nurse_id: str) -> dict:
    nurse = db.nurses.get(nurse_id)
    if nurse is None:
        raise err("ERR_NURSE_NOT_FOUND", f"nurse {nurse_id} not found")
    return nurse


# --------------------------------------------------- Certification records --
def create_certification_record(nurse_id: str, body: dict) -> dict:
    nurse = get_nurse(nurse_id)
    kind = require_enum(body, "kind", KIND_VALUES)
    outcome = require_enum(body, "outcome", OUTCOMES)
    eff_raw = require_str(body, "effective_at")
    try:
        effective_at_dt = parse_iso(eff_raw)
    except ValueError as e:
        raise err("ERR_INVALID_REQUEST", str(e))
    th = body.get("training_hours", 0)
    if isinstance(th, bool) or not isinstance(th, (int, float)):
        raise err("ERR_INVALID_REQUEST", "training_hours must be a number")
    if th < 0:
        raise err("ERR_INVALID_REQUEST", "training_hours must be >= 0")
    notes = body.get("notes", "")
    if notes is not None and not isinstance(notes, str):
        raise err("ERR_INVALID_REQUEST", "notes must be a string")

    record = {
        "nurse_id": nurse_id,
        "kind": kind,
        "training_hours": th,
        "outcome": outcome,
        "effective_at": iso(effective_at_dt),
        "notes": notes or "",
    }
    db.stamp_create(record, common_fields=False)
    db.certification_records[record["id"]] = record

    _apply_certification_state(nurse, record, effective_at_dt)
    return record


def _apply_certification_state(nurse: dict, record: dict, effective_at_dt) -> None:
    """Implements the certification state machine."""
    kind = record["kind"]
    outcome = record["outcome"]

    # Disqualification path
    if kind == "DISQUALIFICATION":
        if nurse["certification_status"] == "DISQUALIFIED":
            raise err("ERR_INVALID_STATE", "nurse is already DISQUALIFIED")
        nurse["certification_status"] = "DISQUALIFIED"
        db.stamp_update(nurse)
        # Cancel all OFFERED dispatches for this nurse, trigger re-dispatch
        from services.dispatch import cancel_offered_dispatches_for_nurse_and_redispatch
        cancel_offered_dispatches_for_nurse_and_redispatch(nurse["id"])
        audit("NURSE", nurse["id"], "DISQUALIFY", payload={"record_id": record["id"]})
        return

    # INITIAL: requires both verifications and >= 24h training (sum of INITIAL+TRAINING)
    # PRD §3.1: 'For this initial certification to advance the nurse from PENDING
    # to CERTIFIED, three conditions must hold...'  When any condition fails, the
    # CertificationRecord is still created but the nurse remains PENDING.
    if kind == "INITIAL" and outcome == "PASS":
        if nurse["certification_status"] != "PENDING":
            # Nurse has already advanced past PENDING; the record is recorded but
            # we don't re-advance.
            return
        if not nurse.get("license_verified"):
            return
        if not nurse.get("hospital_affiliation_verified"):
            return
        total_hours = sum(
            float(r.get("training_hours") or 0)
            for r in db.certification_records.values()
            if r["nurse_id"] == nurse["id"] and r["kind"] in ("INITIAL", "TRAINING")
        )
        if total_hours < MIN_TRAINING_HOURS:
            return
        nurse["certification_status"] = "CERTIFIED"
        nurse["certified_until"] = iso(effective_at_dt + timedelta(days=RECERT_VALIDITY_DAYS))
        db.stamp_update(nurse)
        audit("NURSE", nurse["id"], "CERTIFY", payload={"record_id": record["id"]})
        return

    # RECERTIFICATION: from EXPIRING (or CERTIFIED) back to CERTIFIED
    # When training hours are insufficient, the record is recorded but the nurse
    # state does not advance.
    if kind == "RECERTIFICATION" and outcome == "PASS":
        if nurse["certification_status"] not in ("EXPIRING", "CERTIFIED"):
            return
        # training hours since last successful certification
        last_cert_at = _last_cert_effective(nurse["id"])
        hours_since = sum(
            float(r.get("training_hours") or 0)
            for r in db.certification_records.values()
            if r["nurse_id"] == nurse["id"]
            and r["kind"] in ("TRAINING", "RECERTIFICATION", "INITIAL")
            and (last_cert_at is None or r["created_at"] >= last_cert_at)
            and r["id"] != record["id"]
        )
        # Include this record's hours too
        hours_since += float(record.get("training_hours") or 0)
        if hours_since < MIN_RECERT_TRAINING_HOURS:
            return
        nurse["certification_status"] = "CERTIFIED"
        nurse["certified_until"] = iso(effective_at_dt + timedelta(days=RECERT_VALIDITY_DAYS))
        db.stamp_update(nurse)
        audit("NURSE", nurse["id"], "RECERTIFY", payload={"record_id": record["id"]})
        return

    # TRAINING records do not change cert state directly.
    if kind == "TRAINING":
        return

    # FAIL outcomes do not change state but are recorded.


def _last_cert_effective(nurse_id: str):
    """Return the most recent INITIAL or RECERTIFICATION's effective_at as ISO string, or None."""
    candidates = [
        r for r in db.certification_records.values()
        if r["nurse_id"] == nurse_id and r["kind"] in ("INITIAL", "RECERTIFICATION")
        and r["outcome"] == "PASS"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: r["created_at"], reverse=True)
    return candidates[0]["created_at"]


def list_certification_records(nurse_id: str, limit: int, offset: int):
    get_nurse(nurse_id)  # raises if missing
    rows = [r for r in db.certification_records.values() if r["nurse_id"] == nurse_id]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    return rows[offset: offset + limit], total
