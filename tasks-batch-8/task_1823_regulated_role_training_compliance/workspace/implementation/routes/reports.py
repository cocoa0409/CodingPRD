"""Audit reports."""
from flask import Blueprint

from db import new_entity, now, store
from errors import bad_request, not_found
from middleware import require_any_authenticated, require_roles
from response import get_body, pub, req_enum, success
from services import generate_audit_metrics, recordkeeping_expiry

bp = Blueprint("reports", __name__)

METRIC_VARIANTS = ("STRICT", "AUDIT_LENIENT")


@bp.post("/audit-reports")
def create_audit_report():
    uid, _ = require_roles("Auditor")
    body = get_body()
    spec = body.get("population_spec")
    if not isinstance(spec, dict):
        raise bad_request("population_spec must be an object")
    regulator_id = spec.get("regulator_id")
    if not isinstance(regulator_id, str) or not regulator_id:
        raise bad_request("population_spec.regulator_id is required")
    role_id = spec.get("role_id")
    manager_id = spec.get("manager_id")
    if role_id is not None and not isinstance(role_id, str):
        raise bad_request("population_spec.role_id must be a string")
    if manager_id is not None and not isinstance(manager_id, str):
        raise bad_request("population_spec.manager_id must be a string")
    variant = req_enum(body, "metric_variant", METRIC_VARIANTS)
    regulator = store.regulators.get(regulator_id)
    if regulator is None:
        raise not_found("regulator not found")
    t = now()
    r = new_entity()
    r.update({
        "population_spec": {
            "regulator_id": regulator_id,
            "role_id": role_id,
            "manager_id": manager_id,
        },
        "metric_variant": variant,
        "created_by": uid,
        "generated_at": t,
        "metrics": generate_audit_metrics(
            {"regulator_id": regulator_id, "role_id": role_id, "manager_id": manager_id},
            variant),
        "recordkeeping_expires_at": recordkeeping_expiry(t, regulator),
    })
    store.reports[r["id"]] = r
    return success(pub(r), "object", 201)


@bp.get("/audit-reports/<rid>")
def read_audit_report(rid):
    require_any_authenticated()
    r = store.reports.get(rid)
    if r is None:
        raise not_found("audit report not found")
    return success(pub(r))
