"""LicenseAgreement routes (incl. payments, performances, amendments, cancel, breach)."""
from flask import Blueprint, request

import db
from errors import (
    err_not_found, err_referenced_not_found, err_invalid_request, err_invalid_state,
    err_stale_version, err_payment_amount_invalid, err_performance_already_held,
    err_amendment_on_terminal,
)
from middleware import require_roles, check_applicant_owner
from response import ok_object, ok_list, parse_pagination
from services import calculations
from services.serializers import agreement_out, payment_out, performance_out

bp = Blueprint("agreements", __name__)

AGREEMENT_READ_ROLES = ("RightsAdmin", "LicensingOfficer", "Applicant", "FinanceOfficer", "MaterialsClerk")
AGREEMENT_LIST_ROLES = ("RightsAdmin", "LicensingOfficer", "Applicant", "FinanceOfficer")


def _get_agreement_or_404(agreement_id):
    g = db.agreements.get(agreement_id)
    if not g:
        raise err_not_found("Agreement not found")
    return g


@bp.get("/licensing/agreements/<agreement_id>")
def get_agreement(agreement_id):
    user_id, role = require_roles(*AGREEMENT_READ_ROLES)
    g = _get_agreement_or_404(agreement_id)
    check_applicant_owner(user_id, role, g["organization_id"])
    return ok_object(agreement_out(g))


