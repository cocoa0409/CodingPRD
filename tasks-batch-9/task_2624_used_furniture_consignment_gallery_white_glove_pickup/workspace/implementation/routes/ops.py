"""The logical clock and the two nightly epochs (PRD 2.5, 3.7, 3.9)."""

from flask import Blueprint

import auth
import calc
import envelope
import services
import store
import validation as v
from errors import fail
from store import db

bp = Blueprint("ops", __name__)

ON_FLOOR_STATES = ("ON_FLOOR", "MARKED_DOWN")
MARKDOWN_AGREEMENT_STATES = ("ACTIVE", "EXPIRED")

# the item columns an epoch may move; a version bump is owed only if one of them did
_WATCHED = (
    "markdown_sequence",
    "current_price_cents",
    "lifecycle_state",
    "inventory_state",
    "placement_zone_id",
    "election_deadline_at",
    "disposition_election",
    "election_round",
    "clearance_relocation_pending",
)


def _snapshot(row):
    return tuple(row.get(name) for name in _WATCHED)


# ---------------------------------------------------------------------------
# the clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.require("SystemOperator")
    data = v.body()
    current_utc = v.req_dt(data, "current_utc")
    # ladder 25: time never runs backwards; setting it to its present value is fine
    if current_utc < store.now():
        fail("ERR_CLOCK_NOT_MONOTONIC")
    store.set_clock(current_utc)
    return envelope.empty()


# ---------------------------------------------------------------------------
# the markdown epoch
# ---------------------------------------------------------------------------
@bp.post("/_ops/markdown-run")
def markdown_run():
    auth.require("SystemOperator")

    # lapsed agreements first, so the run's own visit set is settled
    for agreement in store.ordered(db.agreements):
        if agreement["status"] != "ACTIVE":
            continue
        if agreement["expires_at"] is not None and agreement["expires_at"] <= store.now():
            agreement["status"] = "EXPIRED"
            store.touch(agreement)

    for item in store.ordered(db.items):
        if item.get("listed_at") is None:
            continue
        agreement = services.agreement_of(item)
        if agreement is None or agreement["status"] not in MARKDOWN_AGREEMENT_STATES:
            continue

        before = _snapshot(item)

        # the step in force, and the price it produces under the item's variant
        services.recompute_current_price(item)

        # ON_FLOOR -> MARKED_DOWN once a later step takes force; MARKED_DOWN self-loops
        if item["lifecycle_state"] == "ON_FLOOR" and int(item["markdown_sequence"] or 0) >= 2:
            item["lifecycle_state"] = "MARKED_DOWN"
        if item["lifecycle_state"] in ON_FLOOR_STATES:
            services.clearance_relocation(item)

        # the unsold flag
        if item["lifecycle_state"] in ON_FLOOR_STATES:
            trigger = services.unsold_trigger_day_effective(item)
            if services.days_on_floor(item) >= trigger:
                schedule = services.schedule_of_item(item)
                window = int(schedule["election_window_days"]) if schedule else 0
                item["lifecycle_state"] = "UNSOLD_PENDING_ELECTION"
                item["election_deadline_at"] = store.add_days(store.now(), window)

        # a consignor who says nothing is donated for
        if item["lifecycle_state"] == "UNSOLD_PENDING_ELECTION":
            deadline = item.get("election_deadline_at")
            if deadline is not None and deadline <= store.now():
                item["lifecycle_state"] = "DONATION_SCHEDULED"
                item["disposition_election"] = "DONATE"
                item["election_deadline_at"] = None
                item["election_lapsed"] = True

        if _snapshot(item) != before:
            store.touch(item)

    return envelope.empty()


# ---------------------------------------------------------------------------
# the escheatment epoch
# ---------------------------------------------------------------------------
@bp.post("/_ops/escheatment-run")
def escheatment_run():
    auth.require("SystemOperator")

    for consignor in store.ordered(db.consignors):
        if consignor["escheat_state"] == "ESCHEATED":
            continue
        balance = services.unclaimed_balance_cents(consignor["id"])
        before = consignor["escheat_state"]

        if balance <= 0:
            if before != "NONE":
                consignor["escheat_state"] = "NONE"
                store.touch(consignor)
            continue

        dormant_days = store.whole_days_between(consignor["last_activity_at"], store.now())
        if dormant_days >= calc.ESCHEAT_DAYS:
            consignor["escheat_state"] = "ESCHEATED"
            # mint_entry bumps the version once; do not touch the row again
            services.mint_entry(
                consignor,
                "ESCHEATMENT_DEBIT",
                -balance,
                "escheatment of %d cents unclaimed for %d days" % (balance, dormant_days),
                item_id=None,
            )
            for agreement in store.ordered(db.agreements):
                if (
                    agreement["consignor_id"] == consignor["id"]
                    and agreement["status"] == "ACTIVE"
                ):
                    agreement["status"] = "TERMINATED"
                    store.touch(agreement)
            continue

        if dormant_days >= calc.DORMANT_DAYS:
            if before != "DORMANT":
                consignor["escheat_state"] = "DORMANT"
                store.touch(consignor)
            continue

        if before != "NONE":
            consignor["escheat_state"] = "NONE"
            store.touch(consignor)

    return envelope.empty()
