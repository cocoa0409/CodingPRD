"""Market-rate assessment + baseball arbitration endpoints (§3.6)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_ASSESSMENT_SHAPE, ERR_STALE_VERSION,
    ERR_INVALID_STATE, ERR_DISPUTE_WINDOW_CLOSED, ERR_NOT_FOUND,
)
from middleware import authorized, READ_ROLES
from response import success_object
from services.core import (
    new_record, touch, refresh, public, option_assessments, assessment_case,
    compute_fair_market_rent, try_complete_exercise, post_ledger,
)
from routes.helpers import resolve_option, resolve_assessment, paged
from util import CLOCK, fmt_date_midnight
from validate import get_body, req_int, req_enum

bp = Blueprint("assessments", __name__)

METHODS = ["COMPARABLE_AVERAGE", "PSF_REGRESSION"]


def _check_assessment_shape(body, method):
    """Priority 12: comparable set shape / regression inputs coherence."""
    comparables = body.get("comparable_rents_cents")
    base = body.get("regression_base_cents")
    adjustments = body.get("regression_adjustments")
    if method == "COMPARABLE_AVERAGE":
        if comparables is not None:
            if not isinstance(comparables, list):
                raise_error(ERR_VALIDATION, "comparable_rents_cents must be an array")
            for item in comparables:
                if isinstance(item, bool) or not isinstance(item, int):
                    raise_error(ERR_VALIDATION, "comparable_rents_cents entries must be integers")
        if (not comparables or len(comparables) < 3 or len(comparables) > 7
                or any(c <= 0 for c in comparables)):
            raise_error(ERR_ASSESSMENT_SHAPE,
                        "COMPARABLE_AVERAGE requires 3..7 positive comparable_rents_cents")
        if base is not None or adjustments is not None:
            raise_error(ERR_ASSESSMENT_SHAPE,
                        "regression inputs are forbidden on a COMPARABLE_AVERAGE assessment")
        return list(comparables), None, None
    # PSF_REGRESSION
    if base is not None and (isinstance(base, bool) or not isinstance(base, int)):
        raise_error(ERR_VALIDATION, "regression_base_cents must be an integer")
    if base is None or base <= 0:
        raise_error(ERR_ASSESSMENT_SHAPE,
                    "PSF_REGRESSION requires regression_base_cents > 0")
    if adjustments is not None:
        if not isinstance(adjustments, list):
            raise_error(ERR_VALIDATION, "regression_adjustments must be an array")
        for item in adjustments:
            if isinstance(item, bool) or not isinstance(item, int):
                raise_error(ERR_VALIDATION, "regression_adjustments entries must be integers")
    if comparables is not None:
        raise_error(ERR_ASSESSMENT_SHAPE,
                    "comparable_rents_cents is forbidden on a PSF_REGRESSION assessment")
    return None, base, list(adjustments or [])


@bp.post("/portfolios/<pid>/leases/<lid>/options/<oid>/assessments")
def create_assessment(pid, lid, oid):
    authorized(["AssetManager"])
    _p, _l, option = resolve_option(pid, lid, oid)
    body = get_body()
    method = req_enum(body, "method", METHODS)
    expected = req_int(body, "expected_option_version")
    comparables, base, adjustments = _check_assessment_shape(body, method)
    # priority 14: OCC on Option.version (shape checks run first)
    if expected != option["version"]:
        raise_error(ERR_STALE_VERSION, "expected_option_version does not match the option version")
    provisional = compute_fair_market_rent(method, comparables, base, adjustments)
    # supersede any prior PROVISIONAL row; this advances Option.version
    for m in option_assessments(oid):
        if m["status"] == "PROVISIONAL":
            m["status"] = "SUPERSEDED"
            touch(m)
    m = new_record("assessments", {
        "option_id": oid,
        "method": method,
        "comparable_rents_cents": comparables,
        "regression_base_cents": base,
        "regression_adjustments": adjustments,
        "status": "PROVISIONAL",
        "provisional_rent_cents": provisional,
        "determined_rent_cents": None,
        "_created_date": CLOCK.today(),  # logical creation date drives the 15-day windows
    })
    touch(option)
    return success_object(public(m), 201)


@bp.get("/portfolios/<pid>/leases/<lid>/options/<oid>/assessments")
def list_assessments(pid, lid, oid):
    authorized(READ_ROLES)
    resolve_option(pid, lid, oid)
    status = request.args.get("status")
    items = option_assessments(oid)
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return paged(items, public)


@bp.get("/portfolios/<pid>/leases/<lid>/options/<oid>/assessments/<mid>")
def get_assessment(pid, lid, oid, mid):
    authorized(READ_ROLES)
    _p, _l, _o, m = resolve_assessment(pid, lid, oid, mid)
    return success_object(public(m))


@bp.post("/portfolios/<pid>/leases/<lid>/options/<oid>/assessments/<mid>/dispute")
def dispute_assessment(pid, lid, oid, mid):
    authorized(["AssetManager"])
    _p, lease, option, m = resolve_assessment(pid, lid, oid, mid)
    body = get_body()
    landlord_rent = req_int(body, "landlord_rent_cents", positive=True)
    tenant_rent = req_int(body, "tenant_rent_cents", positive=True)
    # option state first (§2.10), then dispute-window timeliness, then assessment state
    if option["status"] not in ("NOTICE_SENT", "IN_ARBITRATION"):
        raise_error(ERR_INVALID_STATE,
                    "dispute requires the option to be NOTICE_SENT or IN_ARBITRATION")
    if CLOCK.today() > m["_created_date"] + timedelta(days=15):
        raise_error(ERR_DISPUTE_WINDOW_CLOSED,
                    "dispute filed more than 15 calendar days after assessment creation")
    if m["status"] != "PROVISIONAL":
        raise_error(ERR_INVALID_STATE, "only a PROVISIONAL assessment can be disputed")
    m["status"] = "DISPUTED"
    touch(m)
    case = new_record("arbitrations", {
        "assessment_id": mid,
        "landlord_rent_cents": landlord_rent,
        "tenant_rent_cents": tenant_rent,
        "submission_close_date": fmt_date_midnight(CLOCK.today() + timedelta(days=30)),
        "status": "OPEN",
        "award_rent_cents": None,
        "panel_guidance_rent_cents": None,
    })
    # cross-entity cascade: parent Option NOTICE_SENT -> IN_ARBITRATION
    if option["status"] == "NOTICE_SENT":
        option["status"] = "IN_ARBITRATION"
        refresh(option)
    return success_object(public(case), 201)


@bp.get("/portfolios/<pid>/leases/<lid>/options/<oid>/assessments/<mid>/arbitration")
def get_arbitration(pid, lid, oid, mid):
    authorized(READ_ROLES)
    resolve_assessment(pid, lid, oid, mid)
    case = assessment_case(mid)
    items = [case] if case is not None else []
    return paged(items, public)


@bp.post("/portfolios/<pid>/leases/<lid>/options/<oid>/assessments/<mid>/arbitration/decide")
def decide_arbitration(pid, lid, oid, mid):
    authorized(["LandlordCounsel"])
    _p, lease, option, m = resolve_assessment(pid, lid, oid, mid)
    case = assessment_case(mid)
    if case is None:
        raise_error(ERR_NOT_FOUND, "no arbitration case exists for this assessment")
    body = get_body()
    guidance = req_int(body, "panel_guidance_rent_cents", positive=True)
    if case["status"] not in ("OPEN", "SUBMISSIONS_FROZEN"):
        raise_error(ERR_INVALID_STATE, "arbitration case is already DECIDED")
    # baseball arbitration: nearest submission to the guidance; exact tie -> lower
    dl = abs(case["landlord_rent_cents"] - guidance)
    dt = abs(case["tenant_rent_cents"] - guidance)
    if dl < dt:
        award = case["landlord_rent_cents"]
    elif dt < dl:
        award = case["tenant_rent_cents"]
    else:
        award = min(case["landlord_rent_cents"], case["tenant_rent_cents"])
    case["award_rent_cents"] = award
    case["panel_guidance_rent_cents"] = guidance
    case["status"] = "DECIDED"
    touch(case)
    # cascade hop 1: assessment DISPUTED -> FINAL with the award
    if m["status"] == "DISPUTED":
        m["status"] = "FINAL"
        m["determined_rent_cents"] = award
        touch(m)
        delta = award - m["provisional_rent_cents"]
        if delta != 0:
            post_ledger(lease["id"], "ARBITRATION_AWARD_ADJUSTMENT",
                        delta * lease["rentable_square_feet"], CLOCK.today(),
                        source_assessment_id=mid)
    # cascade hop 2: option IN_ARBITRATION -> NOTICE_SENT, then exercise may complete
    if option["status"] == "IN_ARBITRATION":
        option["status"] = "NOTICE_SENT"
        refresh(option)
    try_complete_exercise(option, CLOCK.now())
    return success_object(public(case))
