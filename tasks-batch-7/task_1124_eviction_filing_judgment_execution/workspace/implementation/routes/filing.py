from flask import Blueprint

import db
from db import LOCK, STORE
from errors import ApiError
from middleware import auth, require_owner
from response import ok_list, ok_object
from services import calc, serialize as ser
from services.resolution import get_case, get_package, jurisdiction_of_case
from utils import body_json, pagination, v_bool, v_enum, v_int, v_str

bp = Blueprint("filing", __name__)


def _validate_defendant_names(b):
    names = b.get("defendant_names")
    if (
        not isinstance(names, list)
        or not (1 <= len(names) <= 5)
        or any(not isinstance(n, str) or n == "" for n in names)
        or len(set(names)) != len(names)
    ):
        raise ApiError(
            "ERR_VALIDATION",
            400,
            "defendant_names must be 1..5 unique non-empty names",
        )
    return names


@bp.post("/api/cases/<cid>/filing-packages")
@auth({"Landlord"})
def create_package(cid, _uid, _role):
    with LOCK:
        case = get_case(cid)
        require_owner(_uid, case["landlord_id"])
        b = body_json()
        claimed = v_int(b, "claimed_amount_cents", min_exclusive=0)
        names = _validate_defendant_names(b)
        jury = v_bool(b, "jury_demanded")
        efiled = v_bool(b, "efiled")
        if case["status"] not in ("NOTICE_EXPIRED", "FILING_REJECTED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Filing package requires the notice period to have run (NOTICE_EXPIRED or FILING_REJECTED)",
            )
        jurisdiction = jurisdiction_of_case(case)
        fee = calc.filing_fee(jurisdiction, claimed, len(names), jury, efiled)
        r = db.new_record(
            {
                "case_id": cid,
                "claimed_amount_cents": claimed,
                "defendant_names": list(names),
                "jury_demanded": jury,
                "efiled": efiled,
                "filing_fee_cents": fee,
                "fee_paid_cents": 0,
                "fee_status": "UNPAID",
                "status": "DRAFT",
                "accepted_by_clerk_id": None,
                "accepted_at": None,
                "rejection_reason": None,
            }
        )
        STORE.packages[r["id"]] = r
        return ok_object(ser.package(r), 201)


@bp.get("/api/filing-packages/<pid>")
@auth({"Landlord", "CourtClerk", "PlatformAdmin"})
def read_package(pid, _uid, _role):
    with LOCK:
        return ok_object(ser.package(get_package(pid)))


@bp.get("/api/cases/<cid>/filing-packages")
@auth({"Landlord", "CourtClerk", "PlatformAdmin"})
def list_case_packages(cid, _uid, _role):
    with LOCK:
        get_case(cid)
        limit, offset = pagination()
        items = [p for p in db.sorted_items(STORE.packages) if p["case_id"] == cid]
        page = items[offset : offset + limit]
        return ok_list([ser.package(r) for r in page], len(items), limit, offset)


@bp.post("/api/filing-packages/<pid>/fee-payments")
@auth({"Landlord"})
def fee_payment(pid, _uid, _role):
    with LOCK:
        pkg = get_package(pid)
        case = STORE.cases[pkg["case_id"]]
        require_owner(_uid, case["landlord_id"])
        b = body_json()
        amount = v_int(b, "amount_cents", min_exclusive=0)
        if pkg["status"] != "DRAFT":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Fee payments require a DRAFT package"
            )
        if pkg["fee_paid_cents"] + amount > pkg["filing_fee_cents"]:
            raise ApiError(
                "ERR_FEE_OVERPAYMENT",
                422,
                "Fee payment would exceed computed filing_fee_cents",
            )
        pkg["fee_paid_cents"] += amount
        if pkg["fee_paid_cents"] == 0:
            pkg["fee_status"] = "UNPAID"
        elif pkg["fee_paid_cents"] < pkg["filing_fee_cents"]:
            pkg["fee_status"] = "PARTIAL"
        else:
            pkg["fee_status"] = "PAID"
        db.bump(pkg)
        return ok_object(ser.package(pkg))


@bp.post("/api/filing-packages/<pid>/review")
@auth({"CourtClerk"})
def review_package(pid, _uid, _role):
    with LOCK:
        pkg = get_package(pid)
        b = body_json()
        decision = v_enum(b, "decision", {"ACCEPT", "REJECT"})
        rejection_reason = v_str(b, "rejection_reason", required=False)
        case = STORE.cases[pkg["case_id"]]
        if pkg["status"] != "DRAFT":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Package is not DRAFT"
            )
        if case["status"] not in ("NOTICE_EXPIRED", "FILING_REJECTED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Case status does not permit filing review",
            )
        if pkg["fee_status"] != "PAID":
            raise ApiError(
                "ERR_FEE_UNPAID", 422, "Review requires fee_status == PAID"
            )
        if decision == "ACCEPT":
            pkg["status"] = "ACCEPTED"
            pkg["accepted_by_clerk_id"] = _uid
            pkg["accepted_at"] = db.now()
            db.bump(pkg)
            case["status"] = "FILED"
            db.bump(case)
        else:
            pkg["status"] = "REJECTED"
            pkg["rejection_reason"] = rejection_reason
            db.bump(pkg)
            case["status"] = "FILING_REJECTED"
            db.bump(case)
        return ok_object(ser.package(pkg))
