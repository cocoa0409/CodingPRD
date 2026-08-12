from datetime import timedelta

from flask import Blueprint

import db
from db import LOCK, STORE
from errors import ApiError
from middleware import auth, require_owner
from response import ok_list, ok_object
from services import calc, serialize as ser
from services.resolution import (
    get_judgment,
    get_storage_record,
    get_writ,
    jurisdiction_of_case,
)
from utils import body_json, pagination, v_dt, v_int, v_str

bp = Blueprint("writs", __name__)

ACTIVE_WRIT_STATUSES = {"REQUESTED", "ISSUED", "SCHEDULED"}


@bp.post("/api/judgments/<jid>/writs")
@auth({"Landlord"})
def request_writ(jid, _uid, _role):
    with LOCK:
        j = get_judgment(jid)
        case = STORE.cases[j["case_id"]]
        require_owner(_uid, case["landlord_id"])
        b = body_json()
        fee_paid = v_int(b, "writ_fee_paid_cents", min_exclusive=0)
        # appeal finality
        if j["status"] != "FINAL":
            raise ApiError(
                "ERR_APPEAL_WINDOW_OPEN", 409, "Judgment not yet FINAL"
            )
        # possession required
        if not j["possession_granted"]:
            raise ApiError(
                "ERR_NO_POSSESSION_GRANTED",
                422,
                "Writ requested on a judgment without possession_granted",
            )
        # one active writ per judgment
        for w in STORE.writs.values():
            if w["judgment_id"] == jid and w["status"] in ACTIVE_WRIT_STATUSES:
                raise ApiError(
                    "ERR_WRIT_ACTIVE_EXISTS",
                    409,
                    "An active writ already exists for the judgment",
                )
        # exact jurisdictional fee
        jurisdiction = jurisdiction_of_case(case)
        if fee_paid != calc.WRIT_FEE[jurisdiction]:
            raise ApiError(
                "ERR_WRIT_FEE_MISMATCH",
                422,
                "writ_fee_paid_cents != jurisdictional writ fee",
            )
        tenancy = STORE.tenancies[case["tenancy_id"]]
        w = db.new_record(
            {
                "judgment_id": jid,
                "case_id": case["id"],
                "unit_id": tenancy["unit_id"],
                "status": "REQUESTED",
                "writ_fee_paid_cents": fee_paid,
                "issued_at": None,
                "expires_on": None,
                "deputy_id": None,
                "window_start": None,
                "window_end": None,
                "executed_at": None,
            }
        )
        STORE.writs[w["id"]] = w
        return ok_object(ser.writ(w), 201)


@bp.get("/api/writs/<wid>")
@auth({"Landlord", "CourtClerk", "SheriffDeputy", "PlatformAdmin"})
def read_writ(wid, _uid, _role):
    with LOCK:
        return ok_object(ser.writ(get_writ(wid)))


@bp.get("/api/judgments/<jid>/writs")
@auth({"Landlord", "CourtClerk", "SheriffDeputy", "PlatformAdmin"})
def list_judgment_writs(jid, _uid, _role):
    with LOCK:
        get_judgment(jid)
        limit, offset = pagination()
        items = [w for w in db.sorted_items(STORE.writs) if w["judgment_id"] == jid]
        page = items[offset : offset + limit]
        return ok_list([ser.writ(r) for r in page], len(items), limit, offset)


@bp.post("/api/writs/<wid>/issue")
@auth({"CourtClerk"})
def issue_writ(wid, _uid, _role):
    with LOCK:
        w = get_writ(wid)
        if w["status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Writ is not REQUESTED")
        j = STORE.judgments[w["judgment_id"]]
        if j["status"] != "FINAL":
            raise ApiError(
                "ERR_APPEAL_WINDOW_OPEN", 409, "Judgment not yet FINAL"
            )
        jurisdiction = jurisdiction_of_case(STORE.cases[w["case_id"]])
        now = db.now()
        w["issued_at"] = now
        w["expires_on"] = now + timedelta(days=calc.WRIT_VALID_DAYS[jurisdiction])
        w["status"] = "ISSUED"
        db.bump(w)
        case = STORE.cases[w["case_id"]]
        if case["status"] == "JUDGMENT_ENTERED":
            case["status"] = "WRIT_ISSUED"
            db.bump(case)
        return ok_object(ser.writ(w))


@bp.post("/api/writs/<wid>/schedule-lockout")
@auth({"SheriffDeputy"})
def schedule_lockout(wid, _uid, _role):
    with LOCK:
        w = get_writ(wid)
        b = body_json()
        deputy_id = v_str(b, "deputy_id")
        window_start = v_dt(b, "window_start")
        window_end = v_dt(b, "window_end")
        if w["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", 409, "Writ is not ISSUED")
        # deputy day capacity (business constraint rung)
        day = window_start.date()
        load = sum(
            1
            for x in STORE.writs.values()
            if x["status"] == "SCHEDULED"
            and x["deputy_id"] == deputy_id
            and x["window_start"] is not None
            and x["window_start"].date() == day
        )
        if load >= calc.MAX_LOCKOUTS_PER_DEPUTY_DAY:
            raise ApiError(
                "ERR_DEPUTY_DAY_CAPACITY",
                409,
                "Deputy already has 3 SCHEDULED lockouts on that calendar date",
            )
        # window validity (temporal rung)
        now = db.now()
        if window_start < now or window_end <= window_start or window_end > w["expires_on"]:
            raise ApiError(
                "ERR_WRIT_WINDOW_INVALID",
                422,
                "window_start in past, window_end <= window_start, or window_end > expires_on",
            )
        w["status"] = "SCHEDULED"
        w["deputy_id"] = deputy_id
        w["window_start"] = window_start
        w["window_end"] = window_end
        db.bump(w)
        case = STORE.cases[w["case_id"]]
        if case["status"] == "WRIT_ISSUED":
            case["status"] = "LOCKOUT_SCHEDULED"
            db.bump(case)
        return ok_object(ser.writ(w))


