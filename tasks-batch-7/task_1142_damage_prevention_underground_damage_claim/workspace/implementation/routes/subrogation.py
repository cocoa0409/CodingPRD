"""SubrogationCase endpoints."""

from flask import Blueprint, request

import clock
from db import db
from errors import err_invalid_request, err_invalid_state, err_not_found
from middleware import require_roles
from serializers import subrogation_out
from services.core import (invoice_status_from_paid, maybe_advance_case_recovery,
                           recompute_debtor_outstanding,
                           recompute_invoice_amount_due, touch)
from util import get_pagination, paginate, parse_body, require_int, success_envelope

bp = Blueprint("subrogation", __name__)

ALL_ROLES = ("IntakeCoordinator", "DamageInvestigator", "ClaimsAdjuster",
             "RecoveryManager", "Excavator", "Locator")


@bp.route("/damage-recovery/subrogation-cases/<sid>", methods=["GET"])
def get_subrogation(sid):
    require_roles(*ALL_ROLES)
    s = db.subrogation_cases.get(sid)
    if s is None:
        raise err_not_found("subrogation case not found")
    return success_envelope(subrogation_out(s), "object", 200)


@bp.route("/damage-recovery/subrogation-cases", methods=["GET"])
def list_subrogations():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.subrogation_cases.values())
    dispute_id = request.args.get("dispute_id")
    invoice_id = request.args.get("claim_invoice_id")
    status = request.args.get("status")
    if dispute_id is not None:
        items = [s for s in items if s["dispute_id"] == dispute_id]
    if invoice_id is not None:
        items = [s for s in items if s["claim_invoice_id"] == invoice_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(items, limit, offset)
    return success_envelope([subrogation_out(s) for s in page], "array", 200, meta)


@bp.route("/damage-recovery/subrogation-cases/<sid>/record-settlement", methods=["POST"])
def record_settlement(sid):
    require_roles("RecoveryManager")
    s = db.subrogation_cases.get(sid)
    if s is None:
        raise err_not_found("subrogation case not found")
    body = parse_body(required_fields=["recovered_cents", "legal_cost_cents"])
    recovered = require_int(body["recovered_cents"], "recovered_cents")
    legal = require_int(body["legal_cost_cents"], "legal_cost_cents")
    if recovered < 0 or legal < 0:
        raise err_invalid_request("amounts must be non-negative")
    if s["status"] != "DEMANDED":
        raise err_invalid_state("subrogation case is not DEMANDED")
    if legal > recovered:
        raise err_invalid_request("legal_cost_cents must not exceed recovered_cents")

    net = recovered - legal
    applied = 0
    if s["claim_invoice_id"]:
        inv = db.claim_invoices.get(s["claim_invoice_id"])
        if inv is not None:
            recompute_invoice_amount_due(inv)
            applied = min(net, inv["amount_due_cents"])
            inv["amount_paid_cents"] += applied
            recompute_invoice_amount_due(inv)
            if inv["status"] in ("ISSUED", "PARTIALLY_PAID", "DISPUTED"):
                # subrogation settlement pulls invoice out of DISPUTED too
                inv["status"] = invoice_status_from_paid(inv)
            touch(inv)
            recompute_debtor_outstanding(inv["debtor_type"], inv["debtor_id"])
            case = db.damage_cases.get(inv["damage_case_id"])
            if case is not None:
                if case["recovery_status"] == "INVOICED" and applied > 0:
                    case["recovery_status"] = "COLLECTING"
                maybe_advance_case_recovery(case)
    owner_share = net - applied

    s["recovered_cents"] = recovered
    s["legal_cost_cents"] = legal
    s["owner_share_cents"] = owner_share
    s["status"] = "SETTLED"
    s["updated_at"] = clock.get_current_utc()
    s["version"] += 1
    return success_envelope(subrogation_out(s), "object", 200)


@bp.route("/damage-recovery/subrogation-cases/<sid>/close", methods=["POST"])
def close_subrogation(sid):
    require_roles("RecoveryManager")
    s = db.subrogation_cases.get(sid)
    if s is None:
        raise err_not_found("subrogation case not found")
    if s["status"] not in ("DEMANDED", "SETTLED"):
        raise err_invalid_state("subrogation case is not DEMANDED or SETTLED")
    s["status"] = "CLOSED"
    s["updated_at"] = clock.get_current_utc()
    s["version"] += 1
    return success_envelope(subrogation_out(s), "object", 200)
