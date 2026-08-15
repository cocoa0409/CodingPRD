from datetime import timedelta

from flask import Blueprint, request

import clock
import store
from auth import ALL_ROLES, NON_BORROWER_ROLES, authenticate, authorize, check_borrower_ownership
from errors import (
    ERR_APPLICATION_STATE_INVALID,
    ERR_LOAN_NOT_FOUND,
    ERR_MODIFICATION_NOT_FOUND,
    ERR_MODIFICATION_STATE_INVALID,
    ERR_RESCISSION_WINDOW_EXPIRED,
    ERR_TRIAL_PLAN_NOT_COMPLETED,
    ERR_TRIAL_PLAN_NOT_FOUND,
    raise_err,
)
from services import (
    RESCISSION_WINDOW_DAYS,
    create_escrow_analysis,
    loan_of_modification,
    modification_out,
    run_waterfall_variant,
)
from util import body_json, bump, get_or_404, list_response, new_record, req_str, success_object

bp = Blueprint("modifications", __name__)


@bp.route("/loans/<rid>/modifications", methods=["POST"])
def create_modification(rid):
    _, role = authenticate()
    authorize(role, ["ServicingOps"])
    body = body_json()
    trial_plan_id = req_str(body, "trial_plan_id")

    loan = get_or_404(store.loans, rid, ERR_LOAN_NOT_FOUND, "Loan")
    plan = get_or_404(store.plans, trial_plan_id, ERR_TRIAL_PLAN_NOT_FOUND, "TrialPaymentPlan")

    if plan["status"] != "COMPLETED":
        raise_err(ERR_TRIAL_PLAN_NOT_COMPLETED, "Trial plan is not COMPLETED")
    app = store.applications[plan["application_id"]]
    if app["loan_id"] != loan["id"] or app["status"] != "TRIAL_PASSED":
        raise_err(ERR_APPLICATION_STATE_INVALID,
                  "Application must be TRIAL_PASSED for this loan")
    if loan["workout_status"] != "MOD_PENDING":
        raise_err(ERR_APPLICATION_STATE_INVALID,
                  "Loan workout_status must be MOD_PENDING")

    program = next((p for p in store.programs.values()
                    if p["code"] == plan["program_code"]), None)

    # final variant: base uses arrears AFTER trial-suspense application
    if program is not None:
        res = run_waterfall_variant(loan, app["verified_monthly_income_cents"], program)
        final_base = res["base"]
        final_rate = res["rate"]
        final_term = res["term"]
        final_forbearance = res["forborne"]
        final_pi = res["pi"]
    else:
        final_base = loan["unpaid_principal_balance_cents"] + loan["arrears_cents"]
        final_rate = loan["interest_rate_bp"]
        final_term = loan["remaining_term_months"]
        final_forbearance = 0
        final_pi = loan.get("current_pi_cents") or 0

    rec = new_record()
    rec.update({
        "application_id": app["id"],
        "trial_plan_id": plan["id"],
        "final_base_cents": final_base,
        "final_rate_bp": final_rate,
        "final_term_months": final_term,
        "final_forbearance_cents": final_forbearance,
        "final_pi_cents": final_pi,
        "capitalized_arrears_cents": loan["arrears_cents"],
        "prior_terms_snapshot": None,
        "status": "DRAFT",
        "recorded_at": None,
        "rescission_deadline": None,
    })
    store.modifications[rec["id"]] = rec
    return success_object(modification_out(rec), 201)


@bp.route("/modifications/<rid>", methods=["GET"])
def get_modification(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.modifications, rid, ERR_MODIFICATION_NOT_FOUND, "PermanentModification")
    return success_object(modification_out(rec))


@bp.route("/modifications", methods=["GET"])
def list_modifications():
    _, role = authenticate()
    authorize(role, NON_BORROWER_ROLES)
    records = list(store.modifications.values())
    application_id = request.args.get("application_id")
    trial_plan_id = request.args.get("trial_plan_id")
    if application_id is not None:
        records = [m for m in records if m["application_id"] == application_id]
    if trial_plan_id is not None:
        records = [m for m in records if m["trial_plan_id"] == trial_plan_id]
    return list_response(records, modification_out)


@bp.route("/modifications/<rid>/send-docs", methods=["POST"])
def send_docs(rid):
    _, role = authenticate()
    authorize(role, ["ServicingOps"])
    mod = get_or_404(store.modifications, rid, ERR_MODIFICATION_NOT_FOUND, "PermanentModification")
    if mod["status"] != "DRAFT":
        raise_err(ERR_MODIFICATION_STATE_INVALID,
                  "Modification in %s cannot send docs" % mod["status"])
    mod["status"] = "DOCS_SENT"
    bump(mod)
    return success_object(modification_out(mod))


