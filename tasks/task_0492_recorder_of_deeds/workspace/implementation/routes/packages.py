"""DocumentPackage routes and its full lifecycle (PRD §3.2 - §3.5, §4).

Covers: submit, party-entries, begin-examination, assessments (calculations +
OCC + escrow hold), reject (cascade), re-record loop, payments (OCC + escrow
spend), record (page-stamp / instrument mint / index / book roll), withdraw."""
from flask import Blueprint, request

import errors
import calculations as calc
from auth import require_auth, SUBMITTER, EXAMINER, RECORDER, ALL_READERS
from db import db, new_id, common_fields, touch, touch_no_version
from escrow import recompute
from helpers import (body, require_fields, as_int, as_number, as_bool, as_str,
                     as_enum, get_or_404, out, out_list, paginate, sort_created)
from response import ok, created, listed

bp = Blueprint("packages", __name__)

DOC_TYPES = {"DEED", "MORTGAGE", "LIEN", "UCC", "PLAT", "OTHER"}
PARTY_ROLES = {"GRANTOR", "GRANTEE"}
REASON_CODES = {"MARGIN", "NOTARY", "LEGAL_DESCRIPTION", "INDEX_INCOMPLETE", "FEE_DISCREPANCY"}
PAYMENT_METHODS = {"ESCROW", "CARD"}


# --------------------------------------------------------------------------
# helpers scoped to packages
# --------------------------------------------------------------------------

def _party_entries_for(package_id):
    return [pe for pe in db.party_entries.values() if pe["package_id"] == package_id]


def _non_voided_party_entries(package_id):
    return [pe for pe in _party_entries_for(package_id) if pe["status"] != "VOIDED"]


def _has_grantor_and_grantee(package_id):
    roles = {pe["party_role"] for pe in _non_voided_party_entries(package_id)}
    return "GRANTOR" in roles and "GRANTEE" in roles


def _finalized_assessment(package_id):
    for a in db.assessments.values():
        if a["package_id"] == package_id and a["status"] == "FINALIZED":
            return a
    return None


def _require_owner(caller, package):
    """Owner-scoped check (PRD §2.1, §2.10 priority 6): acting Submitter's
    X-User-ID must equal the resource's submitter_id."""
    if caller.user_id != package["submitter_id"]:
        raise errors.err(errors.ERR_NOT_OWNER, "Acting submitter does not own this resource")


# --------------------------------------------------------------------------
# Submit / Get / List
# --------------------------------------------------------------------------

@bp.route("/packages", methods=["POST"])
def create_package():
    require_auth([SUBMITTER])
    data = body()
    require_fields(data, ["submitter_id", "office_id", "doc_type",
                          "declared_page_count", "first_page_top_margin_inches",
                          "notary_present"])
    submitter_id = as_str(data, "submitter_id")
    office_id = as_str(data, "office_id")
    doc_type = as_enum(data, "doc_type", DOC_TYPES)
    declared_page_count = as_int(data, "declared_page_count", minimum=1)
    margin = as_number(data, "first_page_top_margin_inches", minimum=0)
    notary_present = as_bool(data, "notary_present")
    if "declared_consideration_cents" in data and data["declared_consideration_cents"] is not None:
        declared_consideration = as_int(data, "declared_consideration_cents", minimum=0)
    else:
        declared_consideration = 0

    # Existence (priority 3): both referenced ids resolve, left-to-right.
    submitter = get_or_404(db.submitters, submitter_id)
    get_or_404(db.offices, office_id)

    # Compliance (priority 7): a SUSPENDED submitter may not submit.
    if submitter["status"] != "ACTIVE":
        raise errors.err(errors.ERR_SUBMITTER_SUSPENDED, "Submitter is suspended")

    pid = new_id()
    package = {
        "id": pid,
        "submitter_id": submitter_id,
        "office_id": office_id,
        "doc_type": doc_type,
        "declared_page_count": declared_page_count,
        "verified_page_count": None,
        "declared_consideration_cents": declared_consideration,
        "verified_consideration_cents": None,
        "first_page_top_margin_inches": margin,
        "notary_present": notary_present,
        "status": "SUBMITTED",
        "examiner_user_id": None,
        "resubmission_count": 0,
    }
    package.update(common_fields())
    db.packages[pid] = package
    return created(out(package))


