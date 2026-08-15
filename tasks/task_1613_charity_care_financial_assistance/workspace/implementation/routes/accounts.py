"""Accounts, statements, payments, adjustments, notices, ECAs, posture (PRD 3.2, 3.9-3.11)."""
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_PATIENT_NOT_FOUND, ERR_ACCOUNT_NOT_FOUND,
    ERR_DETERMINATION_NOT_FOUND, ERR_DETERMINATION_NOT_FINAL,
    ERR_ACCOUNT_NOT_COVERED, ERR_DUPLICATE_ADJUSTMENT, ERR_NO_COLLECTIBLE_BALANCE,
    ERR_INSURANCE_EXCEEDS_CHARGES, ERR_NONPOSITIVE_AMOUNT, ERR_ACCOUNT_RESOLVED,
    ERR_FIRST_STATEMENT_ALREADY_ISSUED, ERR_ACCOUNT_NOT_ECA_ELIGIBLE,
    ERR_ASSISTANCE_HOLD_ACTIVE, ERR_ECA_NOTIFICATION_WINDOW_UNMET,
    ERR_POSTURE_NOT_EVALUABLE, ERR_STALE_VERSION, ERR_INVALID_REQUEST,
)
from middleware import authorized, check_ownership
from response import success_object
from routes.helpers import list_envelope, require
from services.core import (
    account_view, adjusted_balance_cents, amount_outstanding_cents, create_notice,
    eca_window_met, halt_initiated_actions, new_record, open_application_for_patient,
    overpayment_cents, payments_of, public, resolve_account_if_zero, touch,
)
from util import CLOCK, parse_dt, round_half_up, to_decimal
from validate import get_body, req_date, req_datetime, req_enum, req_int, req_str, opt_enum

bp = Blueprint("accounts", __name__)

ALL_READ = ["Patient", "FinancialCounselor", "AssistanceReviewer",
            "BillingAdministrator", "CollectionsAgent", "ComplianceOfficer"]
STAFF_READ = ["FinancialCounselor", "AssistanceReviewer", "BillingAdministrator",
              "CollectionsAgent", "ComplianceOfficer"]
PAYMENT_METHODS = {"CARD", "CHECK", "ACH", "CASH"}
STAFF_NOTICE_TYPES = {"PLAIN_LANGUAGE_SUMMARY", "ECA_WARNING"}
DELIVERY_CHANNELS = {"MAIL", "PORTAL", "EMAIL"}
ECA_TYPES = {"CREDIT_REPORT", "LAWSUIT", "WAGE_GARNISHMENT", "LIEN", "SALE_TO_AGENCY"}


# ---------------------------------------------------------------------------
# Account CRUD
# ---------------------------------------------------------------------------

@bp.post("/charity-care/accounts")
def create_account():
    authorized(["BillingAdministrator"])
    body = get_body()
    patient_id = req_str(body, "patient_id")
    require("patients", patient_id, ERR_PATIENT_NOT_FOUND)
    encounter_date = req_date(body, "encounter_date")
    total = req_int(body, "total_charges_cents")
    insurance = req_int(body, "insurance_paid_cents")
    # Priority 25: fiscal guard (insurance <= charges, both >= 0)
    if total < 0 or insurance < 0 or insurance > total:
        raise_error(ERR_INSURANCE_EXCEEDS_CHARGES,
                    "insurance_paid_cents must be >= 0 and <= total_charges_cents")
    if total == 0:
        raise_error(ERR_INVALID_REQUEST, "total_charges_cents must be > 0")
    responsibility = total - insurance
    posture = "RESOLVED" if responsibility == 0 else "NOT_IN_COLLECTIONS"
    rec = new_record("accounts", {
        "patient_id": patient_id,
        "encounter_date": encounter_date,
        "total_charges_cents": total,
        "insurance_paid_cents": insurance,
        "patient_responsibility_cents": responsibility,
        "first_statement_at": None,
        "collection_posture": posture,
    })
    return success_object(account_view(rec), status=201)


@bp.get("/charity-care/accounts/<aid>")
def get_account(aid):
    caller = authorized(ALL_READ)
    acct = require("accounts", aid, ERR_ACCOUNT_NOT_FOUND)
    check_ownership(caller, acct["patient_id"])
    return success_object(account_view(acct))


# ---------------------------------------------------------------------------
# First statement (PRD 3.2)
# ---------------------------------------------------------------------------

@bp.post("/charity-care/accounts/<aid>/statements")
def issue_first_statement(aid):
    authorized(["BillingAdministrator"])
    acct = require("accounts", aid, ERR_ACCOUNT_NOT_FOUND)
    if acct["first_statement_at"] is not None:
        raise_error(ERR_FIRST_STATEMENT_ALREADY_ISSUED, "first statement already issued")
    acct["first_statement_at"] = CLOCK.now_iso()
    if acct["collection_posture"] == "NOT_IN_COLLECTIONS":
        acct["collection_posture"] = "NOTICE_PERIOD"
    notice = create_notice(account_id=aid, application_id=None,
                           notice_type="FIRST_STATEMENT", is_plain_language=True)
    touch(acct)
    return success_object(public(notice), status=201)


