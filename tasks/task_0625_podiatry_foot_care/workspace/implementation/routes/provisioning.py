"""Logical clock + practice/provider/modality provisioning (PRD §2.5, §3.1)."""

from flask import Blueprint

import clock
import db
import errors
import middleware as mw
import response as resp
import validate as v

bp = Blueprint("provisioning", __name__)

ALL_ROLES = {"PracticeAdmin", "Podiatrist", "BillingSpecialist", "FrontDesk", "PayerAgent"}


# ---- Logical clock (PRD §2.5) ----

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = mw.authenticate()
    mw.require_role(role, {"PracticeAdmin"})
    body = mw.get_body()
    dt = v.as_datetime(body, "to_iso8601", required=True)
    clock.set_current(dt)
    return resp.success({"current_utc": _clock_iso()}, 200)


@bp.route("/_clock", methods=["GET"])
def get_clock():
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    return resp.success({"current_utc": _clock_iso()}, 200)


def _clock_iso():
    from datetime import timezone
    dt = clock.now().astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---- Practices (PRD §3.1) ----

@bp.route("/podiatry/practices", methods=["POST"])
def create_practice():
    _, role = mw.authenticate()
    mw.require_role(role, {"PracticeAdmin"})
    body = mw.get_body()
    with db.lock():
        name = v.as_str(body, "name", required=True)
        npi = v.as_str(body, "npi", required=True)
        min_interval = v.as_int(body, "routine_care_min_interval_days",
                                required=False, default=61)
        fee_split = v.as_number(body, "fee_split_medicare_pct",
                                required=False, default=0.80)
        entity = {
            "name": name,
            "npi": npi,
            "routine_care_min_interval_days": min_interval,
            "fee_split_medicare_pct": fee_split,
        }
        db.stamp_common(entity)
        db.practices[entity["id"]] = entity
        return resp.success(entity, 201)


@bp.route("/podiatry/practices/<practice_id>", methods=["GET"])
def get_practice(practice_id):
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    entity = db.practices.get(practice_id)
    if entity is None:
        raise errors.not_found("Practice not found.")
    return resp.success(entity, 200)


# ---- Providers (PRD §3.1) ----

@bp.route("/podiatry/providers", methods=["POST"])
def create_provider():
    _, role = mw.authenticate()
    mw.require_role(role, {"PracticeAdmin"})
    body = mw.get_body()
    with db.lock():
        practice_id = v.as_str(body, "practice_id", required=True)
        if practice_id not in db.practices:
            raise errors.fk_not_found("practice_id references a non-existent practice.")
        full_name = v.as_str(body, "full_name", required=True)
        role_type = v.as_enum(body, "role_type", {"PODIATRIST", "NP_PA"}, required=True)
        is_active = v.as_bool(body, "is_active", default=True)
        entity = {
            "practice_id": practice_id,
            "full_name": full_name,
            "role_type": role_type,
            "is_active": is_active,
        }
        db.stamp_common(entity)
        db.providers[entity["id"]] = entity
        return resp.success(entity, 201)


@bp.route("/podiatry/providers", methods=["GET"])
def list_providers():
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    from flask import request
    practice_id = request.args.get("practice_id")
    items = [p for p in db.providers.values()
             if practice_id is None or p["practice_id"] == practice_id]
    page, meta = mw.paginate(items)
    return resp.success(page, 200, pagination=meta)


@bp.route("/podiatry/providers/<provider_id>", methods=["GET"])
def get_provider(provider_id):
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    entity = db.providers.get(provider_id)
    if entity is None:
        raise errors.not_found("Provider not found.")
    return resp.success(entity, 200)


# ---- Modalities (PRD §3.1) ----

@bp.route("/podiatry/modalities", methods=["POST"])
def create_modality():
    _, role = mw.authenticate()
    mw.require_role(role, {"PracticeAdmin"})
    body = mw.get_body()
    with db.lock():
        practice_id = v.as_str(body, "practice_id", required=True)
        if practice_id not in db.practices:
            raise errors.fk_not_found("practice_id references a non-existent practice.")
        name = v.as_str(body, "name", required=True)
        modality_type = v.as_enum(body, "modality_type",
                                  {"XRAY", "ULTRASOUND", "MRI"}, required=True)
        buffer_minutes = v.as_int(body, "cleanup_buffer_minutes",
                                  required=False, default=15)
        entity = {
            "practice_id": practice_id,
            "name": name,
            "modality_type": modality_type,
            "cleanup_buffer_minutes": buffer_minutes,
        }
        db.stamp_common(entity)
        db.modalities[entity["id"]] = entity
        return resp.success(entity, 201)


@bp.route("/podiatry/modalities", methods=["GET"])
def list_modalities():
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    from flask import request
    practice_id = request.args.get("practice_id")
    items = [m for m in db.modalities.values()
             if practice_id is None or m["practice_id"] == practice_id]
    page, meta = mw.paginate(items)
    return resp.success(page, 200, pagination=meta)


@bp.route("/podiatry/modalities/<modality_id>", methods=["GET"])
def get_modality(modality_id):
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    entity = db.modalities.get(modality_id)
    if entity is None:
        raise errors.not_found("Modality not found.")
    return resp.success(entity, 200)
