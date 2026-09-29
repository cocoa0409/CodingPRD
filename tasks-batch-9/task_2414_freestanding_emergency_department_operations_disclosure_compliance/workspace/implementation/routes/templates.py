"""Disclosure template routes."""

from flask import Blueprint

import constants as C
from db import base_row, db, sorted_rows, touch
from domain import (
    append_ledger,
    get_facility,
    get_template,
    recompute_posture,
    rows_of,
    template_view,
)
from errors import ApiError
from response import created, ok, ok_list, paginate
from validate import (
    auth,
    body,
    pagination,
    query_enum,
    req_enum,
    req_enum_array,
    req_int,
    req_str,
)

bp = Blueprint("templates", __name__)


@bp.post("/facilities/<fid>/disclosure-templates")
def create_template(fid):
    auth("FacilityAdministrator")
    data = body()
    version_label = req_str(data, "version_label", 1, 40)
    supersedes = req_str(data, "supersedes_version_label", 1, 40, required=False)
    facility_fee_cents = req_int(data, "facility_fee_cents", minimum=0)
    observation_hourly_cents = req_int(data, "observation_hourly_cents", minimum=0)
    network_status_statement = req_enum(
        data, "network_status_statement", C.NETWORK_STATUS_STATEMENTS
    )
    required_signage_elements = req_enum_array(
        data, "required_signage_elements", C.SIGNAGE_ELEMENTS
    )

    facility = get_facility(fid)

    for existing in db.templates.values():
        if existing["facility_id"] == facility["id"] and existing["version_label"] == version_label:
            raise ApiError("ERR_DUPLICATE_TEMPLATE_VERSION")

    template = base_row()
    template.update(
        {
            "facility_id": facility["id"],
            "version_label": version_label,
            "supersedes_version_label": supersedes,
            "facility_fee_cents": facility_fee_cents,
            "observation_hourly_cents": observation_hourly_cents,
            "network_status_statement": network_status_statement,
            "required_signage_elements": list(required_signage_elements),
            "status": "DRAFT",
            "published_at": None,
            "published_by_user_id": None,
        }
    )
    db.templates[template["id"]] = template
    return created(template_view(template))


@bp.get("/facilities/<fid>/disclosure-templates")
def list_templates(fid):
    auth("FacilityAdministrator", "ComplianceOfficer", "RegistrationClerk")
    status = query_enum("status", C.TEMPLATE_STATUSES)
    limit, offset = pagination()
    facility = get_facility(fid)
    rows = rows_of(db.templates, facility_id=facility["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = paginate(rows, limit, offset)
    return ok_list([template_view(r) for r in page], limit, offset, len(rows))


@bp.get("/disclosure-templates/<tid>")
def read_template(tid):
    auth("FacilityAdministrator", "ComplianceOfficer", "RegistrationClerk")
    return ok(template_view(get_template(tid)))


@bp.post("/disclosure-templates/<tid>/publish")
def publish_template(tid):
    user_id, _ = auth("FacilityAdministrator")
    data = body()
    expected = req_int(data, "expected_facility_version", minimum=0)

    template = get_template(tid)
    facility = db.facilities[template["facility_id"]]

    if expected != facility["version"]:
        raise ApiError("ERR_STALE_FACILITY_VERSION")
    if template["status"] != "DRAFT":
        raise ApiError("ERR_TEMPLATE_NOT_PUBLISHABLE")

    for other in sorted_rows(list(db.templates.values())):
        if (
            other["facility_id"] == facility["id"]
            and other["status"] == "PUBLISHED"
            and other["id"] != template["id"]
        ):
            other["status"] = "RETIRED"
            touch(other)

    template["status"] = "PUBLISHED"
    template["published_at"] = db.clock
    template["published_by_user_id"] = user_id
    touch(template)

    facility["current_published_template_id"] = template["id"]
    append_ledger(
        facility,
        "TEMPLATE_PUBLISHED",
        "INFO",
        "DISCLOSURE_TEMPLATE",
        template["id"],
        "Disclosure template %s published for the facility." % template["version_label"],
        defect_counted=False,
    )
    touch(facility)
    recompute_posture(facility)
    return ok(template_view(template))
