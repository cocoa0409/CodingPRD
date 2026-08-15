"""PriorityCustomer endpoints: register, get, list, certify, decertify."""
from flask import Blueprint, request

from db import db
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    raise_err, ERR_INVALID_STATE_TRANSITION, ERR_CERTIFICATION_WINDOW_PAST,
)
from services.core import (
    get_body, req_string, req_enum, req_datetime, paginate, new_common, bump,
    get_feeder, get_priority_customer, serialize_priority_customer,
    sort_created_asc, recompute_outage_scores_for_feeder,
    PRIORITY_CLASSES,
)

bp = Blueprint("priority_customers", __name__)


@bp.route("/om/priority-customers", methods=["POST"])
def create_priority_customer():
    require_roles(["Dispatcher"])
    body = get_body()
    account_ref = req_string(body, "account_ref")
    pclass = req_enum(body, "priority_class", PRIORITY_CLASSES)
    feeder_id = req_string(body, "feeder_id")
    get_feeder(feeder_id)
    pc = new_common()
    pc.update({
        "account_ref": account_ref,
        "priority_class": pclass,
        "feeder_id": feeder_id,
        "certification_status": "REGISTERED",
        "certified_through": None,
    })
    db.priority_customers[pc["id"]] = pc
    return success_object(serialize_priority_customer(pc), status=201)


@bp.route("/om/priority-customers/<pid>", methods=["GET"])
def get_one(pid):
    require_roles(ALL_ROLES)
    pc = get_priority_customer(pid)
    return success_object(serialize_priority_customer(pc))


@bp.route("/om/priority-customers", methods=["GET"])
def list_priority_customers():
    require_roles(ALL_ROLES)
    items = list(db.priority_customers.values())
    feeder_id = request.args.get("feeder_id")
    status = request.args.get("certification_status")
    if feeder_id is not None:
        items = [p for p in items if p["feeder_id"] == feeder_id]
    if status is not None:
        items = [p for p in items if p["certification_status"] == status]
    items = sort_created_asc(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_priority_customer(p) for p in page], limit, offset, total)


@bp.route("/om/priority-customers/<pid>/certify", methods=["POST"])
def certify(pid):
    require_roles(["Dispatcher"])
    pc = get_priority_customer(pid)
    body = get_body()
    ct = req_datetime(body, "certified_through")
    if pc["certification_status"] not in ("REGISTERED", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"PriorityCustomer in {pc['certification_status']} cannot be certified")
    if not (ct > db.now()):
        raise_err(ERR_CERTIFICATION_WINDOW_PAST,
                  "certified_through must be strictly after the logical now")
    pc["certification_status"] = "CERTIFIED"
    pc["certified_through"] = body["certified_through"]
    bump(pc)
    recompute_outage_scores_for_feeder(pc["feeder_id"])
    return success_object(serialize_priority_customer(pc))


@bp.route("/om/priority-customers/<pid>/decertify", methods=["POST"])
def decertify(pid):
    require_roles(["Dispatcher"])
    pc = get_priority_customer(pid)
    if pc["certification_status"] not in ("REGISTERED", "CERTIFIED", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"PriorityCustomer in {pc['certification_status']} cannot be decertified")
    pc["certification_status"] = "DECERTIFIED"
    bump(pc)
    recompute_outage_scores_for_feeder(pc["feeder_id"])
    return success_object(serialize_priority_customer(pc))
