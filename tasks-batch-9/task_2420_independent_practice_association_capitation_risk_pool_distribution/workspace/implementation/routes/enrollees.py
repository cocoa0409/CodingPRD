"""Enrollees and their per-member capitation components (PRD 3.3)."""

from flask import Blueprint

import calc
import db
import middleware
import resolve
import response
import serialize
import validate
from errors import fail

bp = Blueprint("enrollees", __name__)

AGE_BANDS = ("PEDIATRIC", "ADULT", "SENIOR")
BENEFIT_TIERS = ("HMO", "POS", "HMO_PLUS")


@bp.post("/ipa/delegation-agreements/<agreement_id>/enrollees")
def create_enrollee(agreement_id):
    user_id, role = middleware.require("IpaAdmin", "PayerRepresentative")
    body = validate.body()
    external_member_id = validate.req_str(body, "external_member_id")
    age_band = validate.req_enum(body, "age_band", AGE_BANDS)
    benefit_tier = validate.req_enum(body, "benefit_tier", BENEFIT_TIERS)
    risk_score_bps = validate.req_int(body, "risk_score_bps", minimum=1, maximum=50000)
    coverage_start_date = validate.req_instant(body, "coverage_start_date")
    coverage_end_date = validate.opt_instant(body, "coverage_end_date")

    agreement = resolve.agreement(agreement_id)
    middleware.check_ownership(role, user_id, agreement=agreement)

    # check 8 — the agreement must be ACTIVE to take on new members
    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE")

    # check 20 — external_member_id unique inside the agreement
    for existing in db.enrollees.values():
        if (existing["agreement_id"] == agreement["id"]
                and existing["external_member_id"] == external_member_id):
            fail("ERR_DUPLICATE_MEMBER_ID")

    enrollee = db.create(
        db.enrollees,
        agreement_id=agreement["id"],
        external_member_id=external_member_id,
        age_band=age_band,
        benefit_tier=benefit_tier,
        risk_score_bps=risk_score_bps,
        coverage_start_date=coverage_start_date,
        coverage_end_date=coverage_end_date,
        assigned_physician_id=None,
        gross_pmpm_cents=0,
        withhold_cents=0,
        net_pmpm_cents=0,
        cumulative_paid_claims_cents=0,
    )
    gross, withhold, net = calc.member_pmpm_components(agreement, enrollee)
    enrollee["gross_pmpm_cents"] = gross
    enrollee["withhold_cents"] = withhold
    enrollee["net_pmpm_cents"] = net
    return response.ok(serialize.enrollee(enrollee), 201)


@bp.get("/ipa/enrollees")
def list_enrollees():
    middleware.require("IpaAdmin", "NetworkManager", "ClaimsExaminer",
                       "PayerRepresentative", "PhysicianUser")
    agreement_id = validate.query_str("agreement_id")
    assigned_physician_id = validate.query_str("assigned_physician_id")
    age_band = validate.query_enum("age_band", AGE_BANDS)
    limit, offset = validate.pagination()

    items = db.ordered(db.enrollees.values())
    if agreement_id is not None:
        items = [e for e in items if e["agreement_id"] == agreement_id]
    if assigned_physician_id is not None:
        items = [e for e in items if e["assigned_physician_id"] == assigned_physician_id]
    if age_band is not None:
        items = [e for e in items if e["age_band"] == age_band]
    window = validate.paginate(items, limit, offset)
    return response.ok_list([serialize.enrollee(e) for e in window], limit, offset,
                            len(items))


@bp.get("/ipa/enrollees/<enrollee_id>")
def read_enrollee(enrollee_id):
    user_id, role = middleware.require("IpaAdmin", "NetworkManager", "ClaimsExaminer",
                                       "ReinsuranceUnderwriter", "PayerRepresentative",
                                       "PhysicianUser")
    enrollee = resolve.enrollee(enrollee_id)
    middleware.check_ownership(role, user_id,
                              physician_ids=[enrollee["assigned_physician_id"]],
                              agreement=db.agreement_of_enrollee(enrollee))
    return response.ok(serialize.enrollee(enrollee))
