"""WorkOrder endpoints: create, get, list, ready, assign, arrive, start,
complete, verify, cancel. Carries the parallel execution x verification
dimensions and all cross-entity cascades (crew release, labor posting,
VERIFY_FAILED reopen + system ETR revision, requisition cancellation)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import db, parse_iso, iso_ms
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_ASSIGNEE_AMBIGUOUS, ERR_CREW_NOT_AVAILABLE, ERR_CREW_TYPE_MISMATCH,
    ERR_FATIGUE_LIMIT_EXCEEDED, ERR_OUTSIDE_ENGAGEMENT_WINDOW,
    ERR_CREW_NOT_ON_SITE, ERR_SWITCHING_NOT_EXECUTED, ERR_OWNERSHIP_MISMATCH,
    ERR_ASSESSMENT_REQUIRED,
)
from services.core import (
    get_body, req_string, req_enum, req_bool, paginate, new_common, bump,
    get_outage, get_work_order, get_crew, get_ma_crew, get_event,
    serialize_work_order, sort_created_asc, post_ledger_entry,
    create_etr_revision, check_event_not_closed, fatigue_projection,
    WORK_TYPES, CREW_TYPES, VERIFY_OUTCOMES, CAPITAL_WORK_TYPES,
    MAX_CONTINUOUS_WORK_MINUTES, REWORK_EXTENSION_MINUTES,
)
from routes.outages import _cancel_work_order_cascade

bp = Blueprint("work_orders", __name__)


def _check_field_crew_ownership(user_id, role, wo):
    """FieldCrewLead may act only on their own crew's work orders."""
    if role == "FieldCrewLead":
        if wo.get("assigned_crew_id") is None or wo["assigned_crew_id"] != user_id:
            raise_err(ERR_OWNERSHIP_MISMATCH,
                      "FieldCrewLead may only act on their own crew's work orders")


@bp.route("/om/work-orders", methods=["POST"])
def create_work_order():
    require_roles(["Dispatcher"])
    body = get_body()
    outage_id = req_string(body, "outage_id")
    wtype = req_enum(body, "work_type", WORK_TYPES)
    required = req_enum(body, "required_crew_type", CREW_TYPES)
    req_switching = req_bool(body, "requires_switching_order")
    outage = get_outage(outage_id)
    event = get_event(outage["storm_event_id"])
    check_event_not_closed(event)

    w = new_common()
    w.update({
        "outage_id": outage_id,
        "work_type": wtype,
        "required_crew_type": required,
        "requires_switching_order": req_switching,
        "execution_status": "CREATED",
        "verification_status": "PENDING_VERIFY",
        "assigned_crew_id": None,
        "assigned_mutual_aid_crew_id": None,
        "switching_order_id": None,
        "arrived_at": None,
        "completed_at": None,
    })
    db.work_orders[w["id"]] = w
    return success_object(serialize_work_order(w), status=201)


@bp.route("/om/work-orders/<wid>", methods=["GET"])
def get_one(wid):
    require_roles(ALL_ROLES)
    w = get_work_order(wid)
    return success_object(serialize_work_order(w))


@bp.route("/om/work-orders", methods=["GET"])
def list_work_orders():
    require_roles(ALL_ROLES)
    items = list(db.work_orders.values())
    for param in ("outage_id", "assigned_crew_id", "assigned_mutual_aid_crew_id",
                  "switching_order_id", "execution_status"):
        v = request.args.get(param)
        if v is not None:
            items = [w for w in items if w.get(param) == v]
    items = sort_created_asc(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_work_order(w) for w in page], limit, offset, total)