@bp.route("/packages/<pid>", methods=["GET"])
def get_package(pid):
    require_auth(ALL_READERS)
    package = get_or_404(db.packages, pid)
    return ok(out(package))


@bp.route("/packages", methods=["GET"])
def list_packages():
    require_auth(ALL_READERS)
    items = list(db.packages.values())
    submitter_id = request.args.get("submitter_id")
    office_id = request.args.get("office_id")
    status = request.args.get("status")
    if submitter_id is not None:
        items = [p for p in items if p["submitter_id"] == submitter_id]
    if office_id is not None:
        items = [p for p in items if p["office_id"] == office_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


# --------------------------------------------------------------------------
# Party entries (index)
# --------------------------------------------------------------------------

@bp.route("/packages/<pid>/party-entries", methods=["POST"])
def add_party_entry(pid):
    require_auth([SUBMITTER])
    package = get_or_404(db.packages, pid)
    data = body()
    require_fields(data, ["party_role", "party_name"])
    party_role = as_enum(data, "party_role", PARTY_ROLES)
    party_name = as_str(data, "party_name")

    eid = new_id()
    entry = {
        "id": eid,
        "package_id": pid,
        "party_role": party_role,
        "party_name": party_name,
        "status": "PENDING",
    }
    entry.update(common_fields())
    db.party_entries[eid] = entry
    return created(out(entry))


@bp.route("/packages/<pid>/party-entries", methods=["GET"])
def list_party_entries(pid):
    require_auth(ALL_READERS)
    get_or_404(db.packages, pid)
    items = sort_created(_party_entries_for(pid))
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


# --------------------------------------------------------------------------
# begin-examination: SUBMITTED -> IN_EXAMINATION
# --------------------------------------------------------------------------

@bp.route("/packages/<pid>/begin-examination", methods=["POST"])
def begin_examination(pid):
    require_auth([EXAMINER])
    package = get_or_404(db.packages, pid)
    # State (priority 5)
    if package["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Package is not SUBMITTED")
    # Compliance (priority 7): submitter must be ACTIVE
    submitter = db.submitters[package["submitter_id"]]
    if submitter["status"] != "ACTIVE":
        raise errors.err(errors.ERR_SUBMITTER_SUSPENDED, "Submitter is suspended")
    # Index completeness (priority 8)
    if not _has_grantor_and_grantee(pid):
        raise errors.err(errors.ERR_INDEX_INCOMPLETE, "Need at least one GRANTOR and one GRANTEE")

    package["status"] = "IN_EXAMINATION"
    touch_no_version(package)
    return ok(out(package))


# --------------------------------------------------------------------------
# assessments: IN_EXAMINATION -> ASSESSED  (the most consequential transition)
# --------------------------------------------------------------------------

@bp.route("/packages/<pid>/assessments", methods=["POST"])
def create_assessment(pid):
    caller = require_auth([EXAMINER])
    package = get_or_404(db.packages, pid)
    data = body()
    # Body validation (priority 4)
    require_fields(data, ["verified_page_count", "verified_consideration_cents",
                          "expected_package_version"])
    verified_page_count = as_int(data, "verified_page_count", minimum=1)
    verified_consideration = as_int(data, "verified_consideration_cents", minimum=0)
    expected_version = as_int(data, "expected_package_version", minimum=0)

    # State (priority 5): a fresh assessment is finalized from IN_EXAMINATION,
    # and a re-examination legitimately re-finalizes from ASSESSED (PRD §2.9:
    # "A re-examination legitimately creates a new FINALIZED assessment that
    # supersedes the prior one, advancing the package's version").
    if package["status"] not in ("IN_EXAMINATION", "ASSESSED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Package is not IN_EXAMINATION or ASSESSED")

    # Compliance / safety (priority 7): margin then notary
    if package["first_page_top_margin_inches"] < calc.MIN_TOP_MARGIN_INCHES:
        raise errors.err(errors.ERR_MARGIN_DEFECT, "Top margin below minimum")
    if not package["notary_present"]:
        raise errors.err(errors.ERR_NOTARY_DEFECT, "Notary block not present")

    # OCC (priority 11)
    if expected_version != package["version"]:
        raise errors.err(errors.ERR_STALE_PACKAGE_VERSION, "Stale package version")

    # All checks pass — set verified figures, compute fees.
    package["verified_page_count"] = verified_page_count
    package["verified_consideration_cents"] = verified_consideration

    party_entry_count = len(_non_voided_party_entries(pid))
    rec_fee, tax, rms, total = calc.assessment_components(
        verified_page_count, package["doc_type"], party_entry_count,
        verified_consideration)

    # Supersede any prior FINALIZED assessment for the package.
    for a in db.assessments.values():
        if a["package_id"] == pid and a["status"] == "FINALIZED":
            a["status"] = "SUPERSEDED"
            touch(a)

    aid = new_id()
    assessment = {
        "id": aid,
        "package_id": pid,
        "recording_fee_cents": rec_fee,
        "transfer_tax_cents": tax,
        "records_mgmt_cents": rms,
        "total_due_cents": total,
        "status": "FINALIZED",
    }
    assessment.update(common_fields())
    db.assessments[aid] = assessment

    # examiner of record, status transition, version bump (PRD §2.4, §3.3)
    package["examiner_user_id"] = caller.user_id
    package["status"] = "ASSESSED"
    touch_no_version(package)
    package["version"] = package["version"] + 1

    # Escrow hold recomputed now that an assessment is FINALIZED on an ASSESSED
    # package (PRD §3.4).
    submitter = db.submitters[package["submitter_id"]]
    recompute(submitter)
    touch(submitter)

    return created(out(assessment))


@bp.route("/packages/<pid>/assessments", methods=["GET"])
def list_assessments(pid):
    require_auth(ALL_READERS)
    get_or_404(db.packages, pid)
    items = sort_created([a for a in db.assessments.values() if a["package_id"] == pid])
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


# --------------------------------------------------------------------------
# reject: IN_EXAMINATION -> REJECTED  (cascade)
# --------------------------------------------------------------------------

@bp.route("/packages/<pid>/reject", methods=["POST"])
def reject_package(pid):
    require_auth([EXAMINER])
    package = get_or_404(db.packages, pid)
    data = body()
    require_fields(data, ["reason_code"])
    reason_code = as_enum(data, "reason_code", REASON_CODES)
    detail = data.get("detail")
    if detail is not None and not isinstance(detail, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "detail must be a string")

    # State (priority 5): rejection is examination's alternative outcome. It is
    # valid both before approval (IN_EXAMINATION) and after approval but before
    # payment (ASSESSED), where the rejection cascade voids the FINALIZED
    # FeeAssessment and releases its escrow hold (PRD §2.8: "Rejecting a package
    # both voids its finalized assessment and releases the corresponding escrow
    # hold"; PRD §3.3 rejection cascade).
    if package["status"] not in ("IN_EXAMINATION", "ASSESSED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Package is not IN_EXAMINATION or ASSESSED")

    # cascade link 1: create RejectionNotice
    rid = new_id()
    rejection = {
        "id": rid,
        "package_id": pid,
        "reason_code": reason_code,
        "detail": detail,
        "cured": False,
    }
    rejection.update(common_fields())
    db.rejections[rid] = rejection

    # cascade link 2: void any FINALIZED assessment
    for a in db.assessments.values():
        if a["package_id"] == pid and a["status"] == "FINALIZED":
            a["status"] = "VOIDED"
            touch(a)

    package["status"] = "REJECTED"
    touch_no_version(package)

    # cascade link 3: voiding the assessment releases its hold (recompute escrow)
    submitter = db.submitters[package["submitter_id"]]
    recompute(submitter)
    touch(submitter)

    return created(out(rejection))


@bp.route("/packages/<pid>/rejections", methods=["GET"])
def list_rejections(pid):
    require_auth(ALL_READERS)
    get_or_404(db.packages, pid)
    items = sort_created([r for r in db.rejections.values() if r["package_id"] == pid])
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


# --------------------------------------------------------------------------
# re-record: REJECTED -> IN_EXAMINATION  (cyclic)
# --------------------------------------------------------------------------

@bp.route("/packages/<pid>/re-record", methods=["POST"])
def re_record(pid):
    caller = require_auth([SUBMITTER])
    package = get_or_404(db.packages, pid)
    data = body()
    # validate optional corrected field types (priority 4)
    if "declared_page_count" in data and data["declared_page_count"] is not None:
        as_int(data, "declared_page_count", minimum=1)
    if "declared_consideration_cents" in data and data["declared_consideration_cents"] is not None:
        as_int(data, "declared_consideration_cents", minimum=0)
    if "first_page_top_margin_inches" in data and data["first_page_top_margin_inches"] is not None:
        as_number(data, "first_page_top_margin_inches", minimum=0)
    if "notary_present" in data and data["notary_present"] is not None:
        as_bool(data, "notary_present")

    # State (priority 5)
    if package["status"] != "REJECTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Package is not REJECTED")
    # Ownership (priority 6)
    _require_owner(caller, package)
    # Compliance (priority 7): submitter must be ACTIVE
    submitter = db.submitters[package["submitter_id"]]
    if submitter["status"] != "ACTIVE":
        raise errors.err(errors.ERR_SUBMITTER_SUSPENDED, "Submitter is suspended")

    # apply corrected fields where provided
    for field in ("declared_page_count", "declared_consideration_cents",
                  "first_page_top_margin_inches", "notary_present"):
        if field in data and data[field] is not None:
            package[field] = data[field]

    # mark latest RejectionNotice cured
    rejs = sorted([r for r in db.rejections.values() if r["package_id"] == pid],
                  key=lambda r: r["_seq"])
    if rejs:
        latest = rejs[-1]
        latest["cured"] = True
        touch(latest)

    package["resubmission_count"] += 1
    package["status"] = "IN_EXAMINATION"
    touch_no_version(package)
    return ok(out(package))


