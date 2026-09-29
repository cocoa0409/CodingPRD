"""Facility registration and read (PRD §3.1)."""

from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from db import store
from errors import ApiError
from response import envelope
from services import require, stamp_new
from util import Body, serialize

bp = Blueprint("facilities", __name__)


@bp.post("/facilities")
def create_facility():
    authenticate(("ComplianceOfficer",))
    body = Body(request.get_json(silent=True))

    name = body.str_field("name", min_len=1, max_len=120)
    cms_ccn = body.str_field("cms_ccn", pattern=r"^\d{6}$")
    period_start = body.date_field("review_period_start")
    period_end = body.date_field("review_period_end")
    threshold = body.num_field("compliance_threshold_pct", required=False,
                               minimum=0.01, maximum=100.00, default=60.00)
    daily_cap = body.int_field("daily_therapy_cap_minutes", required=False,
                               minimum=60, maximum=600, default=300)

    # ladder rank 8 — period ordering
    if period_end < period_start:
        raise ApiError("ERR_INVALID_PERIOD")

    # ladder rank 41 — cms_ccn uniqueness
    for existing in store.facilities.values():
        if existing["cms_ccn"] == cms_ccn:
            raise ApiError("ERR_CCN_DUPLICATE")

    facility = stamp_new({
        "name": name,
        "cms_ccn": cms_ccn,
        "review_period_start": period_start.isoformat(),
        "review_period_end": period_end.isoformat(),
        "compliance_threshold_pct": float(threshold),
        "daily_therapy_cap_minutes": daily_cap,
        "cohort_total_count": 0,
        "cohort_qualifying_count": 0,
        "provisional_compliance_pct": 0.00,
        "certified_compliance_pct": None,
        "settled_payment_cents": 0,
        "posture": "OPEN",
        "active_qrp_penalty_pct": 0.00,
        "qrp_penalty_effective_at": None,
        "_certified_source_review_id": None,
    })
    store.facilities[facility["id"]] = facility
    return envelope(serialize(facility), 201)


@bp.get("/facilities/<facility_id>")
def get_facility(facility_id):
    authenticate(ALL_ROLES)
    facility = require(store.facilities, facility_id)
    return envelope(serialize(facility), 200)
