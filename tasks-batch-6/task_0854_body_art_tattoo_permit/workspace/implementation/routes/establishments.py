"""Establishment routes — PRD §3.1, §3.2, §3.8, §3.9 (compliance summary)."""

import re

from flask import Blueprint

import calc
import config
import domain
import serialize
import store
import validate as V
from auth import authenticate
from envelope import array_response, force, send
from errors import ApiError
from util import days

bp = Blueprint("establishments", __name__)

COUNTY_RE = re.compile(r"^[A-Z]{3}$")

READ_ROLES = [
    "HealthOfficer",
    "Inspector",
    "PlanReviewer",
    "RecordsClerk",
    "EstablishmentOperator",
]


@bp.post("/body-art/establishments")
def create_establishment():
    authenticate(["HealthOfficer"])
    data = V.body()
    name = V.req_string(data, "name", 1, 120, trim_check=True)
    street_address = V.req_string(data, "street_address", 1, 200)
    county_code = V.req_string(data, "county_code", 3, 3)
    if not COUNTY_RE.match(county_code):
        raise V.bad("Field 'county_code' must be exactly three uppercase letters.")
    establishment_type = V.req_enum(data, "establishment_type", config.ESTABLISHMENT_TYPES)

    rec = domain.new_record(
        {
            "name": name,
            "street_address": street_address,
            "county_code": county_code,
            "establishment_type": establishment_type,
            "permit_status": "PENDING_PLAN_REVIEW",
            "permit_issued_on": None,
            "permit_expires_on": None,
            "operating_posture": "CLOSED",
            "risk_score": 0,
            "open_violation_count": 0,
            "open_critical_violation_count": 0,
            "sterilization_compliance_status": "NONCOMPLIANT",
            "active_artist_count": 0,
            "fees_paid_cents": 0,
            "fees_refunded_cents": 0,
            "plan_review_cycles_used": 1,
        }
    )
    store.establishments[rec["id"]] = rec
    domain.recompute_risk_and_posture(rec)
    return send(lambda: serialize.establishment(rec), 201)


@bp.get("/body-art/establishments/<establishment_id>")
def read_establishment(establishment_id):
    authenticate(READ_ROLES)
    est = V.get_establishment(establishment_id)
    return send(lambda: serialize.establishment(est), 200)


@bp.get("/body-art/establishments")
def list_establishments():
    authenticate(["HealthOfficer", "Inspector", "PlanReviewer", "RecordsClerk"])
    limit, offset = V.pagination()
    county_code = V.filter_string("county_code")
    permit_status = V.filter_enum("permit_status", config.ESTABLISHMENT_PERMIT_STATUSES)
    operating_posture = V.filter_enum("operating_posture", config.OPERATING_POSTURES)

    rows = store.sorted_rows(store.establishments)
    if county_code is not None:
        rows = [r for r in rows if r["county_code"] == county_code]
    if permit_status is not None:
        rows = [r for r in rows if r["permit_status"] == permit_status]
    if operating_posture is not None:
        rows = [r for r in rows if r["operating_posture"] == operating_posture]
    page, total = V.paginate(rows, limit, offset)
    return array_response(
        [serialize.establishment(r) for r in page], limit, offset, total
    )


@bp.post("/body-art/establishments/<establishment_id>/activate")
def activate_establishment(establishment_id):
    authenticate(["HealthOfficer"])
    est = V.get_establishment(establishment_id)
    if est["permit_status"] != "PENDING_INSPECTION":
        raise ApiError("ERR_ESTABLISHMENT_STATE_INVALID")
    passed = [
        i
        for i in domain.establishment_inspections(est["id"])
        if i["inspection_type"] == "PREOPENING" and i["status"] == "PASSED"
    ]
    if not passed:
        raise ApiError("ERR_PREOPENING_INSPECTION_REQUIRED")

    force(est)
    est["permit_status"] = "ACTIVE"
    est["permit_issued_on"] = store.now()
    est["permit_expires_on"] = est["permit_issued_on"] + days(config.PERMIT_TERM_DAYS)
    domain.recompute_risk_and_posture(est)
    return send(lambda: serialize.establishment(est), 200)


@bp.get("/body-art/establishments/<establishment_id>/compliance-summary")
def compliance_summary(establishment_id):
    authenticate(
        ["HealthOfficer", "Inspector", "RecordsClerk", "EstablishmentOperator"]
    )
    est = V.get_establishment(establishment_id)
    now = store.now()
    ster_status, candidate_count, pass_count = calc.sterilization_status(
        est["id"], now
    )
    provisional = calc.risk_score(est, now, "PROVISIONAL", ster_status)
    audit = calc.risk_score(est, now, "AUDIT", ster_status)
    rate, denominator, numerator = calc.minor_consent_audit_rate(est["id"], now)
    payload = {
        "establishment_id": est["id"],
        "permit_status": est["permit_status"],
        "operating_posture": est["operating_posture"],
        "risk_score_provisional": provisional,
        "risk_score_audit": audit,
        "sterilization_compliance_status": ster_status,
        "sterilization_candidate_count": candidate_count,
        "sterilization_pass_count": pass_count,
        "open_violation_count": est["open_violation_count"],
        "open_critical_violation_count": est["open_critical_violation_count"],
        "active_artist_count": est["active_artist_count"],
        "minor_procedure_count_in_window": denominator,
        "flagged_minor_procedure_count": numerator,
        "minor_consent_audit_rate": rate,
    }
    return send(payload, 200)


@bp.post("/body-art/establishments/<establishment_id>/enforcement-actions")
def create_establishment_enforcement(establishment_id):
    caller = authenticate(["HealthOfficer"])
    est = V.get_establishment(establishment_id)
    data = V.body()
    action_type = V.req_enum(data, "action_type", config.ENFORCEMENT_ACTION_TYPES)
    reason_code = V.req_enum(data, "reason_code", config.ENFORCEMENT_REASON_CODES)

    if domain.active_enforcement_for_establishment(est["id"]) is not None:
        raise ApiError("ERR_ACTIVE_ENFORCEMENT_EXISTS")

    action = domain.create_enforcement_action(
        subject_type="ESTABLISHMENT",
        establishment_id=est["id"],
        artist_id=None,
        action_type=action_type,
        reason_code=reason_code,
        issued_by_user_id=caller.user_id,
        auto_generated=False,
    )
    if action_type == "SUSPENSION":
        domain.suspend_establishment(est)
    else:
        domain.revoke_establishment(est)
    return send(lambda: serialize.enforcement_action(action), 201)
