"""Provider endpoints incl. lifecycle PATCH (suspend / reinstate / terminate)."""

from flask import Blueprint

import db
import errors
import helpers
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.cascades import (
    provider_suspend_cascade,
    provider_reinstate_cascade,
    provider_terminate_cascade,
)

bp = Blueprint("providers", __name__)

PROVIDER_STATUSES = {"PENDING_LOAD", "EFFECTIVE", "SUSPENDED", "TERMINATED"}


@bp.route("/network/providers", methods=["POST"])
@require_roles("NetworkManager")
def create_provider(user_id, role):
    body = helpers.get_body()
    npi = helpers.req_str(body, "npi")
    legal_name = helpers.req_str(body, "legal_name")
    specialty = helpers.req_enum(body, "specialty", helpers.SPECIALTIES)
    ced = helpers.req_str(body, "contract_effective_date")
    helpers.parse_date(ced, "contract_effective_date")
    for p in db.providers.values():
        if p["npi"] == npi:
            raise errors.err_npi_duplicate()
    eff_date = helpers.parse_date(ced, "contract_effective_date")
    status = "EFFECTIVE" if eff_date <= helpers.clock_date() else "PENDING_LOAD"
    rec = {
        "npi": npi, "legal_name": legal_name, "specialty": specialty,
        "contract_effective_date": ced, "status": status, "terminated_at": None,
    }
    helpers.stamp_new(rec)
    db.providers[rec["id"]] = rec
    return success_object(helpers.ser_provider(rec), 201)


@bp.route("/network/providers", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_providers(user_id, role):
    limit, offset = helpers.get_pagination()
    status = helpers.query_enum("status", PROVIDER_STATUSES)
    specialty = helpers.query_enum("specialty", helpers.SPECIALTIES)
    items = list(db.providers.values())
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if specialty is not None:
        items = [p for p in items if p["specialty"] == specialty]
    page, total = helpers.paginate(items, limit, offset)
    return success_list([helpers.ser_provider(p) for p in page], limit, offset, total)


@bp.route("/network/providers/<pid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_provider(user_id, role, pid):
    rec = db.providers.get(pid)
    if rec is None:
        raise errors.err_provider_not_found()
    return success_object(helpers.ser_provider(rec))


@bp.route("/network/providers/<pid>", methods=["PATCH"])
@require_roles("NetworkManager")
def patch_provider(user_id, role, pid):
    rec = db.providers.get(pid)
    if rec is None:
        raise errors.err_provider_not_found()
    body = helpers.get_body()
    to_status = helpers.req_enum(body, "to_status", {"SUSPENDED", "EFFECTIVE", "TERMINATED"})
    cur = rec["status"]
    if to_status == "SUSPENDED":
        if cur != "EFFECTIVE":
            raise errors.err_provider_invalid_transition()
        rec["status"] = "SUSPENDED"
        helpers.touch(rec)
        provider_suspend_cascade(rec)
    elif to_status == "EFFECTIVE":
        if cur != "SUSPENDED":
            raise errors.err_provider_invalid_transition()
        rec["status"] = "EFFECTIVE"
        helpers.touch(rec)
        provider_reinstate_cascade(rec)
    else:  # TERMINATED
        if cur not in ("PENDING_LOAD", "EFFECTIVE", "SUSPENDED"):
            raise errors.err_provider_invalid_transition()
        rec["status"] = "TERMINATED"
        rec["terminated_at"] = helpers.now_iso()
        helpers.touch(rec)
        provider_terminate_cascade(rec)
    return success_object(helpers.ser_provider(rec))
