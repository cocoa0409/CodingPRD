"""AuditCase endpoints: open (half-open exam-period non-overlap), list, get,
propose-adjustment, negotiate, revise-adjustment (negotiation loop), close.

Exam periods are half-open [start, end): an existing audit's end == a new
audit's start is legal adjacency; any true intersection is
ERR_AUDIT_PERIOD_OVERLAP. Only non-closed audits of the same jurisdiction
participate.
"""
from flask import Blueprint

from db import db, new_record, touch
from errors import (
    raise_error,
    ERR_INVALID_STATE_TRANSITION,
    ERR_AUDIT_PERIOD_OVERLAP,
    ERR_DATE_RANGE_INVALID,
    ERR_UNRESOLVED_NOTICES,
    ERR_INVALID_AMOUNT,
)
from middleware import authorized, READER_ROLES
from response import success_object, success_list
from routes.common import get_or_404, apply_filters, paginate
from serializers import serialize
from util import CLOCK, is_date_str, parse_date
from validate import body_json, present_int, req_str, req_int, req_enum, req_date

bp = Blueprint("audits", __name__)

NON_CLOSED_AUDIT_STATUSES = ("UNDER_EXAMINATION", "ADJUSTMENT_PROPOSED", "NEGOTIATING")
CLOSE_OUTCOMES = ("NO_CHANGE", "AGREED")


@bp.route("/tax/audits", methods=["POST"])
def create_audit():
    authorized(("TaxManager",))
    data = body_json()

    # Priority 3 (existence): body FK references resolve.
    tax_year_id = data.get("tax_year_id")
    if isinstance(tax_year_id, str):
        get_or_404(db.tax_years, tax_year_id, "TaxYear")
    jur_probe = data.get("jurisdiction_id")
    if isinstance(jur_probe, str):
        get_or_404(db.jurisdictions, jur_probe, "Jurisdiction")

    # Priority 7 (interval constraint): half-open overlap against non-closed
    # audits of the same jurisdiction (existing.end == new.start is legal).
    ps_raw, pe_raw = data.get("exam_period_start"), data.get("exam_period_end")
    if isinstance(jur_probe, str) and is_date_str(ps_raw) and is_date_str(pe_raw):
        start, end = parse_date(ps_raw), parse_date(pe_raw)
        for a in db.audits.values():
            if a["jurisdiction_id"] != jur_probe or a["status"] not in NON_CLOSED_AUDIT_STATUSES:
                continue
            if start < parse_date(a["exam_period_end"]) and parse_date(a["exam_period_start"]) < end:
                raise_error(ERR_AUDIT_PERIOD_OVERLAP,
                            "exam period intersects a non-closed audit of the same jurisdiction")

    # Priority 8 (date-range sanity): the exclusive end must be after the start.
    if is_date_str(ps_raw) and is_date_str(pe_raw):
        if parse_date(pe_raw) <= parse_date(ps_raw):
            raise_error(ERR_DATE_RANGE_INVALID,
                        "exam_period_end must be after exam_period_start")

    # Priority 11 (structural).
    tax_year_id = req_str(data, "tax_year_id")
    jurisdiction_id = req_str(data, "jurisdiction_id")
    exam_start = req_date(data, "exam_period_start")
    exam_end = req_date(data, "exam_period_end")
    get_or_404(db.tax_years, tax_year_id, "TaxYear")
    get_or_404(db.jurisdictions, jurisdiction_id, "Jurisdiction")

    audit = new_record({
        "tax_year_id": tax_year_id,
        "jurisdiction_id": jurisdiction_id,
        "exam_period_start": exam_start,
        "exam_period_end": exam_end,
        "opened_on": CLOCK.today().isoformat(),
        "proposed_adjustment_cents": None,
        "agreed_adjustment_cents": None,
        "status": "UNDER_EXAMINATION",
    })
    db.audits[audit["id"]] = audit
    return success_object(serialize(audit), status=201)


@bp.route("/tax/audits", methods=["GET"])
def list_audits():
    authorized(READER_ROLES)
    recs = apply_filters(db.audits.values(), {
        "tax_year_id": "tax_year_id",
        "jurisdiction_id": "jurisdiction_id",
        "status": "status",
    })
    page, total, limit, offset = paginate(recs)
    return success_list([serialize(r) for r in page], total, limit, offset)


