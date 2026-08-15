"""Obligation register singleton and published versions (PRD §3.2)."""

from flask import Blueprint

from db import new_id, now_clock, store, touch
from errors import (ApiError, ERR_REGISTER_EMPTY, ERR_STALE_REGISTER_VERSION)
from middleware import auth_context, get_body, req_int, require_roles
from response import paginate, success_object
from serializers import (created_sorted, register_to_api,
                         register_version_to_api)
from services.audit import append_audit
from services.calculations import register_checksum

bp = Blueprint("register", __name__)


@bp.get("/compliance/obligation-register")
def get_register():
    auth_context()
    return success_object(register_to_api(store.register))


@bp.post("/compliance/obligation-register/publish")
def publish_register():
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    body = get_body()
    expected_version = req_int(body, "expected_register_version")

    register = store.register
    # OCC on the register.
    if expected_version != register["version"]:
        raise ApiError(ERR_STALE_REGISTER_VERSION, 412,
                       "expected_register_version != current "
                       "ObligationRegister.version")

    # Priority 7: at least one ACTIVE obligation.
    active_codes = sorted(
        o["obligation_code"] for o in store.obligations.values()
        if o["status"] == "ACTIVE")
    if not active_codes:
        raise ApiError(ERR_REGISTER_EMPTY, 409,
                       "Register publish attempted with zero ACTIVE obligations")

    version_number = register["current_version_number"] + 1
    clock = now_clock()
    version = {
        "id": new_id(),
        "created_at": clock,
        "version_number": version_number,
        "published_at": clock,
        "obligation_codes": active_codes,
        "obligation_count": len(active_codes),
        "register_checksum": register_checksum(version_number, active_codes),
    }
    store.register_versions[version["id"]] = version

    register["current_version_number"] += 1
    touch(register)

    append_audit(user_id, role, "POST /compliance/obligation-register/publish",
                 "ObligationRegister", register["id"])
    return success_object(register_version_to_api(version), status=201)


@bp.get("/compliance/obligation-register-versions")
def list_register_versions():
    auth_context()
    items = created_sorted(store.register_versions.values())
    return paginate(items, register_version_to_api)
