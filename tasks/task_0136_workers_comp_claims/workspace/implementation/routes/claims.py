"""Claim endpoints: lifecycle state machine, reserve-adjustment OCC (PRD §3.2–§3.4, §3.11)."""
from __future__ import annotations

from datetime import timedelta
from flask import Blueprint, request, g

import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_RATING_NOT_FINALIZED,
    ERR_STATUTE_EXPIRED,
    ERR_STALE_CLAIM_VERSION,
    ERR_NOT_FOUND,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, sort_and_page
from services.validation import require_str, require_int, require_enum, require_datetime
from services import calculations as calc
from services import reserve as reserve_svc
from routes._common import (
    get_claim, get_policy, get_worker, get_employer,
    employer_id_of_claim, assert_employer_owns_claim, assert_employer_owns_employer,
)

bp = Blueprint("claims", __name__)

SEVERITY_TIERS = ["MINOR", "MODERATE", "SEVERE"]


def _employer_of_claim(claim):
    return db.employers.get(employer_id_of_claim(claim))


def _froi_acknowledged(claim_id: str) -> bool:
    for r in db.injury_reports.values():
        if (r["claim_id"] == claim_id and r["report_kind"] == "FROI"
                and r["edi_status"] == "ACKNOWLEDGED"):
            return True
    return False


def _has_scheduled_ime(claim_id: str) -> bool:
    for ime in db.ime_orders.values():
        if ime["claim_id"] == claim_id and ime["status"] == "SCHEDULED":
            return True
    return False


@bp.post("/claims")
def create_claim():
    require_auth(["ClaimsAdjuster", "Employer"])()
    body = get_json_body()

    policy_id = require_str(body, "policy_id")
    policy = get_policy(policy_id)
    worker_id = require_str(body, "worker_id")
    worker = get_worker(worker_id)

    require_datetime(body, "date_of_injury")
    disability_days = 0
    if body.get("disability_days") is not None:
        disability_days = require_int(body, "disability_days", minimum=0)

    # Employer ownership: claim's employer is the policy's employer.
    assert_employer_owns_employer(policy["employer_id"])

    # Statute of limitations (priority 9): now must be within SOL_DAYS of injury.
    doi = db.parse_iso_dt(body["date_of_injury"])
    now = db.get_current_utc_dt()
    if now > doi + timedelta(days=calc.SOL_DAYS):
        raise APIError(ERR_STATUTE_EXPIRED, 422,
                       "Claim filed past the statute of limitations")

    claim = {
        "policy_id": policy_id,
        "worker_id": worker_id,
        "status": "REPORTED",
        "claim_class": "UNCLASSIFIED",
        "disability_days": disability_days,
        "date_of_injury": body["date_of_injury"],
        "denial_reason": None,
    }
    db.stamp_common(claim)
    db.claims[claim["id"]] = claim
    return ok_object(claim, 201)


