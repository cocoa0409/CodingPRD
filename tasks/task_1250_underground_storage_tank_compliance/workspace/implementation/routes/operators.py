"""OperatorPerson designation and credential lifecycle (PRD 3.7)."""
from flask import Blueprint

from authz import FACILITY_OWNER, READ_ROLES, check_facility_ownership, require_roles
from calc import latest_training_record, recompute_posture
from db import store
from errors import (
    operator_not_activatable, operator_not_found, training_expired,
    training_missing,
)
from respond import success
from routes.facilities import get_facility_or_404
from serialize import ser_operator
from store_ops import (
    check_closed, get_or_404, json_body, new_common_fields, new_id, paginate,
    qparam, req_enum, req_str, sorted_by_creation, touch,
)

bp = Blueprint("operators", __name__)

OPERATOR_CLASSES = ["A", "B", "C"]


def get_operator_or_404(op_id):
    return get_or_404(store.operators, op_id, operator_not_found)


@bp.route("/operators", methods=["POST"])
def create_operator():
    uid, _ = require_roles([FACILITY_OWNER])
    data = json_body()
    check_closed(data, {"facility_id", "full_name", "operator_class"})
    facility_id = req_str(data, "facility_id")
    full_name = req_str(data, "full_name")
    operator_class = req_enum(data, "operator_class", OPERATOR_CLASSES)

    fac = get_facility_or_404(facility_id)
    check_facility_ownership(uid, fac)

    o = {
        "id": new_id(),
        "_seq": next(store.seq),
        "facility_id": facility_id,
        "full_name": full_name,
        "operator_class": operator_class,
        "status": "DESIGNATED",
    }
    o.update(new_common_fields())
    store.operators[o["id"]] = o
    return success(ser_operator(o), status=201)


@bp.route("/operators", methods=["GET"])
def list_operators():
    require_roles(READ_ROLES)
    items = store.operators.values()
    for f in ("facility_id", "operator_class", "status"):
        v = qparam(f)
        if v is not None:
            items = [o for o in items if o[f] == v]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_operator(o) for o in page], response_type="array", pagination=pagination)


@bp.route("/operators/<op_id>", methods=["GET"])
def get_operator(op_id):
    require_roles(READ_ROLES)
    return success(ser_operator(get_operator_or_404(op_id)))


@bp.route("/operators/<op_id>/activate", methods=["POST"])
def activate_operator(op_id):
    uid, _ = require_roles([FACILITY_OWNER])
    json_body()
    o = get_operator_or_404(op_id)
    fac = get_facility_or_404(o["facility_id"])
    check_facility_ownership(uid, fac)
    if o["status"] not in ("DESIGNATED", "LAPSED"):
        raise operator_not_activatable()
    # Priority 16: a TrainingRecord for the operator's class must exist, and
    # the selected latest one must be unexpired (clock strictly < expires_at).
    rec = latest_training_record(o["id"], o["operator_class"])
    if rec is None:
        raise training_missing()
    if rec["expires_at"] <= store.clock:
        raise training_expired()
    o["status"] = "ACTIVE"
    touch(o)
    recompute_posture(fac)
    return success(ser_operator(o))


@bp.route("/operators/<op_id>/revoke", methods=["POST"])
def revoke_operator(op_id):
    uid, _ = require_roles([FACILITY_OWNER])
    json_body()
    o = get_operator_or_404(op_id)
    fac = get_facility_or_404(o["facility_id"])
    check_facility_ownership(uid, fac)
    if o["status"] == "REVOKED":
        raise operator_not_activatable("REVOKED is terminal")
    o["status"] = "REVOKED"
    touch(o)
    recompute_posture(fac)
    return success(ser_operator(o))
