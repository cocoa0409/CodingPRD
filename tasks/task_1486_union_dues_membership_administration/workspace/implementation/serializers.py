"""Entity -> API dict serialization. Strips internal `_`-prefixed fields and
injects computed fields (member balances/standing, assessment paid_cents)."""
import db
from services import ledger as ledger_svc


def _clean(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def local(entity):
    return _clean(entity)


def classification(entity):
    return _clean(entity)


def employer(entity):
    return _clean(entity)


def member(entity):
    out = _clean(entity)
    arrears, credit = ledger_svc.balances(entity["id"])
    out["arrears_cents"] = arrears
    out["credit_balance_cents"] = credit
    out["good_standing"] = entity["status"] == "ACTIVE" and arrears == 0
    out["chargeable_share_pct"] = active_chargeable_share(entity["id"])
    return out


def active_chargeable_share(member_id):
    """Chargeable-share percent from the member's non-terminal ObjectorCase in
    RATE_SET / REBATE_ISSUED / APPEALED; null when no active case."""
    for c in db.store.objector_cases.values():
        if (c["member_id"] == member_id
                and c["status"] in ("RATE_SET", "REBATE_ISSUED", "APPEALED")):
            return c["chargeable_share_pct"]
    return None


def assessment(entity):
    out = _clean(entity)
    out["paid_cents"] = ledger_svc.paid_cents(entity)
    return out


def ledger_entry(entity):
    return _clean(entity)


def remittance(entity):
    return _clean(entity)


def remittance_line(entity):
    return _clean(entity)


def notice(entity):
    return _clean(entity)


def objector_case(entity):
    return _clean(entity)


def transfer(entity):
    return _clean(entity)


def per_capita_report(entity):
    return _clean(entity)


def election(entity):
    return _clean(entity)


def eligibility(entity):
    return _clean(entity)


def assessment_run(entity):
    return _clean(entity)
