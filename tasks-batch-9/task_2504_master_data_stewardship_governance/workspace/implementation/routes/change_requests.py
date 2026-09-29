"""Change control over reference data and hierarchies (PRD 3.8)."""

from flask import Blueprint, g

import db
import response
import services
import validation as v
from auth import endpoint, entitle, identity_mismatch, is_owner_of
from errors import fail, invalid

bp = Blueprint("change_requests", __name__)

CHANGE_TYPES = ("REFERENCE_VALUE_ADD", "HIERARCHY_RESTRUCTURE", "CLASSIFICATION_UPLIFT")
STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED", "APPROVED",
            "REJECTED", "SCHEDULED", "APPLIED", "WITHDRAWN")
DECISIONS = ("APPROVE", "REQUEST_CHANGES", "REJECT")
CLASSIFICATIONS = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED")
READERS = ("GovernanceAdmin", "DataOwner", "DataSteward", "ConsumerRep", "Auditor")

NON_TERMINAL = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED",
                "APPROVED", "SCHEDULED")

REQUIRED_KEYS = {
    "REFERENCE_VALUE_ADD": ("reference_value",),
    "HIERARCHY_RESTRUCTURE": ("parent_node_key", "child_node_key"),
    "CLASSIFICATION_UPLIFT": ("target_classification_level",),
}


def _notify(change_request, domain):
    """The schedule-time notification fan-out over the impacted consumer set."""
    for subscription in services.impacted_consumers(change_request, domain):
        subscription["pending_change_request_id"] = change_request["id"]
        subscription["notified_at"] = db.now()
        subscription["acknowledged_at"] = None
        subscription["acknowledged_revision"] = None
        db.bump(subscription)


@bp.post("/mdm/change-requests")
@endpoint("DataSteward", "DataOwner")
def create_change_request():
    body = v.body()
    domain_id = v.req_str(body, "domain_id", 1)
    change_type = v.req_enum(body, "change_type", CHANGE_TYPES)
    title = v.req_str(body, "title", 1, 120)
    proposed_values = v.req_obj(body, "proposed_values")

    for key in REQUIRED_KEYS[change_type]:
        value = proposed_values.get(key)
        if value is None or (isinstance(value, str) and value == ""):
            invalid("Field 'proposed_values.%s' is required for change_type %s."
                    % (key, change_type))
    if change_type == "CLASSIFICATION_UPLIFT":
        target = proposed_values.get("target_classification_level")
        if not isinstance(target, str) or target not in CLASSIFICATIONS:
            invalid("Field 'proposed_values.target_classification_level' must be one "
                    "of %s." % ", ".join(CLASSIFICATIONS))
    if change_type == "HIERARCHY_RESTRUCTURE":
        for key in ("parent_node_key", "child_node_key"):
            if not isinstance(proposed_values.get(key), str):
                invalid("Field 'proposed_values.%s' must be a string." % key)

    domain = db.resolve(db.store.domains, domain_id, "ERR_DOMAIN_NOT_FOUND")
    entitle(domain)

    if change_type == "HIERARCHY_RESTRUCTURE":
        if proposed_values["parent_node_key"] == proposed_values["child_node_key"]:
            fail("ERR_HIERARCHY_CYCLE",
                 "parent_node_key and child_node_key must name different nodes.")

    if change_type == "CLASSIFICATION_UPLIFT":
        target = proposed_values["target_classification_level"]
        if services.rank(target) <= services.rank(domain["classification_level"]):
            fail("ERR_CLEARANCE_INSUFFICIENT",
                 "target_classification_level must rank strictly above the domain's "
                 "current classification_level.")

    change_request = db.create("ChangeRequest", {
        "domain_id": domain["id"],
        "requester_steward_id": g.user_id,
        "reviewer_steward_id": None,
        "change_type": change_type,
        "structural": change_type != "REFERENCE_VALUE_ADD",
        "title": title,
        "proposed_values": dict(proposed_values),
        "status": "DRAFT",
        "impact_consumer_count": 0,
        "required_lead_days": 0,
        "submitted_at": None,
        "earliest_apply_at": None,
        "scheduled_apply_at": None,
        "freeze_window_start": None,
        "freeze_window_end": None,
        "revision_cycle_count": 0,
        "applied_at": None,
        "review_note": None,
        "withdraw_reason": None,
    })
    db.store.change_requests[change_request["id"]] = change_request
    return response.created(change_request)


