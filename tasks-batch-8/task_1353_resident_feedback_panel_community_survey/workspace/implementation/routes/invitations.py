from datetime import timedelta

from flask import Blueprint, request

from core import (ApiError, body, db, list_response, new_resource, now, ok,
                  req_str, require_roles, touch)
from logic import (CONTACT_CAP, CONTACT_WINDOW_DAYS, REMINDER_CAP,
                   REMINDER_GAP_HOURS, WASHOUT_DAYS, WAVE_TERMINAL,
                   active_hold_for, cell_touch, recompute_streak)
from serializers import ser_invitation

bp = Blueprint("invitations", __name__)


def get_invitation_or_404(invitation_id):
    i = db.invitations.get(invitation_id)
    if i is None:
        raise ApiError("ERR_INVITATION_NOT_FOUND", 404, "Invitation not found")
    return i


@bp.post("/feedback-panel/invitations")
@require_roles("PanelManager")
def create_invitation():
    data = body()
    wave_id = req_str(data, "wave_id")
    panelist_id = req_str(data, "panelist_id")
    wave = db.waves.get(wave_id)
    if wave is None:
        raise ApiError("ERR_WAVE_NOT_FOUND", 404, "Survey wave not found")
    panelist = db.panelists.get(panelist_id)
    if panelist is None:
        raise ApiError("ERR_PANELIST_NOT_FOUND", 404, "Panelist not found")
    # State preconditions.
    if wave["status"] in WAVE_TERMINAL:
        raise ApiError("ERR_WAVE_ALREADY_TERMINAL", 409, "Wave is terminal")
    if wave["status"] != "FIELDING":
        raise ApiError("ERR_WAVE_NOT_FIELDING", 409,
                       "Dispatch requires wave status FIELDING")
    if panelist["status"] != "ACTIVE":
        raise ApiError("ERR_PANELIST_NOT_ACTIVE", 409,
                       "Dispatch requires panelist status ACTIVE")
    # Privacy gate.
    if active_hold_for(panelist["id"]) is not None:
        raise ApiError("ERR_PRIVACY_HOLD_ACTIVE", 403,
                       "An ACTIVE privacy hold bars invitation dispatch")
    # Temporal: half-open seven-day contact washout.
    if panelist["last_contacted_at"] is not None:
        if now() < panelist["last_contacted_at"] + timedelta(days=WASHOUT_DAYS):
            raise ApiError("ERR_CONTACT_WASHOUT_VIOLATION", 409,
                           "Fewer than 7 days since the panelist's last contact")
    # Capacity, pinned order: duplicate live invitation, then cell contact cap.
    for i in db.invitations.values():
        if (i["wave_id"] == wave_id and i["panelist_id"] == panelist_id
                and i["status"] == "SENT"):
            raise ApiError("ERR_DUPLICATE_INVITATION", 409,
                           "A SENT invitation already exists for this wave and panelist")
    cell = db.cells.get(panelist["home_cell_id"])
    window_start = now() - timedelta(days=CONTACT_WINDOW_DAYS)
    recent = 0
    for i in db.invitations.values():
        ip = db.panelists[i["panelist_id"]]
        if ip["home_cell_id"] == (cell["id"] if cell else None):
            if window_start <= i["sent_at"] <= now():
                recent += 1
    if recent >= CONTACT_CAP:
        raise ApiError("ERR_CELL_CONTACT_CAP_REACHED", 409,
                       "The panelist's home cell has reached its contact cap")
    # Fiscal floor.
    if wave["incentive_pool_available_cents"] < wave["base_incentive_cents"]:
        raise ApiError("ERR_INCENTIVE_POOL_INSUFFICIENT", 402,
                       "Wave incentive pool cannot cover the base incentive")
    inv = new_resource()
    inv.update({
        "wave_id": wave_id,
        "panelist_id": panelist_id,
        "sent_at": now(),
        "reminder_count": 0,
        "last_reminder_at": None,
        "status": "SENT",
    })
    db.invitations[inv["id"]] = inv
    panelist["last_contacted_at"] = now()
    touch(panelist)
    if cell is not None:
        cell["reserved_count"] += 1
        cell_touch(cell)
    wave["invited_count"] += 1
    touch(wave)
    return ok(ser_invitation(inv), 201)


@bp.get("/feedback-panel/invitations")
@require_roles("PanelManager")
def list_invitations():
    items = list(db.invitations.values())
    wave_id = request.args.get("wave_id")
    if wave_id is not None:
        items = [i for i in items if i["wave_id"] == wave_id]
    panelist_id = request.args.get("panelist_id")
    if panelist_id is not None:
        items = [i for i in items if i["panelist_id"] == panelist_id]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return list_response(items, ser_invitation)


@bp.get("/feedback-panel/invitations/<invitation_id>")
@require_roles("PanelManager")
def get_invitation(invitation_id):
    return ok(ser_invitation(get_invitation_or_404(invitation_id)))


@bp.post("/feedback-panel/invitations/<invitation_id>/decline")
@require_roles("PanelManager")
def decline(invitation_id):
    inv = get_invitation_or_404(invitation_id)
    if inv["status"] != "SENT":
        raise ApiError("ERR_INVITATION_NOT_OPEN", 409,
                       "Decline requires invitation status SENT")
    inv["status"] = "DECLINED"
    touch(inv)
    panelist = db.panelists[inv["panelist_id"]]
    cell = db.cells.get(panelist["home_cell_id"])
    if cell is not None:
        cell["reserved_count"] -= 1
        cell_touch(cell)
    recompute_streak(panelist)
    return ok(ser_invitation(inv))


@bp.post("/feedback-panel/invitations/<invitation_id>/remind")
@require_roles("PanelManager")
def remind(invitation_id):
    inv = get_invitation_or_404(invitation_id)
    if inv["status"] != "SENT":
        raise ApiError("ERR_INVITATION_NOT_OPEN", 409,
                       "Remind requires invitation status SENT")
    wave = db.waves[inv["wave_id"]]
    if wave["status"] in WAVE_TERMINAL:
        raise ApiError("ERR_WAVE_ALREADY_TERMINAL", 409, "Wave is terminal")
    if wave["status"] != "FIELDING":
        raise ApiError("ERR_WAVE_NOT_FIELDING", 409,
                       "Remind requires wave status FIELDING")
    if inv["reminder_count"] >= REMINDER_CAP:
        raise ApiError("ERR_REMINDER_CAP_REACHED", 409,
                       "Reminder cap of %d reached" % REMINDER_CAP)
    last = inv["last_reminder_at"] if inv["last_reminder_at"] is not None else inv["sent_at"]
    if now() < last + timedelta(hours=REMINDER_GAP_HOURS):
        raise ApiError("ERR_REMINDER_CADENCE_TOO_SOON", 409,
                       "Fewer than 48 hours since the last contact or reminder")
    inv["reminder_count"] += 1
    inv["last_reminder_at"] = now()
    touch(inv)
    return ok(ser_invitation(inv))
