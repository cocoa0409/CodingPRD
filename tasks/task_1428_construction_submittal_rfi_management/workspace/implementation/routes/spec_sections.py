"""SpecSection routes: CRUD, activate (register generation), lock."""
from flask import Blueprint, request

from authz import ALL_ROLES, PROJECT_ENGINEER, require_roles
import calc
from db import store
from errors import (
    invalid_request,
    project_not_found,
    spec_section_not_active,
    spec_section_not_draft,
    spec_section_not_found,
    subcontractor_not_found,
)
from respond import success
from serialize import ser_spec_section
from services import require_setup_or_active
from store_ops import (
    json_body,
    new_common_fields,
    new_id,
    opt_date,
    opt_enum,
    opt_int,
    opt_str,
    opt_str_list,
    paginate,
    req_str,
    sorted_by_creation,
    touch,
)

bp = Blueprint("spec_sections", __name__)

DISCIPLINES = ("ARCH", "STRUCT", "MEP", "CIVIL")
SUBMITTAL_KINDS = ("PRODUCT_DATA", "SHOP_DRAWINGS", "SAMPLES", "MOCKUP", "CERTIFICATES", "O_AND_M_MANUALS")


def get_section_or_404(section_id):
    s = store.spec_sections.get(section_id)
    if s is None:
        raise spec_section_not_found()
    return s


def _parse_kinds(data, default):
    if "required_submittal_kinds" not in data or data["required_submittal_kinds"] is None:
        return list(default)
    v = data["required_submittal_kinds"]
    if not isinstance(v, list):
        raise invalid_request("required_submittal_kinds must be an array")
    if len(v) == 0:
        raise invalid_request("required_submittal_kinds must not be empty")
    seen = set()
    for k in v:
        if k not in SUBMITTAL_KINDS:
            raise invalid_request("required_submittal_kinds members must be valid kinds")
        if k in seen:
            raise invalid_request("required_submittal_kinds members must be unique")
        seen.add(k)
    return list(v)


@bp.route("/v1/projects/<projectId>/spec-sections", methods=["POST"])
def create_section(projectId):
    require_roles([PROJECT_ENGINEER])
    project = store.projects.get(projectId)
    if project is None:
        raise project_not_found()
    require_setup_or_active(project)
    data = json_body()
    section_number = req_str(data, "section_number")
    # Uniqueness within project
    for s in store.spec_sections.values():
        if s["project_id"] == projectId and s["section_number"] == section_number:
            raise invalid_request("section_number must be unique within project")
    title = opt_str(data, "title", "")
    lead_time_days = opt_int(data, "lead_time_days", 14, minimum=0)
    review_days = opt_int(data, "review_days", 10, minimum=1)
    required_discipline = opt_enum(data, "required_discipline", DISCIPLINES, "ARCH")
    default_need_date = opt_date(data, "default_need_date", None)
    responsible_subcontractor_id = opt_str(data, "responsible_subcontractor_id", None)
    if responsible_subcontractor_id is not None:
        sub = store.subcontractors.get(responsible_subcontractor_id)
        if sub is None or sub["project_id"] != projectId:
            raise subcontractor_not_found()
    kinds = _parse_kinds(data, ["PRODUCT_DATA"])

    section = {
        "id": new_id(),
        "_seq": next(store.seq),
        **new_common_fields(),
        "project_id": projectId,
        "section_number": section_number,
        "title": title,
        "lead_time_days": lead_time_days,
        "review_days": review_days,
        "required_discipline": required_discipline,
        "default_need_date": default_need_date,
        "responsible_subcontractor_id": responsible_subcontractor_id,
        "required_submittal_kinds": kinds,
        "status": "DRAFT",
    }
    store.spec_sections[section["id"]] = section
    return success(ser_spec_section(section), status=201)


@bp.route("/v1/projects/<projectId>/spec-sections", methods=["GET"])
def list_project_sections(projectId):
    require_roles(ALL_ROLES)
    project = store.projects.get(projectId)
    if project is None:
        raise project_not_found()
    items = sorted_by_creation(
        [s for s in store.spec_sections.values() if s["project_id"] == projectId]
    )
    page, pagination = paginate(items)
    return success([ser_spec_section(s) for s in page], response_type="array", pagination=pagination)


@bp.route("/v1/spec-sections", methods=["GET"])
def list_sections():
    require_roles(ALL_ROLES)
    items = list(store.spec_sections.values())
    project_id = request.args.get("project_id")
    if project_id:
        items = [s for s in items if s["project_id"] == project_id]
    responsible = request.args.get("responsible_subcontractor_id")
    if responsible:
        items = [s for s in items if s.get("responsible_subcontractor_id") == responsible]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_spec_section(s) for s in page], response_type="array", pagination=pagination)


