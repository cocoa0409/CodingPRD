"""Department endpoints (PRD §3.1, OCC per §2.7)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_DEPARTMENT_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_VALIDATION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_endpoint
from services.core import department_spent, touch
from services.serializers import serialize_department
from util import CLOCK, new_id, next_seq
from validate import (
    get_body,
    opt_enum,
    opt_str,
    reject_unknown_fields,
    req_int,
    req_str,
)

bp = Blueprint("departments", __name__)

SIGNAGE = {"CURRENT", "DEFICIENT", "MISSING"}


@bp.post("/departments")
def create_department():
    authorized(["LanguageAccessCoordinator"])
    body = get_body()
    reject_unknown_fields(body, {"name", "service_area_code", "annual_budget_cents", "signage_status"})
    name = req_str(body, "name")
    service_area_code = req_str(body, "service_area_code")
    annual_budget_cents = req_int(body, "annual_budget_cents", non_negative=True)
    signage_status = opt_enum(body, "signage_status", SIGNAGE, default="CURRENT")
    now = CLOCK.now_iso()
    rec = {
        "id": new_id(),
        "name": name,
        "service_area_code": service_area_code,
        "annual_budget_cents": annual_budget_cents,
        "signage_status": signage_status,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["departments"][rec["id"]] = rec
    return success_object(serialize_department(rec), status=201)


@bp.get("/departments")
def list_departments():
    return list_endpoint("departments", serialize_department)


@bp.get("/departments/<rid>")
def get_department(rid):
    return get_one("departments", rid, ERR_DEPARTMENT_NOT_FOUND, serialize_department)


def _coerce_version(v):
    """expected_department_version: integer; a decimal string is coerced."""
    if isinstance(v, bool):
        raise_error(ERR_VALIDATION, "expected_department_version must be an integer")
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v.strip())
    raise_error(ERR_VALIDATION, "expected_department_version must be an integer")


@bp.patch("/departments/<rid>")
def patch_department(rid):
    authorized(["LanguageAccessCoordinator"])
    body = get_body()
    reject_unknown_fields(
        body,
        {"name", "service_area_code", "annual_budget_cents", "signage_status",
         "expected_department_version"},
    )
    # Shape (priority 3): expected_department_version is non-optional.
    if "expected_department_version" not in body or body.get("expected_department_version") is None:
        raise_error(ERR_VALIDATION, "expected_department_version is required")
    expected = _coerce_version(body.get("expected_department_version"))
    name = opt_str(body, "name")
    service_area_code = opt_str(body, "service_area_code")
    annual_budget_cents = None
    if "annual_budget_cents" in body and body.get("annual_budget_cents") is not None:
        annual_budget_cents = req_int(body, "annual_budget_cents", non_negative=True)
    signage_status = opt_enum(body, "signage_status", SIGNAGE)

    rec = require_path_dept(rid)
    # OCC (§2.7)
    if expected != rec["version"]:
        raise_error(ERR_STALE_VERSION, "expected_department_version does not match current version")
    # Fiscal gate (priority 9): budget may not drop below recorded spend.
    if annual_budget_cents is not None and annual_budget_cents < department_spent(rid):
        raise_error(ERR_VALIDATION, "annual_budget_cents may not be below spent_cents")

    if name is not None:
        rec["name"] = name
    if service_area_code is not None:
        rec["service_area_code"] = service_area_code
    if annual_budget_cents is not None:
        rec["annual_budget_cents"] = annual_budget_cents
    if signage_status is not None:
        rec["signage_status"] = signage_status
    touch(rec)
    return success_object(serialize_department(rec))


def require_path_dept(rid):
    from validate import require_path
    return require_path("departments", rid, ERR_DEPARTMENT_NOT_FOUND)
