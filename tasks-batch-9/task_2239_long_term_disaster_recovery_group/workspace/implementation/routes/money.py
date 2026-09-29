"""Funding sources, disbursements and the logical clock (PRD 3.6, 2.4)."""

from flask import Blueprint

import db
import lookups
import middleware as mw
import response
from constants import (
    DISBURSEMENT_STATUSES,
    FUNDING_SOURCE_STATUSES,
    FUNDING_SOURCE_TYPES,
    PURPOSE_CODES,
    RESTRICTION_CODES,
    ROLE_ADMIN,
    ROLE_CASE_MANAGER,
    ROLE_CHAIR,
    ROLE_OFFICER,
)
from errors import ApiError
from services import calculations as calc
from services import rollups

bp = Blueprint("money", __name__)

PAYABLE_PROJECT_STATUSES = ("PERMITTED", "IN_PROGRESS", "PUNCHLIST")


# ---------------------------------------------------------------------------
# FundingSource
# ---------------------------------------------------------------------------
@bp.post("/funding-sources")
def create_funding_source():
    mw.authorize((ROLE_ADMIN,))
    body = mw.get_body()
    label = mw.req_str(body, "label")
    source_type = mw.req_enum(body, "source_type", FUNDING_SOURCE_TYPES)
    restriction = mw.req_enum(body, "restriction_code", RESTRICTION_CODES)
    total = mw.req_int(body, "total_cents", minimum=0)
    expires_on = mw.opt_date(body, "expires_on")
    retention_allowed = mw.opt_bool(body, "admin_retention_allowed", True)

    record = db.base_record()
    record.update(
        {
            "label": label,
            "source_type": source_type,
            "restriction_code": restriction,
            "eligible_purpose_codes": calc.eligible_purpose_codes(restriction),
            "restriction_specificity": calc.restriction_specificity(restriction),
            "total_cents": total,
            "expires_on": expires_on,
            "admin_retention_allowed": retention_allowed,
            "committed_cents": 0,
            "disbursed_cents": 0,
            "admin_retained_cents": 0,
            "available_cents": total,
            "status": "OPEN",
        }
    )
    db.funding_sources[record["id"]] = record
    return response.object_response(record, 201)


@bp.get("/funding-sources/<fid>")
def get_funding_source(fid):
    mw.authorize((ROLE_OFFICER, ROLE_ADMIN, ROLE_CHAIR))
    return response.object_response(lookups.funding_source(fid))


@bp.get("/funding-sources")
def list_funding_sources():
    mw.authorize((ROLE_OFFICER, ROLE_ADMIN, ROLE_CHAIR))
    limit, offset = mw.pagination()
    restriction = mw.query_enum("restriction_code", RESTRICTION_CODES)
    status = mw.query_enum("status", FUNDING_SOURCE_STATUSES)
    source_type = mw.query_enum("source_type", FUNDING_SOURCE_TYPES)

    rows = db.sorted_records(list(db.funding_sources.values()))
    if restriction is not None:
        rows = [r for r in rows if r["restriction_code"] == restriction]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if source_type is not None:
        rows = [r for r in rows if r["source_type"] == source_type]

    page, total = response.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Disbursement
# ---------------------------------------------------------------------------
def _fork_on_dob(disbursement, case, exclude_self=True):
    """Store the duplication-of-benefits figures and fork REQUESTED -> cleared/flagged."""
    figures = calc.dob_exposure_check(
        case,
        disbursement["purpose_code"],
        disbursement["requested_cents"],
        exclude_disbursement_id=disbursement["id"] if exclude_self else None,
    )
    disbursement["dob_pool_cents"] = figures["dob_pool_cents"]
    disbursement["dob_exposure_cents"] = figures["dob_exposure_cents"]
    disbursement["status"] = "DOB_CLEARED" if figures["cleared"] else "DOB_FLAGGED"
    return figures


