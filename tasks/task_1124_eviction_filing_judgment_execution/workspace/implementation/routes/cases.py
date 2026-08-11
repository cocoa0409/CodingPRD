from datetime import time, timedelta, timezone
from datetime import datetime as dt_cls

from flask import Blueprint

import db
from db import LOCK, STORE
from errors import ApiError
from middleware import auth, require_owner
from response import ok_list, ok_object
from services import calc, serialize as ser
from services.resolution import get_case, get_notice, get_tenancy, jurisdiction_of_case
from utils import body_json, is_int, pagination, v_date, v_enum, v_str

bp = Blueprint("cases", __name__)

TERMINAL_CASE_STATUSES = {"EXECUTED", "SETTLED", "DISMISSED", "CURED"}
DISMISSIBLE_STATUSES = {
    "DRAFT",
    "NOTICE_ACTIVE",
    "NOTICE_EXPIRED",
    "FILING_REJECTED",
    "FILED",
    "SERVICE_COMPLETE",
    "HEARING_SCHEDULED",
    "ANSWERED",
    "HEARING_CONCLUDED",
}


@bp.post("/api/cases")
@auth({"Landlord"})
def create_case(_uid, _role):
    with LOCK:
        b = body_json()
        tenancy_id = v_str(b, "tenancy_id")
        case_reason = v_enum(b, "case_reason", {"NONPAYMENT", "LEASE_VIOLATION", "SEVERE"})
        tenancy = get_tenancy(tenancy_id)
        unit = STORE.units[tenancy["unit_id"]]
        require_owner(_uid, unit["landlord_id"])
        if tenancy["status"] != "ACTIVE":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Tenancy is not ACTIVE"
            )
        for c in STORE.cases.values():
            if c["tenancy_id"] == tenancy_id and c["status"] not in TERMINAL_CASE_STATUSES:
                raise ApiError(
                    "ERR_CASE_ALREADY_OPEN",
                    409,
                    "Non-terminal case already exists for the tenancy",
                )
        STORE.case_seq += 1
        case_number = f"EV-{db.now().year}-{STORE.case_seq:06d}"
        r = db.new_record(
            {
                "tenancy_id": tenancy_id,
                "landlord_id": unit["landlord_id"],
                "case_reason": case_reason,
                "status": "DRAFT",
                "case_number": case_number,
                "served_defendant_names": [],
                "service_completed_at": None,
                "dismiss_reason": None,
            }
        )
        STORE.cases[r["id"]] = r
        return ok_object(ser.case(r), 201)


@bp.get("/api/cases/<cid>")
@auth({"Landlord", "CourtClerk", "ProcessServer", "SheriffDeputy", "Mediator", "PlatformAdmin"})
def read_case(cid, _uid, _role):
    with LOCK:
        return ok_object(ser.case(get_case(cid)))


@bp.get("/api/cases")
@auth({"Landlord", "CourtClerk", "PlatformAdmin"})
def list_cases(_uid, _role):
    with LOCK:
        limit, offset = pagination()
        f_landlord = _arg("landlord_id")
        f_tenancy = _arg("tenancy_id")
        f_status = _arg("status")
        items = db.sorted_items(STORE.cases)
        if f_landlord is not None:
            items = [c for c in items if c["landlord_id"] == f_landlord]
        if f_tenancy is not None:
            items = [c for c in items if c["tenancy_id"] == f_tenancy]
        if f_status is not None:
            items = [c for c in items if c["status"] == f_status]
        page = items[offset : offset + limit]
        return ok_list([ser.case(r) for r in page], len(items), limit, offset)


def _arg(name):
    from flask import request

    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.get("/api/tenancies/<tid>/cases")
@auth({"Landlord", "CourtClerk", "PlatformAdmin"})
def list_tenancy_cases(tid, _uid, _role):
    with LOCK:
        get_tenancy(tid)
        limit, offset = pagination()
        items = [c for c in db.sorted_items(STORE.cases) if c["tenancy_id"] == tid]
        page = items[offset : offset + limit]
        return ok_list([ser.case(r) for r in page], len(items), limit, offset)


@bp.post("/api/cases/<cid>/dismiss")
@auth({"Landlord"})
def dismiss_case(cid, _uid, _role):
    with LOCK:
        case = get_case(cid)
        require_owner(_uid, case["landlord_id"])
        b = body_json()
        reason = v_str(b, "reason", required=False)
        if case["status"] not in DISMISSIBLE_STATUSES:
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Case status does not permit dismissal"
            )
        case["status"] = "DISMISSED"
        case["dismiss_reason"] = reason
        db.bump(case)
        return ok_object(ser.case(case))


