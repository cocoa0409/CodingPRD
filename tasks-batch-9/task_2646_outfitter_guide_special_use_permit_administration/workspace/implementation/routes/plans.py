"""The annual operating plan review cycle (PRD 3.5)."""
from flask import Blueprint

import calc
import envelope
import security
import serialize
import shapes
import store
from errors import ApiError
from routes.common import match, qint, qstr
from security import ADMIN, ANY_ROLE, OFFICER, REPRESENTATIVE, SPECIALIST

bp = Blueprint("plans", __name__)

SECTION_NAMES = (
    "sanitation_section",
    "campsite_section",
    "stock_section",
    "resource_protection_section",
)
EDITABLE = ("DRAFT", "REVISION_REQUESTED")
PERMIT_OPERABLE = ("ISSUED", "ACTIVE", "SUSPENDED")


def section_object(data, field, required=True):
    if field not in data or data[field] is None:
        if required:
            shapes.bad(field, "is required")
        return None
    body = data[field]
    if not isinstance(body, dict):
        shapes.bad(field, "must be an object")
    return body


def plan_permit(plan):
    return store.get("permits", plan["permit_id"])


@bp.post("/osup/permits/<permit_id>/operating-plans")
def file_plan(permit_id):
    caller = security.authenticate((REPRESENTATIVE,))
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    security.require_owner(caller, permit["outfitter_id"])
    data = shapes.body()
    plan_year = shapes.req_int(data, "plan_year", minimum=1900, maximum=9999)
    sections = {name: section_object(data, name) for name in SECTION_NAMES}
    # priority 11: one live plan per permit and plan year
    for other in store.all_of("operating_plans"):
        if (
            other["permit_id"] == permit["id"]
            and other["plan_year"] == plan_year
            and other["status"] != "REJECTED"
        ):
            raise ApiError(
                "ERR_DUPLICATE_PLAN_YEAR", "a live plan already occupies this plan year"
            )
    plan = store.insert(
        "operating_plans",
        dict(
            {
                "permit_id": permit["id"],
                "plan_year": plan_year,
                "completeness_score": calc.rh(0, 1),
                "status": "DRAFT",
                "revision_round": 0,
                "deficiency_sections": [],
                "reviewed_by_user_id": None,
                "approved_by_user_id": None,
                "rejection_reason_code": None,
            },
            **sections
        ),
    )
    calc.recompute_plan_completeness(plan)
    return envelope.ok(serialize.operating_plan(plan), 201)


@bp.get("/osup/permits/<permit_id>/operating-plans")
def list_plans(permit_id):
    security.authenticate(ANY_ROLE, mutating=False)
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    filters = {"plan_year": qint("plan_year"), "status": qstr("status")}
    rows = [
        p
        for p in store.all_of("operating_plans")
        if p["permit_id"] == permit["id"] and match(p, **filters)
    ]
    return envelope.paginate(store.sort_created(rows), serialize.operating_plan)


@bp.get("/osup/operating-plans/<plan_id>")
def read_plan(plan_id):
    security.authenticate(ANY_ROLE, mutating=False)
    plan = store.get_or_404("operating_plans", plan_id, "ERR_OPERATING_PLAN_NOT_FOUND")
    return envelope.ok(serialize.operating_plan(plan))


@bp.post("/osup/operating-plans/<plan_id>/sections")
def replace_section(plan_id):
    caller = security.authenticate((REPRESENTATIVE,))
    plan = store.get_or_404("operating_plans", plan_id, "ERR_OPERATING_PLAN_NOT_FOUND")
    permit = plan_permit(plan)
    if permit is not None:
        security.require_owner(caller, permit["outfitter_id"])
    data = shapes.body()
    section_name = shapes.req_str(data, "section_name", allowed=SECTION_NAMES)
    section_body = section_object(data, "section_body")
    if plan["status"] not in EDITABLE:
        raise ApiError(
            "ERR_INVALID_PLAN_STATE", "sections may be replaced only before review"
        )
    plan[section_name] = section_body
    calc.recompute_plan_completeness(plan)
    store.touch(plan)
    return envelope.ok(serialize.operating_plan(plan))


