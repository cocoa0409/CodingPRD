"""Entity serializers. Strip internal bookkeeping keys (leading underscore) and
attach computed fields."""
from services import provider_balance_cents


def pub(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def provider_json(p):
    d = pub(p)
    d["recoupment_balance_cents"] = provider_balance_cents(p["id"])
    return d
