"""Application routes — CRUD + docket + pay-issue-fee + convert."""

from flask import Blueprint, request

from db import db, new_id
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services.body import (
    get_json_body,
    require_string,
    require_int,
    optional_int,
    optional_string,
    optional_enum,
    require_enum,
)
from services.calc import (
    filing_fee,
    issue_fee,
    micro_eligible,
)
from services.dateutil import add_months, add_years
from services.pagination import parse_pagination, slice_sorted
from services.serialize import application_to_wire
from services.application_svc import (
    APP_TERMINAL_STATES,
    CONTINUATION_TYPES,
    compute_priority_date,
    compute_term_expiration,
    recompute_total_fees,
    bump_application,
)


bp = Blueprint("applications", __name__)


APPLICATION_TYPES = {"UTILITY", "DESIGN", "PROVISIONAL", "PCT_NATIONAL"}


def _validate_claim_range(claim_count: int, indep: int):
    if not (1 <= claim_count <= 500):
        raise_api("ERR_CLAIM_COUNTS_INVALID", "claim_count must be in [1, 500]")
    if not (1 <= indep <= 500):
        raise_api("ERR_CLAIM_COUNTS_INVALID", "independent_claim_count must be in [1, 500]")
    if indep > claim_count:
        raise_api(
            "ERR_CLAIM_COUNTS_INVALID",
            "independent_claim_count must not exceed claim_count",
        )


# ---------------------------------------------------------------------------
# POST /applications
# ---------------------------------------------------------------------------
@bp.route("/applications", methods=["POST"])
@require_roles("Applicant")
def create_application(_user_id, _role):
    body = get_json_body()
    applicant_id = require_string(body, "applicant_id")
    application_type = require_enum(body, "application_type", APPLICATION_TYPES)
    title = require_string(body, "title", min_len=3, max_len=500)
    claim_count = require_int(body, "claim_count")
    indep = require_int(body, "independent_claim_count")
    parent_application_id = optional_string(body, "parent_application_id")
    continuation_type = optional_enum(
        body, "continuation_type", CONTINUATION_TYPES, default=None
    )

    # Priority 5: existence — applicant_id FK
    applicant = db.applicants.get(applicant_id)
    if applicant is None:
        raise_api(
            "ERR_APPLICATION_NOT_FOUND",
            f"Applicant {applicant_id} not found",
        )

    # parent_application_id FK existence (priority 5) — only validate if provided
    parent_app = None
    if parent_application_id is not None:
        parent_app = db.applications.get(parent_application_id)
        if parent_app is None:
            raise_api(
                "ERR_APPLICATION_NOT_FOUND",
                f"Parent application {parent_application_id} not found",
            )

    # Priority 8: VAL-CONT-PARENT-PARENT_NULL coherence
    if (parent_application_id is None) != (continuation_type is None):
        raise_api(
            "ERR_CONTINUATION_TYPE_MISMATCH",
            "parent_application_id and continuation_type must both be set or both null",
        )

    # Priority 9: VAL-CONT-PARENT-NOT-TERMINAL
    if parent_app is not None and parent_app["status"] in APP_TERMINAL_STATES:
        raise_api(
            "ERR_CONTINUATION_PARENT_TERMINAL",
            f"Parent application is in terminal state {parent_app['status']}",
        )

    # Priority 10: VAL-FEE-MICRO-INCOME (re-evaluated for MICRO applicants)
    if applicant["entity_size"] == "MICRO" and not micro_eligible(applicant):
        raise_api("ERR_MICRO_INELIGIBLE", "MICRO entity eligibility predicate failed")

    # Priority 16: claim-count range
    _validate_claim_range(claim_count, indep)

    # Create the row -------------------------------------------------------
    now = db.current_utc_dt()
    app_id = new_id()
    application = {
        "id": app_id,
        "applicant_id": applicant_id,
        "application_type": application_type,
        "title": title,
        "claim_count": claim_count,
        "independent_claim_count": indep,
        "filing_date": now,
        "status": "FILED",
        "parent_application_id": parent_application_id,
        "continuation_type": continuation_type,
        "priority_date": None,  # filled in below
        "total_fees_paid_cents": 0,
        "issued_patent_number": None,
        "issue_date": None,
        "term_expiration_date": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    application["priority_date"] = compute_priority_date(
        parent_application_id, continuation_type, now
    )

    db.applications[app_id] = application
    return success(application_to_wire(application), http_status=201)


# ---------------------------------------------------------------------------
# GET /applications/{id}
# ---------------------------------------------------------------------------
@bp.route("/applications/<app_id>", methods=["GET"])
@require_roles("Applicant", "USPTOAdmin", "USPTOExaminer")
def get_application(app_id, **_):
    app = db.applications.get(app_id)
    if app is None:
        raise_api("ERR_APPLICATION_NOT_FOUND", f"Application {app_id} not found")
    return success(application_to_wire(app))


# ---------------------------------------------------------------------------
# GET /applications
# ---------------------------------------------------------------------------
@bp.route("/applications", methods=["GET"])
@require_roles("Applicant", "USPTOAdmin", "USPTOExaminer")
def list_applications(**_):
    limit, offset = parse_pagination()
    applicant_filter = request.args.get("applicant_id")
    parent_filter = request.args.get("parent_application_id")

    items = []
    for app in db.applications.values():
        if applicant_filter and app["applicant_id"] != applicant_filter:
            continue
        if parent_filter and app.get("parent_application_id") != parent_filter:
            continue
        items.append(app)
    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [application_to_wire(a) for a in page], limit, offset, total
    )


