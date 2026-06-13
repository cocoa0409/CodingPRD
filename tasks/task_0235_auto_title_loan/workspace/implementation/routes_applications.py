"""LoanApplication routes (PRD 3.3, 3.4, 3.5)."""
from flask import Blueprint, request

import db
import lookups
import calculations as calc
from clock import get_now
from errors import err
from middleware import authenticate, require_role
from response import success, list_success
from serialize import public
from timeutil import iso_now, add_days
from validate import get_body, require_str, require_int, parse_pagination, paginate

bp = Blueprint("applications", __name__)


def _sorted_public(entities):
    rows = sorted(entities, key=lambda e: e["_seq"])
    return [public(e) for e in rows]


def _run_gates(application, borrower, appraisal, prof, at_approve):
    """Business-safety/fiscal gates (PRD 3.3), in the introduced precedence.

    Order at approve: borrower eligibility (BARRED) before APR/term/LTV.
    At submit there is no borrower-status gate; the same APR/term/LTV gates run.
    """
    if at_approve:
        if borrower["status"] != "ACTIVE":
            raise err("ERR_BORROWER_BARRED", "borrower is BARRED")

    # APR cap: strict — contract == cap allowed (PRD 3.3).
    if application["contract_apr_bps"] > prof["max_apr_bps"]:
        raise err("ERR_APR_CAP_EXCEEDED", "contract_apr_bps exceeds state max_apr_bps")

    # Term bounds (PRD 3.3).
    if not (prof["min_term_months"] <= application["term_months"] <= prof["max_term_months"]):
        raise err("ERR_TERM_OUT_OF_BOUNDS", "term_months out of state bounds")

    # LTV: strict — requested == ceiling allowed (PRD 3.3).
    if application["requested_principal_cents"] > appraisal["max_principal_cents"]:
        raise err("ERR_LTV_EXCEEDED", "requested_principal_cents exceeds max_principal_cents")


@bp.route("/atl/applications", methods=["POST"])
def create_application():
    _, role = authenticate()
    require_role(role, {"Underwriter"})
    body = get_body()

    # Resolve referenced identifiers before body field-level validation (PRD 2.5),
    # left-to-right.
    borrower_id = require_str(body, "borrower_id")
    borrower = lookups.get_or_404(db.borrowers, borrower_id)
    appraisal_id = require_str(body, "appraisal_id")
    appraisal = lookups.get_or_404(db.appraisals, appraisal_id)

    requested_principal_cents = require_int(body, "requested_principal_cents")
    contract_apr_bps = require_int(body, "contract_apr_bps")
    term_months = require_int(body, "term_months")

    # Range checks (PRD 2.6 step 6).
    if requested_principal_cents <= 0:
        raise err("ERR_VALIDATION_RANGE", "requested_principal_cents must be > 0")
    if contract_apr_bps <= 0:
        raise err("ERR_VALIDATION_RANGE", "contract_apr_bps must be > 0")
    if term_months < 1:
        raise err("ERR_VALIDATION_RANGE", "term_months must be >= 1")

    prof = lookups.borrower_regulatory_profile(borrower)
    if prof is None:
        raise err("ERR_INVALID_STATE", "no regulatory profile for borrower state")

    effective_apr_bps = calc.effective_apr(contract_apr_bps, prof["max_apr_bps"])

    application = db.common_fields(with_version=True)
    application.update({
        "borrower_id": borrower_id,
        "appraisal_id": appraisal_id,
        "requested_principal_cents": requested_principal_cents,
        "contract_apr_bps": contract_apr_bps,
        "term_months": term_months,
        "effective_apr_bps": effective_apr_bps,
        "status": "SUBMITTED",
    })

    # Gates checked at submission (PRD 3.3). The LTV gate compares against the
    # appraisal's max_principal_cents (only meaningful once finalized; a DRAFT
    # appraisal has None and the strict ">" comparison treats absence below).
    if appraisal["max_principal_cents"] is None:
        # Submission references a not-yet-finalized appraisal; the LTV ceiling
        # cannot be satisfied — any positive request strictly exceeds an unset
        # ceiling. Enforce the APR/term gates first per precedence, then LTV.
        if contract_apr_bps > prof["max_apr_bps"]:
            raise err("ERR_APR_CAP_EXCEEDED", "contract_apr_bps exceeds state max_apr_bps")
        if not (prof["min_term_months"] <= term_months <= prof["max_term_months"]):
            raise err("ERR_TERM_OUT_OF_BOUNDS", "term_months out of state bounds")
        raise err("ERR_LTV_EXCEEDED", "appraisal not finalized; no LTV ceiling")

    _run_gates(application, borrower, appraisal, prof, at_approve=False)

    db.applications[application["id"]] = application
    return success(public(application), status=201)


