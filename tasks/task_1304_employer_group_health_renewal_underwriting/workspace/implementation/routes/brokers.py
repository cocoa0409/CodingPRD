"""Broker endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import store, new_record, touch
from errors import not_found
from middleware import auth
from response import ok, created, paginated, sorted_items
from serializers import broker_json
from validators import body, req_str, req_num, req_enum

bp = Blueprint("brokers", __name__)

READ_ROLES = ["Underwriter", "SeniorUnderwriter", "Broker", "ComplianceOfficer"]
BROKER_STATUSES = ["ACTIVE", "SUSPENDED", "TERMINATED"]


def get_broker_or_404(broker_id):
    broker = store.brokers.get(broker_id)
    if broker is None:
        raise not_found("Broker does not exist")
    return broker


@bp.post("/brokers")
def create_broker():
    auth(["Underwriter"])
    data = body()
    rec = new_record()
    rec.update({
        "firm_name": req_str(data, "firm_name"),
        "license_number": req_str(data, "license_number"),
        "state_code": req_str(data, "state_code"),
        "commission_pct": req_num(data, "commission_pct"),
        "status": "ACTIVE",
    })
    store.brokers[rec["id"]] = rec
    return created(broker_json(rec))


@bp.get("/brokers")
def list_brokers():
    auth(READ_ROLES)
    items = list(store.brokers.values())
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paginated([broker_json(b) for b in sorted_items(items)])


@bp.get("/brokers/<brokerId>")
def get_broker(brokerId):
    auth(READ_ROLES)
    return ok(broker_json(get_broker_or_404(brokerId)))


@bp.put("/brokers/<brokerId>")
def update_broker(brokerId):
    auth(["SeniorUnderwriter"])
    broker = get_broker_or_404(brokerId)
    data = body()
    broker["status"] = req_enum(data, "status", BROKER_STATUSES)
    touch(broker)
    return ok(broker_json(broker))
