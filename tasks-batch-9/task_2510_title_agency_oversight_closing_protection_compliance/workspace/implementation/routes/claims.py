"""Claims arising from agency conduct: recourse, indemnity and resolution
(PRD 3.8)."""

from flask import Blueprint

import calc
import db
import derive
import lookup
import middleware as mw
import response
import shape
import tx
from db import store
from errors import ApiError
from routes.policy_files import ISSUED_STATUSES

bp = Blueprint("claims", __name__)

CAUSE_CODES = (
    "AGENCY_ERROR",
    "SEARCH_DEFECT",
    "ESCROW_DEFALCATION",
    "UNDERWRITING_BREACH",
)
CLAIM_STATUSES = (
    "INVESTIGATING",
    "RECOURSE_DEMANDED",
    "ABSORBED",
    "RECOVERED",
    "WRITTEN_OFF",
)
CLAIM_TRANSITIONS = {
    "INVESTIGATING": ("RECOURSE_DEMANDED", "ABSORBED"),
    "RECOURSE_DEMANDED": ("RECOVERED", "WRITTEN_OFF"),
}
CLAIM_TERMINALS = ("ABSORBED", "RECOVERED", "WRITTEN_OFF")
CLAIM_TARGET_ROLE = {
    "RECOURSE_DEMANDED": (mw.UNDERWRITING_COUNSEL,),
    "ABSORBED": (mw.UNDERWRITING_COUNSEL,),
    "RECOVERED": (mw.COMPLIANCE_OFFICER,),
    "WRITTEN_OFF": (mw.COMPLIANCE_OFFICER,),
}
ADJUDICATIONS = ("RECOURSE_DEMANDED", "ABSORBED")


@bp.post("/agency-claims")
def create_claim():
    mw.require_roles(mw.COMPLIANCE_OFFICER, mw.UNDERWRITING_COUNSEL)
    payload = shape.body()
    agency_id = shape.req_id(payload, "agency_id")
    policy_file_id = shape.req_id(payload, "policy_file_id")
    cpl_id = shape.opt_id(payload, "cpl_id")
    cause_code = shape.req_enum(payload, "cause_code", CAUSE_CODES)
    loss_amount = shape.req_positive_cents(payload, "loss_amount_cents")
    notice_date = shape.req_date(payload, "notice_date")

    # Tier 5 - agency_id, policy_file_id, cpl_id
    agency = lookup.agency(agency_id)
    policy_file = lookup.policy_file(policy_file_id)
    if cpl_id is not None:
        lookup.letter(cpl_id)

    # Tier 12 - one referential rule ties the three together
    if policy_file["agency_id"] != agency["id"]:
        raise ApiError("ERR_CLAIM_POLICY_MISMATCH")
    if policy_file["issuance_status"] not in ISSUED_STATUSES:
        raise ApiError("ERR_CLAIM_POLICY_MISMATCH")
    if cpl_id is not None and policy_file["cpl_id"] != cpl_id:
        raise ApiError("ERR_CLAIM_POLICY_MISMATCH")

    claim = db.new_row(
        db.CLAIM,
        {
            "agency_id": agency["id"],
            "policy_file_id": policy_file["id"],
            "cpl_id": cpl_id,
            "cause_code": cause_code,
            "loss_amount_cents": loss_amount,
            "notice_date": db.date_str(notice_date),
            "status": "INVESTIGATING",
            "recourse_tier": None,
            "indemnity_offset_cents": 0,
            "recourse_amount_cents": 0,
            "net_underwriter_exposure_cents": 0,
            "recovered_amount_cents": 0,
            "decided_by_user_id": None,
        },
    )
    return response.created(claim)


@bp.get("/agency-claims/<claim_id>")
def read_claim(claim_id):
    mw.require_roles(*mw.ALL_ROLES)
    return response.ok(lookup.claim(claim_id))


