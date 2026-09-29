"""Service members, PCS orders and counseling sessions (PRD §3.1, §3.2)."""

from datetime import timedelta

from flask import Blueprint

from db import base_record, by_seq, clock, db, mark_fresh, touch
from errors import ApiError
from middleware import (
    ROLE_CLAIMS_EXAMINER,
    ROLE_MOVE_COUNSELOR,
    ROLE_PROGRAM_ADMIN,
    ROLE_SERVICE_MEMBER,
    ROLE_TSP_COORDINATOR,
    acting_user_id,
    endpoint,
    require_ownership,
)
from paging import list_response
from response import created, ok
from serializers import serialize
from services import calculations as calc
from services import ledger
from validation import (
    DOD_ID_RE,
    MARKET_CODE_RE,
    bad,
    get_body,
    opt_bool,
    opt_dt,
    opt_int,
    opt_str,
    present,
    req_bool,
    req_dt,
    req_enum,
    req_int,
    req_pattern,
    req_str,
)

bp = Blueprint("members", __name__)


# ------------------------------------------------------------- service members


@bp.post("/service-members")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def register_service_member():
    body = get_body()
    dod_id = req_str(body, "dod_id")
    if not DOD_ID_RE.match(dod_id):
        raise bad("Field 'dod_id' must be exactly ten digits.")
    full_name = req_str(body, "full_name", min_len=1, max_len=120)
    rank_code = req_enum(body, "rank_code", calc.RANK_CODES)
    branch = req_enum(body, "branch", calc.BRANCHES)
    email = req_str(body, "email")
    if "@" not in email:
        raise bad("Field 'email' must contain an at-sign.")
    dependents_count = opt_int(body, "dependents_count", default=0, minimum=0, maximum=12)
    spouse_present = opt_bool(body, "spouse_present", default=False)

    for existing in db.service_members.values():
        if existing["dod_id"] == dod_id:
            raise ApiError("ERR_DUPLICATE_DOD_ID", "A member with this DoD ID already exists.")

    record = base_record()
    record.update(
        {
            "dod_id": dod_id,
            "full_name": full_name,
            "rank_code": rank_code,
            "branch": branch,
            "dependents_count": dependents_count,
            "spouse_present": spouse_present,
            "email": email,
            "active_shipment_count": 0,
        }
    )
    mark_fresh(record)
    db.service_members[record["id"]] = record
    return created(serialize(record))


@bp.get("/service-members/<member_id>")
@endpoint(
    [
        ROLE_SERVICE_MEMBER,
        ROLE_MOVE_COUNSELOR,
        ROLE_TSP_COORDINATOR,
        ROLE_CLAIMS_EXAMINER,
        ROLE_PROGRAM_ADMIN,
    ]
)
def read_service_member(member_id):
    member = ledger.get_member(member_id)
    require_ownership(member["id"])
    return ok(serialize(member))


@bp.get("/service-members/<member_id>/orders")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_CLAIMS_EXAMINER, ROLE_PROGRAM_ADMIN])
def list_member_orders(member_id):
    member = ledger.get_member(member_id)
    require_ownership(member["id"])
    records = by_seq(
        [o for o in db.orders.values() if o["service_member_id"] == member["id"]]
    )
    return list_response(records)


# ------------------------------------------------------------------- PCS orders


