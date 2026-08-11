from flask import Blueprint

import db
from db import LOCK, STORE
from errors import ApiError
from middleware import auth
from response import ok_list, ok_object
from services import serialize as ser
from services.resolution import accepted_package_for_case, get_case
from utils import body_json, pagination, v_dt, v_enum, v_str

bp = Blueprint("service", __name__)


@bp.post("/api/cases/<cid>/service-attempts")
@auth({"ProcessServer", "SheriffDeputy"})
def create_service_attempt(cid, _uid, _role):
    with LOCK:
        case = get_case(cid)
        b = body_json()
        defendant_name = v_str(b, "defendant_name")
        method = v_enum(b, "method", {"PERSONAL", "SUBSTITUTED", "POST_AND_MAIL"})
        result = v_enum(b, "result", {"SERVED", "FAILED"})
        served_at = v_dt(b, "served_at")
        # state gate
        if case["status"] != "FILED":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Case is not FILED"
            )
        # segregation of duties: a party may not serve process
        if _uid == case["landlord_id"]:
            raise ApiError(
                "ERR_SOD_PARTY_CANNOT_SERVE",
                403,
                "Service recorder is the case landlord",
            )
        pkg = accepted_package_for_case(cid)
        defendant_names = pkg["defendant_names"] if pkg else []
        if defendant_name not in defendant_names:
            raise ApiError(
                "ERR_DEFENDANT_UNKNOWN",
                422,
                "defendant_name not in the ACCEPTED package's defendant_names",
            )
        if result == "SERVED" and defendant_name in case["served_defendant_names"]:
            raise ApiError(
                "ERR_DEFENDANT_ALREADY_SERVED",
                409,
                "Defendant already has a SERVED attempt on the case",
            )
        if served_at > db.now():
            raise ApiError(
                "ERR_DATE_IN_FUTURE", 422, "served_at must not be in the future"
            )
        att = db.new_ledger(
            {
                "case_id": cid,
                "defendant_name": defendant_name,
                "method": method,
                "result": result,
                "served_at": served_at,
                "server_user_id": _uid,
                "server_role": _role,
            }
        )
        STORE.service_attempts[att["id"]] = att
        if result == "SERVED":
            case["served_defendant_names"].append(defendant_name)
            if set(defendant_names) <= set(case["served_defendant_names"]):
                case["status"] = "SERVICE_COMPLETE"
                case["service_completed_at"] = served_at
            db.bump(case)
        return ok_object(ser.service_attempt(att), 201)


@bp.get("/api/cases/<cid>/service-attempts")
@auth({"Landlord", "CourtClerk", "ProcessServer", "SheriffDeputy", "PlatformAdmin"})
def list_service_attempts(cid, _uid, _role):
    with LOCK:
        get_case(cid)
        limit, offset = pagination()
        items = [
            a for a in db.sorted_items(STORE.service_attempts) if a["case_id"] == cid
        ]
        page = items[offset : offset + limit]
        return ok_list([ser.service_attempt(r) for r in page], len(items), limit, offset)
