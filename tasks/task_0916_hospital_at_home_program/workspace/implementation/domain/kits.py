"""DeviceKit lifecycle: deployment, system release into refurbishment, and the
reconciliation-driven return to service or retirement (PRD 3.5)."""

import calc
import clock
import derived
import store
from domain import compliance


def deploy(kit, episode):
    kit["status"] = "DEPLOYED"
    kit["assigned_episode_id"] = episode["id"]
    kit["deployed_at"] = clock.now_raw()
    store.touch(kit)
    for component in derived.kit_components(kit["id"]):
        if component["reconciliation_status"] == "IN_STOCK":
            component["reconciliation_status"] = "DEPLOYED"
            store.touch(component)
    episode["last_deployed_kit_id"] = kit["id"]


def release_for_episode(episode):
    """The system-performed kit release fired by bed return and by begin-discharge.

    Moves the episode's DEPLOYED kit to IN_REFURB, pushes its components into
    PENDING_RECONCILIATION, then reaches sideways into the day ledger: the
    current date's record loses kit_deployed_all_day and, when still PENDING,
    is immediately scored through the daily verdict.
    """
    kit = derived.episode_deployed_kit(episode["id"])
    if kit is None:
        return None
    kit["status"] = "IN_REFURB"
    kit["assigned_episode_id"] = None
    kit["refurb_cycle_count"] = kit["refurb_cycle_count"] + 1
    store.touch(kit)
    for component in derived.kit_components(kit["id"]):
        if component["reconciliation_status"] == "DEPLOYED":
            component["reconciliation_status"] = "PENDING_RECONCILIATION"
            store.touch(component)

    record = derived.find_record(episode["id"], clock.today_date())
    if record is not None:
        if record["kit_deployed_all_day"]:
            record["kit_deployed_all_day"] = False
            store.touch(record)
        if record["status"] == "PENDING":
            compliance.finalize(record)
    return kit


def reconcile_component(component, outcome, caller_user_id):
    """Close the custody chain on one component; the last one moves the kit."""
    component["reconciliation_status"] = outcome
    component["reconciled_by_user_id"] = caller_user_id
    store.touch(component)

    kit = store.DB.kits.get(component["kit_id"])
    if kit is None:
        return
    if kit["status"] != "IN_REFURB":
        return
    if derived.kit_unreconciled_component_count(kit["id"]) != 0:
        return
    if kit["refurb_cycle_count"] <= calc.REFURB_CYCLE_LIMIT:
        kit["status"] = "AVAILABLE"
        for sibling in derived.kit_components(kit["id"]):
            if sibling["reconciliation_status"] == "RETURNED":
                sibling["reconciliation_status"] = "IN_STOCK"
                store.touch(sibling)
    else:
        kit["status"] = "RETIRED"
    store.touch(kit)
