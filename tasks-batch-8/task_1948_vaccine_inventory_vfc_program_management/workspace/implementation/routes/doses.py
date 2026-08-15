"""Dose administrations (PRD §3.6) — the most heavily guarded write."""

from flask import Blueprint, request

import db
from errors import (
    invalid_state, ApiError,
    ERR_STORAGE_UNIT_QUARANTINED, ERR_LOT_NOT_AVAILABLE, ERR_LOT_EXPIRED,
    ERR_STOCK_ELIGIBILITY_MISMATCH, ERR_SCREENING_MISMATCH,
    ERR_PATIENT_NOT_VFC_ELIGIBLE_AGE, ERR_INSUFFICIENT_STOCK,
)
from middleware import get_auth, ALL_ROLES, ROLE_VACCINE_MANAGER
from response import success_object, paginate
from services.ledger import recompute_accountability_balance
from services.validate import require_body, require_string, require_date, get_or_404

bp = Blueprint("doses", __name__)


def serialize_dose(d):
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "provider_site_id": d["provider_site_id"],
        "patient_id": d["patient_id"],
        "eligibility_screening_id": d["eligibility_screening_id"],
        "lot_id": d["lot_id"],
        "administration_date": d["administration_date"],
        "administered_by_user_id": d["administered_by_user_id"],
        "funding_source": d["funding_source"],
        "registry_status": d["registry_status"],
        "borrowed_context_ticket_id": d["borrowed_context_ticket_id"],
    }


@bp.route("/provider-sites/<site_id>/dose-administrations", methods=["POST"])
def create_dose(site_id):
    user_id = get_auth([ROLE_VACCINE_MANAGER])
    site = get_or_404(db.provider_sites, site_id, "provider site")
    body = require_body(request.get_json(silent=True))
    patient_id = require_string(body, "patient_id")
    eligibility_screening_id = require_string(body, "eligibility_screening_id")
    lot_id = require_string(body, "lot_id")
    admin_date_raw, admin_date = require_date(body, "administration_date")
    borrowed_context_ticket_id = body.get("borrowed_context_ticket_id")

    # Priority 3: existence of every referenced id
    patient = get_or_404(db.patients, patient_id, "patient")
    screening = get_or_404(db.eligibility_screenings, eligibility_screening_id, "eligibility screening")
    lot = get_or_404(db.lots, lot_id, "lot")
    ticket = None
    if borrowed_context_ticket_id is not None:
        if not isinstance(borrowed_context_ticket_id, str):
            from errors import invalid_request
            raise invalid_request("borrowed_context_ticket_id must be a string")
        ticket = get_or_404(db.borrow_tickets, borrowed_context_ticket_id, "borrow ticket")

    # Business checks in PRD §3.6 order.

    # 1. (p6) Storage unit holding the lot must not be quarantined
    unit = db.storage_units.get(lot["storage_unit_id"])
    if unit is not None and unit["active_excursion_id"] is not None:
        raise ApiError(ERR_STORAGE_UNIT_QUARANTINED,
                       "Storage unit has an active excursion", 409)

    # 2. (p7) Lot must be AVAILABLE
    if lot["status"] != "AVAILABLE":
        raise ApiError(ERR_LOT_NOT_AVAILABLE, "Lot is not AVAILABLE", 409)

    # 3. (p8) administration_date must be <= lot.expires_on
    if admin_date > lot["_expires_on_date"]:
        raise ApiError(ERR_LOT_EXPIRED, "administration_date > lot.expires_on", 409)

    # 4. (p9) stock_type must match screening outcome unless covered by an OPEN ticket
    expected_stock = "PUBLIC_VFC" if screening["outcome"] == "VFC_ELIGIBLE" else "PRIVATE"
    if lot["stock_type"] != expected_stock:
        covered = False
        if ticket is not None and ticket["status"] == "OPEN":
            # Ticket must cover this borrow: it must involve this lot pairing direction.
            # A mismatch is permitted only when an OPEN BorrowTicket covers the dose
            # and borrowed_context_ticket_id is set.
            if ticket["to_lot_id"] == lot["id"] or ticket["from_lot_id"] == lot["id"]:
                covered = True
        if not covered:
            raise ApiError(ERR_STOCK_ELIGIBILITY_MISMATCH,
                           "Lot stock_type incompatible with screening outcome and no covering OPEN BorrowTicket",
                           422)

    # 5. (p10) Screening must belong to the same patient and screening_date == administration_date
    if screening["patient_id"] != patient["id"] or screening["screening_date"] != admin_date_raw:
        raise ApiError(ERR_SCREENING_MISMATCH,
                       "Screening belongs to a different patient or screening_date != administration_date",
                       422)

    # 6. (p11) For PUBLIC_VFC lots, patient must be active and < 19 on administration_date
    if lot["stock_type"] == "PUBLIC_VFC":
        age = db.age_years_on(patient["_dob_date"], admin_date)
        if not patient["is_active"] or age >= 19:
            raise ApiError(ERR_PATIENT_NOT_VFC_ELIGIBLE_AGE,
                           "Patient is not active or is 19 or older on administration_date",
                           422)

    # 7. (p13) Lot must hold at least one dose
    if lot["quantity_on_hand"] < 1:
        raise ApiError(ERR_INSUFFICIENT_STOCK, "Lot quantity_on_hand < requested doses", 422)

    # Apply effects
    lot["quantity_on_hand"] -= 1
    lot["updated_at"] = db.now_ts()
    lot["version"] += 1
    if lot["quantity_on_hand"] == 0:
        lot["status"] = "DEPLETED"

    funding_source = "PUBLIC_VFC" if lot["stock_type"] == "PUBLIC_VFC" else "PRIVATE"

    now = db.now_ts()
    dose = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "provider_site_id": site["id"],
        "patient_id": patient["id"],
        "eligibility_screening_id": screening["id"],
        "lot_id": lot["id"],
        "administration_date": admin_date_raw,
        "administered_by_user_id": user_id,
        "funding_source": funding_source,
        "registry_status": "PENDING_SUBMISSION",
        "borrowed_context_ticket_id": borrowed_context_ticket_id,
    }
    db.dose_administrations[dose["id"]] = dose

    if lot["stock_type"] == "PUBLIC_VFC":
        recompute_accountability_balance(site["id"])

    return success_object(serialize_dose(dose), 201)


