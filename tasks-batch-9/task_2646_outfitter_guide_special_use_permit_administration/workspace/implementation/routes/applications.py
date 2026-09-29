"""Permit applications: intake, the capacity screen and issuance (PRD 3.2 / 3.4)."""
from flask import Blueprint

import calc
import envelope
import security
import serialize
import shapes
import store
from errors import ApiError
from routes.common import match, qint, qstr
from security import ADMIN, ANY_ROLE, OFFICER, REPRESENTATIVE, SPECIALIST

bp = Blueprint("applications", __name__)

APPLICATION_TYPES = ("NEW", "RENEWAL")
ACTIVITY_TYPES = ("HUNTING", "FISHING", "PACK_STOCK", "RIVER_FLOAT", "MOUNTAINEERING")
FEE_SCHEDULES = ("GRADUATED", "FLAT_THREE_PERCENT")
PRE_AWARD_DENY = (
    "SUBMITTED",
    "CAPACITY_SCREENED",
    "DIRECT_AWARD_PENDING",
    "PROSPECTUS_QUEUED",
    "PROSPECTUS_RESPONDED",
)
PRE_AWARD_WITHDRAW = ("DRAFT",) + PRE_AWARD_DENY
PRIORITY_RATINGS = ("SUPERIOR", "SATISFACTORY")
DIRECT_HOLD_DAYS = 30


def _resolve_optional(table, value, error_id):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return store.get_or_404(table, value, error_id)


def _check_succession(app_type, predecessor, outfitter_id, use_area_id):
    """PRD 3.2 / 3.9 -- ERR_SUCCESSION_PREDECESSOR_INVALID at draft and at screen."""
    if app_type == "RENEWAL":
        if predecessor is None:
            raise ApiError(
                "ERR_SUCCESSION_PREDECESSOR_INVALID", "a renewal needs a predecessor"
            )
        if (
            predecessor["outfitter_id"] != outfitter_id
            or predecessor["use_area_id"] != use_area_id
            or predecessor["administrative_status"]
            not in ("ACTIVE", "SUSPENDED", "EXPIRED")
        ):
            raise ApiError(
                "ERR_SUCCESSION_PREDECESSOR_INVALID", "predecessor permit is not eligible"
            )
    elif predecessor is not None:
        raise ApiError(
            "ERR_SUCCESSION_PREDECESSOR_INVALID",
            "a new application must not name a predecessor",
        )


@bp.post("/osup/permit-applications")
def draft_application():
    caller = security.authenticate((REPRESENTATIVE, SPECIALIST))
    data = shapes.body()
    # priority 3: body ids resolve in the order the endpoint declares them
    outfitter = _resolve_optional(
        "outfitters", data.get("outfitter_id"), "ERR_OUTFITTER_NOT_FOUND"
    )
    area = _resolve_optional(
        "use_areas", data.get("use_area_id"), "ERR_USE_AREA_NOT_FOUND"
    )
    prospectus = _resolve_optional(
        "prospectuses", data.get("prospectus_id"), "ERR_PROSPECTUS_NOT_FOUND"
    )
    predecessor = _resolve_optional(
        "permits", data.get("predecessor_permit_id"), "ERR_PERMIT_NOT_FOUND"
    )
    # priority 4: ownership on the supplied outfitter_id
    if outfitter is not None:
        security.require_owner(caller, outfitter["id"])
    # priority 5: request shape
    outfitter_id = shapes.req_id(data, "outfitter_id")
    use_area_id = shapes.req_id(data, "use_area_id")
    app_type = shapes.req_str(data, "application_type", allowed=APPLICATION_TYPES)
    season_year = shapes.req_int(data, "season_year", minimum=1900, maximum=9999)
    requested = shapes.req_int(data, "requested_service_days", minimum=1, maximum=3650)
    activity = shapes.req_str(data, "proposed_activity_type", allowed=ACTIVITY_TYPES)
    narrative = shapes.opt_str(data, "narrative")
    if outfitter is None:
        store.get_or_404("outfitters", outfitter_id, "ERR_OUTFITTER_NOT_FOUND")
    if area is None:
        store.get_or_404("use_areas", use_area_id, "ERR_USE_AREA_NOT_FOUND")
    security.require_owner(caller, outfitter_id)
    # priority 9: succession
    _check_succession(app_type, predecessor, outfitter_id, use_area_id)

    app = store.insert(
        "applications",
        {
            "outfitter_id": outfitter_id,
            "use_area_id": use_area_id,
            "prospectus_id": prospectus["id"] if prospectus else None,
            "predecessor_permit_id": predecessor["id"] if predecessor else None,
            "application_type": app_type,
            "season_year": season_year,
            "requested_service_days": requested,
            "proposed_activity_type": activity,
            "narrative": narrative,
            "status": "DRAFT",
            "routing_decision": None,
            "hold_expires_at": None,
            "preliminary_evaluation_score": None,
            "final_evaluation_score": None,
            "denial_reason_code": None,
            "screened_at": None,
        },
    )
    return envelope.ok(serialize.application(app), 201)


