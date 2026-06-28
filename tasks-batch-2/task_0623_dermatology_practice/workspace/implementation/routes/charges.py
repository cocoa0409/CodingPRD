"""Charges: dual-path split, biologic pricing, void compensations (PRD 3.7, 3.8)."""
from flask import Blueprint, request

import db
import errors
import helpers
import response
import services
from middleware import require
from routes.encounters import _void_charge_compensations

bp = Blueprint("charges", __name__)

SOURCE_KINDS = {"ENCOUNTER", "COSMETIC_TREATMENT", "PROCEDURE_BOOKING"}
CHARGE_KINDS = {"OFFICE_VISIT", "PROCEDURE", "BIOLOGIC", "COSMETIC"}


@bp.post("/charges")
@require("BillingSpecialist")
def post_charge():
    data = helpers.body()
    patient_id = helpers.require_str(data, "patient_id")
    encounter_id = helpers.require_str(data, "encounter_id")
    source_kind = helpers.require_enum(data, "source_kind", SOURCE_KINDS)
    charge_kind = helpers.require_enum(data, "charge_kind", CHARGE_KINDS)
    billed_amount_cents = helpers.require_int(data, "billed_amount_cents")
    insurer_allowed_cents = helpers.opt_int(data, "insurer_allowed_cents", None)
    prior_auth_id = data.get("prior_auth_id")
    cosmetic_treatment_id = data.get("cosmetic_treatment_id")

    # Priority 4: body FK existence.
    patient = helpers.get_or_404(db.patients, patient_id, "patient")
    enc = helpers.get_or_404(db.encounters, encounter_id, "encounter")
    pa = None
    if prior_auth_id is not None:
        pa = helpers.get_or_404(db.prior_authorizations, prior_auth_id, "prior_auth")
    if cosmetic_treatment_id is not None:
        helpers.get_or_404(db.cosmetic_treatments, cosmetic_treatment_id, "treatment")

    pay_path = enc["pay_path"]

    # Priority 12: BIOLOGIC requires a non-null prior_auth_id whose PA is APPROVED.
    if charge_kind == "BIOLOGIC":
        if pa is None or pa["status"] != "APPROVED":
            raise errors.pa_not_approved()

    # Priority 14: encounter billing must be BILLING_OPEN.
    if enc["billing_status"] != "BILLING_OPEN":
        raise errors.encounter_billing_locked()

    # Priority 16: allowed-amount requirement by pay path.
    if charge_kind == "BIOLOGIC":
        # Biologic self-prices: the server overwrites billed_amount_cents and,
        # on the INSURANCE path, copies it into insurer_allowed_cents. The
        # client's billed/allowed inputs are ignored, so the allowed-amount
        # requirement does not gate biologic charges.
        billed_amount_cents = services.biologic_charge_amount(pa)
        if pay_path == "INSURANCE":
            insurer_allowed_cents = billed_amount_cents
        else:
            insurer_allowed_cents = None
    else:
        if pay_path == "INSURANCE":
            if insurer_allowed_cents is None:
                raise errors.allowed_amount_required()
        else:  # CASH
            if insurer_allowed_cents is not None:
                raise errors.allowed_amount_required()

    row = {
        "patient_id": patient_id,
        "encounter_id": encounter_id,
        "prior_auth_id": prior_auth_id,
        "cosmetic_treatment_id": cosmetic_treatment_id,
        "source_kind": source_kind,
        "charge_kind": charge_kind,
        "billed_amount_cents": billed_amount_cents,
        "insurer_allowed_cents": insurer_allowed_cents,
        "pay_path": pay_path,
        "patient_responsibility_cents": 0,
        "insurer_responsibility_cents": 0,
        "deductible_applied_cents": 0,
        "status": "POSTED",
    }
    db.stamp_new(row)
    # Compute split (mutates row + writes back deductible on INSURANCE path).
    services.compute_charge_split(row, patient)
    db.charges[row["id"]] = row
    return response.created(row)


@bp.get("/charges/<cid>")
@require("BillingSpecialist", "PracticeAdmin", "Provider")
def get_charge(cid):
    row = helpers.get_or_404(db.charges, cid, "charge")
    return response.ok(row)


@bp.get("/charges")
@require("BillingSpecialist", "PracticeAdmin", "Provider")
def list_charges():
    rows = list(db.charges.values())
    for key in ("patient_id", "encounter_id", "prior_auth_id", "cosmetic_treatment_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [c for c in rows if c.get(key) == val]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing(page, limit, offset, total)


@bp.post("/charges/<cid>/pay")
@require("BillingSpecialist")
def pay_charge(cid):
    c = helpers.get_or_404(db.charges, cid, "charge")
    if c["status"] != "POSTED":
        raise errors.bad_state("ERR_CHARGE_BAD_STATE")
    c["status"] = "PAID"
    db.touch(c)
    return response.ok(c)


@bp.post("/charges/<cid>/void")
@require("BillingSpecialist")
def void_charge(cid):
    c = helpers.get_or_404(db.charges, cid, "charge")
    if c["status"] != "POSTED":
        raise errors.bad_state("ERR_CHARGE_BAD_STATE")
    _void_charge_compensations(c)
    c["status"] = "VOIDED"
    db.touch(c)
    return response.ok(c)
