"""Filing endpoints: open slot, list, get, mark-ready, file (OCC + deadline +
UTP gate + RTP cascade), accept, reject, amend, request-extension,
resolve-extension.

Filings carry two parallel state dimensions: status (PENDING -> READY -> FILED
-> ACCEPTED terminal, with REJECTED -> AMENDED -> READY re-entry) and
extension_status (NONE -> REQUESTED -> GRANTED|DENIED), the latter legal only
while status is PENDING or READY.
"""
from flask import Blueprint

from db import db, new_record, touch, bump_year
from errors import (
    raise_error,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION,
    ERR_TAX_YEAR_NOT_OPEN,
    ERR_TAX_YEAR_NOT_LOCKED,
    ERR_STALE_VERSION,
    ERR_EXTENSION_WINDOW_MISSED,
    ERR_FILING_DEADLINE_PASSED,
    ERR_UTP_UNDISCLOSED,
    ERR_INVALID_AMOUNT,
)
from middleware import authorized, READER_ROLES
from response import success_object, success_list
from routes.common import get_or_404, apply_filters, paginate
from serializers import serialize
from services.calc import (
    recompute_open_year_stack_and_etrs,
    recompute_rtp,
    recompute_etrs,
    respread_rtp_payments,
)
from util import CLOCK, is_date_str, parse_date, add_months, fmt_date
from validate import (
    body_json, present_int, req_str, req_int, req_enum, req_date,
    req_nonempty_str,
)

bp = Blueprint("filings", __name__)


@bp.route("/tax/filings", methods=["POST"])
def create_filing():
    authorized(("TaxAccountant",))
    data = body_json()

    # Priority 3 (existence): body FK references resolve.
    tax_year_id = data.get("tax_year_id")
    year = None
    if isinstance(tax_year_id, str):
        year = get_or_404(db.tax_years, tax_year_id, "TaxYear")
    jur_probe = data.get("jurisdiction_id")
    if isinstance(jur_probe, str):
        get_or_404(db.jurisdictions, jur_probe, "Jurisdiction")

    # Priority 5 (tax-year posture): opening a filing slot requires OPEN.
    if year is not None and year["status"] != "OPEN":
        raise_error(ERR_TAX_YEAR_NOT_OPEN,
                    "filings may be opened only while the year is OPEN")

    # Priority 11 (structural).
    tax_year_id = req_str(data, "tax_year_id")
    jurisdiction_id = req_str(data, "jurisdiction_id")
    original_due_date = req_date(data, "original_due_date")
    if year is None:
        raise_error(ERR_NOT_FOUND, f"TaxYear '{tax_year_id}' does not exist")
    get_or_404(db.jurisdictions, jurisdiction_id, "Jurisdiction")

    filing = new_record({
        "tax_year_id": tax_year_id,
        "jurisdiction_id": jurisdiction_id,
        "original_due_date": original_due_date,
        "extended_due_date": None,
        "extension_status": "NONE",
        "status": "PENDING",
        "return_tax_liability_cents": None,
        "estimated_liability_cents": 0,
        "filed_on": None,
        "is_late": False,
    })
    db.filings[filing["id"]] = filing

    # The jurisdiction enters the current_tax_stack input set; recompute.
    recompute_open_year_stack_and_etrs(year)
    return success_object(serialize(filing), status=201)


@bp.route("/tax/filings", methods=["GET"])
def list_filings():
    authorized(READER_ROLES)
    recs = apply_filters(db.filings.values(), {
        "tax_year_id": "tax_year_id",
        "jurisdiction_id": "jurisdiction_id",
        "status": "status",
    })
    page, total, limit, offset = paginate(recs)
    return success_list([serialize(r) for r in page], total, limit, offset)


@bp.route("/tax/filings/<filingId>", methods=["GET"])
def get_filing(filingId):
    authorized(READER_ROLES)
    return success_object(serialize(get_or_404(db.filings, filingId, "Filing")))


