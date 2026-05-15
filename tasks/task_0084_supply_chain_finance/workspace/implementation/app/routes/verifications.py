"""Trade-background verification endpoints (PRD §3.9)."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..calculations import capital_goods_match
from ..constants import (
    AML_BLACKLIST_THRESHOLD,
    FRAUD_PENALTY,
    ON_SITE_THRESHOLD_CENTS,
    THIRD_PARTY_PASS_FLOOR,
)
from ..errors import api_error
from ..response import success_envelope
from ..services.cascades import cascade_blacklist_supplier
from ..store import store
from ..utils import (
    get_json_body,
    optional_int,
    optional_str,
    require_number,
    require_str,
)

bp = Blueprint("verifications", __name__, url_prefix="/scf/verifications")


# ---- POST /scf/verifications ----
@bp.post("")
@require_auth(["RiskReviewer"])
def open_verification():
    body = get_json_body()
    receivable_id = require_str(body, "receivable_id")
    waybill = optional_str(body, "waybill_doc_id", None)
    customs = optional_str(body, "customs_declaration_doc_id", None)
    third_party = require_number(body, "third_party_score")
    if third_party < 0.0 or third_party > 1.0:
        raise api_error("ERR_VALIDATION", "third_party_score must be in [0.00, 1.00]")
    # Allow round to 2dp
    third_party = round(third_party + 1e-9, 2)

    waybill_value = optional_int(body, "waybill_declared_value_cents", None)
    customs_value = optional_int(body, "customs_declared_value_cents", None)

    receivable = store.receivables.get(receivable_id)
    if receivable is None:
        raise api_error("ERR_REFERENCED_NOT_FOUND", "receivable_id not found")

    capital_cents = int(receivable.get("amount_cents", 0))

    # Compute capital_flow_match
    if waybill is None:
        # If no waybill doc supplied, default capital_flow_match to false
        capital_flow_match = False
    else:
        # If waybill_declared_value_cents was not supplied, default to capital
        # amount so that capital matches goods (deviation 0 bps).
        wval = capital_cents if waybill_value is None else int(waybill_value)
        waybill_ok = capital_goods_match(capital_cents, wval)
        if customs is None:
            capital_flow_match = waybill_ok
        else:
            cval = capital_cents if customs_value is None else int(customs_value)
            customs_ok = capital_goods_match(capital_cents, cval)
            capital_flow_match = waybill_ok and customs_ok

    on_site_required = capital_cents >= ON_SITE_THRESHOLD_CENTS

    with store.lock:
        payload = {
            "receivable_id": receivable_id,
            "waybill_doc_id": waybill,
            "customs_declaration_doc_id": customs,
            "capital_flow_match": capital_flow_match,
            "third_party_score": third_party,
            "on_site_required": on_site_required,
            "on_site_completed": False,
            "outcome": "INCONCLUSIVE",
        }
        store.stamp_event(payload)
        store.verifications[payload["id"]] = payload
    return success_envelope(payload, status=201)


# ---- POST /scf/verifications/{id}/on-site ----
@bp.post("/<vid>/on-site")
@require_auth(["RiskReviewer"])
def on_site_verification(vid):
    verif = store.verifications.get(vid)
    if verif is None:
        raise api_error("ERR_NOT_FOUND", "Verification not found")
    if verif.get("outcome") != "INCONCLUSIVE":
        raise api_error("ERR_INVALID_STATE", "Verification already finalized")
    with store.lock:
        verif["on_site_completed"] = True
    return success_envelope(verif)


# ---- POST /scf/verifications/{id}/finalize ----
@bp.post("/<vid>/finalize")
@require_auth(["RiskReviewer"])
def finalize_verification(vid):
    verif = store.verifications.get(vid)
    if verif is None:
        raise api_error("ERR_NOT_FOUND", "Verification not found")
    if verif.get("outcome") != "INCONCLUSIVE":
        raise api_error("ERR_INVALID_STATE", "Verification already finalized")

    # Determine outcome based on the three conditions
    can_pass = (
        bool(verif.get("capital_flow_match"))
        and float(verif.get("third_party_score", 0.0)) >= THIRD_PARTY_PASS_FLOOR
    )
    if verif.get("on_site_required") and not verif.get("on_site_completed"):
        # If on-site required but not completed, the implementation may either
        # block with ERR_ON_SITE_REQUIRED (treating finalize as a request to
        # PASS) or finalize as FAIL. The PRD pins ERR_ON_SITE_REQUIRED for
        # PASS attempts. To match the SCAFFOLD validation, treat as ERR
        # whenever the can_pass conditions otherwise hold; else FAIL.
        if can_pass:
            raise api_error("ERR_ON_SITE_REQUIRED", "On-site verification required but not completed")
        # else: it will FAIL naturally below

    outcome = "PASS" if can_pass else "FAIL"

    with store.lock:
        verif["outcome"] = outcome
        if outcome == "FAIL":
            supplier_id = None
            receivable = store.receivables.get(verif.get("receivable_id"))
            if receivable:
                supplier_id = receivable.get("supplier_id")
            if supplier_id and supplier_id in store.suppliers:
                supplier = store.suppliers[supplier_id]
                new_aml = float(supplier.get("aml_risk_score", 0.0)) + FRAUD_PENALTY
                if new_aml > 1.0:
                    new_aml = 1.0
                if new_aml < 0.0:
                    new_aml = 0.0
                supplier["aml_risk_score"] = round(new_aml, 2)
                store.stamp_update(supplier)
                if supplier["aml_risk_score"] >= AML_BLACKLIST_THRESHOLD:
                    cascade_blacklist_supplier(supplier)
    return success_envelope(verif)
