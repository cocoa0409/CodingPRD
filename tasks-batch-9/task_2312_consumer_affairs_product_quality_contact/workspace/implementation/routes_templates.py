"""Canned consumer-response templates."""

from flask import Blueprint

import serializers as ser
from common import (
    ROLE_CARE_AGENT,
    ROLE_CARE_SUPERVISOR,
    ROLE_QUALITY_LEAD,
    authorize,
    base_record,
    check_required,
    err,
    get_body,
    must_get,
    pagination,
    paginated,
    q_str,
    sort_records,
    store,
    success,
    touch,
    unique_or_conflict,
    v_bool,
    v_enum,
    v_string,
)

bp = Blueprint("templates", __name__)

APPLIES_TO = ("FOREIGN_MATERIAL", "ILLNESS", "PACKAGING", "QUALITY", "ANY")
BANDS = ("S1", "S2", "S3", "S4")


@bp.post("/response-templates")
def create_template():
    authorize([ROLE_CARE_SUPERVISOR])
    payload = get_body()
    check_required(
        payload, ["template_code", "title", "body", "applies_to_type", "max_band_allowed"]
    )
    template_code = v_string(payload, "template_code", 1)
    title = v_string(payload, "title", 1)
    text = v_string(payload, "body", 1, 4000)
    applies_to_type = v_enum(payload, "applies_to_type", APPLIES_TO)
    max_band_allowed = v_enum(payload, "max_band_allowed", BANDS)
    requires_supervisor_approval = v_bool(payload, "requires_supervisor_approval", False)

    unique_or_conflict("response_templates", "template_code", template_code)

    rec = base_record()
    rec.update(
        {
            "template_code": template_code,
            "title": title,
            "body": text,
            "applies_to_type": applies_to_type,
            "max_band_allowed": max_band_allowed,
            "requires_supervisor_approval": requires_supervisor_approval,
            "status": "DRAFT",
            "usage_count": 0,
        }
    )
    store.response_templates[rec["id"]] = rec
    return success(ser.response_template(rec), 201)


@bp.get("/response-templates")
def list_templates():
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD])
    limit, offset = pagination()
    filters = {
        "applies_to_type": q_str("applies_to_type"),
        "status": q_str("status"),
        "max_band_allowed": q_str("max_band_allowed"),
    }
    items = []
    for rec in sort_records(list(store.response_templates.values())):
        if any(value is not None and rec.get(key) != value for key, value in filters.items()):
            continue
        items.append(ser.response_template(rec))
    return paginated(items, limit, offset)


@bp.get("/response-templates/<record_id>")
def get_template(record_id):
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD])
    rec = must_get("response_templates", record_id)
    return success(ser.response_template(rec))


@bp.post("/response-templates/<record_id>/activate")
def activate_template(record_id):
    authorize([ROLE_CARE_SUPERVISOR])
    rec = must_get("response_templates", record_id)
    get_body()
    if rec["status"] != "DRAFT":
        raise err("ERR_TEMPLATE_STATE_INVALID", "only a DRAFT template may be activated")
    rec["status"] = "ACTIVE"
    touch(rec)
    return success(ser.response_template(rec))


@bp.post("/response-templates/<record_id>/retire")
def retire_template(record_id):
    authorize([ROLE_CARE_SUPERVISOR])
    rec = must_get("response_templates", record_id)
    payload = get_body()
    v_string(payload, "reason", 0)
    if rec["status"] != "ACTIVE":
        raise err("ERR_TEMPLATE_STATE_INVALID", "only an ACTIVE template may be retired")
    rec["status"] = "RETIRED"
    touch(rec)
    return success(ser.response_template(rec))