@bp.post("/api/cases/<cid>/notices")
@auth({"Landlord"})
def create_notice(cid, _uid, _role):
    with LOCK:
        case = get_case(cid)
        # rung 4: ownership
        require_owner(_uid, case["landlord_id"])
        # rung 5: body shape including conditional fields
        b = body_json()
        notice_type = v_enum(
            b, "notice_type", {"PAY_OR_QUIT", "CURE_OR_QUIT", "UNCONDITIONAL_QUIT"}
        )
        served_on = v_date(b, "served_on")
        ecv = b.get("expected_case_version")
        if ecv is None or not is_int(ecv):
            raise ApiError(
                "ERR_VALIDATION", 400, "expected_case_version is required and must be an integer"
            )
        claimed = b.get("claimed_rent_owed_cents")
        vdesc = b.get("violation_description")
        if notice_type == "PAY_OR_QUIT":
            if claimed is None or not is_int(claimed) or claimed <= 0:
                raise ApiError(
                    "ERR_VALIDATION", 400, "claimed_rent_owed_cents is required for PAY_OR_QUIT and must be > 0"
                )
            if vdesc is not None:
                raise ApiError(
                    "ERR_VALIDATION", 400, "violation_description is only allowed for CURE_OR_QUIT"
                )
        elif notice_type == "CURE_OR_QUIT":
            if not isinstance(vdesc, str) or vdesc == "":
                raise ApiError(
                    "ERR_VALIDATION", 400, "violation_description is required for CURE_OR_QUIT"
                )
            if claimed is not None:
                raise ApiError(
                    "ERR_VALIDATION", 400, "claimed_rent_owed_cents is only allowed for PAY_OR_QUIT"
                )
        else:  # UNCONDITIONAL_QUIT
            if claimed is not None or vdesc is not None:
                raise ApiError(
                    "ERR_VALIDATION",
                    400,
                    "claimed_rent_owed_cents/violation_description are not allowed for UNCONDITIONAL_QUIT",
                )
        # rung 6: OCC
        if ecv != case["version"]:
            raise ApiError(
                "ERR_STALE_VERSION", 412, "expected_case_version does not match current case.version"
            )
        # rung 7: state gate
        if case["status"] not in ("DRAFT", "NOTICE_ACTIVE"):
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Case status does not permit notice drafting"
            )
        # rung 9: notice-type compatibility
        if calc.NOTICE_TYPE_REASON[notice_type] != case["case_reason"]:
            raise ApiError(
                "ERR_NOTICE_TYPE_MISMATCH", 422, "notice_type incompatible with case_reason"
            )
        # rung 10: future-date prohibition
        if served_on > db.now().date():
            raise ApiError(
                "ERR_DATE_IN_FUTURE", 422, "served_on must not be in the future"
            )
        # supersede prior PENDING notice
        for n in STORE.notices.values():
            if n["case_id"] == cid and n["status"] == "PENDING":
                n["status"] = "SUPERSEDED"
                db.bump(n)
        jurisdiction = jurisdiction_of_case(case)
        days = calc.CURE_DAYS[jurisdiction][notice_type]
        deadline_date = served_on + timedelta(days=days)
        cure_deadline = dt_cls.combine(
            deadline_date, time(23, 59, 59), tzinfo=timezone.utc
        )
        notice = db.new_record(
            {
                "case_id": cid,
                "notice_type": notice_type,
                "served_on": served_on.isoformat(),
                "claimed_rent_owed_cents": claimed,
                "violation_description": vdesc,
                "statutory_cure_days": days,
                "cure_deadline": cure_deadline,
                "status": "PENDING",
                "cured_at": None,
            }
        )
        STORE.notices[notice["id"]] = notice
        case["status"] = "NOTICE_ACTIVE"
        db.bump(case)  # increments case.version by exactly 1
        return ok_object(ser.notice(notice), 201)


@bp.get("/api/notices/<nid>")
@auth({"Landlord", "CourtClerk", "PlatformAdmin"})
def read_notice(nid, _uid, _role):
    with LOCK:
        return ok_object(ser.notice(get_notice(nid)))


@bp.get("/api/cases/<cid>/notices")
@auth({"Landlord", "CourtClerk", "PlatformAdmin"})
def list_case_notices(cid, _uid, _role):
    with LOCK:
        get_case(cid)
        limit, offset = pagination()
        items = [n for n in db.sorted_items(STORE.notices) if n["case_id"] == cid]
        page = items[offset : offset + limit]
        return ok_list([ser.notice(r) for r in page], len(items), limit, offset)


@bp.post("/api/notices/<nid>/record-cure")
@auth({"Landlord"})
def record_cure(nid, _uid, _role):
    with LOCK:
        notice = get_notice(nid)
        case = STORE.cases[notice["case_id"]]
        require_owner(_uid, case["landlord_id"])
        b = body_json()
        paid = b.get("paid_amount_cents")
        violation_cured = b.get("violation_cured")
        if paid is not None and not is_int(paid):
            raise ApiError("ERR_VALIDATION", 400, "paid_amount_cents must be an integer")
        if violation_cured is not None and not isinstance(violation_cured, bool):
            raise ApiError("ERR_VALIDATION", 400, "violation_cured must be a boolean")
        # shape: type-conditional requirements
        if notice["notice_type"] == "PAY_OR_QUIT" and paid is None:
            raise ApiError(
                "ERR_VALIDATION", 400, "paid_amount_cents is required for PAY_OR_QUIT cure"
            )
        if notice["notice_type"] == "CURE_OR_QUIT" and violation_cured is not True:
            raise ApiError(
                "ERR_VALIDATION", 400, "violation_cured must be affirmed as true for CURE_OR_QUIT cure"
            )
        # state gate
        if notice["status"] != "PENDING":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Notice is not PENDING"
            )
        # cure window: UNCONDITIONAL_QUIT never curable; strict deadline
        if notice["notice_type"] == "UNCONDITIONAL_QUIT" or db.now() > notice["cure_deadline"]:
            raise ApiError(
                "ERR_CURE_WINDOW_CLOSED",
                409,
                "Cure attempted after cure_deadline or on an UNCONDITIONAL_QUIT notice",
            )
        # fiscal sufficiency
        if notice["notice_type"] == "PAY_OR_QUIT" and paid < notice["claimed_rent_owed_cents"]:
            raise ApiError(
                "ERR_CURE_AMOUNT_INSUFFICIENT",
                422,
                "PAY_OR_QUIT cure payment below claimed_rent_owed_cents",
            )
        notice["status"] = "CURED"
        notice["cured_at"] = db.now()
        db.bump(notice)
        if case["status"] == "NOTICE_ACTIVE":
            case["status"] = "CURED"
            db.bump(case)
        return ok_object(ser.notice(notice))
