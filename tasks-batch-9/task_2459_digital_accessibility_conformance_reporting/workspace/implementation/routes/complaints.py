"""Complaint intake, routing, accommodation and closure (PRD 3.11)."""
from flask import Blueprint

from calc import remediation_risk_score
from db import clock_date, db, new_row, now_iso, sort_key, touch
from derive import recompute_product, refresh_complaint_counters
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from response import list_response, obj_response
from serialize import complaint_out
from validate import (
    CLOSURE_OUTCOMES,
    COMPLAINT_CHANNELS,
    COMPLAINT_ROUTES,
    COMPLAINT_STATES,
    DISABILITY_CATEGORIES,
    body,
    fk_component,
    fk_criterion,
    fk_issue,
    fk_product,
    pagination,
    paginate,
    path_complaint,
    q_enum,
    q_str,
    v_date,
    v_enum,
    v_str,
)

bp = Blueprint("complaints", __name__)

REMEDIATION_OUTCOMES = ("REMEDIATION_SCHEDULED", "NOT_A_DEFECT")
ACCOMMODATION_OUTCOMES = ("ACCOMMODATION_PROVIDED", "ACCOMMODATION_DENIED")


@bp.post("/complaints")
@endpoint(["CustomerLiaison"])
def create_complaint():
    data = body()
    product = fk_product(data.get("product_id"))          # step 5
    component = None
    criterion = None
    if data.get("component_id") is not None:
        component = fk_component(data.get("component_id"))
    if data.get("criterion_id") is not None:
        criterion = fk_criterion(data.get("criterion_id"))

    v_str(data, "product_id", required=True, min_len=1)
    channel = v_enum(data, "channel", COMPLAINT_CHANNELS, required=True)
    description = v_str(data, "description", required=True, min_len=10, max_len=2000)
    category = v_enum(data, "disability_category", DISABILITY_CATEGORIES, required=True)

    # step 33: cross-aggregate consistency, component before criterion
    if component is not None and component["product_id"] != product["id"]:
        raise ApiError("ERR_CROSS_PRODUCT_REFERENCE",
                       "Component %s does not belong to product %s"
                       % (component["id"], product["id"]))
    if criterion is not None and criterion["standard_id"] != product["standard_id"]:
        raise ApiError("ERR_CRITERION_STANDARD_MISMATCH",
                       "Criterion %s does not belong to standard %s"
                       % (criterion["id"], product["standard_id"]))

    row = new_row({
        "product_id": product["id"],
        "component_id": component["id"] if component else None,
        "criterion_id": criterion["id"] if criterion else None,
        "channel": channel,
        "description": description,
        "disability_category": category,
        "state": "NEW",
        "route": None,
        "requested_accommodation": None,
        "needed_by_date": None,
        "linked_issue_id": None,
        "_triaged_at": None,
        "accommodation_fulfilled_at": None,
        "closure_outcome": None,
        "closed_at": None,
    })
    db.complaints[row["id"]] = row
    return obj_response(complaint_out(row), 201)


@bp.get("/complaints/<complaint_id>")
@endpoint(ALL_ROLES)
def get_complaint(complaint_id):
    return obj_response(complaint_out(path_complaint(complaint_id)))