@bp.post("/orders")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def issue_orders():
    body = get_body()
    service_member_id = req_str(body, "service_member_id")
    order_number = req_str(body, "order_number", min_len=4, max_len=32)
    move_type = req_enum(body, "move_type", calc.MOVE_TYPES)
    issue_date = req_dt(body, "issue_date")
    report_date = req_dt(body, "report_no_later_than_date")
    if report_date <= issue_date:
        raise bad("Field 'report_no_later_than_date' must be strictly after 'issue_date'.")
    origin_duty_station = req_str(body, "origin_duty_station")
    destination_duty_station = req_str(body, "destination_duty_station")
    origin_market_code = req_pattern(
        body, "origin_market_code", MARKET_CODE_RE, "match ^MKT-[A-Z]{3}$"
    )
    distance_miles = req_int(body, "distance_miles", minimum=1, maximum=12000)
    is_dependent_restricted = opt_bool(body, "is_dependent_restricted", default=False)

    member = ledger.get_member(service_member_id)

    for existing in db.orders.values():
        if existing["order_number"] == order_number:
            raise ApiError(
                "ERR_DUPLICATE_ORDER_NUMBER", "These orders have already been issued."
            )

    record = base_record()
    record.update(
        {
            "service_member_id": member["id"],
            "order_number": order_number,
            "move_type": move_type,
            "issue_date": issue_date,
            "report_no_later_than_date": report_date,
            "origin_duty_station": origin_duty_station,
            "destination_duty_station": destination_duty_station,
            "origin_market_code": origin_market_code,
            "distance_miles": distance_miles,
            "is_dependent_restricted": is_dependent_restricted,
            "dependents_count_at_issue": member["dependents_count"],
            "status": "ISSUED",
            "amendment_count": 0,
            "last_amendment_reason": None,
        }
    )
    mark_fresh(record)
    db.orders[record["id"]] = record
    return created(serialize(record))


@bp.get("/orders/<order_id>")
@endpoint(
    [
        ROLE_SERVICE_MEMBER,
        ROLE_MOVE_COUNSELOR,
        ROLE_TSP_COORDINATOR,
        ROLE_CLAIMS_EXAMINER,
        ROLE_PROGRAM_ADMIN,
    ]
)
def read_order(order_id):
    order = ledger.get_order(order_id)
    require_ownership(ledger.member_of_order(order))
    return ok(serialize(order))


@bp.post("/orders/<order_id>/amend")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def amend_order(order_id):
    body = get_body()
    amendment_reason = req_str(body, "amendment_reason")
    dependents_override = opt_int(
        body, "dependents_count_override", default=None, minimum=0, maximum=12
    )
    report_override = opt_dt(body, "report_no_later_than_date_override")
    move_type_override = None
    if present(body, "move_type_override"):
        move_type_override = req_enum(body, "move_type_override", calc.MOVE_TYPES)
    if dependents_override is None and report_override is None and move_type_override is None:
        raise bad("At least one override must be supplied.")

    order = ledger.get_order(order_id)

    if order["status"] not in ("ISSUED", "AMENDED"):
        raise ApiError("ERR_INVALID_ORDER_STATE", "These orders may no longer be amended.")
    if order["amendment_count"] >= calc.ORDER_AMENDMENT_LIMIT:
        raise ApiError("ERR_ORDER_AMENDMENT_LIMIT", "These orders have already been amended three times.")

    order["amendment_count"] += 1
    order["last_amendment_reason"] = amendment_reason
    if dependents_override is not None:
        order["dependents_count_at_issue"] = dependents_override
    if report_override is not None:
        order["report_no_later_than_date"] = report_override
    if move_type_override is not None:
        order["move_type"] = move_type_override
    order["status"] = "AMENDED"
    touch(order)

    # Amendment cascade (PRD §3.1)
    for entitlement in by_seq(list(db.entitlements.values())):
        if entitlement["order_id"] != order["id"]:
            continue
        if entitlement["status"] not in ("DRAFT", "AUTHORIZED", "SUSPENDED"):
            continue
        ledger.recompute_entitlement_allowance(entitlement)
        ledger.recompute_entitlement_ledger(entitlement, cascade=True)

    return ok(serialize(order))


@bp.get("/orders/<order_id>/counseling-sessions")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def list_order_sessions(order_id):
    order = ledger.get_order(order_id)
    require_ownership(ledger.member_of_order(order))
    records = by_seq(
        [s for s in db.counseling_sessions.values() if s["order_id"] == order["id"]]
    )
    return list_response(records)


@bp.get("/orders/<order_id>/entitlements")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def list_order_entitlements(order_id):
    order = ledger.get_order(order_id)
    require_ownership(ledger.member_of_order(order))
    records = by_seq([e for e in db.entitlements.values() if e["order_id"] == order["id"]])
    return list_response(records)


