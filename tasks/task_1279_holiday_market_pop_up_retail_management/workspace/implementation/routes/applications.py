"""VendorApplication endpoints: create/get/list, submit, score, decide,
withdraw (jury lifecycle per PRD 3.2-3.3)."""
from flask import Blueprint

import clock
import db
from errors import ApiError, invalid_state, posture_forbidden, validation
from middleware import auth, require_roles, require_vendor_owner
from response import success
from services import posture
from services.core import (
    BOOTH_TYPES,
    DECISIONS,
    arg,
    as_bool,
    as_enum,
    as_int,
    as_str,
    base_record,
    body,
    get_child,
    get_market,
    get_vendor,
    list_response,
    required,
    serialize,
    touch,
)

bp = Blueprint("applications", __name__)

VENDOR = ("VendorRole",)
GET_ONE = ("MarketOperator", "VendorRole", "JuryMember", "JuryChair")
GET_LIST = ("MarketOperator", "JuryMember", "JuryChair")


def _resolve(marketId, applicationId):
    get_market(marketId)
    return get_child("applications", applicationId, marketId)


def _category_of(app):
    vendor = db.STORES["vendors"].get(app["vendor_id"])
    return vendor["category"] if vendor else None


def _accepted_count(market_id, category):
    count = 0
    for app in db.STORES["applications"].values():
        if app["market_id"] != market_id or app["status"] != "ACCEPTED":
            continue
        if _category_of(app) == category:
            count += 1
    return count