@bp.get("/complaints")
@endpoint(ALL_ROLES)
def list_complaints():
    product_id = q_str("product_id")
    component_id = q_str("component_id")
    criterion_id = q_str("criterion_id")
    linked_issue_id = q_str("linked_issue_id")
    state = q_enum("state", COMPLAINT_STATES)
    route = q_enum("route", COMPLAINT_ROUTES)
    limit, offset = pagination()
    rows = list(db.complaints.values())
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if component_id is not None:
        rows = [r for r in rows if r["component_id"] == component_id]
    if criterion_id is not None:
        rows = [r for r in rows if r["criterion_id"] == criterion_id]
    if linked_issue_id is not None:
        rows = [r for r in rows if r["linked_issue_id"] == linked_issue_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    if route is not None:
        rows = [r for r in rows if r["route"] == route]
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return list_response([complaint_out(r) for r in page], limit, offset, total)


@bp.post("/complaints/<complaint_id>/triage")
@endpoint(["AccessibilityLead"])
def triage_complaint(complaint_id):
    complaint = path_complaint(complaint_id)
    data = body()
    route = v_enum(data, "route", COMPLAINT_ROUTES, required=True)
    accommodation = None
    needed_raw = None
    needed_date = None
    if route == "ACCOMMODATION":
        accommodation = v_str(data, "requested_accommodation", required=True,
                              min_len=10, max_len=1000)
        needed_raw, needed_date = v_date(data, "needed_by_date", required=True)
    else:
        if data.get("requested_accommodation") is not None:
            accommodation = v_str(data, "requested_accommodation",
                                  min_len=10, max_len=1000)
        if data.get("needed_by_date") is not None:
            needed_raw, needed_date = v_date(data, "needed_by_date")

    # step 13: from-state
    if complaint["state"] != "NEW":
        raise ApiError("ERR_COMPLAINT_NOT_NEW",
                       "Complaint %s is %s" % (complaint["id"], complaint["state"]))

    # step 27: the accommodation date must not be in the past
    if route == "ACCOMMODATION" and needed_date < clock_date():
        raise ApiError("ERR_ACCOMMODATION_DATE_IN_PAST",
                       "needed_by_date %s is in the past" % needed_raw)

    complaint["state"] = "TRIAGED"
    complaint["route"] = route
    if route == "ACCOMMODATION":
        complaint["requested_accommodation"] = accommodation
        complaint["needed_by_date"] = needed_raw
    complaint["_triaged_at"] = now_iso()
    touch(complaint)
    return obj_response(complaint_out(complaint))


@bp.post("/complaints/<complaint_id>/link-issue")
@endpoint(["AccessibilityLead"])
def link_issue(complaint_id):
    complaint = path_complaint(complaint_id)
    data = body()
    issue = fk_issue(data.get("known_issue_id"))           # step 5
    v_str(data, "known_issue_id", required=True, min_len=1)

    # step 13: from-state
    if complaint["state"] != "TRIAGED":
        raise ApiError("ERR_COMPLAINT_NOT_TRIAGED",
                       "Complaint %s is %s" % (complaint["id"], complaint["state"]))
    # step 31: route match
    if complaint["route"] != "REMEDIATION":
        raise ApiError("ERR_COMPLAINT_ROUTE_MISMATCH",
                       "Complaint %s is routed %s" % (complaint["id"],
                                                      complaint["route"]))
    # step 33: the issue must belong to the complaint's product
    if issue["product_id"] != complaint["product_id"]:
        raise ApiError("ERR_CROSS_PRODUCT_REFERENCE",
                       "Known issue %s does not belong to product %s"
                       % (issue["id"], complaint["product_id"]))

    complaint["state"] = "LINKED"
    complaint["linked_issue_id"] = issue["id"]
    touch(complaint)

    issue["linked_complaint_count"] += 1
    issue["risk_score"] = remediation_risk_score(issue, issue["risk_variant"])
    touch(issue)

    product = db.products[complaint["product_id"]]
    recompute_product(product)
    return obj_response(complaint_out(complaint))


@bp.post("/complaints/<complaint_id>/fulfill-accommodation")
@endpoint(["CustomerLiaison"])
def fulfill_accommodation(complaint_id):
    complaint = path_complaint(complaint_id)
    body()

    # step 13: from-state
    if complaint["state"] != "TRIAGED":
        raise ApiError("ERR_COMPLAINT_NOT_TRIAGED",
                       "Complaint %s is %s" % (complaint["id"], complaint["state"]))
    # step 31: route match
    if complaint["route"] != "ACCOMMODATION":
        raise ApiError("ERR_COMPLAINT_ROUTE_MISMATCH",
                       "Complaint %s is routed %s" % (complaint["id"],
                                                      complaint["route"]))

    complaint["state"] = "ACCOMMODATED"
    complaint["accommodation_fulfilled_at"] = now_iso()
    touch(complaint)

    product = db.products[complaint["product_id"]]
    refresh_complaint_counters(product)
    return obj_response(complaint_out(complaint))


@bp.post("/complaints/<complaint_id>/close")
@endpoint(["AccessibilityLead"])
def close_complaint(complaint_id):
    complaint = path_complaint(complaint_id)
    data = body()
    outcome = v_enum(data, "closure_outcome", CLOSURE_OUTCOMES, required=True)

    # step 13: from-state
    if complaint["state"] not in ("LINKED", "ACCOMMODATED"):
        raise ApiError("ERR_COMPLAINT_NOT_CLOSABLE",
                       "Complaint %s is %s" % (complaint["id"], complaint["state"]))

    # step 31: the outcome must match the branch
    if complaint["state"] == "LINKED":
        allowed = REMEDIATION_OUTCOMES
    else:
        allowed = ACCOMMODATION_OUTCOMES
    if outcome not in allowed:
        raise ApiError("ERR_COMPLAINT_ROUTE_MISMATCH",
                       "Closure outcome %s is not valid for a %s complaint"
                       % (outcome, complaint["state"]))

    # step 32: the linked issue must have come to rest
    if complaint["state"] == "LINKED":
        issue = db.issues.get(complaint["linked_issue_id"])
        if issue is None or issue["state"] not in ("RESOLVED", "DEFERRED"):
            raise ApiError("ERR_LINKED_ISSUE_UNRESOLVED",
                           "Known issue %s has not come to rest"
                           % complaint["linked_issue_id"])

    complaint["state"] = "CLOSED"
    complaint["closure_outcome"] = outcome
    complaint["closed_at"] = now_iso()
    touch(complaint)
    return obj_response(complaint_out(complaint))
