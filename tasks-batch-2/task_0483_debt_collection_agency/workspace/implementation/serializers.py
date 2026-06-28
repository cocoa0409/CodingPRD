"""Serialization for all entities except Account (in services/accounts.py)."""
from services.accounts import serialize_account  # re-export


def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_creditor(c):
    d = _common(c)
    d.update({
        "name": c["name"],
        "commission_basis": c.get("commission_basis", "GROSS_OF_FEES"),
        "commission_rate_bps": c["commission_rate_bps"],
        "expense_recovery_cents": c.get("expense_recovery_cents", 0),
    })
    return d


def serialize_consumer(c):
    d = _common(c)
    d.update({
        "full_name": c["full_name"],
        "timezone_offset_minutes": c.get("timezone_offset_minutes", 0),
        "phone": c.get("phone"),
        "address": c.get("address"),
        "contactability": c.get("contactability", "UNKNOWN"),
    })
    return d


def serialize_skip_trace(s):
    d = _common(s)
    d.update({
        "consumer_id": s["consumer_id"],
        "result": s["result"],
        "new_phone": s.get("new_phone"),
        "new_address": s.get("new_address"),
    })
    return d


def serialize_communication_attempt(a):
    d = _common(a)
    d.update({
        "account_id": a["account_id"],
        "channel": a["channel"],
        "attempted_at": a["attempted_at"],
        "outcome": a["outcome"],
        "counts_toward_cadence": a.get("counts_toward_cadence", True),
    })
    return d


def serialize_dispute(dp):
    d = _common(dp)
    d.update({
        "account_id": dp["account_id"],
        "dispute_type": dp["dispute_type"],
        "raised_at": dp["raised_at"],
        "within_validation_window": dp["within_validation_window"],
        "resolution": dp.get("resolution"),
        "status": dp["status"],
    })
    return d


def serialize_arrangement(a):
    d = _common(a)
    d.update({
        "account_id": a["account_id"],
        "arrangement_type": a["arrangement_type"],
        "offer_pct_bps": a.get("offer_pct_bps"),
        "settlement_amount_cents": a.get("settlement_amount_cents"),
        "installment_count": a.get("installment_count", 1),
        "good_through": a.get("good_through"),
        "status": a["status"],
    })
    return d


def serialize_payment(p):
    d = _common(p)
    d.update({
        "account_id": p["account_id"],
        "arrangement_id": p.get("arrangement_id"),
        "amount_cents": p["amount_cents"],
        "posted_at": p["posted_at"],
        "status": p["status"],
    })
    return d


def serialize_bureau_furnishing(f):
    d = _common(f)
    d.update({
        "account_id": f["account_id"],
        "bureau": f["bureau"],
        "furnished_balance_cents": f["furnished_balance_cents"],
        "status": f["status"],
    })
    return d


def serialize_bureau_dispute(bd):
    d = _common(bd)
    d.update({
        "furnishing_id": bd["furnishing_id"],
        "opened_at": bd["opened_at"],
        "investigation_deadline": bd["investigation_deadline"],
        "outcome": bd.get("outcome"),
        "status": bd["status"],
    })
    return d
