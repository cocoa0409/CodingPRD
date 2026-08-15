"""Cross-entity side effects: expiry touch, revocation cascade, ledger postings,
unit manufacture, recycling-intake creation from unit scrap."""
from datetime import timedelta

import clock
import db
import errors
from services import calc

FILLING_COMPONENT_TYPES = {"FOAM_CORE", "MEMORY_LAYER", "FIRE_BARRIER", "TICKING"}


# ---------------------------------------------------------------------------
# Lazy certificate expiry (PRD section 3.3): APPROVED -> EXPIRED when the
# logical clock passes expires_on; applied on any read/validation touch.
# Expiry never cascades.
# ---------------------------------------------------------------------------

def touch_certificates():
    now = clock.now()
    for cert in db.certificates.values():
        if cert["status"] == "APPROVED" and clock.iso_parse(cert["expires_on"]) <= now:
            cert["status"] = "EXPIRED"


def approved_unexpired_flammability_certs(model_id):
    touch_certificates()
    now = clock.now()
    result = []
    for cert in db.certificates.values():
        if cert["model_id"] != model_id:
            continue
        if cert["cert_type"] != "FLAMMABILITY_16CFR1633":
            continue
        if cert["status"] != "APPROVED":
            continue
        if clock.iso_parse(cert["expires_on"]) <= now:
            continue
        result.append(cert)
    return result


# ---------------------------------------------------------------------------
# Certificate revocation cascade (3 hops, PRD section 3.3)
# ---------------------------------------------------------------------------

def revoke_cascade(model):
    """Called after a FLAMMABILITY_16CFR1633 cert is revoked when no other
    APPROVED unexpired one remains. Model CERTIFIED|ACTIVE -> CERT_REVIEW,
    labels superseded, matching open orders pushed into QC_HOLD."""
    if model["status"] in ("CERTIFIED", "ACTIVE"):
        model["status"] = "CERT_REVIEW"
        bump(model)
        # hop 2: supersede all non-terminal labels of this model
        for label in db.law_labels.values():
            if label["model_id"] != model["id"]:
                continue
            if label["status"] in ("GENERATED", "APPROVED", "ACTIVE"):
                label["status"] = "SUPERSEDED"
                bump(label)
                # hop 3: hold matching open orders for the label's state
                for order in db.orders.values():
                    if (
                        order["model_id"] == model["id"]
                        and order["destination_state_code"] == label["state_code"]
                        and order["production_status"] in ("MATERIAL_ALLOCATED", "IN_PRODUCTION", "QC_PENDING")
                    ):
                        order["production_status"] = "QC_HOLD"
                        bump(order)


# ---------------------------------------------------------------------------
# Retailer credit ledger
# ---------------------------------------------------------------------------

def post_credit_adjustment(retailer, amount_cents, reason, source, source_id):
    adj = {
        "id": db.new_id(),
        "retailer_id": retailer["id"],
        "amount_cents": amount_cents,
        "reason": reason,
        "source": source,
        "source_id": source_id,
        "created_at": clock.now_iso(),
    }
    db.put(db.credit_adjustments, adj)
    retailer["credit_balance_cents"] = sum(
        a["amount_cents"]
        for a in db.credit_adjustments.values()
        if a["retailer_id"] == retailer["id"]
    )
    bump(retailer)
    return adj


# ---------------------------------------------------------------------------
# Version / timestamp helpers
# ---------------------------------------------------------------------------

def bump(entity):
    """Every mutation of a versioned resource bumps version and updated_at."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = clock.now_iso()


# ---------------------------------------------------------------------------
# Mattress unit manufacture (complete-production hop and exchange replacement)
# ---------------------------------------------------------------------------

def manufacture_unit(order, law_label_id):
    unit = {
        "id": db.new_id(),
        "serial_no": "%d-%04d" % (order["order_seq"], order["units_made"] + 1),
        "order_id": order["id"],
        "model_id": order["model_id"],
        "retailer_id": order["retailer_id"],
        "foam_batch_id": order["foam_batch_id"],
        "law_label_id": law_label_id,
        "purchase_price_cents": order["unit_price_cents"],
        "delivered_at": None,
        "status": "MANUFACTURED",
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
    }
    order["units_made"] += 1
    db.put(db.units, unit)
    return unit


def active_label_for(model_id, state_code):
    for label in db.law_labels.values():
        if (
            label["model_id"] == model_id
            and label["state_code"] == state_code
            and label["status"] == "ACTIVE"
        ):
            return label
    return None


# ---------------------------------------------------------------------------
# Recycling intake creation (shared by the endpoint and the return-recycle
# cascade; cascade posts provisional with source EXCHANGE_RECOVERY)
# ---------------------------------------------------------------------------

def create_recycling_intake(retailer, declared_weight_kg, unit_id, source):
    intake = {
        "id": db.new_id(),
        "retailer_id": retailer["id"],
        "unit_id": unit_id,
        "declared_weight_kg": declared_weight_kg,
        "provisional_credit_cents": calc.recycling_provisional(declared_weight_kg),
        "final_credit_cents": None,
        "status": "RECEIVED",
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
    }
    db.put(db.intakes, intake)
    post_credit_adjustment(
        retailer,
        intake["provisional_credit_cents"],
        "Recycling take-back provisional credit",
        source,
        intake["id"],
    )
    return intake


def bom_recyclable_mass(model_id):
    """Sum of quantity_per_unit over FOAM_CORE, MEMORY_LAYER, TICKING,
    FOUNDATION BOM lines (return-recycle cascade declared weight)."""
    total = calc.dec(0)
    for line in db.bom_lines.values():
        if line["model_id"] != model_id:
            continue
        if line["component_type"] in ("FOAM_CORE", "MEMORY_LAYER", "TICKING", "FOUNDATION"):
            total += calc.dec(line["quantity_per_unit"])
    return float(total)
