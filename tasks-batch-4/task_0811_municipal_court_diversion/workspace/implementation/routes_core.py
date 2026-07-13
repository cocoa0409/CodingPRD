"""Routes: clock, reference data, defendants, cases, charges, arraignments, plea."""

from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request, g

from errors import ApiError
from auth import endpoint, ALL_ROLES
from store import (db, now, clock, base_fields, touch, serialize,
                   parse_iso_datetime, parse_iso_date)
from envelope import success, parse_pagination, list_response, paginate
import bodyutil as B
import calc
from domain import charges_of_case, account_of_case

bp_core = Blueprint("core", __name__)

PLEA_VALUES = {"GUILTY", "NOT_GUILTY", "NO_CONTEST"}


# ---------------------------------------------------------------------------
# lookups (raise not-found)
# ---------------------------------------------------------------------------
def get_defendant(did):
    d = db.defendants.get(did)
    if d is None:
        raise ApiError("ERR_DEFENDANT_NOT_FOUND", "defendant not found")
    return d


def get_case(cid):
    c = db.cases.get(cid)
    if c is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "case not found")
    return c


def get_courtroom(rid):
    r = db.courtrooms.get(rid)
    if r is None:
        raise ApiError("ERR_COURTROOM_NOT_FOUND", "courtroom not found")
    return r


def get_arraignment(aid):
    a = db.arraignments.get(aid)
    if a is None:
        raise ApiError("ERR_ARRAIGNMENT_NOT_FOUND", "arraignment not found")
    return a


# ---------------------------------------------------------------------------
# clock
# ---------------------------------------------------------------------------
@bp_core.post("/_clock/set_current_utc")
@endpoint(["CourtAdmin"])
def set_clock():
    body = B.get_body()
    target = B.req_datetime(body, "to_iso8601")
    clock.set(target)
    return success({}, response_type="object", status=200)


