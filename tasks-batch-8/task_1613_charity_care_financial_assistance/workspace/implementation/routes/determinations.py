"""Discount determinations: create (OCC), finalize (segregation of duties),
reverse (cascades) — PRD 3.8."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_APPLICATION_NOT_FOUND, ERR_APPLICATION_NOT_UNDER_REVIEW,
    ERR_DETERMINATION_NOT_FOUND, ERR_DETERMINATION_NOT_PRELIMINARY,
    ERR_DETERMINATION_NOT_FINAL, ERR_ACCOUNT_NOT_FOUND,
    ERR_ACCOUNT_PATIENT_MISMATCH, ERR_VERIFIED_DOCS_REQUIRED,
    ERR_PRESCREEN_BELOW_THRESHOLD, ERR_NO_COLLECTIBLE_BALANCE,
    ERR_SEGREGATION_OF_DUTIES, ERR_STALE_VERSION,
)
from middleware import authorized, check_ownership
from response import success_object
from routes.helpers import list_envelope, require
from services.core import (
    adjusted_balance_cents, amount_outstanding_cents, assign_tier_presumptive,
    assign_tier_verified, create_notice, documents_of, get_screening,
    new_record, public, release_holds_for_patient, touch,
    INCOME_DOC_TYPES,
)
from util import CLOCK, parse_dt
from validate import get_body, req_enum, req_int, req_str

bp = Blueprint("determinations", __name__)

DET_READ = ["Patient", "FinancialCounselor", "AssistanceReviewer",
            "BillingAdministrator", "ComplianceOfficer"]
STAFF_READ = ["FinancialCounselor", "AssistanceReviewer", "BillingAdministrator",
              "ComplianceOfficer"]
BASES = {"VERIFIED_APPLICATION", "PRESUMPTIVE_SCORE"}


def _det_patient_id(det):
    app = db["applications"].get(det["application_id"])
    return app["patient_id"] if app else None


@bp.post("/charity-care/determinations")
def create_determination():
    authorized(["AssistanceReviewer"])
    body = get_body()
    application_id = req_str(body, "application_id")
    app = db["applications"].get(application_id)
    if app is None:
        raise_error(ERR_APPLICATION_NOT_FOUND, "application id does not exist")
    if app["status"] != "UNDER_REVIEW":
        raise_error(ERR_APPLICATION_NOT_UNDER_REVIEW,
                    "determination creation requires an UNDER_REVIEW application")
    # OCC (PRD 2.11): stale application view rejected
    expected = req_int(body, "expected_application_version")
    if expected != app["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_application_version does not match current application version")
    basis = req_enum(body, "basis", BASES)
    covered = body.get("covered_account_ids")
    if not isinstance(covered, list) or any(not isinstance(x, str) for x in covered):
        from errors import ERR_INVALID_REQUEST
        raise_error(ERR_INVALID_REQUEST, "covered_account_ids must be a list of strings")
    accounts = []
    for aid in covered:
        acct = db["accounts"].get(aid)
        if acct is None:
            raise_error(ERR_ACCOUNT_NOT_FOUND, f"account {aid} does not exist")
        accounts.append(acct)
    # Priority 20: every covered account belongs to the application's patient
    for acct in accounts:
        if acct["patient_id"] != app["patient_id"]:
            raise_error(ERR_ACCOUNT_PATIENT_MISMATCH,
                        "covered account belongs to a different patient")
    # Priorities 21-22: basis-specific evidence gates
    docs = documents_of(application_id)
    if basis == "VERIFIED_APPLICATION":
        has_income = any(d["status"] == "VERIFIED" and d["doc_type"] in INCOME_DOC_TYPES
                         for d in docs)
        has_identity = any(d["status"] == "VERIFIED" and d["doc_type"] == "IDENTITY"
                           for d in docs)
        if not (has_income and has_identity):
            raise_error(ERR_VERIFIED_DOCS_REQUIRED,
                        "VERIFIED_APPLICATION requires VERIFIED income and IDENTITY documents")
    else:
        screening = get_screening(application_id)
        if screening is None or screening["outcome"] == "NOT_ELIGIBLE":
            raise_error(ERR_PRESCREEN_BELOW_THRESHOLD,
                        "PRESUMPTIVE_SCORE requires a screening with an eligible outcome")
    # Priority 27: at least one covered account has a collectible balance
    if not any(adjusted_balance_cents(a) > 0 for a in accounts):
        raise_error(ERR_NO_COLLECTIBLE_BALANCE,
                    "no covered account has a collectible balance")
    # Tier assignment is computed once and frozen on the PRELIMINARY record
    policy = db["policies"].get(app["policy_id"])
    if basis == "VERIFIED_APPLICATION":
        fpl_pct, tier, discount = assign_tier_verified(app, policy)
        snapshot = float(fpl_pct)
    else:
        _, tier, discount = assign_tier_presumptive(get_screening(application_id))
        snapshot = None
    rec = new_record("determinations", {
        "application_id": application_id,
        "basis": basis,
        "covered_account_ids": list(covered),
        "policy_id": app["policy_id"],
        "policy_version": app["policy_version"],
        "fpl_pct_snapshot": snapshot,
        "tier": tier,
        "discount_pct": float(discount),
        "decided_by_user_id": None,
        "finalized_at": None,
        "status": "PRELIMINARY",
    })
    touch(app)
    return success_object(public(rec), status=201)


@bp.get("/charity-care/determinations")
def list_determinations():
    caller = authorized(DET_READ)
    items = list(db["determinations"].values())
    if caller.role == "Patient":
        items = [d for d in items if _det_patient_id(d) == caller.user_id]
    application_id = request.args.get("application_id")
    policy_id = request.args.get("policy_id")
    status = request.args.get("status")
    if application_id is not None:
        items = [d for d in items if d["application_id"] == application_id]
    if policy_id is not None:
        items = [d for d in items if d.get("policy_id") == policy_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return list_envelope(items, view=public)


@bp.get("/charity-care/determinations/<did>")
def get_determination(did):
    caller = authorized(DET_READ)
    det = require("determinations", did, ERR_DETERMINATION_NOT_FOUND)
    check_ownership(caller, _det_patient_id(det))
    return success_object(public(det))


@bp.post("/charity-care/determinations/<did>/finalize")
def finalize_determination(did):
    caller = authorized(["AssistanceReviewer"])
    det = require("determinations", did, ERR_DETERMINATION_NOT_FOUND)
    if det["status"] != "PRELIMINARY":
        raise_error(ERR_DETERMINATION_NOT_PRELIMINARY, "finalize requires PRELIMINARY")
    app = db["applications"].get(det["application_id"])
    if app is None or app["status"] != "UNDER_REVIEW":
        raise_error(ERR_APPLICATION_NOT_UNDER_REVIEW,
                    "finalize requires the application to be UNDER_REVIEW")
    # Segregation of duties (PRD 2.8): finalizer must not have touched the evidence
    for d in documents_of(det["application_id"]):
        if d["status"] == "VERIFIED" and d["verified_by_user_id"] == caller.user_id:
            raise_error(ERR_SEGREGATION_OF_DUTIES,
                        "finalizer verified a document on this application")
    screening = get_screening(det["application_id"])
    if screening is not None and screening["screened_by_user_id"] == caller.user_id:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "finalizer ran the presumptive screening on this application")
    det["status"] = "FINAL"
    det["decided_by_user_id"] = caller.user_id
    det["finalized_at"] = CLOCK.now_iso()
    create_notice(account_id=None, application_id=app["id"],
                  notice_type="DETERMINATION_LETTER", is_plain_language=True)
    if det["tier"] != "INELIGIBLE":
        app["status"] = "APPROVED"  # accounts stay in ASSISTANCE_HOLD until write-off
    else:
        app["status"] = "DENIED"
        release_holds_for_patient(app["patient_id"])
    touch(det)
    touch(app)
    return success_object(public(det))


@bp.post("/charity-care/determinations/<did>/reverse")
def reverse_determination(did):
    authorized(["AssistanceReviewer", "ComplianceOfficer"])
    det = require("determinations", did, ERR_DETERMINATION_NOT_FOUND)
    if det["status"] != "FINAL":
        raise_error(ERR_DETERMINATION_NOT_FINAL, "reverse requires a FINAL determination")
    det["status"] = "REVERSED"
    # Cascade link 1: POSTED write-offs reverse; refunds stay POSTED
    affected_account_ids = set()
    for adj in db["adjustments"].values():
        if (adj["determination_id"] == did and adj["adjustment_type"] == "WRITE_OFF"
                and adj["status"] == "POSTED"):
            adj["status"] = "REVERSED"
            adj["reversed_at"] = CLOCK.now_iso()
            touch(adj)
            affected_account_ids.add(adj["account_id"])
    # Cascade link 2: accounts recompute; RESOLVED with restored balance -> NOTICE_PERIOD
    for aid in affected_account_ids:
        acct = db["accounts"].get(aid)
        if acct is None:
            continue
        if (acct["collection_posture"] == "RESOLVED"
                and amount_outstanding_cents(acct) > 0):
            acct["collection_posture"] = "NOTICE_PERIOD"
        touch(acct)
    # Revision loop: APPROVED -> UNDER_REVIEW
    app = db["applications"].get(det["application_id"])
    if app is not None and app["status"] == "APPROVED":
        app["status"] = "UNDER_REVIEW"
    # Cascade link 3: a FILED report of the finalized year reopens, totals stale
    if det.get("finalized_at"):
        year = parse_dt(det["finalized_at"]).year
        for report in db["reports"].values():
            if report["reporting_year"] == year:
                if report["status"] == "FILED":
                    report["status"] = "REOPENED"
                report["totals_stale"] = True
                touch(report)
    touch(det)
    if app is not None:
        touch(app)
    return success_object(public(det))


@bp.get("/charity-care/determinations/<did>/adjustments")
def list_determination_adjustments(did):
    authorized(STAFF_READ)
    require("determinations", did, ERR_DETERMINATION_NOT_FOUND)
    items = [a for a in db["adjustments"].values() if a["determination_id"] == did]
    return list_envelope(items, view=public)