# --------------------------------------------------------------------------
# payments: ASSESSED -> PAID  (OCC + escrow spend)
# --------------------------------------------------------------------------

@bp.route("/packages/<pid>/payments", methods=["POST"])
def create_payment(pid):
    caller = require_auth([SUBMITTER])
    package = get_or_404(db.packages, pid)
    data = body()
    require_fields(data, ["amount_cents", "method", "expected_package_version"])
    amount = as_int(data, "amount_cents", minimum=0)
    method = as_enum(data, "method", PAYMENT_METHODS)
    expected_version = as_int(data, "expected_package_version", minimum=0)

    # State (priority 5)
    if package["status"] != "ASSESSED":
        raise errors.err(errors.ERR_INVALID_STATE, "Package is not ASSESSED")
    # Ownership (priority 6)
    _require_owner(caller, package)

    # Cross-entity state (priority 8): a FINALIZED assessment must exist
    assessment = _finalized_assessment(pid)
    if assessment is None:
        raise errors.err(errors.ERR_ASSESSMENT_NOT_FINALIZED, "No finalized assessment")

    # Fiscal (priority 10): amount equals finalized total; escrow sufficiency
    if amount != assessment["total_due_cents"]:
        raise errors.err(errors.ERR_PAYMENT_AMOUNT_MISMATCH, "Amount does not match assessment total")
    submitter = db.submitters[package["submitter_id"]]
    if method == "ESCROW" and submitter["escrow_balance_cents"] < amount:
        raise errors.err(errors.ERR_ESCROW_INSUFFICIENT, "Insufficient settled escrow")

    # OCC (priority 11)
    if expected_version != package["version"]:
        raise errors.err(errors.ERR_STALE_PACKAGE_VERSION, "Stale package version")

    # capture
    payid = new_id()
    payment = {
        "id": payid,
        "package_id": pid,
        "amount_cents": amount,
        "method": method,
        "status": "CAPTURED",
    }
    payment.update(common_fields())
    db.payments[payid] = payment

    package["status"] = "PAID"
    touch_no_version(package)
    package["version"] = package["version"] + 1

    # Escrow: CAPTURED escrow payment draws settled balance; the hold converts
    # to spend (package no longer ASSESSED). recompute() derives both (PRD §3.4).
    recompute(submitter)
    touch(submitter)

    return created(out(payment))


