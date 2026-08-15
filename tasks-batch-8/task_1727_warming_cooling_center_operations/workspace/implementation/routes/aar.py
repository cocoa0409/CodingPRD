"""After-action reports: create (aggregates pinned), submit, approve."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_OPEN_INCIDENTS_REMAIN,
    ERR_SITES_NOT_CLOSED, ERR_SEGREGATION_OF_DUTIES,
)
from flask import Blueprint, g
from response import respond, respond_list
from services import (
    bed_nights_final, episode_children, episodes_activations, ser_aar,
)
from util import paginate, touch

bp = Blueprint("aar", __name__)


def get_episode(episode_id):
    ep = db.store["episodes"].get(episode_id)
    if ep is None:
        raise_err(ERR_NOT_FOUND, f"Episode {episode_id} not found")
    return ep


def get_aar(aar_id):
    a = db.store["aars"].get(aar_id)
    if a is None:
        raise_err(ERR_NOT_FOUND, f"AfterActionReport {aar_id} not found")
    return a


def aars_of_episode(episode_id):
    return [a for a in db.store["aars"].values()
            if a["episode_id"] == episode_id]


@bp.route("/episodes/<episode_id>/after-action-reports", methods=["POST"])
@require_roles("EOCManager")
def create_aar(episode_id):
    ep = get_episode(episode_id)
    if ep["status"] not in ("DEACTIVATING", "DEACTIVATED"):
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot draft an after-action report while the episode is "
            f"{ep['status']}",
        )
    if aars_of_episode(ep["id"]):
        raise_err(
            ERR_INVALID_STATE,
            "This episode already has an after-action report",
        )
    stays = episode_children(ep["id"], "stays")
    meal_services = episode_children(ep["id"], "meal_services")
    incidents = episode_children(ep["id"], "incidents")
    dispatches = episode_children(ep["id"], "dispatches")
    by_sev = {"1": 0, "2": 0, "3": 0}
    for i in incidents:
        key = str(i["severity"])
        if key in by_sev:
            by_sev[key] += 1
    now = clock.now()
    a = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "episode_id": ep["id"],
        "status": "DRAFT",
        "total_unique_guests": len({s["guest_id"] for s in stays}),
        "total_bed_nights": sum(bed_nights_final(s) or 0 for s in stays),
        "meals_served": sum(m["served_count"] or 0 for m in meal_services
                            if m["status"] == "SERVED"),
        "incidents_by_severity": by_sev,
        "transports_arrived": sum(1 for d in dispatches
                                  if d["status"] == "ARRIVED"),
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["aars"][a["id"]] = a
    return respond(ser_aar(a), 201)


@bp.route("/episodes/<episode_id>/after-action-reports", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_aars(episode_id):
    get_episode(episode_id)
    items = sorted(aars_of_episode(episode_id),
                   key=lambda a: (a["created_at"], a["_seq"]))
    page, pagination = paginate([ser_aar(a) for a in items])
    return respond_list(page, pagination)


@bp.route("/after-action-reports/<aar_id>/submit", methods=["POST"])
@require_roles("EOCManager")
def submit_aar(aar_id):
    a = get_aar(aar_id)
    if a["status"] != "DRAFT":
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot submit an after-action report in status {a['status']}",
        )
    open_incidents = any(
        i for i in episode_children(a["episode_id"], "incidents")
        if i["status"] != "RESOLVED"
    )
    if open_incidents:
        raise_err(
            ERR_OPEN_INCIDENTS_REMAIN,
            "Every incident of the episode must be RESOLVED before submit",
        )
    open_sites = any(
        act for act in episodes_activations(a["episode_id"])
        if act["status"] != "CLOSED"
    )
    if open_sites:
        raise_err(
            ERR_SITES_NOT_CLOSED,
            "Every site activation of the episode must be CLOSED before "
            "submit",
        )
    a["status"] = "SUBMITTED"
    a["submitted_by_user_id"] = g.user_id
    touch(a)
    return respond(ser_aar(a), 200)


@bp.route("/after-action-reports/<aar_id>/approve", methods=["POST"])
@require_roles("EOCManager")
def approve_aar(aar_id):
    a = get_aar(aar_id)
    if a["status"] != "SUBMITTED":
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot approve an after-action report in status {a['status']}",
        )
    ep = db.store["episodes"].get(a["episode_id"])
    if ep is not None and g.user_id == ep["activated_by_user_id"]:
        raise_err(
            ERR_SEGREGATION_OF_DUTIES,
            "The episode activator cannot approve the after-action report",
        )
    a["status"] = "APPROVED"
    a["approved_by_user_id"] = g.user_id
    touch(a)
    if ep is not None and ep["status"] in ("DEACTIVATING", "DEACTIVATED"):
        ep["status"] = "CLOSED"
        touch(ep)
    return respond(ser_aar(a), 200)
