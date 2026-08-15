"""Acknowledgment signature cycle: respond SIGN/DECLINE, re-request (PRD §3.6)."""
from flask import Blueprint, request

import db
from db import homes, signatures
from errors import err_invalid_state, err_not_found
from logic import TERMINAL_ITEM_STATUSES, recompute_home
from middleware import (
    ROLE_BUYER, ROLE_MANAGER, ROLE_REP, check_buyer_ownership, require_roles,
)
from response import paginate, success_list, success_object
from validation import json_body, opt_str, req_enum

bp = Blueprint("signatures", __name__)

READ_ROLES = (ROLE_MANAGER, ROLE_REP, ROLE_BUYER)
DECISIONS = ("SIGN", "DECLINE")


def _get_signature_or_404(signature_id):
    sig = signatures.get(signature_id)
    if sig is None:
        raise err_not_found("Acknowledgment signature %s not found." % signature_id)
    return sig


@bp.get("/api/acknowledgment-signatures/<signature_id>")
def get_signature(signature_id):
    require_roles(*READ_ROLES)
    return success_object(db.public(_get_signature_or_404(signature_id)))


@bp.get("/api/acknowledgment-signatures")
def list_signatures():
    require_roles(*READ_ROLES)
    items = list(signatures.values())
    for f in ("home_id", "appointment_id", "signer_buyer_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if s.get(f) == v]
    items.sort(key=db.sort_key)
    page, pagination = paginate(items, request.args)
    return success_list([db.public(s) for s in page], pagination)


@bp.post("/api/acknowledgment-signatures/<signature_id>/respond")
def respond_signature(signature_id):
    actor = require_roles(ROLE_BUYER)
    # Priority 3 ownership: resolvable record -> buyer check before schema.
    sig = signatures.get(signature_id)
    if sig is not None:
        check_buyer_ownership(actor, homes[sig["home_id"]])
    body = json_body()
    decision = req_enum(body, "decision", DECISIONS)
    opt_str(body, "signature_payload")
    decline_reason = opt_str(body, "decline_reason")
    if sig is None:
        raise err_not_found("Acknowledgment signature %s not found." % signature_id)

    home = homes[sig["home_id"]]
    if decision == "SIGN":
        if sig["status"] not in ("PENDING", "STALE"):
            raise err_invalid_state("Only a PENDING or STALE acknowledgment can be signed.")
        sig["status"] = "SIGNED"
        sig["signer_buyer_id"] = actor.user_id
        sig["signed_at"] = db.fmt_dt(db.now())
        sig["decline_reason"] = None
        # Version-pin the count of the home's non-terminal deficiency items.
        sig["open_item_snapshot_count"] = sum(
            1 for i in db.deficiency_items.values()
            if i["home_id"] == home["id"] and i["status"] not in TERMINAL_ITEM_STATUSES
        )
        db.touch(sig)
        if home["status"] == "ORIENTED":
            home["status"] = "ACKNOWLEDGED"
            db.touch(home)
            # With no open before-closing items the home continues to
            # READY_TO_CLOSE in the same breath.
            recompute_home(home)
    else:  # DECLINE
        if sig["status"] != "PENDING":
            raise err_invalid_state("Only a PENDING acknowledgment can be declined.")
        sig["status"] = "DECLINED"
        sig["decline_reason"] = decline_reason
        db.touch(sig)
    return success_object(db.public(sig))


@bp.post("/api/acknowledgment-signatures/<signature_id>/re-request")
def re_request_signature(signature_id):
    require_roles(ROLE_REP)
    sig = _get_signature_or_404(signature_id)
    if sig["status"] != "DECLINED":
        raise err_invalid_state("Only a DECLINED acknowledgment can be re-requested.")
    sig["status"] = "PENDING"
    sig["decline_reason"] = None
    db.touch(sig)
    return success_object(db.public(sig))
