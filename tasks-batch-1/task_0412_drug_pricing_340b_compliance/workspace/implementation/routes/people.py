"""Global fetch/list for prescribers, patients, and child-site fetch."""
from flask import Blueprint

import lookup
from db import db
from middleware import get_identity, serialize
from response import success, list_success
from validation import parse_pagination, paginate
from filters import filter_eq

bp = Blueprint("people", __name__)


@bp.route("/child-sites/<cs_id>", methods=["GET"])
def get_child_site(cs_id):
    get_identity()
    cs = lookup.child_site(cs_id)
    return success(serialize(cs))


@bp.route("/prescribers/<p_id>", methods=["GET"])
def get_prescriber(p_id):
    get_identity()
    p = lookup.prescriber(p_id)
    return success(serialize(p))


@bp.route("/prescribers", methods=["GET"])
def list_prescribers():
    get_identity()
    limit, offset = parse_pagination()
    items = lookup.sorted_by_created(db.prescribers.all())
    items = filter_eq(items, "covered_entity_id")
    page, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.route("/patients/<p_id>", methods=["GET"])
def get_patient(p_id):
    get_identity()
    p = lookup.patient(p_id)
    return success(serialize(p))


@bp.route("/patients", methods=["GET"])
def list_patients():
    get_identity()
    limit, offset = parse_pagination()
    items = lookup.sorted_by_created(db.patients.all())
    items = filter_eq(items, "covered_entity_id")
    page, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)
