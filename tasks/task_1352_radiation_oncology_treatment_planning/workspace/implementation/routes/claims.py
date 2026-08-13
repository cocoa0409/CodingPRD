"""Billing claims (PRD 3.9): open-with-backfill, finalize (OCC), reopen, submit."""
from flask import Blueprint

from db import store, new_entity, touch, sorted_all
from errors import (err, ERR_NOT_FOUND, ERR_STALE_VERSION, ERR_CLAIM_NOT_DRAFT,
                    ERR_CLAIM_NOT_FINALIZED, ERR_CLAIM_ALREADY_OPEN,
                    ERR_EMPTY_CLAIM, ERR_COURSE_NOT_TERMINAL)
from middleware import require_roles, ALL_ROLES, get_body
from response import success, paginate
from serializers import claim_json, line_json
from services import calc
from services.billing import open_claim, claim_lines, recompute_gross, backfill
from timeutil import new_id
from validate import req_int

bp = Blueprint("claims", __name__)


def get_claim_or_404(bid):
    c = store.claims.get(bid)
    if c is None:
        err(ERR_NOT_FOUND, "billing claim not found")
    return c


@bp.post("/oncology/treatment-courses/<cid>/billing-claims")
@require_roles("BillingCoordinator")
def create_claim(cid, user_id):
    course = store.courses.get(cid)
    if course is None:
        err(ERR_NOT_FOUND, "treatment course not found")
    get_body()
    # p11: at most one open (DRAFT or FINALIZED) claim per course
    if open_claim(cid) is not None:
        err(ERR_CLAIM_ALREADY_OPEN,
            "Course already has a claim in DRAFT or FINALIZED status")
    claim = new_entity()
    claim.update({
        "id": new_id(), "course_id": cid, "status": "DRAFT",
        "gross_total_cents": 0, "discount_cents": 0, "final_total_cents": 0,
    })
    store.claims[claim["id"]] = claim
    backfill(claim, course)   # backfilled lines keep gross live
    recompute_gross(claim)
    return success(claim_json(claim), 201)


@bp.get("/oncology/treatment-courses/<cid>/billing-claims")
@require_roles(*ALL_ROLES)
def list_claims(cid, user_id):
    if cid not in store.courses:
        err(ERR_NOT_FOUND, "treatment course not found")
    items = sorted_all(c for c in store.claims.values() if c["course_id"] == cid)
    page, meta = paginate(items)
    return success([claim_json(c) for c in page], 200, pagination=meta)


@bp.get("/oncology/billing-claims/<bid>")
@require_roles(*ALL_ROLES)
def get_claim(bid, user_id):
    return success(claim_json(get_claim_or_404(bid)), 200)


@bp.get("/oncology/billing-claims/<bid>/charge-lines")
@require_roles(*ALL_ROLES)
def list_lines(bid, user_id):
    get_claim_or_404(bid)
    items = sorted_all(claim_lines(bid))
    page, meta = paginate(items)
    return success([line_json(l) for l in page], 200, pagination=meta)


@bp.post("/oncology/billing-claims/<bid>/finalize")
@require_roles("BillingCoordinator")
def finalize_claim(bid, user_id):
    claim = get_claim_or_404(bid)
    body = get_body()
    expected = req_int(body, "expected_claim_version")
    # p5 OCC precedes the p6 state gate
    if expected != claim["version"]:
        err(ERR_STALE_VERSION, "expected_claim_version is stale")
    if claim["status"] != "DRAFT":
        err(ERR_CLAIM_NOT_DRAFT, "Finalize requires claim DRAFT")
    lines = claim_lines(bid)
    if not lines:
        err(ERR_EMPTY_CLAIM, "Finalize requires at least one charge line")
    gross, discount, final = calc.claim_discount(lines)
    claim["gross_total_cents"] = gross
    claim["discount_cents"] = discount
    claim["final_total_cents"] = final
    claim["status"] = "FINALIZED"
    touch(claim)  # finalize increments the claim version by 1
    return success(claim_json(claim), 200)


@bp.post("/oncology/billing-claims/<bid>/submit")
@require_roles("BillingCoordinator")
def submit_claim(bid, user_id):
    claim = get_claim_or_404(bid)
    get_body()
    if claim["status"] != "FINALIZED":
        err(ERR_CLAIM_NOT_FINALIZED, "Submit requires claim FINALIZED")
    course = store.courses.get(claim["course_id"])
    if course is None or course["status"] not in ("COMPLETED", "DISCONTINUED"):
        err(ERR_COURSE_NOT_TERMINAL,
            "Claim submission requires course COMPLETED or DISCONTINUED")
    claim["status"] = "SUBMITTED"
    touch(claim)
    return success(claim_json(claim), 200)


@bp.post("/oncology/billing-claims/<bid>/reopen")
@require_roles("BillingCoordinator")
def reopen_claim(bid, user_id):
    claim = get_claim_or_404(bid)
    get_body()
    if claim["status"] != "FINALIZED":
        err(ERR_CLAIM_NOT_FINALIZED, "Reopen requires claim FINALIZED")
    claim["status"] = "DRAFT"
    touch(claim)  # monetary fields retained verbatim across the round trip
    return success(claim_json(claim), 200)
