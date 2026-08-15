"""ImportDocument, InspectionHold, SubstitutionApproval: compliance overlay."""
from decimal import Decimal

from flask import Blueprint

from db import store, new_record, touch, now
from errors import (
    ApiError,
    ERR_IMPORT_DOC_NOT_FOUND,
    ERR_HOLD_NOT_FOUND,
    ERR_SUBSTITUTION_NOT_FOUND,
    ERR_TICKET_NOT_FOUND,
    ERR_SPECIES_NOT_FOUND,
    ERR_LOT_NOT_FOUND,
    ERR_ORDER_LINE_NOT_FOUND,
    ERR_IMPORT_DOC_INVALID_STATE,
    ERR_HOLD_INVALID_STATE,
    ERR_SUBSTITUTION_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    ERR_LOT_INVALID_STATE,
    ERR_HOLD_ALREADY_ACTIVE,
    ERR_SUBSTITUTION_NOT_ALLOWED,
    ERR_SUBSTITUTION_GROUP_MISMATCH,
    ERR_SUBSTITUTION_PRICE_INCREASE,
    ERR_QUOTE_NOT_PUBLISHED,
    ERR_LABELING_NONCOMPLIANT,
    ERR_ORDER_INVALID_STATE,
)
from middleware import auth, require
from response import ok, ok_list
from services.calc import cents, standing_quote
from services.cascades import (
    condemn_lot,
    deplete_check,
    post_release_epilogue,
    recompute_exposure,
)
from util import body, req_str, req_enum, apply_filters

bp = Blueprint("compliance", __name__)

DOC_TYPES = {"HEALTH_CERT", "CITES", "CUSTOMS_ENTRY"}


def _get_doc(rid):
    rec = store.import_docs.get(rid)
    if rec is None:
        raise ApiError(ERR_IMPORT_DOC_NOT_FOUND, 404, "ImportDocument id does not exist")
    return rec


def _get_hold(rid):
    rec = store.holds.get(rid)
    if rec is None:
        raise ApiError(ERR_HOLD_NOT_FOUND, 404, "InspectionHold id does not exist")
    return rec


def _get_substitution(rid):
    rec = store.substitutions.get(rid)
    if rec is None:
        raise ApiError(ERR_SUBSTITUTION_NOT_FOUND, 404, "SubstitutionApproval id does not exist")
    return rec


# ---------------------------------------------------------------------------
# ImportDocument
# ---------------------------------------------------------------------------
@bp.post("/import-documents")
def create_import_doc():
    _, role = auth()
    require(role, {"ComplianceOfficer"})
    b = body()
    dock_ticket_id = req_str(b, "dock_ticket_id")
    species_id = req_str(b, "species_id")
    doc_type = req_enum(b, "doc_type", DOC_TYPES)
    reference_number = req_str(b, "reference_number")
    # Body FK resolution order: species_id before dock_ticket_id.
    if species_id not in store.species:
        raise ApiError(ERR_SPECIES_NOT_FOUND, 404, "Species id does not exist")
    if dock_ticket_id not in store.tickets:
        raise ApiError(ERR_TICKET_NOT_FOUND, 404, "DockTicket id does not exist")
    rec = new_record({
        "dock_ticket_id": dock_ticket_id,
        "species_id": species_id,
        "doc_type": doc_type,
        "reference_number": reference_number,
        "status": "DRAFT",
        "submitted_by_user_id": "",
        "reviewed_by_user_id": "",
        "resubmit_count": 0,
    })
    store.import_docs[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/import-documents")
def list_import_docs():
    auth()
    page, total, limit, offset = apply_filters(
        list(store.import_docs.values()),
        ["dock_ticket_id", "species_id", "status"],
    )
    return ok_list(page, total, limit, offset)


@bp.get("/import-documents/<rid>")
def get_import_doc(rid):
    auth()
    return ok(_get_doc(rid))


@bp.post("/import-documents/<rid>/submit")
def submit_import_doc(rid):
    uid, role = auth()
    require(role, {"ComplianceOfficer"})
    doc = _get_doc(rid)
    if doc["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError(
            ERR_IMPORT_DOC_INVALID_STATE, 409,
            "Document is not in DRAFT or REJECTED",
        )
    if doc["status"] == "REJECTED":
        doc["resubmit_count"] += 1
    doc["status"] = "SUBMITTED"
    doc["submitted_by_user_id"] = uid
    touch(doc)
    return ok(doc)


@bp.post("/import-documents/<rid>/clear")
def clear_import_doc(rid):
    uid, role = auth()
    require(role, {"ComplianceOfficer"})
    doc = _get_doc(rid)
    if doc["status"] != "SUBMITTED":
        raise ApiError(ERR_IMPORT_DOC_INVALID_STATE, 409, "Document is not in SUBMITTED")
    if uid == doc["submitted_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES_VIOLATION, 403,
            "Clearing officer must differ from the submitter",
        )
    doc["status"] = "CLEARED"
    doc["reviewed_by_user_id"] = uid
    touch(doc)
    return ok(doc)


@bp.post("/import-documents/<rid>/reject")
def reject_import_doc(rid):
    _, role = auth()
    require(role, {"ComplianceOfficer"})
    doc = _get_doc(rid)
    if doc["status"] != "SUBMITTED":
        raise ApiError(ERR_IMPORT_DOC_INVALID_STATE, 409, "Document is not in SUBMITTED")
    doc["status"] = "REJECTED"
    touch(doc)
    return ok(doc)


# ---------------------------------------------------------------------------
# InspectionHold
# ---------------------------------------------------------------------------
@bp.post("/inspection-holds")
def create_hold():
    uid, role = auth()
    require(role, {"ComplianceOfficer"})
    b = body()
    inventory_lot_id = req_str(b, "inventory_lot_id")
    reason = req_str(b, "reason")
    lot = store.lots.get(inventory_lot_id)
    if lot is None:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "InventoryLot id does not exist")
    if lot["lifecycle_status"] != "ACTIVE" or lot["hold_status"] != "CLEAR":
        raise ApiError(
            ERR_LOT_INVALID_STATE, 409,
            "Lot is not ACTIVE with a CLEAR hold dimension",
        )
    if any(h["inventory_lot_id"] == lot["id"] and h["status"] == "PLACED" for h in store.holds.values()):
        raise ApiError(ERR_HOLD_ALREADY_ACTIVE, 409, "A PLACED hold already exists for this lot")
    rec = new_record({
        "inventory_lot_id": lot["id"],
        "reason": reason,
        "status": "PLACED",
        "placed_by_user_id": uid,
        "resolved_by_user_id": "",
        "placed_at": now(),
        "resolved_at": None,
    })
    store.holds[rec["id"]] = rec
    lot["hold_status"] = "ON_HOLD"
    touch(lot)
    return ok(rec, 201)


