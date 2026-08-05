"""Abatement orders, owner notices, extensions and city abatement (PRD 3.6)."""

import datetime

from flask import Blueprint

import auth
import calc
import envelope
import flows
import lclock
import lookups
import routes_inspections
import serialize
import store
import valid
from errors import ApiError

bp = Blueprint("orders", __name__)
P = "/vector-control"

NOTICE_TYPES = ("ABATEMENT_ORDER", "EDUCATIONAL_ADVISORY", "FINAL_WARNING", "LIEN_INTENT")
DELIVERY_METHODS = ("FIRST_CLASS_MAIL", "CERTIFIED_MAIL", "PERSONAL_SERVICE", "POSTING")
SERVICE_OUTCOMES = ("DELIVERED", "REFUSED", "UNDELIVERABLE")


@bp.post(P + "/abatement-orders")
def create_order():
    caller = auth.guard("Supervisor")
    data = valid.body()
    # step 3: existence
    raw_inspection_id = data.get("inspection_id")
    inspection = None
    if isinstance(raw_inspection_id, str) and raw_inspection_id:
        inspection = lookups.inspection(raw_inspection_id)
    # step 5: request shape
    inspection_id = valid.req_id(data, "inspection_id")
    required_actions = valid.req_str_array(data, "required_actions", min_items=1)
    expected_property_version = valid.req_int(data, "expected_property_version")
    if inspection is None:
        inspection = lookups.inspection(inspection_id)
    prop = lookups.prop(inspection["property_id"])
    # step 6: optimistic concurrency on the parcel
    if expected_property_version != prop["version"]:
        raise ApiError("ERR_STALE_PROPERTY_VERSION")
    # step 8: related-entity state
    if inspection["status"] != "COMPLETED":
        raise ApiError("ERR_INSPECTION_NOT_COMPLETED")
    if inspection["result"] != "VIOLATION_FOUND":
        raise ApiError("ERR_NO_VIOLATION_FOUND")
    # step 9: segregation of duties
    if caller.user_id == inspection["officer_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    assessment = routes_inspections.assessment_for(inspection["id"])
    order = store.stamp_new(
        {
            "property_id": inspection["property_id"],
            "inspection_id": inspection["id"],
            "issued_by_officer_id": caller.user_id,
            "status": "ISSUED",
            "required_actions": required_actions,
            "infestation_tier_at_issue": assessment["infestation_tier"] if assessment else None,
            "escalation_level": 0,
            "compliance_deadline": None,
            "served_at": None,
            "extension_count": 0,
            "extension_days_total": 0,
            "education_advisory_served": False,
            "actual_labor_hours": None,
            "actual_materials_cents": None,
            "abated_at": None,
            "closed_at": None,
        }
    )
    store.orders[order["id"]] = order
    complaint = store.complaints.get(inspection["complaint_id"])
    if complaint is not None and complaint["status"] == "INSPECTED":
        complaint["status"] = "ABATEMENT_ORDERED"
        store.touch(complaint)
    flows.refresh_property_counters(prop, bump_version=True)
    return envelope.obj(serialize.order(order), 201)


@bp.get(P + "/abatement-orders/<order_id>")
def read_order(order_id):
    auth.guard(
        "ProgramAdmin", "Supervisor", "Inspector", "IntakeClerk", "FinanceOfficer", "PropertyOwner"
    )
    order = lookups.order(order_id)
    return envelope.obj(serialize.order(order))


@bp.get(P + "/abatement-orders")
def list_orders():
    auth.guard("ProgramAdmin", "Supervisor", "Inspector", "IntakeClerk", "FinanceOfficer")
    limit, offset = valid.pagination()
    filters = {
        "property_id": valid.query_str("property_id"),
        "inspection_id": valid.query_str("inspection_id"),
        "issued_by_officer_id": valid.query_str("issued_by_officer_id"),
        "status": valid.query_str("status"),
    }

    def keep(o):
        for field, expected in filters.items():
            if expected is not None and o[field] != expected:
                return False
        return True

    rows = store.ordered(store.orders, keep)
    return lookups.page(rows, limit, offset, serialize.order)


# --- notices ------------------------------------------------------------


@bp.post(P + "/abatement-orders/<order_id>/notices")
def create_notice(order_id):
    auth.guard("IntakeClerk", "Supervisor")
    order = lookups.order(order_id)
    data = valid.body()
    notice_type = valid.req_enum(data, "notice_type", NOTICE_TYPES)
    delivery_method = valid.req_enum(data, "delivery_method", DELIVERY_METHODS)
    # step 10: notice sequencing
    existing = [n for n in store.notices.values() if n["abatement_order_id"] == order["id"]]
    if not existing and notice_type != "ABATEMENT_ORDER":
        raise ApiError(
            "ERR_NOTICE_SEQUENCE_INVALID",
            "The first notice on an order must be an ABATEMENT_ORDER notice.",
        )
    if notice_type == "FINAL_WARNING" and order["status"] != "ESCALATED":
        raise ApiError(
            "ERR_NOTICE_SEQUENCE_INVALID",
            "A FINAL_WARNING may only be generated while the order is ESCALATED.",
        )
    recipient_address = None
    prop = store.properties.get(order["property_id"])
    if prop is not None:
        owner = store.owners.get(prop["owner_id"])
        if owner is not None:
            recipient_address = owner["mailing_address"]
    notice = store.stamp_new(
        {
            "abatement_order_id": order["id"],
            "notice_type": notice_type,
            "delivery_method": delivery_method,
            "recipient_address": recipient_address,
            "status": "PENDING_SERVICE",
            "service_outcome": None,
            "sent_at": lclock.now(),
            "served_at": None,
        }
    )
    store.notices[notice["id"]] = notice
    return envelope.obj(serialize.notice(notice), 201)


@bp.get(P + "/abatement-orders/<order_id>/notices")
def list_notices(order_id):
    auth.guard("ProgramAdmin", "Supervisor", "IntakeClerk", "FinanceOfficer", "PropertyOwner")
    order = lookups.order(order_id)
    limit, offset = valid.pagination()
    rows = store.ordered(store.notices, lambda n: n["abatement_order_id"] == order["id"])
    return lookups.page(rows, limit, offset, serialize.notice)


@bp.post(P + "/notices/<notice_id>/service-result")
def record_service_result(notice_id):
    auth.guard("IntakeClerk")
    notice = lookups.notice(notice_id)
    data = valid.body()
    outcome = valid.req_enum(data, "service_outcome", SERVICE_OUTCOMES)
    if notice["status"] != "PENDING_SERVICE":
        raise ApiError("ERR_NOTICE_ALREADY_SERVED")
    now = lclock.now()
    notice["service_outcome"] = outcome
    if outcome == "UNDELIVERABLE":
        notice["status"] = "UNDELIVERABLE"
        store.touch(notice)
        return envelope.obj(serialize.notice(notice))
    notice["status"] = "SERVED"
    notice["served_at"] = now
    store.touch(notice)
    order = store.orders.get(notice["abatement_order_id"])
    if order is not None:
        notice_type = notice["notice_type"]
        if notice_type == "ABATEMENT_ORDER" and order["status"] == "ISSUED":
            flows.serve_order(order, now)
        elif notice_type == "FINAL_WARNING" and order["status"] == "ESCALATED":
            flows.serve_order(order, now)
        elif notice_type == "EDUCATIONAL_ADVISORY":
            order["education_advisory_served"] = True
            store.bump(order)
    return envelope.obj(serialize.notice(notice))


# --- extensions and city abatement --------------------------------------


@bp.post(P + "/abatement-orders/<order_id>/extend")
def extend_order(order_id):
    auth.guard("Supervisor")
    order = lookups.order(order_id)
    data = valid.body()
    extension_days = valid.req_int(data, "extension_days")
    valid.req_str(data, "reason", min_len=1)
    if order["status"] not in ("SERVED", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE", "Only a SERVED or ESCALATED order may be extended.")
    if order["extension_count"] >= calc.MAX_EXTENSIONS_PER_ORDER:
        raise ApiError("ERR_EXTENSION_LIMIT_REACHED")
    if extension_days < calc.EXTENSION_MIN_DAYS or extension_days > calc.EXTENSION_MAX_DAYS:
        raise ApiError("ERR_EXTENSION_WINDOW_EXCEEDED")
    if order["compliance_deadline"] is not None:
        order["compliance_deadline"] = order["compliance_deadline"] + datetime.timedelta(
            days=extension_days
        )
    order["extension_count"] += 1
    order["extension_days_total"] += extension_days
    store.bump(order)
    return envelope.obj(serialize.order(order))


@bp.post(P + "/abatement-orders/<order_id>/city-abate")
def city_abate(order_id):
    auth.guard("Supervisor")
    order = lookups.order(order_id)
    data = valid.body()
    labor_hours = valid.req_decimal_hours(data, "actual_labor_hours")
    materials_cents = valid.req_int(data, "actual_materials_cents", minimum=0)
    valid.opt_str(data, "crew_notes")
    if order["status"] not in ("ESCALATED", "SERVED"):
        raise ApiError("ERR_INVALID_STATE", "Only an ESCALATED or SERVED order may be abated.")
    if order["status"] == "SERVED":
        deadline = order["compliance_deadline"]
        if deadline is not None and lclock.now() < deadline:
            raise ApiError("ERR_DEADLINE_NOT_PASSED")
    order["status"] = "CITY_ABATED"
    order["actual_labor_hours"] = labor_hours
    order["actual_materials_cents"] = materials_cents
    order["abated_at"] = lclock.now()
    store.bump(order)
    return envelope.obj(serialize.order(order))
