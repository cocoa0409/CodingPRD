"""Disbursement settlement waterfall (PRD §3.8 / calc disbursement_settlement).

PINNED order: sum grosses, take ONE batch-level fee on the sum (floor), then
allocate that single fee across lines: each line floors its own share, and any
leftover cents are distributed +1 cent per line in created_at ASC order.
"""
from db import db
from services.common import floor_mul, touch


def settle_batch(batch):
    """Run the fee waterfall and propagate settlement (PRD §3.8)."""
    program = db.programs.get(batch["program_id"])
    rate = program["disbursement_admin_fee_rate"]

    # STAGED grants only (VOIDED excluded), ascending created_at.
    staged = [g for g in db.grants.values()
              if g["batch_id"] == batch["id"] and g["status"] == "STAGED"]
    # PRD §3.8: ascending created_at. The frozen logical clock can make
    # created_at strings identical for grants staged in the same instant, so
    # break ties by the monotonic creation sequence (true staging order) rather
    # than the random UUID — this makes the leftover-cent allocation deterministic.
    staged.sort(key=lambda g: (g["created_at"], g.get("_seq", 0)))

    gross_total = sum(g["gross_amount_cents"] for g in staged)
    admin_fee = floor_mul(gross_total, rate)          # single batch-level fee
    net_total = gross_total - admin_fee

    # Per-line floor of own share, then distribute leftover one cent at a time.
    for g in staged:
        g["admin_fee_cents"] = floor_mul(g["gross_amount_cents"], rate)
    allocated = sum(g["admin_fee_cents"] for g in staged)
    leftover = admin_fee - allocated                  # >= 0
    i = 0
    while leftover > 0 and staged:
        staged[i % len(staged)]["admin_fee_cents"] += 1
        leftover -= 1
        i += 1

    for g in staged:
        g["net_amount_cents"] = g["gross_amount_cents"] - g["admin_fee_cents"]
        g["status"] = "SETTLED"
        touch(g)
        # Propagate to underlying source.
        if g["source_type"] == "MATCH":
            gift = db.matching_gifts.get(g["source_id"])
            if gift is not None and gift["status"] == "FINALIZED":
                gift["status"] = "SETTLED"
                touch(gift)
        elif g["source_type"] == "DFD":
            log = db.volunteer_logs.get(g["source_id"])
            if log is not None and log["status"] == "APPROVED":
                log["status"] = "SETTLED"
                touch(log)

    batch["gross_total_cents"] = gross_total
    batch["admin_fee_cents"] = admin_fee
    batch["net_total_cents"] = net_total
    batch["status"] = "SETTLED"
    touch(batch)

    charity = db.charities.get(batch["charity_id"])
    if charity is not None:
        charity["total_received_cents"] += net_total
        touch(charity)
