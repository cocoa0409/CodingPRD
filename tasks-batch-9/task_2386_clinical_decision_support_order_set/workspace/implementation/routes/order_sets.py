"""Order set reads, the item catalogue, pharmacy sign-off, peer-review submission
and publication (PRD §3.2, §3.5)."""
from flask import Blueprint, request

import const
import validate
from common import base_record, now, touch
from db import db
from errors import ApiError
from middleware import (authenticate, caller_id, check_freeze, check_read_freeze,
                        get_clinician, get_order_set)
from response import created, ok, paginate
from services import calc, domain

bp = Blueprint("order_sets", __name__)


@bp.get("/cds/order-sets")
def list_order_sets():
    authenticate(const.ANY_ROLE)
    check_read_freeze("order_set")
    records = list(db.order_sets.values())

    for field in ("content_request_id", "built_by_clinician_id", "pinned_vendor_release_id",
                  "supersedes_order_set_id", "pharmacy_signoff_by_clinician_id",
                  "review_state", "publication_state", "risk_class", "specialty"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    stale = validate.query_bool("pinned_content_stale")
    if stale is not None:
        records = [r for r in records if r["pinned_content_stale"] is stale]
    return paginate(records)


@bp.get("/cds/order-sets/<cid>")
def read_order_set(cid):
    authenticate(const.ANY_ROLE)
    order_set = get_order_set(cid)
    check_read_freeze("order_set")
    return ok(order_set)


# ------------------------------------------------------------------ items
@bp.post("/cds/order-sets/<cid>/items")
def add_item(cid):
    authenticate(("InformaticsBuilder", "PharmacyInformaticist"))
    order_set = get_order_set(cid)
    data = validate.body()

    orderable_code = validate.string(data, "orderable_code", required=True)
    display_name = validate.string(data, "display_name", required=True)
    item_category = validate.enum(data, "item_category", const.ITEM_CATEGORIES, required=True)
    default_selected = validate.boolean(data, "default_selected", default=False)
    default_dose = validate.string(data, "default_dose")
    route = validate.string(data, "route")
    frequency = validate.string(data, "frequency")
    high_alert = validate.boolean(data, "high_alert_medication", default=False)
    sequence_index = validate.integer(data, "sequence_index", minimum=1)

    if order_set["review_state"] != "DRAFT":
        raise ApiError("ERR_ORDER_SET_NOT_DRAFT", "Items may only be added while the order set is DRAFT")

    check_freeze("order_set")

    if sequence_index is None:
        sequence_index = order_set["item_count"] + 1
    else:
        existing = {i["sequence_index"] for i in domain.items_of_order_set(order_set["id"])}
        if sequence_index in existing:
            raise ApiError("ERR_INVALID_REQUEST", "sequence_index must be unique within the order set")

    item = base_record(with_version=False)
    item.update({
        "order_set_id": order_set["id"],
        "orderable_code": orderable_code,
        "display_name": display_name,
        "item_category": item_category,
        "default_selected": default_selected,
        "default_dose": default_dose,
        "route": route,
        "frequency": frequency,
        "high_alert_medication": high_alert,
        "sequence_index": sequence_index,
    })
    db.order_set_items[item["id"]] = item

    order_set["item_count"] += 1
    if high_alert:
        order_set["high_alert_item_count"] += 1
    order_set["risk_class"] = domain.order_set_risk_class(order_set)
    touch(order_set)

    return created(item)


@bp.get("/cds/order-sets/<cid>/items")
def list_items(cid):
    authenticate(const.ANY_ROLE)
    order_set = get_order_set(cid)
    check_read_freeze("order_set")
    records = domain.items_of_order_set(order_set["id"])

    category = request.args.get("item_category")
    if category:
        records = [r for r in records if r["item_category"] == category]
    high_alert = validate.query_bool("high_alert_medication")
    if high_alert is not None:
        records = [r for r in records if r["high_alert_medication"] is high_alert]

    return paginate(records, sort_key=lambda r: (r["sequence_index"], r.get("_seq", 0)))


# ------------------------------------------------------------------ pharmacy sign-off
@bp.post("/cds/order-sets/<cid>/pharmacy-signoff")
def pharmacy_signoff(cid):
    authenticate(("PharmacyInformaticist",))
    order_set = get_order_set(cid)
    data = validate.body()

    signer = None
    if isinstance(data.get("pharmacy_signoff_by_clinician_id"), str):
        signer = get_clinician(data["pharmacy_signoff_by_clinician_id"])
    signer_id = validate.string(data, "pharmacy_signoff_by_clinician_id", required=True)
    validate.string(data, "signoff_note")
    if signer is None:
        get_clinician(signer_id)

    check_freeze("order_set")

    order_set["pharmacy_signoff_by_clinician_id"] = signer_id
    order_set["pharmacy_signoff_at"] = now()
    touch(order_set)
    return ok(order_set)


# ------------------------------------------------------------------ submit for peer review
@bp.post("/cds/order-sets/<cid>/submit-for-peer-review")
def submit_for_peer_review(cid):
    authenticate(("InformaticsBuilder",))
    order_set = get_order_set(cid)
    data = validate.body()
    validate.string(data, "submission_note")

    if order_set["review_state"] != "DRAFT":
        raise ApiError("ERR_ORDER_SET_NOT_DRAFT", "Order set is not DRAFT")
    if order_set["item_count"] < 1:
        raise ApiError("ERR_ORDER_SET_NOT_DRAFT", "Order set carries no items")
    if order_set["publication_state"] not in ("UNPUBLISHED", "EXPIRING", "EXPIRED"):
        raise ApiError("ERR_ORDER_SET_NOT_DRAFT", "Order set publication state forbids resubmission")

    check_freeze("order_set")

    order_set["risk_class"] = domain.order_set_risk_class(order_set)
    order_set["peer_required_votes"] = calc.required_votes(order_set["risk_class"], 0)
    order_set["review_state"] = "PEER_REVIEW"
    touch(order_set)
    return ok(order_set)


# ------------------------------------------------------------------ publication
@bp.post("/cds/order-sets/<cid>/publish")
def publish(cid):
    authenticate(("CommitteeChair",))
    order_set = get_order_set(cid)
    data = validate.body()
    go_live_at = validate.instant(data, "go_live_at", required=True)

    if order_set["publication_state"] != "UNPUBLISHED" or order_set["review_state"] != "APPROVED":
        raise ApiError("ERR_ORDER_SET_NOT_APPROVED", "Order set is not an approved, unpublished build")

    check_freeze("order_set")

    if order_set.get("_deciding_specialty_reviewer_id") == caller_id():
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The deciding specialty approver may not publish this order set",
        )

    if order_set["high_alert_item_count"] >= 1 and order_set["pharmacy_signoff_at"] is None:
        raise ApiError(
            "ERR_HIGH_ALERT_PHARMACY_SIGNOFF_REQUIRED",
            "High-alert content requires pharmacy sign-off before publication",
        )

    release = db.vendor_releases.get(order_set["pinned_vendor_release_id"])
    if release is None or release["review_cycle_state"] != "ACTIVATED":
        raise ApiError("ERR_VENDOR_RELEASE_NOT_ACTIVATED", "Pinned vendor release is not ACTIVATED")

    order_set["publication_state"] = "PUBLISHED"
    order_set["go_live_at"] = go_live_at
    due, expiration, archive = domain.schedule_from(go_live_at, order_set["risk_class"])
    domain.apply_schedule_to_order_set(order_set, due, expiration, archive)
    touch(order_set)

    domain.create_annual_task("ORDER_SET", order_set, due, expiration, archive, cycle_index=1)

    predecessor_id = order_set.get("supersedes_order_set_id")
    if predecessor_id:
        predecessor = db.order_sets.get(predecessor_id)
        if predecessor is not None and predecessor["publication_state"] == "PUBLISHED":
            predecessor["publication_state"] = "SUPERSEDED"
            touch(predecessor)
            task = domain.governing_task("ORDER_SET", predecessor["id"])
            if task is not None:
                task["state"] = "EXPIRED"
                touch(task)
            for alert in sorted(domain.alerts_linked_to(predecessor["id"]),
                                key=lambda a: a.get("_seq", 0)):
                if alert["lifecycle_state"] == "ACTIVE":
                    alert["linked_order_set_id"] = order_set["id"]
                    touch(alert)

    domain.maybe_close_content_request(db.content_requests.get(order_set["content_request_id"]))
    return ok(order_set)
