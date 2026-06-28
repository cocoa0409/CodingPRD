"""Public serialization of entities. Strips internal fields (those prefixed
with '_') and injects freshly computed derived fields."""
from services.reconcile import account_balance, total_rack_count, waitlist_priority_at_read


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def marina_view(rec):
    out = _public(rec)
    out["total_rack_count"] = total_rack_count(rec["id"])
    return out


def forklift_view(rec):
    return _public(rec)


def rack_view(rec):
    return _public(rec)


def vessel_view(rec):
    return _public(rec)


def owner_view(rec):
    out = _public(rec)
    out["account_balance_cents"] = account_balance(rec["id"])
    return out


def policy_view(rec):
    return _public(rec)


def agreement_view(rec):
    return _public(rec)


def waitlist_view(rec):
    out = _public(rec)
    out["priority_score"] = waitlist_priority_at_read(rec)
    return out


def launch_view(rec):
    return _public(rec)


def slot_view(rec):
    return _public(rec)


def service_order_view(rec):
    return _public(rec)


def invoice_view(rec):
    return _public(rec)