@bp.route("/modifications/<rid>/sign", methods=["POST"])
def sign_modification(rid):
    uid, role = authenticate()
    authorize(role, ["Borrower"])
    mod = get_or_404(store.modifications, rid, ERR_MODIFICATION_NOT_FOUND, "PermanentModification")
    check_borrower_ownership(uid, loan_of_modification(mod))
    if mod["status"] != "DOCS_SENT":
        raise_err(ERR_MODIFICATION_STATE_INVALID,
                  "Modification in %s cannot be signed" % mod["status"])
    mod["status"] = "SIGNED"
    bump(mod)
    return success_object(modification_out(mod))


@bp.route("/modifications/<rid>/record", methods=["POST"])
def record_modification(rid):
    _, role = authenticate()
    authorize(role, ["ServicingOps"])
    mod = get_or_404(store.modifications, rid, ERR_MODIFICATION_NOT_FOUND, "PermanentModification")
    if mod["status"] != "SIGNED":
        raise_err(ERR_MODIFICATION_STATE_INVALID,
                  "Modification in %s cannot be recorded" % mod["status"])

    loan = loan_of_modification(mod)
    app = store.applications[mod["application_id"]]
    now = clock.now()

    # snapshot pre-record terms for rescission restore
    mod["prior_terms_snapshot"] = {
        "upb_cents": loan["unpaid_principal_balance_cents"],
        "rate_bp": loan["interest_rate_bp"],
        "term_months": loan["remaining_term_months"],
        "arrears_cents": loan["arrears_cents"],
    }
    mod["recorded_at"] = now
    mod["rescission_deadline"] = now + timedelta(days=RESCISSION_WINDOW_DAYS)
    mod["status"] = "RECORDED"
    bump(mod)

    # L1 - loan terms rewritten
    loan["unpaid_principal_balance_cents"] = mod["final_base_cents"] - mod["final_forbearance_cents"]
    loan["deferred_principal_cents"] = mod["final_forbearance_cents"]
    loan["interest_rate_bp"] = mod["final_rate_bp"]
    loan["remaining_term_months"] = mod["final_term_months"]
    loan["arrears_cents"] = 0
    loan["workout_status"] = "PERMANENTLY_MODIFIED"
    bump(loan)

    # L2 - application approved (caused by workout reaching PERMANENTLY_MODIFIED)
    if app["status"] == "TRIAL_PASSED":
        app["status"] = "APPROVED"
        bump(app)

    # L3 - auto-created POST_MODIFICATION escrow analysis (DRAFT)
    create_escrow_analysis(
        loan,
        "POST_MODIFICATION",
        "%04d-%02d" % (now.year, now.month),
        13 - now.month,
        loan["escrow_monthly_cents"] * 12,
        modification_id=mod["id"],
    )
    return success_object(modification_out(mod))


@bp.route("/modifications/<rid>/rescind", methods=["POST"])
def rescind_modification(rid):
    _, role = authenticate()
    authorize(role, ["ServicingOps"])
    mod = get_or_404(store.modifications, rid, ERR_MODIFICATION_NOT_FOUND, "PermanentModification")
    if mod["status"] != "RECORDED":
        raise_err(ERR_MODIFICATION_STATE_INVALID,
                  "Modification in %s cannot be rescinded" % mod["status"])
    if clock.now() > mod["rescission_deadline"]:
        raise_err(ERR_RESCISSION_WINDOW_EXPIRED,
                  "Rescission window expired at %s" % mod["rescission_deadline"])

    loan = loan_of_modification(mod)
    app = store.applications[mod["application_id"]]

    snap = mod["prior_terms_snapshot"] or {}
    loan["unpaid_principal_balance_cents"] = snap.get("upb_cents", loan["unpaid_principal_balance_cents"])
    loan["interest_rate_bp"] = snap.get("rate_bp", loan["interest_rate_bp"])
    loan["remaining_term_months"] = snap.get("term_months", loan["remaining_term_months"])
    loan["arrears_cents"] = snap.get("arrears_cents", loan["arrears_cents"])
    loan["deferred_principal_cents"] = 0
    loan["workout_status"] = "MOD_PENDING"
    bump(loan)

    mod["status"] = "RESCINDED"
    bump(mod)

    if app["status"] == "APPROVED":
        app["status"] = "TRIAL_PASSED"
        bump(app)

    # cancel the auto-created escrow analysis if still DRAFT
    for a in store.analyses.values():
        if a.get("modification_id") == mod["id"] and a["status"] == "DRAFT":
            a["status"] = "CANCELLED"
            bump(a)
    return success_object(modification_out(mod))
