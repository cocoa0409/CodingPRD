"""Split share allocation (scaffold split_share_allocation) and status rollup.

EVEN: floor base, remainder cents one-each to earliest participants (created_at ASC).
WEIGHTED: largest-remainder method; ties broken created_at ASC.
Invariant: sum(shares) == total exactly.
"""
import models
from db import db


def allocate_shares(total_amount_cents, split_mode, participants):
    """participants: list of participant dicts already sorted by created_at ASC.
    Mutates each participant's share_amount_cents in place.
    """
    n = len(participants)
    if split_mode == "EVEN":
        base = total_amount_cents // n
        remainder = total_amount_cents - base * n
        for i, p in enumerate(participants):
            p["share_amount_cents"] = base + (1 if i < remainder else 0)
    else:  # WEIGHTED
        weights = [p["weight"] for p in participants]
        w_sum = sum(weights)
        floors = []
        fracs = []  # (fractional_remainder, original_index)
        for i, p in enumerate(participants):
            raw_num = total_amount_cents * p["weight"]  # exact numerator over w_sum
            fl = raw_num // w_sum
            rem = raw_num - fl * w_sum  # fractional part * w_sum (integer)
            floors.append(fl)
            fracs.append((rem, i))
        leftover = total_amount_cents - sum(floors)
        # rank by fractional remainder DESC, tie-break created_at ASC (index order,
        # since participants are pre-sorted by created_at ASC)
        order = sorted(range(n), key=lambda i: (-fracs[i][0], i))
        winners = set(order[:leftover])
        for i, p in enumerate(participants):
            p["share_amount_cents"] = floors[i] + (1 if i in winners else 0)


def rollup(split_request):
    """Re-derive collected_amount_cents and status from participant states.

    SETTLED if all terminal and >=1 paid; PARTIALLY_SETTLED if >=1 paid; else OPEN.
    Frozen collected once SETTLED (recompute keeps it correct since paid set is stable).
    """
    parts = [p for p in db.split_participants.values()
             if p["split_request_id"] == split_request["id"]]
    collected = sum(p["share_amount_cents"] for p in parts if p["status"] == "PAID")
    n = len(parts)
    n_paid = sum(1 for p in parts if p["status"] == "PAID")
    n_terminal = sum(1 for p in parts if p["status"] in ("PAID", "FORGIVEN"))

    if n_terminal == n and n_paid >= 1:
        new_status = "SETTLED"
    elif n_paid >= 1:
        new_status = "PARTIALLY_SETTLED"
    else:
        new_status = "OPEN"

    changed = (split_request["collected_amount_cents"] != collected
               or split_request["status"] != new_status)
    split_request["collected_amount_cents"] = collected
    split_request["status"] = new_status
    if changed:
        models.touch(split_request)
