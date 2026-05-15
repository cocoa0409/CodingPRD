"""JobPosting routes."""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

from auth import get_caller, require_hr_bound_to_company, require_roles
from clock import iso_now
from errors import (
    ERR_DUPLICATE_POSTING,
    ERR_INVALID_SALARY_RANGE,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_POSTING_QUOTA_EXCEEDED,
    ERR_PROHIBITED_CONTENT,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
    raise_err,
)
from request_body import check_version, get_json_body, paginate, parse_pagination, require_field
from response import success_array, success_object
from services.cascade import take_posting_off_shelf
from store import append_audit, bump, init_common_fields, lock, store


bp = Blueprint("job_postings", __name__)


_INDUSTRY_VALUES = {"TECH", "FINANCE", "MANUFACTURING", "RETAIL", "HEALTHCARE", "EDUCATION", "OTHER"}
_POSTING_STATUSES = {"DRAFT", "UNDER_REVIEW", "REJECTED", "LIVE", "OFF_SHELF", "EXPIRED"}
_REJECT_REASONS = {"DISCRIMINATORY_WORDING", "ILLEGAL_TERMS", "DUPLICATE", "OTHER"}

# Prohibited-content dictionary. Implementation-defined; the PRD references a
# "prohibited-content dictionary" without enumerating tokens — we use a small
# representative set, matched case-insensitively against title + description.
_PROHIBITED_TOKENS = {
    "men only",
    "women only",
    "male only",
    "female only",
    "only male",
    "only female",
    "only men",
    "only women",
    "only hire male",
    "only hire female",
    "only hire men",
    "only hire women",
    "hire only male",
    "hire only female",
    "no female",
    "no male",
    "no women",
    "no men",
    "female candidates need not apply",
    "male candidates need not apply",
    "women need not apply",
    "men need not apply",
    "no minorities",
    "whites only",
    "no foreigners",
    "must be under",
    "must be over 50",
    "marriage status required",
    "no married",
    "illegal terms",
    "discriminatory wording",
    "child labor",
    "no disabled",
}


def _content_fingerprint(title: str, description: str) -> str:
    t = (title or "").lower()
    d_hash = hashlib.sha256((description or "").lower().encode("utf-8")).hexdigest()
    return f"{t}|{d_hash}"


