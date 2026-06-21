"""Fee ledger append and derived-figure recomputation (PRD 2.9, 3.x)."""
from db import store
from util import new_common


def append_entry(application_id, kind, amount_cents, source_entity, source_entity_id):
    """Append an immutable FeeLedgerEntry (id + created_at only)."""
    entry = new_common("ledger")
    entry.update({
        "application_id": application_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "source_entity": source_entity,
        "source_entity_id": source_entity_id,
    })
    store.ledger[entry["id"]] = entry
    return entry


def recompute_total_charged(application):
    """MarriageApplication.total_charged_cents = sum of CHARGE rows for the chain.

    Bumps version/updated_at because it is a mutation of the application (PRD 2.5).
    """
    from util import touch
    total = 0
    for e in store.ledger.values():
        if e["application_id"] == application["id"] and e["kind"] == "CHARGE":
            total += e["amount_cents"]
    if application.get("total_charged_cents") != total:
        application["total_charged_cents"] = total
        touch(application)
    else:
        application["total_charged_cents"] = total
