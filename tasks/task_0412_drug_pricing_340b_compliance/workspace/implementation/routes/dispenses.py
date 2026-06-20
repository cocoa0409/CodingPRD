"""PrescriptionDispense: record (eligibility + line cost + accumulator cascade),
fetch, list, reverse, reinstate, and the Medicaid-claim subresource."""
import re

from flask import Blueprint

import lookup
from db import db, base_record, touch
from errors import err
from middleware import get_identity, require_role, get_json_body, serialize
from response import success, list_success
from validation import require_string, require_int, parse_pagination, paginate
from filters import filter_eq
from services.eligibility import determine
from services.pricing import effective_ceiling
from services.accumulator import find_accumulator, accrue_and_replenish, debit

bp = Blueprint("dispenses", __name__)

QUARTER_RE = re.compile(r"^[0-9]{4}Q[1-4]$")
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


@bp.route("/dispenses", methods=["POST"])
def create_dispense():
    _, role = get_identity()
    require_role(role, {"PharmacyOperator"})
    body = get_json_body()

    # --- existence of FK parents (ERR_NOT_FOUND, priority 3) precedes non-FK
    #     request-shape validity (ERR_INVALID_REQUEST, priority 4). FK fields are
    #     parsed as present strings first (a prerequisite to looking them up),
    #     then resolved, then the remaining shape checks run. ---
    covered_entity_id = require_string(body, "covered_entity_id")
    patient_id = require_string(body, "patient_id")
    prescriber_id = require_string(body, "prescriber_id")
    drug_product_id = require_string(body, "drug_product_id")

    child_site_id = body.get("child_site_id")
    contract_pharmacy_id = body.get("contract_pharmacy_id")
    if child_site_id is not None and not isinstance(child_site_id, str):
        raise err("ERR_INVALID_REQUEST", "child_site_id must be a string")
    if contract_pharmacy_id is not None and not isinstance(contract_pharmacy_id, str):
        raise err("ERR_INVALID_REQUEST", "contract_pharmacy_id must be a string")

    ce = lookup.covered_entity(covered_entity_id)
    patient = lookup.patient(patient_id)
    prescriber = lookup.prescriber(prescriber_id)
    drug = lookup.drug_product(drug_product_id)
    child_site = lookup.child_site(child_site_id) if child_site_id is not None else None
    contract_pharmacy = (
        lookup.contract_pharmacy(contract_pharmacy_id)
        if contract_pharmacy_id is not None
        else None
    )

    # --- non-FK request-shape validity (ERR_INVALID_REQUEST, priority 4) ---
    quantity_units = require_int(body, "quantity_units", minimum=1)
    quarter = require_string(body, "quarter")
    if not QUARTER_RE.match(quarter):
        raise err("ERR_INVALID_REQUEST", "quarter must match YYYYQn")

    # --- cross-entity referential ownership (ERR_CROSS_ENTITY_MISMATCH, prio 5) ---
    if patient["covered_entity_id"] != ce["id"]:
        raise err("ERR_CROSS_ENTITY_MISMATCH", "patient does not belong to covered entity")
    if prescriber["covered_entity_id"] != ce["id"]:
        raise err("ERR_CROSS_ENTITY_MISMATCH", "prescriber does not belong to covered entity")
    if child_site is not None and child_site["covered_entity_id"] != ce["id"]:
        raise err("ERR_CROSS_ENTITY_MISMATCH", "child site does not belong to covered entity")
    if contract_pharmacy is not None and contract_pharmacy["covered_entity_id"] != ce["id"]:
        raise err("ERR_CROSS_ENTITY_MISMATCH", "contract pharmacy does not belong to covered entity")

    # --- CE must be ACTIVE (ERR_CE_NOT_ACTIVE, prio 8) ---
    if ce["registration_status"] != "ACTIVE":
        raise err("ERR_CE_NOT_ACTIVE", "covered entity is not ACTIVE")

    # contract pharmacy must be ACTIVE when present
    if contract_pharmacy is not None and contract_pharmacy["arrangement_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "contract pharmacy arrangement is not ACTIVE")

    # --- eligibility cascade ---
    classification, reason = determine(patient, prescriber, child_site, ce)

    # --- pricing ---
    if classification == "CLASSIFIED_340B":
        eff, _variant = effective_ceiling(drug["id"], quarter)
        if eff is None:
            raise err("ERR_NO_CEILING_PRICE", "No ceiling price for (drug, quarter)")
        applied_price = eff["ceiling_price_per_unit_cents"]
    else:
        applied_price = drug["wac_price_per_unit_cents"]
    line_cost = applied_price * quantity_units

    rec = base_record(full_meta=True)
    rec.update(
        {
            "covered_entity_id": ce["id"],
            "child_site_id": child_site_id,
            "contract_pharmacy_id": contract_pharmacy_id,
            "patient_id": patient_id,
            "prescriber_id": prescriber_id,
            "drug_product_id": drug_product_id,
            "quantity_units": quantity_units,
            "quarter": quarter,
            "dispense_status": "DISPENSED",
            "classification_status": classification,
            "eligibility_reason": reason,
            "applied_price_per_unit_cents": applied_price,
            "line_cost_cents": line_cost,
        }
    )
    db.dispenses.put(rec)

    # --- 340B accumulator cascade ---
    if classification == "CLASSIFIED_340B":
        acc = find_accumulator(ce["id"], drug["id"])
        if acc is not None:
            accrue_and_replenish(acc, quantity_units, rec["id"], applied_price, quarter)

    return success(serialize(rec), status=201)


@bp.route("/dispenses/<d_id>", methods=["GET"])
def get_dispense(d_id):
    get_identity()
    d = lookup.dispense(d_id)
    return success(serialize(d))


@bp.route("/dispenses", methods=["GET"])
def list_dispenses():
    get_identity()
    limit, offset = parse_pagination()
    items = lookup.sorted_by_created(db.dispenses.all())
    for f in (
        "covered_entity_id",
        "patient_id",
        "prescriber_id",
        "drug_product_id",
        "contract_pharmacy_id",
        "child_site_id",
        "classification_status",
        "dispense_status",
    ):
        items = filter_eq(items, f)
    page, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.route("/dispenses/<d_id>/reverse", methods=["POST"])
def reverse_dispense(d_id):
    _, role = get_identity()
    require_role(role, {"PharmacyOperator"})
    d = lookup.dispense(d_id)

    if d["dispense_status"] != "DISPENSED":
        raise err("ERR_INVALID_STATE", "Only a DISPENSED dispense may be reversed")
    # Blocked when any finding referencing it is UNDER_REVIEW/DISPUTED/RESOLVED.
    for f in db.audit_findings.all():
        if f["prescription_dispense_id"] == d["id"] and f["finding_status"] in (
            "UNDER_REVIEW",
            "DISPUTED",
            "RESOLVED",
        ):
            raise err("ERR_INVALID_STATE", "Dispense under compliance review may not be reversed")

    d["dispense_status"] = "REVERSED"
    touch(d)
    # Compensate the accumulator for a 340B dispense.
    if d["classification_status"] == "CLASSIFIED_340B":
        acc = find_accumulator(d["covered_entity_id"], d["drug_product_id"])
        if acc is not None:
            debit(acc, d["quantity_units"])
    return success(serialize(d))


@bp.route("/dispenses/<d_id>/reinstate", methods=["POST"])
def reinstate_dispense(d_id):
    _, role = get_identity()
    require_role(role, {"PharmacyOperator"})
    d = lookup.dispense(d_id)

    if d["dispense_status"] != "REVERSED":
        raise err("ERR_INVALID_STATE", "Only a REVERSED dispense may be reinstated")
    ce = db.covered_entities.get(d["covered_entity_id"])
    if ce is None or ce["registration_status"] != "ACTIVE":
        raise err("ERR_CE_NOT_ACTIVE", "covered entity is not ACTIVE")

    d["dispense_status"] = "DISPENSED"
    touch(d)
    if d["classification_status"] == "CLASSIFIED_340B":
        acc = find_accumulator(d["covered_entity_id"], d["drug_product_id"])
        if acc is not None:
            accrue_and_replenish(
                acc, d["quantity_units"], d["id"], d["applied_price_per_unit_cents"], d["quarter"]
            )
    return success(serialize(d))


# --------------------------------------------------------------------------
# Medicaid claims (subresource of a dispense)
# --------------------------------------------------------------------------
@bp.route("/dispenses/<d_id>/medicaid-claims", methods=["POST"])
def create_medicaid_claim(d_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer"})
    d = lookup.dispense(d_id)
    body = get_json_body()

    medicaid_state_code = require_string(body, "medicaid_state_code")
    if not STATE_CODE_RE.match(medicaid_state_code):
        raise err("ERR_INVALID_REQUEST", "medicaid_state_code must be two uppercase letters")

    ce = db.covered_entities.get(d["covered_entity_id"])

    # Duplicate-discount guard: a 340B dispense at a CARVE_OUT CE is rejected.
    if d["classification_status"] == "CLASSIFIED_340B" and ce["medicaid_billing_mode"] == "CARVE_OUT":
        raise err("ERR_DUPLICATE_DISCOUNT", "Carve-out CE may not bill Medicaid against a 340B dispense")

    # DUPLICATE_RISK: 340B dispense for a carve-in CE not listed on the MEF.
    claim_status = "CLEAN"
    if (
        d["classification_status"] == "CLASSIFIED_340B"
        and ce["medicaid_billing_mode"] == "CARVE_IN"
        and not ce.get("medicaid_provider_number")
    ):
        claim_status = "DUPLICATE_RISK"

    rec = base_record(full_meta=True)
    rec.update(
        {
            "prescription_dispense_id": d["id"],
            "medicaid_state_code": medicaid_state_code,
            "claim_status": claim_status,
        }
    )
    db.medicaid_claims.put(rec)
    return success(serialize(rec), status=201)


@bp.route("/dispenses/<d_id>/medicaid-claims", methods=["GET"])
def list_medicaid_claims(d_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer", "HrsaAuditor"})
    d = lookup.dispense(d_id)
    limit, offset = parse_pagination()
    items = [
        c for c in db.medicaid_claims.all() if c["prescription_dispense_id"] == d["id"]
    ]
    items = lookup.sorted_by_created(items)
    items = filter_eq(items, "claim_status")
    page, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)
