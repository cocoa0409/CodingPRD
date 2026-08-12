"""WriteDown endpoints: manual proposal, segregated committee approval/rejection."""
from flask import g

import db
import domain
from domain import write_down_json, sort_entities
from envelope import success
from errors import ApiError
from routes.common import (require_roles, body, req_str, req_num, req_enum, paginate, get_or_404)
from routes.properties import ALL_ROLES, request_arg

WD_REASONS = ("MARKET_DECLINE", "MEASUREMENT_PERIOD_ADJUSTMENT", "REGULATORY_CHARGE_OFF")


def create_write_down():
    require_roles("CreditOfficer")
    d = body()
    property_id = req_str(d, "property_id")
    amount = req_num(d, "amount")
    reason = req_enum(d, "reason", WD_REASONS)
    p = get_or_404(db.properties, property_id, "Property")
    wd = domain.new_write_down(property_id, amount, reason, "PROPOSED", False, g.user_id)
    domain.bump(p)
    return success(write_down_json(wd), 201)


def list_write_downs():
    require_roles(*ALL_ROLES)
    pid = request_arg("property_id")
    status = request_arg("status")
    items = [w for w in db.write_downs.values()
             if (pid is None or w["property_id"] == pid)
             and (status is None or w["status"] == status)]
    return paginate(sort_entities(items), write_down_json)


def get_write_down(entity_id):
    require_roles(*ALL_ROLES)
    return success(write_down_json(get_or_404(db.write_downs, entity_id, "Write-down")))


def approve_write_down(entity_id):
    require_roles("OREOCommittee")
    wd = get_or_404(db.write_downs, entity_id, "Write-down")
    if wd["status"] != "PROPOSED":
        raise ApiError("ERR_WRITE_DOWN_NOT_PROPOSED", 409,
                       "Only a PROPOSED write-down can be approved")
    if g.user_id == wd["proposed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Approver must differ from the write-down proposer")
    wd["status"] = "POSTED"
    wd["approved_by_user_id"] = g.user_id
    domain.bump(wd)
    domain.ledger_append(wd["property_id"], "WRITE_DOWN", -wd["amount"],
                         "Write-down posted: %s" % wd["reason"], write_down_id=wd["id"])
    domain.bump(db.properties[wd["property_id"]])
    return success(write_down_json(wd), 200)


def reject_write_down(entity_id):
    require_roles("OREOCommittee")
    wd = get_or_404(db.write_downs, entity_id, "Write-down")
    if wd["status"] != "PROPOSED":
        raise ApiError("ERR_WRITE_DOWN_NOT_PROPOSED", 409,
                       "Only a PROPOSED write-down can be rejected")
    wd["status"] = "REJECTED"
    domain.bump(wd)
    domain.bump(db.properties[wd["property_id"]])
    return success(write_down_json(wd), 200)
