"""Derived aggregates, recomputed from their definitions (PRD §2.10)."""

from db import db

POSITIONS = ("STEER", "DRIVE", "TRAILER")
VEHICLE_TYPES = ("TRACTOR", "TRAILER", "STRAIGHT_TRUCK")
CASING_STATUSES = (
    "ON_WHEEL",
    "COLLECTED",
    "INSPECTED",
    "REJECTED",
    "RETREAD_QUEUED",
    "IN_RETREAD",
    "RETREADED",
    "SCRAPPED",
)
HOLDING_STATUSES = ("COLLECTED", "INSPECTED", "REJECTED", "RETREAD_QUEUED", "IN_RETREAD")
GRADES = ("A", "B", "C", "REJECT")
TIRE_ASSET_STATUSES = ("IN_INVENTORY", "MOUNTED", "PULL_FLAGGED", "PULLED", "SCRAPPED")
ENTRY_TYPES = ("ACCRUAL", "REVERSAL", "ADJUSTMENT", "APPLICATION", "EXPIRY")
SOURCE_ENTITY_TYPES = ("CASING", "RETREAD_JOB", "SCRAP_MANIFEST", "CROSS_LOCATION_INVOICE")
JOB_STATUSES = ("SCHEDULED", "IN_PRODUCTION", "COMPLETED", "FAILED_CURE", "CANCELLED")
DISPATCH_STATUSES = ("OPEN", "DISPATCHED", "ON_SITE", "COMPLETED", "CANCELLED")
BILLING_STATUSES = ("UNBILLED", "NON_BILLABLE", "INVOICED", "BILLED_TO_NATIONAL", "SETTLED")
MANIFEST_STATUSES = ("DRAFT", "SIGNED", "TRANSPORTED", "CERTIFIED_DESTROYED", "VOIDED")
AGREEMENT_STATUSES = ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED")
INVOICE_STATUSES = ("OPEN", "SUBMITTED", "PAID", "DISPUTED")
CERT_LEVELS = ("LEVEL_1", "LEVEL_2", "TIA_CERTIFIED")
FINDING_CODES = ("COMPLIANT", "PRESSURE_DEVIATION", "TREAD_AT_PULL_POINT", "TREAD_BELOW_MIN")
OCCUPYING_JOB_STATUSES = ("SCHEDULED", "IN_PRODUCTION")
CPM_ASSET_STATUSES = ("MOUNTED", "PULL_FLAGGED", "PULLED")


# ---------------------------------------------------------------- ledger

def fleet_entries(fleet_account_id):
    return [
        e for e in db.casing_credit_entries.values()
        if e["fleet_account_id"] == fleet_account_id
    ]


def fleet_balance_cents(fleet_account_id):
    """SUM(amount_cents) over every entry of the fleet, unfiltered (PRD §2.8)."""
    return sum(e["amount_cents"] for e in fleet_entries(fleet_account_id))


def casing_provisional_credit_cents(casing_id):
    """SUM over ACCRUAL/REVERSAL/ADJUSTMENT/EXPIRY entries of the casing (PRD §2.8)."""
    return sum(
        e["amount_cents"]
        for e in db.casing_credit_entries.values()
        if e["casing_id"] == casing_id
        and e["entry_type"] in ("ACCRUAL", "REVERSAL", "ADJUSTMENT", "EXPIRY")
    )


def ledger_replay_order(rows):
    """posted_at ascending, created_at ascending as the tie-break (PRD §2.3)."""
    return sorted(rows, key=lambda e: (e["posted_at_dt"], e["created_at"], e["_seq"]))


# ---------------------------------------------------------------- aggregates

def location_holding_count(location_id):
    return sum(
        1 for c in db.casings.values()
        if c["collected_at_location_id"] == location_id and c["status"] in HOLDING_STATUSES
    )


def job_slot_minutes(job):
    return job["slot_minutes"]


def line_booked_minutes(line):
    total = 0
    for job in db.retread_jobs.values():
        if job["retread_line_id"] == line["id"] and job["status"] in OCCUPYING_JOB_STATUSES:
            total += job["slot_minutes"] + line["cure_cooldown_minutes"]
    return total


def manifest_casings(manifest_id):
    return [c for c in db.casings.values() if c["scrap_manifest_id"] == manifest_id]


def manifest_totals(manifest_id):
    rows = manifest_casings(manifest_id)
    return len(rows), sum(c["scrap_weight_lbs"] for c in rows)


def invoice_line_count(invoice_id):
    return sum(
        1 for call in db.road_service_calls.values()
        if call["cross_location_invoice_id"] == invoice_id
    )


def invoice_calls(invoice_id):
    return [
        call for call in db.road_service_calls.values()
        if call["cross_location_invoice_id"] == invoice_id
    ]


def technician_completed_call_count(technician_id):
    return sum(
        1 for call in db.road_service_calls.values()
        if call["technician_id"] == technician_id and call["dispatch_status"] == "COMPLETED"
    )


# ---------------------------------------------------------------- tire assets

def asset_surveys(tire_asset_id):
    return [s for s in db.tire_surveys.values() if s["tire_asset_id"] == tire_asset_id]


def latest_survey(tire_asset_id):
    """Greatest surveyed_at; among ties the last row by created_at ascending."""
    rows = asset_surveys(tire_asset_id)
    if not rows:
        return None
    rows.sort(key=lambda s: (s["surveyed_at_dt"], s["created_at"], s["_seq"]))
    return rows[-1]


def asset_current_tread_depth(asset):
    survey = latest_survey(asset["id"])
    if survey is not None:
        return survey["tread_depth_32nds"]
    return asset["tread_depth_at_mount_32nds"]


def asset_accumulated_miles(asset):
    survey = latest_survey(asset["id"])
    if survey is None or asset["odometer_at_mount"] is None:
        return 0
    return max(0, survey["odometer_miles"] - asset["odometer_at_mount"])


def casing_assets(casing_id):
    return [a for a in db.tire_assets.values() if a["casing_id"] == casing_id]


# ---------------------------------------------------------------- lookups

def find_policy(fleet_account_id, position):
    if position is None:
        return None
    for policy in db.tire_policies.values():
        if policy["fleet_account_id"] == fleet_account_id and policy["position"] == position:
            return policy
    return None


def active_agreement_on(fleet_account_id, anchor_date):
    """The fleet's ACTIVE agreement whose CLOSED window covers anchor_date (PRD §3.2)."""
    if anchor_date is None:
        return None
    for agreement in db.national_agreements.values():
        if agreement["fleet_account_id"] != fleet_account_id:
            continue
        if agreement["status"] != "ACTIVE":
            continue
        if agreement["effective_from_d"] <= anchor_date <= agreement["effective_to_d"]:
            return agreement
    return None


def casing_jobs(casing_id):
    return [j for j in db.retread_jobs.values() if j["casing_id"] == casing_id]


def casing_has_live_job(casing_id):
    return any(j["status"] in OCCUPYING_JOB_STATUSES for j in casing_jobs(casing_id))


def vehicle_has_live_call(vehicle_id):
    return any(
        call["vehicle_id"] == vehicle_id
        and call["dispatch_status"] in ("OPEN", "DISPATCHED", "ON_SITE")
        for call in db.road_service_calls.values()
    )