@bp.route("/tax/filings/<filingId>/mark-ready", methods=["POST"])
def mark_ready(filingId):
    authorized(("TaxAccountant",))
    filing = get_or_404(db.filings, filingId, "Filing")
    if filing["status"] not in ("PENDING", "AMENDED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"mark-ready is not defined from filing status {filing['status']}")

    # Priority 5 (posture): PENDING requires PROVISION_LOCKED; the AMENDED
    # re-entry also admits RETURNS_FILED.
    year = db.tax_years.get(filing["tax_year_id"])
    if year is not None:
        ok = (year["status"] == "PROVISION_LOCKED" if filing["status"] == "PENDING"
              else year["status"] in ("PROVISION_LOCKED", "RETURNS_FILED"))
        if not ok:
            raise_error(ERR_TAX_YEAR_NOT_LOCKED,
                        "mark-ready requires the year to be PROVISION_LOCKED or later")

    data = body_json()

    # Priority 10 (amount sanity): the return's tax liability must be positive.
    liab_probe = present_int(data, "return_tax_liability_cents")
    if liab_probe is not None and liab_probe <= 0:
        raise_error(ERR_INVALID_AMOUNT, "return_tax_liability_cents must be > 0")

    # Priority 11 (structural).
    liability = req_int(data, "return_tax_liability_cents")

    filing["return_tax_liability_cents"] = liability
    filing["status"] = "READY"
    touch(filing)
    return success_object(serialize(filing))


def _effective_due_date(filing):
    if filing["extension_status"] == "GRANTED" and filing["extended_due_date"]:
        return parse_date(filing["extended_due_date"])
    return parse_date(filing["original_due_date"])


@bp.route("/tax/filings/<filingId>/file", methods=["POST"])
def file_filing(filingId):
    authorized(("TaxDirector",))
    filing = get_or_404(db.filings, filingId, "Filing")
    if filing["status"] != "READY":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"file is not defined from filing status {filing['status']}")

    year = db.tax_years.get(filing["tax_year_id"])

    # Priority 5 (posture): filing requires PROVISION_LOCKED or later (pre-CLOSED).
    if year is not None and year["status"] not in ("PROVISION_LOCKED", "RETURNS_FILED"):
        raise_error(ERR_TAX_YEAR_NOT_LOCKED,
                    "file requires the year to be PROVISION_LOCKED or later")

    data = body_json()

    # Optimistic concurrency (PRD §2.8): expected_tax_year_version must match.
    expected = present_int(data, "expected_tax_year_version")
    if year is not None and expected is not None and expected != year["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_tax_year_version does not match the TaxYear's current version")

    # Priority 8 (deadline discipline): clock date <= effective due date.
    today = CLOCK.today()
    effective_due = _effective_due_date(filing)
    if today > effective_due:
        raise_error(ERR_FILING_DEADLINE_PASSED,
                    "the effective due date (extended when GRANTED) has passed")

    # Priority 9 (cross-entity readiness): every disclosure-required UTP of the
    # (year, jurisdiction) pair must be DISCLOSED, SETTLED, or LAPSED.
    for pos in db.utps.values():
        if (pos["tax_year_id"] == filing["tax_year_id"]
                and pos["jurisdiction_id"] == filing["jurisdiction_id"]
                and pos["disclosure_required"]
                and pos["status"] not in ("DISCLOSED", "SETTLED", "LAPSED")):
            raise_error(ERR_UTP_UNDISCLOSED,
                        "a disclosure-required uncertain tax position is not yet disclosed")

    # Priority 11 (structural).
    req_int(data, "expected_tax_year_version")

    filing["status"] = "FILED"
    filing["filed_on"] = today.isoformat()
    filing["is_late"] = today > effective_due
    touch(filing)

    # RTP cascade hop 1: full recompute of the true-up and the actual ETR.
    recompute_rtp(year)
    recompute_etrs(year)
    # RTP cascade hop 2: re-spread this filing's delta across the jurisdiction's
    # SCHEDULED CURRENT_YEAR_ANNUALIZED quarters (from base — idempotent).
    respread_rtp_payments(year, filing)
    bump_year(year)
    return success_object(serialize(filing))


