"""Supplier, AuditRecord, Ingredient, and IngredientLot endpoints."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import store, now, new_id
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_INVALID_RANGE, ERR_DUPLICATE_CODE, ERR_AUDIT_TOO_OLD,
                    ERR_SUPPLIER_NOT_QUALIFIED, ERR_LOT_EXPIRED)
from middleware import authorized
from response import ok, paginate
from services import (ser_supplier, ser_audit, ser_ingredient, ser_lot, get_or_404,
                      stamp_new, touch, audit_result, compute_risk_rating,
                      cascade_supplier_suspended, cascade_supplier_reinstated,
                      cascade_supplier_disqualified, INGREDIENT_CATEGORIES,
                      RISK_CLASSES, STORAGE_CONDITIONS, AUDIT_TYPES)
from util import (get_body, require_fields, check_enum, check_enum_list,
                  check_int_range, parse_datetime, to_decimal, num)

bp = Blueprint("suppliers", __name__)

SUPPLIER_READ = ("QA_MANAGER", "QUALITY_ANALYST", "PRODUCTION_SUPERVISOR", "SUPPLY_CHAIN_PLANNER")
AUDIT_AGE_LIMIT_DAYS = 365


# ------------------------------------------------------------------ suppliers
@bp.post("/suppliers")
@authorized("QA_MANAGER")
def create_supplier(_user_id=None, _role=None):
    body = get_body()
    code = body.get("supplier_code")
    if isinstance(code, str) and code:
        if any(s["supplier_code"] == code for s in store.suppliers.values()):
            raise err(ERR_DUPLICATE_CODE, "supplier_code '%s' already exists" % code)
    require_fields(body, ["supplier_code", "legal_name", "ingredient_categories",
                          "audit_frequency_days"])
    if len(body["supplier_code"]) > 32:
        raise err(ERR_INVALID_REQUEST, "supplier_code must be at most 32 characters")
    cats = body["ingredient_categories"]
    if not isinstance(cats, list) or len(cats) == 0:
        raise err(ERR_INVALID_REQUEST, "ingredient_categories must contain at least one category")
    check_enum_list(cats, INGREDIENT_CATEGORIES, "ingredient_categories")
    freq = check_int_range(body["audit_frequency_days"], 30, 730, "audit_frequency_days")
    rec = stamp_new({
        "id": new_id(),
        "supplier_code": body["supplier_code"],
        "legal_name": body["legal_name"],
        "ingredient_categories": cats,
        "qualification_status": "PENDING_AUDIT",
        "last_audit_date": None,
        "audit_frequency_days": freq,
        "risk_rating": "HIGH",
        "_suspended_at": None,
    })
    store.suppliers[rec["id"]] = rec
    return ok(ser_supplier(rec), 201)


@bp.get("/suppliers")
@authorized(*SUPPLIER_READ)
def list_suppliers(_user_id=None, _role=None):
    records = list(store.suppliers.values())
    qs = request.args.get("qualification_status")
    if qs is not None:
        records = [s for s in records if s["qualification_status"] == qs]
    return paginate(records, ser_supplier)


@bp.get("/suppliers/<sid>")
@authorized(*SUPPLIER_READ)
def get_supplier(sid, _user_id=None, _role=None):
    return ok(ser_supplier(get_or_404(store.suppliers, sid, "Supplier")))


@bp.post("/suppliers/<sid>/suspend")
@authorized("QUALITY_ANALYST")
def suspend_supplier(sid, _user_id=None, _role=None):
    rec = get_or_404(store.suppliers, sid, "Supplier")
    if rec["qualification_status"] != "QUALIFIED":
        raise err(ERR_INVALID_STATE,
                  "Supplier in status %s cannot be suspended" % rec["qualification_status"])
    body = get_body()
    require_fields(body, ["reason"])
    rec["qualification_status"] = "SUSPENDED"
    rec["_suspended_at"] = now()
    touch(rec)
    cascade_supplier_suspended(rec)
    return ok(ser_supplier(rec))


@bp.post("/suppliers/<sid>/reinstate")
@authorized("QUALITY_ANALYST")
def reinstate_supplier(sid, _user_id=None, _role=None):
    rec = get_or_404(store.suppliers, sid, "Supplier")
    if rec["qualification_status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE,
                  "Supplier in status %s cannot be reinstated" % rec["qualification_status"])
    body = get_body()
    require_fields(body, ["audit_record_id"])
    audit = store.audits.get(body["audit_record_id"])
    if audit is None:
        raise err(ERR_NOT_FOUND, "AuditRecord '%s' does not exist" % body["audit_record_id"])
    if audit["supplier_id"] != rec["id"]:
        raise err(ERR_INVALID_REQUEST, "Audit record does not belong to this supplier")
    if audit["result"] != "PASS":
        raise err(ERR_INVALID_STATE,
                  "Reinstatement requires an audit with result PASS")
    suspended_at = rec.get("_suspended_at")
    if suspended_at is not None and audit["created_at"] < suspended_at:
        raise err(ERR_INVALID_STATE,
                  "Reinstatement audit must be submitted after the suspension")
    rec["qualification_status"] = "QUALIFIED"
    rec["last_audit_date"] = audit["audit_date"]
    rec["risk_rating"] = compute_risk_rating(audit["score"], audit["audit_date"])
    rec["_suspended_at"] = None
    touch(rec)
    cascade_supplier_reinstated(rec)
    return ok(ser_supplier(rec))


@bp.post("/suppliers/<sid>/disqualify")
@authorized("QA_MANAGER")
def disqualify_supplier(sid, _user_id=None, _role=None):
    rec = get_or_404(store.suppliers, sid, "Supplier")
    if rec["qualification_status"] not in ("PENDING_AUDIT", "SUSPENDED"):
        raise err(ERR_INVALID_STATE,
                  "Supplier in status %s cannot be disqualified" % rec["qualification_status"])
    body = get_body()
    require_fields(body, ["rationale"])
    rec["qualification_status"] = "DISQUALIFIED"
    touch(rec)
    cascade_supplier_disqualified(rec)
    return ok(ser_supplier(rec))


# ------------------------------------------------------------------ audits
@bp.post("/suppliers/<sid>/audits")
@authorized("QUALITY_ANALYST")
def create_audit(sid, _user_id=None, _role=None):
    supplier = get_or_404(store.suppliers, sid, "Supplier")
    body = get_body()
    audit_date = None
    if body.get("audit_date") is not None:
        audit_date = parse_datetime(body["audit_date"], "audit_date")
        if (now() - audit_date) > timedelta(days=AUDIT_AGE_LIMIT_DAYS):
            raise err(ERR_AUDIT_TOO_OLD,
                      "audit_date is more than 365 days in the past")
    require_fields(body, ["audit_type", "audit_date", "auditor_name", "score"])
    audit_type = check_enum(body["audit_type"], AUDIT_TYPES, "audit_type")
    score = to_decimal(body["score"], "score")
    if score < 0 or score > 100:
        raise err(ERR_INVALID_RANGE, "score must be between 0 and 100")
    score = score.quantize(Decimal("0.01"))
    findings = body.get("findings", [])
    if not isinstance(findings, list):
        raise err(ERR_INVALID_REQUEST, "findings must be an array")
    capa_deadline = None
    if body.get("capa_deadline") is not None:
        capa_deadline = parse_datetime(body["capa_deadline"], "capa_deadline")
    result = audit_result(score, findings)
    rec = stamp_new({
        "id": new_id(),
        "supplier_id": supplier["id"],
        "audit_type": audit_type,
        "audit_date": audit_date,
        "auditor_name": body["auditor_name"],
        "score": score,
        "findings": findings,
        "capa_deadline": capa_deadline,
        "result": result,
    })
    store.audits[rec["id"]] = rec
    # Qualification side effects
    if result in ("PASS", "CONDITIONAL_PASS"):
        if supplier["qualification_status"] == "PENDING_AUDIT":
            supplier["qualification_status"] = "QUALIFIED"
            supplier["last_audit_date"] = audit_date
            supplier["risk_rating"] = compute_risk_rating(score, audit_date)
            touch(supplier)
        elif supplier["qualification_status"] == "QUALIFIED":
            supplier["last_audit_date"] = audit_date
            supplier["risk_rating"] = compute_risk_rating(score, audit_date)
            touch(supplier)
    return ok(ser_audit(rec), 201)


@bp.get("/suppliers/<sid>/audits")
@authorized("QA_MANAGER", "QUALITY_ANALYST")
def list_audits(sid, _user_id=None, _role=None):
    get_or_404(store.suppliers, sid, "Supplier")
    records = [a for a in store.audits.values() if a["supplier_id"] == sid]
    return paginate(records, ser_audit)


@bp.get("/audit-records/<aid>")
@authorized("QA_MANAGER", "QUALITY_ANALYST")
def get_audit(aid, _user_id=None, _role=None):
    return ok(ser_audit(get_or_404(store.audits, aid, "AuditRecord")))


# ------------------------------------------------------------------ ingredients
@bp.post("/ingredients")
@authorized("QA_MANAGER")
def create_ingredient(_user_id=None, _role=None):
    body = get_body()
    code = body.get("ingredient_code")
    if isinstance(code, str) and code:
        if any(i["ingredient_code"] == code for i in store.ingredients.values()):
            raise err(ERR_DUPLICATE_CODE, "ingredient_code '%s' already exists" % code)
    require_fields(body, ["ingredient_code", "ingredient_name", "category",
                          "pathogen_risk_class", "storage_condition"])
    category = check_enum(body["category"], INGREDIENT_CATEGORIES, "category")
    risk = check_enum(body["pathogen_risk_class"], RISK_CLASSES, "pathogen_risk_class")
    storage = check_enum(body["storage_condition"], STORAGE_CONDITIONS, "storage_condition")
    allergens = body.get("allergen_flags", [])
    if not isinstance(allergens, list):
        raise err(ERR_INVALID_REQUEST, "allergen_flags must be an array")
    rec = stamp_new({
        "id": new_id(),
        "ingredient_code": body["ingredient_code"],
        "ingredient_name": body["ingredient_name"],
        "category": category,
        "pathogen_risk_class": risk,
        "storage_condition": storage,
        "allergen_flags": allergens,
    })
    store.ingredients[rec["id"]] = rec
    return ok(ser_ingredient(rec), 201)


@bp.get("/ingredients")
@authorized(*SUPPLIER_READ)
def list_ingredients(_user_id=None, _role=None):
    records = list(store.ingredients.values())
    cat = request.args.get("category")
    if cat is not None:
        records = [i for i in records if i["category"] == cat]
    return paginate(records, ser_ingredient)


@bp.get("/ingredients/<iid>")
@authorized(*SUPPLIER_READ)
def get_ingredient(iid, _user_id=None, _role=None):
    return ok(ser_ingredient(get_or_404(store.ingredients, iid, "Ingredient")))


@bp.get("/ingredients/<iid>/lots")
@authorized(*SUPPLIER_READ)
def list_ingredient_lots(iid, _user_id=None, _role=None):
    get_or_404(store.ingredients, iid, "Ingredient")
    records = [l for l in store.lots.values() if l["ingredient_id"] == iid]
    qc = request.args.get("qc_status")
    if qc is not None:
        records = [l for l in records if l["qc_status"] == qc]
    return paginate(records, ser_lot)


# ------------------------------------------------------------------ ingredient lots
@bp.post("/ingredient-lots")
@authorized("SUPPLY_CHAIN_PLANNER")
def create_lot(_user_id=None, _role=None):
    body = get_body()
    ingredient = None
    supplier = None
    if body.get("ingredient_id") is not None:
        ingredient = get_or_404(store.ingredients, body["ingredient_id"], "Ingredient")
    if body.get("supplier_id") is not None:
        supplier = get_or_404(store.suppliers, body["supplier_id"], "Supplier")
    require_fields(body, ["ingredient_id", "supplier_id", "lot_number", "quantity_kg",
                          "received_date", "expiry_date"])
    qty = to_decimal(body["quantity_kg"], "quantity_kg")
    if qty <= 0:
        raise err(ERR_INVALID_RANGE, "quantity_kg must be greater than 0")
    qty = qty.quantize(Decimal("0.001"))
    # lot_number unique per (ingredient_id, supplier_id)
    for l in store.lots.values():
        if l["ingredient_id"] == ingredient["id"] and l["supplier_id"] == supplier["id"] \
                and l["lot_number"] == body["lot_number"]:
            raise err(ERR_DUPLICATE_CODE,
                      "lot_number '%s' already exists for this ingredient and supplier"
                      % body["lot_number"])
    rec = stamp_new({
        "id": new_id(),
        "ingredient_id": ingredient["id"],
        "supplier_id": supplier["id"],
        "lot_number": body["lot_number"],
        "quantity_kg": qty,
        "remaining_kg": qty,
        "received_date": parse_datetime(body["received_date"], "received_date"),
        "expiry_date": parse_datetime(body["expiry_date"], "expiry_date"),
        "qc_status": "PENDING_QC",
    })
    store.lots[rec["id"]] = rec
    return ok(ser_lot(rec), 201)


@bp.get("/ingredient-lots")
@authorized(*SUPPLIER_READ)
def list_lots(_user_id=None, _role=None):
    records = list(store.lots.values())
    for param, field in (("ingredient_id", "ingredient_id"),
                         ("supplier_id", "supplier_id"),
                         ("qc_status", "qc_status")):
            v = request.args.get(param)
            if v is not None:
                records = [l for l in records if l[field] == v]
    return paginate(records, ser_lot)


@bp.get("/ingredient-lots/<lid>")
@authorized(*SUPPLIER_READ)
def get_lot(lid, _user_id=None, _role=None):
    return ok(ser_lot(get_or_404(store.lots, lid, "IngredientLot")))


@bp.get("/suppliers/<sid>/lots")
@authorized(*SUPPLIER_READ)
def list_supplier_lots(sid, _user_id=None, _role=None):
    get_or_404(store.suppliers, sid, "Supplier")
    records = [l for l in store.lots.values() if l["supplier_id"] == sid]
    qc = request.args.get("qc_status")
    if qc is not None:
        records = [l for l in records if l["qc_status"] == qc]
    return paginate(records, ser_lot)


@bp.post("/ingredient-lots/<lid>/qc-pass")
@authorized("QUALITY_ANALYST")
def qc_pass_lot(lid, _user_id=None, _role=None):
    rec = get_or_404(store.lots, lid, "IngredientLot")
    if rec["qc_status"] != "PENDING_QC":
        raise err(ERR_INVALID_STATE,
                  "IngredientLot in status %s cannot be QC passed" % rec["qc_status"])
    supplier = store.suppliers.get(rec["supplier_id"])
    if supplier is None or supplier["qualification_status"] != "QUALIFIED":
        raise err(ERR_SUPPLIER_NOT_QUALIFIED,
                  "Supplier of this lot is not QUALIFIED")
    if not (rec["expiry_date"] > now()):
        raise err(ERR_LOT_EXPIRED, "Ingredient lot expiry_date is not after the current time")
    rec["qc_status"] = "QC_PASSED"
    touch(rec)
    return ok(ser_lot(rec))


@bp.post("/ingredient-lots/<lid>/qc-fail")
@authorized("QUALITY_ANALYST")
def qc_fail_lot(lid, _user_id=None, _role=None):
    rec = get_or_404(store.lots, lid, "IngredientLot")
    if rec["qc_status"] != "PENDING_QC":
        raise err(ERR_INVALID_STATE,
                  "IngredientLot in status %s cannot be QC failed" % rec["qc_status"])
    body = get_body()
    require_fields(body, ["failure_reason"])
    rec["qc_status"] = "QC_FAILED"
    touch(rec)
    return ok(ser_lot(rec))


@bp.post("/ingredient-lots/<lid>/quarantine")
@authorized("QUALITY_ANALYST")
def quarantine_lot(lid, _user_id=None, _role=None):
    rec = get_or_404(store.lots, lid, "IngredientLot")
    if rec["qc_status"] != "QC_PASSED":
        raise err(ERR_INVALID_STATE,
                  "IngredientLot in status %s cannot be quarantined" % rec["qc_status"])
    body = get_body()
    require_fields(body, ["reason"])
    rec["qc_status"] = "QUARANTINED"
    touch(rec)
    return ok(ser_lot(rec))


@bp.post("/ingredient-lots/<lid>/release-quarantine")
@authorized("QUALITY_ANALYST")
def release_quarantine_lot(lid, _user_id=None, _role=None):
    rec = get_or_404(store.lots, lid, "IngredientLot")
    if rec["qc_status"] != "QUARANTINED":
        raise err(ERR_INVALID_STATE,
                  "IngredientLot in status %s cannot be released from quarantine"
                  % rec["qc_status"])
    rec["qc_status"] = "QC_PASSED"
    touch(rec)
    return ok(ser_lot(rec))
