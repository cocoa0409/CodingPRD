"""Program lifecycle, its Courses, service scope, marketing ledger and teach-out plans."""

from flask import Blueprint, request

import constants as C
import db
import serializers
from db import bump_partnership_version, store, touch
from errors import ApiError, bad_request
from middleware import (authenticate, body, check_action_role, check_scope,
                        scope_filter)
from response import object_response
from routes.common import get_partnership, get_program, listing
from services import demand
from services.cascades import allocate_liability, enter_teach_out, plan_snapshot
from services.derive import recompute_partnership, recompute_program
from services.money import D, parse_iso_date
from validation import (CIP_RE, Field, enum_filter, pagination_args,
                        validate_body)

bp = Blueprint("programs", __name__)

READ_ALL = ("PlatformAdmin", "UniversityProvost", "UniversityBursar", "FacultyChair",
            "ComplianceAuditor", "PartnerAccountLead")
LEDGER_READ = ("PlatformAdmin", "UniversityProvost", "UniversityBursar",
               "ComplianceAuditor", "PartnerAccountLead")

CREATE_SPEC = {
    "partnership_id": Field("string", required=True),
    "program_name": Field("string", required=True),
    "cip_code": Field("string", required=True, pattern=CIP_RE),
    "delivery_modality": Field("enum", required=True, enum=C.DELIVERY_MODALITIES),
    "credential_level": Field("enum", required=True, enum=C.CREDENTIAL_LEVELS),
    "tuition_per_credit_cents": Field("integer", required=True),
    "credits_to_complete": Field("integer", required=True, minimum=0),
    "enrollment_cap": Field("integer", required=True, minimum=0),
    "projected_annual_enrollments": Field("integer", required=True, minimum=0),
    "competitor_program_count": Field("integer", required=True, minimum=0),
    "regional_wage_premium_pct": Field("number", required=True, minimum=0),
    "employer_partner_count": Field("integer", required=True, minimum=0),
    "prior_year_inquiry_volume": Field("integer", required=True, minimum=0),
    "launch_window_start": Field("date", required=True),
    "launch_window_end": Field("date", required=True),
    "required_service_domains": Field("string_array", item_enum=C.SERVICE_DOMAINS),
}

LIFECYCLE_SPEC = {
    "action": Field("enum", required=True, enum=tuple(C.LIFECYCLE_ACTION_ROLES)),
    "revised_projected_annual_enrollments": Field("integer", minimum=0),
    "revised_prior_year_inquiry_volume": Field("integer", minimum=0),
    "revision_note": Field("string"),
    "teach_out_reason": Field("string"),
}

COURSE_SPEC = {
    "course_code": Field("string", required=True),
    "title": Field("string", required=True),
    "credits": Field("integer", required=True, minimum=0),
    "content_owner": Field("enum", required=True, enum=C.CONTENT_OWNERS),
    "design_cost_cents": Field("integer", required=True),
    "required_for_launch": Field("boolean"),
    "prerequisite_course_id": Field("string", nullable=True),
    "ip_license_grant_back": Field("boolean"),
}

ASSIGNMENT_SPEC = {
    "service_domain": Field("enum", required=True, enum=C.SERVICE_DOMAINS),
    "responsible_party": Field("enum", required=True, enum=C.PARTIES),
    "sla_response_hours": Field("integer", minimum=0),
    "cost_bearer": Field("enum", enum=C.PARTIES),
}

MARKETING_SPEC = {
    "entry_type": Field("enum", required=True, enum=C.MARKETING_ENTRY_TYPES),
    "channel": Field("enum", required=True, enum=C.MARKETING_CHANNELS),
    "amount_cents": Field("integer", required=True),
    "spend_date": Field("date", required=True),
    "reversal_note": Field("string"),
}

PLAN_SPEC = {
    "teach_out_end_date": Field("date", required=True),
    "student_notification_date": Field("date", required=True),
    "asset_transfer_scope": Field("enum", required=True, enum=C.ASSET_TRANSFER_SCOPES),
    "partner_obligation_note": Field("string"),
}