@bp.get("/claims/<rid>")
def get_claim_route(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster", "MedicalReviewer", "Employer"])()
    claim = get_claim(rid)
    assert_employer_owns_claim(claim)
    return ok_object(claim, 200)


@bp.get("/claims")
def list_claims():
    require_auth(["PlatformAdmin", "ClaimsAdjuster", "MedicalReviewer", "Employer"])()
    limit, offset = paginate_params(request.args)
    policy_id = request.args.get("policy_id")
    worker_id = request.args.get("worker_id")
    items = list(db.claims.values())
    if policy_id is not None:
        items = [c for c in items if c["policy_id"] == policy_id]
    if worker_id is not None:
        items = [c for c in items if c["worker_id"] == worker_id]
    if g.user_role == "Employer":
        items = [c for c in items if employer_id_of_claim(c) == g.user_id]
    page, total = sort_and_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/claims/<rid>/accept")
def accept_claim(rid):
    require_auth(["ClaimsAdjuster"])()
    claim = get_claim(rid)
    body = get_json_body()

    # disability_days supplied at acceptance drives the fork + ledger (PRD §3.3).
    if body.get("disability_days") is not None:
        claim["disability_days"] = require_int(body, "disability_days", minimum=0)
    disability_days = claim["disability_days"]

    status = claim["status"]
    if status == "REPORTED":
        # FROI must be ACKNOWLEDGED for either fork.
        if not _froi_acknowledged(claim["id"]):
            raise APIError(ERR_RATING_NOT_FINALIZED, 409,
                           "Claim's FROI is not ACKNOWLEDGED")
        if disability_days == 0:
            claim["status"] = "MEDICAL_ONLY"
            claim["claim_class"] = "MEDICAL_ONLY"
        else:
            # LOST_TIME requires a Reserve row to exist.
            if reserve_svc.reserve_for_claim(claim["id"]) is None:
                raise APIError(ERR_INVALID_STATE, 409,
                               "A reserve must exist before lost-time acceptance")
            claim["status"] = "LOST_TIME"
        _bump_open_count(claim, +1)
    elif status == "REOPENED":
        if reserve_svc.reserve_for_claim(claim["id"]) is None:
            raise APIError(ERR_INVALID_STATE, 409,
                           "A reserve must exist before lost-time acceptance")
        claim["status"] = "LOST_TIME"
        # open_claim_count already incremented on reopen; no change here.
    else:
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Cannot accept a claim in status {status}")

    db.bump(claim)
    return ok_object(claim, 200)


@bp.post("/claims/<rid>/deny")
def deny_claim(rid):
    require_auth(["ClaimsAdjuster"])()
    claim = get_claim(rid)
    if claim["status"] != "REPORTED":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Cannot deny a claim in status {claim['status']}")
    body = get_json_body()
    denial_reason = require_str(body, "denial_reason")
    claim["status"] = "DENIED"
    claim["denial_reason"] = denial_reason
    db.bump(claim)
    return ok_object(claim, 200)


@bp.post("/claims/<rid>/close")
def close_claim(rid):
    require_auth(["ClaimsAdjuster"])()
    claim = get_claim(rid)
    status = claim["status"]
    reserve = reserve_svc.reserve_for_claim(claim["id"])

    if status == "MEDICAL_ONLY":
        if _has_scheduled_ime(claim["id"]):
            raise APIError(ERR_INVALID_STATE, 409,
                           "A SCHEDULED IME blocks closing the claim")
        claim["status"] = "CLOSED"
        _bump_open_count(claim, -1)
    elif status == "MMI":
        if reserve is None or reserve["indemnity_reserve_cents"] != 0:
            raise APIError(ERR_INVALID_STATE, 409,
                           "Indemnity reserve must be fully drawn down before closing")
        if _has_scheduled_ime(claim["id"]):
            raise APIError(ERR_INVALID_STATE, 409,
                           "A SCHEDULED IME blocks closing the claim")
        claim["status"] = "CLOSED"
        _bump_open_count(claim, -1)
        # Lost-time close writes off any remaining medical reserve to zero.
        reserve["medical_reserve_cents"] = 0
        reserve_svc.recompute_total(reserve)
        db.bump(reserve)
    else:
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Cannot close a claim in status {status}")

    db.bump(claim)
    return ok_object(claim, 200)


@bp.post("/claims/<rid>/reopen")
def reopen_claim(rid):
    require_auth(["ClaimsAdjuster"])()
    claim = get_claim(rid)
    if claim["status"] != "CLOSED":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Cannot reopen a claim in status {claim['status']}")
    # Statutory reopening window: now < date_of_injury + REOPEN_LIMIT_DAYS.
    doi = db.parse_iso_dt(claim["date_of_injury"])
    now = db.get_current_utc_dt()
    if now >= doi + timedelta(days=calc.REOPEN_LIMIT_DAYS):
        raise APIError(ERR_STATUTE_EXPIRED, 422,
                       "Reopening window has expired")
    claim["status"] = "REOPENED"
    _bump_open_count(claim, +1)
    db.bump(claim)
    return ok_object(claim, 200)


@bp.post("/claims/<rid>/reserve-adjustments")
def reserve_adjustment(rid):
    require_auth(["ClaimsAdjuster"])()
    claim = get_claim(rid)
    body = get_json_body()

    # Reserve must exist for the claim (existence, priority 4).
    reserve = reserve_svc.reserve_for_claim(claim["id"])
    if reserve is None:
        raise APIError(ERR_NOT_FOUND, 404, "No reserve exists for this claim")

    projected_weeks = require_int(body, "projected_weeks", minimum=0)
    severity_tier = require_enum(body, "severity_tier", SEVERITY_TIERS)
    expected_version = require_int(body, "expected_claim_version")

    # OCC guard on the claim version (PRD §2.8).
    if expected_version != claim["version"]:
        raise APIError(ERR_STALE_CLAIM_VERSION, 412,
                       "expected_claim_version does not match the claim's version")

    reserve_svc.reproject(reserve, claim["id"], projected_weeks, severity_tier)
    db.bump(reserve)
    db.bump(claim)  # successful adjustment advances the claim version
    return ok_object(reserve, 200)


# ---- helpers ----------------------------------------------------------------

def _bump_open_count(claim, delta: int) -> None:
    emp = _employer_of_claim(claim)
    if emp is None:
        return
    emp["open_claim_count"] = emp.get("open_claim_count", 0) + delta
    db.bump(emp)
