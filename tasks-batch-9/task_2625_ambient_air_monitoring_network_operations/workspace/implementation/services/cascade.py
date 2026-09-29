"""Multi-hop cascades.  Every cascade is immediate and complete within the
request: by the time the response is written every affected row has been
mutated, its version incremented and its updated_at refreshed (PRD 2.9).
"""
import clock
from db import sorted_by_created, store, touch
from services import compute as K

DECOMMISSIONABLE_STATUSES = ("PENDING_APPROVAL", "APPROVED", "OPERATING", "OUT_OF_SERVICE")
WRITE_OFF_VALIDATION_STATUSES = ("RAW", "IN_VALIDATION", "REOPENED")
SUPERSEDE_STALE_REASONS = ("EVENT_EXCLUSION_APPLIED", "BATCH_REVALIDATED", "RECOMPUTED")


# --------------------------------------------------------------------------
# certification package scope
# --------------------------------------------------------------------------
def batch_in_package_scope(batch, pkg):
    """Monitor -> MonitoringSite -> network_id and Monitor -> ReferenceMethod ->
    pollutant_id, with batch.year == package.year (PRD 3.8)."""
    if batch["year"] != pkg["year"]:
        return False
    monitor = K.monitor_of_batch(batch)
    if monitor is None:
        return False
    site = store.sites.get(monitor["site_id"])
    if site is None or site["network_id"] != pkg["network_id"]:
        return False
    pollutant = K.pollutant_of_monitor(monitor)
    return pollutant is not None and pollutant["id"] == pkg["pollutant_id"]


def packages_covering_batch(batch):
    return [p for p in store.packages.values() if batch_in_package_scope(batch, p)]


def rerun_rollups_for_batch(batch):
    """The rollup is derived on every read, so re-running it is a recompute of
    computed fields and not a mutation of stored input."""
    for pkg in packages_covering_batch(batch):
        pkg.update(K.certification_package_rollup(pkg))


def batches_in_package_scope(pkg):
    return [b for b in store.data_batches.values() if batch_in_package_scope(b, pkg)]


def demote_submitted_batches(pkg):
    """SUBMITTED -> UNSUBMITTED while validation_status is left untouched."""
    moved = []
    for batch in sorted_by_created(batches_in_package_scope(pkg)):
        if batch["submission_status"] == "SUBMITTED":
            batch["submission_status"] = "UNSUBMITTED"
            touch(batch)
            moved.append(batch)
    return moved


# --------------------------------------------------------------------------
# design-value supersession (PRD 3.5, 3.6, 3.7)
# --------------------------------------------------------------------------
def supersede_provisional_design_values(site_id, pollutant_id, batch_year, stale_reason):
    """Every PROVISIONAL row whose three-year period includes batch_year, i.e.
    whose period_end_year is the batch's year, the year after, or two years
    after."""
    window = (batch_year, batch_year + 1, batch_year + 2)
    superseded = []
    for row in store.design_values.values():
        if row["site_id"] != site_id or row["pollutant_id"] != pollutant_id:
            continue
        if row["status"] != "PROVISIONAL":
            continue
        if row["period_end_year"] not in window:
            continue
        row["status"] = "SUPERSEDED"
        row["stale_reason"] = stale_reason
        touch(row)
        superseded.append(row)
    return superseded


def supersede_for_batch(batch, stale_reason):
    monitor = K.monitor_of_batch(batch)
    if monitor is None:
        return []
    site = store.sites.get(monitor["site_id"])
    pollutant = K.pollutant_of_monitor(monitor)
    if site is None or pollutant is None:
        return []
    return supersede_provisional_design_values(
        site["id"], pollutant["id"], batch["year"], stale_reason)


# --------------------------------------------------------------------------
# SEASONAL_SUSPENSION cascade (three hops, PRD 3.9)
# --------------------------------------------------------------------------
def seasonal_suspension(site, network):
    now = clock.now()
    # hop 1 -- the site itself
    site["status"] = "SUSPENDED"
    site["suspended_at"] = now
    touch(site)
    # hop 2 -- every OPERATING instrument at the site leaves service
    for monitor in K.monitors_of_site(site["id"]):
        if monitor["monitor_status"] == "OPERATING":
            monitor["monitor_status"] = "OUT_OF_SERVICE"
            monitor["out_of_service_since"] = now
            K.refresh_qc_posture(monitor)
            touch(monitor)
    # hop 3 -- the site's monitor count and the network's delinquency counter
    site["operating_monitor_count"] = K.operating_monitor_count(site["id"])
    if network is not None:
        network.update(K.network_census(network["id"]))
        touch(network)


# --------------------------------------------------------------------------
# reinstatement cascade (the exact inverse, three hops, PRD 3.9)
# --------------------------------------------------------------------------
def reinstatement(site, network):
    now = clock.now()
    suspended_at = site["suspended_at"]
    # hop 1 -- the site returns to service and suspended_at is cleared
    site["status"] = "OPERATING"
    site["suspended_at"] = None
    touch(site)
    # hop 2 -- only the instruments the suspension itself pulled out of service
    for monitor in K.monitors_of_site(site["id"]):
        if monitor["monitor_status"] != "OUT_OF_SERVICE":
            continue
        if suspended_at is None or monitor["out_of_service_since"] != suspended_at:
            continue
        monitor["out_of_service_day_count"] += K.whole_days_between(
            monitor["out_of_service_since"], now)
        monitor["out_of_service_since"] = None
        monitor["monitor_status"] = "OPERATING"
        # hop 3 -- both postures recomputed on each reinstated instrument
        K.refresh_qc_posture(monitor)
        touch(monitor)
    site["operating_monitor_count"] = K.operating_monitor_count(site["id"])
    if network is not None:
        network.update(K.network_census(network["id"]))
        touch(network)


