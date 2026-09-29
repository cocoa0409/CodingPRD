"""Derived-field recomputation and cascade propagation (PRD section 2.9)."""

from decimal import Decimal

import calc
import store
from common import minutes_between, r2

ZERO = Decimal("0")


def apply_changes(row, changes):
    """Write changed fields; advance updated_at / version only if something moved."""
    mutated = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            mutated = True
    if mutated:
        store.touch(row)
    return mutated


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def site_of_plant(plant):
    return store.sites.get(plant["site_id"])


def site_of_batch(batch):
    plant = store.plants.get(batch["plant_id"])
    if plant is None:
        return None
    return store.sites.get(plant["site_id"])


def site_of_attribute(attribute):
    batch = store.injection_batches.get(attribute["injection_batch_id"])
    if batch is None:
        return None
    return site_of_batch(batch)


def wells_of_site(site_id):
    return [w for w in store.wells.values() if w["site_id"] == site_id]


def plants_of_site(site_id):
    return store.ordered([p for p in store.plants.values() if p["site_id"] == site_id])


def batches_of_plant(plant_id):
    return store.ordered(
        [b for b in store.injection_batches.values() if b["plant_id"] == plant_id]
    )


# ---------------------------------------------------------------------------
# LandfillSite derived fields and ledgers
# ---------------------------------------------------------------------------

def recompute_site_flow(site):
    collected = ZERO
    denominator = ZERO
    for well in wells_of_site(site["id"]):
        if well["operating_state"] in ("ONLINE", "THROTTLED"):
            collected += well["current_flow_scfm"]
        if well["operating_state"] != "DECOMMISSIONED":
            denominator += well["target_flow_scfm"]
    collected = r2(collected)
    if denominator == 0:
        efficiency = r2(ZERO)
    else:
        efficiency = r2(collected * Decimal("100") / denominator)
    apply_changes(
        site,
        {"collected_flow_scfm": collected, "collection_efficiency_pct": efficiency},
    )


def move_energy(site, produced=ZERO, injected=ZERO, flared=ZERO, vented=ZERO):
    apply_changes(
        site,
        {
            "energy_produced_mmbtu": r2(site["energy_produced_mmbtu"] + produced),
            "energy_injected_mmbtu": r2(site["energy_injected_mmbtu"] + injected),
            "energy_flared_mmbtu": r2(site["energy_flared_mmbtu"] + flared),
            "energy_vented_mmbtu": r2(site["energy_vented_mmbtu"] + vented),
        },
    )


def move_rins(site, generated=0, available=0, retired=0, reversed_=0):
    apply_changes(
        site,
        {
            "rin_generated_total": site["rin_generated_total"] + generated,
            "rin_available_count": site["rin_available_count"] + available,
            "rin_retired_count": site["rin_retired_count"] + retired,
            "rin_reversed_count": site["rin_reversed_count"] + reversed_,
        },
    )


def move_payable(site, delta):
    apply_changes(site, {"royalty_payable_usd": r2(site["royalty_payable_usd"] + delta)})


def recompute_compliance_posture(site):
    posture = "COMPLIANT"
    reports = [r for r in store.compliance_reports.values() if r["site_id"] == site["id"]]
    for report in reports:
        if report["status"] in ("SUBMITTED", "UNDER_REVIEW", "RETURNED", "ACCEPTED") and report[
            "exceedance_flag"
        ]:
            posture = "VIOLATION"
            break
    else:
        for report in reports:
            if report["status"] == "RETURNED":
                posture = "WATCH"
                break
    apply_changes(site, {"compliance_posture": posture})


# ---------------------------------------------------------------------------
# ProcessingPlant derived fields
# ---------------------------------------------------------------------------

def recompute_plant_availability(plant):
    closed = [
        e
        for e in store.downtime_events.values()
        if e["plant_id"] == plant["id"] and e["status"] == "CLOSED" and e["end_at"] is not None
    ]
    downtime_minutes, flare_minutes, factor = calc.availability(closed, store.now())
    apply_changes(
        plant,
        {
            "downtime_minutes_mtd": downtime_minutes,
            "flare_minutes_mtd": flare_minutes,
            "availability_factor_pct": factor,
        },
    )


# ---------------------------------------------------------------------------
# Injection batch divert / void cascades
# ---------------------------------------------------------------------------

