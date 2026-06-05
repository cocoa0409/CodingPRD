"""PatientStatement, Payment, WriteOff (PRD 3.10, 3.11)."""
from flask import Blueprint

import calculations
import clock
import db
import errors
import listing
import response
import services
import timeutil
import validate
from middleware import authenticate, require_role

bp = Blueprint("statements", __name__)

PAYMENT_METHODS = {"CARD", "CASH", "CHECK", "EFT"}
WRITEOFF_REASONS = {"BAD_DEBT", "CHARITY", "SMALL_BALANCE"}


@bp.route("/encounters/<eid>/patient-statements", methods=["GET"])
def list_encounter_statements(eid):
    authenticate()
    if eid not in db.encounters:
        raise errors.not_found()
    recs = [s for s in db.patient_statements.values() if s["encounter_id"] == eid]
    page, limit, offset, total = listing.paginate(recs)
    return response.array_response(page, limit, offset, total, 200)


@bp.route("/patient-statements/<sid>", methods=["GET"])
def get_statement(sid):
    authenticate()
    rec = db.patient_statements.get(sid)
    if rec is None:
        raise errors.not_found()
    return response.object_response(rec, 200)


# --------------------------------------------------------------------------
# Payments
# --------------------------------------------------------------------------
@bp.route("/patient-statements/<sid>/payments", methods=["POST"])
def post_payment(sid):
    _, role = authenticate()
    require_role(role, {"BillingSpecialist"})
    stmt = db.patient_statements.get(sid)
    if stmt is None:
        raise errors.not_found()
    body = validate.get_body()

    amount = validate.require_int(body, "amount_cents")
    if amount < 1:
        raise errors.invalid_request("amount_cents must be an integer >= 1.")
    method = validate.require_enum(body, "method", PAYMENT_METHODS)

    # state gate: payments defined from ISSUED or PARTIALLY_PAID
    if stmt["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise errors.invalid_state("Payments are only defined from ISSUED or PARTIALLY_PAID status.")

    # business fiscal: payment may not exceed outstanding balance
    outstanding = stmt["amount_due_cents"] - stmt["amount_paid_cents"]
    if amount > outstanding:
        raise errors.overpayment("The payment exceeds the statement's outstanding balance.")

    payment = db.base_record(common_fields=False)  # immutable ledger entry
    payment.update({
        "statement_id": sid,
        "amount_cents": amount,
        "method": method,
        "posted_at": clock.now_iso(),
    })
    db.payments[payment["id"]] = payment

    stmt["amount_paid_cents"] += amount
    new_outstanding = stmt["amount_due_cents"] - stmt["amount_paid_cents"]

    enc = db.encounters.get(stmt["encounter_id"])

    if new_outstanding <= 0:
        stmt["status"] = "PAID"
    else:
        stmt["status"] = "PARTIALLY_PAID"
    db.touch(stmt)

    if enc is not None:
        services.recompute_account_balance(enc)
        db.touch(enc)
        # bubble up: encounter BILLED -> CLOSED when the statement reaches PAID
        if stmt["status"] == "PAID" and enc["status"] == "BILLED":
            enc["status"] = "CLOSED"
            db.touch(enc)

    return response.object_response(payment, 201)


@bp.route("/patient-statements/<sid>/payments", methods=["GET"])
def list_payments(sid):
    authenticate()
    if sid not in db.patient_statements:
        raise errors.not_found()
    recs = [p for p in db.payments.values() if p["statement_id"] == sid]
    page, limit, offset, total = listing.paginate(recs)
    return response.array_response(page, limit, offset, total, 200)


# --------------------------------------------------------------------------
# Send to collections
# --------------------------------------------------------------------------
@bp.route("/patient-statements/<sid>/send-to-collections", methods=["POST"])
def send_to_collections(sid):
    _, role = authenticate()
    require_role(role, {"BillingSpecialist"})
    stmt = db.patient_statements.get(sid)
    if stmt is None:
        raise errors.not_found()
    if stmt["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise errors.invalid_state("Send-to-collections is only defined from ISSUED or PARTIALLY_PAID status.")
    # business temporal: aging >= 120 days since issued_at
    elapsed = timeutil.days_between(clock.now(), timeutil.parse_iso(stmt["issued_at"]))
    if elapsed < calculations.BAD_DEBT_AGING_DAYS:
        raise errors.aging_not_met("The statement has not aged 120 days since issue.")
    stmt["status"] = "IN_COLLECTIONS"
    db.touch(stmt)
    return response.object_response(stmt, 200)


# --------------------------------------------------------------------------
# Write-off
# --------------------------------------------------------------------------
@bp.route("/patient-statements/<sid>/write-off", methods=["POST"])
def write_off(sid):
    user_id, role = authenticate()
    require_role(role, {"FinanceManager"})
    stmt = db.patient_statements.get(sid)
    if stmt is None:
        raise errors.not_found()
    body = validate.get_body()

    reason = validate.require_enum(body, "reason", WRITEOFF_REASONS)
    if "expected_patient_statement_version" not in body:
        raise errors.invalid_request("expected_patient_statement_version is required.")
    expected_version = body["expected_patient_statement_version"]
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise errors.invalid_request("expected_patient_statement_version must be an integer.")

    # state gate: only IN_COLLECTIONS may be written off
    if stmt["status"] != "IN_COLLECTIONS":
        raise errors.invalid_state("Write-off is only defined from IN_COLLECTIONS status.")

    enc = db.encounters.get(stmt["encounter_id"])

    # business safety: segregation of duties (priority 9, before fiscal OCC).
    # The approver's X-User-ID must not equal the coder who finalized the
    # encounter's coding assignment.
    finalized_by = _coding_finalizer(stmt["encounter_id"])
    if finalized_by is not None and finalized_by == user_id:
        raise errors.segregation_of_duties()

    # business fiscal: OCC against the statement version
    if expected_version != stmt["version"]:
        raise errors.stale_statement_version()

    amount = stmt["amount_due_cents"] - stmt["amount_paid_cents"]
    wo = db.base_record(common_fields=False)  # immutable ledger entry
    wo.update({
        "statement_id": sid,
        "amount_cents": amount,
        "reason": reason,
        "approved_by_user_id": user_id,
        "approved_at": clock.now_iso(),
    })
    db.write_offs[wo["id"]] = wo

    stmt["written_off_cents"] = amount
    stmt["status"] = "WRITTEN_OFF"
    db.touch(stmt)

    if enc is not None:
        enc["account_balance_cents"] = 0
        db.touch(enc)
        if enc["status"] == "BILLED":
            enc["status"] = "CLOSED"
            db.touch(enc)

    return response.object_response(wo, 201)


def _coding_finalizer(encounter_id):
    """Return the finalized_by_user_id recorded on the encounter's coding
    assignment, or None if no assignment has been finalized."""
    matches = [c for c in db.coding_assignments.values() if c["encounter_id"] == encounter_id]
    if not matches:
        return None
    coding = max(matches, key=lambda c: c["_seq"])
    return coding.get("finalized_by_user_id")


@bp.route("/patient-statements/<sid>/write-offs", methods=["GET"])
def list_write_offs(sid):
    authenticate()
    if sid not in db.patient_statements:
        raise errors.not_found()
    recs = [w for w in db.write_offs.values() if w["statement_id"] == sid]
    page, limit, offset, total = listing.paginate(recs)
    return response.array_response(page, limit, offset, total, 200)
