"""Selectors, ledger appends and the declared cascades."""
from decimal import Decimal

import calc
import derive
import store
import sync
from errors import fail
from store import (add_hours, clock_now, dec, money, night_set, sorted_rows,
                   touch)


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------
def append_entry(claim, entry_type, delta_case_reserve, delta_paid, memo,
                 reverses_entry_id=None):
    event_id = claim["event_id"]
    rec = store.base_record(with_common=False)
    rec.update({
        "event_id": event_id,
        "claim_id": claim["id"],
        "reverses_entry_id": reverses_entry_id,
        "entry_type": entry_type,
        "delta_case_reserve": money(delta_case_reserve),
        "delta_paid": money(delta_paid),
        "sequence_no": derive.next_sequence_no(event_id),
        "effective_utc": clock_now(),
        "memo": memo,
    })
    store.reserve_entries[rec["id"]] = rec
    return rec


# --------------------------------------------------------------------------
# Bulletin-derived figures
# --------------------------------------------------------------------------
def governing_mandate_pct(event_id):
    return derive.governing_mandate_pct(event_id)


# --------------------------------------------------------------------------
# Adjuster selector (PRD 3.5 / 3.7)
# --------------------------------------------------------------------------
def rest_conflict(adjuster_id, start, end, ignore_deployment_id=None):
    buffer_h = calc.REST_BUFFER_HOURS
    for d in store.deployments.values():
        if d["adjuster_id"] != adjuster_id:
            continue
        if d["id"] == ignore_deployment_id:
            continue
        if d["status"] not in ("CONFIRMED", "ON_SITE", "DEMOBILIZED"):
            continue
        if start < add_hours(d["window_end_utc"], buffer_h) \
                and d["window_start_utc"] < add_hours(end, buffer_h):
            return True
    return False


def adjuster_eligible(adj, event, role, start, end):
    if adj["deployment_status"] != "AVAILABLE":
        return False
    if adj["credential_status"] not in ("VALID", "EXPIRING", "WAIVED"):
        return False
    if event["jurisdiction_state"] not in adj["licensed_states"] \
            and adj["credential_status"] != "WAIVED":
        return False
    if derive.adjuster_open_assignment_count(adj["id"]) >= adj["max_open_claims"]:
        return False
    if role == "DESK" and not adj["desk_certified"]:
        return False
    if role == "AERIAL" and not adj["aerial_certified"]:
        return False
    if rest_conflict(adj["id"], start, end):
        return False
    return True


def select_adjuster(event, role, start, end):
    pool = [a for a in store.adjusters.values()
            if adjuster_eligible(a, event, role, start, end)]
    if not pool:
        fail("ERR_NO_ELIGIBLE_ADJUSTER")
    pool.sort(key=lambda a: (-derive.adjuster_score(a), -a["max_open_claims"],
                             a["created_at"], a["_seq"]))
    return pool[0]


# --------------------------------------------------------------------------
# Vendor selector (PRD 3.9)
# --------------------------------------------------------------------------
def vendor_eligible(firm, claim, required_type):
    if firm["status"] != "ACTIVATED":
        return False
    if firm["activated_for_event_id"] != claim["event_id"]:
        return False
    if claim["loss_state"] not in firm["service_states"]:
        return False
    if derive.firm_open_job_count(firm["id"]) >= firm["max_concurrent_jobs"]:
        return False
    if firm["vendor_type"] != required_type:
        return False
    return True


def select_vendor(claim, required_type):
    pool = [f for f in store.vendor_firms.values()
            if vendor_eligible(f, claim, required_type)]
    if not pool:
        fail("ERR_NO_ELIGIBLE_VENDOR")
    pool.sort(key=lambda f: (-dec(f["performance_score"]),
                             -(f["max_concurrent_jobs"]
                               - derive.firm_open_job_count(f["id"])),
                             f["created_at"], f["_seq"]))
    return pool[0]


# --------------------------------------------------------------------------
# Housing capacity
# --------------------------------------------------------------------------
def nightly_capacity_exceeded(block, deployment):
    """AGGREGATE-NIGHTLY rule: only deployments sharing a night compete."""
    new_nights = night_set(deployment["window_start_utc"], deployment["window_end_utc"])
    if not new_nights:
        return False
    per_night = {}
    for d in store.deployments.values():
        if d["id"] == deployment["id"]:
            continue
        if d.get("housing_block_id") != block["id"]:
            continue
        if d["status"] not in ("CONFIRMED", "ON_SITE"):
            continue
        for night in night_set(d["window_start_utc"], d["window_end_utc"]):
            if night in new_nights:
                per_night[night] = per_night.get(night, 0) + int(d["rooms_reserved"])
    demand = int(deployment["rooms_reserved"])
    for night in new_nights:
        if per_night.get(night, 0) + demand > int(block["rooms_total"]):
            return True
    return False


def sync_block_occupancy(block):
    if block is None:
        return
    available = int(block["rooms_total"]) - derive.block_rooms_occupied(block["id"])
    if block["status"] == "ACTIVE" and available == 0:
        block["status"] = "EXHAUSTED"
        touch(block)
    elif block["status"] == "EXHAUSTED" and available >= 1:
        block["status"] = "ACTIVE"
        touch(block)


def sync_firm_capacity(firm):
    if firm is None:
        return
    open_jobs = derive.firm_open_job_count(firm["id"])
    if firm["status"] == "ACTIVATED" and open_jobs >= firm["max_concurrent_jobs"]:
        firm["status"] = "CAPACITY_HOLD"
        touch(firm)
    elif firm["status"] == "CAPACITY_HOLD" and open_jobs < firm["max_concurrent_jobs"]:
        firm["status"] = "ACTIVATED"
        touch(firm)


# --------------------------------------------------------------------------
# Cascades
# --------------------------------------------------------------------------
def rest_adjuster(adjuster):
    """Link 2 of the demobilization / cancellation chains."""
    if adjuster is None:
        return
    if adjuster["deployment_status"] == "DEPLOYED":
        adjuster["deployment_status"] = "RESTING"
    adjuster["last_demobilized_at_utc"] = clock_now()
    touch(adjuster)


def cancel_adjuster_live_assignments(adjuster_id):
    """Link 3: SCHEDULED and IN_PROGRESS work is cancelled, claims regress."""
    regressed = []
    for a in sorted_rows([x for x in store.assignments.values()
                          if x["adjuster_id"] == adjuster_id
                          and x["status"] in ("SCHEDULED", "IN_PROGRESS")]):
        a["status"] = "CANCELLED"
        touch(a)
        if sync.regress_claim(a["claim_id"]):
            regressed.append(a["claim_id"])
    return regressed


def revision_after_completion(claim, memo):
    """The REVISION entry that accompanies a completed inspection."""
    current = derive.claim_case_reserve(claim["id"])
    delta = calc.reserve_revision_delta(claim, current)
    return append_entry(claim, "REVISION", delta, Decimal("0.00"), memo)


def release_event_housing(event_id, statuses):
    for b in store.housing_blocks.values():
        if b["event_id"] == event_id and b["status"] in statuses:
            b["status"] = "RELEASED"
            touch(b)


def deactivate_event_vendors(event_id):
    for f in store.vendor_firms.values():
        if f["activated_for_event_id"] == event_id and f["status"] == "ACTIVATED":
            f["status"] = "NETWORK_INACTIVE"
            f["activated_for_event_id"] = None
            touch(f)