@bp.post("/disbursements")
def create_disbursement():
    user_id, _role = mw.authorize((ROLE_OFFICER, ROLE_ADMIN))
    body = mw.get_body()
    case_id = mw.req_id(body, "case_id")
    purpose_code = mw.req_enum(body, "purpose_code", PURPOSE_CODES)
    requested = mw.req_int(body, "requested_cents", minimum=1)
    payee_name = mw.req_str(body, "payee_name")
    expected_case_version = mw.req_int(body, "expected_case_version")
    project_id = mw.opt_id(body, "project_id")
    commitment_id = mw.opt_id(body, "commitment_id")

    if purpose_code == "STRUCTURE_REPAIR" and project_id is None:
        raise mw.bad("Field 'project_id' is required when purpose_code is STRUCTURE_REPAIR.")
    if purpose_code != "STRUCTURE_REPAIR" and project_id is not None:
        raise mw.bad("Field 'project_id' is only allowed when purpose_code is STRUCTURE_REPAIR.")

    case = lookups.case(case_id)
    if project_id is not None:
        lookups.project(project_id)
    if commitment_id is not None:
        lookups.commitment(commitment_id)

    if expected_case_version != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION")

    record = db.base_record()
    record.update(
        {
            "case_id": case["id"],
            "project_id": project_id,
            "commitment_id": commitment_id,
            "purpose_code": purpose_code,
            "requested_cents": requested,
            "payee_name": payee_name,
            "status": "REQUESTED",
            "dob_pool_cents": 0,
            "dob_exposure_cents": 0,
            "allocation_lines": [],
            "net_cents": 0,
            "admin_retained_cents": 0,
            "gross_cents": 0,
            "requested_by_user_id": user_id,
            "approved_by_user_id": None,
            "dob_resolution_note": None,
            "reversal_reason": None,
        }
    )
    db.disbursements[record["id"]] = record
    _fork_on_dob(record, case)

    db.mark(case)
    return response.object_response(record, 201)


@bp.get("/disbursements/<did>")
def get_disbursement(did):
    mw.authorize((ROLE_OFFICER, ROLE_ADMIN, ROLE_CASE_MANAGER))
    return response.object_response(lookups.disbursement(did))


