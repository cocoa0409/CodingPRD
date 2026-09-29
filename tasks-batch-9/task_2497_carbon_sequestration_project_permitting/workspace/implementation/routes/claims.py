"""Tax credit claim endpoints (PRD 3.9)."""

from decimal import Decimal as D

from flask import Blueprint

import db
import enums
import middleware as mw
import response
from errors import ApiError
from services import derive, lookup, serialize

bp = Blueprint("claims", __name__)

ADMIN = "ProgramAdmin"
DEV = "ProjectDeveloper"
REVIEWER = "RegulatoryReviewer"
VERIFIER = "IndependentVerifier"

APPROVED_PLAN_STATUSES = ("APPROVED", "APPROVED_WITH_CONDITIONS")


@bp.post("/ccs/tax-credit-claims")
@mw.require(DEV)
def create_claim():
    payload = mw.body()
    project_id = mw.req_str(payload, "project_id")
    monitoring_plan_id = mw.req_str(payload, "monitoring_plan_id")
    tax_year = mw.req_int(payload, "tax_year", ge=2020, le=2100)
    claim_variant = mw.opt_enum(
        payload, "claim_variant", enums.CLAIM_VARIANT, default="REPORTED"
    )
    lca_factor = mw.opt_num(
        payload, "lca_upstream_emissions_factor", default=D("0"), ge=0, le=D("0.5")
    )

    project = lookup.project(project_id)
    plan = lookup.plan(monitoring_plan_id)
    if plan["project_id"] != project["id"]:
        raise ApiError(
            "ERR_PROJECT_NOT_FOUND", "the monitoring plan does not belong to the given project"
        )

    derive.require_not_frozen(project)

    for existing in db.claims_of(project["id"]):
        if existing["tax_year"] == tax_year:
            raise ApiError(
                "ERR_DUPLICATE_TAX_YEAR_CLAIM",
                "this project already holds a claim for that tax year",
            )

    row = db.base_fields()
    row.update(
        {
            "project_id": project["id"],
            "monitoring_plan_id": plan["id"],
            "tax_year": tax_year,
            "claim_variant": claim_variant,
            "lca_upstream_emissions_factor": lca_factor,
            "reported_tonnes": D("0.000"),
            "verified_tonnes": D("0.000"),
            "credit_rate_usd_per_tonne": D("0.00"),
            "credit_amount_usd": D("0.00"),
            "status": "DRAFT",
            "submitted_by_user_id": None,
            "verifier_user_id": None,
        }
    )
    derive.recompute_claim(row, project)
    db.tax_credit_claims[row["id"]] = row
    return response.object_response(serialize.claim(row), 201)


@bp.get("/ccs/tax-credit-claims")
@mw.require(ADMIN, DEV, REVIEWER, VERIFIER)
def list_claims():
    project_id = mw.query_str("project_id")
    monitoring_plan_id = mw.query_str("monitoring_plan_id")
    tax_year = mw.query_int("tax_year")
    status = mw.query_enum("status", enums.CLAIM_STATUS)
    rows = db.ordered(db.tax_credit_claims.values())
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if monitoring_plan_id is not None:
        rows = [r for r in rows if r["monitoring_plan_id"] == monitoring_plan_id]
    if tax_year is not None:
        rows = [r for r in rows if r["tax_year"] == tax_year]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = mw.paginate(rows)
    return response.list_response([serialize.claim(r) for r in page], limit, offset, total)


@bp.get("/ccs/tax-credit-claims/<claim_id>")
@mw.require(ADMIN, DEV, REVIEWER, VERIFIER)
def get_claim(claim_id):
    return response.object_response(serialize.claim(lookup.claim(claim_id)))


@bp.post("/ccs/tax-credit-claims/<claim_id>/submit")
@mw.require(DEV)
def submit_claim(claim_id):
    payload = mw.body()
    mw.opt_str(payload, "submission_note")

    claim = lookup.claim(claim_id)
    project = db.projects.get(claim["project_id"])
    derive.require_not_frozen(project)

    if claim["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "a claim may only be submitted from DRAFT")

    plan = db.monitoring_plans.get(claim["monitoring_plan_id"])
    if plan is None or plan["status"] not in APPROVED_PLAN_STATUSES:
        raise ApiError(
            "ERR_MRV_PLAN_NOT_APPROVED", "the claim's monitoring plan is not approved"
        )

    derive.recompute_claim(claim, project)
    if claim["reported_tonnes"] <= 0:
        raise ApiError(
            "ERR_INVALID_CLAIM_STATE", "the claim's reported tonnage is not greater than zero"
        )

    claim["submitted_by_user_id"] = mw.caller_id()
    claim["status"] = "SUBMITTED"
    db.touch(claim)

    derive.recompute_pending_credit(project)
    db.touch(project)

    return response.object_response(serialize.claim(claim))


@bp.post("/ccs/tax-credit-claims/<claim_id>/verify")
@mw.require(VERIFIER)
def verify_claim(claim_id):
    # PRD 2.6 rank 4 — segregation of duties outranks request shape and state.
    existing = lookup.maybe_claim(claim_id)
    if existing is not None and existing["submitted_by_user_id"] == mw.caller_id():
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "a claim may not be verified by the user who submitted it"
        )

    payload = mw.body()
    decision = mw.req_enum(payload, "decision", enums.CLAIM_DECISION)
    mw.opt_str(payload, "verification_note")

    claim = lookup.claim(claim_id)
    project = db.projects.get(claim["project_id"])
    derive.require_not_frozen(project)

    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "only a SUBMITTED claim may be verified")

    if decision == "ALLOW":
        if claim["verified_tonnes"] <= 0:
            raise ApiError(
                "ERR_INVALID_CLAIM_STATE",
                "the claim's verified tonnage is not greater than zero",
            )
        claim["claim_variant"] = "VERIFIED"
        derive.recompute_claim(claim, project)
        claim["status"] = "ALLOWED"
    else:
        claim["status"] = "DISALLOWED"

    claim["verifier_user_id"] = mw.caller_id()
    db.touch(claim)

    derive.recompute_pending_credit(project)
    db.touch(project)

    return response.object_response(serialize.claim(claim))