@bp.route("/om/work-orders/<wid>/ready", methods=["POST"])
def ready(wid):
    require_roles(["Dispatcher"])
    w = get_work_order(wid)
    if w["execution_status"] != "CREATED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"WorkOrder in {w['execution_status']} cannot be readied")
    outage = get_outage(w["outage_id"])
    event = get_event(outage["storm_event_id"])
    check_event_not_closed(event)
    if outage["outage_status"] not in ("CONFIRMED", "ASSESSED", "WORKING"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Linked outage in {outage['outage_status']} cannot accept work")
    if w["work_type"] != "ASSESSMENT":
        accepted = any(
            a["outage_id"] == outage["id"] and a["assessment_status"] == "ACCEPTED"
            for a in db.damage_assessments.values()
        )
        if not accepted:
            raise_err(ERR_ASSESSMENT_REQUIRED,
                      "Non-ASSESSMENT work requires an ACCEPTED damage assessment")
    w["execution_status"] = "READY"
    bump(w)
    return success_object(serialize_work_order(w))


def _do_assign(w, crew_id, ma_crew_id):
    """Shared assignment logic for /assign and /dispatch_next. Preconditions are
    checked in validation-cascade order; the caller supplies exactly one id."""
    outage = get_outage(w["outage_id"])
    if crew_id is not None:
        crew = get_crew(crew_id)
        # Constraint checks: availability, type, fatigue.
        if crew["crew_status"] != "AVAILABLE":
            raise_err(ERR_CREW_NOT_AVAILABLE, "Internal crew is not AVAILABLE")
        if crew["crew_type"] != w["required_crew_type"]:
            raise_err(ERR_CREW_TYPE_MISMATCH,
                      "Crew type does not match required_crew_type")
        projected = fatigue_projection(crew, outage)
        if projected > MAX_CONTINUOUS_WORK_MINUTES:
            raise_err(ERR_FATIGUE_LIMIT_EXCEEDED,
                      f"Fatigue projection {projected} exceeds 960 minutes")
        w["assigned_crew_id"] = crew_id
        w["assigned_mutual_aid_crew_id"] = None
        crew["crew_status"] = "EN_ROUTE"
        bump(crew)
    else:
        mac = get_ma_crew(ma_crew_id)
        if mac["ma_status"] != "AVAILABLE":
            raise_err(ERR_CREW_NOT_AVAILABLE, "Mutual-aid crew is not AVAILABLE")
        if mac["crew_type"] != w["required_crew_type"]:
            raise_err(ERR_CREW_TYPE_MISMATCH,
                      "Crew type does not match required_crew_type")
        now = db.now()
        ws = parse_iso(mac["committed_window_start"])
        we = parse_iso(mac["committed_window_end"])
        if not (ws <= now < we):
            raise_err(ERR_OUTSIDE_ENGAGEMENT_WINDOW,
                      "Logical now is outside the crew's committed engagement window")
        w["assigned_crew_id"] = None
        w["assigned_mutual_aid_crew_id"] = ma_crew_id
        # Mutual-aid crews keep ma_status AVAILABLE while assigned.
    w["execution_status"] = "DISPATCHED"
    bump(w)


@bp.route("/om/work-orders/<wid>/assign", methods=["POST"])
def assign(wid):
    require_roles(["Dispatcher"])
    w = get_work_order(wid)
    body = get_body()
    crew_id = body.get("crew_id")
    ma_crew_id = body.get("mutual_aid_crew_id")
    if crew_id is not None and not isinstance(crew_id, str):
        raise_err(ERR_INVALID_REQUEST, "crew_id must be a string")
    if ma_crew_id is not None and not isinstance(ma_crew_id, str):
        raise_err(ERR_INVALID_REQUEST, "mutual_aid_crew_id must be a string")
    if crew_id is not None and ma_crew_id is not None:
        raise_err(ERR_ASSIGNEE_AMBIGUOUS,
                  "Supply exactly one of crew_id / mutual_aid_crew_id")
    if crew_id is None and ma_crew_id is None:
        raise_err(ERR_INVALID_REQUEST,
                  "Supply exactly one of crew_id / mutual_aid_crew_id")
    # Existence of body FK references precedes state checks.
    if crew_id is not None:
        get_crew(crew_id)
    if ma_crew_id is not None:
        get_ma_crew(ma_crew_id)
    if w["execution_status"] != "READY":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"WorkOrder in {w['execution_status']} cannot be assigned")
    outage = get_outage(w["outage_id"])
    event = get_event(outage["storm_event_id"])
    check_event_not_closed(event)
    _do_assign(w, crew_id, ma_crew_id)
    return success_object(serialize_work_order(w))


@bp.route("/om/work-orders/<wid>/arrive", methods=["POST"])
def arrive(wid):
    user_id, role = require_roles(["FieldCrewLead", "Dispatcher"])
    w = get_work_order(wid)
    if w["execution_status"] != "DISPATCHED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"WorkOrder in {w['execution_status']} cannot be arrived")
    _check_field_crew_ownership(user_id, role, w)
    if w.get("assigned_crew_id"):
        crew = db.crews.get(w["assigned_crew_id"])
        if crew is not None and crew["crew_status"] == "EN_ROUTE":
            crew["crew_status"] = "ON_SITE"
            bump(crew)
    w["arrived_at"] = iso_ms(db.now())
    bump(w)
    return success_object(serialize_work_order(w))


