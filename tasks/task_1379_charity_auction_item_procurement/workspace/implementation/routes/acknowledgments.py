"""DonorAcknowledgment routes (PRD 3.9)."""

from flask import Blueprint, request

import clock
import errors
import middleware as mw
import response
from db import stores

bp = Blueprint("acknowledgments", __name__)

READ = mw.ALL_ROLES
FO = ["FinanceOfficer"]


@bp.get("/acknowledgments/<rid>")
def get_acknowledgment(rid):
    mw.require_auth(READ)
    return response.success_object(mw.serialize(mw.get_or_404("acknowledgments", rid)))


@bp.get("/acknowledgments")
def list_acknowledgments():
    mw.require_auth(READ)
    limit, offset = mw.parse_pagination()
    items = list(stores["acknowledgments"].values())
    for f in ("donor_id", "gala_event_id", "item_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if str(a.get(f)) == v]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array([mw.serialize(a) for a in page], limit, offset, total)


@bp.post("/acknowledgments/<rid>/issue")
def issue_acknowledgment(rid):
    mw.require_auth(FO)
    ack = mw.get_or_404("acknowledgments", rid)
    if ack["status"] != "PENDING":
        raise errors.err_invalid_state("Issue requires status PENDING")
    event = stores["gala_events"][ack["gala_event_id"]]
    # Inclusive threshold: fmv exactly equal to ack_threshold_cents issues cleanly.
    if ack["fmv_cents"] < event["ack_threshold_cents"]:
        raise errors.err_ack_threshold_not_met()
    ack["status"] = "ISSUED"
    ack["issued_at"] = clock.now()
    mw.touch(ack)
    return response.success_object(mw.serialize(ack))


@bp.post("/acknowledgments/<rid>/void")
def void_acknowledgment(rid):
    mw.require_auth(FO)
    ack = mw.get_or_404("acknowledgments", rid)
    if ack["status"] not in ("PENDING", "ISSUED"):
        raise errors.err_invalid_state("Void requires status PENDING or ISSUED")
    ack["status"] = "VOIDED"
    mw.touch(ack)
    return response.success_object(mw.serialize(ack))