@bp.get("/disbursements")
def list_disbursements():
    mw.authorize((ROLE_OFFICER, ROLE_ADMIN, ROLE_CASE_MANAGER))
    limit, offset = mw.pagination()
    case_id = mw.query_str("case_id")
    project_id = mw.query_str("project_id")
    commitment_id = mw.query_str("commitment_id")
    status = mw.query_enum("status", DISBURSEMENT_STATUSES)
    purpose_code = mw.query_enum("purpose_code", PURPOSE_CODES)

    rows = db.sorted_records(list(db.disbursements.values()))
    if case_id is not None:
        rows = [r for r in rows if r["case_id"] == case_id]
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if commitment_id is not None:
        rows = [r for r in rows if r["commitment_id"] == commitment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if purpose_code is not None:
        rows = [r for r in rows if r["purpose_code"] == purpose_code]

    page, total = response.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.post("/disbursements/<did>/dob-resolution")
def resolve_dob(did):
    mw.authorize((ROLE_OFFICER, ROLE_ADMIN))
    body = mw.get_body()
    note = mw.req_str(body, "dob_resolution_note")
    excluded_ids = mw.req_list(body, "excluded_assistance_record_ids")

    disbursement = lookups.disbursement(did)
    if disbursement["status"] != "DOB_FLAGGED":
        raise ApiError("ERR_DISBURSEMENT_INVALID_STATE")

    case = db.recovery_cases.get(disbursement["case_id"])
    sibling_ids = (
        [c["id"] for c in calc.sibling_cases(case["survivor_id"])] if case else []
    )
    records = []
    for record_id in excluded_ids:
        record = db.assistance_records.get(record_id)
        if record is None or record["case_id"] not in sibling_ids:
            raise mw.bad(
                "Field 'excluded_assistance_record_ids' must reference assistance "
                "records of this survivor."
            )
        records.append(record)

    for record in records:
        record["is_excluded_from_dob"] = True
        record["exclusion_note"] = note

    db.set_field(disbursement, "dob_resolution_note", note)
    db.set_field(disbursement, "status", "REQUESTED")
    figures = calc.dob_exposure_check(
        case,
        disbursement["purpose_code"],
        disbursement["requested_cents"],
        exclude_disbursement_id=disbursement["id"],
    )
    db.set_field(disbursement, "dob_pool_cents", figures["dob_pool_cents"])
    db.set_field(disbursement, "dob_exposure_cents", figures["dob_exposure_cents"])
    db.set_field(
        disbursement,
        "status",
        "DOB_CLEARED" if figures["cleared"] else "DOB_FLAGGED",
    )
    db.mark(disbursement)
    return response.object_response(disbursement)


def _case_allocated_net(case_id, exclude_id=None):
    return sum(
        d["net_cents"] if d["status"] in ("APPROVED", "PAID") else 0
        for d in db.disbursements.values()
        if d["case_id"] == case_id and d["id"] != exclude_id
    )


@bp.post("/disbursements/<did>/approve")
def approve_disbursement(did):
    user_id, _role = mw.authorize((ROLE_ADMIN,))
    body = mw.get_body()
    mw.opt_str(body, "approval_note")

    disbursement = lookups.disbursement(did)
    if user_id == disbursement["requested_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if disbursement["status"] != "DOB_CLEARED":
        raise ApiError("ERR_DISBURSEMENT_INVALID_STATE")

    if disbursement["purpose_code"] == "STRUCTURE_REPAIR":
        project = db.projects.get(disbursement["project_id"])
        if project is None or project["status"] not in PAYABLE_PROJECT_STATUSES:
            raise ApiError("ERR_PROJECT_NOT_PAYABLE")

    case = db.recovery_cases.get(disbursement["case_id"])
    figures = calc.dob_exposure_check(
        case,
        disbursement["purpose_code"],
        disbursement["requested_cents"],
        exclude_disbursement_id=disbursement["id"],
    )
    if not figures["cleared"]:
        raise ApiError("ERR_DUPLICATION_OF_BENEFITS")

    eligible_pool = [
        s
        for s in calc.open_unexpired_sources()
        if disbursement["purpose_code"] in s["eligible_purpose_codes"]
    ]
    if not eligible_pool:
        raise ApiError("ERR_RESTRICTION_MISMATCH")

    allocated = _case_allocated_net(disbursement["case_id"], disbursement["id"])
    if allocated + disbursement["requested_cents"] > case["total_committed_cents"]:
        raise ApiError("ERR_DISBURSEMENT_EXCEEDS_COMMITMENT")

    result = calc.restricted_fund_waterfall(
        disbursement["purpose_code"], disbursement["requested_cents"]
    )
    if result is None:
        raise ApiError("ERR_INSUFFICIENT_RESTRICTED_FUNDS")
    lines, net_cents, admin_retained_cents, gross_cents = result

    db.set_field(disbursement, "allocation_lines", lines)
    db.set_field(disbursement, "net_cents", net_cents)
    db.set_field(disbursement, "admin_retained_cents", admin_retained_cents)
    db.set_field(disbursement, "gross_cents", gross_cents)
    db.set_field(disbursement, "approved_by_user_id", user_id)
    db.set_field(disbursement, "status", "APPROVED")

    for line in lines:
        source = db.funding_sources.get(line["funding_source_id"])
        if source is None:
            continue
        db.set_field(
            source, "committed_cents", source["committed_cents"] + line["gross_cents"]
        )
        rollups.recompute_funding_source(source)

    db.mark(disbursement)
    return response.object_response(disbursement)


@bp.post("/disbursements/<did>/pay")
def pay_disbursement(did):
    mw.authorize((ROLE_OFFICER, ROLE_ADMIN))
    body = mw.get_body()
    mw.opt_str(body, "payment_reference")

    disbursement = lookups.disbursement(did)
    if disbursement["status"] != "APPROVED":
        raise ApiError("ERR_DISBURSEMENT_INVALID_STATE")

    for line in disbursement["allocation_lines"]:
        source = db.funding_sources.get(line["funding_source_id"])
        if source is None:
            continue
        db.set_field(
            source, "committed_cents", source["committed_cents"] - line["gross_cents"]
        )
        db.set_field(
            source, "disbursed_cents", source["disbursed_cents"] + line["net_cents"]
        )
        db.set_field(
            source,
            "admin_retained_cents",
            source["admin_retained_cents"] + line["retention_cents"],
        )
        rollups.recompute_funding_source(source)

    commitment = db.commitments.get(disbursement["commitment_id"])
    if commitment is not None and commitment["status"] == "CONFIRMED":
        db.set_field(commitment, "status", "DISBURSED")
        rollups.recompute_member_org(db.member_orgs.get(commitment["member_org_id"]))

    db.set_field(disbursement, "status", "PAID")

    case = db.recovery_cases.get(disbursement["case_id"])
    if case is not None:
        rollups.recompute_case_funding(case)

    db.mark(disbursement)
    return response.object_response(disbursement)


@bp.post("/disbursements/<did>/reverse")
def reverse_disbursement(did):
    mw.authorize((ROLE_ADMIN,))
    body = mw.get_body()
    reason = mw.req_str(body, "reversal_reason")

    disbursement = lookups.disbursement(did)
    if disbursement["status"] != "PAID":
        raise ApiError("ERR_DISBURSEMENT_INVALID_STATE")

    db.set_field(disbursement, "status", "REVERSED")
    db.set_field(disbursement, "reversal_reason", reason)

    for line in disbursement["allocation_lines"]:
        source = db.funding_sources.get(line["funding_source_id"])
        if source is None:
            continue
        db.set_field(
            source, "disbursed_cents", source["disbursed_cents"] - line["net_cents"]
        )
        db.set_field(
            source,
            "admin_retained_cents",
            source["admin_retained_cents"] - line["retention_cents"],
        )
        rollups.recompute_funding_source(source)

    commitment = db.commitments.get(disbursement["commitment_id"])
    if commitment is not None and commitment["status"] == "DISBURSED":
        db.set_field(commitment, "status", "CONFIRMED")
        rollups.recompute_member_org(db.member_orgs.get(commitment["member_org_id"]))

    case = db.recovery_cases.get(disbursement["case_id"])
    if case is not None:
        rollups.recompute_case_funding(case)
        if case["funding_status"] != "SATISFIED":
            rollups.rewind_closure_pending(case)

    db.mark(disbursement)
    return response.object_response(disbursement)


@bp.post("/disbursements/<did>/void")
def void_disbursement(did):
    mw.authorize((ROLE_OFFICER, ROLE_ADMIN))
    body = mw.get_body()
    mw.req_str(body, "void_reason")

    disbursement = lookups.disbursement(did)
    if disbursement["status"] not in ("DOB_FLAGGED", "DOB_CLEARED"):
        raise ApiError("ERR_DISBURSEMENT_INVALID_STATE")

    db.set_field(disbursement, "status", "VOIDED")
    db.mark(disbursement)
    return response.object_response(disbursement)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    mw.authorize((ROLE_ADMIN,))
    body = mw.get_body()
    raw = mw.req_str(body, "to_iso8601")
    moment = mw.parse_instant("to_iso8601", raw)

    db.set_clock(moment)
    current_date = db.clock_date()

    expired_ids = []
    for source in db.sorted_records(list(db.funding_sources.values())):
        if source["status"] != "OPEN" or not source.get("expires_on"):
            continue
        if calc.to_date(source["expires_on"]) < current_date:
            db.set_field(source, "status", "EXPIRED")
            expired_ids.append(source["id"])

    payload = {
        "current_utc": db.clock_iso(),
        "expired_funding_source_ids": expired_ids,
    }
    return response.object_response(payload)
