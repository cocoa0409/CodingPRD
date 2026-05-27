"""Cascading side effects across multiple entities."""
from __future__ import annotations

from datetime import datetime

import db
from common import touch
from services.calculations import (
    compute_net_taxable,
    guardian_eligible,
    recompute_and_store_gross,
    recompute_and_store_net,
)


def cascade_register_death(decedent: dict, now: datetime) -> None:
    """Triggered by POST /decedents/{id}/register-death after date_of_death set.

    For every Estate with decedent_id == this id and status == ALIVE:
      - Estate ALIVE -> DECEASED
      - Non-DURABLE POAs (FINANCIAL, HEALTHCARE) ACTIVE -> TERMINATED
      - Assets with beneficiary_designation_id != None and category IN
        {RETIREMENT_IRA, LIFE_INSURANCE} INCLUDED -> EXCLUDED
      - Guardianships PROPOSED -> COURT_REVIEW when ward < 18
      - Estate.gross_estate_value_cents recomputed
      - Estate.updated_at + version bumped once for the whole logical op

    Non-durable POAs are also terminated independently of any estate (they hang
    off the decedent), but this implementation walks them once per cascade.
    """
    # POAs on the decedent (non-durable, ACTIVE -> TERMINATED)
    for p in db.powers_of_attorney.values():
        if (
            p["decedent_id"] == decedent["id"]
            and p["status"] == "ACTIVE"
            and p["scope"] in ("FINANCIAL", "HEALTHCARE")
        ):
            p["status"] = "TERMINATED"
            touch(p, now)

    # Per-estate cascade
    affected_estates = [e for e in db.estates.values() if e["decedent_id"] == decedent["id"]]
    for estate in affected_estates:
        if estate["status"] != "ALIVE":
            # PRD: only ALIVE estates cascade to DECEASED.
            continue

        # Exclude beneficiary-designated non-probate assets
        for a in db.assets.values():
            if (
                a["estate_id"] == estate["id"]
                and a["status"] == "INCLUDED"
                and a.get("beneficiary_designation_id") is not None
                and a["category"] in ("RETIREMENT_IRA", "LIFE_INSURANCE")
            ):
                a["status"] = "EXCLUDED"
                touch(a, now)

        # Guardianships -> COURT_REVIEW where ward < 18
        for g in db.guardianships.values():
            if g["estate_id"] != estate["id"]:
                continue
            if g["status"] != "PROPOSED":
                continue
            if guardian_eligible(g["ward_date_of_birth"], decedent["date_of_death"]):
                g["status"] = "COURT_REVIEW"
                touch(g, now)
            # If ward is over age, the guardianship stays PROPOSED.
            # Activation/review with ERR_WARD_OVER_AGE is raised on explicit
            # POST /guardianships/{id}/review.

        # Estate status & recompute
        estate["status"] = "DECEASED"
        recompute_and_store_gross(estate)
        # Provisional variant recomputes
        recompute_and_store_net(estate)
        touch(estate, now)


def cascade_open_probate(estate: dict, order: dict, now: datetime) -> None:
    """Triggered when OPEN_PROBATE order enters. Caller has already validated
    preconditions (estate.status, executor-beneficiary conflict)."""
    estate["status"] = "PROBATE_OPEN"
    estate["probate_opened_at"] = order["entered_at"]

    # Promote the unique ACCEPTED EXECUTOR to COURT_CONFIRMED.
    for x in db.executors.values():
        if (
            x["estate_id"] == estate["id"]
            and x["role_type"] == "EXECUTOR"
            and x["status"] == "ACCEPTED"
        ):
            x["status"] = "COURT_CONFIRMED"
            touch(x, now)
            break  # one only
    touch(estate, now)


def cascade_approve_inventory(estate: dict, now: datetime) -> None:
    """Triggered when APPROVE_INVENTORY enters."""
    estate["status"] = "ADMINISTRATION"
    estate["inventory_snapshot_gross_cents"] = estate["gross_estate_value_cents"]
    # Net taxable estate now runs in 'final' variant
    recompute_and_store_net(estate)
    touch(estate, now)


def cascade_close_estate(estate: dict, now: datetime) -> None:
    """Triggered when CLOSE_ESTATE enters."""
    estate["status"] = "CLOSED"
    estate["closed_at"] = now
    for x in db.executors.values():
        if x["estate_id"] == estate["id"] and x["status"] == "COURT_CONFIRMED":
            x["status"] = "DISCHARGED"
            touch(x, now)
    # Final variant recompute (frozen snapshot)
    recompute_and_store_net(estate)
    touch(estate, now)


def cascade_contest(estate: dict, now: datetime) -> None:
    """Triggered on POST /estates/{id}/contest."""
    estate["status"] = "CONTESTED"
    cutoff = now
    # Supersede ENTERED ProbateOrders within the last 72h
    from datetime import timedelta
    window = timedelta(hours=72)
    for o in db.probate_orders.values():
        if o["estate_id"] != estate["id"]:
            continue
        if o["status"] != "ENTERED":
            continue
        entered = o.get("entered_at")
        if entered is None:
            continue
        if (cutoff - entered) <= window:
            o["status"] = "SUPERSEDED"
            touch(o, now)
    touch(estate, now)


def cascade_revoke_designation(designation: dict, now: datetime) -> None:
    """On revoke, any DRAFT designation whose contingent_of_designation_id ==
    this.id auto-transitions DRAFT -> ACTIVE."""
    estate_id = designation["estate_id"]
    for b in db.beneficiary_designations.values():
        if b["estate_id"] != estate_id:
            continue
        if b.get("contingent_of_designation_id") != designation["id"]:
            continue
        if b["status"] != "DRAFT":
            continue
        b["status"] = "ACTIVE"
        touch(b, now)


def cascade_supersede_confirm_executor(order: dict, now: datetime) -> None:
    """When a CONFIRM_EXECUTOR order is explicitly superseded, demote the
    estate's COURT_CONFIRMED executor to REMOVED and clear Estate.executor_user_id."""
    estate = db.estates.get(order["estate_id"])
    if estate is None:
        return
    for x in db.executors.values():
        if (
            x["estate_id"] == estate["id"]
            and x["role_type"] == "EXECUTOR"
            and x["status"] == "COURT_CONFIRMED"
        ):
            x["status"] = "REMOVED"
            touch(x, now)
    estate["executor_user_id"] = None
    touch(estate, now)