@bp.get("/inspection-holds")
def list_holds():
    auth()
    page, total, limit, offset = apply_filters(
        list(store.holds.values()),
        ["inventory_lot_id", "status"],
    )
    return ok_list(page, total, limit, offset)


@bp.get("/inspection-holds/<rid>")
def get_hold(rid):
    auth()
    return ok(_get_hold(rid))


@bp.post("/inspection-holds/<rid>/release")
def release_hold(rid):
    uid, role = auth()
    require(role, {"ComplianceOfficer"})
    hold = _get_hold(rid)
    if hold["status"] != "PLACED":
        raise ApiError(ERR_HOLD_INVALID_STATE, 409, "Hold is not in PLACED")
    if uid == hold["placed_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES_VIOLATION, 403,
            "Releasing officer must differ from the placing officer",
        )
    hold["status"] = "RELEASED"
    hold["resolved_by_user_id"] = uid
    hold["resolved_at"] = now()
    touch(hold)
    lot = store.lots[hold["inventory_lot_id"]]
    lot["hold_status"] = "CLEAR"
    touch(lot)
    return ok(hold)


@bp.post("/inspection-holds/<rid>/condemn")
def condemn_hold(rid):
    uid, role = auth()
    require(role, {"ComplianceOfficer"})
    hold = _get_hold(rid)
    if hold["status"] != "PLACED":
        raise ApiError(ERR_HOLD_INVALID_STATE, 409, "Hold is not in PLACED")
    hold["status"] = "CONDEMNED"
    hold["resolved_by_user_id"] = uid
    hold["resolved_at"] = now()
    touch(hold)
    lot = store.lots[hold["inventory_lot_id"]]
    affected = condemn_lot(lot)
    # Lines recompute, orders regress, auto-substitution fires for shorted
    # lines that permit substitution; then the DEPLETED evaluation runs.
    post_release_epilogue(affected, fire_substitution=True)
    deplete_check(lot)
    touch(lot)
    return ok(hold)