# ---------------------------------------------------------------------------
# Payments (PRD 3.9)
# ---------------------------------------------------------------------------

@bp.post("/charity-care/accounts/<aid>/payments")
def post_payment(aid):
    caller = authorized(["BillingAdministrator", "Patient"])
    acct = require("accounts", aid, ERR_ACCOUNT_NOT_FOUND)
    check_ownership(caller, acct["patient_id"])
    body = get_body()
    amount = req_int(body, "amount_cents")
    paid_at = req_datetime(body, "paid_at")
    method = req_enum(body, "method", PAYMENT_METHODS)
    # Priority 26: non-positive amount first, then the RESOLVED fiscal-state guard
    if amount <= 0:
        raise_error(ERR_NONPOSITIVE_AMOUNT, "payment amount_cents must be > 0")
    if acct["collection_posture"] == "RESOLVED":
        raise_error(ERR_ACCOUNT_RESOLVED, "payments are not accepted on a RESOLVED account")
    pmt = new_record("payments", {
        "account_id": aid,
        "amount_cents": amount,
        "paid_at": paid_at,
        "method": method,
        "refunded_cents": 0,
        "status": "POSTED",
    })
    resolve_account_if_zero(acct)
    touch(acct)
    return success_object(public(pmt), status=201)


@bp.get("/charity-care/accounts/<aid>/payments")
def list_payments(aid):
    caller = authorized(ALL_READ)
    acct = require("accounts", aid, ERR_ACCOUNT_NOT_FOUND)
    check_ownership(caller, acct["patient_id"])
    return list_envelope(payments_of(aid), view=public)


# ---------------------------------------------------------------------------
# Adjustments: write-off leg + retroactive refund waterfall (PRD 3.10)
# ---------------------------------------------------------------------------

@bp.post("/charity-care/accounts/<aid>/adjustments")
def post_adjustment(aid):
    authorized(["BillingAdministrator"])
    acct = require("accounts", aid, ERR_ACCOUNT_NOT_FOUND)
    body = get_body()
    determination_id = req_str(body, "determination_id")
    expected_version = req_int(body, "expected_account_version")
    # OCC (PRD 2.11): stale account view rejected before posting
    if expected_version != acct["version"]:
        raise_error(ERR_STALE_VERSION, "expected_account_version does not match current account version")
    # Priority 23: determination exists / FINAL / covers this account
    det = db["determinations"].get(determination_id)
    if det is None:
        raise_error(ERR_DETERMINATION_NOT_FOUND, "determination id does not exist")
    if det["status"] != "FINAL":
        raise_error(ERR_DETERMINATION_NOT_FINAL, "determination must be FINAL")
    if aid not in det["covered_account_ids"]:
        raise_error(ERR_ACCOUNT_NOT_COVERED, "account not covered by this determination")
    # Priority 24: no other POSTED WRITE_OFF for (account, determination)
    for a in db["adjustments"].values():
        if (a["account_id"] == aid and a["determination_id"] == determination_id
                and a["adjustment_type"] == "WRITE_OFF" and a["status"] == "POSTED"):
            raise_error(ERR_DUPLICATE_ADJUSTMENT,
                        "a POSTED write-off already exists for this account and determination")
    # Priority 27: collectible balance
    if adjusted_balance_cents(acct) <= 0:
        raise_error(ERR_NO_COLLECTIBLE_BALANCE, "account has no collectible balance")

    # WRITE_OFF leg — round per account first (calc: account_adjustment_computation)
    discount = to_decimal(det["discount_pct"])
    amount = int(round_half_up(
        Decimal(acct["patient_responsibility_cents"]) * discount / Decimal(100), 0))
    write_off = new_record("adjustments", {
        "account_id": aid,
        "determination_id": determination_id,
        "adjustment_type": "WRITE_OFF",
        "amount_cents": amount,
        "payment_id": None,
        "reversed_at": None,
        "status": "POSTED",
    })

    # REFUND leg — retroactive window against the pinned policy (PRD 3.10)
    app = db["applications"].get(det["application_id"])
    policy = db["policies"].get(app["policy_id"]) if app else None
    retro_days = policy["retroactive_window_days"] if policy else 0
    if acct["first_statement_at"] is None:
        eligible = True
    else:
        window_end = parse_dt(acct["first_statement_at"]) + timedelta(days=retro_days)
        eligible = app is not None and parse_dt(app["submitted_at"]) <= window_end
    if eligible:
        remaining = overpayment_cents(acct)
        payments = sorted(
            payments_of(aid),
            key=lambda p: (-parse_dt(p["paid_at"]).timestamp(), p["created_at"], p["id"]),
        )
        for p in payments:
            if remaining <= 0:
                break
            room = p["amount_cents"] - p["refunded_cents"]
            if room <= 0:
                continue
            grant = min(room, remaining)
            p["refunded_cents"] += grant
            p["status"] = ("FULLY_REFUNDED" if p["refunded_cents"] == p["amount_cents"]
                           else "PARTIALLY_REFUNDED")
            touch(p)
            new_record("adjustments", {
                "account_id": aid,
                "determination_id": determination_id,
                "adjustment_type": "REFUND",
                "amount_cents": grant,
                "payment_id": p["id"],
                "reversed_at": None,
                "status": "POSTED",
            })
            remaining -= grant

    # Posture resolution (PRD 3.10)
    if not resolve_account_if_zero(acct):
        if acct["collection_posture"] == "ASSISTANCE_HOLD":
            acct["collection_posture"] = "NOTICE_PERIOD"
    touch(acct)
    return success_object(public(write_off), status=201)


