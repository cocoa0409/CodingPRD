from decimal import Decimal

from flask import Blueprint, request

from core import (ERR_INVALID_REQUEST, ApiError, body, db, list_response,
                  new_resource, ok, req_int, req_str, require_roles, touch)
from logic import (LOW_EFFORT_MIN_PCT, SPEEDER_MIN_SECONDS, cell_touch,
                   compute_award_amount, recompute_streak)
from serializers import ser_response

bp = Blueprint("responses", __name__)


def get_response_or_404(response_id):
    r = db.responses.get(response_id)
    if r is None:
        raise ApiError("ERR_RESPONSE_NOT_FOUND", 404, "Response not found")
    return r


@bp.post("/feedback-panel/responses")
@require_roles("PanelManager")
def create_response():
    data = body()
    invitation_id = req_str(data, "invitation_id")
    inv = db.invitations.get(invitation_id)
    if inv is None:
        raise ApiError("ERR_INVITATION_NOT_FOUND", 404, "Invitation not found")
    answers_payload = data.get("answers_payload")
    if not isinstance(answers_payload, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "answers_payload must be an object")
    completeness_pct = data.get("completeness_pct")
    if (isinstance(completeness_pct, bool)
            or not isinstance(completeness_pct, (int, float))):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "completeness_pct must be a number")
    pct = Decimal(str(completeness_pct))
    if pct < 0 or pct > 100:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "completeness_pct must lie between 0 and 100 inclusive")
    completion_seconds = req_int(data, "completion_seconds", min_value=0)
    if inv["status"] != "SENT":
        raise ApiError("ERR_INVITATION_NOT_OPEN", 409,
                       "Response submission requires invitation status SENT")
    speeder = completion_seconds < SPEEDER_MIN_SECONDS
    low_effort = pct < LOW_EFFORT_MIN_PCT

    inv["status"] = "COMPLETED"
    touch(inv)
    wave = db.waves[inv["wave_id"]]
    wave["completed_count"] += 1
    touch(wave)
    panelist = db.panelists[inv["panelist_id"]]
    cell = db.cells.get(panelist["home_cell_id"])
    if cell is not None:
        cell["reserved_count"] -= 1
        cell_touch(cell)
    recompute_streak(panelist)

    resp = new_resource()
    resp.update({
        "invitation_id": inv["id"],
        "wave_id": inv["wave_id"],
        "panelist_id": inv["panelist_id"],
        "answers_payload": answers_payload,
        "completeness_pct": completeness_pct,
        "completion_seconds": completion_seconds,
        "speeder_flag": speeder,
        "low_effort_flag": low_effort,
        "status": "SUBMITTED",
    })
    db.responses[resp["id"]] = resp

    award = new_resource()
    award.update({
        "response_id": resp["id"],
        "wave_id": inv["wave_id"],
        "amount_cents": compute_award_amount(wave, panelist, completeness_pct, speeder),
        "eligibility_status": "PENDING",
        "payout_status": "UNPAID",
        "_panelist_id": inv["panelist_id"],
    })
    db.awards[award["id"]] = award
    return ok(ser_response(resp), 201)


@bp.get("/feedback-panel/responses")
@require_roles("PanelManager", "DataAnalyst")
def list_responses():
    items = list(db.responses.values())
    invitation_id = request.args.get("invitation_id")
    if invitation_id is not None:
        items = [r for r in items if r["invitation_id"] == invitation_id]
    wave_id = request.args.get("wave_id")
    if wave_id is not None:
        items = [r for r in items if r["wave_id"] == wave_id]
    panelist_id = request.args.get("panelist_id")
    if panelist_id is not None:
        items = [r for r in items if r["panelist_id"] == panelist_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items, ser_response)


@bp.get("/feedback-panel/responses/<response_id>")
@require_roles("PanelManager", "DataAnalyst")
def get_response(response_id):
    return ok(ser_response(get_response_or_404(response_id)))


def _award_of(resp):
    for a in db.awards.values():
        if a["response_id"] == resp["id"]:
            return a
    return None


@bp.post("/feedback-panel/responses/<response_id>/accept")
@require_roles("DataAnalyst")
def accept(response_id):
    resp = get_response_or_404(response_id)
    if resp["status"] not in ("SUBMITTED", "QUARANTINED"):
        raise ApiError("ERR_RESPONSE_NOT_REVIEWABLE", 409,
                       "Accept requires response status SUBMITTED or QUARANTINED")
    resp["status"] = "ACCEPTED"
    touch(resp)
    award = _award_of(resp)
    if award is not None and award["eligibility_status"] == "PENDING":
        award["eligibility_status"] = "ELIGIBLE"
        touch(award)
    return ok(ser_response(resp))


@bp.post("/feedback-panel/responses/<response_id>/quarantine")
@require_roles("DataAnalyst")
def quarantine(response_id):
    resp = get_response_or_404(response_id)
    if resp["status"] != "SUBMITTED":
        raise ApiError("ERR_RESPONSE_NOT_REVIEWABLE", 409,
                       "Quarantine requires response status SUBMITTED")
    resp["status"] = "QUARANTINED"
    touch(resp)
    return ok(ser_response(resp))


@bp.post("/feedback-panel/responses/<response_id>/discard")
@require_roles("DataAnalyst")
def discard(response_id):
    resp = get_response_or_404(response_id)
    if resp["status"] != "QUARANTINED":
        raise ApiError("ERR_RESPONSE_NOT_REVIEWABLE", 409,
                       "Discard requires response status QUARANTINED")
    resp["status"] = "DISCARDED"
    touch(resp)
    award = _award_of(resp)
    if award is not None and award["eligibility_status"] == "PENDING":
        award["eligibility_status"] = "INELIGIBLE"
        touch(award)
    return ok(ser_response(resp))
