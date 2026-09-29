"""Forecast valuation, cascade chains and regulatory packet assembly."""

from decimal import Decimal

import constants as K
from db import db, base_entity, by_creation, now_logical, rhu, touch
from errors import fail
from services import costing, graph, ledger


# --- forecast valuation (§1.3 forecast_value) --------------------------------

def _approved_formula_exists(brief_id):
    for formula in db.formulas.values():
        if formula["brief_id"] == brief_id and formula["status"] == "APPROVED":
            return True
    return False


def _passed_test_exists(brief_id):
    formula_ids = set(f["id"] for f in db.formulas.values()
                      if f["brief_id"] == brief_id)
    lot_ids = set(l["id"] for l in db.lots.values()
                  if l["formula_id"] in formula_ids)
    for test in db.tests.values():
        if test["sample_lot_id"] in lot_ids and test["status"] == "PASSED":
            return True
    return False


def revalue_forecast(forecast, brief):
    base = Decimal(forecast["annual_volume_kg"]) * \
        Decimal(forecast["unit_price_cents_per_kg"])
    if brief["status"] == "CLOSED_WON":
        forecast["variant_applied"] = "COMMITTED"
        forecast["stage_probability"] = K.COMMITTED_FACTOR
        forecast["technical_factor"] = K.COMMITTED_FACTOR
        forecast["weighted_annual_value_cents"] = int(base)
        return
    if brief["status"] == "ACCEPTED":
        stage = K.STAGE_PROB_ACCEPTED
    elif brief["status"] == "SUBMITTED":
        stage = K.STAGE_PROB_SUBMITTED
    else:
        stage = K.STAGE_PROB_CLARIFICATION
    approved = _approved_formula_exists(brief["id"])
    if approved and _passed_test_exists(brief["id"]):
        technical = K.TECH_FACTOR_TESTED
    elif approved:
        technical = K.TECH_FACTOR_APPROVED
    else:
        technical = K.TECH_FACTOR_BENCH
    forecast["variant_applied"] = "RISK_WEIGHTED"
    forecast["stage_probability"] = stage
    forecast["technical_factor"] = technical
    forecast["weighted_annual_value_cents"] = int(rhu(base * stage * technical, 0))


def recompute_live_forecasts(brief, statuses=("ACTIVE", "AT_RISK")):
    for forecast in ledger.forecasts_of_brief(brief["id"]):
        if forecast["status"] in statuses:
            revalue_forecast(forecast, brief)
            touch(forecast)


# --- the formula-left-APPROVED cascade (§3.5 / §3.7) ------------------------

def formula_left_approved(formula, rework_reason):
    """APPROVED -> REWORK_REQUIRED plus the four documented consequences."""
    formula["status"] = "REWORK_REQUIRED"
    formula["rework_reason"] = rework_reason
    formula["cost_stale"] = False
    touch(formula)

    for lot in ledger.lots_of_formula(formula["id"]):
        if lot["disposition_status"] != "RELEASED":
            continue
        lot["disposition_status"] = "HELD"
        touch(lot)
        for shipment in ledger.shipments_of_lot(lot["id"]):
            if shipment["status"] in ("DRAFT", "PACKET_ASSEMBLED"):
                shipment["status"] = "BLOCKED"
                shipment["block_reason"] = "LOT_HELD"
                touch(shipment)

    for batch in ledger.batches_of_formula(formula["id"]):
        if batch["status"] in ("REQUESTED", "TOLERANCE_SET", "PILOT_RUN"):
            batch["status"] = "CANCELLED"
            batch["cancellation_reason"] = "FORMULA_REWORK"
            touch(batch)

    brief = db.briefs.get(formula["brief_id"])
    if brief is not None:
        for forecast in ledger.forecasts_of_brief(brief["id"]):
            if forecast["status"] == "ACTIVE":
                forecast["status"] = "AT_RISK"
                revalue_forecast(forecast, brief)
                touch(forecast)


def cancel_batches_for_supersession(formula_id, reason,
                                    statuses=("REQUESTED", "TOLERANCE_SET"),
                                    exclude_batch_id=None):
    for batch in ledger.batches_of_formula(formula_id):
        if exclude_batch_id is not None and batch["id"] == exclude_batch_id:
            continue
        if batch["status"] in statuses:
            batch["status"] = "CANCELLED"
            batch["cancellation_reason"] = reason
            touch(batch)


# --- brief terminal cascades (§3.1) -----------------------------------------

ARCHIVABLE = ("DRAFT", "COSTED", "SUBMITTED", "REWORK_REQUIRED")


def archive_brief_formulas(brief):
    for formula in ledger.formulas_of_brief(brief["id"]):
        if formula["status"] in ARCHIVABLE:
            formula["status"] = "ARCHIVED"
            touch(formula)


def lapse_brief_forecasts(brief):
    for forecast in ledger.forecasts_of_brief(brief["id"]):
        if forecast["status"] in ("ACTIVE", "AT_RISK"):
            forecast["status"] = "LAPSED"
            touch(forecast)


def realize_brief_forecasts(brief):
    for forecast in ledger.forecasts_of_brief(brief["id"]):
        if forecast["status"] in ("ACTIVE", "AT_RISK"):
            forecast["status"] = "REALIZED"
            revalue_forecast(forecast, brief)
            touch(forecast)


def cancel_shipment(shipment, reason):
    shipment["status"] = "CANCELLED"
    shipment["cancellation_reason"] = reason
    touch(shipment)
    lot = db.lots.get(shipment["sample_lot_id"])
    if lot is not None:
        ledger.reconcile_lot(lot)


