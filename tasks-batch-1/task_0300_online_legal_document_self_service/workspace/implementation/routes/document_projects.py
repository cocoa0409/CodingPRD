"""DocumentProject routes: create (credit consumption + Order), questionnaire
upsert, assemble, and lifecycle transitions."""

from flask import Blueprint, request

import constants
import errors
import validators
from common import (
    base_entity,
    get_or_404,
    list_collection,
    parse_datetime,
    serialize,
    touch,
)
from db import store
from middleware import get_json_body, parse_pagination, roles
from response import array_response, object_response
from routes.subscriptions import recompute_credits
from services.pricing import (
    compute_assembled_completeness,
    compute_provisional_completeness,
    document_portion_cents,
    order_for_project,
    recompute_net,
    required_mandatory_count,
    set_provisional_quote,
)

bp = Blueprint("document_projects", __name__)

PROJECT_STATES = {
    "DRAFT", "IN_PROGRESS", "ASSEMBLED", "IN_REVIEW", "CHANGES_REQUESTED",
    "FINALIZED", "SIGNED", "STORED", "ABANDONED", "STORAGE_LOCKED",
}


# --------------------------------------------------------------------------
# Lease term overlap (PRD §3.8): closed interval + LEASE_TURNOVER_BUFFER_DAYS
# gap between consecutive terms, against existing non-ABANDONED LEASE projects
# on the same lease_property_ref.
# --------------------------------------------------------------------------
def _lease_overlaps(property_ref, start, end, exclude_id=None):
    buffer = constants.LEASE_TURNOVER_BUFFER_DAYS
    from datetime import timedelta
    gap = timedelta(days=buffer)
    for p in store.document_projects.values():
        if p["id"] == exclude_id:
            continue
        if p["document_type"] != "LEASE":
            continue
        if p["status"] == "ABANDONED":
            continue
        if p.get("lease_property_ref") != property_ref:
            continue
        other_start = parse_datetime(p["lease_start_date"], "lease_start_date")
        other_end = parse_datetime(p["lease_end_date"], "lease_end_date")
        # Terms must not overlap AND consecutive terms must be separated by at
        # least the turnover buffer. They are adequately separated if the new
        # term starts >= buffer after the existing term ends, OR the existing
        # term starts >= buffer after the new term ends. A gap of EXACTLY the
        # buffer (e.g. 7 days) is allowed; anything less is a conflict.
        separated_after = start >= other_end + gap
        separated_before = other_start >= end + gap
        if not (separated_after or separated_before):
            return True
    return False


@bp.route("/legal/document-projects", methods=["POST"])
@roles("Customer")
def create_project():
    body = get_json_body()
    customer_id = validators.require_string(body, "customer_id")
    subscription_id = validators.require_string(body, "subscription_id")
    doc_type = validators.require_enum(body, "document_type", constants.DOCUMENT_TYPES)
    state = validators.require_enum(body, "state_code", constants.STATE_CODES)
    title = validators.require_string(body, "title")
    addon = validators.optional_bool(body, "attorney_review_addon", default=False)

    # Existence (404), left-to-right.
    customer = store.customers.get(customer_id)
    if customer is None:
        raise errors.not_found("customer_id does not exist")
    subscription = store.subscriptions.get(subscription_id)
    if subscription is None:
        raise errors.not_found("subscription_id does not exist")

    # Reference consistency (409): subscription must belong to the customer,
    # and the project's state must equal the customer's state_of_residence.
    if subscription["customer_id"] != customer_id:
        raise errors.reference_invalid("subscription_id does not belong to customer_id")
    if state != customer["state_of_residence"]:
        raise errors.reference_invalid("state_code must equal customer's state_of_residence")

    # Lease-only fields.
    lease_property_ref = None
    lease_start_date = None
    lease_end_date = None
    if doc_type == "LEASE":
        lease_property_ref = body.get("lease_property_ref")
        lease_start_date = body.get("lease_start_date")
        lease_end_date = body.get("lease_end_date")

    plan = store.subscription_plans.get(subscription["plan_id"])

    # Credit availability (402) — business_fiscal.
    if subscription["credits_remaining"] < 1:
        raise errors.ApiError(errors.ERR_NO_CREDITS_REMAINING, 402,
                              "No subscription credits remaining")

    # Lease term overlap (409) — only for LEASE with a property ref + dates.
    if (doc_type == "LEASE" and lease_property_ref is not None
            and lease_start_date is not None and lease_end_date is not None):
        start = parse_datetime(lease_start_date, "lease_start_date")
        end = parse_datetime(lease_end_date, "lease_end_date")
        if _lease_overlaps(lease_property_ref, start, end):
            raise errors.ApiError(errors.ERR_LEASE_TERM_OVERLAP, 409,
                                  "Lease term overlaps an existing lease on this property")

    ent = base_entity()
    ent.update({
        "customer_id": customer_id,
        "subscription_id": subscription_id,
        "document_type": doc_type,
        "state_code": state,
        "title": title,
        "attorney_review_addon": addon,
        "lease_property_ref": lease_property_ref,
        "lease_start_date": lease_start_date,
        "lease_end_date": lease_end_date,
        "status": "DRAFT",
        "provisional_completeness": 0.0,
        "assembled_completeness": 0.0,
        "assembled_clause_count": 0,
        "credit_held": True,
    })
    store.document_projects[ent["id"]] = ent

    # Consume a credit (credit_conservation).
    subscription["credits_used"] += 1
    recompute_credits(subscription, plan)
    touch(subscription)

    # Create the Order side effect, all monetary fields 0.
    order = base_entity()
    order.update({
        "document_project_id": ent["id"],
        "provisional_quote_cents": 0,
        "final_invoice_cents": 0,
        "amount_charged_cents": 0,
        "amount_refunded_cents": 0,
        "net_collected_cents": 0,
    })
    store.orders[order["id"]] = order

    return object_response(serialize(ent), 201)


