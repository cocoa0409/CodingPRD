"""Inquiry intake, sensitivity scoring and queue routing (PRD §3.5)."""
from flask import Blueprint

import calc
import validation as V
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from serializers import inquiry_out
from store import (ESCALATION_THRESHOLD, INQUIRY_STATUSES, ROUTING_QUEUES,
                   TOPIC_CATEGORIES, new_row, sorted_rows, store, touch)

bp = Blueprint("inquiries", __name__)


@bp.post("/inquiries")
def create_inquiry():
    V.authorize("IRAdmin", "IRAnalyst")
    b = V.body()
    company_id = V.f_str(b, "company_id", required=True)
    contact_id = V.f_str(b, "contact_id", required=True)
    topic_category = V.f_enum(b, "topic_category", TOPIC_CATEGORIES, required=True)
    subject = V.f_str(b, "subject", required=True, max_len=200)
    requests_nonpublic_detail = V.f_bool(b, "requests_nonpublic_detail", default=False)
    linked_prior_inquiry_id = V.f_str(b, "linked_prior_inquiry_id", default=None)

    # §2.10 step 5: body foreign keys in declaration order
    company = V.get_company(company_id)
    contact = V.get_contact(contact_id)
    prior = None
    if linked_prior_inquiry_id is not None:
        prior = V.get_inquiry(linked_prior_inquiry_id)

    if contact["company_id"] != company["id"]:
        raise ApiError("ERR_CONTACT_COMPANY_MISMATCH",
                       "the named contact belongs to a different issuer")

    score = calc.sensitivity_score(topic_category, requests_nonpublic_detail,
                                   contact, company, prior)
    queue = calc.routing_queue(topic_category, score, contact)

    inquiry = new_row({
        "company_id": company["id"],
        "contact_id": contact["id"],
        "linked_prior_inquiry_id": linked_prior_inquiry_id,
        "topic_category": topic_category,
        "subject": subject,
        "requests_nonpublic_detail": requests_nonpublic_detail,
        "sensitivity_score": score,
        "routing_queue": queue,
        "sla_due_at": None,
        "status": "NEW",
        "answered_at": None,
    })
    calc.recompute_sla(inquiry)
    store.inquiries[inquiry["id"]] = inquiry
    calc.inquiry_count_write(company)
    return created(inquiry_out(inquiry))


@bp.get("/inquiries")
def list_inquiries():
    V.authorize("IRAdmin", "IRAnalyst", "DisclosureOfficer", "TransferAgentLiaison")
    limit, offset = V.q_pagination()
    company_id = V.q_str("company_id")
    contact_id = V.q_str("contact_id")
    linked_prior_inquiry_id = V.q_str("linked_prior_inquiry_id")
    status = V.q_enum("status", INQUIRY_STATUSES)
    queue = V.q_enum("routing_queue", ROUTING_QUEUES)
    topic_category = V.q_enum("topic_category", TOPIC_CATEGORIES)
    rows = sorted_rows(store.inquiries)
    if company_id is not None:
        rows = [r for r in rows if r["company_id"] == company_id]
    if contact_id is not None:
        rows = [r for r in rows if r["contact_id"] == contact_id]
    if linked_prior_inquiry_id is not None:
        rows = [r for r in rows if r["linked_prior_inquiry_id"] == linked_prior_inquiry_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if queue is not None:
        rows = [r for r in rows if r["routing_queue"] == queue]
    if topic_category is not None:
        rows = [r for r in rows if r["topic_category"] == topic_category]
    page, total = paginate(rows, limit, offset)
    return ok_list([inquiry_out(r) for r in page], limit, offset, total)


@bp.get("/inquiries/<inquiry_id>")
def read_inquiry(inquiry_id):
    V.authorize("IRAdmin", "IRAnalyst", "DisclosureOfficer", "TransferAgentLiaison")
    return ok(inquiry_out(V.get_inquiry(inquiry_id)))


@bp.post("/inquiries/<inquiry_id>/route")
def route_inquiry(inquiry_id):
    actor = V.authorize("IRAnalyst", "DisclosureOfficer")
    b = V.body()
    target_queue = V.f_enum(b, "target_queue", ROUTING_QUEUES, default=None)

    inquiry = V.get_inquiry(inquiry_id)
    if inquiry["status"] not in ("NEW", "ESCALATED"):
        raise ApiError("ERR_INQUIRY_INVALID_STATE",
                       "only a NEW or ESCALATED ticket may be routed")

    officer_override = target_queue is not None and actor.role == "DisclosureOfficer"
    if target_queue is not None and actor.role != "DisclosureOfficer":
        raise ApiError("ERR_QUEUE_OVERRIDE_FORBIDDEN",
                       "only a DisclosureOfficer may supply target_queue")
    if inquiry["status"] == "ESCALATED" and not officer_override:
        raise ApiError("ERR_QUEUE_OVERRIDE_FORBIDDEN",
                       "an ESCALATED ticket may only be re-routed by a DisclosureOfficer "
                       "supplying target_queue")

    if inquiry["status"] == "NEW":
        if inquiry["sensitivity_score"] >= ESCALATION_THRESHOLD:
            inquiry["status"] = "ESCALATED"
            inquiry["routing_queue"] = "DISCLOSURE_COMMITTEE"
            calc.recompute_sla(inquiry)
        else:
            inquiry["status"] = "ROUTED"
            if officer_override:
                inquiry["routing_queue"] = target_queue
                calc.recompute_sla(inquiry)
    else:
        inquiry["status"] = "ROUTED"
        inquiry["routing_queue"] = target_queue
        calc.recompute_sla(inquiry)
    touch(inquiry)
    return ok(inquiry_out(inquiry))
