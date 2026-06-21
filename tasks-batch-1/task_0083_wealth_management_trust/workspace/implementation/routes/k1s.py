"""K-1 statements (computed satellite) (PRD §3.6)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_role, parse_pagination, paginate
from response import success
from services import serialize
from services.helpers import must_exist

bp = Blueprint("k1s", __name__)


def _trustee_appointed(trustee_id, trust_id):
    for ap in db.trustee_appointments.values():
        if ap["trust_id"] == trust_id and ap["trustee_id"] == trustee_id and ap["status"] == "ACTIVE":
            return True
    return False


@bp.route("/accounts/<aid>/k1s", methods=["GET"])
def list_account_k1s(aid):
    user_id, role = authenticate()
    require_role(role, {"TrustAdmin", "Trustee"})
    a = must_exist(db.accounts, aid)
    if role == "Trustee" and not _trustee_appointed(user_id, a["trust_id"]):
        raise err("ERR_NOT_OWNER")
    limit, offset = parse_pagination()
    beneficiary_id = request.args.get("beneficiary_id")
    items = [k for k in db.k1s.values() if k["account_id"] == aid]
    if beneficiary_id is not None:
        items = [k for k in items if k["beneficiary_id"] == beneficiary_id]
    page, meta = paginate(items, limit, offset)
    return success([serialize.k1(k) for k in page], pagination=meta)


@bp.route("/k1s/<kid>", methods=["GET"])
def get_k1(kid):
    user_id, role = authenticate()
    require_role(role, {"TrustAdmin", "Trustee", "Beneficiary"})
    k = must_exist(db.k1s, kid)
    if role == "Beneficiary" and user_id != k["beneficiary_id"]:
        raise err("ERR_NOT_OWNER")
    if role == "Trustee":
        a = db.accounts[k["account_id"]]
        if not _trustee_appointed(user_id, a["trust_id"]):
            raise err("ERR_NOT_OWNER")
    return success(serialize.k1(k))


@bp.route("/k1s", methods=["GET"])
def list_k1s():
    user_id, role = authenticate()
    require_role(role, {"TrustAdmin", "Beneficiary"})
    limit, offset = parse_pagination()
    beneficiary_id = request.args.get("beneficiary_id")
    if role == "Beneficiary":
        # A beneficiary may read only their own K-1s.
        if beneficiary_id is not None and beneficiary_id != user_id:
            raise err("ERR_NOT_OWNER")
        beneficiary_id = user_id
    items = list(db.k1s.values())
    if beneficiary_id is not None:
        items = [k for k in items if k["beneficiary_id"] == beneficiary_id]
    page, meta = paginate(items, limit, offset)
    return success([serialize.k1(k) for k in page], pagination=meta)
