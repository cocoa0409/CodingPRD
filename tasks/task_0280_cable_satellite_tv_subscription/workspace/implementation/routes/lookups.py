"""Cross-aggregate reverse-lookup reads (PRD §3.11, §4).

Flat collection lists and single-resource gets. Single gets of subscriptions,
add-ons, service visits, and promotion applications are additionally available
to Subscriber; equipment-lease and service-visit reads to FieldTechnician.
"""

from flask import Blueprint, request

import db
import errors
from middleware import get_identity, require_role
from response import object_response
from services import common

bp = Blueprint("lookups", __name__)


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------
@bp.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent"})
    items = list(db.subscriptions.values())
    for field in ("account_id", "package_id", "previous_subscription_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [s for s in items if s.get(field) == val]
    return common.paginate_and_respond(items)


@bp.route("/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "Subscriber"})
    rec = db.subscriptions.get(sid)
    if rec is None:
        raise errors.subresource_not_found("Subscription not found")
    return object_response(rec, 200)


# ---------------------------------------------------------------------------
# Add-ons
# ---------------------------------------------------------------------------
@bp.route("/add-ons", methods=["GET"])
def list_add_ons():
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent"})
    items = list(db.add_on_subscriptions.values())
    for field in ("account_id", "premium_channel_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [a for a in items if a.get(field) == val]
    return common.paginate_and_respond(items)


@bp.route("/add-ons/<aid>", methods=["GET"])
def get_add_on(aid):
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "Subscriber"})
    rec = db.add_on_subscriptions.get(aid)
    if rec is None:
        raise errors.subresource_not_found("Add-on not found")
    return object_response(rec, 200)


# ---------------------------------------------------------------------------
# Equipment leases
# ---------------------------------------------------------------------------
@bp.route("/equipment-leases", methods=["GET"])
def list_equipment_leases():
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent"})
    items = list(db.equipment_leases.values())
    for field in ("account_id", "equipment_model_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [e for e in items if e.get(field) == val]
    return common.paginate_and_respond(items)


@bp.route("/equipment-leases/<lid>", methods=["GET"])
def get_equipment_lease(lid):
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "FieldTechnician"})
    rec = db.equipment_leases.get(lid)
    if rec is None:
        raise errors.subresource_not_found("Equipment lease not found")
    return object_response(rec, 200)


# ---------------------------------------------------------------------------
# Service visits
# ---------------------------------------------------------------------------
@bp.route("/service-visits", methods=["GET"])
def list_service_visits():
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "FieldTechnician"})
    items = list(db.service_visits.values())
    for field in ("account_id", "technician_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [v for v in items if v.get(field) == val]
    return common.paginate_and_respond([_visit_view(v) for v in items])


@bp.route("/service-visits/<vid>", methods=["GET"])
def get_service_visit(vid):
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "Subscriber", "FieldTechnician"})
    rec = db.service_visits.get(vid)
    if rec is None:
        raise errors.subresource_not_found("Service visit not found")
    return object_response(_visit_view(rec), 200)


# ---------------------------------------------------------------------------
# Promotion applications
# ---------------------------------------------------------------------------
@bp.route("/promotion-applications", methods=["GET"])
def list_promotion_applications():
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent"})
    items = list(db.promotion_applications.values())
    for field in ("account_id", "promotion_offer_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [p for p in items if p.get(field) == val]
    return common.paginate_and_respond(items)


@bp.route("/promotion-applications/<paid>", methods=["GET"])
def get_promotion_application(paid):
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "Subscriber"})
    rec = db.promotion_applications.get(paid)
    if rec is None:
        raise errors.subresource_not_found("Promotion application not found")
    return object_response(rec, 200)


def _visit_view(visit):
    return {k: v for k, v in visit.items() if k != "billed_cycle_index"}
