"""EmissionReport, EmissionDataLine, SupportingDocument, VerificationAssignment endpoints."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import clock
import db
import errors
import helpers
import response
from middleware import auth_required, get_actor
from serializers import (
    emission_report_dict,
    emission_data_line_dict,
    supporting_document_dict,
    verification_assignment_dict,
)
from services.calculations import (
    calc_line_source_amount,
    calc_total_reported_emissions,
    calc_total_verified_emissions,
    calc_cross_check_delta_pct,
)
from helpers import to_dec, bump


bp = Blueprint("emission_reports", __name__)


VALID_SOURCE_CATEGORIES = {"FUEL", "ELECTRICITY", "PROCESS", "FUGITIVE"}
DOC_REQUIRED_CATEGORIES = {"FUEL", "PROCESS"}
VALID_DOCUMENT_TYPES = {"FUEL_INVOICE", "METER_LOG", "PROCESS_SHEET", "EXTERNAL_AUDIT"}


def _own_report_or_raise(report, user_id, user_role):
    if user_role == "Enterprise" and report["enterprise_id"] != user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION,
                           "Acting enterprise does not own this report.")
    if user_role == "VerifierAgency":
        # Allowed only if assigned via a VerificationAssignment.
        ok = False
        for v in db.verification_assignments.values():
            if v["report_id"] == report["id"] and v["agency_id"] == user_id:
                ok = True
                break
        if not ok:
            errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION,
                               "VerifierAgency not assigned to this report.")


def _lines_for_report(report_id):
    return [l for l in db.emission_data_lines.values() if l["report_id"] == report_id]


def _recompute_total_reported(report):
    lines = _lines_for_report(report["id"])
    report["total_reported_emissions"] = calc_total_reported_emissions(lines)


def _touch_report(report):
    """Update updated_at on the report WITHOUT bumping the resubmission counter.

    Per PRD §2.4, EmissionReport's `version` is the resubmission counter
    (per (enterprise, cycle_year)), which only advances when a new version is
    created. Mutations such as line/doc additions therefore bump updated_at
    only — they do NOT change `version`.
    """
    report["updated_at"] = clock.now()


@bp.route("/enterprises/<eid>/emission-reports", methods=["POST"])
@auth_required("Enterprise")
def create_report(eid):
    if eid not in db.enterprises:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Enterprise {eid} not found.")
    user_id, _ = get_actor()
    if user_id != eid:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION,
                           "Enterprise can only create reports for itself.")
    body = helpers.get_json_body()
    helpers.require_fields(body, ["cycle_year"])
    cycle_year = int(body["cycle_year"])

    # Find cycle by cycle_year.
    cycle = None
    for c in db.allocation_cycles.values():
        if c["cycle_year"] == cycle_year:
            cycle = c
            break
    if cycle is None:
        errors.raise_error(errors.ERR_NOT_FOUND,
                           f"AllocationCycle for cycle_year {cycle_year} not found.")

    # Find the latest existing report for (enterprise, cycle_year), if any.
    prior_reports = sorted(
        [r for r in db.emission_reports.values()
         if r["enterprise_id"] == eid and r["cycle_year"] == cycle_year],
        key=lambda r: r["version"],
    )
    if prior_reports:
        latest = prior_reports[-1]
        if latest["status"] not in ("SUBMITTED", "REJECTED"):
            errors.raise_error(errors.ERR_INVALID_STATE,
                               f"Existing report in {latest['status']}; cannot create new version.")
        new_version = latest["version"] + 1
        # Older versions get is_current_version=false.
        latest["is_current_version"] = False
    else:
        new_version = 1

    submission_deadline = cycle["compliance_deadline"] - timedelta(days=90)
    common = helpers.common_create()
    r = {
        "id": db.new_id(),
        "enterprise_id": eid,
        "cycle_year": cycle_year,
        "version": new_version,    # domain version (also OCC version)
        "status": "DRAFT",
        "submission_deadline": submission_deadline,
        "submitted_at": None,
        "total_reported_emissions": Decimal("0"),
        "total_verified_emissions": None,
        "is_current_version": True,
        "supporting_document_count": 0,
        "created_at": common["created_at"],
        "updated_at": common["updated_at"],
    }
    db.emission_reports[r["id"]] = r
    return response.created(emission_report_dict(r))


@bp.route("/emission-reports/<rid>", methods=["GET"])
@auth_required("Regulator", "Enterprise", "VerifierAgency")
def read_report(rid):
    r = db.emission_reports.get(rid)
    if r is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"EmissionReport {rid} not found.")
    user_id, user_role = get_actor()
    if user_role != "Regulator":
        _own_report_or_raise(r, user_id, user_role)
    out = emission_report_dict(r)
    # PRD §4: 'GET /emission-reports/{id} — Read emission report including
    # lines and verified totals'. Surface attached EmissionDataLine rows
    # (and supporting documents) under the report.
    lines = sorted(_lines_for_report(rid), key=lambda l: l["created_at"])
    out["lines"] = [emission_data_line_dict(l) for l in lines]
    docs = sorted(
        [d for d in db.supporting_documents.values() if d["report_id"] == rid],
        key=lambda d: d["created_at"],
    )
    out["supporting_documents"] = [supporting_document_dict(d) for d in docs]
    return response.ok(out)


@bp.route("/emission-reports/<rid>/lines", methods=["POST"])
@auth_required("Enterprise")
def add_line(rid):
    r = db.emission_reports.get(rid)
    if r is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"EmissionReport {rid} not found.")
    if r["status"] != "DRAFT":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Report must be DRAFT to add lines; is {r['status']}.")
    user_id, _ = get_actor()
    if r["enterprise_id"] != user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION,
                           "Acting enterprise does not own this report.")
    body = helpers.get_json_body()
    helpers.require_fields(body, ["source_category", "activity_data", "emission_factor"])
    sc = body["source_category"]
    if sc not in VALID_SOURCE_CATEGORIES:
        errors.raise_error(errors.ERR_INVALID_INPUT, "Invalid source_category.")
    sd_id = body.get("supporting_document_id")
    if sc in DOC_REQUIRED_CATEGORIES and not sd_id:
        errors.raise_error(errors.ERR_SUPPORTING_DOCUMENT_REQUIRED,
                           f"source_category {sc} requires supporting_document_id.")
    if sd_id is not None:
        # Verify supporting_document exists and belongs to this report.
        doc = db.supporting_documents.get(sd_id)
        if doc is None or doc["report_id"] != rid:
            errors.raise_error(errors.ERR_NOT_FOUND, "supporting_document_id not found on this report.")

    source_amount = calc_line_source_amount(body["activity_data"], body["emission_factor"])
    line = {
        "id": db.new_id(),
        "report_id": rid,
        "source_category": sc,
        "activity_data": to_dec(body["activity_data"]),
        "emission_factor": to_dec(body["emission_factor"]),
        "source_amount": source_amount,
        "verified_amount": None,
        "supporting_document_id": sd_id,
        "created_at": clock.now(),
    }
    db.emission_data_lines[line["id"]] = line
    _recompute_total_reported(r)
    _touch_report(r)
    return response.created(emission_data_line_dict(line))


@bp.route("/emission-reports/<rid>/documents", methods=["POST"])
@auth_required("Enterprise")
def upload_document(rid):
    r = db.emission_reports.get(rid)
    if r is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"EmissionReport {rid} not found.")
    user_id, _ = get_actor()
    if r["enterprise_id"] != user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION,
                           "Acting enterprise does not own this report.")
    body = helpers.get_json_body()
    helpers.require_fields(body, ["document_type", "file_uri"])
    if body["document_type"] not in VALID_DOCUMENT_TYPES:
        errors.raise_error(errors.ERR_INVALID_INPUT, "Invalid document_type.")
    now = clock.now()
    doc = {
        "id": db.new_id(),
        "report_id": rid,
        "document_type": body["document_type"],
        "file_uri": body["file_uri"],
        "uploaded_at": now,
        "created_at": now,
    }
    db.supporting_documents[doc["id"]] = doc
    r["supporting_document_count"] = r["supporting_document_count"] + 1
    _touch_report(r)
    return response.created(supporting_document_dict(doc))


@bp.route("/emission-reports/<rid>/submit", methods=["POST"])
@auth_required("Enterprise")
def submit_report(rid):
    r = db.emission_reports.get(rid)
    if r is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"EmissionReport {rid} not found.")
    user_id, _ = get_actor()
    if r["enterprise_id"] != user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION,
                           "Acting enterprise does not own this report.")
    if r["status"] != "DRAFT":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Report must be DRAFT to submit; is {r['status']}.")
    body = helpers.get_json_body()
    helpers.check_occ(r, body.get("version"))

    # Cycle status check.
    cycle = None
    for c in db.allocation_cycles.values():
        if c["cycle_year"] == r["cycle_year"]:
            cycle = c
            break
    if cycle is None or cycle["status"] != "COMPLIANCE_OPEN":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Parent cycle must be COMPLIANCE_OPEN to submit report.")
    if clock.now() > r["submission_deadline"]:
        errors.raise_error(errors.ERR_WINDOW_CLOSED,
                           "Past report submission deadline.")
    lines = _lines_for_report(rid)
    if not lines:
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Report must have at least one emission data line.")
    for l in lines:
        if l["source_category"] in DOC_REQUIRED_CATEGORIES and not l.get("supporting_document_id"):
            errors.raise_error(errors.ERR_SUPPORTING_DOCUMENT_REQUIRED,
                               f"Line {l['id']} ({l['source_category']}) lacks supporting_document_id.")

    # Older versions of (enterprise, cycle_year) -> is_current_version=false.
    for other in db.emission_reports.values():
        if (other["id"] != r["id"]
                and other["enterprise_id"] == r["enterprise_id"]
                and other["cycle_year"] == r["cycle_year"]):
            if other["is_current_version"]:
                other["is_current_version"] = False
                _touch_report(other)

    _recompute_total_reported(r)
    r["status"] = "SUBMITTED"
    r["submitted_at"] = clock.now()
    r["is_current_version"] = True
    _touch_report(r)
    return response.ok(emission_report_dict(r))


@bp.route("/emission-reports/<rid>/assign-verifier", methods=["POST"])
@auth_required("Regulator")
def assign_verifier(rid):
    r = db.emission_reports.get(rid)
    if r is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"EmissionReport {rid} not found.")
    if r["status"] != "SUBMITTED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Report must be SUBMITTED to assign verifier; is {r['status']}.")
    body = helpers.get_json_body()
    helpers.require_fields(body, ["agency_id", "scheduled_visit_at"])
    agency_id = body["agency_id"]
    scheduled = clock.parse_iso(body["scheduled_visit_at"])
    if agency_id == r["enterprise_id"]:
        errors.raise_error(errors.ERR_VERIFIER_CONFLICT_OF_INTEREST,
                           "Verifier agency cannot equal the enterprise being verified.")
    now = clock.now()
    if scheduled < now + timedelta(days=7):
        errors.raise_error(errors.ERR_WINDOW_CLOSED,
                           "scheduled_visit_at must be at least 7 days in the future.")
    common = helpers.common_create()
    v = {
        "id": db.new_id(),
        "report_id": rid,
        "agency_id": agency_id,
        "scheduled_visit_at": scheduled,
        "status": "ASSIGNED",
        "cross_check_delta_pct": None,
        "report_issued_at": None,
        **common,
    }
    db.verification_assignments[v["id"]] = v
    r["status"] = "UNDER_VERIFICATION"
    _touch_report(r)
    return response.created(verification_assignment_dict(v))


@bp.route("/verification-assignments/<vid>/complete-onsite", methods=["POST"])
@auth_required("VerifierAgency")
def complete_onsite(vid):
    v = db.verification_assignments.get(vid)
    if v is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"VerificationAssignment {vid} not found.")
    if v["status"] != "ASSIGNED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Assignment must be ASSIGNED to complete on-site; is {v['status']}.")
    user_id, _ = get_actor()
    if v["agency_id"] != user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION,
                           "Verifier can only act on its own assignment.")
    body = helpers.get_json_body()
    line_adjustments = body.get("line_adjustments", [])
    if not isinstance(line_adjustments, list):
        errors.raise_error(errors.ERR_INVALID_INPUT, "line_adjustments must be a list.")
    r = db.emission_reports[v["report_id"]]
    lines = _lines_for_report(r["id"])
    line_map = {l["id"]: l for l in lines}
    # Apply per-line verified_amounts.
    for adj in line_adjustments:
        if not isinstance(adj, dict):
            errors.raise_error(errors.ERR_INVALID_INPUT, "Each line_adjustment must be an object.")
        lid = adj.get("line_id")
        va = adj.get("verified_amount")
        if lid is None or va is None:
            errors.raise_error(errors.ERR_INVALID_INPUT,
                               "line_adjustment requires line_id and verified_amount.")
        line = line_map.get(lid)
        if line is None:
            errors.raise_error(errors.ERR_NOT_FOUND,
                               f"Line {lid} not found on this report.")
        line["verified_amount"] = to_dec(va)
    # For lines with no adjustment supplied, verified_amount defaults to source_amount
    # (i.e., zero adjustment). PRD says verifier supplies per-line verified_amount;
    # if not supplied, use the reported amount as the verified amount.
    for l in lines:
        if l.get("verified_amount") is None:
            l["verified_amount"] = to_dec(l["source_amount"])

    total_verified = calc_total_verified_emissions(lines)
    total_reported = to_dec(r["total_reported_emissions"])
    v["cross_check_delta_pct"] = calc_cross_check_delta_pct(total_reported, total_verified)
    v["status"] = "ON_SITE_DONE"
    bump(v)
    # Stash interim verified total on the report (used by issue-report).
    r["_interim_verified"] = total_verified
    return response.ok(verification_assignment_dict(v))


@bp.route("/verification-assignments/<vid>/issue-report", methods=["POST"])
@auth_required("VerifierAgency")
def issue_report(vid):
    v = db.verification_assignments.get(vid)
    if v is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"VerificationAssignment {vid} not found.")
    if v["status"] != "ON_SITE_DONE":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Assignment must be ON_SITE_DONE to issue report; is {v['status']}.")
    user_id, _ = get_actor()
    if v["agency_id"] != user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION,
                           "Verifier can only act on its own assignment.")
    r = db.emission_reports[v["report_id"]]
    lines = _lines_for_report(r["id"])
    total_verified = calc_total_verified_emissions(lines)
    r["total_verified_emissions"] = total_verified
    r["status"] = "VERIFIED"
    _touch_report(r)
    v["status"] = "REPORT_ISSUED"
    v["report_issued_at"] = clock.now()
    bump(v)
    return response.ok(verification_assignment_dict(v))


@bp.route("/emission-reports/<rid>/dispute", methods=["POST"])
@auth_required("Enterprise")
def dispute_report(rid):
    r = db.emission_reports.get(rid)
    if r is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"EmissionReport {rid} not found.")
    if r["status"] != "VERIFIED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Report must be VERIFIED to dispute; is {r['status']}.")
    user_id, _ = get_actor()
    if r["enterprise_id"] != user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION,
                           "Acting enterprise does not own this report.")
    body = helpers.get_json_body()
    helpers.require_fields(body, ["ground"])
    # Within 14 days of report_issued_at.
    v = next((va for va in db.verification_assignments.values()
              if va["report_id"] == rid and va["status"] == "REPORT_ISSUED"), None)
    if v is None:
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "No REPORT_ISSUED assignment found for this report.")
    if clock.now() > v["report_issued_at"] + timedelta(days=14):
        errors.raise_error(errors.ERR_WINDOW_CLOSED, "Dispute window (14 days) elapsed.")
    r["status"] = "DISPUTED"
    _touch_report(r)
    v["status"] = "DISPUTED"
    bump(v)
    return response.ok(emission_report_dict(r))


@bp.route("/verification-assignments/<vid>/resolve-dispute", methods=["POST"])
@auth_required("Regulator")
def resolve_dispute(vid):
    v = db.verification_assignments.get(vid)
    if v is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"VerificationAssignment {vid} not found.")
    if v["status"] != "DISPUTED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Assignment must be DISPUTED to resolve; is {v['status']}.")
    body = helpers.get_json_body()
    r = db.emission_reports[v["report_id"]]
    if "adjusted_total_verified_emissions" in body and body["adjusted_total_verified_emissions"] is not None:
        r["total_verified_emissions"] = to_dec(body["adjusted_total_verified_emissions"])
    r["status"] = "VERIFIED"
    _touch_report(r)
    v["status"] = "RESOLVED"
    bump(v)
    return response.ok(verification_assignment_dict(v))


@bp.route("/emission-reports/<rid>/finalize", methods=["POST"])
@auth_required("Regulator")
def finalize_report(rid):
    r = db.emission_reports.get(rid)
    if r is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"EmissionReport {rid} not found.")
    if r["status"] != "VERIFIED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Report must be VERIFIED to finalize; is {r['status']}.")
    v = next((va for va in db.verification_assignments.values()
              if va["report_id"] == rid), None)
    if v is None or v["status"] not in ("REPORT_ISSUED", "RESOLVED"):
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Verification assignment must be REPORT_ISSUED or RESOLVED.")
    r["status"] = "FINALIZED"
    _touch_report(r)
    return response.ok(emission_report_dict(r))


@bp.route("/emission-reports/<rid>/reject", methods=["POST"])
@auth_required("Regulator")
def reject_report(rid):
    r = db.emission_reports.get(rid)
    if r is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"EmissionReport {rid} not found.")
    if r["status"] != "SUBMITTED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Report must be SUBMITTED to reject; is {r['status']}.")
    body = helpers.get_json_body()
    helpers.require_fields(body, ["reason"])
    r["status"] = "REJECTED"
    _touch_report(r)
    return response.ok(emission_report_dict(r))
