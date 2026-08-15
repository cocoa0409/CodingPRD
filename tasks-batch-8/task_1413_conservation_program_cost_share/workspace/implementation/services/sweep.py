"""Deadline sweep (PRD 2.7) — runs only when the logical clock is set."""
from datetime import timedelta

from db import STORE
from helpers import touch
from services.ledger import (
    create_demand,
    expire_item,
    pool_available,  # noqa: F401  (re-exported for readers)
)


def run_sweep():
    clock = STORE.clock

    # 1. Programs: OPEN -> CLOSED once the clock has passed window_end.
    for p in STORE.programs.values():
        if p["status"] == "OPEN" and clock > p["window_end"]:
            p["status"] = "CLOSED"
            touch(p)

    # 2. Practice items: PLANNED/INSTALLED/CERTIFICATION_FAILED -> EXPIRED once
    #    the clock passes implementation_deadline — frozen while the contract is
    #    under modification review.
    for item in list(STORE.items.values()):
        if item["certification_status"] not in ("PLANNED", "INSTALLED", "CERTIFICATION_FAILED"):
            continue
        if clock <= item["implementation_deadline"]:
            continue
        contract = STORE.contracts.get(item["contract_id"])
        if contract is None or contract["status"] == "MODIFICATION_PENDING":
            continue
        release = contract["status"] != "DRAFT"  # DRAFT contracts hold no pool funds
        pool = STORE.pools.get(contract["pool_id"]) if release else None
        expire_item(item, pool, release=release)

    # 3. Advances: ISSUED -> RETURN_DUE past expenditure_due_date;
    #    RETURN_DUE -> ESCALATED thirty days past due, spawning a demand.
    for adv in list(STORE.advances.values()):
        if adv["status"] == "ISSUED" and adv["outstanding_cents"] > 0 \
                and clock > adv["expenditure_due_date"]:
            adv["status"] = "RETURN_DUE"
            touch(adv)
        if adv["status"] == "RETURN_DUE" and adv["outstanding_cents"] > 0 \
                and clock > adv["expenditure_due_date"] + timedelta(days=30):
            adv["status"] = "ESCALATED"
            touch(adv)
            create_demand(
                contract_id=adv["contract_id"],
                amount_cents=adv["outstanding_cents"],
                advance_payment_id=adv["id"],
            )

    # 4. Maintenance obligations: ACTIVE -> SATISFIED once the clock reaches
    #    end_date (half-open interval: satisfied at exactly end_date).
    for ob in STORE.obligations.values():
        if ob["status"] == "ACTIVE" and clock >= ob["end_date"]:
            ob["status"] = "SATISFIED"
            touch(ob)

    # 5. Recoupment demands: DEMANDED -> ESCALATED once the clock passes due_date.
    for d in STORE.demands.values():
        if d["status"] == "DEMANDED" and clock > d["due_date"]:
            d["status"] = "ESCALATED"
            touch(d)
