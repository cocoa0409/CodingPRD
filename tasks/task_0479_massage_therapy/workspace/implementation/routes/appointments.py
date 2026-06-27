"""Appointment endpoints (PRD §3.4-3.9)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import helpers as h
import response
import util
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_STALE_VERSION, ERR_CONSENT_REQUIRED, ERR_CONTRAINDICATION,
    ERR_INTAKE_INVALID, ERR_LICENSE_EXPIRED, ERR_CERTIFICATION_REQUIRED,
    ERR_TABLE_UNSUITABLE, ERR_TABLE_DOUBLE_BOOKED, ERR_THERAPIST_DOUBLE_BOOKED,
    ERR_NO_CREDITS, ERR_INSUFFICIENT_HSA,
)
from middleware import authenticate, require_role
from routes.therapists import license_status
from services import appointments as svc
from services import packages as pkgsvc

bp = Blueprint("appointments", __name__)

DURATIONS = {30, 60, 90, 120}
PAYERS = {"CASH", "HSA", "MEMBERSHIP"}
CANCEL_REASONS = {"CLIENT_REQUEST", "LATE_CANCEL", "CONSENT_REVOKED", "PRACTICE_CANCEL"}


def serialize(appt):
    return h.public(appt)


# ---------------------------------------------------------------------------
# Booking (PRD §3.4)
# ---------------------------------------------------------------------------

@bp.post("/practice/appointments")
def book():
    caller = authenticate()
    require_role(caller, {"FrontDesk", "PracticeAdmin"})
    body = h.get_body()

    # Existence resolution left-to-right: path (none), then body FKs in order
    # client_id, therapist_id, table_id, modality_id, consent_id (PRD §2.9).
    client_id = h.as_str(h.require(body, "client_id"), "client_id")
    client = h.resolve(db.clients, client_id)
    therapist_id = h.as_str(h.require(body, "therapist_id"), "therapist_id")
    therapist = h.resolve(db.therapists, therapist_id)
    table_id = h.as_str(h.require(body, "table_id"), "table_id")
    table = h.resolve(db.tables, table_id)
    modality_id = h.as_str(h.require(body, "modality_id"), "modality_id")
    modality = h.resolve(db.modalities, modality_id)
    consent_id = h.as_str(h.require(body, "consent_id"), "consent_id")
    consent = h.resolve(db.consent_records, consent_id)

    package_id = h.opt(body, "package_id", None)
    package = None
    if package_id is not None:
        package = h.resolve(db.packages, package_id)

    # Request well-formedness (PRD §2.10)
    start_at = util.parse_iso(h.require(body, "start_at"))
    duration_minutes = h.opt(body, "duration_minutes", 60)
    if duration_minutes not in DURATIONS:
        raise ApiError(*ERR_INVALID_REQUEST, message="duration_minutes invalid")
    payer = h.opt(body, "payer", "CASH")
    h.enum(payer, "payer", PAYERS)
    gratuity_cents = h.opt(body, "gratuity_cents", 0)
    gratuity_cents = h.as_int(gratuity_cents, "gratuity_cents", minimum=0)
    expected_table_version = h.require(body, "expected_table_version")
    expected_table_version = h.as_int(expected_table_version, "expected_table_version")

    # OCC check (ERR_STALE_VERSION) — only the table is the contested resource
    if expected_table_version != table["version"]:
        raise ApiError(*ERR_STALE_VERSION, message="stale table version")

    end_at = start_at + timedelta(minutes=duration_minutes)

    # Domain gates in fixed order (PRD §3.4)
    if not svc.consent_gate(consent, modality):
        raise ApiError(*ERR_CONSENT_REQUIRED, message="consent gate failed")
    if not svc.contraindication_gate(client_id, modality):
        raise ApiError(*ERR_CONTRAINDICATION, message="contraindication")
    if not svc.intake_gate(client_id):
        raise ApiError(*ERR_INTAKE_INVALID, message="intake invalid")
    if not svc.license_gate(therapist):
        raise ApiError(*ERR_LICENSE_EXPIRED, message="license expired")
    if not svc.certification_gate(therapist, modality):
        raise ApiError(*ERR_CERTIFICATION_REQUIRED, message="certification required")
    if not svc.table_suitable(table, modality):
        raise ApiError(*ERR_TABLE_UNSUITABLE, message="table unsuitable")
    if svc.table_overlap(table, start_at, end_at):
        raise ApiError(*ERR_TABLE_DOUBLE_BOOKED, message="table double booked")
    if svc.therapist_overlap(therapist_id, start_at, end_at):
        raise ApiError(*ERR_THERAPIST_DOUBLE_BOOKED, message="therapist double booked")

    appt = h.new_entity({
        "client_id": client_id,
        "therapist_id": therapist_id,
        "table_id": table_id,
        "modality_id": modality_id,
        "consent_id": consent_id,
        "package_id": package_id,
        "start_at": util.iso_format(start_at),
        "end_at": util.iso_format(end_at),
        "duration_minutes": duration_minutes,
        "payer": payer,
        "gratuity_cents": gratuity_cents,
        "scheduling_status": "SCHEDULED",
        "settlement_status": "UNSETTLED",
        "cancel_reason": None,
        "service_charge_cents": 0,
        "client_owed_cents": 0,
        "no_show_fee_cents": 0,
        "commission_credited_cents": 0,
    })
    # internal bookkeeping
    appt["_credit_redeemed"] = False
    appt["_wallet_applied_cents"] = 0
    db.appointments[appt["id"]] = appt

    # Successful booking advances the table's version by 1.
    h.touch(table)
    return response.success(serialize(appt), status=201)


@bp.get("/practice/appointments")
def list_appointments():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Therapist", "Client"})
    limit, offset = h.get_pagination()
    items = list(db.appointments.values())

    for fk in ("client_id", "therapist_id", "table_id", "modality_id", "consent_id", "package_id"):
        val = request.args.get(fk)
        if val is not None:
            items = [a for a in items if a.get(fk) == val]
    sched = request.args.get("scheduling_status")
    if sched is not None:
        items = [a for a in items if a["scheduling_status"] == sched]
    settle = request.args.get("settlement_status")
    if settle is not None:
        items = [a for a in items if a["settlement_status"] == settle]

    # Ownership scoping for entity-backed roles
    if caller.role == "Therapist":
        items = [a for a in items if a["therapist_id"] == caller.user_id]
    elif caller.role == "Client":
        items = [a for a in items if a["client_id"] == caller.user_id]

    page, total = h.paginate(items, limit, offset)
    return response.list_success([serialize(a) for a in page], limit, offset, total)


@bp.get("/practice/appointments/<id>")
def get_appointment(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Therapist", "Client"})
    appt = h.resolve(db.appointments, id)
    if caller.role == "Therapist" and appt["therapist_id"] != caller.user_id:
        raise ApiError(*ERR_NOT_FOUND, message="not found")
    if caller.role == "Client" and appt["client_id"] != caller.user_id:
        raise ApiError(*ERR_NOT_FOUND, message="not found")
    return response.success(serialize(appt))


# ---------------------------------------------------------------------------
# Check-in (PRD §3.5)
# ---------------------------------------------------------------------------

@bp.post("/practice/appointments/<id>/check-in")
def check_in(id):
    caller = authenticate()
    require_role(caller, {"FrontDesk"})
    appt = h.resolve(db.appointments, id)
    if appt["scheduling_status"] != "SCHEDULED":
        raise ApiError(*ERR_INVALID_STATE, message="not SCHEDULED")
    # clock strictly before end_at
    end_at = util.parse_iso(appt["end_at"])
    if not (clock.now() < end_at):
        raise ApiError(*ERR_INVALID_STATE, message="window elapsed")
    # license ACTIVE at check-in
    therapist = db.therapists[appt["therapist_id"]]
    if license_status(therapist) != "ACTIVE":
        raise ApiError(*ERR_LICENSE_EXPIRED, message="license expired")
    # consent still ACTIVE
    consent = db.consent_records[appt["consent_id"]]
    if consent["consent_status"] != "ACTIVE":
        raise ApiError(*ERR_CONSENT_REQUIRED, message="consent not active")

    appt["scheduling_status"] = "CHECKED_IN"
    h.touch(appt)
    return response.success(serialize(appt))


# ---------------------------------------------------------------------------
# Complete (PRD §3.5)
# ---------------------------------------------------------------------------

@bp.post("/practice/appointments/<id>/complete")
def complete(id):
    caller = authenticate()
    require_role(caller, {"Therapist", "FrontDesk"})
    appt = h.resolve(db.appointments, id)
    if caller.role == "Therapist" and appt["therapist_id"] != caller.user_id:
        raise ApiError(*ERR_NOT_FOUND, message="not found")
    if appt["scheduling_status"] != "CHECKED_IN":
        raise ApiError(*ERR_INVALID_STATE, message="not CHECKED_IN")
    # a SOAP note in FINALIZED or AMENDED must exist for this appointment
    has_final = any(
        n["appointment_id"] == appt["id"] and n["note_status"] in ("FINALIZED", "AMENDED")
        for n in db.soap_notes.values()
    )
    if not has_final:
        raise ApiError(*ERR_INVALID_STATE, message="no finalized SOAP note")
    appt["scheduling_status"] = "COMPLETED"
    h.touch(appt)
    return response.success(serialize(appt))


# ---------------------------------------------------------------------------
# Cancel (PRD §3.6)
# ---------------------------------------------------------------------------

@bp.post("/practice/appointments/<id>/cancel")
def cancel(id):
    caller = authenticate()
    require_role(caller, {"FrontDesk", "PracticeAdmin"})
    appt = h.resolve(db.appointments, id)
    body = h.get_body()
    cancel_reason = h.require(body, "cancel_reason")
    h.enum(cancel_reason, "cancel_reason", CANCEL_REASONS)
    if appt["scheduling_status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise ApiError(*ERR_INVALID_STATE, message="not cancellable")

    modality = db.modalities[appt["modality_id"]]
    client = db.clients[appt["client_id"]]
    start_at = util.parse_iso(appt["start_at"])

    appt["scheduling_status"] = "CANCELLED"
    appt["cancel_reason"] = cancel_reason

    # refund redeemed credit
    svc.refund_credit_if_redeemed(appt)

    # Lead-time: late cancel if clock has passed the free-cancellation cutoff.
    # Free cutoff is 24h (1440 min) before start (band >= 1440 => fraction 0).
    lead_seconds = (start_at - clock.now()).total_seconds()
    lead_minutes = lead_seconds / 60.0
    if lead_minutes < 1440:
        # late cancel -> priced via late-cancel proration; strikes read before increment
        fee = svc.compute_fee(modality, appt["duration_minutes"], start_at, client["no_show_strikes"])
        appt["no_show_fee_cents"] = fee
        appt["settlement_status"] = "PRICED"
    else:
        appt["no_show_fee_cents"] = 0

    h.touch(appt)
    return response.success(serialize(appt))


# ---------------------------------------------------------------------------
# No-show (PRD §3.6)
# ---------------------------------------------------------------------------

@bp.post("/practice/appointments/<id>/no-show")
def no_show(id):
    caller = authenticate()
    require_role(caller, {"FrontDesk", "PracticeAdmin"})
    appt = h.resolve(db.appointments, id)
    if appt["scheduling_status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise ApiError(*ERR_INVALID_STATE, message="not markable no-show")
    start_at = util.parse_iso(appt["start_at"])
    if clock.now() < start_at:
        raise ApiError(*ERR_INVALID_STATE, message="before start")

    modality = db.modalities[appt["modality_id"]]
    client = db.clients[appt["client_id"]]

    appt["scheduling_status"] = "NO_SHOW"
    # increment strikes, then use the incremented count
    client["no_show_strikes"] += 1
    fee = svc.compute_fee(modality, appt["duration_minutes"], start_at, client["no_show_strikes"])
    appt["service_charge_cents"] = 0
    appt["no_show_fee_cents"] = fee
    appt["client_owed_cents"] = fee
    appt["settlement_status"] = "PRICED"

    svc.refund_credit_if_redeemed(appt)

    h.touch(appt)
    h.touch(client)
    return response.success(serialize(appt))


# ---------------------------------------------------------------------------
# Waive no-show (PRD §3.6)
# ---------------------------------------------------------------------------

@bp.post("/practice/appointments/<id>/waive-no-show")
def waive_no_show(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin"})
    appt = h.resolve(db.appointments, id)
    if appt["scheduling_status"] != "NO_SHOW":
        raise ApiError(*ERR_INVALID_STATE, message="not NO_SHOW")
    if appt["settlement_status"] == "PAID":
        raise ApiError(*ERR_INVALID_STATE, message="already paid")
    client = db.clients[appt["client_id"]]

    appt["scheduling_status"] = "SCHEDULED"
    if client["no_show_strikes"] > 0:
        client["no_show_strikes"] -= 1
    appt["settlement_status"] = "UNSETTLED"
    appt["no_show_fee_cents"] = 0
    appt["client_owed_cents"] = 0
    h.touch(appt)
    h.touch(client)
    return response.success(serialize(appt))


# ---------------------------------------------------------------------------
# Price (PRD §3.8)
# ---------------------------------------------------------------------------

@bp.post("/practice/appointments/<id>/price")
def price(id):
    caller = authenticate()
    require_role(caller, {"FrontDesk", "PracticeAdmin"})
    appt = h.resolve(db.appointments, id)
    if appt["settlement_status"] != "UNSETTLED":
        raise ApiError(*ERR_INVALID_STATE, message="not UNSETTLED")
    if appt["scheduling_status"] != "COMPLETED":
        raise ApiError(*ERR_INVALID_STATE, message="not COMPLETED")

    modality = db.modalities[appt["modality_id"]]
    client = db.clients[appt["client_id"]]

    # Membership redemption gate (PRD §3.10) runs at price time for MEMBERSHIP
    if appt["payer"] == "MEMBERSHIP":
        pkg = db.packages.get(appt.get("package_id")) if appt.get("package_id") else None
        if (appt.get("package_id") is None or pkg is None
                or pkg["package_status"] != "ACTIVE"
                or pkg["client_id"] != appt["client_id"]
                or pkg["credit_balance_sessions"] < 1):
            raise ApiError(*ERR_NO_CREDITS, message="no credits")

    service_charge = svc.compute_service_charge(appt, modality)
    appt["service_charge_cents"] = service_charge

    # payment waterfall
    owed = service_charge
    wallet_contribution = min(client["wallet_credit_cents"], owed)
    owed -= wallet_contribution
    appt["client_owed_cents"] = owed
    appt["_wallet_applied_cents"] = wallet_contribution

    # MEMBERSHIP redemption (writes REDEEM, recompute balance) if not already
    if appt["payer"] == "MEMBERSHIP" and not appt.get("_credit_redeemed"):
        pkg = db.packages[appt["package_id"]]
        pkgsvc.write_ledger(pkg, "REDEEM", -1)
        h.touch(pkg)
        appt["_credit_redeemed"] = True

    appt["settlement_status"] = "PRICED"
    h.touch(appt)
    return response.success(serialize(appt))


# ---------------------------------------------------------------------------
# Pay (PRD §3.9)
# ---------------------------------------------------------------------------

@bp.post("/practice/appointments/<id>/pay")
def pay(id):
    caller = authenticate()
    require_role(caller, {"FrontDesk", "PracticeAdmin"})
    appt = h.resolve(db.appointments, id)
    if appt["settlement_status"] != "PRICED":
        raise ApiError(*ERR_INVALID_STATE, message="not PRICED")
    body = h.get_body()
    if "gratuity_cents" in body and body["gratuity_cents"] is not None:
        gratuity = h.as_int(body["gratuity_cents"], "gratuity_cents", minimum=0)
        appt["gratuity_cents"] = gratuity

    client = db.clients[appt["client_id"]]
    therapist = db.therapists[appt["therapist_id"]]

    # HSA sufficiency
    if appt["payer"] == "HSA":
        if client["hsa_balance_cents"] < appt["client_owed_cents"]:
            raise ApiError(*ERR_INSUFFICIENT_HSA, message="insufficient HSA")
        client["hsa_balance_cents"] -= appt["client_owed_cents"]
        h.touch(client)

    # decrement wallet by applied amount
    wallet_applied = appt.get("_wallet_applied_cents", 0)
    if wallet_applied > 0:
        client["wallet_credit_cents"] -= wallet_applied
        if client["wallet_credit_cents"] < 0:
            client["wallet_credit_cents"] = 0
        h.touch(client)

    appt["settlement_status"] = "PAID"

    # Credit the therapist.
    service_charge = appt["service_charge_cents"]
    commission = svc.compute_commission(therapist, service_charge)
    appt["commission_credited_cents"] = commission
    therapist["mtd_service_revenue_cents"] += service_charge
    therapist["accrued_commission_cents"] += commission + appt["gratuity_cents"]
    h.touch(therapist)

    h.touch(appt)
    return response.success(serialize(appt))


# ---------------------------------------------------------------------------
# Void (PRD §3.9)
# ---------------------------------------------------------------------------

@bp.post("/practice/appointments/<id>/void")
def void(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin"})
    appt = h.resolve(db.appointments, id)
    if appt["settlement_status"] not in ("UNSETTLED", "PRICED"):
        raise ApiError(*ERR_INVALID_STATE, message="not voidable")

    appt["settlement_status"] = "VOID"
    # refund redeemed credit
    svc.refund_credit_if_redeemed(appt)
    h.touch(appt)
    return response.success(serialize(appt))
