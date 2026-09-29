"""Policies, policy versions and the legal update service."""

from flask import Blueprint

import auth
import calc
import resp
import store
import validate as v
from errors import fail
from store import db, set_fields, touch

bp = Blueprint("policy", __name__)

CATEGORIES = ["GOVERNANCE", "INSTRUCTION", "PERSONNEL", "STUDENTS", "BUSINESS"]
LEVELS = ["REQUIRED_BY_LAW", "RECOMMENDED", "LOCAL_DISCRETION"]
POLICY_STATUSES = ["UNADOPTED", "ADOPTED"]
COMPLIANCE_STATES = ["COMPLIANT", "ACTION_REQUIRED", "NON_COMPLIANT"]
VERSION_STATUSES = ["DRAFT", "FIRST_READING_PASSED", "ADOPTED", "SUPERSEDED",
                    "WITHDRAWN"]
REQUIRED_ACTIONS = ["ADOPT_NEW", "REVISE_EXISTING", "RESCIND"]
MANDATE_STATUSES = ["OPEN", "IN_PROGRESS", "SATISFIED", "OVERDUE"]


# ---------------------------------------------------------------------------
# policies
# ---------------------------------------------------------------------------

@bp.post("/governance/policies")
def create_policy():
    auth.authorize(["PolicyAnalyst"])
    body = v.body()
    code = v.req_str(body, "code", 3, 20)
    title = v.req_str(body, "title")
    category = v.req_enum(body, "category", CATEGORIES)
    level = v.req_enum(body, "legal_requirement_level", LEVELS)
    manual_section = v.req_str(body, "manual_section")

    for p in db["policies"].values():
        if p["code"] == code:
            fail("ERR_DUPLICATE_POLICY_CODE",
                 "Policy code %s is already registered." % code)

    rec = store.create("policies", "Policy", {
        "code": code,
        "title": title,
        "category": category,
        "legal_requirement_level": level,
        "manual_section": manual_section,
        "status": "UNADOPTED",
        "adopted_version_no": None,
        "last_review_date": None,
        "version_count": 0,
        "open_mandate_count": 0,
        "overdue_mandate_count": 0,
        "active_waiver_count": 0,
        "compliance_state": "ACTION_REQUIRED",
    })
    calc.policy_scoped_recompute(rec)
    return resp.created(store.serialize(rec))


@bp.get("/governance/policies")
def list_policies():
    auth.authorize(auth.READ_ROLES_PUBLIC)
    limit, offset = v.pagination()
    status = v.query_enum("status", POLICY_STATUSES)
    category = v.query_enum("category", CATEGORIES)
    compliance_state = v.query_enum("compliance_state", COMPLIANCE_STATES)
    items = store.sorted_rows("policies")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if category is not None:
        items = [p for p in items if p["category"] == category]
    if compliance_state is not None:
        items = [p for p in items if p["compliance_state"] == compliance_state]
    page, total = v.paginate(items, limit, offset)
    return resp.listing([store.serialize(p) for p in page], limit, offset, total)


@bp.get("/governance/policies/<policy_id>")
def get_policy(policy_id):
    auth.authorize(auth.READ_ROLES_PUBLIC)
    rec = v.find("policies", policy_id)
    return resp.ok(store.serialize(rec))


@bp.post("/governance/policies/<policy_id>/versions")
def create_policy_version(policy_id):
    auth.authorize(["PolicyAnalyst", "Superintendent"])
    policy = v.find("policies", policy_id)
    body = v.body()
    body_text = v.req_str(body, "body_text")
    summary = v.req_str(body, "summary_of_change")
    expected = v.req_int(body, "expected_policy_version")

    if expected != policy["version"]:
        fail("ERR_STALE_VERSION",
             "expected_policy_version does not match the policy's current version.")

    existing = [pv for pv in db["policy_versions"].values()
                if pv["policy_id"] == policy_id]
    next_no = max([pv["version_no"] for pv in existing] or [0]) + 1

    rec = store.create("policy_versions", "PolicyVersion", {
        "policy_id": policy_id,
        "version_no": next_no,
        "body_text": body_text,
        "summary_of_change": summary,
        "status": "DRAFT",
        "reading_count": 0,
        "first_reading_meeting_id": None,
        "adopting_meeting_id": None,
        "adopted_at": None,
        "effective_date": None,
        "superseded_at": None,
        "withdrawn_reason": None,
        "policy_version_after": None,
    })

    touch(policy)
    policy["version_count"] = len([pv for pv in db["policy_versions"].values()
                                   if pv["policy_id"] == policy_id])
    rec["policy_version_after"] = policy["version"]

    for m in calc.policy_mandates(policy_id):
        if m["status"] == "OPEN":
            set_fields(m, status="IN_PROGRESS")

    return resp.created(store.serialize(rec))


