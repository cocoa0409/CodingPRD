"""Certificate endpoints: listing, revoke (with failure cascade), transfer."""

from flask import Blueprint, request

from errors import raise_err, ERR_ACCOUNT_NOT_ACTIVE, ERR_CERTIFICATE_NOT_ACTIVE
from store import STORE, now_ts
from util import auth, require_role, forbidden, ok_object, body_json, req_str, \
    get_or_404
from services import add_strike, touch
from routes.generators import list_with_serializer

bp = Blueprint("certificates", __name__)


def serialize_certificate(c):
    return {k: v for k, v in c.items() if not k.startswith("_")}


@bp.get("/greenpower/certificates")
def list_certificates():
    auth()
    filters = {
        "generator_id": request.args.get("generator_id"),
        "account_id": request.args.get("account_id"),
        "status": request.args.get("status"),
        "vintage_month": request.args.get("vintage_month"),
        "region_code": request.args.get("region_code"),
    }
    return list_with_serializer(list(STORE["certificates"].values()), filters,
                                serialize_certificate)


@bp.get("/greenpower/certificates/<cid>")
def get_certificate(cid):
    auth()
    cert = get_or_404(STORE["certificates"], cid, "Certificate")
    return ok_object(serialize_certificate(cert))


def _fail_trades_referencing(cert_id):
    """Every ACCEPTED trade whose items reference cert_id -> FAILED; the
    trade's other locked certificates unlock; the seller is struck (with the
    three-strike suspension cascade)."""
    for trade in list(STORE["trades"].values()):
        if trade["status"] != "ACCEPTED":
            continue
        item_ids = [it["certificate_id"] for it in trade["items"]]
        if cert_id not in item_ids:
            continue
        for other_id in item_ids:
            if other_id == cert_id:
                continue
            other = STORE["certificates"].get(other_id)
            if other is not None and other["status"] == "LOCKED":
                other["status"] = "ACTIVE"
                touch(other)
        trade["status"] = "FAILED"
        touch(trade)
        seller = STORE["accounts"].get(trade["from_account_id"])
        if seller is not None:
            add_strike(seller)


@bp.post("/greenpower/certificates/<cid>/revoke")
def revoke_certificate(cid):
    uid, role = auth()
    require_role(role, "RegistryAdmin")
    cert = get_or_404(STORE["certificates"], cid, "Certificate")
    if cert["status"] not in ("ACTIVE", "LOCKED"):
        raise_err(ERR_CERTIFICATE_NOT_ACTIVE,
                  "Only an ACTIVE or LOCKED certificate may be revoked")
    was_locked = cert["status"] == "LOCKED"
    quantity = cert["quantity_mwh"]
    gen = STORE["generators"].get(cert["generator_id"])
    if gen is not None:
        gen["lifetime_minted_mwh"] -= quantity
        touch(gen)
    cert["status"] = "REVOKED"
    touch(cert)
    if was_locked:
        _fail_trades_referencing(cid)
    return ok_object(serialize_certificate(cert))


@bp.post("/greenpower/certificates/<cid>/transfer")
def transfer_certificate(cid):
    uid, role = auth()
    require_role(role, "RegistryAdmin", "BrokerTrader")
    body = body_json()
    to_account_id = req_str(body, "to_account_id")
    cert = get_or_404(STORE["certificates"], cid, "Certificate")
    target = get_or_404(STORE["accounts"], to_account_id, "Account")
    if role == "BrokerTrader" and uid != cert["account_id"]:
        forbidden("A BrokerTrader may only transfer certificates they hold")
    if target["status"] != "ACTIVE":
        raise_err(ERR_ACCOUNT_NOT_ACTIVE, "The receiving account is not ACTIVE")
    if cert["status"] != "ACTIVE":
        raise_err(ERR_CERTIFICATE_NOT_ACTIVE,
                  "Only an ACTIVE certificate may be transferred")
    cert["account_id"] = to_account_id
    touch(cert)
    return ok_object(serialize_certificate(cert))
