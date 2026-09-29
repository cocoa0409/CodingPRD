"""Replacement orders and compliance progress reports."""

from datetime import timedelta

from flask import Blueprint, g

import logic
import lookup
from core import (
    body_json, by_created_at, db, endpoint, fail, field, filter_arg, new_row,
    paginate, parse_date, parse_datetime, read_pagination, respond_list,
    respond_object, touch, validate_body,
)

bp = Blueprint("orders", __name__)

OUTCOMES = ("GRANTED", "DENIED", "NO_RESPONSE")
CONSENT_BARRIERS = ("COST", "REFUSED", "NO_CONTACT", "ACCESS_DENIED")
SIDES = ("UTILITY", "CUSTOMER")
CANCELLABLE = ("DRAFT", "SCOPED", "FUNDED", "SCHEDULED")

ORDER_READ_ROLES = ["ProgramAdministrator", "InventoryAnalyst", "ComplianceOfficer",
                    "CustomerRepresentative", "ReplacementContractor"]
REPORT_ROLES = ["ProgramAdministrator", "InventoryAnalyst", "ComplianceOfficer"]


def _system_of_order(order):
    line = db.service_lines.get(order["service_line_id"])
    if line is None:
        return None, None
    return line, db.water_systems.get(line["water_system_id"])


# ------------------------------------------------------------ ReplacementOrder
@bp.post("/lsl/replacement-orders")
@endpoint(["ProgramAdministrator"])
def open_order():
    data = validate_body(body_json(), [
        field("service_line_id", "string", required=True),
        field("estimated_cost_cents", "integer", required=True, min=1),
        field("excavation_start_date", "date", required=True),
        field("excavation_end_date", "date", required=True),
        field("street_project_id", "string", default=None),
    ])
    if parse_date(data["excavation_end_date"]) < parse_date(data["excavation_start_date"]):
        fail("ERR_INVALID_DATE_RANGE",
             "excavation_end_date must be on or after excavation_start_date.")

    line = lookup.service_line(data["service_line_id"])
    if data["street_project_id"] is not None:
        lookup.street_project(data["street_project_id"])
    ws = db.water_systems.get(line["water_system_id"])

    if line["replacement_state"] not in ("ELIGIBLE", "REPLACED_PARTIAL"):
        fail("ERR_LINE_NOT_ELIGIBLE",
             "A replacement order requires the line to be ELIGIBLE or "
             "REPLACED_PARTIAL, not %s." % line["replacement_state"])
    if ws is not None and logic.program_posture(ws) == "FROZEN":
        fail("ERR_PROGRAM_POSTURE_FROZEN",
             "The program posture is FROZEN; no replacement order may be opened.")
    if ws is None or ws["inventory_status"] not in ("PUBLISHED", "AMENDMENT_PENDING"):
        fail("ERR_INVENTORY_NOT_PUBLISHED",
             "Replacement may not precede inventory publication.")

    order = new_row()
    order.update({
        "service_line_id": line["id"],
        "street_project_id": data["street_project_id"],
        "estimated_cost_cents": data["estimated_cost_cents"],
        "excavation_start_date": data["excavation_start_date"],
        "excavation_end_date": data["excavation_end_date"],
        "fulfillment_state": "DRAFT",
        "consent_state": "NOT_REQUESTED",
        "scope": None,
        "consent_barrier_reason": None,
        "funding_allocations": [],
        "funding_mode_applied": None,
        "flushing_duration_minutes": None,
        "replaced_sides": [],
        "completed_at": None,
        "_completed_at": None,
        "cancellation_reason": None,
    })
    db.orders[order["id"]] = order

    line["replacement_state"] = "IN_PROGRAM"
    line["consent_barrier_flag"] = logic.compute_consent_barrier(line)
    logic.recompute_priority(line)
    touch(line)

    return respond_object(logic.serialize_order(order), 201)


