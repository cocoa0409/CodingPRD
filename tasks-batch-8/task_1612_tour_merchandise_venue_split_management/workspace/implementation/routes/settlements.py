"""Settlement endpoints (PRD §3.5)."""

from flask import Blueprint, request

from db import DB
from errors import (
    ERR_SETTLEMENT_NOT_FOUND,
    ERR_INVALID_SETTLEMENT_STATE,
    ERR_SETTLEMENT_NOT_RECONCILED,
    ERR_UNRESOLVED_SESSIONS,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_ROYALTY_CONFIG,
    ERR_VALIDATION,
    err,
)
from middleware import (
    require_role,
    require_auth,
    get_json_body,
    require_string,
    touch,
    paginate,
)
from response import success_object, success_list
from services import core
from services.serializers import settlement_view

bp = Blueprint("settlements", __name__)


def get_settlement_or_404(settlement_id):
    s = DB.settlements.get(settlement_id)
    if s is None:
        raise err(ERR_SETTLEMENT_NOT_FOUND, 404, "No Settlement with the given id")
    return s


@bp.get("/merch/settlements")
def list_settlements():
    require_auth()
    show_id = request.args.get("show_id")
    items = list(DB.settlements.values())
    if show_id is not None:
        items = [s for s in items if s["show_id"] == show_id]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([settlement_view(s) for s in page], limit, offset, total)


@bp.get("/merch/settlements/<settlement_id>")
def get_settlement(settlement_id):
    require_auth()
    return success_object(settlement_view(get_settlement_or_404(settlement_id)))


@bp.post("/merch/settlements/<settlement_id>/reconcile")
def reconcile_settlement(settlement_id):
    user_id, role = require_role("Accountant")
    st = get_settlement_or_404(settlement_id)
    if st["status"] != "PROVISIONAL":
        raise err(ERR_INVALID_SETTLEMENT_STATE, 409,
                  "Reconcile requires a PROVISIONAL settlement")
    for s in core.sessions_of_show(st["show_id"]):
        if s["status"] != "VERIFIED":
            raise err(ERR_UNRESOLVED_SESSIONS, 409,
                      "Reconcile requires every session VERIFIED")
    core.compute_final_figures(st)
    st["reconciled_by_user_id"] = user_id
    st["status"] = "RECONCILED"
    touch(st)
    return success_object(settlement_view(st))


@bp.post("/merch/settlements/<settlement_id>/dispute")
def dispute_settlement(settlement_id):
    user_id, role = require_role("VenueRep", "TourManager")
    st = get_settlement_or_404(settlement_id)
    if st["status"] != "RECONCILED":
        raise err(ERR_SETTLEMENT_NOT_RECONCILED, 409,
                  "Dispute requires a RECONCILED settlement")
    body = get_json_body()
    reason = require_string(body, "reason", required=True)
    st["dispute_reason"] = reason
    st["status"] = "DISPUTED"
    touch(st)
    return success_object(settlement_view(st))


@bp.post("/merch/settlements/<settlement_id>/resolve")
def resolve_settlement(settlement_id):
    user_id, role = require_role("Accountant")
    st = get_settlement_or_404(settlement_id)
    if st["status"] != "DISPUTED":
        raise err(ERR_INVALID_SETTLEMENT_STATE, 409,
                  "Resolve requires a DISPUTED settlement")
    core.compute_final_figures(st)
    st["reconciled_by_user_id"] = user_id
    st["status"] = "RECONCILED"
    touch(st)
    return success_object(settlement_view(st))


@bp.post("/merch/settlements/<settlement_id>/finalize")
def finalize_settlement(settlement_id):
    user_id, role = require_role("Accountant")
    st = get_settlement_or_404(settlement_id)
    if st["status"] != "RECONCILED":
        raise err(ERR_SETTLEMENT_NOT_RECONCILED, 409,
                  "Finalize requires a RECONCILED settlement")
    if st["reconciled_by_user_id"] == user_id:
        raise err(ERR_SEGREGATION_OF_DUTIES, 403,
                  "The finalizer must differ from the reconciler")
    show = DB.shows[st["show_id"]]
    tour = DB.tours[show["tour_id"]]
    if not core.snapshot_matches_tour(st, tour):
        raise err(ERR_STALE_ROYALTY_CONFIG, 409,
                  "Pinned royalty snapshot differs from the tour's current config; "
                  "call rebase-royalty first")

    st["status"] = "FINALIZED"
    touch(st)

    # Cascade: parent show RECONCILING -> SETTLED; VERIFIED sessions -> LOCKED.
    if show["status"] == "RECONCILING":
        show["status"] = "SETTLED"
        touch(show)
    for s in core.sessions_of_show(show["id"]):
        if s["status"] == "VERIFIED":
            s["status"] = "LOCKED"
            touch(s)
    return success_object(settlement_view(st))


@bp.post("/merch/settlements/<settlement_id>/rebase-royalty")
def rebase_royalty(settlement_id):
    user_id, role = require_role("Accountant")
    st = get_settlement_or_404(settlement_id)
    if st["status"] == "FINALIZED":
        raise err(ERR_INVALID_SETTLEMENT_STATE, 409,
                  "Rebase-royalty is not allowed on a FINALIZED settlement")
    show = DB.shows[st["show_id"]]
    tour = DB.tours[show["tour_id"]]
    st.update(core.royalty_snapshot_from_tour(tour))
    if st["status"] == "RECONCILED":
        core.recompute_royalty_from_final(st)
    touch(st)
    return success_object(settlement_view(st))