@bp.post("/api/writs/<wid>/cancel-lockout")
@auth({"SheriffDeputy"})
def cancel_lockout(wid, _uid, _role):
    with LOCK:
        w = get_writ(wid)
        if _uid != w["deputy_id"]:
            raise ApiError(
                "ERR_NOT_ASSIGNED_DEPUTY",
                403,
                "Cancel recorder is not the writ's assigned deputy_id",
            )
        b = body_json()
        v_str(b, "reason", required=False)
        if w["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", 409, "Writ is not SCHEDULED")
        w["status"] = "ISSUED"
        w["deputy_id"] = None
        w["window_start"] = None
        w["window_end"] = None
        db.bump(w)
        case = STORE.cases[w["case_id"]]
        if case["status"] == "LOCKOUT_SCHEDULED":
            case["status"] = "WRIT_ISSUED"
            db.bump(case)
        return ok_object(ser.writ(w))


@bp.post("/api/writs/<wid>/execute")
@auth({"SheriffDeputy"})
def execute_writ(wid, _uid, _role):
    with LOCK:
        w = get_writ(wid)
        if _uid != w["deputy_id"]:
            raise ApiError(
                "ERR_NOT_ASSIGNED_DEPUTY",
                403,
                "Execute recorder is not the writ's assigned deputy_id",
            )
        b = body_json()
        items_summary = v_str(b, "items_summary", required=False)
        if w["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", 409, "Writ is not SCHEDULED")
        now = db.now()
        if not (w["window_start"] <= now <= w["window_end"]) or now > w["expires_on"]:
            raise ApiError(
                "ERR_LOCKOUT_WINDOW_NOT_OPEN",
                409,
                "Execute outside [window_start, window_end] or after expires_on",
            )
        w["status"] = "EXECUTED"
        w["executed_at"] = now
        db.bump(w)
        # storage record side effect
        case = STORE.cases[w["case_id"]]
        unit = STORE.units[w["unit_id"]]
        jurisdiction = unit["jurisdiction_code"]
        sr = db.new_record(
            {
                "writ_id": w["id"],
                "case_id": w["case_id"],
                "items_summary": items_summary,
                "status": "STORED",
                "stored_at": now,
                "daily_fee_cents": calc.STORAGE_DAILY_FEE[jurisdiction],
                "billing_mode": calc.STORAGE_BILLING_MODE[jurisdiction],
                "disposal_eligible_on": calc.disposal_eligible_on(jurisdiction, now),
                "final_charge_cents": None,
            }
        )
        STORE.storage_records[sr["id"]] = sr
        # cascade: case -> EXECUTED -> tenancy ENDED -> unit VACANT
        case["status"] = "EXECUTED"
        db.bump(case)
        tenancy = STORE.tenancies[case["tenancy_id"]]
        tenancy["status"] = "ENDED"
        tenancy["ended_at"] = now
        db.bump(tenancy)
        unit["status"] = "VACANT"
        db.bump(unit)
        return ok_object(ser.writ(w))


@bp.get("/api/writs/<wid>/storage-records")
@auth({"Landlord", "CourtClerk", "SheriffDeputy", "PlatformAdmin"})
def list_writ_storage_records(wid, _uid, _role):
    with LOCK:
        get_writ(wid)
        limit, offset = pagination()
        items = [
            r for r in db.sorted_items(STORE.storage_records) if r["writ_id"] == wid
        ]
        page = items[offset : offset + limit]
        return ok_list([ser.storage_record(r) for r in page], len(items), limit, offset)


@bp.get("/api/storage-records/<sid>")
@auth({"Landlord", "CourtClerk", "SheriffDeputy", "PlatformAdmin"})
def read_storage_record(sid, _uid, _role):
    with LOCK:
        return ok_object(ser.storage_record(get_storage_record(sid)))


@bp.post("/api/storage-records/<sid>/reclaim")
@auth({"SheriffDeputy"})
def reclaim_storage(sid, _uid, _role):
    with LOCK:
        sr = get_storage_record(sid)
        b = body_json()
        charge_paid = v_int(b, "charge_paid_cents", min_inclusive=0)
        if sr["status"] not in ("STORED", "DISPOSABLE"):
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Record is not STORED or DISPOSABLE"
            )
        accrued = calc.storage_charge(
            sr["billing_mode"], sr["daily_fee_cents"], sr["stored_at"], db.now()
        )
        if charge_paid != accrued:
            raise ApiError(
                "ERR_STORAGE_CHARGE_MISMATCH",
                422,
                "charge_paid_cents != accrued charge at current clock",
            )
        sr["final_charge_cents"] = accrued
        sr["status"] = "RECLAIMED"
        db.bump(sr)
        return ok_object(ser.storage_record(sr))


@bp.post("/api/storage-records/<sid>/dispose")
@auth({"SheriffDeputy"})
def dispose_storage(sid, _uid, _role):
    with LOCK:
        sr = get_storage_record(sid)
        body_json()
        if sr["status"] in ("RECLAIMED", "DISPOSED"):
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Record already RECLAIMED or DISPOSED"
            )
        if sr["status"] != "DISPOSABLE":
            raise ApiError(
                "ERR_DISPOSAL_NOT_ELIGIBLE",
                409,
                "Storage disposal before statutory period elapsed",
            )
        sr["status"] = "DISPOSED"
        db.bump(sr)
        return ok_object(ser.storage_record(sr))