@bp.get("/charity-care/accounts/<aid>/adjustments")
def list_account_adjustments(aid):
    caller = authorized(ALL_READ)
    acct = require("accounts", aid, ERR_ACCOUNT_NOT_FOUND)
    check_ownership(caller, acct["patient_id"])
    items = [a for a in db["adjustments"].values() if a["account_id"] == aid]
    return list_envelope(items, view=public)


# ---------------------------------------------------------------------------
# Staff-issued notices (PRD 3.2)
# ---------------------------------------------------------------------------

@bp.post("/charity-care/accounts/<aid>/notices")
def issue_notice(aid):
    authorized(["BillingAdministrator"])
    require("accounts", aid, ERR_ACCOUNT_NOT_FOUND)
    body = get_body()
    notice_type = req_enum(body, "notice_type", STAFF_NOTICE_TYPES)
    channel = opt_enum(body, "delivery_channel", DELIVERY_CHANNELS, default="MAIL")
    notice = create_notice(account_id=aid, application_id=None,
                           notice_type=notice_type, delivery_channel=channel,
                           is_plain_language=True)
    return success_object(public(notice), status=201)


@bp.get("/charity-care/accounts/<aid>/notices")
def list_notices(aid):
    caller = authorized(ALL_READ)
    acct = require("accounts", aid, ERR_ACCOUNT_NOT_FOUND)
    check_ownership(caller, acct["patient_id"])
    items = [n for n in db["notices"].values() if n.get("account_id") == aid]
    return list_envelope(items, view=public)


# ---------------------------------------------------------------------------
# Extraordinary collection actions (PRD 3.11)
# ---------------------------------------------------------------------------

@bp.post("/charity-care/accounts/<aid>/collection-actions")
def initiate_collection_action(aid):
    caller = authorized(["CollectionsAgent"])
    acct = require("accounts", aid, ERR_ACCOUNT_NOT_FOUND)
    if acct["collection_posture"] != "ECA_ELIGIBLE":
        raise_error(ERR_ACCOUNT_NOT_ECA_ELIGIBLE,
                    "collection actions require posture ECA_ELIGIBLE")
    if open_application_for_patient(acct["patient_id"]) is not None:
        raise_error(ERR_ASSISTANCE_HOLD_ACTIVE,
                    "an open assistance application freezes collection actions")
    if not eca_window_met(acct):
        raise_error(ERR_ECA_NOTIFICATION_WINDOW_UNMET, "501(r) clearance window not met")
    body = get_body()
    action_type = req_enum(body, "action_type", ECA_TYPES)
    if amount_outstanding_cents(acct) <= 0:
        raise_error(ERR_NO_COLLECTIBLE_BALANCE, "account has no outstanding balance")
    action = new_record("collection_actions", {
        "account_id": aid,
        "action_type": action_type,
        "initiated_at": CLOCK.now_iso(),
        "initiated_by_user_id": caller.user_id,
        "halted_at": None,
        "halt_reason": None,
        "status": "INITIATED",
    })
    acct["collection_posture"] = "ECA_ACTIVE"
    touch(acct)
    return success_object(public(action), status=201)


@bp.get("/charity-care/accounts/<aid>/collection-actions")
def list_collection_actions(aid):
    authorized(STAFF_READ)
    require("accounts", aid, ERR_ACCOUNT_NOT_FOUND)
    items = [c for c in db["collection_actions"].values() if c["account_id"] == aid]
    return list_envelope(items, view=public)


# ---------------------------------------------------------------------------
# Posture evaluation (PRD 3.11, 2.9)
# ---------------------------------------------------------------------------

@bp.post("/charity-care/accounts/<aid>/evaluate-posture")
def evaluate_posture(aid):
    authorized(["CollectionsAgent", "BillingAdministrator", "ComplianceOfficer"])
    acct = require("accounts", aid, ERR_ACCOUNT_NOT_FOUND)
    if acct["collection_posture"] not in ("NOTICE_PERIOD", "ASSISTANCE_HOLD"):
        raise_error(ERR_POSTURE_NOT_EVALUABLE,
                    "evaluate-posture requires NOTICE_PERIOD or ASSISTANCE_HOLD")
    if not eca_window_met(acct):
        raise_error(ERR_ECA_NOTIFICATION_WINDOW_UNMET, "501(r) clearance window not met")
    if open_application_for_patient(acct["patient_id"]) is not None:
        raise_error(ERR_ASSISTANCE_HOLD_ACTIVE,
                    "an open assistance application freezes posture evaluation")
    acct["collection_posture"] = "ECA_ELIGIBLE"
    touch(acct)
    return success_object(account_view(acct))
