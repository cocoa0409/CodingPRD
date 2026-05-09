"""Planting-batch + agro-app + harvest endpoints."""

from flask import Blueprint, request

from middleware import require_roles
from response import paginated, success
from services import agro_app as agro_svc
from services import harvest as harvest_svc
from services import inspection as insp_svc
from services import logistics as leg_svc
from services import planting_batch as svc


bp = Blueprint("planting_batches", __name__)


@bp.route("/planting-batches", methods=["POST"])
@require_roles("Grower")
def create():
    data = svc.create_batch()
    return success(data, status_code=201)


@bp.route("/planting-batches", methods=["GET"])
@require_roles("Grower", "Inspector", "RegulatoryOfficer")
def list_():
    items, limit, offset, total = svc.list_batches(request.args)
    return paginated(items, limit, offset, total)


@bp.route("/planting-batches/<batch_id>", methods=["GET"])
@require_roles("Grower", "Inspector", "RegulatoryOfficer", "LogisticsOperator", "Distributor")
def get_one(batch_id):
    return success(svc.get_batch(batch_id))


@bp.route("/planting-batches/<batch_id>/declare-growing", methods=["POST"])
@require_roles("Grower")
def declare_growing(batch_id):
    return success(svc.declare_growing(batch_id))


# ---- Agrochemical applications ----

@bp.route("/planting-batches/<batch_id>/agrochemical-applications", methods=["POST"])
@require_roles("Grower")
def create_app(batch_id):
    data = agro_svc.create_application(batch_id)
    return success(data, status_code=201)


@bp.route("/planting-batches/<batch_id>/agrochemical-applications", methods=["GET"])
@require_roles("Grower", "Inspector", "RegulatoryOfficer")
def list_apps(batch_id):
    items, limit, offset, total = agro_svc.list_applications(batch_id, request.args)
    return paginated(items, limit, offset, total)


# ---- Harvest records ----

@bp.route("/planting-batches/<batch_id>/harvest-records", methods=["POST"])
@require_roles("Grower")
def create_harvest(batch_id):
    data = harvest_svc.create_harvest(batch_id)
    return success(data, status_code=201)


@bp.route("/planting-batches/<batch_id>/harvest-records", methods=["GET"])
@require_roles("Grower", "Inspector", "RegulatoryOfficer")
def list_harvests(batch_id):
    items, limit, offset, total = harvest_svc.list_harvests(batch_id, request.args)
    return paginated(items, limit, offset, total)


# ---- Inspection (create draft) ----

@bp.route("/planting-batches/<batch_id>/inspection-reports", methods=["POST"])
@require_roles("Inspector")
def create_inspection(batch_id):
    data = insp_svc.create_draft(batch_id)
    return success(data, status_code=201)


# ---- Logistics legs (under planting batch) ----

@bp.route("/planting-batches/<batch_id>/logistics-legs", methods=["POST"])
@require_roles("LogisticsOperator")
def create_leg(batch_id):
    data = leg_svc.create_leg(batch_id)
    return success(data, status_code=201)


@bp.route("/planting-batches/<batch_id>/logistics-legs", methods=["GET"])
@require_roles("Grower", "Inspector", "RegulatoryOfficer", "LogisticsOperator", "Distributor")
def list_legs(batch_id):
    items, limit, offset, total = leg_svc.list_legs(batch_id, request.args)
    return paginated(items, limit, offset, total)
