"""SemolinaLot endpoints: receipt (grading + settlement), lab results, disposition."""
from flask import Blueprint

import db
from db import new_common, new_id, num_out, store, touch
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, ok, paginate
from services.calc import semolina_grade, settlement_price
from services.cascades import lot_reject_cascade, sweep_contract
from validation import fk_exists, parse_body, raw_body, require_path_entity, validate_schema

bp = Blueprint("lots", __name__)

MOISTURE_SAFETY_CAP = db.dec("15.0")

_LOT_SCHEMA = {
    "contract_id": ("string", True, None),
    "delivery_date": ("date", True, None),
    "received_weight_kg": ("number", True, None),
    "cert_protein_pct": ("number", True, None),
    "cert_moisture_pct": ("number", True, None),
    "cert_gluten_index": ("number", True, None),
    "cert_falling_number_s": ("number", True, None),
}

_LAB_SCHEMA = {
    "lab_protein_pct": ("number", True, None),
    "lab_moisture_pct": ("number", True, None),
    "lab_gluten_index": ("number", True, None),
    "lab_falling_number_s": ("number", True, None),
}


@bp.post("/semolina-lots")
def create_lot():
    uid, role, _ = get_context()
    require_roles(["ProcurementManager"])
    body = raw_body()
    contract = fk_exists(store.contracts, body, "contract_id", "ERR_CONTRACT_NOT_FOUND")
    if contract is not None:
        sweep_contract(contract)
    validate_schema(body, _LOT_SCHEMA)
    if db.dec(body["received_weight_kg"]) <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "received_weight_kg must be > 0")
    delivery_date = db.parse_date(body["delivery_date"])
    # Temporal window rule (priority 9) precedes the referential ACTIVE rule (10).
    if not (contract["effective_start"] <= delivery_date <= contract["effective_end"]):
        raise ApiError("ERR_CONTRACT_WINDOW_INVALID", 409,
                       "delivery_date outside contract window (inclusive both ends)")
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409,
                       "Goods receipt requires an ACTIVE contract")
    cert_score, cert_grade = semolina_grade(
        body["cert_protein_pct"], body["cert_moisture_pct"],
        body["cert_gluten_index"], body["cert_falling_number_s"])
    unit_price, total_price = settlement_price(contract, delivery_date,
                                               body["received_weight_kg"])
    lot = {
        "id": new_id(),
        "contract_id": contract["id"],
        "delivery_date": delivery_date,
        "received_weight_kg": body["received_weight_kg"],
        "remaining_weight_kg": body["received_weight_kg"],
        "consumed_kg": 0,
        "cert_protein_pct": body["cert_protein_pct"],
        "cert_moisture_pct": body["cert_moisture_pct"],
        "cert_gluten_index": body["cert_gluten_index"],
        "cert_falling_number_s": body["cert_falling_number_s"],
        "lab_protein_pct": None,
        "lab_moisture_pct": None,
        "lab_gluten_index": None,
        "lab_falling_number_s": None,
        "cert_grade_score": num_out(cert_score),
        "cert_grade": cert_grade,
        "lab_grade_score": None,
        "lab_grade": None,
        "unit_price_cents": unit_price,
        "total_price_cents": total_price,
        "status": "QUARANTINED",
        "created_by_user_id": uid,
    }
    new_common(lot)
    store.semolina_lots[lot["id"]] = lot
    # Cumulative increases only AFTER pricing (pinned evaluation order).
    contract["cumulative_delivered_kg"] = num_out(
        db.dec(contract["cumulative_delivered_kg"]) + db.dec(body["received_weight_kg"]))
    touch(contract)
    return created(lot)


@bp.get("/semolina-lots")
def list_lots():
    get_context()
    require_roles(ALL_ROLES)
    rows = list(store.semolina_lots.values())
    rows = paginate.filter(rows, "contract_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/semolina-lots/<lot_id>")
def get_lot(lot_id):
    get_context()
    require_roles(ALL_ROLES)
    return ok(require_path_entity(store.semolina_lots, lot_id, "ERR_LOT_NOT_FOUND"))


@bp.post("/semolina-lots/<lot_id>/lab-results")
def submit_lab_results(lot_id):
    get_context()
    require_roles(["QATechnician"])
    lot = require_path_entity(store.semolina_lots, lot_id, "ERR_LOT_NOT_FOUND")
    body = parse_body(_LAB_SCHEMA, allow_empty=False)
    if lot["status"] not in ("QUARANTINED", "ACCEPTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Lab results require a QUARANTINED or ACCEPTED lot")
    lot["lab_protein_pct"] = body["lab_protein_pct"]
    lot["lab_moisture_pct"] = body["lab_moisture_pct"]
    lot["lab_gluten_index"] = body["lab_gluten_index"]
    lot["lab_falling_number_s"] = body["lab_falling_number_s"]
    score, grade = semolina_grade(
        body["lab_protein_pct"], body["lab_moisture_pct"],
        body["lab_gluten_index"], body["lab_falling_number_s"])
    lot["lab_grade_score"] = num_out(score)
    lot["lab_grade"] = grade
    if lot["status"] == "ACCEPTED":
        lot["status"] = "QUARANTINED"  # sanctioned retest loop
    touch(lot)
    return ok(lot)


@bp.post("/semolina-lots/<lot_id>/accept")
def accept_lot(lot_id):
    uid, role, _ = get_context()
    require_roles(["QAManager"])
    lot = require_path_entity(store.semolina_lots, lot_id, "ERR_LOT_NOT_FOUND")
    if uid == lot["created_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "Acceptor must differ from the receiving user")
    if lot["lab_grade"] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "No lab results recorded for this lot")
    if lot["status"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a QUARANTINED lot can be accepted")
    if db.dec(lot["lab_moisture_pct"]) > MOISTURE_SAFETY_CAP:
        raise ApiError("ERR_MOISTURE_CAP_EXCEEDED", 422,
                       "lab_moisture_pct exceeds the 15.0 safety cap")
    if lot["lab_grade"] == "GRADE_REJECT":
        raise ApiError("ERR_LOT_GRADE_BELOW_CONTRACT", 422,
                       "lab_grade is GRADE_REJECT")
    lot["status"] = "ACCEPTED"
    touch(lot)
    return ok(lot)


@bp.post("/semolina-lots/<lot_id>/reject")
def reject_lot(lot_id):
    get_context()
    require_roles(["QAManager"])
    lot = require_path_entity(store.semolina_lots, lot_id, "ERR_LOT_NOT_FOUND")
    if lot["status"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a QUARANTINED lot can be rejected")
    lot["status"] = "REJECTED"
    touch(lot)
    lot_reject_cascade(lot)
    return ok(lot)