TRANSITIONS = {
    "SUBMIT": (("DRAFT", "REVISION_REQUESTED"), "SUBMITTED"),
    "REQUEST_REVISION": (("SUBMITTED",), "REVISION_REQUESTED"),
    "APPROVE": (("SUBMITTED",), "APPROVED"),
    "REJECT": (("SUBMITTED",), "REJECTED"),
    "LAUNCH": (("APPROVED",), "LAUNCHED"),
    "SUSPEND": (("LAUNCHED",), "SUSPENDED"),
    "RESUME": (("SUSPENDED",), "LAUNCHED"),
    "BEGIN_TEACH_OUT": (("LAUNCHED", "SUSPENDED"), "TEACH_OUT"),
    "CLOSE": (("TEACH_OUT",), "CLOSED"),
}

PARENT_EXECUTED_ACTIONS = ("SUBMIT", "LAUNCH", "RESUME")


# --------------------------------------------------------------------------- #
# Program                                                                     #
# --------------------------------------------------------------------------- #

@bp.post("/programs")
def create():
    uid, role = authenticate(("PartnerAccountLead",))
    values = validate_body(body(), CREATE_SPEC)
    partnership = get_partnership(values["partnership_id"])
    check_scope(role, uid, partnership["id"])
    if partnership["status"] != "EXECUTED":
        raise ApiError("ERR_PARTNERSHIP_INVALID_STATE")

    program = db.base_entity()
    program.update({
        "partnership_id": partnership["id"],
        "program_name": values["program_name"],
        "cip_code": values["cip_code"],
        "delivery_modality": values["delivery_modality"],
        "credential_level": values["credential_level"],
        "tuition_per_credit_cents": values["tuition_per_credit_cents"],
        "credits_to_complete": values["credits_to_complete"],
        "enrollment_cap": values["enrollment_cap"],
        "projected_annual_enrollments": values["projected_annual_enrollments"],
        "competitor_program_count": values["competitor_program_count"],
        "regional_wage_premium_pct": values["regional_wage_premium_pct"],
        "employer_partner_count": values["employer_partner_count"],
        "prior_year_inquiry_volume": values["prior_year_inquiry_volume"],
        "launch_window_start": values["launch_window_start"],
        "launch_window_end": values["launch_window_end"],
        "required_service_domains": values.get(
            "required_service_domains", list(C.DEFAULT_REQUIRED_SERVICE_DOMAINS)),
        "status": "DRAFT",
        "revision_round": 0,
        "active_enrollment_count": 0,
        "total_enrollment_count": 0,
        "marketing_spend_net_cents": 0,
        "blended_cac_cents": None,
        "recognized_revenue_cents": 0,
        "launched_at": None,
        "teach_out_started_at": None,
        "closed_at": None,
    })
    program["demand_score_screening"] = demand.screening(program)
    program["demand_score_confirmed"] = demand.confirmed(program)
    store.programs[program["id"]] = program

    bump_partnership_version(partnership)
    return object_response(serializers.program(program), 201)


@bp.get("/programs/<program_id>")
def read(program_id):
    uid, role = authenticate(READ_ALL)
    program = get_program(program_id)
    check_scope(role, uid, program["partnership_id"])
    return object_response(serializers.program(program))