# ---------------------------------------------------------------------------
# SubstitutionApproval
# ---------------------------------------------------------------------------
@bp.post("/substitution-approvals")
def create_substitution():
    uid, role = auth()
    require(role, {"InventoryPlanner"})
    b = body()
    order_line_id = req_str(b, "order_line_id")
    substitute_species_id = req_str(b, "substitute_species_id")
    line = store.order_lines.get(order_line_id)
    if line is None:
        raise ApiError(ERR_ORDER_LINE_NOT_FOUND, 404, "OrderLine id does not exist")
    if substitute_species_id not in store.species:
        raise ApiError(ERR_SPECIES_NOT_FOUND, 404, "Species id does not exist")
    if not line["allow_substitution"]:
        raise ApiError(
            ERR_SUBSTITUTION_NOT_ALLOWED, 422,
            "Order line has allow_substitution == false",
        )
    rec = new_record({
        "order_line_id": order_line_id,
        "original_species_id": line["species_id"],
        "substitute_species_id": substitute_species_id,
        "status": "REQUESTED",
        "price_credit_cents": 0,
        "auto_created": False,
        "requested_by_user_id": uid,
        "decided_by_user_id": "",
    })
    store.substitutions[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/substitution-approvals")
def list_substitutions():
    auth()
    page, total, limit, offset = apply_filters(
        list(store.substitutions.values()),
        ["order_line_id", "original_species_id", "substitute_species_id", "status"],
    )
    return ok_list(page, total, limit, offset)


@bp.get("/substitution-approvals/<rid>")
def get_substitution(rid):
    auth()
    return ok(_get_substitution(rid))


@bp.post("/substitution-approvals/<rid>/approve")
def approve_substitution(rid):
    uid, role = auth()
    require(role, {"ComplianceOfficer"})
    rec = _get_substitution(rid)
    if rec["status"] != "REQUESTED":
        raise ApiError(ERR_SUBSTITUTION_INVALID_STATE, 409, "Record is not in REQUESTED")
    line = store.order_lines[rec["order_line_id"]]
    original = store.species[rec["original_species_id"]]
    substitute = store.species[rec["substitute_species_id"]]
    # The three approval rules in the PRD 3.8 narrative order: group, price,
    # labeling/CITES.
    if substitute["substitution_group"] != original["substitution_group"]:
        raise ApiError(
            ERR_SUBSTITUTION_GROUP_MISMATCH, 422,
            "Substitute species is not in the original's substitution_group",
        )
    quote = standing_quote(substitute["id"], line["requested_grade"])
    if quote is None:
        raise ApiError(
            ERR_QUOTE_NOT_PUBLISHED, 422,
            "No PUBLISHED quote resolvable for the substitute species and grade",
        )
    if quote["price_per_kg_cents"] > line["unit_price_cents"]:
        raise ApiError(
            ERR_SUBSTITUTION_PRICE_INCREASE, 422,
            "Substitute's standing price exceeds the line's locked unit price",
        )
    if substitute["requires_cites"]:
        cleared = any(
            d["species_id"] == substitute["id"]
            and d["doc_type"] == "CITES"
            and d["status"] == "CLEARED"
            for d in store.import_docs.values()
        )
        if not cleared:
            raise ApiError(
                ERR_LABELING_NONCOMPLIANT, 422,
                "Substitute requires CITES but no CLEARED CITES document exists",
            )
    rec["status"] = "APPROVED"
    rec["decided_by_user_id"] = uid
    touch(rec)
    return ok(rec)


@bp.post("/substitution-approvals/<rid>/reject")
def reject_substitution(rid):
    uid, role = auth()
    require(role, {"ComplianceOfficer"})
    rec = _get_substitution(rid)
    if rec["status"] != "REQUESTED":
        raise ApiError(ERR_SUBSTITUTION_INVALID_STATE, 409, "Record is not in REQUESTED")
    rec["status"] = "REJECTED"
    rec["decided_by_user_id"] = uid
    touch(rec)
    return ok(rec)


@bp.post("/substitution-approvals/<rid>/apply")
def apply_substitution(rid):
    _, role = auth()
    require(role, {"InventoryPlanner"})
    rec = _get_substitution(rid)
    if rec["status"] != "APPROVED":
        raise ApiError(ERR_SUBSTITUTION_INVALID_STATE, 409, "Record is not in APPROVED")
    line = store.order_lines[rec["order_line_id"]]
    order = store.orders[line["sales_order_id"]]
    if order["status"] != "CONFIRMED":
        raise ApiError(ERR_ORDER_INVALID_STATE, 409, "Order is not in CONFIRMED")
    customer = store.customers[order["customer_id"]]
    quote = standing_quote(rec["substitute_species_id"], line["requested_grade"])
    if quote is None:
        raise ApiError(
            ERR_QUOTE_NOT_PUBLISHED, 422,
            "No PUBLISHED quote resolvable for the substitute species and grade",
        )
    new_unit = quote["price_per_kg_cents"]
    old_unit = line["unit_price_cents"]
    credit = cents(Decimal(old_unit - new_unit) * line["requested_qty_kg"])
    line["species_id"] = rec["substitute_species_id"]
    line["unit_price_cents"] = new_unit
    line["line_total_cents"] = cents(
        line["requested_qty_kg"] * new_unit * (Decimal("1") - customer["discount_pct"])
    )
    touch(line)
    order["total_cents"] -= credit
    touch(order)
    rec["price_credit_cents"] = credit
    rec["status"] = "APPLIED"
    touch(rec)
    recompute_exposure(customer)
    return ok(rec)