@bp.route("/tax/filings/<filingId>/accept", methods=["POST"])
def accept_filing(filingId):
    authorized(("TaxManager",))
    filing = get_or_404(db.filings, filingId, "Filing")
    if filing["status"] != "FILED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"accept is not defined from filing status {filing['status']}")
    filing["status"] = "ACCEPTED"
    touch(filing)
    return success_object(serialize(filing))


@bp.route("/tax/filings/<filingId>/reject", methods=["POST"])
def reject_filing(filingId):
    authorized(("TaxManager",))
    filing = get_or_404(db.filings, filingId, "Filing")
    if filing["status"] != "FILED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"reject is not defined from filing status {filing['status']}")
    data = body_json()
    req_nonempty_str(data, "rejection_reason")  # structural (priority 11)

    filing["status"] = "REJECTED"
    touch(filing)

    # REJECTED filings drop out of the filed set: RTP and actual ETR recompute.
    year = db.tax_years.get(filing["tax_year_id"])
    if year is not None:
        recompute_rtp(year)
        recompute_etrs(year)
        bump_year(year)
    return success_object(serialize(filing))


@bp.route("/tax/filings/<filingId>/amend", methods=["POST"])
def amend_filing(filingId):
    authorized(("TaxAccountant",))
    filing = get_or_404(db.filings, filingId, "Filing")
    if filing["status"] != "REJECTED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"amend is not defined from filing status {filing['status']}")
    data = body_json()

    # Priority 10 (amount sanity): the corrected liability must be positive.
    liab_probe = present_int(data, "return_tax_liability_cents")
    if liab_probe is not None and liab_probe <= 0:
        raise_error(ERR_INVALID_AMOUNT, "return_tax_liability_cents must be > 0")

    liability = req_int(data, "return_tax_liability_cents")
    filing["return_tax_liability_cents"] = liability
    filing["status"] = "AMENDED"
    touch(filing)
    return success_object(serialize(filing))


@bp.route("/tax/filings/<filingId>/request-extension", methods=["POST"])
def request_extension(filingId):
    authorized(("TaxAccountant",))
    filing = get_or_404(db.filings, filingId, "Filing")
    # Extension motions are legal only while status is PENDING or READY and
    # extension_status is still NONE; they never change status.
    if filing["status"] not in ("PENDING", "READY") or filing["extension_status"] != "NONE":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "an extension may be requested only while the filing is PENDING/READY "
                    "with extension_status NONE")

    # Priority 8 (deadline discipline): on or before the original due date.
    if CLOCK.today() > parse_date(filing["original_due_date"]):
        raise_error(ERR_EXTENSION_WINDOW_MISSED,
                    "the original due date has passed")

    filing["extension_status"] = "REQUESTED"
    touch(filing)
    return success_object(serialize(filing))


@bp.route("/tax/filings/<filingId>/resolve-extension", methods=["POST"])
def resolve_extension(filingId):
    authorized(("TaxDirector",))
    filing = get_or_404(db.filings, filingId, "Filing")
    if filing["status"] not in ("PENDING", "READY") or filing["extension_status"] != "REQUESTED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "an extension may be resolved only while the filing is PENDING/READY "
                    "with extension_status REQUESTED")

    data = body_json()
    decision = req_enum(data, "decision", ("GRANTED", "DENIED"))  # structural (p11)

    filing["extension_status"] = decision
    if decision == "GRANTED":
        jur = db.jurisdictions.get(filing["jurisdiction_id"])
        months = jur["extension_months"] if jur is not None else 6
        filing["extended_due_date"] = fmt_date(
            add_months(parse_date(filing["original_due_date"]), months))
    touch(filing)
    return success_object(serialize(filing))
