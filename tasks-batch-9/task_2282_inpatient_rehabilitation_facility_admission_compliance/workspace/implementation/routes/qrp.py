"""Quality reporting programme assessments and the payment penalty (PRD §3.9)."""

from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from db import store
from errors import ApiError
from queryargs import enum_arg, int_arg, matches, str_arg
from response import envelope, paged, pagination_params
from services import by_seq, qrp_metrics, require, stamp_new, touch
from util import Body, iso, serialize

bp = Blueprint("qrp", __name__)

QRP_STATUSES = ("DRAFT", "FINALIZED")


@bp.post("/qrp-assessments")
def create_qrp():
    authenticate(("ComplianceOfficer",))
    body = Body(request.get_json(silent=True))

    facility_id = body.id_field("facility_id")
    fiscal_year = body.int_field("fiscal_year", minimum=2020, maximum=2100)
    period_start = body.date_field("reporting_period_start")
    period_end = body.date_field("reporting_period_end")

    # ladder rank 8 — period ordering
    if period_end < period_start:
        raise ApiError("ERR_INVALID_PERIOD")

    # ladder rank 10 — body identifier existence
    require(store.facilities, facility_id)

    qrp = stamp_new({
        "facility_id": facility_id,
        "fiscal_year": fiscal_year,
        "reporting_period_start": period_start.isoformat(),
        "reporting_period_end": period_end.isoformat(),
        "cohort_count": 0,
        "timely_count": 0,
        "data_completeness_pct": 0.00,
        "penalty_pct": 0.00,
        "finalized_at": None,
        "status": "DRAFT",
    })
    # metrics are computed from current data straight away (PRD §3.9)
    cohort_count, timely_count, completeness, penalty = qrp_metrics(qrp)
    qrp["cohort_count"] = cohort_count
    qrp["timely_count"] = timely_count
    qrp["data_completeness_pct"] = completeness
    qrp["penalty_pct"] = penalty

    store.qrps[qrp["id"]] = qrp
    return envelope(serialize(qrp), 201)


@bp.get("/qrp-assessments/<qrp_id>")
def get_qrp(qrp_id):
    authenticate(ALL_ROLES)
    qrp = require(store.qrps, qrp_id)
    return envelope(serialize(qrp), 200)


@bp.get("/qrp-assessments")
def list_qrps():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    filters = {
        "facility_id": str_arg("facility_id"),
        "fiscal_year": int_arg("fiscal_year"),
        "status": enum_arg("status", QRP_STATUSES),
    }
    items = [q for q in by_seq(list(store.qrps.values())) if matches(q, filters)]
    page, pagination = paged(items, limit, offset)
    return envelope([serialize(q) for q in page], 200, pagination)


@bp.post("/qrp-assessments/<qrp_id>/finalize")
def finalize_qrp(qrp_id):
    authenticate(("ComplianceOfficer",))
    qrp = require(store.qrps, qrp_id)

    # ladder rank 16 — declared transition DRAFT -> FINALIZED
    if qrp["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    cohort_count, timely_count, completeness, penalty = qrp_metrics(qrp)
    qrp["cohort_count"] = cohort_count
    qrp["timely_count"] = timely_count
    qrp["data_completeness_pct"] = completeness
    qrp["penalty_pct"] = penalty
    qrp["finalized_at"] = iso(store.clock)
    qrp["status"] = "FINALIZED"
    touch(qrp)

    facility = store.facilities.get(qrp["facility_id"])
    if facility is not None:
        facility["active_qrp_penalty_pct"] = penalty
        facility["qrp_penalty_effective_at"] = qrp["finalized_at"]
        touch(facility)

    return envelope(serialize(qrp), 200)
