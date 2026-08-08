"""Controlled analgesic orders and the patient MME ledger (PRD 3.8)."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import config
from envelope import created, listing, ok
from errors import (
    ERR_EARLY_REFILL, ERR_MME_REVIEW_REQUIRED, ERR_SEGREGATION_OF_DUTIES, api_error,
)
from ladder import (
    apply_filters, auth, field, fk, freeze_gate, pagination, paginate,
    path_row, query_filters, raw_body, state, touch, validate,
)
from store import ordered, store

bp = Blueprint("medications", __name__)

THRESHOLD = Decimal(config.MME_REVIEW_THRESHOLD)


@bp.post("/palliative/medication-orders")
def create_medication_order():
    ctx = auth([config.ROLE_PHYSICIAN, config.ROLE_ADMIN])
    body = raw_body()
    data = validate(body, [
        field("patient_id", "string", required=True),
        field("drug", "enum", required=True, enum=config.DRUGS),
        field("dose_amount", "number", required=True, gt=0),
        field("days_supply", "integer", required=True, lo=1, hi=90),
        field("breakthrough_drug", "enum", enum=config.BREAKTHROUGH_DRUGS),
    ])
    patient = fk(store.patients, data["patient_id"])
    freeze_gate(patient)

    variant, mme_daily = calc.medication_daily_mme(
        data["drug"], data["dose_amount"], patient["opioid_status"])
    row = store.new_row({
        "patient_id": patient["id"],
        "drug": data["drug"],
        "dose_amount": body["dose_amount"],
        "days_supply": data["days_supply"],
        "breakthrough_drug": data["breakthrough_drug"],
        "prescriber_user_id": ctx.user_id,
        "verifier_user_id": None,
        "mme_variant": variant,
        "mme_daily": mme_daily,
        "breakthrough_dose_mg": None,
        "last_fill_at": None,
        "next_refill_allowed_at": None,
        "refill_count": 0,
        "mme_review_count": 0,
        "status": "PENDING_VERIFICATION",
    })
    store.medication_orders[row["id"]] = row
    return created(row)


def _activate(order, patient):
    order["last_fill_at"] = store.now()
    order["next_refill_allowed_at"] = calc.next_refill_allowed_at(
        order["last_fill_at"], order["days_supply"])
    order["status"] = "ACTIVE"
    touch(order)
    cascades.recompute_active_daily_mme(patient)
    cascades.recompute_breakthrough(patient)


@bp.post("/palliative/medication-orders/<mid>/attestations")
def attest_medication_order(mid):
    ctx = auth([config.ROLE_NURSE, config.ROLE_PHYSICIAN, config.ROLE_ADMIN])
    order = path_row(store.medication_orders, mid)
    body = raw_body()
    data = validate(body, [
        field("attestation_type", "enum", required=True, enum=config.MED_ATTESTATION_TYPES),
        field("attestation_note", "string"),
    ])
    patient = store.patients.get(order["patient_id"])
    freeze_gate(patient)
    if data["attestation_type"] == "VERIFICATION":
        state(order["status"] == "PENDING_VERIFICATION")
    else:
        state(order["status"] == "REVIEW_REQUIRED")
    if ctx.user_id == order["prescriber_user_id"]:
        raise api_error(ERR_SEGREGATION_OF_DUTIES)

    if data["attestation_type"] == "VERIFICATION":
        order["verifier_user_id"] = ctx.user_id
        projected = patient["active_daily_mme"] + order["mme_daily"]
        if projected < THRESHOLD:
            _activate(order, patient)
        else:
            order["status"] = "REVIEW_REQUIRED"
            touch(order)
    else:
        order["mme_review_count"] += 1
        _activate(order, patient)
    return ok(order)


@bp.post("/palliative/medication-orders/<mid>/refills")
def refill_medication_order(mid):
    auth([config.ROLE_NURSE, config.ROLE_ADMIN])
    order = path_row(store.medication_orders, mid)
    body = raw_body()
    validate(body, [field("refill_note", "string")])
    patient = store.patients.get(order["patient_id"])
    freeze_gate(patient)
    state(order["status"] in ("ACTIVE", "REVIEW_REQUIRED"))
    if order["status"] == "REVIEW_REQUIRED":
        raise api_error(ERR_MME_REVIEW_REQUIRED)
    if order["next_refill_allowed_at"] is None or store.now() < order["next_refill_allowed_at"]:
        raise api_error(ERR_EARLY_REFILL)

    order["refill_count"] += 1
    order["last_fill_at"] = store.now()
    order["next_refill_allowed_at"] = calc.next_refill_allowed_at(
        order["last_fill_at"], order["days_supply"])
    if patient["active_daily_mme"] >= THRESHOLD:
        order["status"] = "REVIEW_REQUIRED"
        touch(order)
        cascades.recompute_active_daily_mme(patient)
        cascades.recompute_breakthrough(patient)
    else:
        touch(order)
    return ok(order)


@bp.post("/palliative/medication-orders/<mid>/discontinue")
def discontinue_medication_order(mid):
    auth([config.ROLE_PHYSICIAN, config.ROLE_ADMIN])
    order = path_row(store.medication_orders, mid)
    body = raw_body()
    validate(body, [field("discontinue_reason", "string", required=True)])
    patient = store.patients.get(order["patient_id"])
    freeze_gate(patient)
    state(order["status"] in ("PENDING_VERIFICATION", "ACTIVE", "REVIEW_REQUIRED"))
    order["status"] = "DISCONTINUED"
    touch(order)
    cascades.recompute_active_daily_mme(patient)
    cascades.recompute_breakthrough(patient)
    return ok(order)


@bp.get("/palliative/patients/<pid>/medication-orders")
def list_patient_medication_orders(pid):
    auth([config.ROLE_PHYSICIAN, config.ROLE_NURSE, config.ROLE_ADMIN])
    patient = path_row(store.patients, pid)
    limit, offset = pagination()
    rows = [r for r in store.medication_orders.values() if r["patient_id"] == patient["id"]]
    rows = apply_filters(ordered(rows), query_filters(["status"]))
    page, total = paginate(rows, limit, offset)
    return listing(page, limit, offset, total)
