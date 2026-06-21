"""Flat top-level reverse-reachability GET endpoints (PRD §2.5, §4)."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_NOT_FOUND
from middleware import require_roles
from response import object_response, array_response
from serialize import public, public_list
from services.common import apply_page, paginate, sorted_by_created

bp = Blueprint("flat", __name__)

READ_ROLES = ("Officer", "SupervisingJudge", "CompactAdministrator")


def _filtered(store, filters):
    """Return list of records matching all (field, value) filters in args."""
    records = list(store.values())
    for field, value in filters.items():
        if value is not None:
            records = [r for r in records if r.get(field) == value]
    return records


def _list(store, filter_fields):
    limit, offset = paginate(request.args)
    filters = {f: request.args.get(f) for f in filter_fields}
    records = _filtered(store, filters)
    records = sorted_by_created(records)
    page, total = apply_page(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


def _get(store, rid, label):
    rec = store.get(rid)
    if rec is None:
        raise ApiError(*ERR_NOT_FOUND, f"{label} not found.")
    return object_response(public(rec), 200)


# ---- Risk assessments ----------------------------------------------------
@bp.get("/risk-assessments/<rid>")
@require_roles(*READ_ROLES)
def get_ra(rid):
    return _get(db.risk_assessments, rid, "Risk assessment")


@bp.get("/risk-assessments")
@require_roles(*READ_ROLES)
def list_ra():
    return _list(db.risk_assessments, ["supervisee_id", "assessment_status"])


# ---- Conditions ----------------------------------------------------------
@bp.get("/conditions/<cid>")
@require_roles(*READ_ROLES)
def get_condition(cid):
    return _get(db.conditions, cid, "Condition")


@bp.get("/conditions")
@require_roles(*READ_ROLES)
def list_conditions():
    return _list(db.conditions, ["supervisee_id", "status"])


# ---- Check-ins -----------------------------------------------------------
@bp.get("/check-ins/<cid>")
@require_roles(*READ_ROLES)
def get_check_in(cid):
    return _get(db.check_ins, cid, "Check-in")


@bp.get("/check-ins")
@require_roles(*READ_ROLES)
def list_check_ins():
    return _list(db.check_ins, ["supervisee_id", "status"])


# ---- Drug tests ----------------------------------------------------------
@bp.get("/drug-tests/<dtid>")
@require_roles(*READ_ROLES)
def get_drug_test(dtid):
    return _get(db.drug_tests, dtid, "Drug test")


@bp.get("/drug-tests")
@require_roles(*READ_ROLES)
def list_drug_tests():
    return _list(db.drug_tests, ["check_in_id", "result"])


# ---- Violations ----------------------------------------------------------
@bp.get("/violations/<vid>")
@require_roles(*READ_ROLES)
def get_violation(vid):
    return _get(db.violations, vid, "Violation")


@bp.get("/violations")
@require_roles(*READ_ROLES)
def list_violations():
    return _list(
        db.violations,
        ["supervisee_id", "filed_by_officer_id", "source_drug_test_id", "status"],
    )


# ---- Sanctions -----------------------------------------------------------
@bp.get("/sanctions/<sid>")
@require_roles(*READ_ROLES)
def get_sanction(sid):
    return _get(db.sanctions, sid, "Sanction")


@bp.get("/sanctions")
@require_roles(*READ_ROLES)
def list_sanctions():
    return _list(db.sanctions, ["violation_id", "status"])


# ---- Obligations ---------------------------------------------------------
@bp.get("/obligations/<oid>")
@require_roles(*READ_ROLES)
def get_obligation(oid):
    return _get(db.obligations, oid, "Obligation")


@bp.get("/obligations")
@require_roles(*READ_ROLES)
def list_obligations():
    return _list(
        db.obligations,
        ["supervisee_id", "parent_obligation_id", "obligation_type", "status"],
    )


# ---- Payments ------------------------------------------------------------
@bp.get("/payments/<pid>")
@require_roles(*READ_ROLES)
def get_payment(pid):
    return _get(db.payments, pid, "Payment")


@bp.get("/payments")
@require_roles(*READ_ROLES)
def list_payments():
    return _list(db.payments, ["supervisee_id"])


# ---- Court reports -------------------------------------------------------
@bp.get("/court-reports/<rid>")
@require_roles(*READ_ROLES)
def get_court_report(rid):
    return _get(db.court_reports, rid, "Court report")


@bp.get("/court-reports")
@require_roles(*READ_ROLES)
def list_court_reports():
    return _list(db.court_reports, ["supervisee_id", "report_type", "status"])


# ---- Transfers -----------------------------------------------------------
@bp.get("/transfers/<tid>")
@require_roles(*READ_ROLES)
def get_transfer(tid):
    return _get(db.transfers, tid, "Transfer")


@bp.get("/transfers")
@require_roles(*READ_ROLES)
def list_transfers():
    return _list(db.transfers, ["supervisee_id", "status"])


# ---- Early terminations --------------------------------------------------
@bp.get("/early-terminations/<eid>")
@require_roles(*READ_ROLES)
def get_petition(eid):
    return _get(db.early_terminations, eid, "Early-termination petition")


@bp.get("/early-terminations")
@require_roles(*READ_ROLES)
def list_petitions():
    return _list(db.early_terminations, ["supervisee_id", "status"])