@bp.get("/governance/policy-versions")
def list_policy_versions():
    auth.authorize(auth.READ_ROLES_PUBLIC)
    limit, offset = v.pagination()
    policy_id = v.query_str("policy_id")
    status = v.query_enum("status", VERSION_STATUSES)
    first_meeting = v.query_str("first_reading_meeting_id")
    adopting_meeting = v.query_str("adopting_meeting_id")
    items = store.sorted_rows("policy_versions")
    if policy_id is not None:
        items = [x for x in items if x["policy_id"] == policy_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    if first_meeting is not None:
        items = [x for x in items if x["first_reading_meeting_id"] == first_meeting]
    if adopting_meeting is not None:
        items = [x for x in items if x["adopting_meeting_id"] == adopting_meeting]
    page, total = v.paginate(items, limit, offset)
    return resp.listing([store.serialize(x) for x in page], limit, offset, total)


@bp.get("/governance/policy-versions/<version_id>")
def get_policy_version(version_id):
    auth.authorize(auth.READ_ROLES_PUBLIC)
    rec = v.find("policy_versions", version_id)
    return resp.ok(store.serialize(rec))


@bp.post("/governance/policy-versions/<version_id>/withdraw")
def withdraw_policy_version(version_id):
    auth.authorize(["PolicyAnalyst"])
    version = v.find("policy_versions", version_id)
    body = v.body()
    reason = v.req_str(body, "withdrawn_reason")

    if version["status"] not in ("DRAFT", "FIRST_READING_PASSED"):
        fail("ERR_POLICY_VERSION_NOT_ELIGIBLE",
             "Only a draft or once-read version may be withdrawn.")

    for item in db["agenda_items"].values():
        if item.get("policy_version_id") == version_id \
                and item["status"] in ("PROPOSED", "POSTED"):
            fail("ERR_VERSION_ON_LIVE_AGENDA",
                 "The version is still referenced by a live agenda item.")

    set_fields(version, status="WITHDRAWN", withdrawn_reason=reason)

    policy = db["policies"].get(version["policy_id"])
    if policy is not None:
        touch(policy)
        policy["version_count"] = len([pv for pv in db["policy_versions"].values()
                                       if pv["policy_id"] == policy["id"]])
    return resp.ok(store.serialize(version))


# ---------------------------------------------------------------------------
# legal mandates
# ---------------------------------------------------------------------------

@bp.post("/governance/legal-mandates")
def create_mandate():
    auth.authorize(["LegalUpdateService"])
    body = v.body()
    notice_code = v.req_str(body, "notice_code")
    policy_id = v.req_id(body, "policy_id")
    citation = v.req_str(body, "citation")
    issued_on = v.req_dt(body, "issued_on")
    deadline = v.req_dt(body, "compliance_deadline")
    required_action = v.req_enum(body, "required_action", REQUIRED_ACTIONS)
    if deadline <= issued_on:
        fail("ERR_INVALID_REQUEST",
             "compliance_deadline must be strictly after issued_on.")

    policy = v.find("policies", policy_id)

    for m in db["mandates"].values():
        if m["notice_code"] == notice_code:
            fail("ERR_DUPLICATE_NOTICE_CODE",
                 "Notice code %s has already been filed." % notice_code)

    rec = store.create("mandates", "LegalMandate", {
        "notice_code": notice_code,
        "policy_id": policy_id,
        "citation": citation,
        "issued_on": issued_on,
        "compliance_deadline": deadline,
        "required_action": required_action,
        "status": "OPEN",
        "satisfied_by_version_no": None,
        "days_past_deadline": 0,
    })
    calc.policy_scoped_recompute(policy)
    return resp.created(store.serialize(rec))


@bp.get("/governance/legal-mandates")
def list_mandates():
    auth.authorize(auth.READ_ROLES_MANDATE)
    limit, offset = v.pagination()
    policy_id = v.query_str("policy_id")
    status = v.query_enum("status", MANDATE_STATUSES)
    items = store.sorted_rows("mandates")
    if policy_id is not None:
        items = [m for m in items if m["policy_id"] == policy_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, total = v.paginate(items, limit, offset)
    return resp.listing([store.serialize(m) for m in page], limit, offset, total)


@bp.get("/governance/legal-mandates/<mandate_id>")
def get_mandate(mandate_id):
    auth.authorize(auth.READ_ROLES_MANDATE)
    rec = v.find("mandates", mandate_id)
    return resp.ok(store.serialize(rec))