def _serialize(p: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(p)
    # application_count is computed
    out["application_count"] = sum(
        1 for a in store.applications.values() if a.get("job_posting_id") == p["id"]
    )
    return out


@bp.post("/recruitment/job-postings")
def create_job_posting():
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    body = get_json_body()
    company_id = require_field(body, "company_id")
    title = require_field(body, "title")
    description = require_field(body, "description")
    salary_min = require_field(body, "salary_min_cents")
    salary_max = require_field(body, "salary_max_cents")
    benefits = body.get("benefits", [])

    if not isinstance(title, str) or not title:
        raise_err(ERR_VALIDATION, "title must be a non-empty string.")
    if not isinstance(description, str) or not description:
        raise_err(ERR_VALIDATION, "description must be a non-empty string.")
    if not isinstance(benefits, list):
        raise_err(ERR_VALIDATION, "benefits must be an array.")
    if not isinstance(salary_min, int) or isinstance(salary_min, bool):
        raise_err(ERR_VALIDATION, "salary_min_cents must be an integer.")
    if not isinstance(salary_max, int) or isinstance(salary_max, bool):
        raise_err(ERR_VALIDATION, "salary_max_cents must be an integer.")

    # FK existence check first (priority 5 before HR binding priority 6)
    company = store.companies.get(company_id)
    if company is None:
        raise_err(ERR_REFERENCE_NOT_FOUND, "company_id not found.")

    # HR-binding referential integrity (priority 6)
    require_hr_bound_to_company(caller, company_id)

    # Salary range sanity (priority 18) — happens here as part of creation
    if salary_min > salary_max or salary_min <= 0 or salary_max <= 0:
        raise_err(ERR_INVALID_SALARY_RANGE, "Salary range invalid.")

    row = init_common_fields(
        {
            "company_id": company_id,
            "title": title,
            "description": description,
            "salary_min_cents": salary_min,
            "salary_max_cents": salary_max,
            "benefits": list(benefits),
            "posting_status": "DRAFT",
            "review_rejection_reason": None,
            "content_fingerprint": None,
            "listed_at": None,
            "off_shelf_at": None,
        }
    )
    store.job_postings[row["id"]] = row
    body_out, status = success_object(_serialize(row), 201)
    return jsonify(body_out), status


@bp.get("/recruitment/job-postings/<pid>")
def get_job_posting(pid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser", "PlatformAdmin", "Candidate"])
    p = store.job_postings.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "JobPosting not found.")
    body_out, status = success_object(_serialize(p))
    return jsonify(body_out), status


@bp.get("/recruitment/job-postings")
def list_job_postings():
    caller = get_caller()
    require_roles(caller, ["HrUser", "PlatformAdmin", "Candidate"])
    limit, offset = parse_pagination()
    company_id = request.args.get("company_id")
    posting_status = request.args.get("posting_status")
    industry = request.args.get("industry")

    rows = list(store.job_postings.values())
    if company_id is not None:
        rows = [r for r in rows if r.get("company_id") == company_id]
    if posting_status is not None:
        rows = [r for r in rows if r.get("posting_status") == posting_status]
    if industry is not None:
        # industry filter applies via owning Company.industry
        ok_companies = {
            cid for cid, c in store.companies.items() if c.get("industry") == industry
        }
        rows = [r for r in rows if r.get("company_id") in ok_companies]

    rows.sort(key=lambda r: r.get("created_at", ""))
    page, total = paginate(rows, limit, offset)
    out = [_serialize(r) for r in page]
    body_out, status = success_array(out, limit=limit, offset=offset, total_count=total)
    return jsonify(body_out), status


@bp.post("/recruitment/job-postings/<pid>/submit-review")
def submit_review(pid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    p = store.job_postings.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "JobPosting not found.")
    company = store.companies.get(p.get("company_id"))
    if company is None:
        raise_err(ERR_NOT_FOUND, "Owning company not found.")
    require_hr_bound_to_company(caller, p["company_id"])
    body = get_json_body()
    check_version(body, p)

    if p.get("posting_status") != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Posting not in DRAFT.")
    # Owning company must be VERIFIED to submit review.
    if company.get("verification_status") != "VERIFIED":
        raise_err(ERR_INVALID_STATE, "Owning company not VERIFIED.")
    smin = int(p.get("salary_min_cents") or 0)
    smax = int(p.get("salary_max_cents") or 0)
    if smin > smax or smin <= 0 or smax <= 0:
        raise_err(ERR_INVALID_SALARY_RANGE, "Salary range invalid.")

    p["content_fingerprint"] = _content_fingerprint(p.get("title", ""), p.get("description", ""))
    from_state = p["posting_status"]
    p["posting_status"] = "UNDER_REVIEW"
    bump(p)
    append_audit(
        subject_entity="JobPosting",
        subject_id=p["id"],
        event_kind="STATE_TRANSITION",
        from_state=from_state,
        to_state="UNDER_REVIEW",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = success_object(_serialize(p))
    return jsonify(body_out), status


def _contains_prohibited_content(p: Dict[str, Any]) -> bool:
    blob = f"{p.get('title','')} {p.get('description','')}".lower()
    return any(tok in blob for tok in _PROHIBITED_TOKENS)


@bp.post("/recruitment/job-postings/<pid>/approve")
def approve_posting(pid: str):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin"])
    p = store.job_postings.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "JobPosting not found.")
    company = store.companies.get(p.get("company_id"))
    if company is None:
        raise_err(ERR_NOT_FOUND, "Owning company not found.")
    body = get_json_body()
    check_version(body, p)
    if p.get("posting_status") != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "Posting not UNDER_REVIEW.")
    # Prohibited content guard (priority 9)
    if _contains_prohibited_content(p):
        raise_err(ERR_PROHIBITED_CONTENT, "Prohibited content detected.")
    # Duplicate-posting guard (priority 10)
    fp = p.get("content_fingerprint")
    for other in store.job_postings.values():
        if other["id"] == p["id"]:
            continue
        if other.get("company_id") != p.get("company_id"):
            continue
        if other.get("posting_status") == "LIVE" and other.get("content_fingerprint") == fp:
            raise_err(ERR_DUPLICATE_POSTING, "Duplicate LIVE posting fingerprint.")
    # Posting quota guard (priority 16)
    if int(company.get("active_job_posting_count", 0)) >= int(company.get("posting_quota_limit", 0)):
        raise_err(ERR_POSTING_QUOTA_EXCEEDED, "Posting quota exceeded.")

    p["posting_status"] = "LIVE"
    p["listed_at"] = iso_now()
    bump(p)
    company["active_job_posting_count"] = int(company.get("active_job_posting_count", 0)) + 1
    bump(company)
    append_audit(
        subject_entity="JobPosting",
        subject_id=p["id"],
        event_kind="STATE_TRANSITION",
        from_state="UNDER_REVIEW",
        to_state="LIVE",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = success_object(_serialize(p))
    return jsonify(body_out), status


@bp.post("/recruitment/job-postings/<pid>/reject")
def reject_posting(pid: str):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin"])
    p = store.job_postings.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "JobPosting not found.")
    body = get_json_body()
    reason = require_field(body, "review_rejection_reason")
    check_version(body, p)
    if reason not in _REJECT_REASONS:
        raise_err(ERR_VALIDATION, "review_rejection_reason invalid.")
    if p.get("posting_status") != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "Posting not UNDER_REVIEW.")
    p["posting_status"] = "REJECTED"
    p["review_rejection_reason"] = reason
    bump(p)
    append_audit(
        subject_entity="JobPosting",
        subject_id=p["id"],
        event_kind="STATE_TRANSITION",
        from_state="UNDER_REVIEW",
        to_state="REJECTED",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = success_object(_serialize(p))
    return jsonify(body_out), status


@bp.post("/recruitment/job-postings/<pid>/revise")
def revise_posting(pid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    p = store.job_postings.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "JobPosting not found.")
    require_hr_bound_to_company(caller, p["company_id"])
    body = get_json_body()
    check_version(body, p)
    if p.get("posting_status") != "REJECTED":
        raise_err(ERR_INVALID_STATE, "Posting not REJECTED.")
    p["posting_status"] = "DRAFT"
    p["review_rejection_reason"] = None
    bump(p)
    append_audit(
        subject_entity="JobPosting",
        subject_id=p["id"],
        event_kind="STATE_TRANSITION",
        from_state="REJECTED",
        to_state="DRAFT",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = success_object(_serialize(p))
    return jsonify(body_out), status


@bp.post("/recruitment/job-postings/<pid>/take-off-shelf")
def take_off_shelf(pid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    p = store.job_postings.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "JobPosting not found.")
    require_hr_bound_to_company(caller, p["company_id"])
    body = get_json_body()
    check_version(body, p)
    if p.get("posting_status") != "LIVE":
        raise_err(ERR_INVALID_STATE, "Posting not LIVE.")
    take_posting_off_shelf(p, to_state="OFF_SHELF", actor_role=caller.role, actor_user_id=caller.user_id)
    body_out, status = success_object(_serialize(p))
    return jsonify(body_out), status
