"""ApostilleRequest endpoints (PRD 3.7)."""
from flask import Blueprint

from db import store
from errors import ApiError
from middleware import require_roles
from response import success
from util import new_common, serialize, touch
from services.common import get_body, require_fields, require_str, require_enum, lookup
from services import ledger as ledger_svc

bp = Blueprint("apostilles", __name__)


def _owning_application(record):
    lic = store.licenses.get(record["license_id"])
    if lic is None:
        return None
    return store.applications.get(lic["application_id"])


@bp.route("/apostilles", methods=["POST"])
@require_roles("Clerk", "Applicant")
def create_apostille():
    body = get_body()
    require_fields(body, "copy_request_id", "destination_country")
    require_str(body["copy_request_id"], "copy_request_id")
    require_str(body["destination_country"], "destination_country")
    lookup("certified_copy", body["copy_request_id"])

    ent = new_common("apostille")
    ent.update({
        "copy_request_id": body["copy_request_id"],
        "destination_country": body["destination_country"],
        "status": "REQUESTED",
        "fee_cents": 0,
    })
    store.apostilles[ent["id"]] = ent
    return success(serialize(ent), status=201)


@bp.route("/apostilles/<apostille_id>", methods=["GET"])
@require_roles("Clerk", "Registrar", "Applicant")
def get_apostille(apostille_id):
    ent = lookup("apostille", apostille_id)
    return success(serialize(ent), status=200)


@bp.route("/apostilles/<apostille_id>/decide", methods=["POST"])
@require_roles("Registrar")
def decide_apostille(apostille_id):
    apo = lookup("apostille", apostille_id)
    body = get_body()
    require_fields(body, "decision")
    require_enum(body["decision"], {"AUTHENTICATE", "REJECT"}, "decision")
    decision = body["decision"]

    if apo["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Apostille is not REQUESTED")

    if decision == "REJECT":
        apo["status"] = "REJECTED"
        touch(apo)
        return success(serialize(apo), status=200)

    # AUTHENTICATE — copy must be ISSUED, its record must not be SEALED.
    copy = store.certified_copies.get(apo["copy_request_id"])
    if copy is None or copy["status"] != "ISSUED":
        raise ApiError("ERR_COPY_NOT_ISSUED", "Certified copy is not ISSUED")
    record = store.records.get(copy["record_id"])
    if record is not None and record["status"] == "SEALED":
        raise ApiError("ERR_RECORD_SEALED", "Record is sealed")

    from constants import APOSTILLE_FEE_CENTS
    apo["status"] = "AUTHENTICATED"
    apo["fee_cents"] = APOSTILLE_FEE_CENTS
    touch(apo)

    app = _owning_application(record) if record else None
    app_id = app["id"] if app else None
    ledger_svc.append_entry(app_id, "CHARGE", APOSTILLE_FEE_CENTS, "APOSTILLE", apo["id"])
    if app is not None:
        ledger_svc.recompute_total_charged(app)

    return success(serialize(apo), status=200)
