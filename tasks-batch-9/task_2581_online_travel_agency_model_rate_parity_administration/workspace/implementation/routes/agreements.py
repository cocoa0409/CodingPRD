"""ModelAgreement: the merchant-versus-agency contract (PRD 3.2)."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import response
import store
import validate
from errors import ApiError
from store import created_key, db, touch

from routes import common

bp = Blueprint("agreements", __name__)

MODELS = ("MERCHANT", "AGENCY")
STATUSES = ("DRAFT", "ACTIVE", "SUPERSEDED", "TERMINATED", "WITHDRAWN")


def _end(agreement):
    return agreement.get("effective_to") or calc.OPEN_ENDED


@bp.post("/suppliers/<supplier_id>/model-agreements")
def create_agreement(supplier_id):
    actor = auth.authenticate(("CommercialManager",))
    supplier = common.find("suppliers", supplier_id)
    data = validate.body()
    model = validate.enum_req(data, "model", MODELS)
    effective_from = validate.date_req(data, "effective_from")
    effective_to = validate.date_opt(data, "effective_to")
    commission = validate.num_opt(data, "base_commission_pct", None, 0, 0.5)
    markup = validate.num_opt(data, "base_markup_pct", None, 0, 0.5)
    liability = validate.num_req(data, "chargeback_liability_pct_marketplace", 0, 1)
    fraud_cap = validate.int_req(data, "fraud_liability_cap_cents", minimum=0)
    settlement_days = validate.int_req(data, "settlement_terms_days", 1, 90)
    if model == "AGENCY":
        if commission is None or markup is not None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "An AGENCY agreement requires base_commission_pct and no base_markup_pct.")
    else:
        if markup is None or commission is not None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "A MERCHANT agreement requires base_markup_pct and no base_commission_pct.")
    if effective_to is not None and effective_to < effective_from:
        raise ApiError("ERR_INVALID_REQUEST", "effective_to must not precede effective_from.")
    common.guard_offboarded(supplier)
    agreement = store.new_row("model_agreements", {
        "supplier_id": supplier["id"],
        "model": model,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "base_commission_pct": commission,
        "base_markup_pct": markup,
        "chargeback_liability_pct_marketplace": liability,
        "fraud_liability_cap_cents": fraud_cap,
        "settlement_terms_days": settlement_days,
        "status": "DRAFT",
        "activated_at": None,
        "termination_reason": None,
        "proposed_by_user_id": actor.user_id,
        "activated_by_user_id": None,
    })
    return response.obj(agreement, 201)


@bp.get("/model-agreements/<agreement_id>")
def read_agreement(agreement_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("model_agreements", agreement_id), 200)


@bp.get("/model-agreements")
def list_agreements():
    auth.authenticate(auth.ALL_ROLES)
    supplier_id = validate.filter_str("supplier_id")
    model = validate.filter_enum("model", MODELS)
    status = validate.filter_enum("status", STATUSES)
    rows = []
    for row in db["model_agreements"].values():
        if supplier_id is not None and row["supplier_id"] != supplier_id:
            continue
        if model is not None and row["model"] != model:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return common.paged(rows, key=lambda r: (r["effective_from"], created_key(r)))


@bp.post("/model-agreements/<agreement_id>/activate")
def activate(agreement_id):
    actor = auth.authenticate(("ComplianceOfficer",))
    agreement = common.find("model_agreements", agreement_id)
    data = validate.body()
    validate.str_opt(data, "note")
    supplier = db["suppliers"].get(agreement["supplier_id"])
    if agreement["status"] != "DRAFT":
        raise ApiError("ERR_AGREEMENT_NOT_DRAFT")
    common.guard_offboarded(supplier)
    auth.require_distinct(actor, agreement.get("proposed_by_user_id"))
    same_start = []
    cand_from = agreement["effective_from"]
    cand_to = _end(agreement)
    for row in db["model_agreements"].values():
        if row["id"] == agreement["id"] or row["supplier_id"] != agreement["supplier_id"]:
            continue
        if row["status"] != "ACTIVE":
            continue
        if row["effective_from"] == cand_from:
            same_start.append(row)     # the single exemption: superseded, not a conflict
            continue
        if cand_from <= _end(row) and row["effective_from"] <= cand_to:
            raise ApiError("ERR_MODEL_AGREEMENT_OVERLAP")
    agreement["status"] = "ACTIVE"
    agreement["activated_at"] = clock.now_iso()
    agreement["activated_by_user_id"] = actor.user_id
    touch(agreement)
    for row in sorted(same_start, key=lambda r: r["_seq"]):
        row["status"] = "SUPERSEDED"
        touch(row)
    if supplier is not None:
        cascade.recompute_current_model(supplier)
        touch(supplier)
    return response.obj(agreement, 200)


@bp.post("/model-agreements/<agreement_id>/terminate")
def terminate(agreement_id):
    auth.authenticate(("CommercialManager",))
    agreement = common.find("model_agreements", agreement_id)
    data = validate.body()
    reason = validate.str_req(data, "termination_reason")
    supplier = db["suppliers"].get(agreement["supplier_id"])
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE_STATE")
    common.guard_offboarded(supplier)
    agreement["status"] = "TERMINATED"
    agreement["termination_reason"] = reason
    touch(agreement)
    if supplier is not None:
        cascade.recompute_current_model(supplier)
        touch(supplier)
    return response.obj(agreement, 200)


@bp.post("/model-agreements/<agreement_id>/withdraw")
def withdraw(agreement_id):
    auth.authenticate(("CommercialManager",))
    agreement = common.find("model_agreements", agreement_id)
    data = validate.body()
    validate.str_opt(data, "note")
    if agreement["status"] != "DRAFT":
        raise ApiError("ERR_AGREEMENT_NOT_DRAFT")
    common.guard_offboarded(db["suppliers"].get(agreement["supplier_id"]))
    agreement["status"] = "WITHDRAWN"
    touch(agreement)
    return response.obj(agreement, 200)
