"""Review protocol authoring, submission and the client decision (PRD 3.2)."""

from flask import Blueprint, request

from db import base_row, by_creation, db, touch
from errors import ApiError
from middleware import (
    ROLE_CLIENT_COUNSEL,
    ROLE_ENGAGEMENT_MANAGER,
    ROLE_QC_LEAD,
    ROLE_REVIEWER,
    ROLE_STAFFING_COORDINATOR,
    body,
    require_roles,
)
from response import created_response, object_response, paginated
from routes.matters import require_matter_client, require_not_suspended
from services import cascade, compute
from validation import (
    opt_bool,
    opt_str,
    req_enum,
    req_enum_array,
    req_fraction,
    req_int,
    req_tag_array,
)

bp = Blueprint("protocols", __name__)

PRIVILEGE_CRITERIA = ("ATTORNEY_CLIENT", "WORK_PRODUCT", "COMMON_INTEREST")
DECISIONS = ("APPROVE", "REQUEST_CHANGES")


@bp.route("/matters/<matter_id>/protocols", methods=["POST"])
def mint_protocol(matter_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER)
    matter = compute.get_matter(matter_id)
    payload = body()

    expected_matter_version = req_int(payload, "expected_matter_version")
    issue_codes = req_tag_array(payload, "issue_codes", allow_empty=False)
    privilege_criteria = req_enum_array(payload, "privilege_criteria",
                                        PRIVILEGE_CRITERIA, allow_empty=False)
    qc_sample_pct = req_fraction(payload, "qc_sample_pct", "0.01", "1.00")
    privilege_sample_pct = req_fraction(payload, "privilege_sample_pct", "0.01", "1.00")
    max_discrepancy_pct = req_fraction(payload, "max_discrepancy_pct", "0.001", "0.500")
    min_pace_dph = req_int(payload, "min_pace_dph", 1)
    second_level_required = opt_bool(payload, "second_level_required", True)

    # Rank 10 - optimistic concurrency on the parent matter.
    if expected_matter_version != matter["version"]:
        raise ApiError("ERR_STALE_MATTER_VERSION",
                       "The matter has moved on since it was last read.")

    existing = compute.protocols_of_matter(matter["id"])
    if not existing:
        if matter["status"] != "INTAKE":
            raise ApiError("ERR_INVALID_STATE",
                           "Revision 1 may only be minted while the matter is in INTAKE.")
    else:
        if matter["status"] not in ("STAFFING", "IN_REVIEW"):
            raise ApiError("ERR_INVALID_STATE",
                           "A later revision may only be minted from STAFFING or IN_REVIEW.")

    for protocol in existing:
        if protocol["status"] in ("DRAFT", "CLIENT_REVIEW", "APPROVED"):
            protocol["status"] = "SUPERSEDED"
            touch(protocol)

    revision_number = 1
    if existing:
        revision_number = max(p["revision_number"] for p in existing) + 1

    row = base_row()
    row.update({
        "matter_id": matter["id"],
        "revision_number": revision_number,
        "issue_codes": issue_codes,
        "privilege_criteria": privilege_criteria,
        "qc_sample_pct": qc_sample_pct,
        "privilege_sample_pct": privilege_sample_pct,
        "max_discrepancy_pct": max_discrepancy_pct,
        "min_pace_dph": min_pace_dph,
        "second_level_required": second_level_required,
        "status": "DRAFT",
        "change_notes": None,
        "approved_at": None,
    })
    db.protocols[row["id"]] = row

    matter["status"] = "PROTOCOL_PENDING"
    touch(matter)
    return created_response(compute.protocol_out(row))


@bp.route("/protocols/<protocol_id>", methods=["GET"])
def read_protocol(protocol_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR, ROLE_QC_LEAD,
                  ROLE_REVIEWER, ROLE_CLIENT_COUNSEL)
    protocol = compute.get_protocol(protocol_id)
    return object_response(compute.protocol_out(protocol))


@bp.route("/protocols", methods=["GET"])
def list_protocols():
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR, ROLE_QC_LEAD,
                  ROLE_REVIEWER, ROLE_CLIENT_COUNSEL)
    rows = by_creation(list(db.protocols.values()))
    matter_id = request.args.get("matter_id")
    status = request.args.get("status")
    if matter_id:
        rows = [r for r in rows if r["matter_id"] == matter_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginated(rows, compute.protocol_out)


@bp.route("/protocols/<protocol_id>/submit", methods=["POST"])
def submit_protocol(protocol_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER)
    protocol = compute.get_protocol(protocol_id)
    matter = compute.get_matter(protocol["matter_id"])
    if protocol["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT revision may be submitted.")
    require_not_suspended(matter)
    protocol["status"] = "CLIENT_REVIEW"
    touch(protocol)
    return object_response(compute.protocol_out(protocol))


@bp.route("/protocols/<protocol_id>/client-decision", methods=["POST"])
def client_decision(protocol_id):
    require_roles(ROLE_CLIENT_COUNSEL)
    protocol = compute.get_protocol(protocol_id)
    matter = compute.get_matter(protocol["matter_id"])
    require_matter_client(matter)
    payload = body()
    decision = req_enum(payload, "decision", DECISIONS)
    change_notes = opt_str(payload, "change_notes", 1, 2000, None)
    if decision == "REQUEST_CHANGES" and (change_notes is None or change_notes.strip() == ""):
        raise ApiError("ERR_INVALID_REQUEST",
                       "'change_notes' must be supplied and non-blank on REQUEST_CHANGES.")
    if protocol["status"] != "CLIENT_REVIEW":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a CLIENT_REVIEW revision may receive a client decision.")
    require_not_suspended(matter)

    if decision == "REQUEST_CHANGES":
        protocol["status"] = "DRAFT"
        protocol["change_notes"] = change_notes
        touch(protocol)
        return object_response(compute.protocol_out(protocol))

    protocol["status"] = "APPROVED"
    protocol["approved_at"] = db.now_iso()
    touch(protocol)
    if matter["status"] == "PROTOCOL_PENDING":
        matter["status"] = "STAFFING"
        touch(matter)
        cascade.sync_matter_staffing(matter)
    return object_response(compute.protocol_out(protocol))
