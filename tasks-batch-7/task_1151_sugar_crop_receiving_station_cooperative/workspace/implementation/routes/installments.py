from flask import Blueprint

import db
import response
import serializers
import services.cascade as cascade
from errors import raise_err
from middleware import require_roles
from services.calc import installment_waterfall

bp = Blueprint("installments", __name__)


@bp.post("/api/installments/<installment_id>/issue")
def issue_installment(installment_id):
    require_roles(["POOL_ACCOUNTANT"])
    inst = db.installments.get(installment_id)
    if not inst:
        raise_err("ERR_NOT_FOUND", "Installment not found")
    if inst["status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "Installment is not SCHEDULED")
    pool = db.pools.get(inst["pool_id"])
    if pool["status"] != "ACCRUING":
        raise_err("ERR_POOL_NOT_ACCRUING", "Pool is not ACCRUING")
    campaign = db.campaigns.get(pool["campaign_id"])

    advances = installment_waterfall(inst, pool, campaign)
    distributed = 0
    for member, amount in advances:
        entry = db.stamp_ledger({
            "member_id": member["id"],
            "pool_id": pool["id"],
            "installment_id": inst["id"],
            "settlement_id": None,
            "kind": "ADVANCE_CREDIT",
            "amount_cents": int(amount),
            "reversal_of_id": None,
        })
        db.ledger_entries[entry["id"]] = entry
        distributed += int(amount)
    for member, _amount in advances:
        cascade.recompute_member_ledger(member["id"])

    inst["distributed_amount_cents"] = distributed
    inst["status"] = "ISSUED"
    db.touch(inst)
    return response.success(serializers.installment(inst), 200)
