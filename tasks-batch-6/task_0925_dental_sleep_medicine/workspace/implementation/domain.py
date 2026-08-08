"""Shared business helpers: the cascades of PRD 2.11, the mutate-then-reject
rungs, the standard-written-order selection, and list assembly."""

from decimal import Decimal

import calc
from access import ordered, touch
from envelope import listing
from errors import fail
from serializers import dump_all
from store import DB, add_days, clock_date, dec


# ---------------------------------------------------------------- lookups

def referral_of_appliance(appliance):
    lab_order = DB["lab_orders"].get(appliance.get("lab_order_id"))
    if lab_order is None:
        return None
    return DB["referrals"].get(lab_order.get("referral_id"))


def patient_of(row_patient_id):
    return DB["patients"].get(row_patient_id)


def medical_payer_of(patient):
    if patient is None:
        return None
    return DB["payers"].get(patient.get("medical_payer_id"))


def visits_of(appliance_id):
    return [v for v in DB["titration_visits"].values() if v["appliance_id"] == appliance_id]


def open_visits_of(appliance_id):
    return [v for v in visits_of(appliance_id) if v["status"] in ("SCHEDULED", "HELD")]


def last_resolved_visit(appliance_id):
    """The appliance's most recent APPLIED or REDUCED visit, by applied_on."""
    resolved = [v for v in visits_of(appliance_id)
                if v["status"] in ("APPLIED", "REDUCED") and v.get("applied_on") is not None]
    if not resolved:
        return None
    return sorted(resolved, key=lambda v: (v["applied_on"], v["created_at"], v["_seq"]))[-1]


# ------------------------------------------------------------ recomputation

def recompute_advancement(appliance):
    """Conservation 1: starting advancement plus the APPLIED/REDUCED increments."""
    total = dec(appliance["starting_advancement_mm"] or 0)
    count = 0
    for visit in ordered(visits_of(appliance["id"])):
        if visit["status"] in ("APPLIED", "REDUCED"):
            total = total + dec(visit["applied_increment_mm"] or 0)
            count += 1
    appliance["current_advancement_mm"] = total.quantize(Decimal("0.01"))
    appliance["applied_visit_count"] = count


def recompute_loop_count(provider_id):
    """open_efficacy_loop_count counts SUBMITTED or DISPUTED reports for this
    referring physician; the provider row is written only when it changes."""
    provider = DB["providers"].get(provider_id)
    if provider is None:
        return
    total = 0
    for report in DB["efficacy_reports"].values():
        if report["status"] not in ("SUBMITTED", "DISPUTED"):
            continue
        referral = DB["referrals"].get(report["referral_id"])
        if referral is not None and referral["referring_physician_id"] == provider_id:
            total += 1
    if provider["open_efficacy_loop_count"] != total:
        provider["open_efficacy_loop_count"] = total
        touch(provider)


def recompute_records_frozen(patient):
    frozen = any(h["patient_id"] == patient["id"] and h["status"] == "OPEN"
                 for h in DB["audit_holds"].values())
    if patient["records_frozen"] != frozen:
        patient["records_frozen"] = frozen
        touch(patient)


# ------------------------------------------------------- rung 18 (referral)

def rung18_diagnosis_currency(referral):
    """Mutate then reject: persist EXPIRED, cascade, then raise."""
    valid_until = referral.get("diagnosis_valid_until")
    if valid_until is None or clock_date() <= valid_until:
        return
    if referral["status"] not in ("ISSUED", "ACCEPTED"):
        return
    was_accepted = referral["status"] == "ACCEPTED"
    referral["status"] = "EXPIRED"
    touch(referral)
    if was_accepted:
        for lab_order in DB["lab_orders"].values():
            if lab_order["referral_id"] == referral["id"] and lab_order["status"] == "RECORDS_CAPTURED":
                lab_order["status"] = "CANCELLED"
                touch(lab_order)
    fail("ERR_DIAGNOSIS_EXPIRED", "The referral's diagnosis is no longer current.")


# ------------------------------------------ rungs 26-28 (standard written order)

def newest_signed_written_order(patient_id, hcpcs):
    rows = [w for w in DB["written_orders"].values()
            if w["patient_id"] == patient_id
            and w["item_hcpcs"] == hcpcs
            and w["status"] == "SIGNED"]
    if not rows:
        return None
    rows.sort(key=lambda w: (w["signed_on"], w["created_at"], w["_seq"]))
    return rows[-1]


def swo_ladder(patient_id, hcpcs, delivered_on):
    order = newest_signed_written_order(patient_id, hcpcs)
    if order is None:
        fail("ERR_SWO_MISSING", "No SIGNED standard written order exists for this patient and item.")
    if delivered_on is not None and order["order_date"] > delivered_on:
        fail("ERR_SWO_AFTER_DELIVERY", "The standard written order post-dates the delivery.")
    if order["f2f_age_days"] is None or order["f2f_age_days"] > calc.F2F_LOOKBACK_DAYS:
        fail("ERR_F2F_ENCOUNTER_STALE", "The supporting face-to-face encounter is stale.")
    return order


