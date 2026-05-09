"""Recall-order endpoints."""

from flask import Blueprint

from middleware import require_roles
from response import success
from services import recall as svc


bp = Blueprint("recalls", __name__)


@bp.route("/recall-orders", methods=["POST"])
@require_roles("RegulatoryOfficer")
def initiate():
    data = svc.initiate_recall()
    return success(data, status_code=201)


@bp.route("/recall-orders/<recall_id>/notify", methods=["POST"])
@require_roles("RegulatoryOfficer")
def notify(recall_id):
    return success(svc.notify_recall(recall_id))


@bp.route("/recall-orders/<recall_id>/disposals", methods=["POST"])
@require_roles("Distributor")
def disposal(recall_id):
    data = svc.record_disposal(recall_id)
    return success(data, status_code=201)


@bp.route("/recall-orders/<recall_id>/complete", methods=["POST"])
@require_roles("RegulatoryOfficer")
def complete(recall_id):
    return success(svc.complete_recall(recall_id))


@bp.route("/recall-orders/<recall_id>/cancel", methods=["POST"])
@require_roles("RegulatoryOfficer")
def cancel(recall_id):
    return success(svc.cancel_recall(recall_id))


@bp.route("/recall-orders/<recall_id>", methods=["GET"])
@require_roles("RegulatoryOfficer", "Distributor")
def get_one(recall_id):
    return success(svc.get_recall(recall_id))
