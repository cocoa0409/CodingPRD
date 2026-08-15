"""Availability recompute and the outage -> obligation -> credit cascade."""
from decimal import Decimal

from db import store
from util import touch
from services.credit import refresh_credit


def covering_approved_outages(generator_id):
    now = store.clock_now
    result = []
    for o in store.outages.values():
        if o["generator_asset_id"] != generator_id or o["status"] != "APPROVED":
            continue
        if o["_start_dt"] <= now < o["_end_dt"]:  # half-open window
            result.append(o)
    return result


def recompute_availability(generator):
    """Recompute availability_mw and AVAILABLE/ON_OUTAGE status, then cascade
    into open capacity obligations and participant credit posture."""
    covering = covering_approved_outages(generator["id"])
    full = any(o["outage_type"] == "FULL" for o in covering)
    if full:
        new_avail = Decimal(0)
        new_status = "ON_OUTAGE"
    else:
        max_derate = max((o["derate_pct"] for o in covering), default=0)
        new_avail = Decimal(generator["capacity_mw"]) * (Decimal(100 - max_derate) / Decimal(100))
        new_status = generator["status"] if generator["status"] == "DECOMMISSIONED" else "AVAILABLE"

    if new_avail != generator["availability_mw"] or new_status != generator["status"]:
        generator["availability_mw"] = new_avail
        generator["status"] = new_status
        touch(generator)

    participant = store.participants.get(generator["market_participant_id"])
    for obl in store.obligations.values():
        if obl["generator_asset_id"] != generator["id"]:
            continue
        if obl["status"] not in ("ACTIVE", "AT_RISK"):
            continue
        new_expected = min(Decimal(obl["obligated_mw"]), new_avail)
        new_ostatus = "AT_RISK" if new_expected < Decimal(obl["obligated_mw"]) else "ACTIVE"
        changed = (new_expected != obl["expected_output_mw"]) or (new_ostatus != obl["status"])
        status_changed = new_ostatus != obl["status"]
        if changed:
            obl["expected_output_mw"] = new_expected
            obl["status"] = new_ostatus
            touch(obl)
            # Every transition into or out of AT_RISK changes the capacity
            # risk adder -> recompute requirement and evaluate posture.
            if status_changed and participant is not None:
                refresh_credit(participant)


def recompute_all_availability():
    """Used when the logical clock moves: re-evaluate every generator that has
    an APPROVED outage (window entry/exit), then sweep open margin calls."""
    seen = set()
    for o in store.outages.values():
        if o["status"] != "APPROVED":
            continue
        gid = o["generator_asset_id"]
        if gid in seen:
            continue
        seen.add(gid)
        gen = store.generators.get(gid)
        if gen is not None:
            recompute_availability(gen)
    # Time-based margin call defaulting: an OPEN call past due_at with the
    # deficiency standing defaults when the clock passes.
    for participant in list(store.participants.values()):
        has_open = any(mc["market_participant_id"] == participant["id"] and mc["status"] == "OPEN"
                       for mc in store.margin_calls.values())
        if has_open:
            from services.credit import evaluate_credit
            evaluate_credit(participant)