@bp.get("/agency-claims")
def list_claims():
    mw.require_roles(*mw.ALL_ROLES)
    limit, offset = shape.pagination()
    filters = {
        "agency_id": shape.query_value("agency_id"),
        "policy_file_id": shape.query_value("policy_file_id"),
        "cpl_id": shape.query_value("cpl_id"),
        "status": shape.query_value("status"),
        "cause_code": shape.query_value("cause_code"),
    }
    rows = [
        row
        for row in store.all(db.CLAIM)
        if all(v is None or row.get(k) == v for k, v in filters.items())
    ]
    return response.ok_list(shape.page(rows, limit, offset), limit, offset, len(rows))


@bp.post("/agency-claims/<claim_id>/state")
def claim_state(claim_id):
    user_id, role = mw.require_roles(mw.UNDERWRITING_COUNSEL, mw.COMPLIANCE_OFFICER)
    payload = shape.body()
    to_state = shape.req_enum(payload, "to_state", CLAIM_STATUSES)
    shape.opt_str(payload, "note")
    recovered_amount = None
    if to_state == "RECOVERED":
        recovered_amount = shape.req_cents(payload, "recovered_amount_cents")

    claim = lookup.claim(claim_id)
    agency = lookup.agency(claim["agency_id"])
    policy_file = store.get(db.POLICY_FILE, claim["policy_file_id"])

    # Tier 7
    mw.require_transition_role(role, CLAIM_TARGET_ROLE.get(to_state))
    # Tier 8 - SoD-2 on either adjudication out of INVESTIGATING
    if to_state in ADJUDICATIONS and policy_file is not None:
        mw.require_segregation(user_id, policy_file["referral_decided_by_user_id"])
    # Tier 10
    lookup.guard_transition(claim["status"], to_state, CLAIM_TRANSITIONS, CLAIM_TERMINALS)

    if to_state in ADJUDICATIONS:
        # Tier 11
        if agency["eo_policy_limit_cents"] <= 0:
            raise ApiError("ERR_EO_COVERAGE_LAPSED")

    if to_state == "RECOURSE_DEMANDED":
        tier, indemnity, recourse, net = calc.claim_waterfall(
            claim["loss_amount_cents"],
            agency["eo_policy_limit_cents"],
            claim["cause_code"],
        )
        claim["status"] = "RECOURSE_DEMANDED"
        claim["recourse_tier"] = tier
        claim["indemnity_offset_cents"] = indemnity
        claim["recourse_amount_cents"] = recourse
        claim["net_underwriter_exposure_cents"] = net
        claim["decided_by_user_id"] = user_id
        if claim["cause_code"] == "ESCROW_DEFALCATION":
            # The punitive tail: standing, posture, accounts and letters.
            agency["escrow_standing"] = "DEFALCATION_RISK"
            previous = derive.recompute_agency(agency)
            if agency["oversight_posture"] == "FROZEN":
                derive.restrict_open_accounts(agency)
                derive.decline_letters_in_flight(agency)
            tx.force_agency_version_bump(agency)
        else:
            derive.recompute_agency(agency)

    elif to_state == "ABSORBED":
        claim["status"] = "ABSORBED"
        claim["recourse_tier"] = calc.recourse_tier(
            claim["loss_amount_cents"], agency["eo_policy_limit_cents"]
        )
        claim["indemnity_offset_cents"] = 0
        claim["recourse_amount_cents"] = 0
        claim["net_underwriter_exposure_cents"] = claim["loss_amount_cents"]
        claim["decided_by_user_id"] = user_id
        derive.recompute_agency(agency)

    elif to_state == "RECOVERED":
        # Tier 14 - the recovery ceiling
        if recovered_amount > claim["recourse_amount_cents"]:
            raise ApiError("ERR_RECOVERY_EXCEEDS_RECOURSE")
        claim["status"] = "RECOVERED"
        claim["recovered_amount_cents"] = recovered_amount
        claim["net_underwriter_exposure_cents"] = (
            claim["loss_amount_cents"]
            - claim["indemnity_offset_cents"]
            - recovered_amount
        )
        derive.recompute_agency(agency)

    else:  # WRITTEN_OFF
        claim["status"] = "WRITTEN_OFF"
        claim["net_underwriter_exposure_cents"] = (
            claim["loss_amount_cents"] - claim["indemnity_offset_cents"]
        )
        derive.recompute_agency(agency)

    return response.ok(claim)
