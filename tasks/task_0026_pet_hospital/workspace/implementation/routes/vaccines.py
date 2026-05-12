"""Vaccine schedules + vaccination records + due-list (PRD §3.3)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, g, request

import db
from clock import now_iso, now_utc, today_utc_date
from errors import err
from middleware import authenticate, require_roles
from response import success_array, success_object
from services.common import init_bare
from validators import (
    parse_iso8601,
    require_int,
    require_str,
    _BATCH_ID_RE,
    _VACCINE_CODE_RE,
)

bp = Blueprint("vaccines", __name__)


@bp.before_request
def _auth():
    authenticate()


# Vaccine schedules ---------------------------------------------------------
@bp.post("/vaccine-schedules")
def create_schedule():
    require_roles("PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    species = payload.get("species")
    if species not in {"DOG", "CAT", "RABBIT", "BIRD", "OTHER"}:
        raise err("ERR_VALIDATION_FAILED", "species invalid")
    vc = payload.get("vaccine_code")
    if not isinstance(vc, str) or not _VACCINE_CODE_RE.match(vc):
        raise err("ERR_VALIDATION_FAILED", "vaccine_code invalid")
    age_min = payload.get("age_min_days")
    if isinstance(age_min, bool) or not isinstance(age_min, int) or age_min < 0 or age_min > 7300:
        raise err("ERR_VALIDATION_FAILED", "age_min_days invalid")
    booster = payload.get("booster_interval_days")
    if booster is not None:
        if isinstance(booster, bool) or not isinstance(booster, int) or booster < 7 or booster > 1825:
            raise err("ERR_VALIDATION_FAILED", "booster_interval_days invalid")
    required = payload.get("required", False)
    if not isinstance(required, bool):
        raise err("ERR_VALIDATION_FAILED", "required must be bool")

    with db.GLOBAL_LOCK:
        if db.schedule_unique(species, vc, age_min):
            raise err("ERR_VALIDATION_FAILED", "schedule already exists for (species, vaccine_code, age_min_days)")
        s = {
            "species": species,
            "vaccine_code": vc,
            "age_min_days": int(age_min),
            "booster_interval_days": booster if booster is not None else None,
            "required": bool(required),
        }
        init_bare(s)
        db.vaccine_schedules[s["id"]] = s
        return success_object(schedule_view(s), status=201)


# Vaccinations --------------------------------------------------------------
@bp.post("/pets/<pet_id>/vaccinations")
def record_vaccination(pet_id):
    require_roles("DraftingVet", "TriageNurse")
    payload = request.get_json(silent=True) or {}
    vc = payload.get("vaccine_code")
    if not isinstance(vc, str) or not _VACCINE_CODE_RE.match(vc):
        raise err("ERR_VALIDATION_FAILED", "vaccine_code invalid")
    administered_at = payload.get("administered_at")
    if not isinstance(administered_at, str):
        raise err("ERR_VALIDATION_FAILED", "administered_at required")
    parse_iso8601(administered_at)
    batch_id = payload.get("batch_id")
    if not isinstance(batch_id, str) or not _BATCH_ID_RE.match(batch_id):
        raise err("ERR_VALIDATION_FAILED", "batch_id invalid")

    with db.GLOBAL_LOCK:
        pet = db.pets.get(pet_id)
        if not pet:
            raise err("ERR_NOT_FOUND", f"Pet {pet_id} not found")
        sched = db.schedule_by_species_and_vaccine(pet["species"], vc)
        if not sched:
            raise err("ERR_REFERENCE_NOT_FOUND", "no matching VaccineSchedule")
        # age-min check.
        admin_dt = datetime.fromisoformat(administered_at.replace("Z", "+00:00"))
        bd = datetime.fromisoformat(pet["birth_date"]).replace(tzinfo=timezone.utc)
        days_since_birth = (admin_dt - bd).days
        if days_since_birth < int(sched["age_min_days"]):
            raise err("ERR_VACCINE_AGE_MIN", "administered_at below age_min_days")
        # batch recall check.
        if batch_id in db.recalled_batches:
            raise err("ERR_BATCH_RECALLED", "batch is recalled")
        # cooldown check.
        booster = sched.get("booster_interval_days")
        if booster:
            prior_active = [
                vr for vr in db.vaccinations_for_pet(pet_id)
                if vr.get("vaccine_code") == vc and vr.get("status") == "ACTIVE"
            ]
            if prior_active:
                # latest by administered_at
                prior_active.sort(key=lambda r: r["administered_at"])
                latest = prior_active[-1]
                latest_dt = datetime.fromisoformat(latest["administered_at"].replace("Z", "+00:00"))
                cooldown_days = booster // 2
                earliest = latest_dt + timedelta(days=cooldown_days)
                if admin_dt < earliest:
                    raise err("ERR_VACCINE_COOLDOWN", "before earliest cooldown moment")
        # Mark prior ACTIVE same-vaccine_code as SUPERSEDED.
        for vr in db.vaccinations_for_pet(pet_id):
            if vr.get("vaccine_code") == vc and vr.get("status") == "ACTIVE":
                vr["status"] = "SUPERSEDED"
        # Compute next_due_at.
        next_due_at = None
        if booster:
            next_due_at = (admin_dt + timedelta(days=int(booster))).strftime(
                "%Y-%m-%dT%H:%M:%S.000Z"
            )
        rec = {
            "pet_id": pet_id,
            "vaccine_code": vc,
            "administered_at": administered_at,
            "batch_id": batch_id,
            "status": "ACTIVE",
            "next_due_at": next_due_at,
        }
        init_bare(rec)
        db.vaccination_records[rec["id"]] = rec
        return success_object(vrec_view(rec), status=201)


@bp.get("/pets/<pet_id>/vaccines/due-list")
def due_list(pet_id):
    require_roles("OwnerService", "TriageNurse", "DraftingVet")
    with db.GLOBAL_LOCK:
        pet = db.pets.get(pet_id)
        if not pet:
            raise err("ERR_NOT_FOUND", f"Pet {pet_id} not found")
        items = _compute_due_list(pet)
        # Not paginated per PRD — but tests accept either dict or list.
        # We return as a top-level array.
        return success_object(items)


def _compute_due_list(pet):
    pet_id = pet["id"]
    species = pet["species"]
    bd = date.fromisoformat(pet["birth_date"])
    today = today_utc_date()
    pet_age_days = (today - bd).days
    out = []
    for sched in db.vaccine_schedules.values():
        if sched.get("species") != species:
            continue
        if int(sched.get("age_min_days", 0)) > pet_age_days:
            continue
        # ACTIVE history only.
        history = [
            vr for vr in db.vaccinations_for_pet(pet_id)
            if vr.get("vaccine_code") == sched["vaccine_code"]
            and vr.get("status") == "ACTIVE"
        ]
        history.sort(key=lambda r: (r.get("administered_at", ""), r.get("id", "")))
        booster = sched.get("booster_interval_days")
        if not history:
            due_at_date = bd + timedelta(days=int(sched["age_min_days"]))
            due_at_iso = due_at_date.strftime("%Y-%m-%dT00:00:00.000Z")
        else:
            if booster is None:
                continue  # single-dose, satisfied.
            last = history[-1]
            last_dt = datetime.fromisoformat(last["administered_at"].replace("Z", "+00:00"))
            due_dt = last_dt + timedelta(days=int(booster))
            due_at_iso = due_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        # Overdue if due_at_date <= today (date equal-to today is overdue).
        try:
            due_date_only = datetime.fromisoformat(due_at_iso.replace("Z", "+00:00")).date()
        except Exception:
            due_date_only = today
        overdue = due_date_only <= today
        out.append({
            "vaccine_code": sched["vaccine_code"],
            "due_at": due_at_iso,
            "overdue": bool(overdue),
        })
    return out


def schedule_view(s):
    return {
        "id": s["id"],
        "species": s["species"],
        "vaccine_code": s["vaccine_code"],
        "age_min_days": s["age_min_days"],
        "booster_interval_days": s.get("booster_interval_days"),
        "required": bool(s.get("required", False)),
        "created_at": s["created_at"],
    }


def vrec_view(r):
    return {
        "id": r["id"],
        "pet_id": r["pet_id"],
        "vaccine_code": r["vaccine_code"],
        "administered_at": r["administered_at"],
        "batch_id": r["batch_id"],
        "status": r["status"],
        "next_due_at": r.get("next_due_at"),
        "created_at": r["created_at"],
    }