def _filter_doses(items, args):
    f_site = args.get("provider_site_id")
    f_patient = args.get("patient_id")
    f_screening = args.get("eligibility_screening_id")
    f_lot = args.get("lot_id")
    f_ticket = args.get("borrowed_context_ticket_id")
    f_funding = args.get("funding_source")
    f_registry = args.get("registry_status")
    f_date = args.get("administration_date")
    if f_site is not None:
        items = [d for d in items if d["provider_site_id"] == f_site]
    if f_patient is not None:
        items = [d for d in items if d["patient_id"] == f_patient]
    if f_screening is not None:
        items = [d for d in items if d["eligibility_screening_id"] == f_screening]
    if f_lot is not None:
        items = [d for d in items if d["lot_id"] == f_lot]
    if f_ticket is not None:
        items = [d for d in items if d["borrowed_context_ticket_id"] == f_ticket]
    if f_funding is not None:
        items = [d for d in items if d["funding_source"] == f_funding]
    if f_registry is not None:
        items = [d for d in items if d["registry_status"] == f_registry]
    if f_date is not None:
        items = [d for d in items if d["administration_date"] == f_date]
    return items


@bp.route("/provider-sites/<site_id>/dose-administrations", methods=["GET"])
def list_doses(site_id):
    get_auth(ALL_ROLES)
    site = get_or_404(db.provider_sites, site_id, "provider site")
    items = [d for d in db.dose_administrations.values() if d["provider_site_id"] == site["id"]]
    items = _filter_doses(items, request.args)
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    return paginate([serialize_dose(d) for d in items], request.args)


@bp.route("/dose-administrations/<dose_id>", methods=["GET"])
def get_dose(dose_id):
    get_auth(ALL_ROLES)
    dose = get_or_404(db.dose_administrations, dose_id, "dose administration")
    return success_object(serialize_dose(dose))


@bp.route("/dose-administrations", methods=["GET"])
def list_doses_global():
    get_auth(ALL_ROLES)
    items = list(db.dose_administrations.values())
    items = _filter_doses(items, request.args)
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    return paginate([serialize_dose(d) for d in items], request.args)


def _get_site_dose(site_id, dose_id):
    site = get_or_404(db.provider_sites, site_id, "provider site")
    dose = get_or_404(db.dose_administrations, dose_id, "dose administration")
    if dose["provider_site_id"] != site["id"]:
        from errors import not_found
        raise not_found("dose administration")
    return dose


def _transition_registry(dose, from_states, to_state, message):
    if dose["registry_status"] not in from_states:
        raise invalid_state(message)
    dose["registry_status"] = to_state
    dose["updated_at"] = db.now_ts()
    dose["version"] += 1
    return success_object(serialize_dose(dose))


@bp.route("/provider-sites/<site_id>/dose-administrations/<dose_id>/submit-registry", methods=["POST"])
def submit_registry(site_id, dose_id):
    get_auth([ROLE_VACCINE_MANAGER])
    dose = _get_site_dose(site_id, dose_id)
    return _transition_registry(dose, ("PENDING_SUBMISSION",), "SUBMITTED",
                                "Dose must be PENDING_SUBMISSION")


@bp.route("/provider-sites/<site_id>/dose-administrations/<dose_id>/mark-registry-rejected", methods=["POST"])
def mark_registry_rejected(site_id, dose_id):
    get_auth([ROLE_VACCINE_MANAGER])
    dose = _get_site_dose(site_id, dose_id)
    return _transition_registry(dose, ("PENDING_SUBMISSION",), "REJECTED_BY_REGISTRY",
                                "Dose must be PENDING_SUBMISSION")


@bp.route("/provider-sites/<site_id>/dose-administrations/<dose_id>/reset-registry", methods=["POST"])
def reset_registry(site_id, dose_id):
    get_auth([ROLE_VACCINE_MANAGER])
    dose = _get_site_dose(site_id, dose_id)
    return _transition_registry(dose, ("REJECTED_BY_REGISTRY",), "PENDING_SUBMISSION",
                                "Dose must be REJECTED_BY_REGISTRY")