@bp.route("/atl/applications", methods=["GET"])
def list_applications():
    _, role = authenticate()
    require_role(role, {"Underwriter", "ComplianceAdmin"})
    limit, offset = parse_pagination()
    rows = list(db.applications.values())
    borrower_id = request.args.get("borrower_id")
    appraisal_id = request.args.get("appraisal_id")
    if borrower_id is not None:
        rows = [r for r in rows if r["borrower_id"] == borrower_id]
    if appraisal_id is not None:
        rows = [r for r in rows if r["appraisal_id"] == appraisal_id]
    items = _sorted_public(rows)
    return list_success(paginate(items, limit, offset), limit, offset, len(items))


@bp.route("/atl/applications/<application_id>", methods=["GET"])
def get_application(application_id):
    _, role = authenticate()
    require_role(role, {"Underwriter", "ComplianceAdmin"})
    application = lookups.get_or_404(db.applications, application_id)
    return success(public(application), status=200)


@bp.route("/atl/applications/<application_id>/approve", methods=["POST"])
def approve_application(application_id):
    user_id, role = authenticate()
    require_role(role, {"Underwriter"})
    application = lookups.get_or_404(db.applications, application_id)

    appraisal = db.appraisals.get(application["appraisal_id"])
    borrower = db.borrowers.get(application["borrower_id"])

    # Segregation of duties (PRD 2.1, priority 3) — before existence-of-state and
    # business checks. The approving Underwriter must differ from the Appraiser
    # who finalized the backing appraisal.
    if appraisal is not None and appraisal.get("_finalized_by") == user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "approver must differ from the appraiser who finalized")

    # State legality (priority 6).
    if application["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "application not in SUBMITTED")

    # Approval requires the appraisal still FINALIZED (PRD 3.3).
    if appraisal is None or appraisal["status"] != "FINALIZED":
        raise err("ERR_INVALID_STATE", "backing appraisal not FINALIZED")

    prof = lookups.borrower_regulatory_profile(borrower)
    if prof is None:
        raise err("ERR_INVALID_STATE", "no regulatory profile for borrower state")

    # Re-verify business gates at approval, borrower-eligibility first (PRD 3.3).
    _run_gates(application, borrower, appraisal, prof, at_approve=True)

    # ---- Cascade (PRD 3.3 / 3.4 / 3.5) ----
    # Application SUBMITTED -> APPROVED
    application["status"] = "APPROVED"
    db.touch(application)

    # Appraisal FINALIZED -> CONSUMED
    appraisal["status"] = "CONSUMED"
    db.touch(appraisal)

    # Create the Loan (OUTSTANDING / CURRENT)
    loan = db.common_fields(with_version=True)
    vehicle_id = appraisal["vehicle_id"]
    loan.update({
        "application_id": application["id"],
        "borrower_id": application["borrower_id"],
        "vehicle_id": vehicle_id,
        "original_principal_cents": application["requested_principal_cents"],
        "effective_apr_bps": application["effective_apr_bps"],
        "term_months": application["term_months"],
        "principal_balance_cents": application["requested_principal_cents"],
        "accrued_interest_cents": 0,
        "fees_balance_cents": 0,
        "renewal_count": 0,
        "payoff_status": "OUTSTANDING",
        "delinquency_status": "CURRENT",
    })
    db.loans[loan["id"]] = loan

    # Create the TitleLien (PENDING); vehicle_id mirrored from the loan.
    lien = db.common_fields(with_version=True)
    lien.update({
        "loan_id": loan["id"],
        "vehicle_id": vehicle_id,
        "dmv_reference": None,
        "status": "PENDING",
    })
    db.title_liens[lien["id"]] = lien

    # Generate the amortization schedule (PRD 3.5).
    rows = calc.amortization_schedule(
        loan["original_principal_cents"],
        loan["effective_apr_bps"],
        loan["term_months"],
    )
    origination = get_now()
    for idx, r in enumerate(rows, start=1):
        due = add_days(origination, calc.FIRST_DUE_OFFSET_DAYS + (idx - 1) * calc.DUE_SPACING_DAYS)
        inst = db.common_fields(with_version=True)
        inst.update({
            "loan_id": loan["id"],
            "sequence_no": idx,
            "due_date": iso_now(due),
            "principal_due_cents": r["principal_due_cents"],
            "interest_due_cents": r["interest_due_cents"],
            "late_fee_cents": 0,
            "status": "SCHEDULED",
        })
        db.installments[inst["id"]] = inst

    # Vehicle.lien_state = ENCUMBERED
    vehicle = db.vehicles.get(vehicle_id)
    if vehicle is not None:
        vehicle["lien_state"] = "ENCUMBERED"
        db.touch(vehicle)

    return success(public(application), status=200)


@bp.route("/atl/applications/<application_id>/reject", methods=["POST"])
def reject_application(application_id):
    _, role = authenticate()
    require_role(role, {"Underwriter"})
    application = lookups.get_or_404(db.applications, application_id)

    if application["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "application not in SUBMITTED")

    application["status"] = "REJECTED"
    db.touch(application)
    return success(public(application), status=200)
