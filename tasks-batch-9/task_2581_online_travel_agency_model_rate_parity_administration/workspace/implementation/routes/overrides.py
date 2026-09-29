"""Negotiated commission and markup overrides (PRD 3.3)."""
from flask import Blueprint

import auth
import calc
import cascade
import response
import store
import validate
from errors import ApiError
from store import db, touch

from routes import common

bp = Blueprint("overrides", __name__)

TYPES = ("COMMISSION_PCT", "MARKUP_PCT", "FLAT_FEE_CENTS")
STATUSES = ("PROPOSED", "ACTIVE", "REJECTED", "REVOKED", "EXPIRED")


@bp.post("/commission-overrides")
def create_override():
    actor = auth.authenticate(("CommercialManager",))
    data = validate.body()
    raw_supplier = data.get("supplier_id")
    if isinstance(raw_supplier, str) and raw_supplier:
        common.find("suppliers", raw_supplier)
    raw_plan = data.get("rate_plan_id")
    if isinstance(raw_plan, str) and raw_plan:
        common.find("rate_plans", raw_plan)
    supplier_id = validate.str_req(data, "supplier_id")
    rate_plan_id = validate.id_opt(data, "rate_plan_id")
    override_type = validate.enum_req(data, "override_type", TYPES)
    value = validate.num_req(data, "value", 0)
    effective_from = validate.date_req(data, "effective_from")
    effective_to = validate.date_req(data, "effective_to")
    justification = validate.str_req(data, "justification")
    supplier = db["suppliers"][supplier_id]
    common.guard_offboarded(supplier)
    override = store.new_row("overrides", {
        "supplier_id": supplier_id,
        "rate_plan_id": rate_plan_id,
        "override_type": override_type,
        "value": value,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "justification": justification,
        "status": "PROPOSED",
        "proposed_by_user_id": actor.user_id,
        "approved_by_user_id": None,
        "rejection_reason": None,
    })
    return response.obj(override, 201)


@bp.get("/commission-overrides/<override_id>")
def read_override(override_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("overrides", override_id), 200)


@bp.get("/commission-overrides")
def list_overrides():
    auth.authenticate(auth.ALL_ROLES)
    supplier_id = validate.filter_str("supplier_id")
    rate_plan_id = validate.filter_str("rate_plan_id")
    status = validate.filter_enum("status", STATUSES)
    override_type = validate.filter_enum("override_type", TYPES)
    rows = []
    for row in db["overrides"].values():
        if supplier_id is not None and row["supplier_id"] != supplier_id:
            continue
        if rate_plan_id is not None and row["rate_plan_id"] != rate_plan_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if override_type is not None and row["override_type"] != override_type:
            continue
        rows.append(row)
    return common.paged(rows)


def _reprice_pending(override):
    """PRD §3.3: activation reprices every PENDING offer inside the override's scope."""
    for offer in sorted(db["offers"].values(), key=lambda r: r["_seq"]):
        if offer["status"] != "PENDING":
            continue
        plan = db["rate_plans"].get(offer["rate_plan_id"])
        if plan is None or plan["supplier_id"] != override["supplier_id"]:
            continue
        if override["rate_plan_id"] is not None and override["rate_plan_id"] != plan["id"]:
            continue
        if not (override["effective_from"] <= offer["travel_date"] <= override["effective_to"]):
            continue
        agreement = calc.active_agreement_for_date(plan["supplier_id"], offer["travel_date"])
        if agreement is None:
            continue
        offer.update(calc.price_offer(plan, agreement, offer["travel_date"],
                                     offer["net_rate_cents"]))
        touch(offer)


@bp.post("/commission-overrides/<override_id>/approve")
def approve(override_id):
    actor = auth.authenticate(("ComplianceOfficer",))
    override = common.find("overrides", override_id)
    data = validate.body()
    validate.str_opt(data, "note")
    common.guard_offboarded(db["suppliers"].get(override["supplier_id"]))
    if override["status"] != "PROPOSED":
        raise ApiError("ERR_OVERRIDE_NOT_PENDING")
    auth.require_distinct(actor, override["proposed_by_user_id"])
    agreement = calc.active_agreement_for_date(override["supplier_id"],
                                               override["effective_from"])
    if agreement is None:
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE",
                       "No ACTIVE model agreement covers effective_from.")
    if not calc._override_compatible(override["override_type"], agreement["model"]):
        raise ApiError("ERR_OVERRIDE_MODEL_MISMATCH")
    override["status"] = "ACTIVE"
    override["approved_by_user_id"] = actor.user_id
    touch(override)
    _reprice_pending(override)
    return response.obj(override, 200)


@bp.post("/commission-overrides/<override_id>/reject")
def reject(override_id):
    actor = auth.authenticate(("ComplianceOfficer",))
    override = common.find("overrides", override_id)
    data = validate.body()
    reason = validate.str_req(data, "rejection_reason")
    common.guard_offboarded(db["suppliers"].get(override["supplier_id"]))
    if override["status"] not in ("PROPOSED", "ACTIVE"):
        raise ApiError("ERR_OVERRIDE_NOT_PENDING")
    auth.require_distinct(actor, override["proposed_by_user_id"])
    override["status"] = "REJECTED" if override["status"] == "PROPOSED" else "REVOKED"
    override["rejection_reason"] = reason
    touch(override)
    return response.obj(override, 200)
