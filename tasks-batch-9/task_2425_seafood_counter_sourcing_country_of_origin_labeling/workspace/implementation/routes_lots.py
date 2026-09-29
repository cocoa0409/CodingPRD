"""Supplier lots: receipt, casing, sales, relabelling and chargeback closure."""

from datetime import timedelta
from decimal import Decimal

import calc
import serializers
import services
from auth import counter_scope, supplier_scope
from common import base_record, dec, rhu, sort_records, touch
from envelope import obj_result
from errors import fail
from store import db
from validators import (
    opt_country,
    opt_id,
    req_bool,
    req_country,
    req_enum,
    req_int,
    req_number,
    req_str,
)
from web import listing, route

HARVEST_METHODS = (
    "WILD_NET",
    "WILD_LONGLINE",
    "WILD_TRAP",
    "AQUACULTURE_POND",
    "AQUACULTURE_PEN",
)
PRODUCTION_METHODS = ("WILD", "FARMED")

ALL_ROLES = (
    "ChainAdmin",
    "SeafoodManager",
    "ComplianceOfficer",
    "MerchandisingLead",
    "SupplierRep",
)


def resolve_lot(lot_id):
    """Priority 3/4 scope checks run before the priority 9 existence check, so
    the lot is resolved first and compared when it exists."""
    lot = db.lots.get(lot_id)
    if lot is not None:
        counter_scope(lot["counter_id"])
        supplier_scope(lot["supplier_id"])
    else:
        fail("ERR_LOT_NOT_FOUND")
    return lot


def guard_suspended(counter):
    if counter["posture"] == "SUSPENDED":
        fail("ERR_COUNTER_SUSPENDED")


def guard_restricted(counter):
    if counter["posture"] == "RESTRICTED":
        fail("ERR_COUNTER_RESTRICTED")


# --------------------------------------------------------------------------
# receipt
# --------------------------------------------------------------------------

@route("/lots", methods=["POST"], roles=("SeafoodManager",))
def receive_lot(body):
    raw_counter = opt_id(body, "counter_id")
    raw_supplier = opt_id(body, "supplier_id")
    raw_species = opt_id(body, "species_id")

    counter_scope(raw_counter)
    supplier_scope(None)

    counter = None
    if raw_counter is not None:
        counter = db.counters.get(raw_counter)
        if counter is None:
            fail("ERR_COUNTER_NOT_FOUND")
    supplier = None
    if raw_supplier is not None:
        supplier = db.suppliers.get(raw_supplier)
        if supplier is None:
            fail("ERR_SUPPLIER_NOT_FOUND")
    species = None
    if raw_species is not None:
        species = db.species.get(raw_species)
        if species is None:
            fail("ERR_SPECIES_NOT_FOUND")

    counter_id = req_str(body, "counter_id")
    supplier_id = req_str(body, "supplier_id")
    species_id = req_str(body, "species_id")
    lot_code = req_str(body, "lot_code")
    harvest_method = req_enum(body, "harvest_method", HARVEST_METHODS)
    production_method = req_enum(body, "production_method", PRODUCTION_METHODS)
    origin_country_code = req_country(body, "origin_country_code")
    processing_country_code = opt_country(body, "processing_country_code")
    previously_frozen = req_bool(body, "previously_frozen")
    fresh_claim = req_bool(body, "fresh_claim")
    received_weight_kg = req_number(body, "received_weight_kg", 3, exclusive_min=0)
    unit_cost = req_int(body, "unit_cost_cents_per_kg", minimum=1)
    retail_price = req_int(body, "retail_price_cents_per_kg", minimum=1)
    cooked_price = req_int(body, "cooked_retail_price_cents_per_kg", minimum=1)

    guard_suspended(counter)
    guard_restricted(counter)

    if previously_frozen and fresh_claim:
        fail("ERR_FROZEN_DISCLOSURE_CONFLICT")
    if supplier["chargeback_outstanding_cents"] >= calc.CREDIT_HOLD_CENTS:
        fail("ERR_SUPPLIER_CREDIT_HOLD")

    record = base_record("lot")
    record.update(
        {
            "counter_id": counter_id,
            "supplier_id": supplier_id,
            "species_id": species_id,
            "lot_code": lot_code,
            "harvest_method": harvest_method,
            "production_method": production_method,
            "origin_country_code": origin_country_code,
            "processing_country_code": processing_country_code,
            "previously_frozen": previously_frozen,
            "fresh_claim": fresh_claim,
            "received_weight_kg": received_weight_kg,
            "remaining_weight_kg": received_weight_kg,
            "unit_cost_cents_per_kg": unit_cost,
            "retail_price_cents_per_kg": retail_price,
            "cooked_retail_price_cents_per_kg": cooked_price,
            "case_slot": None,
            "cased_at": None,
            "vacated_at": None,
            "received_at": db.clock,
            "intake_status": "RECEIVED",
            "label_status": "UNVERIFIED",
            "chargeback_status": "NONE",
            "chargeback_assessed_cents": 0,
            "_vacated_slot": None,
        }
    )
    db.lots[record["id"]] = record
    return obj_result(serializers.lot, record, 201)