@bp.get("/osup/permit-applications/<app_id>")
def read_application(app_id):
    security.authenticate(ANY_ROLE, mutating=False)
    app = store.get_or_404("applications", app_id, "ERR_APPLICATION_NOT_FOUND")
    return envelope.ok(serialize.application(app))


@bp.get("/osup/permit-applications")
def list_applications():
    security.authenticate(ANY_ROLE, mutating=False)
    filters = {
        "outfitter_id": qstr("outfitter_id"),
        "use_area_id": qstr("use_area_id"),
        "prospectus_id": qstr("prospectus_id"),
        "predecessor_permit_id": qstr("predecessor_permit_id"),
        "status": qstr("status"),
        "season_year": qint("season_year"),
        "application_type": qstr("application_type"),
        "routing_decision": qstr("routing_decision"),
    }
    rows = [a for a in store.all_of("applications") if match(a, **filters)]
    return envelope.paginate(store.sort_created(rows), serialize.application)


@bp.post("/osup/permit-applications/<app_id>/submit")
def submit_application(app_id):
    caller = security.authenticate((REPRESENTATIVE,))
    app = store.get_or_404("applications", app_id, "ERR_APPLICATION_NOT_FOUND")
    security.require_owner(caller, app["outfitter_id"])
    if app["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_APPLICATION_STATE", "application is not DRAFT")
    outfitter = store.get("outfitters", app["outfitter_id"])
    if outfitter is not None and outfitter["status"] == "SUSPENDED":
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE", "a suspended outfitter may not file"
        )
    predecessor = store.get("permits", app.get("predecessor_permit_id"))
    _check_succession(
        app["application_type"], predecessor, app["outfitter_id"], app["use_area_id"]
    )
    app["status"] = "SUBMITTED"
    store.touch(app)
    return envelope.ok(serialize.application(app))