@bp.post("/osup/operating-plans/<plan_id>/submit")
def submit_plan(plan_id):
    caller = security.authenticate((REPRESENTATIVE,))
    plan = store.get_or_404("operating_plans", plan_id, "ERR_OPERATING_PLAN_NOT_FOUND")
    permit = plan_permit(plan)
    if permit is not None:
        security.require_owner(caller, permit["outfitter_id"])
    previous = plan["status"]
    if previous not in EDITABLE:
        raise ApiError("ERR_INVALID_PLAN_STATE", "the plan cannot be submitted from here")
    if permit is None or permit["administrative_status"] not in PERMIT_OPERABLE:
        raise ApiError("ERR_PERMIT_NOT_OPERATIONAL", "the permit is not operable")
    calc.recompute_plan_completeness(plan)
    if plan["completeness_score"] != calc.Decimal("100.0"):
        raise ApiError(
            "ERR_OPERATING_PLAN_INCOMPLETE", "completeness_score must be exactly 100.0"
        )
    plan["status"] = "SUBMITTED"
    plan["deficiency_sections"] = []
    if previous == "REVISION_REQUESTED":
        # revision_round keeps its accumulated value; a fresh reviewer must take custody
        plan["reviewed_by_user_id"] = None
    store.touch(plan)
    return envelope.ok(serialize.operating_plan(plan))


@bp.post("/osup/operating-plans/<plan_id>/start-review")
def start_review(plan_id):
    caller = security.authenticate((SPECIALIST, OFFICER))
    plan = store.get_or_404("operating_plans", plan_id, "ERR_OPERATING_PLAN_NOT_FOUND")
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_PLAN_STATE", "only a SUBMITTED plan may be taken up")
    plan["status"] = "UNDER_REVIEW"
    plan["reviewed_by_user_id"] = caller.user_id
    store.touch(plan)
    return envelope.ok(serialize.operating_plan(plan))


@bp.post("/osup/operating-plans/<plan_id>/request-revision")
def request_revision(plan_id):
    security.authenticate((SPECIALIST, OFFICER))
    plan = store.get_or_404("operating_plans", plan_id, "ERR_OPERATING_PLAN_NOT_FOUND")
    data = shapes.body()
    if "deficiency_sections" not in data or data["deficiency_sections"] is None:
        shapes.bad("deficiency_sections", "is required")
    sections = data["deficiency_sections"]
    if not isinstance(sections, list):
        shapes.bad("deficiency_sections", "must be an array of section names")
    for entry in sections:
        if entry not in SECTION_NAMES:
            shapes.bad("deficiency_sections", "must name declared sections only")
    if plan["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_PLAN_STATE", "the plan is not UNDER_REVIEW")
    if plan["revision_round"] >= calc.MAX_REVISION_ROUNDS:
        raise ApiError(
            "ERR_REVISION_LIMIT_EXCEEDED", "the revision loop is exhausted; reject instead"
        )
    plan["status"] = "REVISION_REQUESTED"
    plan["revision_round"] = plan["revision_round"] + 1
    plan["deficiency_sections"] = list(sections)
    store.touch(plan)
    return envelope.ok(serialize.operating_plan(plan))


@bp.post("/osup/operating-plans/<plan_id>/approve")
def approve_plan(plan_id):
    caller = security.authenticate((OFFICER, ADMIN))
    plan = store.get_or_404("operating_plans", plan_id, "ERR_OPERATING_PLAN_NOT_FOUND")
    if plan["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_PLAN_STATE", "the plan is not UNDER_REVIEW")
    if plan["reviewed_by_user_id"] is not None and caller.user_id == plan["reviewed_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "the reviewer may not dispose of the same plan"
        )
    plan["status"] = "APPROVED"
    plan["approved_by_user_id"] = caller.user_id
    store.touch(plan)
    return envelope.ok(serialize.operating_plan(plan))


@bp.post("/osup/operating-plans/<plan_id>/reject")
def reject_plan(plan_id):
    caller = security.authenticate((OFFICER, ADMIN))
    plan = store.get_or_404("operating_plans", plan_id, "ERR_OPERATING_PLAN_NOT_FOUND")
    data = shapes.body()
    reason = shapes.req_str(data, "rejection_reason_code")
    if plan["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_PLAN_STATE", "the plan is not UNDER_REVIEW")
    if plan["reviewed_by_user_id"] is not None and caller.user_id == plan["reviewed_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "the reviewer may not dispose of the same plan"
        )
    plan["status"] = "REJECTED"
    plan["rejection_reason_code"] = reason
    store.touch(plan)
    return envelope.ok(serialize.operating_plan(plan))