# ---------------------------------------------------------------------------
# reference data
# ---------------------------------------------------------------------------
@bp_core.post("/courtrooms")
@endpoint(["CourtAdmin"])
def create_courtroom():
    body = B.get_body()
    name = B.req_str(body, "name")
    room_code = B.req_str(body, "room_code")
    buffer_min = B.opt_int(body, "changeover_buffer_minutes", 15, minimum=0)
    rec = base_fields()
    rec.update({"name": name, "room_code": room_code,
                "changeover_buffer_minutes": buffer_min})
    db.courtrooms[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp_core.get("/courtrooms/<rid>")
@endpoint(ALL_ROLES)
def fetch_courtroom(rid):
    return success(serialize(get_courtroom(rid)))


@bp_core.post("/service-sites")
@endpoint(["CourtAdmin"])
def create_service_site():
    body = B.get_body()
    name = B.req_str(body, "name")
    site_type = B.req_enum(body, "site_type", {"COMMUNITY_SERVICE", "EDUCATION_CLASS"})
    capacity = B.req_int(body, "concurrent_capacity", minimum=1)
    rec = base_fields()
    rec.update({"name": name, "site_type": site_type, "concurrent_capacity": capacity})
    db.service_sites[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp_core.get("/service-sites/<sid>")
@endpoint(ALL_ROLES)
def fetch_service_site(sid):
    s = db.service_sites.get(sid)
    if s is None:
        raise ApiError("ERR_SERVICE_SITE_NOT_FOUND", "service site not found")
    return success(serialize(s))


@bp_core.post("/amnesty-programs")
@endpoint(["CourtAdmin"])
def create_amnesty_program():
    body = B.get_body()
    name = B.req_str(body, "name")
    waiver = B.req_decimal(body, "penalty_waiver_pct")
    if waiver < Decimal("0") or waiver > Decimal("1"):
        raise ApiError("ERR_VALIDATION", "penalty_waiver_pct must be within [0, 1]")
    fee = B.req_decimal(body, "reinstatement_fee", minimum=Decimal("0"))
    active_from = B.req_datetime(body, "active_from")
    active_to = B.req_datetime(body, "active_to")
    rec = base_fields()
    rec.update({"name": name, "penalty_waiver_pct": waiver, "reinstatement_fee": fee,
                "active_from": active_from, "active_to": active_to})
    db.amnesty_programs[rec["id"]] = rec
    return success(serialize(rec), status=201)


# ---------------------------------------------------------------------------
# defendants
# ---------------------------------------------------------------------------
@bp_core.post("/defendants")
@endpoint(["CourtClerk"])
def create_defendant():
    body = B.get_body()
    full_name = B.req_str(body, "full_name")
    dob = B.req_str(body, "date_of_birth")
    email = B.req_str(body, "email")
    prior = B.opt_int(body, "prior_diversion_count", 0, minimum=0)
    rec = base_fields()
    rec.update({"full_name": full_name, "date_of_birth": dob, "email": email,
                "prior_diversion_count": prior})
    db.defendants[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp_core.get("/defendants/<did>")
@endpoint(ALL_ROLES)
def fetch_defendant(did):
    return success(serialize(get_defendant(did)))


@bp_core.get("/defendants/<did>/cases")
@endpoint(ALL_ROLES)
def list_defendant_cases(did):
    get_defendant(did)
    limit, offset = parse_pagination(request.args)
    items = [c for c in db.cases.values() if c["defendant_id"] == did]
    return list_response(items, limit, offset, serialize)


# ---------------------------------------------------------------------------
# cases & charges
# ---------------------------------------------------------------------------
@bp_core.post("/cases")
@endpoint(["CourtClerk"])
def create_case():
    body = B.get_body()
    defendant_id = B.req_str(body, "defendant_id")
    citation_number = B.req_str(body, "citation_number")
    offense_date = B.req_str(body, "offense_date")
    # validate the date parses
    try:
        od = parse_iso_date(offense_date)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "offense_date must be an ISO date (YYYY-MM-DD)")
    get_defendant(defendant_id)
    deadline = od + timedelta(days=calc.ARRAIGNMENT_WINDOW_DAYS)
    rec = base_fields()
    rec.update({"defendant_id": defendant_id, "citation_number": citation_number,
                "offense_date": offense_date, "arraignment_deadline": deadline,
                "status": "DOCKETED"})
    db.cases[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp_core.get("/cases/<cid>")
@endpoint(ALL_ROLES)
def fetch_case(cid):
    return success(serialize(get_case(cid)))


@bp_core.post("/cases/<cid>/charges")
@endpoint(["CourtClerk"])
def add_charge(cid):
    get_case(cid)
    body = B.get_body()
    offense_code = B.req_str(body, "offense_code")
    severity = B.req_enum(body, "severity", {"INFRACTION", "MISDEMEANOR"})
    base_fine = B.req_decimal(body, "base_fine_amount", minimum=Decimal("0"))
    eligible = B.opt_bool(body, "is_diversion_eligible", True)
    rec = base_fields()
    rec.update({"case_id": cid, "offense_code": offense_code, "severity": severity,
                "base_fine_amount": base_fine, "is_diversion_eligible": eligible})
    db.charges[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp_core.get("/cases/<cid>/charges")
@endpoint(ALL_ROLES)
def list_charges(cid):
    get_case(cid)
    limit, offset = parse_pagination(request.args)
    items = charges_of_case(cid)
    return list_response(items, limit, offset, serialize)


# ---------------------------------------------------------------------------
# arraignments
# ---------------------------------------------------------------------------
def _expand(start, end, buf_minutes):
    delta = timedelta(minutes=buf_minutes)
    return start - delta, end + delta


@bp_core.post("/cases/<cid>/arraignments")
@endpoint(["CourtClerk"])
def schedule_arraignment(cid):
    get_case(cid)
    body = B.get_body()
    courtroom_id = B.req_str(body, "courtroom_id")
    start = B.req_datetime(body, "scheduled_start")
    end = B.req_datetime(body, "scheduled_end")
    if end <= start:
        raise ApiError("ERR_VALIDATION", "scheduled_end must be after scheduled_start")
    room = get_courtroom(courtroom_id)
    buf = room["changeover_buffer_minutes"]
    ns, ne = _expand(start, end, buf)
    for a in db.arraignments.values():
        if a["courtroom_id"] != courtroom_id:
            continue
        es, ee = _expand(a["scheduled_start"], a["scheduled_end"], buf)
        if ns < ee and es < ne:  # half-open overlap of buffer-expanded intervals
            raise ApiError("ERR_COURTROOM_DOUBLE_BOOKED",
                           "hearing overlaps another in this courtroom")
    rec = base_fields()
    rec.update({"case_id": cid, "courtroom_id": courtroom_id,
                "scheduled_start": start, "scheduled_end": end,
                "plea": None, "status": "SCHEDULED"})
    db.arraignments[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp_core.get("/arraignments/<aid>")
@endpoint(ALL_ROLES)
def fetch_arraignment(aid):
    return success(serialize(get_arraignment(aid)))


@bp_core.get("/arraignments")
@endpoint(ALL_ROLES)
def list_arraignments():
    limit, offset = parse_pagination(request.args)
    case_id = request.args.get("case_id")
    courtroom_id = request.args.get("courtroom_id")
    items = list(db.arraignments.values())
    if case_id is not None:
        items = [a for a in items if a["case_id"] == case_id]
    if courtroom_id is not None:
        items = [a for a in items if a["courtroom_id"] == courtroom_id]
    return list_response(items, limit, offset, serialize)


@bp_core.post("/arraignments/<aid>/plea")
@endpoint(["Defendant", "Judge"])
def enter_plea(aid):
    arr = get_arraignment(aid)
    case = db.cases[arr["case_id"]]
    # ownership: a Defendant may only act on their own case
    if g.user_role == "Defendant" and g.user_id != case["defendant_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "defendant may act only on their own case")
    # state: arraignment must be SCHEDULED (plea not already recorded)
    if arr["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_PLEA", "plea already recorded")
    body = B.get_body()
    plea = body.get("plea")
    if plea is not None and plea not in PLEA_VALUES:
        raise ApiError("ERR_INVALID_PLEA", "invalid plea value")
    # temporal: plea at or before arraignment deadline
    if now() > case["arraignment_deadline"]:
        raise ApiError("ERR_ARRAIGNMENT_DEADLINE_PASSED", "arraignment deadline passed")
    if plea is None:
        raise ApiError("ERR_VALIDATION", "'plea' is required")

    # apply
    arr["plea"] = plea
    arr["status"] = "HELD"
    touch(arr)
    case["status"] = "ARRAIGNED"
    touch(case)
    # create provisional ledger account
    charges = charges_of_case(case["id"])
    fines, court_fee, surcharge, pf = calc.fine_components(charges, "provisional")
    acct = base_fields()
    acct.update({
        "case_id": case["id"],
        "_fines": fines, "_court_fee": court_fee, "_surcharge": surcharge,
        "_program_fee": pf, "_penalty": Decimal("0.00"),
        "assessed_amount": calc.q2(fines + court_fee + surcharge),
        "collected_amount": Decimal("0.00"),
        "balance": calc.q2(fines + court_fee + surcharge),
        "status": "PROVISIONAL",
    })
    db.ledger_accounts[acct["id"]] = acct
    return success(serialize(arr), status=200)