# ---------------------------------------------------------------------------
# POST /applications/{id}/docket
# ---------------------------------------------------------------------------
@bp.route("/applications/<app_id>/docket", methods=["POST"])
@require_roles("USPTOExaminer")
def docket_application(app_id, **_):
    app = db.applications.get(app_id)
    if app is None:
        raise_api("ERR_APPLICATION_NOT_FOUND", f"Application {app_id} not found")

    # Priority 6/7 state checks
    if app["status"] in APP_TERMINAL_STATES or app["status"] == "ISSUED":
        raise_api("ERR_TERMINAL_STATE", f"Application status {app['status']} is terminal")
    if app["status"] != "FILED":
        raise_api(
            "ERR_INVALID_STATE",
            f"Docket requires status=FILED (current: {app['status']})",
        )

    # Provisional cannot be docketed (per scaffold precondition)
    if app["application_type"] == "PROVISIONAL":
        raise_api(
            "ERR_INVALID_STATE",
            "PROVISIONAL applications cannot be docketed",
        )

    # Filing-fee precondition: total_fees_paid_cents >= filing fee for (type, size)
    applicant = db.applicants.get(app["applicant_id"])
    if applicant is None:
        # defensive — applicant must always exist since FK is checked at create
        raise_api("ERR_APPLICATION_NOT_FOUND", "Applicant for this application was not found")
    expected_filing = filing_fee(app["application_type"], applicant["entity_size"])
    if app.get("total_fees_paid_cents", 0) < expected_filing:
        raise_api(
            "ERR_INVALID_STATE",
            f"Filing fee not posted: have {app.get('total_fees_paid_cents', 0)}, need {expected_filing}",
        )

    app["status"] = "AWAITING_EXAMINATION"
    bump_application(app)
    return success(application_to_wire(app))


# ---------------------------------------------------------------------------
# POST /applications/{id}/pay-issue-fee
# ---------------------------------------------------------------------------
@bp.route("/applications/<app_id>/pay-issue-fee", methods=["POST"])
@require_roles("Applicant")
def pay_issue_fee(app_id, _user_id, _role):
    app = db.applications.get(app_id)
    if app is None:
        raise_api("ERR_APPLICATION_NOT_FOUND", f"Application {app_id} not found")

    body = get_json_body()
    amount_cents = require_int(body, "amount_cents")
    expected_version = require_int(body, "expected_application_version")

    # Priority 6/7 state
    if app["status"] in APP_TERMINAL_STATES or app["status"] == "ISSUED":
        raise_api("ERR_TERMINAL_STATE", f"Application status {app['status']} is terminal")
    if app["status"] != "ALLOWED":
        raise_api(
            "ERR_INVALID_STATE",
            f"Pay-issue-fee requires status=ALLOWED (current: {app['status']})",
        )

    # Priority 15: VAL-FEE-AMOUNT-EXACT
    applicant = db.applicants.get(app["applicant_id"])
    if applicant is None:
        raise_api("ERR_APPLICATION_NOT_FOUND", "Applicant for this application was not found")
    expected = issue_fee(app["application_type"], applicant["entity_size"])
    if amount_cents != expected:
        raise_api(
            "ERR_FEE_AMOUNT_MISMATCH",
            f"Expected {expected} cents, got {amount_cents}",
        )

    # Priority 19: VAL-OCC-VERSION
    if expected_version != app["version"]:
        raise_api(
            "ERR_STALE_VERSION",
            f"expected_application_version {expected_version} != current {app['version']}",
        )

    # ---- Side effects (atomic) -----------------------------------------
    now = db.current_utc_dt()

    # Append fee payment to ledger (FeePayment is append-only / no version)
    fp_id = new_id()
    fp = {
        "id": fp_id,
        "application_id": app_id,
        "payment_category": "ISSUE",
        "amount_cents": amount_cents,
        "maintenance_fee_id": None,
        "payment_status": "POSTED",
        "created_at": now,
    }
    db.fee_payments[fp_id] = fp

    # Stamp issuance fields
    app["issue_date"] = now
    app["issued_patent_number"] = db.mint_patent_number()
    app["status"] = "ISSUED"
    app["term_expiration_date"] = compute_term_expiration(app)
    app["total_fees_paid_cents"] = recompute_total_fees(app_id)
    bump_application(app)

    # For UTILITY, generate three MaintenanceFee rows
    if app["application_type"] == "UTILITY":
        issue_dt = app["issue_date"]
        for window in (1, 2, 3):
            if window == 1:
                open_dt = add_months(issue_dt, 42)   # 3.5 years
                due_dt = add_years(issue_dt, 4)
            elif window == 2:
                open_dt = add_months(issue_dt, 90)   # 7.5 years
                due_dt = add_years(issue_dt, 8)
            else:
                open_dt = add_months(issue_dt, 138)  # 11.5 years
                due_dt = add_years(issue_dt, 12)
            grace_dt = add_months(due_dt, 6)
            from services.calc import maintenance_base_fee
            mf_id = new_id()
            mf = {
                "id": mf_id,
                "application_id": app_id,
                "window_number": window,
                "window_open_date": open_dt,
                "window_due_date": due_dt,
                "window_grace_date": grace_dt,
                "base_fee_cents": maintenance_base_fee(window, applicant["entity_size"]),
                "fee_status": "PENDING",
                "paid_at": None,
                "created_at": now,
                "updated_at": now,
                "version": 1,
            }
            db.maintenance_fees[mf_id] = mf

    return success(application_to_wire(app))


