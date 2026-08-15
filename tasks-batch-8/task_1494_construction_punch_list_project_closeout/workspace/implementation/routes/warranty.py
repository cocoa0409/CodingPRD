"""Warranty callbacks after closeout (PRD 3.7): closed-interval 365-day
window, severity-driven SLA with CALENDAR / BUSINESS day counting."""
from datetime import timedelta

from flask import Blueprint

from authz import GCPM, OWNER, ALL_ROLES, require_roles
from db import store
from errors import invalid_state, project_not_closed, warranty_expired
from respond import success
from serialize import ser_case
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate, query_filters,
    req_enum, req_str, sorted_by_creation, touch,
)
from timeutil import add_business_days

bp = Blueprint("warranty", __name__, url_prefix="/closeout")

SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
SLA_DAYS = {"CRITICAL": 1, "MAJOR": 7, "MINOR": 30}
WARRANTY_PERIOD_DAYS = 365


@bp.route("/warranty-cases", methods=["POST"])
def create_case():
    require_roles([OWNER])
    data = json_body()
    project_id = req_str(data, "project_id")
    title = req_str(data, "title")
    severity = req_enum(data, "severity", SEVERITIES)
    description = req_str(data, "description")
    p = get_or_404(store.projects, project_id)
    if p["status"] != "CLOSED":
        raise project_not_closed()
    # The window is closed at its end: reported_at exactly equal to
    # warranty_start_date + 365 days is accepted; one second later is not.
    warranty_end = p["warranty_start_date"] + timedelta(days=WARRANTY_PERIOD_DAYS)
    if store.clock > warranty_end:
        raise warranty_expired()
    c = {
        "id": new_id(),
        "_seq": next(store.seq),
        "project_id": project_id,
        "title": title,
        "severity": severity,
        "description": description,
        "reported_at": store.clock,
        "sla_due_at": None,
        "resolution_note": None,
        "denial_reason": None,
        "status": "REPORTED",
    }
    c.update(new_common_fields())
    store.warranty_cases[c["id"]] = c
    return success(ser_case(c), status=201)


@bp.route("/warranty-cases/<cid>", methods=["GET"])
def get_case(cid):
    require_roles(ALL_ROLES)
    return success(ser_case(get_or_404(store.warranty_cases, cid)))


@bp.route("/warranty-cases", methods=["GET"])
def list_cases():
    require_roles(ALL_ROLES)
    filters = query_filters("project_id", "status")
    items = [c for c in store.warranty_cases.values()
             if all(c[k] == v for k, v in filters.items())]
    page, pagination = paginate(sorted_by_creation(items))
    return success([ser_case(c) for c in page], response_type="array",
                   pagination=pagination)


@bp.route("/warranty-cases/<cid>/triage", methods=["POST"])
def triage_case(cid):
    require_roles([GCPM])
    data = json_body()
    severity = req_enum(data, "severity", SEVERITIES)
    c = get_or_404(store.warranty_cases, cid)
    if c["status"] != "REPORTED":
        raise invalid_state("Only a REPORTED case can be triaged")
    p = store.projects[c["project_id"]]
    days = SLA_DAYS[severity]
    if p["warranty_sla_mode"] == "BUSINESS":
        due = add_business_days(store.clock, days)
    else:
        due = store.clock + timedelta(days=days)
    c["severity"] = severity
    c["sla_due_at"] = due
    c["status"] = "TRIAGED"
    touch(c)
    return success(ser_case(c))


@bp.route("/warranty-cases/<cid>/resolve", methods=["POST"])
def resolve_case(cid):
    require_roles([GCPM])
    data = json_body()
    note = req_str(data, "resolution_note")
    c = get_or_404(store.warranty_cases, cid)
    if c["status"] != "TRIAGED":
        raise invalid_state("Only a TRIAGED case can be resolved")
    c["resolution_note"] = note
    c["status"] = "RESOLVED"
    touch(c)
    return success(ser_case(c))


@bp.route("/warranty-cases/<cid>/deny", methods=["POST"])
def deny_case(cid):
    require_roles([GCPM])
    data = json_body()
    reason = req_str(data, "denial_reason")
    c = get_or_404(store.warranty_cases, cid)
    if c["status"] not in ("REPORTED", "TRIAGED"):
        raise invalid_state("Only a REPORTED or TRIAGED case can be denied")
    c["denial_reason"] = reason
    c["status"] = "DENIED"
    touch(c)
    return success(ser_case(c))
