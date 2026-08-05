"""DailyComplianceRecord lifecycle: minting, back-fill, finalization, reopening.

PRD 3.2 "How service dates come into existence" and PRD 3.4 "Scoring the day".
"""

import clock
import derived
import store
from store import DB


def mint_record(episode, service_date):
    """Mint the PENDING record for a service date when the episode has none."""
    existing = derived.find_record(episode["id"], service_date)
    if existing is not None:
        return existing
    return store.make_row("compliance_days", {
        "episode_id": episode["id"],
        "service_date": service_date,
        "kit_deployed_all_day": True,
        "status": "PENDING",
        "finalized_at": None,
        "carve_out_reason": None,
    })


def backfill(episode):
    """Mint a PENDING record for every still-missing date in
    [admitted_at date .. current clock date] inclusive (PRD 3.2)."""
    start_date = clock.utc_date(clock.parse_iso(episode["admitted_at"]))
    end_date = clock.today_date()
    for service_date in clock.date_range_inclusive(start_date, end_date):
        mint_record(episode, service_date)


def void_built_claims(episode_id):
    """A carve-out drives every claim of the episode still in BUILT to VOIDED."""
    for claim in store.ordered(DB.claims.values()):
        if claim["episode_id"] != episode_id:
            continue
        if claim["status"] != "BUILT":
            continue
        claim["status"] = "VOIDED"
        store.touch(claim)


def finalize(record):
    """Commit the daily verdict onto a PENDING record (PRD 3.4)."""
    if record["status"] != "PENDING":
        return record
    verdict, reason = derived.score_record(record)
    record["status"] = verdict
    record["carve_out_reason"] = reason
    record["finalized_at"] = clock.now_raw()
    store.touch(record)
    if verdict == "CARVED_OUT":
        void_built_claims(record["episode_id"])
    return record


def reopen(record):
    """An amendment drives a finalized record back to PENDING (PRD 3.3)."""
    if record["status"] not in ("COMPLIANT", "CARVED_OUT"):
        return record
    record["status"] = "PENDING"
    record["finalized_at"] = None
    record["carve_out_reason"] = None
    store.touch(record)
    return record


def finalize_all_pending(episode):
    """The discharge sweep: finalize every record still PENDING, in date order."""
    for record in derived.episode_records(episode["id"]):
        if record["status"] == "PENDING":
            finalize(record)
