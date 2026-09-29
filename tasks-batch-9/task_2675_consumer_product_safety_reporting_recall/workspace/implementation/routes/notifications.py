"""Retailer stop-sale notifications (PRD 3.6)."""

from flask import Blueprint

import auth
import lookups
import responses
import shapes
import store
from errors import raise_error

bp = Blueprint("notifications", __name__)

NOTIFICATION_STATUSES = ("PENDING", "ISSUED", "ACKNOWLEDGED", "VERIFIED",
                         "DELINQUENT")

ROLES = ("ProgramAdmin", "ComplianceOfficer", "SafetyDirector", "FieldAuditor",
         "RetailerRep")


@bp.route("/retailer-notifications/<notification_id>", methods=["GET"])
def get_notification(notification_id):
    actor = auth.authorize(*ROLES)
    notification = lookups.find("retailer_notification", notification_id)
    # A retailer representative may only read the notification records it is
    # party to (PRD 2.1); scope is ordering step 6, after path existence.
    if actor.role == "RetailerRep" and actor.user_id != notification["retailer_id"]:
        raise_error("ERR_RETAILER_SCOPE_VIOLATION")
    return responses.object_response(notification)


@bp.route("/retailer-notifications", methods=["GET"])
def list_notifications():
    auth.authorize(*ROLES)
    limit, offset = shapes.pagination()
    recall_id = shapes.q_str("recall_id")
    retailer_id = shapes.q_str("retailer_id")
    status = shapes.q_enum("status", NOTIFICATION_STATUSES)
    stop_sale_required = shapes.q_bool("stop_sale_required")

    def keep(row):
        if recall_id is not None and row["recall_id"] != recall_id:
            return False
        if retailer_id is not None and row["retailer_id"] != retailer_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if (stop_sale_required is not None
                and row["stop_sale_required"] != stop_sale_required):
            return False
        return True

    return responses.list_response(
        store.ordered(store.retailer_notifications, keep), limit, offset)


@bp.route("/retailer-notifications", methods=["POST"])
def create_notification():
    auth.authorize("ComplianceOfficer", "SafetyDirector")
    data = shapes.body()
    recall_id = shapes._req(data, "recall_id")
    retailer_id = shapes._req(data, "retailer_id")
    # stop_sale_required is server-owned: any supplied value is ignored.

    recall = lookups.find("recall", recall_id)
    lookups.find("retailer", retailer_id)

    if recall["plan_status"] not in ("DRAFT", "SUBMITTED"):
        raise_error("ERR_RECALL_PLAN_STATE_INVALID")

    for existing in store.retailer_notifications.values():
        if (existing["recall_id"] == recall_id
                and existing["retailer_id"] == retailer_id):
            raise_error("ERR_DUPLICATE_RETAILER_NOTIFICATION")

    row = store.new_row(
        recall_id=recall_id,
        retailer_id=retailer_id,
        status="PENDING",
        stop_sale_required=False,
        issued_at=None,
        ack_due_at=None,
        acknowledged_at=None,
        verified_at=None,
        units_on_shelf_reported=None,
    )
    store.retailer_notifications[row["id"]] = row
    return responses.created(row)


@bp.route("/retailer-notifications/<notification_id>/acknowledge",
          methods=["POST"])
def acknowledge(notification_id):
    actor = auth.authorize("RetailerRep", "ComplianceOfficer")
    notification = lookups.find("retailer_notification", notification_id)
    data = shapes.body()
    units_on_shelf = shapes.req_int(data, "units_on_shelf_reported", minimum=0)

    if actor.role == "RetailerRep" and actor.user_id != notification["retailer_id"]:
        raise_error("ERR_RETAILER_SCOPE_VIOLATION")

    was = notification["status"]
    if was not in ("ISSUED", "DELINQUENT"):
        raise_error("ERR_NOTIFICATION_STATE_INVALID")

    notification["status"] = "ACKNOWLEDGED"
    notification["acknowledged_at"] = store.now_logical()
    notification["units_on_shelf_reported"] = units_on_shelf
    store.touch(notification)

    if was == "DELINQUENT":
        retailer = lookups.maybe("retailer", notification["retailer_id"])
        if retailer is not None:
            # delinquent_count is monotonic and is never decremented here.
            if retailer["open_stop_sale_count"] >= 1:
                retailer["compliance_posture"] = "STOP_SALE_ACTIVE"
            else:
                retailer["compliance_posture"] = "CLEAR"
            store.touch(retailer)

        recall = lookups.maybe("recall", notification["recall_id"])
        if recall is not None and recall["notification_status"] == "DEFICIENT":
            remaining = any(
                n["recall_id"] == notification["recall_id"]
                and n["status"] == "DELINQUENT"
                for n in store.retailer_notifications.values())
            if not remaining:
                recall["notification_status"] = "IN_PROGRESS"
                store.touch(recall)

    return responses.object_response(notification)


@bp.route("/retailer-notifications/<notification_id>/verify", methods=["POST"])
def verify(notification_id):
    auth.authorize("SafetyDirector", "FieldAuditor")
    notification = lookups.find("retailer_notification", notification_id)
    shapes.body()

    if notification["status"] != "ACKNOWLEDGED":
        raise_error("ERR_NOTIFICATION_STATE_INVALID")

    evidenced = any(
        v["retailer_notification_id"] == notification_id
        and v["status"] == "COMPLETED"
        and v["verdict"] == "PASS"
        for v in store.audit_visits.values())
    if not evidenced:
        raise_error("ERR_SHELF_REMOVAL_UNVERIFIED")

    notification["status"] = "VERIFIED"
    notification["verified_at"] = store.now_logical()
    store.touch(notification)

    retailer = lookups.maybe("retailer", notification["retailer_id"])
    if retailer is not None:
        retailer["open_stop_sale_count"] = retailer["open_stop_sale_count"] - 1
        retailer["verified_removal_count"] = retailer["verified_removal_count"] + 1
        if retailer["open_stop_sale_count"] == 0:
            retailer["compliance_posture"] = "CLEAR"
        store.touch(retailer)

    recall = lookups.maybe("recall", notification["recall_id"])
    if recall is not None and recall["notification_status"] == "IN_PROGRESS":
        siblings = [n for n in store.retailer_notifications.values()
                    if n["recall_id"] == recall["id"]]
        if all(n["status"] == "VERIFIED" for n in siblings):
            recall["notification_status"] = "SATISFIED"
            store.touch(recall)

    return responses.object_response(notification)