@bp.route("/legal/document-projects/<pid>", methods=["GET"])
@roles("Customer", "Attorney", "PlatformAdmin")
def get_project(pid):
    ent = get_or_404(store.document_projects, pid)
    return object_response(serialize(ent), 200)


@bp.route("/legal/document-projects", methods=["GET"])
@roles("Customer", "Attorney", "PlatformAdmin")
def list_projects():
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    subscription_id = request.args.get("subscription_id")

    def predicate(e):
        if customer_id is not None and e["customer_id"] != customer_id:
            return False
        if subscription_id is not None and e["subscription_id"] != subscription_id:
            return False
        return True

    page, total = list_collection(store.document_projects, predicate, limit, offset)
    return array_response(page, limit, offset, total, 200)


# --------------------------------------------------------------------------
# Questionnaire upsert (1:1). First upsert: DRAFT -> IN_PROGRESS.
# --------------------------------------------------------------------------
@bp.route("/legal/document-projects/<pid>/questionnaire", methods=["PUT"])
@roles("Customer")
def upsert_questionnaire(pid):
    project = get_or_404(store.document_projects, pid)
    body = get_json_body()
    answers = validators.require_object(body, "answers")

    # State gate: only DRAFT (first) or IN_PROGRESS (subsequent self-loop).
    if project["status"] not in ("DRAFT", "IN_PROGRESS"):
        raise errors.invalid_state("Questionnaire can only be upserted in DRAFT or IN_PROGRESS")

    answered, total, ratio = compute_provisional_completeness(project, answers)

    # Find existing response (1:1) or create.
    existing = None
    for r in store.questionnaire_responses.values():
        if r["document_project_id"] == pid:
            existing = r
            break

    if existing is None:
        resp = base_entity()
        resp.update({
            "document_project_id": pid,
            "answers": answers,
            "answered_required_count": answered,
            "total_required_count": total,
        })
        store.questionnaire_responses[resp["id"]] = resp
    else:
        resp = existing
        resp["answers"] = answers
        resp["answered_required_count"] = answered
        resp["total_required_count"] = total
        touch(resp)

    # First upsert moves DRAFT -> IN_PROGRESS.
    if project["status"] == "DRAFT":
        project["status"] = "IN_PROGRESS"
    project["provisional_completeness"] = ratio
    touch(project)

    return object_response(serialize(resp), 200)


@bp.route("/legal/document-projects/<pid>/questionnaire", methods=["GET"])
@roles("Customer", "Attorney", "PlatformAdmin")
def get_questionnaire(pid):
    project = get_or_404(store.document_projects, pid)
    limit, offset = parse_pagination()

    def predicate(e):
        return e["document_project_id"] == pid

    page, total = list_collection(store.questionnaire_responses, predicate, limit, offset)
    return array_response(page, limit, offset, total, 200)


# --------------------------------------------------------------------------
# Assemble: IN_PROGRESS -> ASSEMBLED.
# --------------------------------------------------------------------------
@bp.route("/legal/document-projects/<pid>/assemble", methods=["POST"])
@roles("Customer")
def assemble_project(pid):
    project = get_or_404(store.document_projects, pid)

    # State gate first (ERR_INVALID_STATE precedes business rules).
    if project["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Assemble requires project status IN_PROGRESS")

    # Business gate: questionnaire complete.
    if project["provisional_completeness"] < 1.0:
        raise errors.ApiError(errors.ERR_QUESTIONNAIRE_INCOMPLETE, 409,
                              "Questionnaire is not fully answered")

    # Business gate: at least one ClauseTemplate for (type,state).
    matching = [
        t for t in store.clause_templates.values()
        if t["document_type"] == project["document_type"]
        and t["state_code"] == project["state_code"]
    ]
    if len(matching) == 0:
        raise errors.ApiError(errors.ERR_NO_CLAUSE_TEMPLATES, 409,
                              "No clause templates exist for this document type and state")

    # Snapshot clauses in deterministic creation order of the templates.
    matching.sort(key=lambda t: t["_seq"])
    for t in matching:
        ac = base_entity(with_version=False)  # AssembledClause: id + created_at only
        ac.update({
            "document_project_id": pid,
            "source_clause_template_id": t["id"],
            "clause_key": t["clause_key"],
            "is_mandatory": t["is_mandatory"],
            "body_text": t["body_text"],
        })
        store.assembled_clauses[ac["id"]] = ac

    project["assembled_clause_count"] = len(matching)
    project["status"] = "ASSEMBLED"
    project["assembled_completeness"] = compute_assembled_completeness(project)
    touch(project)

    # Recompute provisional quote (document portion only).
    sub = store.subscriptions.get(project["subscription_id"])
    plan = store.subscription_plans.get(sub["plan_id"]) if sub else None
    if plan is not None:
        set_provisional_quote(project, plan)

    return object_response(serialize(project), 200)