@bp.route("/v1/spec-sections/<sectionId>", methods=["GET"])
def get_section(sectionId):
    require_roles(ALL_ROLES)
    section = get_section_or_404(sectionId)
    return success(ser_spec_section(section))


@bp.route("/v1/spec-sections/<sectionId>", methods=["PATCH"])
def patch_section(sectionId):
    require_roles([PROJECT_ENGINEER])
    section = get_section_or_404(sectionId)
    if section["status"] != "DRAFT":
        raise spec_section_not_draft()
    data = json_body()
    if "section_number" in data and data["section_number"] is not None:
        new_number = req_str(data, "section_number")
        for s in store.spec_sections.values():
            if (
                s["project_id"] == section["project_id"]
                and s["id"] != section["id"]
                and s["section_number"] == new_number
            ):
                raise invalid_request("section_number must be unique within project")
        section["section_number"] = new_number
    if "title" in data and data["title"] is not None:
        section["title"] = req_str(data, "title")
    if "lead_time_days" in data and data["lead_time_days"] is not None:
        section["lead_time_days"] = opt_int(data, "lead_time_days", None, minimum=0)
    if "review_days" in data and data["review_days"] is not None:
        section["review_days"] = opt_int(data, "review_days", None, minimum=1)
    if "required_discipline" in data and data["required_discipline"] is not None:
        section["required_discipline"] = opt_enum(data, "required_discipline", DISCIPLINES)
    if "default_need_date" in data:
        section["default_need_date"] = opt_date(data, "default_need_date", None)
    if "responsible_subcontractor_id" in data:
        rsid = opt_str(data, "responsible_subcontractor_id", None)
        if rsid is not None:
            sub = store.subcontractors.get(rsid)
            if sub is None or sub["project_id"] != section["project_id"]:
                raise subcontractor_not_found()
        section["responsible_subcontractor_id"] = rsid
    if "required_submittal_kinds" in data and data["required_submittal_kinds"] is not None:
        section["required_submittal_kinds"] = _parse_kinds(data, ["PRODUCT_DATA"])
    touch(section)
    return success(ser_spec_section(section))


@bp.route("/v1/spec-sections/<sectionId>/activate", methods=["POST"])
def activate_section(sectionId):
    require_roles([PROJECT_ENGINEER])
    section = get_section_or_404(sectionId)
    project = store.projects.get(section["project_id"])
    if project is None:
        raise project_not_found()
    if section["status"] != "DRAFT":
        raise spec_section_not_draft()
    require_setup_or_active(project)

    # Register generation: one Submittal per required kind, in array order.
    for idx, kind in enumerate(section["required_submittal_kinds"], start=1):
        item_number = "%s-%02d" % (section["section_number"], idx)
        is_long_lead = section["lead_time_days"] >= project["long_lead_threshold_days"]
        submittal = {
            "id": new_id(),
            "_seq": next(store.seq),
            **new_common_fields(),
            "project_id": project["id"],
            "spec_section_id": section["id"],
            "submittal_kind": kind,
            "item_number": item_number,
            "required_on_site_date": section.get("default_need_date"),
            "required_approval_date": None,
            "required_submission_date": None,
            "is_long_lead": is_long_lead,
            "review_status": "REGISTERED",
            "expediting_status": "NOT_REQUIRED",
            "deferral_status": "NONE",
            "revision_count": 0,
        }
        calc.recompute_submittal_dates(submittal, section, project)
        store.submittals[submittal["id"]] = submittal
        if is_long_lead:
            lli = {
                "id": new_id(),
                "_seq": next(store.seq),
                **new_common_fields(),
                "project_id": project["id"],
                "submittal_id": submittal["id"],
                "description": "",
                "criticality": "STANDARD",
                "status": "IDENTIFIED",
                "required_on_site_date": submittal["required_on_site_date"],
                "days_late": 0,
                "escalation_level": 0,
                "priority_score": 0,
                "quoted_date": None,
                "po_issued_date": None,
                "shipped_date": None,
                "delivered_date": None,
            }
            calc.recompute_lli(lli, submittal)
            store.long_lead_items[lli["id"]] = lli
            submittal["expediting_status"] = "MONITORING"
    section["status"] = "ACTIVE"
    touch(section)
    return success(ser_spec_section(section))


@bp.route("/v1/spec-sections/<sectionId>/lock", methods=["POST"])
def lock_section(sectionId):
    require_roles([PROJECT_ENGINEER])
    section = get_section_or_404(sectionId)
    if section["status"] != "ACTIVE":
        raise spec_section_not_active()
    section["status"] = "LOCKED"
    touch(section)
    return success(ser_spec_section(section))
