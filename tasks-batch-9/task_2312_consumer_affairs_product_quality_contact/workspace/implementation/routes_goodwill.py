"""Goodwill remedies: pricing, authority tiers and the consumer ledger."""

from flask import Blueprint

import calc
import serializers as ser
import services as svc
from common import (
    ROLE_CARE_AGENT,
    ROLE_CARE_SUPERVISOR,
    ROLE_QUALITY_LEAD,
    authorize,
    base_record,
    check_required,
    err,
    get_body,
    must_get,
    now,
    pagination,
    paginated,
    q_str,
    sort_records,
    store,
    success,
    touch,
    v_enum,
    v_int,
    v_string,
)

bp = Blueprint("goodwill", __name__)

REMEDY_TYPES = ("COUPON", "REFUND", "REPLACEMENT")
DECISIONS = ("APPROVE", "REJECT", "REQUEST_REVISION")
BLOCKED_FOR_SUBMIT = ("ON_QUALITY_HOLD", "RESOLVED", "CLOSED", "DUPLICATE")
IN_FLIGHT_KIT_STATES = ("REQUESTED", "SHIPPED", "IN_TRANSIT_INBOUND")


def _check_ceiling(figures):
    if figures["payout_cents"] > calc.GOODWILL_MAX_PAYOUT_CENTS:
        raise err(
            "ERR_GOODWILL_ABOVE_MAX",
            "the computed payout exceeds the goodwill ceiling",
        )


@bp.post("/remedies")
def create_remedy():
    actor = authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR])
    body = get_body()
    if "complaint_id" in body and body["complaint_id"] is not None:
        must_get("complaints", body["complaint_id"])
    check_required(
        body, ["complaint_id", "remedy_type", "requested_value_cents", "expected_complaint_version"]
    )
    complaint_id = v_string(body, "complaint_id", 1)
    remedy_type = v_enum(body, "remedy_type", REMEDY_TYPES)
    requested_value_cents = v_int(body, "requested_value_cents", 1, 999999)
    expected_version = v_int(body, "expected_complaint_version", 0)

    complaint = store.complaints[complaint_id]
    if expected_version != complaint["version"]:
        raise err(
            "ERR_STALE_COMPLAINT_VERSION",
            "expected_complaint_version does not match the complaint's current version",
        )

    rec = base_record()
    rec.update(
        {
            "complaint_id": complaint_id,
            "consumer_id": complaint["consumer_id"],
            "remedy_type": remedy_type,
            "requested_value_cents": requested_value_cents,
            "status": "DRAFT",
            "revision_count": 0,
            "authored_by_ref": actor.user_id,
            "decided_by_ref": None,
            "fulfilled_at": None,
            "kit_returned_credit_applied": False,
        }
    )
    figures = calc.goodwill_authorization(rec, complaint)
    _check_ceiling(figures)
    rec.update(figures)

    for other in svc.remedies_of_complaint(complaint_id):
        if other["status"] in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED"):
            other["status"] = "SUPERSEDED"
            touch(other)

    store.remedies[rec["id"]] = rec
    return success(ser.remedy(rec), 201)


@bp.get("/remedies")
def list_remedies():
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD])
    limit, offset = pagination()
    filters = {
        "complaint_id": q_str("complaint_id"),
        "consumer_id": q_str("consumer_id"),
        "status": q_str("status"),
        "remedy_type": q_str("remedy_type"),
    }
    items = []
    for rec in sort_records(list(store.remedies.values())):
        if any(value is not None and rec.get(key) != value for key, value in filters.items()):
            continue
        items.append(ser.remedy(rec))
    return paginated(items, limit, offset)


@bp.get("/remedies/<record_id>")
def get_remedy(record_id):
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD])
    rec = must_get("remedies", record_id)
    return success(ser.remedy(rec))


@bp.post("/remedies/<record_id>/submit")
def submit_remedy(record_id):
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR])
    rec = must_get("remedies", record_id)
    body = get_body()
    v_string(body, "submit_note", 0)

    complaint = store.complaints.get(rec["complaint_id"])
    if rec["status"] == "DRAFT":
        if complaint is not None and complaint["handling_status"] in BLOCKED_FOR_SUBMIT:
            raise err(
                "ERR_REMEDY_STATE_INVALID",
                "the parent complaint's handling_status does not permit submission",
            )
    elif rec["status"] == "REVISION_REQUESTED":
        if rec["revision_count"] > calc.MAX_REMEDY_REVISIONS:
            raise err("ERR_REMEDY_STATE_INVALID", "the revision cap has been exceeded")
    else:
        raise err(
            "ERR_REMEDY_STATE_INVALID", "only a DRAFT or REVISION_REQUESTED remedy may be submitted"
        )

    figures = calc.goodwill_authorization(rec, complaint or {})
    _check_ceiling(figures)
    rec.update(figures)
    rec["status"] = "SUBMITTED"
    touch(rec)
    return success(ser.remedy(rec))


