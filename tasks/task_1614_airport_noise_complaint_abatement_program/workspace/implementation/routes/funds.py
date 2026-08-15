"""Insulation funds and sound insulation applications (PRD §3.8)."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

from db import db, new_id
from errors import err
from middleware import get_caller, require_role, get_body
from response import success_object, success_list
from serialize import ser_fund, ser_application
import services
from services import (touch, obligation_split, active_fund, fund_available,
                      issue_offer, release_reservation, sweep_offer_expiry,
                      priority_score)
from util import now
from validate import validate, parse_pagination

bp = Blueprint("funds", __name__)

STAFF = ["NoiseOfficeAdmin", "NoiseAnalyst", "CommunityLiaison",
         "StudyCoordinator", "BoardMember"]

DWELLING_TYPES = ["SINGLE_FAMILY", "MULTI_FAMILY", "MOBILE_HOME"]
DECISIONS = ["ELIGIBLE_TIER1", "ELIGIBLE_TIER2", "INELIGIBLE"]
ACTIVE_APP_STATES = {"NEW", "SUBMITTED", "SCREENING", "ELIGIBLE_TIER1",
                     "ELIGIBLE_TIER2", "APPEALED"}
_FAR_FUTURE = datetime(9999, 1, 1, tzinfo=timezone.utc)


def _get_fund(fid):
    f = db.funds.get(fid)
    if f is None:
        raise err("ERR_NOT_FOUND", f"InsulationFund {fid} not found")
    return f


def _get_application(aid):
    a = db.applications.get(aid)
    if a is None:
        raise err("ERR_NOT_FOUND", f"SoundInsulationApplication {aid} not found")
    return a


# ------------------------------ funds --------------------------------------

@bp.post("/insulation-funds")
def create_fund():
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("fiscal_year", "str", True),
        ("total_allocation_cents", "int", True, {"min": 1}),
        ("intake_opens_at", "dt", True),
        ("intake_closes_at", "dt", True),
    ])
    if data["intake_closes_at"] <= data["intake_opens_at"]:
        raise err("ERR_VALIDATION",
                  "intake_closes_at must be strictly after intake_opens_at")
    require_role(caller, ["NoiseOfficeAdmin"])
    for f in db.funds.values():
        if f["fiscal_year"] == data["fiscal_year"]:
            raise err("ERR_DUPLICATE_FISCAL_YEAR_FUND",
                      f"A fund for {data['fiscal_year']} already exists")
    if active_fund() is not None:
        raise err("ERR_ACTIVE_FUND_EXISTS",
                  "An ACTIVE fund already exists; close it first")
    t = now()
    f = {
        "id": new_id(),
        "fiscal_year": data["fiscal_year"],
        "total_allocation_cents": data["total_allocation_cents"],
        "intake_opens_at": data["intake_opens_at"],
        "intake_closes_at": data["intake_closes_at"],
        "status": "ACTIVE",
        "reserved_cents": 0,
        "disbursed_cents": 0,
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }
    db.funds[f["id"]] = f
    return success_object(ser_fund(f), status=201)


@bp.get("/insulation-funds")
def list_funds():
    caller = get_caller()
    require_role(caller, STAFF)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = sorted(db.funds.values(), key=lambda f: f["created_at"])
    if status is not None:
        items = [f for f in items if f["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_fund(f) for f in page], limit, offset, total)


@bp.get("/insulation-funds/<fundId>")
def get_fund(fundId):
    caller = get_caller()
    require_role(caller, STAFF)
    f = _get_fund(fundId)
    return success_object(ser_fund(f))


@bp.post("/insulation-funds/<fundId>/allocate")
def allocate(fundId):
    caller = get_caller()
    get_body()
    require_role(caller, ["NoiseOfficeAdmin"])
    f = _get_fund(fundId)
    if f["status"] != "ACTIVE":
        raise err("ERR_INVALID_FUND_STATE",
                  "allocate requires an ACTIVE fund")
    candidates = [a for a in db.applications.values()
                  if a["funding_status"] == "UNFUNDED"
                  and a["eligibility_status"] in ("ELIGIBLE_TIER1", "ELIGIBLE_TIER2")]
    candidates.sort(key=lambda a: (-a["priority_score"],
                                   a.get("submitted_at") or _FAR_FUTURE,
                                   a["created_at"]))
    offers_issued = 0
    total_reserved = 0
    skipped = []
    for a in candidates:
        _, _, _, obligation = obligation_split(
            a["est_cost_cents"], a["eligibility_status"])
        avail = fund_available(f)
        if avail >= obligation:
            total_reserved += issue_offer(a, f)
            offers_issued += 1
        elif avail * 2 >= obligation:
            # partial offer: the entire remaining availability is reserved
            total_reserved += issue_offer(a, f)
            offers_issued += 1
        else:
            skipped.append(a["id"])
    return success_object({
        "offers_issued": offers_issued,
        "total_reserved_cents": total_reserved,
        "skipped_application_ids": skipped,
    })


@bp.post("/insulation-funds/<fundId>/close")
def close_fund(fundId):
    caller = get_caller()
    get_body()
    require_role(caller, ["NoiseOfficeAdmin"])
    f = _get_fund(fundId)
    if f["status"] != "ACTIVE":
        raise err("ERR_INVALID_FUND_STATE", "close requires an ACTIVE fund")
    if f["reserved_cents"] != 0:
        raise err("ERR_FUND_HAS_RESERVED",
                  "Fund has outstanding reservations")
    f["status"] = "CLOSED"
    touch(f)
    return success_object(ser_fund(f))


# --------------------------- applications ----------------------------------

@bp.post("/sound-insulation-applications")
def create_application():
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("parcel_id", "str", True),
        ("complainant_id", "str", False),
        ("dwelling_type", "enum", True, {"enum": DWELLING_TYPES}),
        ("rooms_count", "int", True, {"min": 1}),
        ("est_cost_cents", "int", True, {"min": 1}),
    ])
    require_role(caller, ["CommunityLiaison"])
    parcel = db.parcels.get(data["parcel_id"])
    if parcel is None:
        raise err("ERR_PARCEL_NOT_FOUND",
                  f"LandUseParcel {data['parcel_id']} not found")
    complainant = None
    if data.get("complainant_id") is not None:
        complainant = db.complainants.get(data["complainant_id"])
        if complainant is None:
            raise err("ERR_COMPLAINANT_NOT_FOUND",
                      f"Complainant {data['complainant_id']} not found")
    # gate 11: one active application per parcel
    for a in db.applications.values():
        if a["parcel_id"] == parcel["id"] and a["eligibility_status"] in ACTIVE_APP_STATES:
            raise err("ERR_ACTIVE_APPLICATION_EXISTS",
                      "An active application already exists for this parcel")
    # gate 12: parcel eligibility
    if not parcel["insulation_eligible"]:
        raise err("ERR_PARCEL_NOT_INCOMPATIBLE",
                  "Parcel is not insulation-eligible")
    t = now()
    a = {
        "id": new_id(),
        "parcel_id": parcel["id"],
        "complainant_id": complainant["id"] if complainant else None,
        "dwelling_type": data["dwelling_type"],
        "rooms_count": data["rooms_count"],
        "est_cost_cents": data["est_cost_cents"],
        "actual_cost_cents": None,
        "eligibility_status": "NEW",
        "funding_status": "UNFUNDED",
        "fund_id": None,
        "priority_score": 0,
        "tier_cap_cents": 0,
        "offered_amount_cents": None,
        "offer_issued_at": None,
        "offer_expires_at": None,
        "last_offer_expired_at": None,
        "disbursed_cents": None,
        "appeal_count": 0,
        "submitted_at": None,
        "decided_at": None,
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }
    db.applications[a["id"]] = a
    return success_object(ser_application(a), status=201)


@bp.get("/sound-insulation-applications")
def list_applications():
    caller = get_caller()
    require_role(caller, STAFF)
    limit, offset = parse_pagination(request.args)
    f_parcel = request.args.get("parcel_id")
    f_complainant = request.args.get("complainant_id")
    f_fund = request.args.get("fund_id")
    f_elig = request.args.get("eligibility_status")
    f_funding = request.args.get("funding_status")
    items = sorted(db.applications.values(), key=lambda a: a["created_at"])
    # lazy offer-expiry sweep fires on read
    for a in items:
        sweep_offer_expiry(a)
    if f_parcel is not None:
        items = [a for a in items if a["parcel_id"] == f_parcel]
    if f_complainant is not None:
        items = [a for a in items if a.get("complainant_id") == f_complainant]
    if f_fund is not None:
        items = [a for a in items if a.get("fund_id") == f_fund]
    if f_elig is not None:
        items = [a for a in items if a["eligibility_status"] == f_elig]
    if f_funding is not None:
        items = [a for a in items if a["funding_status"] == f_funding]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_application(a) for a in page], limit, offset, total)


@bp.get("/sound-insulation-applications/<applicationId>")
def get_application(applicationId):
    caller = get_caller()
    require_role(caller, STAFF)
    a = _get_application(applicationId)
    sweep_offer_expiry(a)
    return success_object(ser_application(a))


@bp.post("/sound-insulation-applications/<applicationId>/submit")
def submit_application(applicationId):
    caller = get_caller()
    get_body()
    require_role(caller, ["CommunityLiaison"])
    a = _get_application(applicationId)
    if a["eligibility_status"] != "NEW":
        raise err("ERR_INVALID_APPLICATION_STATE",
                  "submit requires eligibility_status NEW")
    f = active_fund()
    t = now()
    if f is None or not (f["intake_opens_at"] <= t < f["intake_closes_at"]):
        raise err("ERR_SUBMISSION_WINDOW_CLOSED",
                  "No ACTIVE fund intake window covers the current time")
    a["eligibility_status"] = "SUBMITTED"
    a["submitted_at"] = t
    touch(a)
    return success_object(ser_application(a))


@bp.post("/sound-insulation-applications/<applicationId>/begin-screening")
def begin_screening_app(applicationId):
    caller = get_caller()
    get_body()
    require_role(caller, ["StudyCoordinator"])
    a = _get_application(applicationId)
    if a["eligibility_status"] not in ("SUBMITTED", "APPEALED"):
        raise err("ERR_INVALID_APPLICATION_STATE",
                  "begin-screening requires SUBMITTED or APPEALED")
    a["eligibility_status"] = "SCREENING"
    touch(a)
    return success_object(ser_application(a))


@bp.post("/sound-insulation-applications/<applicationId>/record-decision")
def record_decision(applicationId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [("decision", "enum", True, {"enum": DECISIONS})])
    require_role(caller, ["StudyCoordinator"])
    a = _get_application(applicationId)
    if a["eligibility_status"] != "SCREENING":
        raise err("ERR_INVALID_APPLICATION_STATE",
                  "record-decision requires SCREENING")
    decision = data["decision"]
    parcel = db.parcels.get(a["parcel_id"])
    if decision == "ELIGIBLE_TIER1":
        ok = (parcel is not None and
              (parcel["dnl_db_effective"] >= 70.0
               or parcel["land_use"] in ("SCHOOL", "HOSPITAL")))
        if not ok:
            raise err("ERR_TIER_NOT_PERMITTED",
                      "TIER1 requires dnl_db_effective >= 70.0 or SCHOOL/HOSPITAL use")
    a["eligibility_status"] = decision
    a["decided_at"] = now()
    if decision in ("ELIGIBLE_TIER1", "ELIGIBLE_TIER2"):
        a["priority_score"] = priority_score(a)
        a["tier_cap_cents"] = services.TIER1_CAP if decision == "ELIGIBLE_TIER1" \
            else services.TIER2_CAP
    touch(a)
    return success_object(ser_application(a))


@bp.post("/sound-insulation-applications/<applicationId>/appeal")
def appeal(applicationId):
    caller = get_caller()
    body = get_body()
    validate(body, [("reason", "str", True)])
    require_role(caller, ["CommunityLiaison"])
    a = _get_application(applicationId)
    if a["eligibility_status"] != "INELIGIBLE":
        raise err("ERR_INVALID_APPLICATION_STATE",
                  "appeal requires eligibility_status INELIGIBLE")
    if now() > a["decided_at"] + timedelta(days=30):
        raise err("ERR_APPEAL_WINDOW_EXPIRED",
                  "Appeal window (30 days from decided_at) has expired")
    if a["appeal_count"] >= 2:
        raise err("ERR_APPEAL_LIMIT_REACHED",
                  "Application has already been appealed twice")
    a["appeal_count"] += 1
    a["eligibility_status"] = "APPEALED"
    touch(a)
    return success_object(ser_application(a))


@bp.post("/sound-insulation-applications/<applicationId>/issue-offer")
def issue_offer_endpoint(applicationId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [("expected_fund_version", "int", True)])
    require_role(caller, ["NoiseOfficeAdmin"])
    a = _get_application(applicationId)
    # gate 8: state (both dimensions) + OCC against the active fund
    if a["funding_status"] != "UNFUNDED" or \
            a["eligibility_status"] not in ("ELIGIBLE_TIER1", "ELIGIBLE_TIER2"):
        raise err("ERR_INVALID_APPLICATION_STATE",
                  "issue-offer requires UNFUNDED funding and an eligible tier")
    f = active_fund()
    if f is not None and data["expected_fund_version"] != f["version"]:
        raise err("ERR_STALE_FUND_VERSION",
                  "expected_fund_version does not match the fund version")
    # gate 12: the parcel's study must be ADOPTED
    parcel = db.parcels.get(a["parcel_id"])
    study = db.studies.get(parcel["study_id"]) if parcel is not None else None
    if study is None or study["status"] != "ADOPTED":
        raise err("ERR_STUDY_NOT_ADOPTED",
                  "The parcel's study must be ADOPTED")
    # gate 13: fiscal guards
    if f is None:
        raise err("ERR_NO_ACTIVE_FUND", "No ACTIVE InsulationFund exists")
    _, _, _, obligation = obligation_split(a["est_cost_cents"],
                                           a["eligibility_status"])
    if fund_available(f) * 2 < obligation:
        raise err("ERR_INSUFFICIENT_FUNDS",
                  "Available funds cover less than half the provisional obligation")
    issue_offer(a, f)
    return success_object(ser_application(a))


@bp.post("/sound-insulation-applications/<applicationId>/accept-offer")
def accept_offer(applicationId):
    caller = get_caller()
    get_body()
    require_role(caller, ["CommunityLiaison"])
    a = _get_application(applicationId)
    if a["funding_status"] != "OFFER_ISSUED":
        raise err("ERR_INVALID_APPLICATION_STATE",
                  "accept-offer requires funding_status OFFER_ISSUED")
    # expiry is evaluated lazily on READ only; a write on an expired-but-unswept
    # offer deterministically fails
    if now() >= a["offer_expires_at"]:
        raise err("ERR_OFFER_EXPIRED", "The offer has expired")
    a["funding_status"] = "GRANT_COMMITTED"
    touch(a)
    return success_object(ser_application(a))


@bp.post("/sound-insulation-applications/<applicationId>/decline-offer")
def decline_offer(applicationId):
    caller = get_caller()
    get_body()
    require_role(caller, ["CommunityLiaison"])
    a = _get_application(applicationId)
    if a["funding_status"] != "OFFER_ISSUED":
        raise err("ERR_INVALID_APPLICATION_STATE",
                  "decline-offer requires funding_status OFFER_ISSUED")
    release_reservation(a)
    # OFFER_DECLINED -> immediate re-queue to UNFUNDED within the same request
    a["funding_status"] = "UNFUNDED"
    touch(a)
    return success_object(ser_application(a))


@bp.post("/sound-insulation-applications/<applicationId>/disburse")
def disburse(applicationId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [("actual_cost_cents", "int", True, {"min": 1})])
    require_role(caller, ["NoiseOfficeAdmin"])
    a = _get_application(applicationId)
    if a["funding_status"] != "GRANT_COMMITTED":
        raise err("ERR_INVALID_APPLICATION_STATE",
                  "disburse requires funding_status GRANT_COMMITTED")
    _, _, _, final_total = obligation_split(data["actual_cost_cents"],
                                            a["eligibility_status"])
    fund = db.funds.get(a.get("fund_id") or "")
    provisional = a.get("offered_amount_cents") or 0
    if fund is not None:
        fund["reserved_cents"] -= provisional
        fund["disbursed_cents"] += final_total
        touch(fund)
    a["actual_cost_cents"] = data["actual_cost_cents"]
    a["disbursed_cents"] = final_total
    a["offered_amount_cents"] = None
    a["funding_status"] = "REIMBURSED"
    touch(a)
    return success_object(ser_application(a))


@bp.post("/sound-insulation-applications/<applicationId>/withdraw")
def withdraw_application(applicationId):
    caller = get_caller()
    get_body()
    require_role(caller, ["CommunityLiaison"])
    a = _get_application(applicationId)
    if a["eligibility_status"] == "WITHDRAWN":
        raise err("ERR_INVALID_APPLICATION_STATE",
                  "Application is already WITHDRAWN")
    if a["funding_status"] in ("OFFER_ISSUED", "GRANT_COMMITTED"):
        release_reservation(a)
        a["funding_status"] = "UNFUNDED"
    a["eligibility_status"] = "WITHDRAWN"
    touch(a)
    return success_object(ser_application(a))
