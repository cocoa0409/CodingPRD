"""Case-type configuration endpoints (Supervisor admin)."""
from __future__ import annotations

from flask import Blueprint

from config import CASE_TYPES, VALID_RECEIPT_PREFIXES
from db import store
from errors import err_not_found, err_validation
from middleware import require_auth
from response import success
from services.serializers import serialize_case_type_config
from utils import new_uuid

from routes._helpers import (
    get_json,
    require_bool,
    require_enum,
    require_int,
    require_string,
)


bp = Blueprint("case_type_config", __name__)


@bp.post("/admin/case-type-config")
@require_auth(["Supervisor"])
def upsert_case_type_config():
    """Idempotent upsert keyed by case_type (PRD §3.3)."""
    body = get_json()

    case_type = require_enum(body, "case_type", CASE_TYPES)
    requires_biometrics = require_bool(body, "requires_biometrics")
    requires_interview = require_bool(body, "requires_interview")
    rfe_window = require_int(body, "rfe_response_window_days", min_value=1)
    requires_priority_date_current = require_bool(body, "requires_priority_date_current")
    receipt_prefix = require_enum(body, "receipt_prefix", VALID_RECEIPT_PREFIXES)

    with store.lock:
        now = store.now()
        existing = store.case_type_configs_by_type.get(case_type)
        if existing is not None:
            # Replace in place; immutable per PRD except for upsert flow.
            existing["requires_biometrics"] = requires_biometrics
            existing["requires_interview"] = requires_interview
            existing["rfe_response_window_days"] = rfe_window
            existing["requires_priority_date_current"] = requires_priority_date_current
            existing["receipt_prefix"] = receipt_prefix
            return success(serialize_case_type_config(existing), 201)
        entity = {
            "id": new_uuid(),
            "created_at": now,
            "case_type": case_type,
            "requires_biometrics": requires_biometrics,
            "requires_interview": requires_interview,
            "rfe_response_window_days": rfe_window,
            "requires_priority_date_current": requires_priority_date_current,
            "receipt_prefix": receipt_prefix,
        }
        store.case_type_configs[entity["id"]] = entity
        store.case_type_configs_by_type[case_type] = entity

    return success(serialize_case_type_config(entity), 201)


@bp.get("/admin/case-type-config/<case_type>")
@require_auth(["Petitioner", "Beneficiary", "Officer", "Supervisor"])
def get_case_type_config(case_type: str):
    config = store.case_type_configs_by_type.get(case_type)
    if config is None:
        raise err_not_found(f"CaseTypeConfig for {case_type} not found.")
    return success(serialize_case_type_config(config), 200)