@bp.get("/orders/<order_id>/shipments")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def list_order_shipments(order_id):
    order = ledger.get_order(order_id)
    require_ownership(ledger.member_of_order(order))
    records = by_seq([s for s in db.shipments.values() if s["order_id"] == order["id"]])
    return list_response(records)


# ----------------------------------------------------------- counseling sessions


@bp.post("/counseling-sessions")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def book_counseling_session():
    body = get_body()
    order_id = req_str(body, "order_id")
    session_type = req_enum(body, "session_type", calc.SESSION_TYPES)
    scheduled_at = req_dt(body, "scheduled_at")

    order = ledger.get_order(order_id)

    record = base_record()
    record.update(
        {
            "order_id": order["id"],
            "session_type": session_type,
            "scheduled_at": scheduled_at,
            "counselor_user_id": None,
            "completed_at": None,
            "entitlement_briefed": False,
            "counseling_deadline_at": order["report_no_later_than_date"]
            - timedelta(days=calc.COUNSELING_LEAD_DAYS),
            "is_late_counseling": False,
            "status": "SCHEDULED",
        }
    )
    mark_fresh(record)
    db.counseling_sessions[record["id"]] = record
    return created(serialize(record))


@bp.get("/counseling-sessions/<session_id>")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def read_counseling_session(session_id):
    session = ledger.get_session(session_id)
    require_ownership(ledger.member_of_session(session))
    return ok(serialize(session))


@bp.post("/counseling-sessions/<session_id>/complete")
@endpoint([ROLE_MOVE_COUNSELOR])
def complete_counseling_session(session_id):
    body = get_body()
    briefed = req_bool(body, "entitlement_briefed")
    if briefed is not True:
        raise bad("Field 'entitlement_briefed' must be true.")

    session = ledger.get_session(session_id)

    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_COUNSELING_STATE", "This session has already been completed.")
    for existing in db.entitlements.values():
        if existing["order_id"] == session["order_id"]:
            raise ApiError(
                "ERR_DUPLICATE_ENTITLEMENT",
                "An entitlement authorization already exists for these orders.",
            )

    completed_at = clock()
    session["completed_at"] = completed_at
    session["counselor_user_id"] = acting_user_id()
    session["entitlement_briefed"] = True
    session["is_late_counseling"] = completed_at > session["counseling_deadline_at"]
    session["status"] = "COMPLETED"
    touch(session)

    order = db.orders[session["order_id"]]
    member = db.service_members[order["service_member_id"]]
    dep_status = calc.dependent_status_effective(
        order["dependents_count_at_issue"], order["is_dependent_restricted"]
    )
    base_allowance = calc.base_weight_allowance(
        member["rank_code"], dep_status, order["move_type"]
    )
    entitlement = base_record()
    entitlement.update(
        {
            "order_id": order["id"],
            "counseling_session_id": session["id"],
            "rank_code_at_authorization": member["rank_code"],
            "dependent_status_effective": dep_status,
            "base_weight_allowance_lbs": base_allowance,
            "pro_gear_member_allowance_lbs": calc.PRO_GEAR_MEMBER_CAP_LBS,
            "pro_gear_spouse_allowance_lbs": calc.spouse_allowance(
                dep_status, member["spouse_present"]
            ),
            "admin_weight_bump_lbs": 0,
            "total_billable_cap_lbs": base_allowance,
            "charged_billable_weight_lbs": 0,
            "pro_gear_excluded_total_lbs": 0,
            "excess_weight_lbs": 0,
            "gross_excess_cost_usd": calc.ZERO,
            "excess_cost_waived_usd": calc.ZERO,
            "excess_cost_due_usd": calc.ZERO,
            "authorized_by_user_id": None,
            "waiver_reason": None,
            "suspension_reason": None,
            "status": "DRAFT",
        }
    )
    mark_fresh(entitlement)
    db.entitlements[entitlement["id"]] = entitlement

    return ok(serialize(session))


@bp.get("/counseling-sessions/<session_id>/entitlements")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def list_session_entitlements(session_id):
    session = ledger.get_session(session_id)
    require_ownership(ledger.member_of_session(session))
    records = by_seq(
        [e for e in db.entitlements.values() if e["counseling_session_id"] == session["id"]]
    )
    return list_response(records)
