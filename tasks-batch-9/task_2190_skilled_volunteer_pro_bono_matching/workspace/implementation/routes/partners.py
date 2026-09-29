"""Partner orgs (PRD 3.1)."""
from flask import Blueprint

import config as C
import domain
import guards as G
import response as R
import serialize as Z
import store as S
from errors import ApiError
from guards import route

bp = Blueprint("partners", __name__)


@route(bp, "/partner-orgs", ["POST"], [C.ROLE_PROGRAM_MANAGER])
def create_partner_org():
    payload = G.body()
    name = G.v_str(payload, "name", min_len=1, max_len=160)
    contact_email = G.v_str(payload, "contact_email", min_len=1, max_len=320)
    sector = G.v_enum(payload, "sector", C.SECTORS)
    budget = G.v_num(payload, "annual_budget_usd", minimum=0, places=2)
    for existing in S.all_rows("partner_orgs"):
        if existing["contact_email"] == contact_email:
            raise ApiError("ERR_VALIDATION", "contact_email must be unique")
    row = S.insert(
        "partner_orgs",
        {
            "name": name,
            "contact_email": contact_email,
            "sector": sector,
            "annual_budget_usd": budget,
            "satisfaction_index": None,
            "satisfaction_sample_size": 0,
            "status": "ACTIVE",
            "probation_reason": None,
            "suspended_at": None,
        },
    )
    return R.created(Z.partner_org(row))


@route(
    bp,
    "/partner-orgs/<partner_id>",
    ["GET"],
    [
        C.ROLE_PROGRAM_MANAGER,
        C.ROLE_SCOPING_SPECIALIST,
        C.ROLE_PARTNER_CONTACT,
        C.ROLE_QUALITY_REVIEWER,
    ],
)
def get_partner_org(partner_id):
    partner = G.g03_partner(partner_id)
    return R.ok(Z.partner_org(partner))


@route(
    bp,
    "/partner-orgs/<partner_id>/summary",
    ["GET"],
    [C.ROLE_PROGRAM_MANAGER, C.ROLE_PARTNER_CONTACT],
)
def get_partner_summary(partner_id):
    partner = G.g03_partner(partner_id)
    return R.ok(Z.partner_summary(partner))


@route(bp, "/partner-orgs/<partner_id>/status", ["PATCH"], [C.ROLE_PROGRAM_MANAGER])
def patch_partner_status(partner_id):
    partner = G.g03_partner(partner_id)
    payload = G.body()
    to_status = G.v_enum(payload, "to_status", C.PARTNER_STATUSES)
    probation_reason = G.v_enum(
        payload, "probation_reason", C.PROBATION_REASONS, required=False
    )
    if partner["status"] == "SUSPENDED":
        raise ApiError("ERR_PARTNER_SUSPENDED", "SUSPENDED is terminal")
    if to_status == "SUSPENDED":
        domain.suspend_partner(partner)
    elif to_status == "PROBATION":
        partner["status"] = "PROBATION"
        partner["probation_reason"] = probation_reason or "MANUAL"
        S.touch(partner)
    else:
        partner["status"] = "ACTIVE"
        partner["probation_reason"] = None
        S.touch(partner)
    return R.ok(Z.partner_org(partner))


@route(
    bp,
    "/partner-orgs/<partner_id>/satisfaction-surveys",
    ["GET"],
    [C.ROLE_PROGRAM_MANAGER, C.ROLE_PARTNER_CONTACT],
)
def list_partner_surveys(partner_id):
    partner = G.g03_partner(partner_id)
    rows = S.where("satisfaction_surveys", partner_org_id=partner["id"])
    rows.sort(key=lambda s: (s["submitted_at"], s["created_at"], s["_seq"]), reverse=True)
    return R.paginate(rows, Z.satisfaction_survey)