@route("/lots/<lot_id>", methods=["GET"], roles=ALL_ROLES)
def get_lot(body, lot_id):
    lot = resolve_lot(lot_id)
    return obj_result(serializers.lot, lot)


@route("/lots", methods=["GET"], roles=ALL_ROLES)
def list_lots(body):
    return listing(
        serializers.lot,
        list(db.lots.values()),
        string_fields=(
            "counter_id",
            "supplier_id",
            "species_id",
            "intake_status",
            "label_status",
            "chargeback_status",
        ),
    )


# --------------------------------------------------------------------------
# casing
# --------------------------------------------------------------------------

@route("/lots/<lot_id>/case", methods=["POST"], roles=("SeafoodManager",))
def case_lot(body, lot_id):
    lot = resolve_lot(lot_id)
    case_slot = req_int(body, "case_slot")

    if lot["intake_status"] != "RECEIVED":
        fail("ERR_LOT_STATE_INVALID")
    counter = services.lot_counter(lot)
    guard_suspended(counter)

    species = db.species.get(lot["species_id"])
    if species is not None and species["simp_covered"]:
        accepted = [
            document
            for document in db.simp_documents.values()
            if document["lot_id"] == lot["id"] and document["status"] == "ACCEPTED"
        ]
        if not accepted:
            fail("ERR_SIMP_DOCUMENT_MISSING")

    if case_slot < 1 or case_slot > counter["case_slot_count"]:
        fail("ERR_CASE_SLOT_OUT_OF_RANGE")

    for other in db.lots.values():
        if other["id"] == lot["id"]:
            continue
        if other["counter_id"] != lot["counter_id"]:
            continue
        if other["case_slot"] == case_slot and other["intake_status"] in ("CASED", "HELD"):
            fail("ERR_CASE_SLOT_OCCUPIED")

    previous = [
        other
        for other in db.lots.values()
        if other["counter_id"] == lot["counter_id"]
        and other.get("_vacated_slot") == case_slot
        and other["vacated_at"] is not None
    ]
    if previous:
        previous = sorted(previous, key=lambda r: (r["vacated_at"], r["_seq"]))
        last = previous[-1]
        if db.clock < last["vacated_at"] + timedelta(minutes=calc.SANITATION_BUFFER_MINUTES):
            fail("ERR_CASE_SLOT_OCCUPIED")

    lot["intake_status"] = "CASED"
    lot["case_slot"] = case_slot
    lot["cased_at"] = db.clock
    touch(lot)
    return obj_result(serializers.lot, lot)


# --------------------------------------------------------------------------
# sales
# --------------------------------------------------------------------------

@route("/lots/<lot_id>/record-sales", methods=["POST"], roles=("SeafoodManager",))
def record_sales(body, lot_id):
    lot = resolve_lot(lot_id)
    sold_weight_kg = req_number(body, "sold_weight_kg", 3, exclusive_min=0)

    if lot["intake_status"] != "CASED":
        fail("ERR_LOT_STATE_INVALID")
    guard_suspended(services.lot_counter(lot))

    remaining = dec(lot["remaining_weight_kg"])
    if sold_weight_kg > remaining:
        fail("ERR_INSUFFICIENT_REMAINING_WEIGHT")

    lot["remaining_weight_kg"] = rhu(remaining - sold_weight_kg, 3)
    touch(lot)
    if lot["remaining_weight_kg"] == Decimal("0.000"):
        services.vacate_lot(lot, "DEPLETED")
        services.withdraw_published_labels(lot, "MANUAL")
    return obj_result(serializers.lot, lot)