@bp.get("/mdm/change-requests")
@endpoint(*READERS)
def list_change_requests():
    limit, offset = v.pagination()
    domain_id = v.str_filter("domain_id")
    requester_steward_id = v.str_filter("requester_steward_id")
    reviewer_steward_id = v.str_filter("reviewer_steward_id")
    status = v.enum_filter("status", STATUSES)
    change_type = v.enum_filter("change_type", CHANGE_TYPES)

    rows = db.ordered(db.store.change_requests)
    if domain_id is not None:
        rows = [r for r in rows if r["domain_id"] == domain_id]
    if requester_steward_id is not None:
        rows = [r for r in rows if r["requester_steward_id"] == requester_steward_id]
    if reviewer_steward_id is not None:
        rows = [r for r in rows if r["reviewer_steward_id"] == reviewer_steward_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if change_type is not None:
        rows = [r for r in rows if r["change_type"] == change_type]
    return response.collection(rows, limit, offset)


@bp.get("/mdm/change-requests/<change_request_id>")
@endpoint(*READERS)
def read_change_request(change_request_id):
    change_request = db.resolve(db.store.change_requests, change_request_id,
                                "ERR_CHANGE_REQUEST_NOT_FOUND")
    return response.entity(change_request)


@bp.post("/mdm/change-requests/<change_request_id>/submit")
@endpoint("DataSteward", "DataOwner")
def submit_change_request(change_request_id):
    change_request = db.resolve(db.store.change_requests, change_request_id,
                                "ERR_CHANGE_REQUEST_NOT_FOUND")
    domain = db.store.domains[change_request["domain_id"]]
    entitle(domain)

    if change_request["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "Submission is only available from DRAFT or CHANGES_REQUESTED status.")
    if domain["status"] != "ACTIVE":
        fail("ERR_DOMAIN_NOT_ACTIVE", "The owning domain is not ACTIVE.")

    if change_request["requester_steward_id"] != g.user_id:
        identity_mismatch("Only the originating steward may submit this request.")

    resubmission = change_request["status"] == "CHANGES_REQUESTED"
    change_request["status"] = "SUBMITTED"
    change_request["submitted_at"] = db.now()
    if resubmission:
        change_request["revision_cycle_count"] += 1
    services.assess_impact(change_request, domain)
    db.bump(change_request)
    return response.entity(change_request)


@bp.post("/mdm/change-requests/<change_request_id>/review")
@endpoint("DataOwner")
def review_change_request(change_request_id):
    change_request = db.resolve(db.store.change_requests, change_request_id,
                                "ERR_CHANGE_REQUEST_NOT_FOUND")
    domain = db.store.domains[change_request["domain_id"]]
    entitle(domain)

    if change_request["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Review is only available from SUBMITTED status.")

    if change_request["requester_steward_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The steward who raised the request may not review it.")

    change_request["status"] = "UNDER_REVIEW"
    change_request["reviewer_steward_id"] = g.user_id
    db.bump(change_request)
    return response.entity(change_request)


@bp.post("/mdm/change-requests/<change_request_id>/decide")
@endpoint("DataOwner")
def decide_change_request(change_request_id):
    change_request = db.resolve(db.store.change_requests, change_request_id,
                                "ERR_CHANGE_REQUEST_NOT_FOUND")
    body = v.body()
    decision = v.req_enum(body, "decision", DECISIONS)
    review_note = v.opt_str(body, "review_note", 0)

    domain = db.store.domains[change_request["domain_id"]]
    entitle(domain)

    if change_request["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A decision is only available from UNDER_REVIEW status.")

    if change_request["reviewer_steward_id"] != g.user_id:
        identity_mismatch("Only the data owner who took the request under review may "
                          "decide it.")

    if decision == "APPROVE":
        if change_request["structural"]:
            for subscription in db.subscriptions_of(domain["id"]):
                if (subscription["status"] == "ACTIVE"
                        and subscription["criticality"] == "TIER1"
                        and subscription["lineage_status"] != "DOCUMENTED"):
                    fail("ERR_LINEAGE_INCOMPLETE",
                         "Every ACTIVE TIER1 consumer must have DOCUMENTED lineage "
                         "before a structural change is approved.")
        change_request["status"] = "APPROVED"
    elif decision == "REQUEST_CHANGES":
        change_request["status"] = "CHANGES_REQUESTED"
        change_request["reviewer_steward_id"] = None
        change_request["impact_consumer_count"] = 0
        change_request["required_lead_days"] = 0
        change_request["earliest_apply_at"] = None
    else:
        change_request["status"] = "REJECTED"

    change_request["review_note"] = review_note
    db.bump(change_request)
    return response.entity(change_request)


@bp.post("/mdm/change-requests/<change_request_id>/schedule")
@endpoint("DataOwner")
def schedule_change_request(change_request_id):
    change_request = db.resolve(db.store.change_requests, change_request_id,
                                "ERR_CHANGE_REQUEST_NOT_FOUND")
    body = v.body()
    scheduled_apply_at = v.req_dt(body, "scheduled_apply_at")

    domain = db.store.domains[change_request["domain_id"]]
    entitle(domain)

    if change_request["status"] != "APPROVED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Scheduling is only available from APPROVED status.")

    earliest = change_request["earliest_apply_at"]
    if earliest is not None and scheduled_apply_at < earliest:
        fail("ERR_LEAD_TIME_NOT_SATISFIED",
             "scheduled_apply_at must fall at or after the computed earliest_apply_at.")

    start, end = services.freeze_window(change_request, scheduled_apply_at)
    if services.window_conflicts(change_request, domain, start, end):
        fail("ERR_FREEZE_WINDOW_CONFLICT",
             "The freeze window does not clear another scheduled window by 72 hours.")

    if services.calendar_capacity_exceeded(change_request, domain, scheduled_apply_at):
        fail("ERR_CHANGE_CALENDAR_CAPACITY",
             "At most two structural changes may be scheduled within a rolling "
             "thirty-day span.")

    change_request["status"] = "SCHEDULED"
    change_request["scheduled_apply_at"] = scheduled_apply_at
    change_request["freeze_window_start"] = start
    change_request["freeze_window_end"] = end
    db.bump(change_request)

    _notify(change_request, domain)

    services.recompute_domain(domain)
    db.touch_domain(domain)
    return response.entity(change_request)


@bp.post("/mdm/change-requests/<change_request_id>/apply")
@endpoint("GovernanceAdmin")
def apply_change_request(change_request_id):
    change_request = db.resolve(db.store.change_requests, change_request_id,
                                "ERR_CHANGE_REQUEST_NOT_FOUND")
    domain = db.store.domains[change_request["domain_id"]]

    if change_request["status"] != "SCHEDULED":
        fail("ERR_CHANGE_REQUEST_NOT_SCHEDULED", "The change request is not SCHEDULED.")

    if domain["governance_posture"] == "FROZEN":
        fail("ERR_DOMAIN_POSTURE_BLOCKED",
             "A FROZEN domain blocks the application of a change request.")

    if db.now() < change_request["scheduled_apply_at"]:
        fail("ERR_APPLY_WINDOW_NOT_REACHED",
             "The logical clock has not yet reached scheduled_apply_at.")

    for subscription in db.store.consumer_subscriptions.values():
        if (subscription["pending_change_request_id"] == change_request["id"]
                and subscription["criticality"] == "TIER1"
                and subscription["acknowledged_at"] is None):
            fail("ERR_TIER1_ACK_MISSING",
                 "Every notified TIER1 consumer must acknowledge before the change "
                 "is applied.")

    # --- hop 1 -------------------------------------------------------------
    change_request["status"] = "APPLIED"
    change_request["applied_at"] = db.now()
    change_request["freeze_window_start"] = None
    change_request["freeze_window_end"] = None
    db.bump(change_request)

    domain["reference_data_revision"] += 1
    revision = domain["reference_data_revision"]
    if change_request["change_type"] == "CLASSIFICATION_UPLIFT":
        level = change_request["proposed_values"]["target_classification_level"]
        domain["classification_level"] = level
        domain["sensitive_handling_required"] = level in services.SENSITIVE_LEVELS

    # --- hop 2 -------------------------------------------------------------
    classification_rank = services.rank(domain["classification_level"])
    for subscription in db.subscriptions_of(domain["id"]):
        if subscription["status"] != "ACTIVE":
            continue
        if services.rank(subscription["clearance_level"]) >= classification_rank:
            continue
        subscription["status"] = "SUSPENDED"
        subscription["suspended_reason"] = "CLEARANCE_BELOW_CLASSIFICATION"
        subscription["pending_change_request_id"] = None
        subscription["notified_at"] = None
        subscription["acknowledged_at"] = None
        db.bump(subscription)

    # --- hop 3 -------------------------------------------------------------
    for other in db.change_requests_of(domain["id"]):
        if other["id"] == change_request["id"]:
            continue
        if other["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
            continue
        services.assess_impact(other, domain)
        db.bump(other)

    # --- lineage staling and notification release --------------------------
    for subscription in db.subscriptions_of(domain["id"]):
        mutated = False
        if (subscription["lineage_status"] == "DOCUMENTED"
                and subscription["lineage_revision"] is not None
                and subscription["lineage_revision"] < revision):
            subscription["lineage_status"] = "STALE"
            mutated = True
        if (subscription["status"] == "ACTIVE"
                and subscription["pending_change_request_id"] == change_request["id"]):
            subscription["pending_change_request_id"] = None
            subscription["notified_at"] = None
            subscription["acknowledged_at"] = None
            mutated = True
        if mutated:
            db.bump(subscription)

    services.recompute_domain(domain)
    db.touch_domain(domain)
    return response.entity(change_request)


@bp.post("/mdm/change-requests/<change_request_id>/withdraw")
@endpoint("DataSteward", "DataOwner")
def withdraw_change_request(change_request_id):
    change_request = db.resolve(db.store.change_requests, change_request_id,
                                "ERR_CHANGE_REQUEST_NOT_FOUND")
    body = v.body()
    withdraw_reason = v.req_str(body, "withdraw_reason", 1)

    domain = db.store.domains[change_request["domain_id"]]
    entitle(domain)

    previous = change_request["status"]
    if previous not in NON_TERMINAL:
        fail("ERR_INVALID_STATE_TRANSITION",
             "A terminal change request can no longer be withdrawn.")

    is_requester = change_request["requester_steward_id"] == g.user_id
    if previous == "DRAFT":
        if not is_requester:
            identity_mismatch("Only the originating steward may withdraw a DRAFT "
                              "request.")
    elif not (is_requester or is_owner_of(domain)):
        identity_mismatch("Only the originating steward or a data owner of the domain "
                          "may withdraw this request.")

    change_request["status"] = "WITHDRAWN"
    change_request["withdraw_reason"] = withdraw_reason
    change_request["freeze_window_start"] = None
    change_request["freeze_window_end"] = None
    db.bump(change_request)

    services.clear_notifications(change_request)

    if previous == "SCHEDULED":
        services.recompute_domain(domain)
        db.touch_domain(domain)
    return response.entity(change_request)
