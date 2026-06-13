"""CopayPayment routes (PRD §2.7, §3.10)."""
from flask import Blueprint, request

import db
import serialize
from errors import (
    err,
    ERR_STALE_SESSION_VERSION,
    ERR_COPAY_NOT_DUE,
    ERR_COPAY_AMOUNT_MISMATCH,
    ERR_PAYMENT_NOT_AUTHORIZED,
    ERR_PAYMENT_NOT_CAPTURED,
)
from middleware import require_roles
from response import success, success_list
from services.common import touch, require_string, require_int
from services.lookups import get_session, get_payment
from services.pagination import paginate
from services import sessions as S

bp = Blueprint("copay", __name__)


@bp.route("/copay-payments", methods=["POST"])
@require_roles("BillingClerk")
def authorize_copay():
    body = request.get_json(silent=True) or {}
    intake_session_id = require_string(body, "intake_session_id")
    amount_cents = require_int(body, "amount_cents")
    expected_version = require_int(body, "expected_intake_session_version")
    session = get_session(intake_session_id)

    with db.LOCK:
        # OCC check runs first, before any business validation (PRD §2.7).
        if expected_version != session["version"]:
            raise err(ERR_STALE_SESSION_VERSION, "stale session version")
        # financial dimension must be COPAY_DUE (PRD §3.10).
        if session["financial_status"] != "COPAY_DUE":
            raise err(ERR_COPAY_NOT_DUE, "financial_status not COPAY_DUE")
        # amount must equal final_patient_responsibility_cents (PRD §3.10).
        if amount_cents != session["final_patient_responsibility_cents"]:
            raise err(ERR_COPAY_AMOUNT_MISMATCH, "amount mismatch")

        now = db.now_iso()
        payment = {
            "id": db.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": db.next_seq(),
            "intake_session_id": intake_session_id,
            "amount_cents": amount_cents,
            "refunded_cents": 0,
            "status": "AUTHORIZED",
        }
        db.copay_payments[payment["id"]] = payment
    return success(serialize.copay_payment(payment), status=201)


@bp.route("/copay-payments/<pid>", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def get_payment_route(pid):
    payment = get_payment(pid)
    return success(serialize.copay_payment(payment), status=200)


@bp.route("/copay-payments", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def list_payments():
    records = list(db.copay_payments.values())
    val = request.args.get("intake_session_id")
    if val is not None:
        records = [r for r in records if r["intake_session_id"] == val]
    items, limit, offset, total = paginate(records, serialize.copay_payment)
    return success_list(items, limit, offset, total)


@bp.route("/copay-payments/<pid>/capture", methods=["POST"])
@require_roles("BillingClerk")
def capture_copay(pid):
    payment = get_payment(pid)
    with db.LOCK:
        if payment["status"] != "AUTHORIZED":
            raise err(ERR_PAYMENT_NOT_AUTHORIZED, "payment not AUTHORIZED")
        session = db.intake_sessions[payment["intake_session_id"]]
        if session["financial_status"] != "COPAY_DUE":
            raise err(ERR_COPAY_NOT_DUE, "financial_status not COPAY_DUE")
        if payment["amount_cents"] != session["final_patient_responsibility_cents"]:
            raise err(ERR_COPAY_AMOUNT_MISMATCH, "amount mismatch")
        payment["status"] = "CAPTURED"
        touch(payment)
        # Ledger credit (PRD §2.9, §3.10).
        clinic = db.clinics[session["clinic_id"]]
        clinic["collected_copay_cents"] += payment["amount_cents"]
        touch(clinic)
        # Cascade: session financial_status -> COPAY_SETTLED.
        S.set_financial(session, "COPAY_SETTLED")
        S.bubble_up(session)
    return success(serialize.copay_payment(payment), status=200)


@bp.route("/copay-payments/<pid>/void", methods=["POST"])
@require_roles("BillingClerk")
def void_copay(pid):
    payment = get_payment(pid)
    with db.LOCK:
        if payment["status"] != "AUTHORIZED":
            raise err(ERR_PAYMENT_NOT_AUTHORIZED, "payment not AUTHORIZED")
        payment["status"] = "VOIDED"
        touch(payment)
    return success(serialize.copay_payment(payment), status=200)


@bp.route("/copay-payments/<pid>/refund", methods=["POST"])
@require_roles("BillingClerk")
def refund_copay(pid):
    payment = get_payment(pid)
    with db.LOCK:
        if payment["status"] != "CAPTURED":
            raise err(ERR_PAYMENT_NOT_CAPTURED, "payment not CAPTURED")
        payment["status"] = "REFUNDED"
        payment["refunded_cents"] = payment["amount_cents"]
        touch(payment)
        # Ledger debit / compensation (PRD §2.9, §3.10).
        session = db.intake_sessions[payment["intake_session_id"]]
        clinic = db.clinics[session["clinic_id"]]
        clinic["collected_copay_cents"] -= payment["amount_cents"]
        touch(clinic)
        # Cascade: session financial_status COPAY_SETTLED -> COPAY_DUE.
        S.set_financial(session, "COPAY_DUE")
        # Losing settled status may revert readiness (financial gate no longer met).
        S.bubble_up(session)
    return success(serialize.copay_payment(payment), status=200)
