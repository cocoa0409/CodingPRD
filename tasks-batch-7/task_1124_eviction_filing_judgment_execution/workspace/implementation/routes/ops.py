from flask import Blueprint

import db
from db import LOCK, STORE
from middleware import auth
from response import ok_object
from utils import body_json, v_dt

bp = Blueprint("ops", __name__)


@bp.post("/api/ops/runs")
@auth({"CourtClerk"})
def ops_run(_uid, _role):
    with LOCK:
        body_json()
        now = db.now()
        notices_expired = 0
        judgments_finalized = 0
        writs_expired = 0
        writs_unscheduled = 0
        storage_records_disposable = 0
        # step 1: expire PENDING notices past cure_deadline; advance cases
        for n in list(STORE.notices.values()):
            if n["status"] == "PENDING" and now > n["cure_deadline"]:
                n["status"] = "EXPIRED"
                db.bump(n)
                notices_expired += 1
                case = STORE.cases.get(n["case_id"])
                if case is not None and case["status"] == "NOTICE_ACTIVE":
                    case["status"] = "NOTICE_EXPIRED"
                    db.bump(case)
        # step 2: finalize ENTERED judgments at/past appeal_deadline
        for j in list(STORE.judgments.values()):
            if j["status"] == "ENTERED" and now >= j["appeal_deadline"]:
                j["status"] = "FINAL"
                db.bump(j)
                judgments_finalized += 1
        # step 3: expire ISSUED writs past expires_on; case back to JUDGMENT_ENTERED
        for w in list(STORE.writs.values()):
            if (
                w["status"] == "ISSUED"
                and w["expires_on"] is not None
                and now > w["expires_on"]
            ):
                w["status"] = "EXPIRED"
                db.bump(w)
                writs_expired += 1
                case = STORE.cases.get(w["case_id"])
                if case is not None and case["status"] == "WRIT_ISSUED":
                    case["status"] = "JUDGMENT_ENTERED"
                    db.bump(case)
        # step 4: unschedule SCHEDULED writs whose window has lapsed
        for w in list(STORE.writs.values()):
            if (
                w["status"] == "SCHEDULED"
                and w["window_end"] is not None
                and now > w["window_end"]
            ):
                w["status"] = "ISSUED"
                w["deputy_id"] = None
                w["window_start"] = None
                w["window_end"] = None
                db.bump(w)
                writs_unscheduled += 1
                case = STORE.cases.get(w["case_id"])
                if case is not None and case["status"] == "LOCKOUT_SCHEDULED":
                    case["status"] = "WRIT_ISSUED"
                    db.bump(case)
        # step 5: STORED storage records past disposal_eligible_on -> DISPOSABLE
        for sr in list(STORE.storage_records.values()):
            if sr["status"] == "STORED" and now > sr["disposal_eligible_on"]:
                sr["status"] = "DISPOSABLE"
                db.bump(sr)
                storage_records_disposable += 1
        return ok_object(
            {
                "notices_expired": notices_expired,
                "judgments_finalized": judgments_finalized,
                "writs_expired": writs_expired,
                "writs_unscheduled": writs_unscheduled,
                "storage_records_disposable": storage_records_disposable,
            }
        )


@bp.post("/api/_clock/set_current_utc")
@auth({"PlatformAdmin"})
def set_clock(_uid, _role):
    with LOCK:
        b = body_json()
        target = v_dt(b, "to_iso8601")
        STORE.clock = target
        from utils import ts

        return ok_object({"current_utc": ts(STORE.clock)})