@bp.post("/remedies/<record_id>/decide")
def decide_remedy(record_id):
    actor = authorize([ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD])
    rec = must_get("remedies", record_id)
    body = get_body()
    check_required(body, ["decision"])
    decision = v_enum(body, "decision", DECISIONS)
    v_string(body, "decision_note", 0)

    if rec["status"] != "SUBMITTED":
        raise err("ERR_REMEDY_STATE_INVALID", "only a SUBMITTED remedy may be decided")

    if decision == "APPROVE":
        for kit in svc.kits_of_complaint(rec["complaint_id"]):
            if kit["status"] in IN_FLIGHT_KIT_STATES:
                raise err(
                    "ERR_SAMPLE_KIT_IN_FLIGHT",
                    "the complaint's sample kit is still in flight",
                )
    if decision == "REQUEST_REVISION" and rec["revision_count"] >= calc.MAX_REMEDY_REVISIONS:
        raise err("ERR_REVISION_LIMIT_REACHED", "the remedy revision cap has been reached")

    if actor.user_id == rec["authored_by_ref"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "the decider may not be the author of the remedy")

    if decision == "APPROVE":
        tier = actor.authority_tier or "TIER_1"
        if calc.TIER_RANK[tier] < calc.TIER_RANK[rec["authority_tier_required"]]:
            raise err(
                "ERR_AUTHORITY_TIER_INSUFFICIENT",
                "the deciding staff member's authority tier is too low",
            )
        _check_ceiling(rec)

    if decision == "REQUEST_REVISION":
        rec["status"] = "REVISION_REQUESTED"
        rec["revision_count"] += 1
    elif decision == "REJECT":
        rec["status"] = "REJECTED"
        rec["decided_by_ref"] = actor.user_id
    else:
        rec["status"] = "APPROVED"
        rec["decided_by_ref"] = actor.user_id
    touch(rec)

    if decision == "APPROVE":
        consumer = store.consumers.get(rec["consumer_id"])
        if consumer is not None:
            consumer["goodwill_authorized_cents"] += rec["payout_cents"]
            consumer["goodwill_outstanding_cents"] += rec["payout_cents"]
            touch(consumer)
    return success(ser.remedy(rec))


@bp.post("/remedies/<record_id>/fulfill")
def fulfill_remedy(record_id):
    authorize([ROLE_CARE_SUPERVISOR])
    rec = must_get("remedies", record_id)
    body = get_body()
    v_string(body, "fulfilment_reference", 0)

    if rec["status"] != "APPROVED":
        raise err("ERR_REMEDY_STATE_INVALID", "only an APPROVED remedy may be fulfilled")
    complaint = store.complaints.get(rec["complaint_id"])
    if complaint is not None and complaint["handling_status"] == "ON_QUALITY_HOLD":
        raise err("ERR_REMEDY_STATE_INVALID", "the parent complaint is on quality hold")

    rec["status"] = "FULFILLED"
    rec["fulfilled_at"] = now()
    touch(rec)

    payout = rec["payout_cents"]
    consumer = store.consumers.get(rec["consumer_id"])
    if consumer is not None:
        consumer["goodwill_outstanding_cents"] -= payout
        consumer["goodwill_paid_cents"] += payout
        touch(consumer)
    lot = store.production_lots.get(complaint.get("lot_id")) if complaint else None
    if lot is not None:
        lot["goodwill_charged_cents"] += payout
        touch(lot)
    return success(ser.remedy(rec))


@bp.post("/remedies/<record_id>/void")
def void_remedy(record_id):
    authorize([ROLE_CARE_SUPERVISOR])
    rec = must_get("remedies", record_id)
    body = get_body()
    v_string(body, "reason", 0)

    if rec["status"] not in ("APPROVED", "FULFILLED"):
        raise err(
            "ERR_REMEDY_STATE_INVALID", "only an APPROVED or FULFILLED remedy may be voided"
        )
    complaint = store.complaints.get(rec["complaint_id"])
    if complaint is not None and complaint["handling_status"] == "CLOSED":
        raise err("ERR_REMEDY_STATE_INVALID", "the parent complaint is closed")

    rec["status"] = "VOIDED_AFTER_FULFILLMENT"
    touch(rec)

    payout = rec["payout_cents"]
    consumer = store.consumers.get(rec["consumer_id"])
    if consumer is not None:
        consumer["goodwill_paid_cents"] -= payout
        consumer["goodwill_voided_cents"] += payout
        touch(consumer)
    lot = store.production_lots.get(complaint.get("lot_id")) if complaint else None
    if lot is not None:
        lot["goodwill_charged_cents"] -= payout
        touch(lot)
    return success(ser.remedy(rec))