def cancel_live_brief_shipments(brief, reason):
    for shipment in ledger.shipments_of_brief(brief["id"]):
        if shipment["status"] in ("DRAFT", "PACKET_ASSEMBLED", "BLOCKED"):
            cancel_shipment(shipment, reason)


def reject_brief_cascade(brief):
    archive_brief_formulas(brief)
    lapse_brief_forecasts(brief)


# --- certificate cascades (§3.2) --------------------------------------------

def staleify_documents_for_record(record):
    for document in db.documents.values():
        if document.get("substantiation_id") != record["id"]:
            continue
        if document["status"] == "PINNED":
            document["status"] = "STALE"
            touch(document)


ELIGIBILITY_FLAG = {
    "NATURAL": "natural_claim_eligible",
    "KOSHER": "kosher_eligible",
    "HALAL": "halal_eligible",
}


def revocation_cascade(record):
    """LINK 2 -> LINK 4 plus the two fan-out branches."""
    material_id = record["raw_material_id"]
    claim_type = record["claim_type"]
    for formula in by_creation(list(db.formulas.values())):
        if formula["status"] != "APPROVED":
            continue
        if not graph.formula_contains_material(formula["id"], material_id):
            continue
        brief = db.briefs.get(formula["brief_id"])
        if brief is None:
            continue
        if claim_type not in graph.required_claim_set(brief):
            continue
        flag = ELIGIBILITY_FLAG.get(claim_type)
        if flag:
            formula[flag] = False
        formula_left_approved(formula, "SUBSTANTIATION_REVOKED")
    staleify_documents_for_record(record)


def reprice_cascade(material):
    """PATCH /raw-materials/{id} - re-cost every affected formula in place."""
    affected = [f for f in by_creation(list(db.formulas.values()))
                if f["status"] in ("COSTED", "SUBMITTED", "APPROVED")
                and graph.formula_contains_material(f["id"], material["id"])]
    for formula in affected:
        brief = db.briefs.get(formula["brief_id"])
        costing.apply_bench_cost(formula)
        if brief is not None:
            costing.apply_cost_in_use(formula, brief)
        if formula["status"] == "APPROVED":
            formula["cost_stale"] = True
        elif formula["status"] == "SUBMITTED":
            formula["status"] = "REWORK_REQUIRED"
            formula["rework_reason"] = "RAW_MATERIAL_REPRICED"
        touch(formula)


# --- regulatory packet (§1.3 regulatory_packet, §3.8) -----------------------

def required_document_types(shipment, formula, brief):
    types = ["SDS", "ALLERGEN_STATEMENT"]
    if brief.get("natural_claim_required"):
        types.append("NATURAL_DECLARATION")
    if brief.get("kosher_required"):
        types.append("KOSHER_CERT")
    if brief.get("halal_required"):
        types.append("HALAL_CERT")
    if shipment["destination_country"] != "US":
        types.append("EXPORT_DECLARATION")
    if formula["confidentiality_tier"] in ("TIER_2_RESTRICTED", "TIER_3_BLACK_BOX"):
        types.append("IP_NDA_ADDENDUM")
    return types


def _candidates(material_id, claim_type):
    clock = now_logical()
    rows = [r for r in db.records.values()
            if r["raw_material_id"] == material_id
            and r["claim_type"] == claim_type
            and r["status"] == "VERIFIED"
            and r["valid_until"] >= clock]
    return rows


def _select_pin(leaves, claim_type):
    pool = []
    for material_id in leaves:
        pool.extend(_candidates(material_id, claim_type))
    if not pool:
        return None
    pool.sort(key=lambda r: (r["valid_until"], r["created_at"], r["_ord"]))
    return pool[0]


def assemble_packet(shipment, formula, brief):
    types = required_document_types(shipment, formula, brief)
    leaves = graph.leaf_materials(formula["id"])

    # priority 72: every certificate-backed type needs a candidate on *every*
    # transitive leaf material.
    pins = {}
    for doc_type in types:
        claim_type = K.CERT_BACKED.get(doc_type)
        if claim_type is None:
            continue
        if not leaves:
            fail("ERR_DOC_PACKET_INCOMPLETE",
                 "formula has no leaf material for %s" % doc_type)
        for material_id in leaves:
            if not _candidates(material_id, claim_type):
                fail("ERR_DOC_PACKET_INCOMPLETE",
                     "material %s has no unexpired VERIFIED %s certificate"
                     % (material_id, claim_type))
        pins[doc_type] = _select_pin(leaves, claim_type)

    existing = {}
    for document in ledger.documents_of_shipment(shipment["id"]):
        existing[document["doc_type"]] = document

    clock = now_logical()
    validities = []
    for doc_type in K.DOC_TYPES:
        if doc_type not in types:
            continue
        record = pins.get(doc_type)
        document = existing.get(doc_type)
        if document is None:
            document = base_entity()
            document.update({
                "shipment_id": shipment["id"],
                "doc_type": doc_type,
                "substantiation_id": None,
                "pinned_substantiation_version": None,
                "pinned_valid_until": None,
                "status": "PINNED",
                "generated_at": clock,
            })
            db.documents[document["id"]] = document
        else:
            document["generated_at"] = clock
            touch(document)
        if record is not None:
            document["substantiation_id"] = record["id"]
            document["pinned_substantiation_version"] = record["version"]
            document["pinned_valid_until"] = record["valid_until"]
            validities.append(record["valid_until"])
        else:
            document["substantiation_id"] = None
            document["pinned_substantiation_version"] = None
            document["pinned_valid_until"] = None
        document["status"] = "PINNED"

    shipment["required_document_types"] = types
    shipment["packet_valid_until"] = min(validities) if validities else None
    return types
