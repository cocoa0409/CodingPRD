"""RepaymentObligation: fetch, list, remit, waive."""
from flask import Blueprint

import lookup
from db import db, touch
from errors import err
from middleware import get_identity, require_role, get_json_body, serialize
from response import success, list_success
from validation import require_int, parse_pagination, paginate
from filters import filter_eq
from services.compliance import recompute_ce_posture

bp = Blueprint("repayments", __name__)


@bp.route("/repayment-obligations/<r_id>", methods=["GET"])
def get_repayment(r_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer", "HrsaAuditor"})
    r = lookup.repayment_obligation(r_id)
    return success(serialize(r))


@bp.route("/repayment-obligations", methods=["GET"])
def list_repayments():
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer", "HrsaAuditor"})
    limit, offset = parse_pagination()
    items = lookup.sorted_by_created(db.repayment_obligations.all())
    items = filter_eq(items, "source_ref_id")
    items = filter_eq(items, "source_kind")
    items = filter_eq(items, "status")
    page, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.route("/repayment-obligations/<r_id>/remit", methods=["POST"])
def remit(r_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer"})
    r = lookup.repayment_obligation(r_id)
    body = get_json_body()

    amount = require_int(body, "amount_cents")

    if r["status"] not in ("OWED", "PARTIALLY_PAID"):
        raise err("ERR_INVALID_STATE", "Obligation is not in a remittable state")

    if amount <= 0 or amount > r["remaining_balance_cents"]:
        raise err("ERR_REMIT_EXCEEDS_BALANCE", "Invalid remittance amount")

    r["paid_cents"] += amount
    r["remaining_balance_cents"] = r["assessed_cents"] - r["paid_cents"]
    if r["remaining_balance_cents"] == 0:
        r["status"] = "SETTLED"
    else:
        r["status"] = "PARTIALLY_PAID"
    touch(r)

    ce = db.covered_entities.get(r["covered_entity_id"])
    if ce is not None:
        recompute_ce_posture(ce)
    return success(serialize(r))


@bp.route("/repayment-obligations/<r_id>/waive", methods=["POST"])
def waive(r_id):
    _, role = get_identity()
    require_role(role, {"HrsaAuditor"})
    r = lookup.repayment_obligation(r_id)

    if r["status"] != "OWED":
        raise err("ERR_INVALID_STATE", "Only an OWED obligation may be waived")

    r["status"] = "WAIVED"
    r["remaining_balance_cents"] = 0
    touch(r)

    ce = db.covered_entities.get(r["covered_entity_id"])
    if ce is not None:
        recompute_ce_posture(ce)
    return success(serialize(r))
