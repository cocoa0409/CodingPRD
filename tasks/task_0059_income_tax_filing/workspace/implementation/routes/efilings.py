from flask import Blueprint, request
import errors
from errors import err
from db import db, init_common, touch
from middleware import get_auth, require_roles
from response import success
from util import (get_body, require_str, require_int, require_enum,
                  paginate, sorted_by_created)
from serialize import public, public_list
from services.common import get_return_or_404, get_efiling_or_404, owner_check_return

bp = Blueprint("efilings", __name__)

OUTCOMES = {"ACCEPTED", "REJECTED"}


@bp.post("/tax-returns/<return_id>/efile")
def efile(return_id):
    user_id, role = get_auth()
    require_roles(role, {"Taxpayer"})
    ret = get_return_or_404(return_id)
    owner_check_return(role, user_id, ret)
    body = get_body()

    signature_pin = require_str(body, "signature_pin")
    expected_version = require_int(body, "expected_return_version")

    # state: transmission only from READY. DRAFT -> NOT_COMPUTED; else INVALID_STATE.
    if ret["status"] == "DRAFT":
        raise err(errors.ERR_RETURN_NOT_COMPUTED,
                  "Return must be computed and current before e-filing")
    if ret["status"] != "READY":
        raise err(errors.ERR_INVALID_STATE,
                  "e-file not defined from current state")

    # OCC
    if expected_version != ret["version"]:
        raise err(errors.ERR_STALE_RETURN_VERSION,
                  "expected_return_version does not match current return version")

    # already e-filed: a non-REJECTED submission exists for this return
    for s in db.efilings.values():
        if s["return_id"] == return_id and s["status"] != "REJECTED":
            raise err(errors.ERR_ALREADY_EFILED,
                      "A non-REJECTED e-file submission already exists for this return")

    sub = {
        "return_id": return_id,
        "status": "TRANSMITTED",
        "signature_pin": signature_pin,
        "ack_code": None,
        "snapshot_balance_due_cents": ret["balance_due_cents"],
        "superseded_by_amendment": False,
    }
    init_common(sub)
    db.efilings[sub["id"]] = sub
    touch(ret)
    return success(public(sub), status=201)


@bp.get("/efilings/<efiling_id>")
def get_efiling(efiling_id):
    user_id, role = get_auth()
    require_roles(role, {"Taxpayer", "Preparer", "IrsGateway"})
    sub = get_efiling_or_404(efiling_id)
    if role in ("Taxpayer", "Preparer"):
        ret = db.tax_returns.get(sub["return_id"])
        if ret is not None:
            owner_check_return(role, user_id, ret)
    return success(public(sub))


@bp.get("/efilings")
def list_efilings():
    user_id, role = get_auth()
    require_roles(role, {"Taxpayer", "Preparer", "IrsGateway"})
    items = list(db.efilings.values())
    if role in ("Taxpayer", "Preparer"):
        items = [s for s in items
                 if (db.tax_returns.get(s["return_id"]) or {}).get("taxpayer_id") == user_id]
    return_filter = request.args.get("return_id")
    if return_filter is not None:
        items = [s for s in items if s["return_id"] == return_filter]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)


@bp.post("/efilings/<efiling_id>/acknowledge")
def acknowledge(efiling_id):
    _, role = get_auth()
    require_roles(role, {"IrsGateway"})
    sub = get_efiling_or_404(efiling_id)
    body = get_body()

    outcome = require_enum(body, "outcome", OUTCOMES)
    ack_code = require_str(body, "ack_code")

    if sub["status"] != "TRANSMITTED":
        raise err(errors.ERR_INVALID_STATE,
                  "acknowledge only defined for a TRANSMITTED submission")

    ret = db.tax_returns.get(sub["return_id"])

    if outcome == "ACCEPTED":
        sub["status"] = "ACCEPTED"
        sub["ack_code"] = ack_code
        touch(sub)
        if ret is not None:
            ret["status"] = "FILED"
            touch(ret)
    else:  # REJECTED
        sub["status"] = "REJECTED"
        sub["ack_code"] = ack_code
        touch(sub)
        if ret is not None:
            ret["status"] = "REJECTED"
            touch(ret)

    return success(public(sub))
