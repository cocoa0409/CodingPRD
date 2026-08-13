from flask import Blueprint, request

from core import (AGE_BANDS, ERR_INVALID_REQUEST, ApiError, body, db,
                  list_response, new_resource, ok, opt_str, req_enum, req_str,
                  require_roles, touch)
from logic import active_hold_for, cell_touch, find_cell_by_triple, suppress_live_invitations
from serializers import ser_panelist

bp = Blueprint("panelists", __name__)


def get_panelist_or_404(panelist_id):
    p = db.panelists.get(panelist_id)
    if p is None:
        raise ApiError("ERR_PANELIST_NOT_FOUND", 404, "Panelist not found")
    return p


@bp.post("/feedback-panel/panelists")
@require_roles("PanelManager")
def create_panelist():
    data = body()
    external_ref = req_str(data, "external_ref")
    full_name = req_str(data, "full_name")
    age_band = req_enum(data, "age_band", AGE_BANDS)
    district = req_str(data, "district")
    tenure_bucket = req_enum(data, "tenure_bucket", ("RENTER", "OWNER"))
    preferred_locale = opt_str(data, "preferred_locale", "en")
    for p in db.panelists.values():
        if p["external_ref"] == external_ref:
            raise ApiError(ERR_INVALID_REQUEST, 400, "external_ref already registered")
    p = new_resource()
    p.update({
        "external_ref": external_ref,
        "full_name": full_name,
        "age_band": age_band,
        "district": district,
        "tenure_bucket": tenure_bucket,
        "preferred_locale": preferred_locale,
        "home_cell_id": None,
        "status": "APPLICANT",
        "missed_streak": 0,
        "last_contacted_at": None,
        "lapsed_at": None,
    })
    db.panelists[p["id"]] = p
    return ok(ser_panelist(p), 201)


@bp.get("/feedback-panel/panelists")
@require_roles("PanelManager", "PrivacyOfficer")
def list_panelists():
    items = list(db.panelists.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    home_cell_id = request.args.get("home_cell_id")
    if home_cell_id is not None:
        items = [p for p in items if p["home_cell_id"] == home_cell_id]
    return list_response(items, ser_panelist)


@bp.get("/feedback-panel/panelists/<panelist_id>")
@require_roles("PanelManager", "PrivacyOfficer")
def get_panelist(panelist_id):
    return ok(ser_panelist(get_panelist_or_404(panelist_id)))


@bp.post("/feedback-panel/panelists/<panelist_id>/enroll")
@require_roles("PanelManager")
def enroll(panelist_id):
    p = get_panelist_or_404(panelist_id)
    # Existence: resolve the demographic triple to a cell (priority 3).
    cell = find_cell_by_triple(p["age_band"], p["district"], p["tenure_bucket"])
    if cell is None:
        raise ApiError("ERR_PANEL_CELL_NOT_FOUND", 404,
                       "No cell matches the panelist's demographic triple")
    if p["status"] != "APPLICANT":
        raise ApiError("ERR_PANELIST_NOT_ACTIVE", 409,
                       "Enroll requires panelist status APPLICANT")
    if cell["active_count"] >= cell["target_size"]:
        raise ApiError("ERR_CELL_SATURATED", 409,
                       "Cell active_count has reached target_size")
    p["home_cell_id"] = cell["id"]
    p["status"] = "ACTIVE"
    touch(p)
    cell["active_count"] += 1
    cell_touch(cell)
    return ok(ser_panelist(p))


@bp.post("/feedback-panel/panelists/<panelist_id>/reactivate")
@require_roles("PanelManager")
def reactivate(panelist_id):
    p = get_panelist_or_404(panelist_id)
    if p["status"] != "LAPSED":
        raise ApiError("ERR_PANELIST_NOT_LAPSED", 409,
                       "Reactivate requires panelist status LAPSED")
    if active_hold_for(p["id"]) is not None:
        raise ApiError("ERR_PRIVACY_HOLD_ACTIVE", 403,
                       "An ACTIVE privacy hold bars panelist reactivation")
    # LAPSED already counts toward active_count: re-derivation is a no-op.
    p["status"] = "ACTIVE"
    touch(p)
    return ok(ser_panelist(p))


@bp.post("/feedback-panel/panelists/<panelist_id>/withdraw")
@require_roles("PanelManager")
def withdraw(panelist_id):
    p = get_panelist_or_404(panelist_id)
    if p["status"] not in ("ACTIVE", "LAPSED"):
        raise ApiError("ERR_PANELIST_NOT_ACTIVE", 409,
                       "Withdraw requires panelist status ACTIVE or LAPSED")
    was_active = p["status"] == "ACTIVE"
    p["status"] = "WITHDRAWN"
    touch(p)
    cell = db.cells.get(p["home_cell_id"])
    if cell is not None:
        cell["active_count"] -= 1
        cell_touch(cell)
    if was_active:
        suppress_live_invitations(p)
    return ok(ser_panelist(p))