@bp.post("/osup/permit-applications/<app_id>/screen")
def screen_application(app_id):
    security.authenticate((SPECIALIST,))
    app = store.get_or_404("applications", app_id, "ERR_APPLICATION_NOT_FOUND")
    if app["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_APPLICATION_STATE", "application is not SUBMITTED")
    area = store.get("use_areas", app["use_area_id"])
    assessment = calc.published_assessment(app["use_area_id"], app["season_year"])
    if assessment is None:
        raise ApiError(
            "ERR_NEEDS_ASSESSMENT_NOT_PUBLISHED",
            "no published needs assessment for this area and season year",
        )
    if assessment["public_need_finding"] != "NEED_EXISTS":
        raise ApiError("ERR_NO_PUBLIC_NEED", "the governing finding is NO_NEED")
    predecessor = store.get("permits", app.get("predecessor_permit_id"))
    _check_succession(
        app["application_type"], predecessor, app["outfitter_id"], app["use_area_id"]
    )

    # the routing rule reads the remainder BEFORE this application's own hold lands
    pre_hold_available = calc.area_ledger(area)["available_service_days"]
    if app["application_type"] == "RENEWAL":
        direct = (
            predecessor is not None
            and predecessor["compliance_status"] == "COMPLIANT"
            and predecessor.get("latest_performance_rating") in PRIORITY_RATINGS
            and app["requested_service_days"] <= predecessor["authorized_service_days"]
        )
    else:
        direct = app["requested_service_days"] <= pre_hold_available

    screened_at = store.now_dt()
    app["screened_at"] = store.fmt_dt(screened_at)
    app["routing_decision"] = "DIRECT" if direct else "PROSPECTUS"
    app["status"] = "CAPACITY_SCREENED"
    if direct:
        app["status"] = "DIRECT_AWARD_PENDING"
        app["hold_expires_at"] = store.fmt_dt(
            store.plus_days(screened_at, DIRECT_HOLD_DAYS)
        )
    else:
        app["status"] = "PROSPECTUS_QUEUED"
        app["hold_expires_at"] = None
    store.touch(app)

    calc.recompute_area(area)
    if area["available_service_days"] < 0:
        for sibling in store.all_of("applications"):
            if (
                sibling["id"] != app["id"]
                and sibling["use_area_id"] == area["id"]
                and sibling["status"] == "DIRECT_AWARD_PENDING"
            ):
                sibling["status"] = "PROSPECTUS_QUEUED"
                sibling["hold_expires_at"] = None
                sibling["routing_decision"] = "PROSPECTUS"
                store.touch(sibling)
    governing = calc.recompute_governing_assessment(area["id"], app["season_year"])
    if governing is not None and not direct:
        governing["prospectus_required"] = True
    return envelope.ok(serialize.application(app))


@bp.post("/osup/permit-applications/<app_id>/deny")
def deny_application(app_id):
    security.authenticate((OFFICER, ADMIN))
    app = store.get_or_404("applications", app_id, "ERR_APPLICATION_NOT_FOUND")
    data = shapes.body()
    reason = shapes.req_str(data, "denial_reason_code")
    if app["status"] not in PRE_AWARD_DENY:
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE", "application cannot be denied from here"
        )
    was_holding = app["status"] in calc.HOLDING_APPLICATION_STATUSES
    app["status"] = "DENIED"
    app["denial_reason_code"] = reason
    store.touch(app)
    if was_holding:
        area = store.get("use_areas", app["use_area_id"])
        calc.recompute_area(area)
        calc.recompute_governing_assessment(area["id"], app["season_year"])
    return envelope.ok(serialize.application(app))


@bp.post("/osup/permit-applications/<app_id>/withdraw")
def withdraw_application(app_id):
    caller = security.authenticate((REPRESENTATIVE,))
    app = store.get_or_404("applications", app_id, "ERR_APPLICATION_NOT_FOUND")
    security.require_owner(caller, app["outfitter_id"])
    if app["status"] not in PRE_AWARD_WITHDRAW:
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE", "application cannot be withdrawn from here"
        )
    was_holding = app["status"] in calc.HOLDING_APPLICATION_STATUSES
    app["status"] = "WITHDRAWN"
    store.touch(app)
    if was_holding:
        area = store.get("use_areas", app["use_area_id"])
        calc.recompute_area(area)
        calc.recompute_governing_assessment(area["id"], app["season_year"])
    return envelope.ok(serialize.application(app))


def term_buffer_conflict(outfitter_id, use_area_id, start, end, exclude_permit_id=None):
    """PRD 3.4 -- at least 14 clear days from any other held permit's term."""
    for other in store.all_of("permits"):
        if (
            other["id"] == exclude_permit_id
            or other["outfitter_id"] != outfitter_id
            or other["use_area_id"] != use_area_id
            or other["administrative_status"] not in calc.COMMITTING_PERMIT_STATUSES
        ):
            continue
        o_start = store.as_date(other["term_start_date"])
        o_end = store.as_date(other["term_end_date"])
        if start > o_end:
            clear = (start - o_end).days - 1
        elif end < o_start:
            clear = (o_start - end).days - 1
        else:
            return True
        if clear < calc.PERMIT_TERM_BUFFER_DAYS:
            return True
    return False


