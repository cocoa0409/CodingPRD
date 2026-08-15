"""TransparencyPosting endpoints (PRD §3.5): create, publish (disclosure
regime), close (minimum duration)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_DUPLICATE_POSTING_REF,
    ERR_POSTING_INVALID_STATE,
    ERR_RANGE_DISCLOSURE_REQUIRED,
    ERR_INVALID_SALARY_RANGE,
    ERR_RANGE_SPREAD_EXCEEDED,
    ERR_MIN_POSTING_DURATION_NOT_MET,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record, touch
from util import D, clock_now_iso, clock_today, parse_datetime
from datetime import timedelta
from validate import get_body, req_str, opt_int, require_path_resource, require_fk

bp = Blueprint("postings", __name__)


@bp.post("/transparency-postings")
def create_posting():
    authorized(["ComplianceReporter"])
    body = get_body()
    rule_id = body.get("jurisdiction_rule_id")
    if rule_id is None or not isinstance(rule_id, str) or rule_id.strip() == "":
        raise_error(ERR_INVALID_REQUEST, "missing or invalid field: jurisdiction_rule_id")
    # Priority 3: body FK existence
    require_fk("jurisdiction_rules", rule_id, "jurisdiction_rule_id")
    # Priority 3.7: shape
    job_posting_ref = req_str(body, "job_posting_ref")
    title = req_str(body, "title")
    min_salary_cents = opt_int(body, "min_salary_cents", None, minimum=0)
    max_salary_cents = opt_int(body, "max_salary_cents", None, minimum=0)
    # Priority 7: job_posting_ref unique across the system
    for p in db["transparency_postings"].values():
        if p["job_posting_ref"] == job_posting_ref:
            raise_error(ERR_DUPLICATE_POSTING_REF,
                        f"job_posting_ref already exists: {job_posting_ref}")

    rec = new_record("transparency_postings", {
        "jurisdiction_rule_id": rule_id,
        "job_posting_ref": job_posting_ref,
        "title": title,
        "min_salary_cents": min_salary_cents,
        "max_salary_cents": max_salary_cents,
        "published_at": None,
        "closed_at": None,
        "status": "DRAFT",
    })
    return success_object(public(rec), status=201)


@bp.get("/transparency-postings")
def list_postings():
    return list_response("transparency_postings", {
        "jurisdiction_rule_id": request.args.get("jurisdiction_rule_id"),
        "status": request.args.get("status"),
    })


@bp.get("/transparency-postings/<rid>")
def get_posting(rid):
    return get_one("transparency_postings", rid)


@bp.post("/transparency-postings/<rid>/publish")
def publish_posting(rid):
    authorized(["ComplianceReporter"])
    posting = require_path_resource("transparency_postings", rid)
    # Checks applied in the pinned order (PRD §3.5)
    # 1. state
    if posting["status"] != "DRAFT":
        raise_error(ERR_POSTING_INVALID_STATE, "publish requires a DRAFT posting")
    rule = db["jurisdiction_rules"].get(posting["jurisdiction_rule_id"])
    lo = posting["min_salary_cents"]
    hi = posting["max_salary_cents"]
    # 2. disclosure safety: full range required when the jurisdiction mandates it
    if rule is not None and rule["range_disclosure_required"]:
        if lo is None or hi is None:
            raise_error(ERR_RANGE_DISCLOSURE_REQUIRED,
                        "jurisdiction requires pay range disclosure")
    # 3. range sanity when both bounds present
    if lo is not None and hi is not None and hi < lo:
        raise_error(ERR_INVALID_SALARY_RANGE,
                    "max_salary_cents must be >= min_salary_cents")
    # 4. spread cap when the jurisdiction sets one and both bounds are present
    if rule is not None and rule["max_range_spread_pct"] is not None \
            and lo is not None and hi is not None:
        if lo == 0:
            spread = D(0) if hi == 0 else None  # undefined spread -> treated as over cap
        else:
            spread = (D(hi) - D(lo)) / D(lo) * 100
        if spread is None or spread > D(rule["max_range_spread_pct"]):
            raise_error(ERR_RANGE_SPREAD_EXCEEDED,
                        "range spread exceeds the jurisdiction's max_range_spread_pct")

    posting["published_at"] = clock_now_iso()
    posting["status"] = "PUBLISHED"
    touch(posting)
    return success_object(public(posting))


@bp.post("/transparency-postings/<rid>/close")
def close_posting(rid):
    authorized(["ComplianceReporter"])
    posting = require_path_resource("transparency_postings", rid)
    if posting["status"] != "PUBLISHED":
        raise_error(ERR_POSTING_INVALID_STATE, "close requires a PUBLISHED posting")
    rule = db["jurisdiction_rules"].get(posting["jurisdiction_rule_id"])
    min_days = rule["min_posting_duration_days"] if rule is not None else 0
    # Inclusive boundary: closing exactly when the duration elapsed is permitted
    earliest = parse_datetime(posting["published_at"]).date() + timedelta(days=min_days)
    if clock_today() < earliest:
        raise_error(ERR_MIN_POSTING_DURATION_NOT_MET,
                    "posting has not met the jurisdiction's minimum duration")
    posting["closed_at"] = clock_now_iso()
    posting["status"] = "CLOSED"
    touch(posting)
    return success_object(public(posting))