@bp.get("/lsl/replacement-orders")
@endpoint(ORDER_READ_ROLES)
def list_orders():
    limit, offset = read_pagination()
    rows = by_created_at(list(db.orders.values()))
    for name in ("service_line_id", "street_project_id", "fulfillment_state",
                 "consent_state", "scope"):
        value = filter_arg(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    page, total = paginate(rows, limit, offset)
    return respond_list([logic.serialize_order(r) for r in page],
                        limit, offset, total)


@bp.get("/lsl/replacement-orders/<order_id>")
@endpoint(ORDER_READ_ROLES)
def read_order(order_id):
    order = lookup.order(order_id)
    return respond_object(logic.serialize_order(order))


@bp.post("/lsl/replacement-orders/<order_id>/consent-request")
@endpoint(["CustomerRepresentative"])
def consent_request(order_id):
    order = lookup.order(order_id)
    first_pass = (order["consent_state"] == "NOT_REQUESTED"
                  and order["fulfillment_state"] == "DRAFT")
    recanvass = (order["consent_state"] == "NO_RESPONSE"
                 and order["fulfillment_state"] == "SCOPED")
    if not first_pass and not recanvass:
        fail("ERR_ORDER_STATE_INVALID",
             "Consent may be requested from (DRAFT, NOT_REQUESTED) or re-canvassed "
             "from (SCOPED, NO_RESPONSE); this order is (%s, %s)."
             % (order["fulfillment_state"], order["consent_state"]))

    order["consent_state"] = "REQUESTED"
    if recanvass:
        order["fulfillment_state"] = "DRAFT"
        order["scope"] = None
        order["consent_barrier_reason"] = None
    touch(order)

    line = db.service_lines.get(order["service_line_id"])
    if recanvass and line is not None:
        line["consent_barrier_flag"] = logic.compute_consent_barrier(line)
        logic.recompute_priority(line)
        touch(line)
    return respond_object(logic.serialize_order(order))


@bp.post("/lsl/replacement-orders/<order_id>/consent-response")
@endpoint(["CustomerRepresentative"])
def consent_response(order_id):
    data = validate_body(body_json(), [
        field("outcome", "string", required=True, enum=OUTCOMES),
        field("barrier_reason", "string", default=None, enum=CONSENT_BARRIERS),
    ])
    outcome = data["outcome"]
    if outcome in ("DENIED", "NO_RESPONSE") and data["barrier_reason"] is None:
        fail("ERR_INVALID_REQUEST",
             "barrier_reason is required when the consent outcome is %s." % outcome)

    order = lookup.order(order_id)
    if order["fulfillment_state"] != "DRAFT" or order["consent_state"] != "REQUESTED":
        fail("ERR_ORDER_STATE_INVALID",
             "A consent response requires (DRAFT, REQUESTED); this order is (%s, %s)."
             % (order["fulfillment_state"], order["consent_state"]))

    order["fulfillment_state"] = "SCOPED"
    order["consent_state"] = outcome
    if outcome == "GRANTED":
        order["scope"] = "FULL"
    else:
        order["scope"] = "PARTIAL"
        order["consent_barrier_reason"] = data["barrier_reason"]
    touch(order)

    line = db.service_lines.get(order["service_line_id"])
    if line is not None:
        if outcome == "GRANTED":
            # The granting branch touches no other service-line field.
            logic.recompute_priority(line)
        else:
            line["consent_barrier_flag"] = True
            logic.recompute_priority(line)
            touch(line)
    return respond_object(logic.serialize_order(order))


@bp.post("/lsl/replacement-orders/<order_id>/funding-plan")
@endpoint(["ProgramAdministrator"])
def funding_plan(order_id):
    order = lookup.order(order_id)
    if order["consent_state"] not in ("GRANTED", "DENIED", "NO_RESPONSE") \
            or order["scope"] is None:
        fail("ERR_CONSENT_NOT_RESOLVED",
             "The consent canvass must be settled before funding is assembled.")
    if order["fulfillment_state"] != "SCOPED":
        fail("ERR_ORDER_STATE_INVALID",
             "A funding plan requires fulfillment_state SCOPED, not %s."
             % order["fulfillment_state"])

    line, ws = _system_of_order(order)
    if ws is None:
        fail("ERR_WATER_SYSTEM_NOT_FOUND", "The order's water system is missing.")
    if logic.program_posture(ws) == "FROZEN":
        fail("ERR_PROGRAM_POSTURE_FROZEN",
             "The program posture is FROZEN; funding may not be committed.")

    mode = ws["funding_mode"]
    candidates = logic.funding_candidates(ws["id"])
    rows, uncovered = logic.plan_allocations(order, mode, candidates)

    tentative = [(row, order) for row in rows]
    for source in logic.funding_sources_of_system(ws["id"]):
        if source["status"] != "ACTIVE":
            continue
        if logic.source_ledger(source, tentative)["equity_shortfall_cents"] > 0:
            fail("ERR_EQUITY_REQUIREMENT_BREACH",
                 "Funding source %s would end this commit short of its equity "
                 "requirement." % source["id"])
    if uncovered > 0 or not rows:
        fail("ERR_FUNDING_INSUFFICIENT",
             "The active candidate pool cannot cover the order's estimated cost.")

    order["funding_allocations"] = rows
    order["funding_mode_applied"] = mode
    order["fulfillment_state"] = "FUNDED"
    touch(order)
    return respond_object(logic.serialize_order(order))


@bp.post("/lsl/replacement-orders/<order_id>/schedule")
@endpoint(["ReplacementContractor"])
def schedule_order(order_id):
    data = validate_body(body_json(), [
        field("excavation_start_date", "date", required=True),
        field("excavation_end_date", "date", required=True),
    ])
    start = parse_date(data["excavation_start_date"])
    end = parse_date(data["excavation_end_date"])
    if end < start:
        fail("ERR_INVALID_DATE_RANGE",
             "excavation_end_date must be on or after excavation_start_date.")

    order = lookup.order(order_id)
    if order["fulfillment_state"] != "FUNDED":
        fail("ERR_ORDER_STATE_INVALID",
             "Scheduling requires fulfillment_state FUNDED, not %s."
             % order["fulfillment_state"])

    line, ws = _system_of_order(order)
    if ws is not None and logic.program_posture(ws) != "OPEN":
        fail("ERR_PROGRAM_POSTURE_RESTRICTED",
             "Scheduling an excavation window requires the program posture to be "
             "exactly OPEN.")
    if ws is not None and ws["cct_optimization_status"] == "PENDING_REOPTIMIZATION":
        fail("ERR_CCT_NOT_OPTIMIZED",
             "Excavation may not proceed while corrosion control is being "
             "re-optimized.")

    project = db.street_projects.get(order["street_project_id"]) \
        if order["street_project_id"] else None
    if project is not None:
        m_start = parse_date(project["moratorium_start_date"])
        m_end = parse_date(project["moratorium_end_date"])
        if start <= m_end and end >= m_start:
            fail("ERR_MORATORIUM_CONFLICT",
                 "The excavation window intersects the street project's cut "
                 "moratorium.")
        cap = project["max_concurrent_excavations"]
        day = start
        while day <= end:
            busy = 0
            for other in db.orders.values():
                if other["id"] == order["id"]:
                    continue
                if other["street_project_id"] != project["id"]:
                    continue
                if other["fulfillment_state"] not in ("SCHEDULED", "IN_PROGRESS"):
                    continue
                o_start = parse_date(other["excavation_start_date"])
                o_end = parse_date(other["excavation_end_date"])
                if o_start is not None and o_end is not None \
                        and o_start <= day <= o_end:
                    busy += 1
            if busy >= cap:
                fail("ERR_EXCAVATION_CAPACITY_EXCEEDED",
                     "Street project capacity of %d concurrent excavations is "
                     "already taken on %s." % (cap, day.isoformat()))
            day = day + timedelta(days=1)

    order["excavation_start_date"] = data["excavation_start_date"]
    order["excavation_end_date"] = data["excavation_end_date"]
    order["fulfillment_state"] = "SCHEDULED"
    touch(order)
    return respond_object(logic.serialize_order(order))


@bp.post("/lsl/replacement-orders/<order_id>/start")
@endpoint(["ReplacementContractor"])
def start_order(order_id):
    order = lookup.order(order_id)
    if order["fulfillment_state"] != "SCHEDULED":
        fail("ERR_ORDER_STATE_INVALID",
             "Breaking ground requires fulfillment_state SCHEDULED, not %s."
             % order["fulfillment_state"])
    order["fulfillment_state"] = "IN_PROGRESS"
    touch(order)
    return respond_object(logic.serialize_order(order))


@bp.post("/lsl/replacement-orders/<order_id>/complete")
@endpoint(["ReplacementContractor"])
def complete_order(order_id):
    data = validate_body(body_json(), [
        field("completed_at", "datetime", required=True),
        field("replaced_sides", "array", required=True, nonempty=True,
              item_type="string", item_enum=SIDES),
    ])
    order = lookup.order(order_id)
    if order["fulfillment_state"] != "IN_PROGRESS":
        fail("ERR_ORDER_STATE_INVALID",
             "Completion requires fulfillment_state IN_PROGRESS, not %s."
             % order["fulfillment_state"])

    expected = {"UTILITY", "CUSTOMER"} if order["scope"] == "FULL" else {"UTILITY"}
    if set(data["replaced_sides"]) != expected or \
            len(data["replaced_sides"]) != len(expected):
        fail("ERR_REPLACED_SIDES_MISMATCH",
             "replaced_sides must be %s for a %s order."
             % (sorted(expected), order["scope"]))

    line, ws = _system_of_order(order)
    order["completed_at"] = data["completed_at"]
    order["_completed_at"] = parse_datetime(data["completed_at"])
    order["replaced_sides"] = list(data["replaced_sides"])
    order["fulfillment_state"] = "COMPLETED"
    if line is not None and ws is not None:
        order["flushing_duration_minutes"] = logic.flushing_duration_minutes(
            line, order, ws)

    # LINK 1 -- every committed allocation is drawn.
    for row in order["funding_allocations"]:
        if row["state"] == "COMMITTED":
            row["state"] = "DRAWN"
    touch(order)

    # The line settles first: REPLACED_* is sticky, so the NON_LEAD recompute the
    # cascaded evidence triggers cannot drag it back to NOT_REQUIRED.
    if line is not None:
        line["replacement_state"] = "REPLACED_FULL" if order["scope"] == "FULL" \
            else "REPLACED_PARTIAL"
        touch(line)
        for side in order["replaced_sides"]:
            logic.create_evidence_item(
                line["id"], "POTHOLE", side, "COPPER", order["completed_at"],
                notes=None, origin="REPLACEMENT_CASCADE",
            )
            logic.classification_recompute(line)

    return respond_object(logic.serialize_order(order))


@bp.post("/lsl/replacement-orders/<order_id>/cancel")
@endpoint(["ProgramAdministrator"])
def cancel_order(order_id):
    data = validate_body(body_json(), [
        field("reason", "string", required=True, nonempty=True),
    ])
    order = lookup.order(order_id)
    previous = order["fulfillment_state"]
    if previous not in CANCELLABLE:
        fail("ERR_ORDER_STATE_INVALID",
             "An order in %s may not be cancelled." % previous)

    order["fulfillment_state"] = "CANCELLED"
    order["cancellation_reason"] = data["reason"]
    if previous in ("FUNDED", "SCHEDULED"):
        for row in order["funding_allocations"]:
            if row["state"] == "COMMITTED":
                row["state"] = "RELEASED"
    touch(order)

    line = db.service_lines.get(order["service_line_id"])
    if line is not None:
        if line["replacement_state"] == "IN_PROGRAM":
            line["replacement_state"] = "ELIGIBLE"
        line["consent_barrier_flag"] = logic.compute_consent_barrier(line)
        logic.recompute_priority(line)
        touch(line)
    return respond_object(logic.serialize_order(order))


# --------------------------------------------------------------- ProgressReport
@bp.post("/lsl/progress-reports")
@endpoint(["ComplianceOfficer"])
def file_progress_report():
    data = validate_body(body_json(), [
        field("water_system_id", "string", required=True),
        field("period_start_date", "date", required=True),
        field("period_end_date", "date", required=True),
    ])
    start = parse_date(data["period_start_date"])
    end = parse_date(data["period_end_date"])
    if end < start:
        fail("ERR_INVALID_DATE_RANGE",
             "period_end_date must be on or after period_start_date.")
    ws = lookup.water_system(data["water_system_id"])

    for other in logic.reports_of_system(ws["id"]):
        o_start = parse_date(other["period_start_date"])
        o_end = parse_date(other["period_end_date"])
        if start <= o_end and end >= o_start:
            fail("ERR_PERIOD_OVERLAP",
                 "This reporting period overlaps an already-filed report.")

    # A progress report is append-only: id and created_at only, no version.
    stamped = new_row()
    report = {
        "id": stamped["id"],
        "created_at": stamped["created_at"],
        "_seq": stamped["_seq"],
        "water_system_id": ws["id"],
        "period_start_date": data["period_start_date"],
        "period_end_date": data["period_end_date"],
    }
    report.update(logic.build_progress_report(ws, start, end))
    db.progress_reports[report["id"]] = report
    return respond_object(logic.serialize_progress_report(report), 201)


@bp.get("/lsl/progress-reports")
@endpoint(REPORT_ROLES)
def list_progress_reports():
    limit, offset = read_pagination()
    rows = by_created_at(list(db.progress_reports.values()))
    for name in ("water_system_id", "compliance_status"):
        value = filter_arg(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    page, total = paginate(rows, limit, offset)
    return respond_list([logic.serialize_progress_report(r) for r in page],
                        limit, offset, total)


@bp.get("/lsl/progress-reports/<report_id>")
@endpoint(REPORT_ROLES)
def read_progress_report(report_id):
    report = lookup.progress_report(report_id)
    return respond_object(logic.serialize_progress_report(report))
