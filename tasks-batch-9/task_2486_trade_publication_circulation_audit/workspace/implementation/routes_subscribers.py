"""The recipient file: enrolment, classification, evidence (PRD 3.2)."""
from flask import Blueprint

import calc
import validation as V
from auth import (OPERATOR_ROLES, ROLE_CIRCULATION_MANAGER,
                  ROLE_QUALIFICATION_SPECIALIST, endpoint)
from envelope import created, ok, paginate
from errors import ApiError
from lookups import get_publication, get_source_document, get_subscriber
from store import (add_months, base_record, collection_sorted, db, now,
                   serialize, touch)

subscribers_bp = Blueprint("subscribers", __name__)

SUB_READ_ROLES = OPERATOR_ROLES
EVIDENCE_WRITE_ROLES = (ROLE_CIRCULATION_MANAGER, ROLE_QUALIFICATION_SPECIALIST)


# --------------------------------------------------------------------------
# POST /circulation/subscribers
# --------------------------------------------------------------------------
@subscribers_bp.route("/circulation/subscribers", methods=["POST"])
@endpoint(ROLE_CIRCULATION_MANAGER)
def create_subscriber():
    payload = V.body()
    pub = get_publication(payload.get("publication_id"))
    fields = V.parse(payload, [
        V.f_id("publication_id"),
        V.f_str("company_name", max_len=200),
        V.f_str("contact_email", max_len=200),
        V.f_str("job_function_code", max_len=40),
        V.f_str("industry_code", max_len=40),
        V.f_enum("purchasing_authority_level", V.PURCHASING_AUTHORITIES),
        V.f_enum("subscription_class", V.SUBSCRIPTION_CLASSES),
        V.f_int("copies", required=False, minimum=1, default=1),
        V.f_int("paid_amount_cents", required=False, minimum=0, default=0),
    ])

    if fields["subscription_class"] == "PAID" and fields["paid_amount_cents"] < 1:
        raise ApiError("ERR_PAID_REQUIRES_PAYMENT",
                       "A PAID recipient requires paid_amount_cents of at least 1.")

    sub = base_record()
    sub.update({
        "publication_id": pub["id"],
        "company_name": fields["company_name"],
        "contact_email": fields["contact_email"],
        "job_function_code": fields["job_function_code"],
        "industry_code": fields["industry_code"],
        "purchasing_authority_level": fields["purchasing_authority_level"],
        "subscription_class": fields["subscription_class"],
        "copies": fields["copies"],
        "paid_amount_cents": fields["paid_amount_cents"],
        "qualification_status": "UNQUALIFIED",
        "delivery_status": "DELIVERABLE",
        "undeliverable_count": 0,
        "qualification_score": 0,
        "qualified_at": None,
        "qualification_expires_at": None,
    })
    db.subscribers[sub["id"]] = sub

    calc.recompute_publication(pub)
    calc.mark_drafts_stale(pub["id"])
    # Enrolment mutates the publication's copies ledger, hygiene ratio and posture,
    # so the publication's own version advances (PRD 2.4).
    touch(pub)
    return created(serialize(sub))


@subscribers_bp.route("/circulation/subscribers/<sub_id>", methods=["GET"])
@endpoint(*SUB_READ_ROLES)
def read_subscriber(sub_id):
    return ok(serialize(get_subscriber(sub_id)))


@subscribers_bp.route("/circulation/subscribers", methods=["GET"])
@endpoint(*SUB_READ_ROLES)
def list_subscribers():
    publication_id = V.filter_str("publication_id")
    qualification_status = V.filter_enum("qualification_status", V.QUALIFICATION_STATUSES)
    delivery_status = V.filter_enum("delivery_status", V.DELIVERY_STATUSES)
    subscription_class = V.filter_enum("subscription_class", V.SUBSCRIPTION_CLASSES)
    rows = list(db.subscribers.values())
    if publication_id:
        rows = [s for s in rows if s["publication_id"] == publication_id]
    if qualification_status:
        rows = [s for s in rows if s["qualification_status"] == qualification_status]
    if delivery_status:
        rows = [s for s in rows if s["delivery_status"] == delivery_status]
    if subscription_class:
        rows = [s for s in rows if s["subscription_class"] == subscription_class]
    return paginate(collection_sorted(rows))


