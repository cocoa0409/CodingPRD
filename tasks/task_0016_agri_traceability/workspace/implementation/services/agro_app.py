"""Agrochemical Application service."""

from flask import g

from common import (
    add_days_utc_midnight,
    get_json_body,
    paginate,
    parse_iso_datetime,
    parse_pagination,
    require_field,
    sort_by_created_at,
    stamp_create_immutable,
)
from db import db
from errors import (
    ERR_DOSAGE_EXCEEDED,
    ERR_FORBIDDEN,
    ERR_PROHIBITED_SUBSTANCE,
    ERR_REGISTRATION_NOT_FOUND,
    ERR_VALIDATION,
    raise_error,
)
from services.audit import record_audit
from services.planting_batch import (
    get_batch_or_404,
    recompute_earliest_legal_harvest,
)


def _serialize(app: dict) -> dict:
    return {
        "id": app["id"],
        "created_at": app["created_at"],
        "planting_batch_id": app["planting_batch_id"],
        "registration_no": app["registration_no"],
        "application_date": app["application_date"],
        "dosage_g_per_hectare": app["dosage_g_per_hectare"],
        "applied_by_user_id": app["applied_by_user_id"],
        "withdrawal_end_date": app.get("withdrawal_end_date"),
    }


def create_application(batch_id):
    body = get_json_body()
    registration_no = require_field(body, "registration_no", str)
    application_date = require_field(body, "application_date", str)
    dosage = body.get("dosage_g_per_hectare")
    if dosage is None:
        raise_error(ERR_VALIDATION, "missing required field dosage_g_per_hectare")
    try:
        dosage_f = float(dosage)
    except Exception:
        raise_error(ERR_VALIDATION, "dosage_g_per_hectare must be numeric")
    if dosage_f <= 0:
        raise_error(ERR_VALIDATION, "dosage_g_per_hectare must be > 0")

    app_dt = parse_iso_datetime(application_date, "application_date")

    with db.lock:
        batch = get_batch_or_404(batch_id)
        # Ownership check
        if batch["grower_id"] != g.user_id:
            raise_error(ERR_FORBIDDEN, "grower can only act on own batches")

        # State check
        if batch["status"] not in {"REGISTERED", "GROWING"}:
            from errors import ERR_INVALID_STATE
            raise_error(ERR_INVALID_STATE, f"cannot record application on batch in {batch['status']}")

        # application_date >= batch.planting_date
        pd = parse_iso_datetime(batch["planting_date"])
        if app_dt < pd:
            raise_error(ERR_VALIDATION, "application_date must be >= planting_date")

        # Priority order per scaffold §1.4:
        # 6. ERR_PROHIBITED_SUBSTANCE (business_safety, runs BEFORE registration check)
        # 9. ERR_REGISTRATION_NOT_FOUND (business_referential)
        # 14. ERR_DOSAGE_EXCEEDED (business_constraint)
        registry = db.pesticide_registry.get(registration_no)
        if registry is not None:
            if registry.get("prohibited"):
                ps = registry.get("prohibited_since")
                if ps is None:
                    raise_error(ERR_PROHIBITED_SUBSTANCE, "substance is prohibited")
                ps_dt = parse_iso_datetime(ps)
                # prohibited at application_date iff prohibited_since <= application_date
                if app_dt >= ps_dt:
                    raise_error(ERR_PROHIBITED_SUBSTANCE, "substance prohibited at application_date")
        if registry is None:
            raise_error(ERR_REGISTRATION_NOT_FOUND, f"registration_no {registration_no} not found")
        if dosage_f > float(registry["max_dosage_per_hectare_g"]):
            raise_error(ERR_DOSAGE_EXCEEDED, "dosage exceeds registry max_dosage_per_hectare_g")

        app = {
            "id": db.new_id(),
            "planting_batch_id": batch_id,
            "registration_no": registration_no,
            "application_date": application_date,
            "dosage_g_per_hectare": dosage_f,
            "applied_by_user_id": g.user_id,
            "withdrawal_end_date": add_days_utc_midnight(
                app_dt, registry["withdrawal_period_days"]
            ),
        }
        stamp_create_immutable(app)
        db.agrochemical_applications[app["id"]] = app

        # Side effects
        before_status = batch["status"]
        recompute_earliest_legal_harvest(batch)
        from common import stamp_update
        if batch["status"] == "REGISTERED":
            batch["status"] = "GROWING"
        stamp_update(batch)

        record_audit(
            "AgrochemicalApplication", app["id"], "CREATE", "CREATED",
            before_state=None,
            change_summary={"batch_id": batch_id, "registration_no": registration_no},
        )
        if before_status != batch["status"]:
            record_audit(
                "PlantingBatch", batch["id"], "STATE_TRANSITION", batch["status"],
                before_state=before_status,
                change_summary={"trigger": "first_agrochemical_application"},
            )
    return _serialize(app)


def list_applications(batch_id, args):
    get_batch_or_404(batch_id)
    limit, offset = parse_pagination()
    items = [a for a in db.agrochemical_applications.values()
             if a["planting_batch_id"] == batch_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return [_serialize(a) for a in page], limit, offset, total
