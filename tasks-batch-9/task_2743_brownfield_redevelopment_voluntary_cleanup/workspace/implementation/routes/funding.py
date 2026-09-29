"""Funding awards: applications, the agency decision and the waterfall."""

from flask import Blueprint

import db
import response
import validation as V
from errors import ApiError
from middleware import actor_id, endpoint
from routes.common import apply_filter, fetch, require_owner
from services import derive
from services.constants import (
    AWARD_STATUS,
    COST_CATEGORIES,
    ELIGIBILITY_DOCUMENTS,
    FUNDING_DECISIONS,
    FUNDING_KINDS,
    REQUIRED_DOCUMENTS,
)
from services.serialize import dump_award

bp = Blueprint("funding", __name__)

READ_ROLES = ["Redeveloper", "StateAgencyReviewer", "Lender", "Insurer"]


@bp.post("/funding-awards")
@endpoint(["Redeveloper"])
def create_award():
    body = V.json_body()
    site_id = V.id_field(body, "site_id", True)
    program_code = V.string_field(body, "program_code", True, 1, 48)
    funding_kind = V.enum_field(body, "funding_kind", FUNDING_KINDS, True)
    priority = V.int_field(body, "program_priority", True, 1, 99)
    max_award_cents = V.int_field(body, "max_award_cents", True, minimum=1)
    max_share_pct = V.number_field(body, "max_share_pct", True, gt=0, le=1)
    match_pct = V.number_field(body, "match_requirement_pct", True, ge=0, le=1)
    categories = V.enum_array_field(body, "eligible_cost_categories",
                                    COST_CATEGORIES, True, min_len=1, max_len=5,
                                    unique=True)
    documents = V.enum_array_field(body, "eligibility_documents",
                                   ELIGIBILITY_DOCUMENTS, False, min_len=0,
                                   max_len=5, default=[])

    site = fetch("sites", site_id)
    require_owner(site)
    derive.assert_not_frozen(site)

    row = db.insert("funding_awards", {
        "site_id": site["id"],
        "program_code": program_code,
        "funding_kind": funding_kind,
        "program_priority": priority,
        "max_award_cents": max_award_cents,
        "max_share_pct": max_share_pct,
        "match_requirement_pct": match_pct,
        "eligible_cost_categories": categories,
        "eligibility_documents": documents,
        "status": "APPLIED",
        "decided_by_user_id": None,
        "allocated_cents": 0,
    })
    return response.created(dump_award(row))


@bp.get("/funding-awards")
@endpoint(READ_ROLES)
def list_awards():
    rows = db.ordered(db.all_rows("funding_awards"))
    rows = apply_filter(rows, "site_id", V.query_string("site_id"))
    rows = apply_filter(rows, "funding_kind",
                        V.query_enum("funding_kind", FUNDING_KINDS))
    rows = apply_filter(rows, "status", V.query_enum("status", AWARD_STATUS))
    return response.list_response(rows, dump_award)


@bp.get("/funding-awards/<award_id>")
@endpoint(READ_ROLES)
def get_award(award_id):
    return response.object_response(dump_award(fetch("funding_awards", award_id)))


@bp.post("/funding-awards/<award_id>/decision")
@endpoint(["StateAgencyReviewer"])
def award_decision(award_id):
    body = V.json_body()
    decision = V.enum_field(body, "decision", FUNDING_DECISIONS, True)
    V.string_field(body, "decision_note", False, 1, 600)

    award = fetch("funding_awards", award_id)
    site = db.get("sites", award["site_id"])
    if site is not None:
        derive.assert_not_frozen(site)

    if decision == "AWARD":
        if site is not None:
            derive.assert_posture_open(site)
        if award["status"] != "APPLIED":
            raise ApiError("ERR_INVALID_AWARD_STATE",
                           "Only an APPLIED application may be awarded.")
        required = REQUIRED_DOCUMENTS[award["funding_kind"]]
        filed = award["eligibility_documents"] or []
        for code in required:
            if code not in filed:
                raise ApiError("ERR_MISSING_ELIGIBILITY_DOCUMENT",
                               "Document %s is required for a %s application."
                               % (code, award["funding_kind"]))
        plan = derive.approved_plan_of_site(award["site_id"])
        if plan is None:
            raise ApiError("ERR_FUNDING_NEED_UNDETERMINED",
                           "The parcel has no APPROVED remedial action plan.")
        if not derive.plan_has_eligible_line(plan,
                                            award["eligible_cost_categories"]):
            raise ApiError("ERR_NO_ELIGIBLE_COST_BASE",
                           "The approved plan carries no cost line in this "
                           "programme's eligible categories.")
        award["status"] = "AWARDED"
        award["decided_by_user_id"] = actor_id()
        db.touch(award)
        if site is not None:
            derive.rederive_funding(site)
        return response.object_response(dump_award(award))

    if decision == "DENY":
        if award["status"] != "APPLIED":
            raise ApiError("ERR_INVALID_AWARD_STATE",
                           "Only an APPLIED application may be denied.")
        award["status"] = "DENIED"
        award["decided_by_user_id"] = actor_id()
        award["allocated_cents"] = 0
        db.touch(award)
        return response.object_response(dump_award(award))

    # RESCIND
    if award["status"] != "AWARDED":
        raise ApiError("ERR_INVALID_AWARD_STATE",
                       "Only an AWARDED application may be rescinded.")
    award["status"] = "RESCINDED"
    award["allocated_cents"] = 0
    award["decided_by_user_id"] = actor_id()
    db.touch(award)
    if site is not None:
        derive.rederive_funding(site)
    return response.object_response(dump_award(award))