@bp.route("/packages/<pid>/payments", methods=["GET"])
def list_payments(pid):
    require_auth(ALL_READERS)
    get_or_404(db.packages, pid)
    items = sort_created([p for p in db.payments.values() if p["package_id"] == pid])
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


# --------------------------------------------------------------------------
# record: PAID -> RECORDED  (page-stamp / mint / index / book roll cascade)
# --------------------------------------------------------------------------

@bp.route("/packages/<pid>/record", methods=["POST"])
def record_package(pid):
    caller = require_auth([RECORDER])
    package = get_or_404(db.packages, pid)

    # State (priority 5)
    if package["status"] != "PAID":
        raise errors.err(errors.ERR_INVALID_STATE, "Package is not PAID")
    # Compliance (priority 7): segregation of duties
    if caller.user_id == package["examiner_user_id"]:
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES, "Recorder is the examiner of record")
    # Index completeness (priority 8)
    if not _has_grantor_and_grantee(pid):
        raise errors.err(errors.ERR_INDEX_INCOMPLETE, "Need at least one GRANTOR and one GRANTEE")

    office = db.offices[package["office_id"]]
    assessment = _finalized_assessment(pid)

    # cascade link 1: mint RecordedDocument at the office's current counters
    did = new_id()
    recorded = {
        "id": did,
        "package_id": pid,
        "instrument_number": office["next_instrument_number"],
        "book": office["current_book"],
        "page": office["current_page"],
        "recorded_on": office["recording_date"],
        "status": "RECORDED",
    }
    recorded.update(common_fields())
    db.recorded_documents[did] = recorded

    # cascade link 2: advance office counters
    office["next_instrument_number"] += 1
    office["current_page"] += package["verified_page_count"]
    office["documents_in_current_book"] += 1
    # cascade link 3: book roll if capacity reached
    if office["documents_in_current_book"] >= office["book_capacity"]:
        office["current_book"] += 1
        office["documents_in_current_book"] = 0
        office["current_page"] = 1

    # index parties: PENDING -> INDEXED; office.total_indexed_entries += count
    indexed_count = 0
    for pe in _party_entries_for(pid):
        if pe["status"] == "PENDING":
            pe["status"] = "INDEXED"
            touch(pe)
            indexed_count += 1
    office["total_indexed_entries"] += indexed_count

    # office daily ledger
    office["daily_collected_cents"] += assessment["total_due_cents"]
    touch(office)

    package["status"] = "RECORDED"
    touch_no_version(package)
    return created(out(recorded))


@bp.route("/packages/<pid>/recorded-document", methods=["GET"])
def get_package_recorded_document(pid):
    require_auth(ALL_READERS)
    get_or_404(db.packages, pid)
    items = sort_created([d for d in db.recorded_documents.values() if d["package_id"] == pid])
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


# --------------------------------------------------------------------------
# withdraw: SUBMITTED|REJECTED -> WITHDRAWN
# --------------------------------------------------------------------------

@bp.route("/packages/<pid>/withdraw", methods=["POST"])
def withdraw_package(pid):
    caller = require_auth([SUBMITTER])
    package = get_or_404(db.packages, pid)

    # State (priority 5)
    if package["status"] not in ("SUBMITTED", "REJECTED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Package is not SUBMITTED or REJECTED")
    # Ownership (priority 6)
    _require_owner(caller, package)

    package["status"] = "WITHDRAWN"
    touch_no_version(package)
    for pe in _party_entries_for(pid):
        if pe["status"] != "VOIDED":
            pe["status"] = "VOIDED"
            touch(pe)
    return ok(out(package))
