"""Signature requests: sign / decline."""
from flask import Blueprint, request

import errors as E
import middleware as mw
from db import store, touch, pub, pub_list, fmt_dt
from response import ok_object, ok_list

bp = Blueprint("signatures", __name__)


def _load(uid, srid):
    rec = mw.get_or_404("signature_request", srid)
    # priority 4: signer scope check precedes state checks (PRD section 2.5).
    if uid != rec["agent_id"]:
        E.raise_err(E.ERR_SIGNATURE_NOT_AUTHORIZED,
                    "Acting agent does not match the signature request's agent_id")
    return rec


@bp.get("/tc/signature-requests/<signatureRequestId>")
def get_signature_request(signatureRequestId):
    mw.auth()
    rec = mw.get_or_404("signature_request", signatureRequestId)
    return ok_object(pub("signature_request", rec))


@bp.get("/tc/signature-requests")
def list_signature_requests():
    mw.auth()
    limit, offset = mw.page_params()
    recs = list(store.signature_requests.values())
    recs = mw.filter_eq(recs, "amendment_id", request.args.get("amendment_id"))
    recs = mw.filter_eq(recs, "agent_id", request.args.get("agent_id"))
    recs = mw.filter_eq(recs, "status", request.args.get("status"))
    round_raw = request.args.get("round_number")
    if round_raw is not None:
        try:
            round_no = int(round_raw)
        except (TypeError, ValueError):
            E.raise_err(E.ERR_INVALID_REQUEST, "round_number must be an integer")
        recs = [r for r in recs if r.get("round_number") == round_no]
    page, total = mw.apply_page(recs, limit, offset)
    return ok_list(pub_list("signature_request", page), limit, offset, total)


@bp.post("/tc/signature-requests/<signatureRequestId>/sign")
def sign(signatureRequestId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Agent"})
    rec = _load(uid, signatureRequestId)
    if rec["status"] != "PENDING":
        E.raise_err(E.ERR_SIGNATURE_INVALID_STATE, "Only a PENDING request can be signed")
    amendment = store.amendments.get(rec["amendment_id"])
    if amendment is None or amendment["status"] not in ("ROUTED", "PARTIALLY_SIGNED"):
        E.raise_err(E.ERR_AMENDMENT_INVALID_STATE,
                    "Owning amendment must be ROUTED or PARTIALLY_SIGNED")
    rec["status"] = "SIGNED"
    rec["signed_at"] = fmt_dt(store.now)
    touch(rec)
    round_reqs = [s for s in store.signature_requests.values()
                  if s["amendment_id"] == amendment["id"]
                  and s["round_number"] == amendment["round_number"]]
    if all(s["status"] == "SIGNED" for s in round_reqs):
        amendment["status"] = "FULLY_SIGNED"
        touch(amendment)
    elif amendment["status"] == "ROUTED":
        amendment["status"] = "PARTIALLY_SIGNED"
        touch(amendment)
    return ok_object(pub("signature_request", rec))


@bp.post("/tc/signature-requests/<signatureRequestId>/decline")
def decline(signatureRequestId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Agent"})
    rec = _load(uid, signatureRequestId)
    if rec["status"] != "PENDING":
        E.raise_err(E.ERR_SIGNATURE_INVALID_STATE, "Only a PENDING request can be declined")
    rec["status"] = "DECLINED"
    touch(rec)
    amendment = store.amendments.get(rec["amendment_id"])
    if amendment is not None:
        amendment["status"] = "REJECTED"
        touch(amendment)
        for s in store.signature_requests.values():
            if s["amendment_id"] == amendment["id"] \
                    and s["round_number"] == amendment["round_number"] \
                    and s["status"] == "PENDING":
                s["status"] = "VOIDED"
                touch(s)
    return ok_object(pub("signature_request", rec))
