"""Disposition routes (PRD 3.9)."""

from flask import Blueprint, request

import errors
import middleware as mw
import response
from db import stores
from services import workflows as wf

bp = Blueprint("dispositions", __name__)

READ = mw.ALL_ROLES


@bp.get("/dispositions/<rid>")
def get_disposition(rid):
    mw.require_auth(READ)
    return response.success_object(mw.serialize(mw.get_or_404("dispositions", rid)))


@bp.get("/dispositions")
def list_dispositions():
    mw.require_auth(READ)
    limit, offset = mw.parse_pagination()
    items = list(stores["dispositions"].values())
    for f in ("gala_event_id", "item_id", "donor_id", "target_gala_event_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [d for d in items if str(d.get(f)) == v]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array([mw.serialize(d) for d in page], limit, offset, total)


@bp.post("/dispositions/<rid>/decide")
def decide_disposition(rid):
    mw.require_auth(["GalaAdmin"])
    disp = mw.get_or_404("dispositions", rid)
    body = mw.get_json_body()
    # Body FK existence (priority 4) when a target is supplied.
    target_id = body.get("target_gala_event_id")
    target = None
    if target_id is not None:
        if not isinstance(target_id, str):
            raise errors.err_invalid_request("target_gala_event_id must be a string")
        target = mw.get_or_404("gala_events", target_id)
    decision = mw.require_enum(body, "decision", {"RETURN_TO_DONOR", "ROLLOVER", "DISCARD"})
    if disp["status"] != "PROPOSED":
        raise errors.err_disposition_forbidden("Decide requires status PROPOSED")
    if decision == "ROLLOVER":
        if target is None:
            raise errors.err_rollover_target_invalid("ROLLOVER requires target_gala_event_id")
        if target["id"] == disp["gala_event_id"]:
            raise errors.err_rollover_target_invalid("Rollover target must differ from the source event")
        if target["status"] not in ("DRAFT", "SOLICITING", "CATALOGING"):
            raise errors.err_rollover_target_invalid("Rollover target must be DRAFT, SOLICITING, or CATALOGING")
        disp["target_gala_event_id"] = target["id"]
    else:
        disp["target_gala_event_id"] = None
    disp["decision"] = decision
    disp["status"] = "DONOR_NOTIFIED"
    mw.touch(disp)
    return response.success_object(mw.serialize(disp))


@bp.post("/dispositions/<rid>/donor-response")
def donor_response(rid):
    user_id, _ = mw.require_auth(["Donor"])
    disp = mw.get_or_404("dispositions", rid)
    # Ownership (priority 3): only the donor who must respond may answer.
    if disp["donor_id"] != user_id:
        raise errors.err_ownership("Only the disposition's donor may respond")
    body = mw.get_json_body()
    accept = mw.require_bool(body, "accept")
    if disp["status"] != "DONOR_NOTIFIED":
        raise errors.err_disposition_forbidden("Donor response requires status DONOR_NOTIFIED")
    if accept:
        disp["status"] = "EXECUTED"
        mw.touch(disp)
        wf.execute_disposition(disp)
    else:
        # Reconsideration cycle: back to PROPOSED with the decision cleared.
        disp["status"] = "PROPOSED"
        disp["decision"] = None
        disp["target_gala_event_id"] = None
        mw.touch(disp)
    return response.success_object(mw.serialize(disp))