@bp.post("/markets/<marketId>/applications")
def create_application(marketId):
    user = auth()
    require_roles(user, VENDOR)
    get_market(marketId)
    data = body()
    vendor_id = as_str(required(data, "vendor_id"), "vendor_id")
    get_vendor(vendor_id)
    require_vendor_owner(user, vendor_id)
    booth_type = as_enum(
        required(data, "requested_booth_type"), "requested_booth_type", BOOTH_TYPES
    )
    requested_pos = as_bool(data.get("requested_pos", False), "requested_pos")
    heating = as_bool(data.get("heating_requested", False), "heating_requested")
    rec = base_record()
    rec.update(
        {
            "market_id": marketId,
            "vendor_id": vendor_id,
            "requested_booth_type": booth_type,
            "requested_pos": requested_pos,
            "heating_requested": heating,
            "status": "DRAFT",
            "jury_scores": [],
            "jury_average": None,
            "decided_at": None,
        }
    )
    db.STORES["applications"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/markets/<marketId>/applications/<applicationId>")
def get_application(marketId, applicationId):
    user = auth()
    require_roles(user, GET_ONE)
    app = _resolve(marketId, applicationId)
    # PRD 2.1: a VendorRole caller may only read a resource whose vendor_id
    # foreign key equals X-User-ID.
    require_vendor_owner(user, app["vendor_id"])
    return success(serialize(app))


@bp.get("/markets/<marketId>/applications")
def list_applications(marketId):
    user = auth()
    require_roles(user, GET_LIST)
    get_market(marketId)
    status = arg("status")
    category = arg("category")
    vendor_id = arg("vendor_id")
    records = []
    for app in db.STORES["applications"].values():
        if app["market_id"] != marketId:
            continue
        if status is not None and app["status"] != status:
            continue
        if vendor_id is not None and app["vendor_id"] != vendor_id:
            continue
        if category is not None and _category_of(app) != category:
            continue
        records.append(app)
    return list_response(records)


@bp.post("/markets/<marketId>/applications/<applicationId>/submit")
def submit_application(marketId, applicationId):
    user = auth()
    require_roles(user, VENDOR)
    market = get_market(marketId)
    app = get_child("applications", applicationId, marketId)
    require_vendor_owner(user, app["vendor_id"])
    if posture.derive_posture(market) != "SETUP":
        raise posture_forbidden("applications may only be submitted while market is in SETUP")
    if app["status"] != "DRAFT":
        raise invalid_state("only a DRAFT application can be submitted")
    now = clock.now()
    if not (market["application_opens_at"] <= now <= market["application_closes_at"]):
        raise ApiError(
            "ERR_APPLICATION_WINDOW_CLOSED",
            "application submitted outside [application_opens_at, application_closes_at]",
            409,
        )
    app["status"] = "SUBMITTED"
    touch(app)
    return success(serialize(app))


@bp.post("/markets/<marketId>/applications/<applicationId>/score")
def score_application(marketId, applicationId):
    user = auth()
    require_roles(user, ("JuryMember",))
    market = get_market(marketId)
    app = get_child("applications", applicationId, marketId)
    data = body()
    score = as_int(required(data, "score_0_100"), "score_0_100")
    if score < 0 or score > 100:
        raise validation("score_0_100 must be between 0 and 100")
    if app["status"] == "SUBMITTED":
        if posture.derive_posture(market) != "SETUP":
            raise posture_forbidden("jury scoring requires SETUP posture")
    elif app["status"] == "UNDER_JURY":
        if any(s["juror_id"] == user.id for s in app["jury_scores"]):
            raise ApiError(
                "ERR_JURY_QUORUM_NOT_MET",
                "juror has already scored this application",
                409,
            )
        if len(app["jury_scores"]) >= 5:
            raise ApiError(
                "ERR_JURY_QUORUM_NOT_MET",
                "an application may hold at most 5 jury scores",
                409,
            )
    else:
        raise invalid_state("application is not open to jury scoring")
    app["jury_scores"].append({"juror_id": user.id, "score_0_100": score})
    app["jury_average"] = sum(s["score_0_100"] for s in app["jury_scores"]) / len(
        app["jury_scores"]
    )
    app["status"] = "UNDER_JURY"
    touch(app)
    return success(serialize(app))


@bp.post("/markets/<marketId>/applications/<applicationId>/decide")
def decide_application(marketId, applicationId):
    user = auth()
    require_roles(user, ("JuryChair",))
    market = get_market(marketId)
    app = get_child("applications", applicationId, marketId)
    data = body()
    expected = data.get("expected_application_version")
    if expected is not None and expected != app["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_application_version does not match the application's current version",
            412,
        )
    if app["status"] != "UNDER_JURY":
        raise invalid_state("only an UNDER_JURY application can be decided")
    decision = as_enum(required(data, "decision"), "decision", DECISIONS)
    category = _category_of(app)
    cap = market["category_caps"].get(category)
    accepted = _accepted_count(marketId, category)
    cap_reached = cap is not None and accepted >= cap
    # priority 10 (category cap) is evaluated before priority 11 (quorum)
    if decision == "ACCEPTED" and cap_reached:
        raise ApiError(
            "ERR_CATEGORY_CAP_REACHED",
            "acceptance would exceed market.category_caps[%s]" % category,
            409,
        )
    if len(app["jury_scores"]) < market["jury_quorum"]:
        raise ApiError(
            "ERR_JURY_QUORUM_NOT_MET",
            "decide requires at least jury_quorum scores",
            409,
        )
    avg = app["jury_average"]
    if decision == "ACCEPTED" and not (avg is not None and avg >= 60):
        raise invalid_state("ACCEPTED requires jury_average >= 60")
    if decision == "REJECTED" and not (avg is not None and avg < 60):
        raise invalid_state("REJECTED requires jury_average < 60")
    if decision == "WAITLISTED" and not (avg is not None and avg >= 60 and cap_reached):
        raise invalid_state("WAITLISTED requires jury_average >= 60 and category cap reached")
    app["status"] = decision
    app["decided_at"] = clock.now()
    touch(app)
    if decision == "ACCEPTED":
        vendor = db.STORES["vendors"].get(app["vendor_id"])
        if vendor is not None and vendor["status"] == "PROSPECT":
            vendor["status"] = "APPROVED"
            touch(vendor)
    return success(serialize(app))


@bp.post("/markets/<marketId>/applications/<applicationId>/withdraw")
def withdraw_application(marketId, applicationId):
    user = auth()
    require_roles(user, VENDOR)
    app = _resolve(marketId, applicationId)
    require_vendor_owner(user, app["vendor_id"])
    if app["status"] not in ("DRAFT", "SUBMITTED"):
        raise invalid_state("only a DRAFT or SUBMITTED application can be withdrawn")
    app["status"] = "WITHDRAWN"
    touch(app)
    return success(serialize(app))