@bp.get("/programs")
def index():
    uid, role = authenticate(READ_ALL)
    limit, offset = pagination_args(request.args)
    status = enum_filter(request.args, "status", C.PROGRAM_STATUSES)
    partnership_id = scope_filter(role, uid, request.args.get("partnership_id"))
    cip = request.args.get("cip_code")

    items = db.sort_created(list(store.programs.values()))
    if partnership_id is not None:
        items = [p for p in items if p["partnership_id"] == partnership_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if cip is not None:
        items = [p for p in items if p["cip_code"] == cip]
    return listing(items, serializers.program, limit, offset)


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) semantics: touching windows do not overlap."""
    return a_start < b_end and b_start < a_end


def _check_cip_exclusivity(program, partnership):
    cip = program["cip_code"]
    start = parse_iso_date(program["launch_window_start"])
    end = parse_iso_date(program["launch_window_end"])
    for other in store.programs.values():
        if other["id"] == program["id"]:
            continue
        if other["status"] not in ("LAUNCHED", "SUSPENDED", "TEACH_OUT"):
            continue
        if other["cip_code"] != cip:
            continue
        other_partnership = store.partnerships.get(other["partnership_id"])
        if other_partnership is None:  # pragma: no cover
            continue
        if other_partnership["university_ipeds_id"] != partnership["university_ipeds_id"]:
            continue
        if (cip not in (partnership["exclusivity_cip_codes"] or [])
                and cip not in (other_partnership["exclusivity_cip_codes"] or [])):
            continue
        if _windows_overlap(start, end,
                            parse_iso_date(other["launch_window_start"]),
                            parse_iso_date(other["launch_window_end"])):
            raise ApiError("ERR_CIP_EXCLUSIVITY_CONFLICT")


@bp.post("/programs/<program_id>/lifecycle-actions")
def lifecycle(program_id):
    uid, role = authenticate(("PartnerAccountLead", "UniversityProvost"))
    values = validate_body(body(), LIFECYCLE_SPEC)
    action = values["action"]
    check_action_role(role, action, C.LIFECYCLE_ACTION_ROLES)

    program = get_program(program_id)
    check_scope(role, uid, program["partnership_id"])
    partnership = get_partnership(program["partnership_id"])

    if action in PARENT_EXECUTED_ACTIONS and partnership["status"] != "EXECUTED":
        raise ApiError("ERR_PARTNERSHIP_INVALID_STATE")

    sources, target = TRANSITIONS[action]
    if program["status"] not in sources:
        raise ApiError("ERR_PROGRAM_INVALID_STATE")

    today = db.current_date()

    if action == "SUBMIT":
        if not db.courses_of(program["id"]):
            raise ApiError("ERR_NO_COURSES_DEFINED")
        candidate = dict(program)
        if "revised_projected_annual_enrollments" in values:
            candidate["projected_annual_enrollments"] = \
                values["revised_projected_annual_enrollments"]
        if "revised_prior_year_inquiry_volume" in values:
            candidate["prior_year_inquiry_volume"] = \
                values["revised_prior_year_inquiry_volume"]
        score = demand.demand_score(candidate, "SCREENING")
        if score < D(C.SUBMIT_MIN_SCORE):
            raise ApiError("ERR_DEMAND_SCORE_BELOW_SUBMIT_THRESHOLD")
        program["projected_annual_enrollments"] = candidate["projected_annual_enrollments"]
        program["prior_year_inquiry_volume"] = candidate["prior_year_inquiry_volume"]
        program["demand_score_screening"] = float(score)

    elif action == "REQUEST_REVISION":
        program["revision_round"] += 1

    elif action == "APPROVE":
        assigned = {a["service_domain"] for a in db.assignments_of(program["id"])}
        for domain in program["required_service_domains"]:
            if domain not in assigned:
                raise ApiError("ERR_SERVICE_SCOPE_INCOMPLETE")
        for course in db.courses_of(program["id"]):
            if course["required_for_launch"] and course["design_status"] != "APPROVED":
                raise ApiError("ERR_COURSE_DESIGN_INCOMPLETE")
        score = demand.demand_score(program, "CONFIRMED")
        if score < D(C.APPROVAL_MIN_SCORE):
            raise ApiError("ERR_DEMAND_SCORE_BELOW_APPROVAL_THRESHOLD")
        program["demand_score_confirmed"] = float(score)

    elif action == "LAUNCH":
        if today > parse_iso_date(partnership["expiry_date"]):
            raise ApiError("ERR_CONTRACT_TERM_EXPIRED")
        if not (parse_iso_date(program["launch_window_start"]) <= today
                < parse_iso_date(program["launch_window_end"])):
            raise ApiError("ERR_OUTSIDE_LAUNCH_WINDOW")
        _check_cip_exclusivity(program, partnership)
        program["launched_at"] = db.now_iso()

    elif action == "RESUME":
        if today > parse_iso_date(partnership["expiry_date"]):
            raise ApiError("ERR_CONTRACT_TERM_EXPIRED")

    elif action == "CLOSE":
        certified = any(plan["status"] == "CERTIFIED"
                        for plan in db.plans_of(program["id"]))
        recompute_program(program)
        if not certified or program["active_enrollment_count"] != 0:
            raise ApiError("ERR_TEACH_OUT_OBLIGATIONS_UNMET")
        program["closed_at"] = db.now_iso()

    if action == "BEGIN_TEACH_OUT":
        enter_teach_out(program)
    else:
        program["status"] = target
        touch(program)

    return object_response(serializers.program(program))


# --------------------------------------------------------------------------- #
# Courses of a Program                                                        #
# --------------------------------------------------------------------------- #

def check_prerequisite_cycle(program_id, course_id, prerequisite_id):
    """Follow prerequisite_course_id transitively; a self-edge is a cycle."""
    if prerequisite_id is None:
        return
    if prerequisite_id == course_id:
        raise ApiError("ERR_PREREQUISITE_CYCLE")
    seen = set()
    current = prerequisite_id
    while current is not None:
        if current in seen:
            return
        seen.add(current)
        node = store.courses.get(current)
        if node is None:  # pragma: no cover
            return
        nxt = node.get("prerequisite_course_id")
        if nxt == course_id:
            raise ApiError("ERR_PREREQUISITE_CYCLE")
        current = nxt


def resolve_prerequisite(program_id, prerequisite_id):
    course = store.courses.get(prerequisite_id)
    if course is None or course["program_id"] != program_id:
        raise ApiError("ERR_PREREQUISITE_COURSE_NOT_FOUND")
    return course


@bp.post("/programs/<program_id>/courses")
def create_course(program_id):
    uid, role = authenticate(("PartnerAccountLead", "FacultyChair"))
    values = validate_body(body(), COURSE_SPEC)
    program = get_program(program_id)

    prerequisite_id = values.get("prerequisite_course_id")
    if prerequisite_id is not None:
        resolve_prerequisite(program["id"], prerequisite_id)

    check_scope(role, uid, program["partnership_id"])

    if program["status"] not in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED"):
        raise ApiError("ERR_PROGRAM_INVALID_STATE")

    course = db.base_entity()
    check_prerequisite_cycle(program["id"], course["id"], prerequisite_id)

    course.update({
        "program_id": program["id"],
        "prerequisite_course_id": prerequisite_id,
        "course_code": values["course_code"],
        "title": values["title"],
        "credits": values["credits"],
        "required_for_launch": values.get("required_for_launch", True),
        "content_owner": values["content_owner"],
        "ip_license_grant_back": values.get("ip_license_grant_back", False),
        "design_cost_cents": values["design_cost_cents"],
        "design_status": "NOT_STARTED",
        "faculty_approver_name": None,
        "revision_round": 0,
    })
    store.courses[course["id"]] = course
    return object_response(serializers.course(course), 201)


# --------------------------------------------------------------------------- #
# ServiceScopeAssignment                                                      #
# --------------------------------------------------------------------------- #

@bp.post("/programs/<program_id>/service-scope-assignments")
def create_assignment(program_id):
    authenticate(("UniversityProvost",))
    values = validate_body(body(), ASSIGNMENT_SPEC)
    program = get_program(program_id)

    if program["status"] not in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED"):
        raise ApiError("ERR_PROGRAM_INVALID_STATE")

    domain = values["service_domain"]
    if domain in C.NON_DELEGABLE_DOMAINS and values["responsible_party"] != "UNIVERSITY":
        raise ApiError("ERR_NON_DELEGABLE_SERVICE_DOMAIN")

    for existing in db.assignments_of(program["id"]):
        if existing["service_domain"] == domain:
            raise ApiError("ERR_DUPLICATE_SERVICE_DOMAIN")

    assignment = db.base_entity()
    assignment.update({
        "program_id": program["id"],
        "service_domain": domain,
        "responsible_party": values["responsible_party"],
        "sla_response_hours": values.get("sla_response_hours", 24),
        "cost_bearer": values.get("cost_bearer", "PARTNER"),
    })
    store.service_scope_assignments[assignment["id"]] = assignment
    return object_response(serializers.assignment(assignment), 201)


@bp.get("/programs/<program_id>/service-scope-assignments")
def list_assignments(program_id):
    uid, role = authenticate(READ_ALL)
    limit, offset = pagination_args(request.args)
    program = get_program(program_id)
    check_scope(role, uid, program["partnership_id"])
    return listing(db.assignments_of(program["id"]), serializers.assignment,
                   limit, offset)


# --------------------------------------------------------------------------- #
# marketing ledger                                                            #
# --------------------------------------------------------------------------- #

@bp.post("/programs/<program_id>/marketing-spend-entries")
def create_marketing_entry(program_id):
    uid, role = authenticate(("PartnerAccountLead",))
    values = validate_body(body(), MARKETING_SPEC)
    if values["entry_type"] == "CREDIT_MEMO" and not values.get("reversal_note"):
        raise bad_request("reversal_note is required on a CREDIT_MEMO entry.")

    program = get_program(program_id)
    check_scope(role, uid, program["partnership_id"])
    partnership = get_partnership(program["partnership_id"])
    if partnership["status"] != "EXECUTED":
        raise ApiError("ERR_PARTNERSHIP_INVALID_STATE")

    if (values["entry_type"] == "SPEND"
            and values["amount_cents"] > partnership["marketing_budget_remaining_cents"]):
        raise ApiError("ERR_MARKETING_BUDGET_EXCEEDED")

    entry = db.base_entity(full=False)
    entry.update({
        "program_id": program["id"],
        "entry_type": values["entry_type"],
        "channel": values["channel"],
        "amount_cents": values["amount_cents"],
        "spend_date": values["spend_date"],
        "reversal_note": values.get("reversal_note"),
    })
    store.marketing_entries[entry["id"]] = entry

    recompute_program(program)
    recompute_partnership(partnership)
    return object_response(serializers.marketing_entry(entry), 201)


@bp.get("/programs/<program_id>/marketing-spend-entries")
def list_marketing_entries(program_id):
    uid, role = authenticate(LEDGER_READ)
    limit, offset = pagination_args(request.args)
    program = get_program(program_id)
    check_scope(role, uid, program["partnership_id"])
    return listing(db.marketing_of(program["id"]), serializers.marketing_entry,
                   limit, offset)


# --------------------------------------------------------------------------- #
# teach-out plans                                                             #
# --------------------------------------------------------------------------- #

@bp.post("/programs/<program_id>/teach-out-plans")
def create_plan(program_id):
    authenticate(("UniversityProvost",))
    values = validate_body(body(), PLAN_SPEC)
    program = get_program(program_id)

    if program["status"] != "TEACH_OUT":
        raise ApiError("ERR_PROGRAM_INVALID_STATE")

    for existing in db.plans_of(program["id"]):
        if existing["status"] == "DRAFT":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    affected, remaining, cost = plan_snapshot(program)
    plan = db.base_entity()
    plan.update({
        "program_id": program["id"],
        "teach_out_end_date": values["teach_out_end_date"],
        "student_notification_date": values["student_notification_date"],
        "asset_transfer_scope": values["asset_transfer_scope"],
        "status": "DRAFT",
        "affected_enrollment_count": affected,
        "remaining_credit_count": remaining,
        "teach_out_cost_cents": cost,
        "holdback_applied_cents": 0,
        "partner_obligation_cents": 0,
        "university_residual_cents": 0,
        "transferred_asset_value_cents": 0,
        "partner_obligation_note": values.get("partner_obligation_note"),
        "certified_by_user_id": None,
        "certified_at": None,
    })
    store.teach_out_plans[plan["id"]] = plan
    return object_response(serializers.teach_out_plan(plan), 201)


@bp.get("/programs/<program_id>/teach-out-plans")
def list_plans(program_id):
    uid, role = authenticate(LEDGER_READ)
    limit, offset = pagination_args(request.args)
    program = get_program(program_id)
    check_scope(role, uid, program["partnership_id"])
    return listing(db.plans_of(program["id"]), serializers.teach_out_plan,
                   limit, offset)