DIVERTIBLE = ("DRAFT", "PENDING_ANALYSIS", "ON_SPEC", "OFF_SPEC", "NOMINATED")
CASCADE_DIVERTIBLE = ("DRAFT", "PENDING_ANALYSIS", "ON_SPEC", "NOMINATED")


def divert_batch(batch, curtail_reason="UPSTREAM_DIVERT"):
    """Land a batch on DIVERTED_TO_FLARE and apply its ledger consequences."""
    gross = batch["gross_mmbtu"]
    apply_changes(batch, {"status": "DIVERTED_TO_FLARE"})

    site = site_of_batch(batch)
    if site is not None:
        move_energy(site, produced=gross, flared=gross)

    nomination_id = batch["nomination_id"]
    if nomination_id:
        nomination = store.nominations.get(nomination_id)
        if nomination is not None:
            changes = {"committed_dth": r2(nomination["committed_dth"] - gross)}
            if nomination["status"] in ("CONFIRMED", "SCHEDULED"):
                changes["status"] = "CURTAILED"
                changes["curtail_reason"] = curtail_reason
            apply_changes(nomination, changes)


def reverse_attribute(attribute, reason):
    site = site_of_attribute(attribute)
    apply_changes(attribute, {"status": "REVERSED", "reversal_reason": reason})
    if site is not None and attribute["program"] == "RIN_D3":
        move_rins(site, available=-attribute["rin_count"], reversed_=attribute["rin_count"])


def attributes_of_batch(batch_id):
    return store.ordered(
        [a for a in store.attribute_batches.values() if a["injection_batch_id"] == batch_id]
    )


# ---------------------------------------------------------------------------
# Plant process-mode cascades
# ---------------------------------------------------------------------------

def divert_in_flight_batches(plant):
    for batch in batches_of_plant(plant["id"]):
        if batch["status"] in CASCADE_DIVERTIBLE:
            divert_batch(batch)


def open_shortfall_downtime(plant):
    event = store.new_row(
        plant_id=plant["id"],
        start_at=store.now(),
        end_at=None,
        cause="WELLFIELD_SHORTFALL",
        disposition="FLARED",
        status="OPEN",
        flared_mmbtu=r2(ZERO),
        vented_mmbtu=r2(ZERO),
        duration_minutes=r2(ZERO),
        auto_generated=True,
    )
    store.downtime_events[event["id"]] = event
    return event


def plant_to_flaring(plant, automatic):
    """UPGRADING -> FLARING, manual or automatic."""
    changes = {"process_mode": "FLARING"}
    if automatic:
        changes["spec_status"] = "OFF_SPEC"
    apply_changes(plant, changes)
    if automatic:
        open_shortfall_downtime(plant)
    divert_in_flight_batches(plant)


def close_auto_downtime(plant):
    """FLARING -> UPGRADING closes every OPEN auto_generated record."""
    events = store.ordered(
        [
            e
            for e in store.downtime_events.values()
            if e["plant_id"] == plant["id"] and e["status"] == "OPEN" and e["auto_generated"]
        ]
    )
    for event in events:
        end_at = store.now()
        duration = r2(minutes_between(event["start_at"], end_at))
        if duration < 0:
            duration = r2(ZERO)
        apply_changes(
            event,
            {
                "status": "CLOSED",
                "end_at": end_at,
                "flared_mmbtu": r2(ZERO),
                "vented_mmbtu": r2(ZERO),
                "duration_minutes": duration,
            },
        )
    recompute_plant_availability(plant)


def plant_to_upgrading(plant):
    apply_changes(plant, {"process_mode": "UPGRADING"})
    close_auto_downtime(plant)


# ---------------------------------------------------------------------------
# Wellfield shortfall / recovery propagation
# ---------------------------------------------------------------------------

def propagate_shortfall(site):
    """Any UPGRADING plant starved below its minimum feed is forced to flare."""
    for plant in plants_of_site(site["id"]):
        if plant["process_mode"] == "UPGRADING" and site["collected_flow_scfm"] < plant["min_feed_scfm"]:
            plant_to_flaring(plant, automatic=True)


def propagate_recovery(site):
    """Any FLARING, ON_SPEC plant with enough feed returns to upgrading."""
    for plant in plants_of_site(site["id"]):
        if (
            plant["process_mode"] == "FLARING"
            and plant["spec_status"] == "ON_SPEC"
            and site["collected_flow_scfm"] >= plant["min_feed_scfm"]
        ):
            plant_to_upgrading(plant)
