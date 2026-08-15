"""ComplianceDisclosure endpoints — draft, submit, approve, reject (revision loop)."""

from flask import Blueprint, request

import errors
from db import db
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.common import get_json_body, make_entity, req_enum, req_string, touch

bp = Blueprint("compliance_disclosures", __name__)
ALL = ("ComplianceOfficer", "TaxDirector", "BoardDirector")
DISCLOSURE_TYPES = (
    "ASSET_TEST", "INCOME_TEST", "FIVE_FIFTY", "DISTRIBUTION", "PROHIBITED_TRANSACTION",
)

# Polymorphic reference resolution: disclosure_type -> (table, acceptable states)
_REFERENCE_MAP = {
    "ASSET_TEST": ("asset_test_reports", ("LOCKED", "BREACHED")),
    "INCOME_TEST": ("income_test_reports", ("LOCKED", "BREACHED")),
    "FIVE_FIFTY": ("shareholder_snapshots", ("FINALIZED",)),
    "DISTRIBUTION": ("distribution_requirements", ("POSTED", "CLOSED")),
    "PROHIBITED_TRANSACTION": ("asset_sales", ("CONFIRMED",)),
}


@bp.route("/reit-compliance/compliance-disclosures", methods=["POST"])
def create_disclosure():
    require_roles("ComplianceOfficer")
    body = get_json_body()
    reit_id = body.get("reit_id")
    if not isinstance(reit_id, str) or not reit_id:
        raise errors.validation("Field 'reit_id' is required")
    if db.reits.get(reit_id) is None:
        raise errors.not_found("reit_id does not resolve to an existing REIT")

    disclosure_type = req_enum(body, "disclosure_type", DISCLOSURE_TYPES)
    reference_id = req_string(body, "reference_id")
    title = req_string(body, "title")
    narrative = req_string(body, "body")

    d = make_entity({
        "reit_id": reit_id,
        "disclosure_type": disclosure_type,
        "reference_id": reference_id,
        "title": title,
        "body": narrative,
        "status": "DRAFT",
        "revision_count": 0,
        "submitted_by_officer_id": None,
        "decided_by_director_id": None,
    })
    db.compliance_disclosures[d["id"]] = d
    return success_object(dict(d), status=201)


@bp.route("/reit-compliance/compliance-disclosures/<did>", methods=["GET"])
def get_disclosure(did):
    require_roles(*ALL)
    d = db.compliance_disclosures.get(did)
    if d is None:
        raise errors.not_found("Compliance disclosure not found")
    return success_object(dict(d))


@bp.route("/reit-compliance/compliance-disclosures", methods=["GET"])
def list_disclosures():
    require_roles(*ALL)
    limit, offset = parse_pagination(request.args)
    rows = list(db.compliance_disclosures.values())
    reit_id = request.args.get("reit_id")
    if reit_id is not None:
        rows = [d for d in rows if d["reit_id"] == reit_id]
    page, total = paginate(rows, limit, offset)
    return success_list([dict(d) for d in page], limit, offset, total)


@bp.route("/reit-compliance/compliance-disclosures/<did>/submit", methods=["POST"])
def submit_disclosure(did):
    user_id, _ = require_roles("ComplianceOfficer")
    d = db.compliance_disclosures.get(did)
    if d is None:
        raise errors.not_found("Compliance disclosure not found")
    if d["status"] != "DRAFT":
        raise errors.invalid_state("Only DRAFT disclosures can be submitted")

    # Reference integrity: must resolve to an entity of the implied type and be
    # in a terminal/locked state.
    table_name, terminal_states = _REFERENCE_MAP[d["disclosure_type"]]
    table = getattr(db, table_name)
    ref = table.get(d["reference_id"])
    if ref is None:
        raise errors.not_found("reference_id does not resolve to an existing entity")
    if ref["status"] not in terminal_states:
        raise errors.invalid_state(
            "Referenced entity must be in a terminal or locked state for submission"
        )

    d["status"] = "SUBMITTED"
    d["submitted_by_officer_id"] = user_id
    touch(d)
    return success_object(dict(d))


@bp.route("/reit-compliance/compliance-disclosures/<did>/approve", methods=["POST"])
def approve_disclosure(did):
    user_id, _ = require_roles("BoardDirector")
    d = db.compliance_disclosures.get(did)
    if d is None:
        raise errors.not_found("Compliance disclosure not found")
    if d["status"] != "SUBMITTED":
        raise errors.invalid_state("Only SUBMITTED disclosures can be approved")
    if d["submitted_by_officer_id"] is not None and user_id == d["submitted_by_officer_id"]:
        raise errors.segregation(
            "The deciding director must differ from the submitting officer"
        )
    d["status"] = "APPROVED"
    d["decided_by_director_id"] = user_id
    touch(d)
    return success_object(dict(d))


@bp.route("/reit-compliance/compliance-disclosures/<did>/reject", methods=["POST"])
def reject_disclosure(did):
    user_id, _ = require_roles("BoardDirector")
    d = db.compliance_disclosures.get(did)
    if d is None:
        raise errors.not_found("Compliance disclosure not found")
    if d["status"] != "SUBMITTED":
        raise errors.invalid_state("Only SUBMITTED disclosures can be rejected")
    if d["submitted_by_officer_id"] is not None and user_id == d["submitted_by_officer_id"]:
        raise errors.segregation(
            "The deciding director must differ from the submitting officer"
        )
    # Rejection is a revision loop: SUBMITTED -> DRAFT, revision_count += 1
    d["status"] = "DRAFT"
    d["decided_by_director_id"] = user_id
    d["revision_count"] = d.get("revision_count", 0) + 1
    touch(d)
    return success_object(dict(d))
