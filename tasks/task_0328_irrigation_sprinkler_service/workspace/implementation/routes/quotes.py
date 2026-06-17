"""ServiceQuote routes (PRD §3.3)."""
from flask import Blueprint, request

from db import db, LOCK, stamp_new, touch
import domain
import errors
import lookups
from domain import serialize
from errors import fail
from listing import list_response
from middleware import get_auth, require_role
from response import success
from validation import get_body, require_str, require_enum, require_line_items

bp = Blueprint("quotes", __name__)

QUOTE_TYPES = {"INSTALL", "REPAIR"}


def _customer_owns_property(user_id, prop):
    """Ownership: acting Customer's id must equal Property.customer_id."""
    return prop["customer_id"] == user_id


@bp.route("/service-quotes", methods=["POST"])
def create_quote():
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        body = get_body()
        property_id = require_str(body, "property_id")
        lookups.get_property(property_id)
        quote_type = require_enum(body, "quote_type", QUOTE_TYPES)
        line_items = require_line_items(body, "line_items")
        rec = {
            "property_id": property_id,
            "quote_type": quote_type,
            "line_items": line_items,
            "estimated_total_cents": 0,
            "final_total_cents": 0,
            "quote_state": "DRAFT",
            "linked_work_order_id": None,
        }
        stamp_new(rec)
        db.service_quotes[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/service-quotes/<qid>", methods=["GET"])
def get_quote(qid):
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Customer"})
    with LOCK:
        rec = lookups.get_quote(qid)
        return success(serialize(rec), status=200)


@bp.route("/service-quotes", methods=["GET"])
def list_quotes():
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Customer"})
    with LOCK:
        rows = list(db.service_quotes.values())
        property_id = request.args.get("property_id")
        linked = request.args.get("linked_work_order_id")
        if property_id is not None:
            rows = [q for q in rows if q["property_id"] == property_id]
        if linked is not None:
            rows = [q for q in rows if q["linked_work_order_id"] == linked]
        return list_response(rows)


@bp.route("/service-quotes/<qid>/send", methods=["POST"])
def send_quote(qid):
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        quote = lookups.get_quote(qid)
        # State precondition (priority 5)
        if quote["quote_state"] != "DRAFT":
            fail(errors.ERR_QUOTE_NOT_DRAFT, "Quote is not in DRAFT")
        # Empty-quote guard (priority 13, HTTP 422)
        if len(quote["line_items"]) == 0:
            fail(errors.ERR_EMPTY_QUOTE, "Cannot send a quote with empty line_items")
        quote["estimated_total_cents"] = domain.quote_estimated_total(quote["line_items"])
        quote["quote_state"] = "SENT"
        touch(quote)
        return success(serialize(quote), status=200)


@bp.route("/service-quotes/<qid>/line-items", methods=["PATCH"])
def revise_line_items(qid):
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        quote = lookups.get_quote(qid)
        if quote["quote_state"] != "CHANGES_REQUESTED":
            fail(errors.ERR_QUOTE_NOT_REVISABLE, "Quote is not in CHANGES_REQUESTED")
        body = get_body()
        line_items = require_line_items(body, "line_items")
        quote["line_items"] = line_items
        quote["estimated_total_cents"] = domain.quote_estimated_total(line_items)
        quote["quote_state"] = "DRAFT"
        touch(quote)
        return success(serialize(quote), status=200)


@bp.route("/service-quotes/<qid>/request-changes", methods=["POST"])
def request_changes(qid):
    user_id, role = get_auth()
    require_role(role, {"Customer"})
    with LOCK:
        quote = lookups.get_quote(qid)
        prop = db.properties.get(quote["property_id"])
        # Ownership (priority 4) checked before state (priority 5)
        if prop is None or not _customer_owns_property(user_id, prop):
            fail(errors.ERR_NOT_RESOURCE_OWNER, "Customer does not own this quote's property")
        if quote["quote_state"] != "SENT":
            fail(errors.ERR_QUOTE_NOT_SENT, "Quote is not in SENT")
        quote["quote_state"] = "CHANGES_REQUESTED"
        touch(quote)
        return success(serialize(quote), status=200)


@bp.route("/service-quotes/<qid>/reject", methods=["POST"])
def reject_quote(qid):
    user_id, role = get_auth()
    require_role(role, {"Customer"})
    with LOCK:
        quote = lookups.get_quote(qid)
        prop = db.properties.get(quote["property_id"])
        if prop is None or not _customer_owns_property(user_id, prop):
            fail(errors.ERR_NOT_RESOURCE_OWNER, "Customer does not own this quote's property")
        if quote["quote_state"] != "SENT":
            fail(errors.ERR_QUOTE_NOT_SENT, "Quote is not in SENT")
        quote["quote_state"] = "REJECTED"
        touch(quote)
        return success(serialize(quote), status=200)


@bp.route("/service-quotes/<qid>/approve", methods=["POST"])
def approve_quote(qid):
    user_id, role = get_auth()
    require_role(role, {"Customer"})
    with LOCK:
        quote = lookups.get_quote(qid)
        prop = db.properties.get(quote["property_id"])
        # Ownership (priority 4)
        if prop is None or not _customer_owns_property(user_id, prop):
            fail(errors.ERR_NOT_RESOURCE_OWNER, "Customer does not own this quote's property")
        # State (priority 5)
        if quote["quote_state"] != "SENT":
            fail(errors.ERR_QUOTE_NOT_SENT, "Quote is not in SENT")
        # Cross-entity business gate: property must be ACTIVE
        if prop["status"] != "ACTIVE":
            fail(errors.ERR_PROPERTY_INACTIVE, "Property is not ACTIVE")

        # Spawn a WorkOrder on the property's first OPERATIONAL system.
        op_systems = [
            s for s in domain.systems_of_property(prop["id"])
            if s["lifecycle_state"] == "OPERATIONAL"
        ]
        op_systems = sorted(op_systems, key=lambda s: (s["created_at"], s.get("_seq", 0)))
        target_system = op_systems[0] if op_systems else None

        job_type = "INSTALL" if quote["quote_type"] == "INSTALL" else "LEAK_REPAIR"
        wo = {
            "system_id": target_system["id"] if target_system else None,
            "job_type": job_type,
            "estimated_minutes": 1,
            "estimated_cost_cents": quote["estimated_total_cents"],
            "actual_labor_cents": 0,
            "actual_parts_cents": 0,
            "assigned_technician_id": None,
            "dispatch_status": "UNSCHEDULED",
            "completion_status": "PENDING",
            "origin_quote_id": quote["id"],
        }
        stamp_new(wo)
        db.work_orders[wo["id"]] = wo

        quote["quote_state"] = "APPROVED"
        quote["linked_work_order_id"] = wo["id"]
        touch(quote)

        # Creating the work order debits the system's committed_cost_cents.
        if target_system is not None:
            domain.recompute_system_derived(target_system)

        return success(serialize(quote), status=200)