# ---------------------------------------------------------------- cascades

def void_draft_continued_use_claims(appliance_id):
    for claim in DB["claims"].values():
        if (claim["appliance_id"] == appliance_id
                and claim["claim_type"] == "CONTINUED_USE"
                and claim["status"] == "DRAFT"):
            claim["status"] = "VOIDED"
            touch(claim)


def retire_appliance(appliance):
    """Level 2/3 of the LOSS repair cascade."""
    if appliance["lifecycle_status"] == "IN_TITRATION":
        for visit in open_visits_of(appliance["id"]):
            visit["status"] = "SUPERSEDED"
            touch(visit)
    appliance["lifecycle_status"] = "RETIRED"
    appliance["recall_status"] = "NOT_SCHEDULED"
    appliance["next_recall_due_on"] = None
    touch(appliance)
    void_draft_continued_use_claims(appliance["id"])


def recall_cascade(lot):
    """The five level lot recall cascade of PRD 3.9."""
    devices = [a for a in DB["appliances"].values() if a["lot_id"] == lot["id"]]
    affected = [a for a in devices if a["lifecycle_status"] not in ("RETIRED", "REPLACED")]
    retired = [a for a in devices if a["lifecycle_status"] in ("RETIRED", "REPLACED")]

    lot["affected_device_count"] = len(affected)
    lot["retired_count"] = len(retired)
    lot["remediated_count"] = 0
    lot["pending_remediation_count"] = len(affected)

    for appliance in affected:
        # Level 1 — the safety hold.
        appliance["device_hold_status"] = "RECALL_HOLD"
        touch(appliance)
        # Level 2 — void every open titration visit.
        for visit in open_visits_of(appliance["id"]):
            visit["status"] = "VOIDED_BY_HOLD"
            touch(visit)
        # Level 3 — a device left with no open visit while in titration suspends.
        if appliance["lifecycle_status"] == "IN_TITRATION" and not open_visits_of(appliance["id"]):
            appliance["lifecycle_status"] = "TITRATION_SUSPENDED"
        # Level 4 — withdraw every open efficacy report and re-open its loop.
        for report in DB["efficacy_reports"].values():
            if report["appliance_id"] != appliance["id"]:
                continue
            if report["status"] not in ("DRAFT", "SUBMITTED", "DISPUTED"):
                continue
            report["status"] = "WITHDRAWN"
            touch(report)
            referral = DB["referrals"].get(report["referral_id"])
            if referral is not None and referral["loop_status"] != "OPEN":
                referral["loop_status"] = "OPEN"
                touch(referral)
            if referral is not None:
                recompute_loop_count(referral["referring_physician_id"])
        # Level 5 — void every draft continued-use claim.
        void_draft_continued_use_claims(appliance["id"])


def sweep_recall_postures():
    """Re-evaluated on every clock set; the LAPSED edge is tested first."""
    for appliance in DB["appliances"].values():
        if appliance["lifecycle_status"] != "ACTIVE_THERAPY":
            continue
        if appliance["recall_status"] not in ("NOT_DUE", "DUE"):
            continue
        posture = calc.recall_posture(clock_date(), appliance.get("next_recall_due_on"))
        if posture is not None and posture != appliance["recall_status"]:
            appliance["recall_status"] = posture
            touch(appliance)


# ------------------------------------------------------------------ listing

def paginate(kind, collection, filters, limit, offset, scope_pred=None):
    rows = list(DB[collection].values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    if scope_pred is not None:
        rows = [r for r in rows if scope_pred(r)]
    rows = ordered(rows)
    total = len(rows)
    page = rows[offset:offset + limit]
    return listing(dump_all(kind, page), limit, offset, total)


def live_appliance_conflict(patient_id, self_id, replaces_id):
    """Rung 20 — one live device per patient."""
    live = [a for a in DB["appliances"].values()
            if a["patient_id"] == patient_id
            and a["id"] != self_id
            and a["lifecycle_status"] in calc.LIVE_LIFECYCLE]
    if not live:
        return
    for other in live:
        if replaces_id != other["id"]:
            fail("ERR_ACTIVE_APPLIANCE_EXISTS", "The patient already holds a live appliance.")
        if other["lifecycle_status"] not in ("ACTIVE_THERAPY", "RETIRED"):
            fail("ERR_ACTIVE_APPLIANCE_EXISTS", "The predecessor device is not replaceable.")


def add_days_or_none(day, days):
    return None if day is None else add_days(day, days)
