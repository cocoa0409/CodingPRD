"""Solicitation pipeline routes (PRD 3.2)."""

from flask import Blueprint

import clock
import errors
import middleware as mw
import response
from db import stores
from services import workflows as wf

bp = Blueprint("solicitations", __name__)

PO = ["ProcurementOfficer"]
READ = mw.ALL_ROLES


@bp.post("/solicitations")
def create_solicitation():
    mw.require_auth(PO)
    body = mw.get_json_body()
    donor_id = mw.require_string(body, "donor_id")
    mw.get_or_404("donors", donor_id)
    gala_event_id = mw.require_string(body, "gala_event_id")
    event = mw.get_or_404("gala_events", gala_event_id)
    ask_description = mw.require_string(body, "ask_description")
    ask_estimate_cents = mw.require_int(body, "ask_estimate_cents")
    # Cooldown applies at creation against other sent solicitations (PRD 3.2).
    wf.check_cooldown(donor_id, event)
    rec = mw.new_record()
    rec["donor_id"] = donor_id
    rec["gala_event_id"] = gala_event_id
    rec["ask_description"] = ask_description
    rec["ask_estimate_cents"] = ask_estimate_cents
    rec["status"] = "DRAFT"
    rec["last_sent_at"] = None
    stores["solicitations"][rec["id"]] = rec
    return response.success_object(mw.serialize(rec), 201)


@bp.get("/solicitations/<rid>")
def get_solicitation(rid):
    mw.require_auth(READ)
    return response.success_object(mw.serialize(mw.get_or_404("solicitations", rid)))


@bp.post("/solicitations/<rid>/send")
def send_solicitation(rid):
    mw.require_auth(PO)
    sol = mw.get_or_404("solicitations", rid)
    if sol["status"] not in ("DRAFT", "REVISED", "STALLED"):
        raise errors.err_invalid_state("Only DRAFT/REVISED/STALLED can be sent")
    event = stores["gala_events"][sol["gala_event_id"]]
    if event["status"] not in ("SOLICITING", "CATALOGING"):
        raise errors.err_event_phase_forbidden("Send requires event SOLICITING or CATALOGING")
    wf.check_cooldown(sol["donor_id"], event, exclude_id=sol["id"])
    sol["status"] = "SENT"
    sol["last_sent_at"] = clock.now()
    mw.touch(sol)
    return response.success_object(mw.serialize(sol))


@bp.post("/solicitations/<rid>/revise")
def revise_solicitation(rid):
    mw.require_auth(PO)
    sol = mw.get_or_404("solicitations", rid)
    body = mw.get_json_body()
    ask_description = mw.require_string(body, "ask_description")
    ask_estimate_cents = mw.require_int(body, "ask_estimate_cents")
    if sol["status"] != "SENT":
        raise errors.err_invalid_state("Only SENT can be revised")
    sol["status"] = "REVISED"
    sol["ask_description"] = ask_description
    sol["ask_estimate_cents"] = ask_estimate_cents
    mw.touch(sol)
    return response.success_object(mw.serialize(sol))


@bp.post("/solicitations/<rid>/record-response")
def record_response(rid):
    mw.require_auth(PO)
    sol = mw.get_or_404("solicitations", rid)
    body = mw.get_json_body()
    outcome = mw.require_enum(body, "outcome", {"PLEDGED", "DECLINED", "STALLED", "WITHDRAWN"})
    current = sol["status"]
    if outcome == "WITHDRAWN":
        if current not in ("DRAFT", "SENT", "REVISED", "STALLED"):
            raise errors.err_invalid_state("Only non-terminal solicitations can be withdrawn")
        sol["status"] = "WITHDRAWN"
    elif outcome == "PLEDGED":
        if current != "SENT":
            raise errors.err_invalid_state("PLEDGED requires status SENT")
        sol["status"] = "PLEDGED"
    elif outcome == "DECLINED":
        if current != "SENT":
            raise errors.err_invalid_state("DECLINED requires status SENT")
        sol["status"] = "DECLINED"
    else:  # STALLED
        if current != "SENT":
            raise errors.err_invalid_state("STALLED requires status SENT")
        sol["status"] = "STALLED"
    mw.touch(sol)
    return response.success_object(mw.serialize(sol))