# --------------------------------------------------------------------------
# Project lifecycle transitions (IN_PROGRESS reopen, FINALIZED, STORED, ABANDONED).
# --------------------------------------------------------------------------
@bp.route("/legal/document-projects/<pid>/transition", methods=["POST"])
@roles("Customer")
def transition_project(pid):
    project = get_or_404(store.document_projects, pid)
    body = get_json_body()
    to_status = validators.require_enum(body, "to_status", PROJECT_STATES)

    current = project["status"]

    if to_status == "IN_PROGRESS":
        # Only valid from CHANGES_REQUESTED (revision loop reopen).
        if current != "CHANGES_REQUESTED":
            raise errors.invalid_state("IN_PROGRESS reopen requires CHANGES_REQUESTED")
        project["status"] = "IN_PROGRESS"
        touch(project)

    elif to_status == "FINALIZED":
        if current not in ("ASSEMBLED", "CHANGES_REQUESTED"):
            raise errors.invalid_state("Finalize requires ASSEMBLED or CHANGES_REQUESTED")
        # Mandatory-clause completeness gate (read live).
        completeness = compute_assembled_completeness(project)
        project["assembled_completeness"] = completeness
        if completeness < 1.0:
            raise errors.ApiError(errors.ERR_MANDATORY_CLAUSE_MISSING, 409,
                                  "A mandatory clause is missing")
        # Review-in-progress gate (applies when finalizing from ASSEMBLED).
        if current == "ASSEMBLED":
            in_flight = any(
                r["document_project_id"] == pid
                and r["status"] in ("REQUESTED", "ASSIGNED", "IN_REVIEW")
                for r in store.attorney_reviews.values()
            )
            if in_flight:
                raise errors.ApiError(errors.ERR_REVIEW_IN_PROGRESS, 409,
                                      "An attorney review is still in progress")
        _finalize_pricing(project)
        project["status"] = "FINALIZED"
        touch(project)

    elif to_status == "STORED":
        if current != "SIGNED":
            raise errors.invalid_state("STORED requires SIGNED")
        project["status"] = "STORED"
        touch(project)

    elif to_status == "ABANDONED":
        if current not in ("DRAFT", "IN_PROGRESS"):
            raise errors.invalid_state("ABANDONED requires DRAFT or IN_PROGRESS")
        project["status"] = "ABANDONED"
        # Return the held credit (credit_conservation).
        if project.get("credit_held"):
            project["credit_held"] = False
            sub = store.subscriptions.get(project["subscription_id"])
            if sub is not None:
                sub["credits_used"] = max(0, sub["credits_used"] - 1)
                plan = store.subscription_plans.get(sub["plan_id"])
                if plan is not None:
                    recompute_credits(sub, plan)
                touch(sub)
        touch(project)

    else:
        # STAGE/SIGNED/STORAGE_LOCKED etc. are not client-driven via this endpoint.
        raise errors.invalid_state(f"Unsupported target status {to_status}")

    return object_response(serialize(project), 200)


def _finalize_pricing(project):
    """final_pricing: doc_portion + review_line + notary_line.
    amount_charged_cents is additive — add (doc_portion + notary_line) here;
    the review surcharge was already charged at review request."""
    order = order_for_project(project["id"])
    sub = store.subscriptions.get(project["subscription_id"])
    plan = store.subscription_plans.get(sub["plan_id"]) if sub else None
    if order is None or plan is None:
        return

    doc_portion = document_portion_cents(project, plan)

    # Active review line: sum surcharge over APPROVED reviews of this project.
    review_line = sum(
        r["surcharge_cents"] for r in store.attorney_reviews.values()
        if r["document_project_id"] == project["id"] and r["status"] == "APPROVED"
    )

    # Active notary line: NOTARY_FEE if any SignatureRequest on a FINAL revision
    # of this project has notary_required == true.
    final_revision_ids = {
        rev["id"] for rev in store.document_revisions.values()
        if rev["document_project_id"] == project["id"] and rev["status"] == "FINAL"
    }
    notary_active = any(
        sr["notary_required"] is True and sr["document_revision_id"] in final_revision_ids
        for sr in store.signature_requests.values()
    )
    notary_line = constants.NOTARY_FEE_CENTS if notary_active else 0

    order["final_invoice_cents"] = doc_portion + review_line + notary_line
    order["amount_charged_cents"] += (doc_portion + notary_line)
    recompute_net(order)
    touch(order)