# ---------------------------------------------------------------------------
# POST /applications/{id}/convert-provisional-to-utility
# ---------------------------------------------------------------------------
@bp.route(
    "/applications/<app_id>/convert-provisional-to-utility", methods=["POST"]
)
@require_roles("Applicant")
def convert_provisional(app_id, _user_id, _role):
    app = db.applications.get(app_id)
    if app is None:
        raise_api("ERR_APPLICATION_NOT_FOUND", f"Application {app_id} not found")

    body = get_json_body()
    title = require_string(body, "title", min_len=3, max_len=500)
    claim_count = require_int(body, "claim_count")
    indep = require_int(body, "independent_claim_count")
    expected_version = require_int(body, "expected_application_version")

    # Priority 6/7: state
    if app["application_type"] != "PROVISIONAL":
        # Not a provisional → invalid state for this operation
        raise_api(
            "ERR_INVALID_STATE",
            "Conversion only valid for PROVISIONAL applications",
        )

    # If already converted/expired → terminal-state lockdown (priority 7)
    if app["status"] == "CONVERTED":
        # Specific rule: VAL-CONV-ONE-TIME (priority 13)
        raise_api(
            "ERR_PROVISIONAL_ALREADY_CONVERTED",
            "PROVISIONAL has already been converted",
        )
    if app["status"] in {"ABANDONED", "EXPIRED", "ISSUED"}:
        raise_api(
            "ERR_TERMINAL_STATE",
            f"Application status {app['status']} is terminal",
        )
    if app["status"] != "FILED":
        raise_api(
            "ERR_INVALID_STATE",
            f"Conversion requires status=FILED (current: {app['status']})",
        )

    # Priority 12: VAL-CONV-DEADLINE — within 12 months
    deadline = add_months(app["filing_date"], 12)
    if db.current_utc_dt() > deadline:
        raise_api(
            "ERR_PROVISIONAL_CONVERSION_LATE",
            "Conversion attempted more than 12 months after filing_date",
        )

    # Priority 16: claim-count range
    _validate_claim_range(claim_count, indep)

    # Priority 19: OCC
    if expected_version != app["version"]:
        raise_api(
            "ERR_STALE_VERSION",
            f"expected_application_version {expected_version} != current {app['version']}",
        )

    # ---- Side effects ---------------------------------------------------
    now = db.current_utc_dt()
    new_app_id = new_id()
    new_app = {
        "id": new_app_id,
        "applicant_id": app["applicant_id"],
        "application_type": "UTILITY",
        "title": title,
        "claim_count": claim_count,
        "independent_claim_count": indep,
        "filing_date": now,
        "status": "FILED",
        "parent_application_id": app_id,
        "continuation_type": None,  # conversion is distinct from continuation
        "priority_date": app["filing_date"],   # inherits source provisional's filing_date
        "total_fees_paid_cents": 0,
        "issued_patent_number": None,
        "issue_date": None,
        "term_expiration_date": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.applications[new_app_id] = new_app

    # Source: FILED → CONVERTED
    app["status"] = "CONVERTED"
    bump_application(app)

    return success(application_to_wire(new_app), http_status=201)