@bp.route("/om/work-orders/<wid>/start", methods=["POST"])
def start(wid):
    user_id, role = require_roles(["FieldCrewLead", "Dispatcher"])
    w = get_work_order(wid)
    if w["execution_status"] != "DISPATCHED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"WorkOrder in {w['execution_status']} cannot be started")
    outage = get_outage(w["outage_id"])
    event = get_event(outage["storm_event_id"])
    check_event_not_closed(event)
    _check_field_crew_ownership(user_id, role, w)
    # Safety gates: internal assignee must be ON_SITE; mutual-aid skips the check.
    if w.get("assigned_crew_id"):
        crew = db.crews.get(w["assigned_crew_id"])
        if crew is None or crew["crew_status"] != "ON_SITE":
            raise_err(ERR_CREW_NOT_ON_SITE,
                      "Assigned internal crew is not ON_SITE")
    if w["requires_switching_order"]:
        so = db.switching_orders.get(w.get("switching_order_id") or "")
        if so is None or so["so_status"] != "EXECUTED":
            raise_err(ERR_SWITCHING_NOT_EXECUTED,
                      "Switching order has not reached EXECUTED")
    w["execution_status"] = "IN_PROGRESS"
    bump(w)
    # Bubble: first non-cancelled WO entering IN_PROGRESS on a CONFIRMED/ASSESSED
    # outage moves it to WORKING (single version increment for the request).
    if outage["outage_status"] in ("CONFIRMED", "ASSESSED"):
        others_in_progress = any(
            other["outage_id"] == outage["id"] and other["id"] != w["id"]
            and other["execution_status"] == "IN_PROGRESS"
            for other in db.work_orders.values()
        )
        if not others_in_progress:
            outage["outage_status"] = "WORKING"
            bump(outage)
    return success_object(serialize_work_order(w))


@bp.route("/om/work-orders/<wid>/complete", methods=["POST"])
def complete(wid):
    user_id, role = require_roles(["FieldCrewLead", "Dispatcher"])
    w = get_work_order(wid)
    if w["execution_status"] != "IN_PROGRESS":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"WorkOrder in {w['execution_status']} cannot be completed")
    outage = get_outage(w["outage_id"])
    event = get_event(outage["storm_event_id"])
    check_event_not_closed(event)
    _check_field_crew_ownership(user_id, role, w)

    now = db.now()
    w["completed_at"] = iso_ms(now)
    w["execution_status"] = "COMPLETED"
    # Re-completion after a failed verification returns the verification
    # dimension to PENDING_VERIFY.
    if w["verification_status"] == "VERIFY_FAILED":
        w["verification_status"] = "PENDING_VERIFY"
    bump(w)

    # Internal crew: release ON_SITE -> AVAILABLE and post labor cost.
    if w.get("assigned_crew_id"):
        crew = db.crews.get(w["assigned_crew_id"])
        if crew is not None:
            if crew["crew_status"] == "ON_SITE":
                crew["crew_status"] = "AVAILABLE"
                bump(crew)
            arr = parse_iso(w["arrived_at"]) if w.get("arrived_at") else now
            worked_minutes = (now - arr).total_seconds() / 60.0
            amount = int(
                (Decimal(str(worked_minutes)) * Decimal(crew["hourly_rate_cents"])
                 / Decimal(60)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            feeder = db.feeders.get(outage["feeder_id"])
            county = feeder["county_code"] if feeder else ""
            cost_class = "CAPITAL" if w["work_type"] in CAPITAL_WORK_TYPES else "O_AND_M"
            post_ledger_entry(
                storm_event_id=outage["storm_event_id"], work_order_id=w["id"],
                entry_type="LABOR_INTERNAL", cost_class=cost_class,
                county_code=county, amount_cents=amount,
            )
    # Mutual-aid assignments post no labor entry here.
    return success_object(serialize_work_order(w))


@bp.route("/om/work-orders/<wid>/verify", methods=["POST"])
def verify(wid):
    require_roles(["Dispatcher"])
    w = get_work_order(wid)
    body = get_body()
    outcome = req_enum(body, "outcome", VERIFY_OUTCOMES)
    if w["execution_status"] != "COMPLETED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Verification requires execution_status COMPLETED")
    if w["verification_status"] != "PENDING_VERIFY":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Verification dimension in {w['verification_status']} cannot be verified")
    outage = get_outage(w["outage_id"])
    event = get_event(outage["storm_event_id"])
    check_event_not_closed(event)

    if outcome == "PASSED":
        w["verification_status"] = "VERIFY_PASSED"
        bump(w)
    else:
        # Cross-dimension cascade: reopen execution, clear completed_at.
        w["verification_status"] = "VERIFY_FAILED"
        w["execution_status"] = "IN_PROGRESS"
        w["completed_at"] = None
        bump(w)
        # System ETR revision: now + 180 minutes.
        etr = db.now() + timedelta(minutes=REWORK_EXTENSION_MINUTES)
        create_etr_revision(outage, "VERIFICATION_FAILED", etr, "system")
        bump(outage)
    return success_object(serialize_work_order(w))


@bp.route("/om/work-orders/<wid>/cancel", methods=["POST"])
def cancel(wid):
    require_roles(["Dispatcher"])
    w = get_work_order(wid)
    if w["execution_status"] not in ("CREATED", "READY", "DISPATCHED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"WorkOrder in {w['execution_status']} cannot be cancelled")
    outage = get_outage(w["outage_id"])
    event = get_event(outage["storm_event_id"])
    check_event_not_closed(event)
    _cancel_work_order_cascade(w)
    return success_object(serialize_work_order(w))