# --------------------------------------------------------------------------
# SHUTDOWN / RELOCATION cascade (five hops, PRD 3.9)
# --------------------------------------------------------------------------
def decommission_cascade(site):
    """Hops 2..5: decommission the instruments, write off their unfinished
    quarters, push submitted packages back to draft, demote their quarters."""
    now = clock.now()
    # hop 2/3 -- decommission every instrument that has not already been retired
    decommissioned = []
    for monitor in K.monitors_of_site(site["id"]):
        if monitor["monitor_status"] not in DECOMMISSIONABLE_STATUSES:
            continue
        if monitor["monitor_status"] == "OUT_OF_SERVICE" and monitor["out_of_service_since"]:
            monitor["out_of_service_day_count"] += K.whole_days_between(
                monitor["out_of_service_since"], now)
            monitor["out_of_service_since"] = None
        # a decommissioned instrument keeps its last computed posture
        monitor["monitor_status"] = "DECOMMISSIONED"
        touch(monitor)
        decommissioned.append(monitor)
    # next hop -- every unfinished quarter of theirs is written off
    written_off = []
    for monitor in decommissioned:
        for batch in sorted_by_created(K.batches_of_monitor(monitor["id"])):
            if batch["validation_status"] not in WRITE_OFF_VALIDATION_STATUSES:
                continue
            batch["validation_status"] = "INVALIDATED"
            batch["batch_invalidation_reason"] = "MONITOR_DECOMMISSIONED"
            K.refresh_hour_accounting(batch)
            touch(batch)
            written_off.append(batch)
    # next hop -- packages covering those quarters re-run their rollup, and any
    # SUBMITTED package returns to DRAFT with rejection_count incremented
    returned = []
    seen = set()
    for batch in written_off:
        for pkg in packages_covering_batch(batch):
            if pkg["id"] in seen:
                continue
            seen.add(pkg["id"])
            pkg.update(K.certification_package_rollup(pkg))
            if pkg["status"] == "SUBMITTED":
                pkg["status"] = "DRAFT"
                pkg["rejection_count"] += 1
                touch(pkg)
                returned.append(pkg)
    # final hop -- the submission dimension of every quarter those packages held
    for pkg in returned:
        demote_submitted_batches(pkg)
    site["operating_monitor_count"] = K.operating_monitor_count(site["id"])
    return decommissioned, written_off, returned


def shutdown_cascade(site, network):
    site["status"] = "SHUTDOWN"
    touch(site)
    decommission_cascade(site)
    if network is not None:
        network.update(K.network_census(network["id"]))
        touch(network)


def relocation_cascade(site, replacement, network):
    site["status"] = "RELOCATED"
    touch(site)
    if replacement is not None:
        replacement["replaces_site_id"] = site["id"]
        touch(replacement)
    decommission_cascade(site)
    if network is not None:
        network.update(K.network_census(network["id"]))
        touch(network)


# --------------------------------------------------------------------------
# concurrence cascade (five hops, PRD 3.6)
# --------------------------------------------------------------------------
def concurrence_cascade(demo):
    now = clock.now()
    # hop 2 -- every PROPOSED exclusion becomes EFFECTIVE
    made_effective = []
    for exc in K.exclusions_of_demonstration(demo["id"]):
        if exc["status"] != "PROPOSED":
            continue
        exc["status"] = "EFFECTIVE"
        exc["effective_at"] = now
        touch(exc)
        made_effective.append(exc)
    demo["excluded_hour_total"] = sum(
        e["hours_affected"] for e in K.exclusions_of_demonstration(demo["id"])
        if e["status"] == "EFFECTIVE"
    )
    # hop 3 -- every referenced quarter re-runs hour accounting
    touched_batches = []
    seen = set()
    for exc in made_effective:
        batch = store.data_batches.get(exc["data_batch_id"])
        if batch is None or batch["id"] in seen:
            continue
        seen.add(batch["id"])
        K.refresh_hour_accounting(batch)
        touch(batch)
        touched_batches.append(batch)
    # hop 4 -- provisional design values covering those quarters are superseded
    for batch in touched_batches:
        supersede_for_batch(batch, "EVENT_EXCLUSION_APPLIED")
        # a completeness change also moves every package covering the quarter
        rerun_rollups_for_batch(batch)
    # hop 5 -- each affected site's attainment standing is recomputed
    for batch in touched_batches:
        monitor = K.monitor_of_batch(batch)
        if monitor is None:
            continue
        site = store.sites.get(monitor["site_id"])
        if site is not None:
            site["current_attainment_status"] = K.current_attainment_status(site["id"])


def non_concurrence_cascade(demo):
    """Every PROPOSED exclusion is REJECTED; effective_at stays null and no
    hour accounting, design value or site standing moves."""
    for exc in K.exclusions_of_demonstration(demo["id"]):
        if exc["status"] != "PROPOSED":
            continue
        exc["status"] = "REJECTED"
        touch(exc)