def new_permit_record(fields):
    permit = store.insert(
        "permits",
        dict(
            {
                "predecessor_permit_id": None,
                "administrative_status": "ISSUED",
                "compliance_status": "COMPLIANT",
                "open_noncompliance_points": 0,
                "insurance_current": False,
                "bond_current": False,
                "fee_delinquent": False,
                "authorized_client_capacity_total": 0,
                "service_days_used_ytd": 0,
                "suspension_count": 0,
                "suspended_until_date": None,
                "suspension_reason_code": None,
                "revocation_reason_code": None,
                "latest_performance_rating": None,
            },
            **fields
        ),
    )
    return permit


@bp.post("/osup/permit-applications/<app_id>/issue-permit")
def issue_permit(app_id):
    security.authenticate((OFFICER, ADMIN))
    app = store.get_or_404("applications", app_id, "ERR_APPLICATION_NOT_FOUND")
    data = shapes.body()
    term_start = shapes.req_date(data, "term_start_date")
    term_end = shapes.req_date(data, "term_end_date")
    schedule = shapes.opt_str(
        data, "fee_schedule_code", allowed=FEE_SCHEDULES, default="GRADUATED"
    )
    acknowledged = shapes.opt_bool(data, "indemnification_acknowledged", default=False)
    start_date = store.as_date(term_start)
    end_date = store.as_date(term_end)
    if end_date <= start_date:
        shapes.bad("term_end_date", "must be strictly after term_start_date")

    if app["status"] not in ("DIRECT_AWARD_PENDING", "AWARDED"):
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE", "application is not award-ready"
        )
    prospectus = store.get("prospectuses", app.get("prospectus_id"))
    if prospectus is not None:
        if (
            prospectus["status"] != "AWARDED"
            or prospectus.get("awarded_application_id") != app["id"]
        ):
            raise ApiError(
                "ERR_INVALID_APPLICATION_STATE",
                "the solicitation has not awarded this application",
            )
        authorized = min(
            app["requested_service_days"], prospectus["offered_service_days"]
        )
    else:
        authorized = app["requested_service_days"]

    area = store.get("use_areas", app["use_area_id"])
    # priority 10: the 14-clear-day term buffer
    if term_buffer_conflict(app["outfitter_id"], area["id"], start_date, end_date):
        raise ApiError(
            "ERR_PERMIT_TERM_CONFLICT", "term is within 14 days of another permit"
        )
    # priority 12: area capacity, then the predecessor's outstanding balance
    led = calc.area_ledger(area)
    if led["available_service_days"] + app["requested_service_days"] < authorized:
        raise ApiError(
            "ERR_INSUFFICIENT_SERVICE_DAYS", "the area cannot cover the authorization"
        )
    predecessor = store.get("permits", app.get("predecessor_permit_id"))
    if predecessor is not None and calc.permit_has_outstanding_balance(predecessor["id"]):
        raise ApiError(
            "ERR_FEE_BALANCE_OUTSTANDING", "the predecessor permit still owes money"
        )

    permit = new_permit_record(
        {
            "outfitter_id": app["outfitter_id"],
            "use_area_id": app["use_area_id"],
            "application_id": app["id"],
            "predecessor_permit_id": predecessor["id"] if predecessor else None,
            "authorized_service_days": authorized,
            "term_start_date": term_start,
            "term_end_date": term_end,
            "fee_schedule_code": schedule,
            "indemnification_acknowledged": acknowledged,
        }
    )
    calc.recompute_permit_signals(permit)
    app["status"] = "PERMIT_ISSUED"
    store.touch(app)
    calc.recompute_area(area)
    calc.recompute_governing_assessment(area["id"], app["season_year"])
    calc.derive_outfitter(app["outfitter_id"])
    return envelope.ok(serialize.permit(permit), 201)