# --------------------------------------------------------------------------
# relabelling
# --------------------------------------------------------------------------

@route("/lots/<lot_id>/relabel", methods=["POST"], roles=("SeafoodManager",))
def relabel_lot(body, lot_id):
    lot = resolve_lot(lot_id)

    raw_species = opt_id(body, "corrected_species_id")
    if raw_species is not None and db.species.get(raw_species) is None:
        fail("ERR_SPECIES_NOT_FOUND")

    corrected_species_id = req_str(body, "corrected_species_id")
    corrected_market_name = req_str(body, "corrected_market_name")

    if lot["label_status"] != "MISMATCHED":
        fail("ERR_LABEL_STATE_INVALID")
    guard_suspended(services.lot_counter(lot))

    mismatches = [
        sample
        for sample in db.samples.values()
        if sample["lot_id"] == lot["id"] and sample["status"] == "MISMATCH"
    ]
    latest = None
    if mismatches:
        mismatches.sort(
            key=lambda s: (
                s["result_recorded_at"] or s["created_at"],
                s["created_at"],
                s["_seq"],
            )
        )
        latest = mismatches[-1]
    if latest is None or latest["observed_species_id"] != corrected_species_id:
        fail("ERR_RELABEL_SPECIES_MISMATCH")

    species = db.species[corrected_species_id]
    if corrected_market_name not in species["acceptable_market_names"]:
        fail("ERR_MARKET_NAME_NOT_ACCEPTABLE")

    lot["species_id"] = corrected_species_id
    lot["label_status"] = "RELABELED"
    touch(lot)
    for sample in sort_records(
        [s for s in db.samples.values() if s["lot_id"] == lot["id"] and s["status"] == "DISPUTED"]
    ):
        sample["status"] = "VOIDED"
        touch(sample)
    return obj_result(serializers.lot, lot)


# --------------------------------------------------------------------------
# chargeback closure
# --------------------------------------------------------------------------

@route("/lots/<lot_id>/settle-chargeback", methods=["POST"], roles=("SupplierRep",))
def settle_chargeback(body, lot_id):
    lot = resolve_lot(lot_id)
    payment_amount_cents = req_int(body, "payment_amount_cents", minimum=0)

    if lot["chargeback_status"] != "ASSESSED":
        fail("ERR_CHARGEBACK_STATE_INVALID")
    supplier = services.lot_supplier(lot)
    if payment_amount_cents != supplier["chargeback_outstanding_cents"]:
        fail("ERR_SETTLEMENT_AMOUNT_MISMATCH")

    amount = lot["chargeback_assessed_cents"]
    lot["chargeback_status"] = "SETTLED"
    touch(lot)
    supplier["chargeback_outstanding_cents"] -= amount
    supplier["chargeback_settled_cents"] += amount
    touch(supplier)
    return obj_result(serializers.lot, lot)


@route("/lots/<lot_id>/reverse-chargeback", methods=["POST"], roles=("ComplianceOfficer",))
def reverse_chargeback(body, lot_id):
    lot = resolve_lot(lot_id)
    # The note is required by the contract but SupplierLot has no field for it.
    req_str(body, "reversal_note")

    if lot["chargeback_status"] != "ASSESSED":
        fail("ERR_CHARGEBACK_STATE_INVALID")

    amount = lot["chargeback_assessed_cents"]
    lot["chargeback_status"] = "REVERSED"
    touch(lot)
    supplier = services.lot_supplier(lot)
    if supplier is not None:
        supplier["chargeback_outstanding_cents"] -= amount
        supplier["chargeback_reversed_cents"] += amount
        touch(supplier)
        services.recompute_supplier_indices(supplier)
    return obj_result(serializers.lot, lot)