# --------------------------------------------------------------------------
# POST /circulation/subscribers/{id}/reclassify
# --------------------------------------------------------------------------
@subscribers_bp.route("/circulation/subscribers/<sub_id>/reclassify", methods=["POST"])
@endpoint(ROLE_CIRCULATION_MANAGER)
def reclassify_subscriber(sub_id):
    sub = get_subscriber(sub_id)
    payload = V.body()
    fields = V.parse(payload, [
        V.f_enum("subscription_class", V.SUBSCRIPTION_CLASSES),
        V.f_int("paid_amount_cents", required=False, minimum=0, default=None),
    ])

    effective_paid = sub["paid_amount_cents"] if fields["paid_amount_cents"] is None \
        else fields["paid_amount_cents"]
    if fields["subscription_class"] == "PAID" and effective_paid < 1:
        raise ApiError("ERR_PAID_REQUIRES_PAYMENT",
                       "A PAID recipient requires paid_amount_cents of at least 1.")

    sub["subscription_class"] = fields["subscription_class"]
    if fields["paid_amount_cents"] is not None:
        sub["paid_amount_cents"] = fields["paid_amount_cents"]
    touch(sub)

    pub = db.publications.get(sub["publication_id"])
    if pub is not None:
        calc.recompute_publication(pub)
        calc.mark_drafts_stale(pub["id"])
        # Reclassification moves copies between the publication's class buckets,
        # so the publication is mutated and its version advances (PRD 2.4).
        touch(pub)
    return ok(serialize(sub))


# --------------------------------------------------------------------------
# POST /circulation/subscribers/{id}/undeliverable-events
# --------------------------------------------------------------------------
@subscribers_bp.route("/circulation/subscribers/<sub_id>/undeliverable-events", methods=["POST"])
@endpoint(ROLE_CIRCULATION_MANAGER)
def record_undeliverable_event(sub_id):
    sub = get_subscriber(sub_id)
    payload = V.body()
    V.parse(payload, [V.f_str("reason_code", required=False, max_len=200, default=None)])
    sub["undeliverable_count"] = sub["undeliverable_count"] + 1
    touch(sub)
    return ok(serialize(sub))


# --------------------------------------------------------------------------
# source documents
# --------------------------------------------------------------------------
@subscribers_bp.route("/circulation/subscribers/<sub_id>/source-documents", methods=["POST"])
@endpoint(*EVIDENCE_WRITE_ROLES)
def create_source_document(sub_id):
    sub = get_subscriber(sub_id)
    payload = V.body()

    def cross(values):
        if values["captured_at"] > now():
            raise ApiError("ERR_INVALID_REQUEST",
                           "captured_at may not lie in the future of the logical clock.")

    fields = V.parse(payload, [
        V.f_enum("doc_type", V.DOC_TYPES),
        V.f_dt("captured_at"),
        V.f_str("storage_ref", max_len=120),
    ], cross=cross)

    pub = db.publications.get(sub["publication_id"])
    retention_months = pub["source_doc_retention_months"] if pub else 36

    doc = base_record()
    doc.update({
        "subscriber_id": sub["id"],
        "doc_type": fields["doc_type"],
        "captured_at": fields["captured_at"],
        "storage_ref": fields["storage_ref"],
        "retention_expires_at": add_months(fields["captured_at"], retention_months),
        "purge_status": "RETAINED",
        "purged_at": None,
    })
    db.source_documents[doc["id"]] = doc
    return created(serialize(doc))


@subscribers_bp.route("/circulation/subscribers/<sub_id>/source-documents", methods=["GET"])
@endpoint(*SUB_READ_ROLES)
def list_source_documents(sub_id):
    sub = get_subscriber(sub_id)
    purge_status = V.filter_enum("purge_status", V.PURGE_STATUSES)
    rows = [d for d in db.source_documents.values() if d["subscriber_id"] == sub["id"]]
    if purge_status:
        rows = [d for d in rows if d["purge_status"] == purge_status]
    return paginate(collection_sorted(rows))


@subscribers_bp.route("/circulation/source-documents/<doc_id>/purge", methods=["POST"])
@endpoint(ROLE_CIRCULATION_MANAGER)
def purge_source_document(doc_id):
    doc = get_source_document(doc_id)
    payload = V.body()
    V.parse(payload, [V.f_str("purge_reason", required=False, max_len=500, default=None)])

    if doc["purge_status"] != "RETAINED":
        raise ApiError("ERR_INVALID_STATE", "This source document is already purged.")
    if now() < doc["retention_expires_at"]:
        raise ApiError("ERR_RETENTION_NOT_ELAPSED",
                       "The retention period has not elapsed yet.")

    doc["purge_status"] = "PURGED"
    doc["purged_at"] = now()
    touch(doc)
    return ok(serialize(doc))
