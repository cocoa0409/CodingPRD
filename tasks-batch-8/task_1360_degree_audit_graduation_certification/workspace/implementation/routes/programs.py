"""Program, RequirementGroup, HonorsPolicy routes + program reverse-lookup lists."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import get_auth, parse_pagination, require_roles
from response import success_list, success_object
from util import (
    as_enum,
    as_int,
    as_number,
    as_str,
    as_str_list,
    json_body,
    make_resource,
    optional,
    paginate,
    require,
    touch,
)

bp = Blueprint("programs", __name__)

DEGREE_TYPES = ("ASSOCIATE", "BACHELOR", "MASTER")
GPA_BASES = ("INSTITUTIONAL", "CUMULATIVE")
MIN_GRADES = ("A", "B", "C", "D")


def _get_program_or_404(program_id):
    p = db.programs.get(program_id)
    if p is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND", "Program not found.")
    return p


# ---------------------------------------------------------------------------
# POST /programs
# ---------------------------------------------------------------------------


@bp.route("/programs", methods=["POST"])
def create_program():
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    body = json_body()

    program_code = as_str(require(body, "program_code"), "program_code")
    name = as_str(require(body, "name"), "name")
    degree_type = as_enum(require(body, "degree_type"), "degree_type", DEGREE_TYPES)
    min_total_credits = as_number(require(body, "min_total_credits"), "min_total_credits")
    min_gpa = as_number(require(body, "min_gpa"), "min_gpa")
    catalog_year_start = as_int(require(body, "catalog_year_start"), "catalog_year_start")
    catalog_year_end = as_int(require(body, "catalog_year_end"), "catalog_year_end")

    if catalog_year_end <= catalog_year_start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "catalog_year_end must be > catalog_year_start.",
        )

    # Half-open overlap check per program_code
    for p in db.programs.values():
        if p["program_code"] != program_code:
            continue
        # [start,end) overlap: a.start < b.end AND b.start < a.end
        if catalog_year_start < p["catalog_year_end"] and p["catalog_year_start"] < catalog_year_end:
            raise ApiError(
                "ERR_CATALOG_RANGE_OVERLAP",
                "Catalog-year range overlaps another version of the same program_code.",
            )

    program = make_resource(
        {
            "program_code": program_code,
            "name": name,
            "degree_type": degree_type,
            "min_total_credits": min_total_credits,
            "min_gpa": min_gpa,
            "catalog_year_start": catalog_year_start,
            "catalog_year_end": catalog_year_end,
            "status": "ACTIVE",
        }
    )
    db.programs[program["id"]] = program
    return success_object(program, 201)


# ---------------------------------------------------------------------------
# GET /programs/{id}
# ---------------------------------------------------------------------------


@bp.route("/programs/<program_id>", methods=["GET"])
def get_program(program_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor", "Student"))
    return success_object(_get_program_or_404(program_id))


# ---------------------------------------------------------------------------
# POST /programs/{id}/retire
# ---------------------------------------------------------------------------


@bp.route("/programs/<program_id>/retire", methods=["POST"])
def retire_program(program_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    program = _get_program_or_404(program_id)
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_INVALID_STATE", "Program must be ACTIVE to retire.")
    program["status"] = "RETIRED"
    touch(program)
    return success_object(program)


# ---------------------------------------------------------------------------
# POST /programs/{id}/requirement-groups
# ---------------------------------------------------------------------------


@bp.route("/programs/<program_id>/requirement-groups", methods=["POST"])
def create_requirement_group(program_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    program = _get_program_or_404(program_id)
    body = json_body()

    group_code = as_str(require(body, "group_code"), "group_code")
    required_credits = as_number(require(body, "required_credits"), "required_credits")
    min_grade = as_enum(require(body, "min_grade"), "min_grade", MIN_GRADES)
    eligible_course_codes = as_str_list(
        require(body, "eligible_course_codes"), "eligible_course_codes"
    )

    # Uniqueness of group_code within the program
    for g in db.requirement_groups.values():
        if g["program_id"] == program["id"] and g["group_code"] == group_code:
            raise ApiError(
                "ERR_UNIQUE_CONSTRAINT_VIOLATION",
                "group_code must be unique within the program.",
            )

    group = make_resource(
        {
            "program_id": program["id"],
            "group_code": group_code,
            "required_credits": required_credits,
            "min_grade": min_grade,
            "eligible_course_codes": list(eligible_course_codes),
        }
    )
    db.requirement_groups[group["id"]] = group
    return success_object(group, 201)


# ---------------------------------------------------------------------------
# GET /programs/{id}/requirement-groups
# ---------------------------------------------------------------------------


@bp.route("/programs/<program_id>/requirement-groups", methods=["GET"])
def list_requirement_groups(program_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor", "Student"))
    program = _get_program_or_404(program_id)
    limit, offset = parse_pagination()
    items = [g for g in db.requirement_groups.values() if g["program_id"] == program["id"]]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# POST /programs/{id}/honors-policies
# ---------------------------------------------------------------------------


@bp.route("/programs/<program_id>/honors-policies", methods=["POST"])
def create_honors_policy(program_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    program = _get_program_or_404(program_id)
    body = json_body()

    basis = as_enum(require(body, "honors_gpa_basis"), "honors_gpa_basis", GPA_BASES)
    cum_threshold = as_number(require(body, "cum_threshold"), "cum_threshold")
    magna_threshold = as_number(require(body, "magna_threshold"), "magna_threshold")
    summa_threshold = as_number(require(body, "summa_threshold"), "summa_threshold")
    first = as_int(require(body, "effective_first_year"), "effective_first_year")
    last = as_int(require(body, "effective_last_year"), "effective_last_year")
    residency = optional(body, "residency_min_credits", 30)
    if residency is not None:
        residency = as_int(residency, "residency_min_credits")
    else:
        residency = 30

    if last < first:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "effective_last_year must be >= effective_first_year.",
        )

    # Closed-interval overlap within the same program (shared boundary IS overlap)
    for p in db.honors_policies.values():
        if p["program_id"] != program["id"]:
            continue
        if first <= p["effective_last_year"] and p["effective_first_year"] <= last:
            raise ApiError(
                "ERR_POLICY_RANGE_OVERLAP",
                "Honors-policy effective range overlaps another policy of the program.",
            )

    policy = make_resource(
        {
            "program_id": program["id"],
            "honors_gpa_basis": basis,
            "cum_threshold": cum_threshold,
            "magna_threshold": magna_threshold,
            "summa_threshold": summa_threshold,
            "effective_first_year": first,
            "effective_last_year": last,
            "residency_min_credits": residency,
        }
    )
    db.honors_policies[policy["id"]] = policy
    return success_object(policy, 201)


# ---------------------------------------------------------------------------
# GET /programs/{id}/honors-policies
# ---------------------------------------------------------------------------


@bp.route("/programs/<program_id>/honors-policies", methods=["GET"])
def list_honors_policies(program_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor", "Student"))
    program = _get_program_or_404(program_id)
    limit, offset = parse_pagination()
    items = [p for p in db.honors_policies.values() if p["program_id"] == program["id"]]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# GET /programs/{id}/student-programs  (FK reverse)
# ---------------------------------------------------------------------------


@bp.route("/programs/<program_id>/student-programs", methods=["GET"])
def list_program_student_programs(program_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor"))
    program = _get_program_or_404(program_id)
    limit, offset = parse_pagination()
    items = [sp for sp in db.student_programs.values() if sp["program_id"] == program["id"]]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# GET /programs/{id}/audits  (FK reverse for target_program_id)
# ---------------------------------------------------------------------------


@bp.route("/programs/<program_id>/audits", methods=["GET"])
def list_program_audits(program_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor"))
    program = _get_program_or_404(program_id)
    limit, offset = parse_pagination()
    items = [
        a for a in db.degree_audits.values() if a["target_program_id"] == program["id"]
    ]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)