@bp.get("/licensing/agreements")
def list_agreements():
    user_id, role = require_roles(*AGREEMENT_LIST_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.agreements.values())
    if role == "Applicant":
        items = [g for g in items if g["organization_id"] == user_id]
    for field in ("license_status", "payment_status", "organization_id", "title_id", "application_id", "supersedes_agreement_id"):
        v = request.args.get(field)
        if v is not None:
            items = [g for g in items if g.get(field) == v]
    items.sort(key=lambda g: (g["created_at"], g["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([agreement_out(g) for g in page], limit, offset, total)


@bp.post("/licensing/agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    require_roles("RightsAdmin")
    g = _get_agreement_or_404(agreement_id)
    if g["license_status"] != "PENDING_PAYMENT":
        raise err_invalid_state("Agreement must be PENDING_PAYMENT to activate")
    # Partial-payment activation rule: balance <= ceil(quoted / 2)
    half = -(-g["quoted_royalty_total_cents"] // 2)  # ceil division
    if not (g["payment_status"] == "PAID_IN_FULL" or g["royalty_balance_cents"] <= half):
        raise err_invalid_state("Agreement is not sufficiently funded to activate")
    g["license_status"] = "ACTIVE"
    g["updated_at"] = db.clock_now()
    g["version"] += 1
    return ok_object(agreement_out(g))


@bp.post("/licensing/agreements/<agreement_id>/payments")
def create_payment(agreement_id):
    require_roles("FinanceOfficer")
    g = _get_agreement_or_404(agreement_id)
    body = request.get_json(silent=True) or {}
    amount = body.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise err_invalid_request("amount_cents is required and must be an integer")
    # State check (payment_status machine): CANCELLED / BREACHED not accepted
    if g["license_status"] in ("CANCELLED", "BREACHED"):
        raise err_invalid_state("Payments not accepted on CANCELLED or BREACHED agreements")
    # Priority 16: amount sanity
    if amount < 1 or amount > g["royalty_balance_cents"]:
        raise err_payment_amount_invalid()

    now = db.clock_now()
    balance_before = g["royalty_balance_cents"]
    total_paid_before = sum(p["amount_cents"] for p in db.payments.values() if p["agreement_id"] == agreement_id)
    p = {
        "id": db.new_id(),
        "agreement_id": agreement_id,
        "amount_cents": amount,
        "paid_at": now,
        "refunded_cents": 0,
        "created_at": now,
        "_seq": db.next_seq(),
    }
    db.payments[p["id"]] = p
    cumulative_after = total_paid_before + amount
    if cumulative_after >= balance_before:
        g["royalty_balance_cents"] = 0
        g["payment_status"] = "PAID_IN_FULL"
    else:
        g["royalty_balance_cents"] = balance_before - amount
        g["payment_status"] = "PARTIALLY_PAID"
    g["updated_at"] = now
    g["version"] += 1
    return ok_object(payment_out(p), 201)


@bp.get("/licensing/agreements/<agreement_id>/payments")
def list_agreement_payments(agreement_id):
    user_id, role = require_roles("RightsAdmin", "FinanceOfficer", "Applicant")
    g = _get_agreement_or_404(agreement_id)
    check_applicant_owner(user_id, role, g["organization_id"])
    limit, offset = parse_pagination(request.args)
    items = [p for p in db.payments.values() if p["agreement_id"] == agreement_id]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([payment_out(p) for p in page], limit, offset, total)


@bp.get("/licensing/payments")
def list_payments():
    require_roles("RightsAdmin", "FinanceOfficer")
    limit, offset = parse_pagination(request.args)
    agreement_id = request.args.get("agreement_id")
    items = list(db.payments.values())
    if agreement_id is not None:
        items = [p for p in items if p["agreement_id"] == agreement_id]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([payment_out(p) for p in page], limit, offset, total)


@bp.get("/licensing/payments/<payment_id>")
def get_payment(payment_id):
    require_roles("RightsAdmin", "FinanceOfficer", "Applicant")
    p = db.payments.get(payment_id)
    if not p:
        raise err_not_found("Payment not found")
    return ok_object(payment_out(p))


@bp.post("/licensing/agreements/<agreement_id>/performances")
def create_performance(agreement_id):
    user_id, role = require_roles("Applicant")
    g = _get_agreement_or_404(agreement_id)
    check_applicant_owner(user_id, role, g["organization_id"])
    body = request.get_json(silent=True) or {}
    raw = body.get("performance_at")
    perf_at = db.parse_ts(raw) if raw is not None else None
    if perf_at is None:
        raise err_invalid_temporal("performance_at must be a valid ISO8601 UTC datetime")
    if g["license_status"] != "ACTIVE":
        raise err_invalid_state("Agreement must be ACTIVE to declare performances")
    # Priority 15: window fit + no duplicate performance_at for same agreement
    if perf_at < g["window_start"] or perf_at > g["window_end"]:
        raise err_performance_outside_window("performance_at outside agreement window")
    for p in db.performances.values():
        if p["agreement_id"] == agreement_id and p["performance_at"] == perf_at and p["status"] != "CANCELLED":
            raise err_performance_outside_window("duplicate performance_at for this agreement")
    now = db.clock_now()
    perf = {
        "id": db.new_id(),
        "agreement_id": agreement_id,
        "performance_at": perf_at,
        "reported_attendance": 0,
        "reported_gross_cents": 0,
        "gross_reported": False,
        "royalty_cents": 0,
        "status": "SCHEDULED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.performances[perf["id"]] = perf
    return ok_object(performance_out(perf), 201)


@bp.get("/licensing/agreements/<agreement_id>/performances")
def list_agreement_performances(agreement_id):
    user_id, role = require_roles("RightsAdmin", "LicensingOfficer", "Applicant", "FinanceOfficer")
    g = _get_agreement_or_404(agreement_id)
    check_applicant_owner(user_id, role, g["organization_id"])
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [p for p in db.performances.values() if p["agreement_id"] == agreement_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([performance_out(p) for p in page], limit, offset, total)


@bp.post("/licensing/agreements/<agreement_id>/amendments")
def apply_amendment(agreement_id):
    require_roles("RightsAdmin")
    g = _get_agreement_or_404(agreement_id)
    body = request.get_json(silent=True) or {}
    if g["license_status"] in ("COMPLETED", "CANCELLED", "BREACHED"):
        raise err_amendment_on_terminal()
    expected = body.get("expected_agreement_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_agreement_version is required and must be an integer")
    if expected != g["version"]:
        raise err_stale_version()
    new_window_end = body.get("new_window_end")
    additional = body.get("additional_performances")
    amendment_note = body.get("amendment_note")
    if amendment_note is not None and not isinstance(amendment_note, str):
        raise err_invalid_request("amendment_note must be a string")
    if new_window_end is not None:
        nwe = db.parse_ts(new_window_end)
        if nwe is None:
            raise err_invalid_temporal("new_window_end must be a valid ISO8601 UTC datetime")
        if not g["window_start"] < nwe:
            raise err_invalid_temporal("new_window_end must be after window_start")
    if additional is not None:
        if not isinstance(additional, int) or isinstance(additional, bool) or additional < 0:
            raise err_invalid_request("additional_performances must be an integer >= 0")

    now = db.clock_now()
    old_quoted = g["quoted_royalty_total_cents"]
    if new_window_end is not None:
        g["window_end"] = nwe
    if additional is not None and additional > 0:
        g["contracted_performance_count"] += additional
        title = db.titles[g["title_id"]]
        # QUOTED variant recomputation over projected figures
        synthetic_app = {
            "determined_classification": g["classification"],
            "venue_seating_capacity": g["house_seating_capacity"],
            "projected_gross_cents": db.applications[g["application_id"]]["projected_gross_cents"],
            "performance_count": g["contracted_performance_count"],
        }
        new_quoted = calculations.quoted_royalty_total(title, synthetic_app)
        g["quoted_royalty_total_cents"] = new_quoted
        g["royalty_balance_cents"] += (new_quoted - old_quoted)
    g["amendment_seq"] += 1
    g["updated_at"] = now
    g["version"] += 1
    return ok_object(agreement_out(g))


@bp.post("/licensing/agreements/<agreement_id>/cancel")
def cancel_agreement(agreement_id):
    require_roles("RightsAdmin")
    g = _get_agreement_or_404(agreement_id)
    if g["license_status"] != "ACTIVE":
        raise err_invalid_state("Agreement must be ACTIVE to cancel")
    # Priority 18: no HELD performance
    for p in db.performances.values():
        if p["agreement_id"] == agreement_id and p["status"] == "HELD":
            raise err_performance_already_held()
    now = db.clock_now()
    g["license_status"] = "CANCELLED"
    # Cascade: performances -> CANCELLED
    for p in db.performances.values():
        if p["agreement_id"] == agreement_id and p["status"] == "SCHEDULED":
            p["status"] = "CANCELLED"
            p["updated_at"] = now
            p["version"] += 1
    # Cascade: rentals deposit settlement
    for r in db.rentals.values():
        if r["agreement_id"] != agreement_id:
            continue
        if r["status"] in ("RESERVED", "SHIPPED", "RECEIVED", "RETURN_IN_TRANSIT"):
            if r["accrued_late_fee_cents"] == 0:
                r["deposit_status"] = "RETURNED"
            # else remains HELD pending fine settlement
            r["updated_at"] = now
            r["version"] += 1
        # rentals already OVERDUE stay OVERDUE
    # Cascade: recording grants REQUESTED/APPROVED -> REVOKED, reverse royalty debit
    for gr in db.recording_grants.values():
        if gr["agreement_id"] == agreement_id and gr["status"] in ("REQUESTED", "APPROVED"):
            was_approved = gr["status"] == "APPROVED"
            gr["status"] = "REVOKED"
            gr["updated_at"] = now
            gr["version"] += 1
            if was_approved:
                g["royalty_balance_cents"] -= gr["recording_royalty_cents"]
    # Cascade: alteration requests SUBMITTED -> DENIED
    for ar in db.alteration_requests.values():
        if ar["agreement_id"] == agreement_id and ar["status"] == "SUBMITTED":
            ar["status"] = "DENIED"
            ar["updated_at"] = now
            ar["version"] += 1
    # cancellation_refund_rule
    payments = [p for p in db.payments.values() if p["agreement_id"] == agreement_id]
    total_paid = sum(p["amount_cents"] for p in payments)
    refund_total = calculations.cancellation_refund(g, payments, now)
    if total_paid > 0 and refund_total >= total_paid:
        g["payment_status"] = "REFUNDED"
    g["updated_at"] = now
    g["version"] += 1
    return ok_object(agreement_out(g))


@bp.post("/licensing/agreements/<agreement_id>/declare_breach")
def declare_breach(agreement_id):
    require_roles("RightsAdmin")
    g = _get_agreement_or_404(agreement_id)
    body = request.get_json(silent=True) or {}
    reason = body.get("breach_reason")
    if not isinstance(reason, str) or not reason:
        raise err_invalid_request("breach_reason is required")
    if g["license_status"] != "ACTIVE":
        raise err_invalid_state("Agreement must be ACTIVE to declare breach")
    rl = reason.lower()
    if "recording" in rl:
        fine_kind = "UNAUTHORIZED_RECORDING"
    else:
        fine_kind = "UNAUTHORIZED_ALTERATION"
    now = db.clock_now()
    g["license_status"] = "BREACHED"
    amount = calculations.breach_fine_amount(fine_kind, g["quoted_royalty_total_cents"])
    org = db.organizations[g["organization_id"]]
    f = {
        "id": db.new_id(),
        "organization_id": g["organization_id"],
        "rental_id": None,
        "agreement_id": agreement_id,
        "fine_kind": fine_kind,
        "amount_cents": amount,
        "status": "ASSESSED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.fines[f["id"]] = f
    org["standing"] = "SUSPENDED"
    org["updated_at"] = now
    org["version"] += 1
    # RecordingGrants -> REVOKED (all statuses per state machine); reverse debit for APPROVED
    for gr in db.recording_grants.values():
        if gr["agreement_id"] == agreement_id and gr["status"] in ("REQUESTED", "APPROVED"):
            was_approved = gr["status"] == "APPROVED"
            gr["status"] = "REVOKED"
            gr["updated_at"] = now
            gr["version"] += 1
            if was_approved:
                g["royalty_balance_cents"] -= gr["recording_royalty_cents"]
    # SCHEDULED performances -> CANCELLED
    for p in db.performances.values():
        if p["agreement_id"] == agreement_id and p["status"] == "SCHEDULED":
            p["status"] = "CANCELLED"
            p["updated_at"] = now
            p["version"] += 1
    g["updated_at"] = now
    g["version"] += 1
    return ok_object(agreement_out(g))