@bp.route("/tax/audits/<auditId>", methods=["GET"])
def get_audit(auditId):
    authorized(READER_ROLES)
    return success_object(serialize(get_or_404(db.audits, auditId, "AuditCase")))


def _audit_target(audit_id, allowed_from, action):
    audit = get_or_404(db.audits, audit_id, "AuditCase")
    if audit["status"] not in allowed_from:
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"{action} is not defined from audit status {audit['status']}")
    return audit


def _set_proposal(audit, data):
    amt_probe = present_int(data, "proposed_adjustment_cents")
    if amt_probe is not None and amt_probe < 0:
        raise_error(ERR_INVALID_AMOUNT, "proposed_adjustment_cents must be >= 0")
    audit["proposed_adjustment_cents"] = req_int(data, "proposed_adjustment_cents")


@bp.route("/tax/audits/<auditId>/propose-adjustment", methods=["POST"])
def propose_adjustment(auditId):
    authorized(("TaxManager",))
    audit = _audit_target(auditId, ("UNDER_EXAMINATION",), "propose-adjustment")
    _set_proposal(audit, body_json())
    audit["status"] = "ADJUSTMENT_PROPOSED"
    touch(audit)
    return success_object(serialize(audit))


@bp.route("/tax/audits/<auditId>/negotiate", methods=["POST"])
def negotiate(auditId):
    authorized(("TaxManager",))
    audit = _audit_target(auditId, ("ADJUSTMENT_PROPOSED",), "negotiate")
    audit["status"] = "NEGOTIATING"
    touch(audit)
    return success_object(serialize(audit))


@bp.route("/tax/audits/<auditId>/revise-adjustment", methods=["POST"])
def revise_adjustment(auditId):
    authorized(("TaxManager",))
    audit = _audit_target(auditId, ("NEGOTIATING",), "revise-adjustment")
    _set_proposal(audit, body_json())
    audit["status"] = "ADJUSTMENT_PROPOSED"
    touch(audit)
    return success_object(serialize(audit))


@bp.route("/tax/audits/<auditId>/close", methods=["POST"])
def close_audit(auditId):
    authorized(("TaxManager",))
    audit = get_or_404(db.audits, auditId, "AuditCase")

    # Priority 4 (state): close is defined only from the three open states, and
    # the outcome must name a declared transition from the current state.
    if audit["status"] not in NON_CLOSED_AUDIT_STATUSES:
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"close is not defined from audit status {audit['status']}")
    data = body_json()
    outcome_probe = data.get("outcome")
    if isinstance(outcome_probe, str) and outcome_probe in CLOSE_OUTCOMES:
        legal = (("NO_CHANGE",) if audit["status"] == "UNDER_EXAMINATION"
                 else ("AGREED",))  # ADJUSTMENT_PROPOSED | NEGOTIATING
        if outcome_probe not in legal:
            raise_error(ERR_INVALID_STATE_TRANSITION,
                        f"outcome {outcome_probe} is not defined from status {audit['status']}")

    # Priority 9 (cross-entity readiness): every linked notice RESOLVED.
    if any(n["audit_case_id"] == audit["id"] and n["status"] != "RESOLVED"
           for n in db.notices.values()):
        raise_error(ERR_UNRESOLVED_NOTICES,
                    "every TaxNotice linked to the audit must be RESOLVED")

    # Priority 10 (amount sanity): an AGREED assessment is nonnegative.
    agreed_probe = present_int(data, "agreed_adjustment_cents")
    if agreed_probe is not None and agreed_probe < 0:
        raise_error(ERR_INVALID_AMOUNT, "agreed_adjustment_cents must be >= 0")

    # Priority 11 (structural): outcome enum; AGREED additionally requires the
    # agreed amount to be present.
    outcome = req_enum(data, "outcome", CLOSE_OUTCOMES)
    if outcome == "AGREED":
        audit["agreed_adjustment_cents"] = req_int(data, "agreed_adjustment_cents")
        audit["status"] = "CLOSED_AGREED"
    else:
        audit["status"] = "CLOSED_NO_CHANGE"
    touch(audit)
    return success_object(serialize(audit))
