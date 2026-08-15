"""Core shared services: record lifecycle, payer lookups, cadence math, cascades."""
from db import db, next_seq
from util import (
    logical_ts,
    today,
    parse_date,
    add_days,
    add_months,
)

# ---------------------------------------------------------------------------
# Record lifecycle (PRD 2.4): id + created_at + updated_at + version on all
# nine entities; every mutation bumps version and refreshes updated_at.
# ---------------------------------------------------------------------------

def new_record(collection, fields):
    rec = dict(fields)
    rec["id"] = __import__("util").new_id()
    ts = logical_ts()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    rec["updated_at"] = logical_ts()
    rec["version"] = int(rec.get("version", 1)) + 1


def public(rec):
    """Strip internal bookkeeping keys before serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_patient(patient_id):
    return db["patients"].get(patient_id)


def payer_for_patient(patient):
    if patient is None:
        return None
    return db["payer_policies"].get(patient.get("payer_policy_id"))


def plans_of_patient(patient_id):
    return [p for p in db["component_supply_plans"].values() if p["patient_id"] == patient_id]


def current_rental_contract(patient):
    cid = patient.get("current_rental_contract_id")
    if cid is None:
        return None
    return db["rental_contracts"].get(cid)


def rental_contract_for_enrollment(enrollment_id):
    matches = [c for c in db["rental_contracts"].values() if c["device_enrollment_id"] == enrollment_id]
    if not matches:
        return None
    matches.sort(key=lambda c: c["_seq"])
    return matches[-1]


# ---------------------------------------------------------------------------
# Cadence (PRD 3.5): per-component minimum days between billable resupplies.
# ---------------------------------------------------------------------------

def cadence_days_for(payer, component_type):
    return {
        "MASK": payer["mask_cadence_days"],
        "CUSHION": payer["cushion_cadence_days"],
        "FILTER": payer["filter_cadence_days"],
        "TUBING": payer["tubing_cadence_days"],
    }[component_type]


# Payer fee-schedule snapshot per component (integer cents per unit). The payer
# policy carries no fee fields, so the schedule is a deterministic constant;
# the authorized order's unit_allowable_cents drives the invoice math.
FEE_SCHEDULE_CENTS = {
    "MASK": 12500,
    "CUSHION": 4500,
    "FILTER": 900,
    "TUBING": 2200,
}


# ---------------------------------------------------------------------------
# Compliance hold / resume cascade (PRD 3.4)
# ---------------------------------------------------------------------------

def apply_compliance_cascade(patient, is_compliant):
    """Drive Patient ACTIVE_THERAPY <-> NON_COMPLIANT_HOLD plus plan/rental effects."""
    status = patient["patient_status"]
    if not is_compliant and status == "ACTIVE_THERAPY":
        patient["patient_status"] = "NON_COMPLIANT_HOLD"
        for plan in plans_of_patient(patient["id"]):
            if plan["plan_status"] == "ACTIVE":
                plan["plan_status"] = "SUSPENDED_NON_COMPLIANCE"
                touch(plan)
        contract = current_rental_contract(patient)
        if contract is not None and contract["billing_status"] == "BILLING":
            contract["billing_status"] = "PAUSED_NON_COMPLIANCE"
            touch(contract)
    elif is_compliant and status == "NON_COMPLIANT_HOLD":
        patient["patient_status"] = "ACTIVE_THERAPY"
        for plan in plans_of_patient(patient["id"]):
            if plan["plan_status"] == "SUSPENDED_NON_COMPLIANCE":
                plan["plan_status"] = "ACTIVE"
                touch(plan)
        contract = current_rental_contract(patient)
        if contract is not None and contract["billing_status"] == "PAUSED_NON_COMPLIANCE":
            contract["billing_status"] = "BILLING"
            touch(contract)


# ---------------------------------------------------------------------------
# Discontinuation finalization cascade (PRD 3.8): synchronous with the
# retrieval-case reconcile / close-unrecoverable call (and swept as backstop).
# ---------------------------------------------------------------------------

def cascade_patient_discontinued(patient, enrollment_id, recovered: bool) -> bool:
    """Patient DISCONTINUING -> DISCONTINUED with plan/rental/enrollment effects.

    Returns True when this call actually transitioned the patient.
    """
    if patient is None or patient["patient_status"] != "DISCONTINUING":
        return False
    patient["patient_status"] = "DISCONTINUED"
    touch(patient)
    for plan in plans_of_patient(patient["id"]):
        if plan["plan_status"] != "CLOSED":
            plan["plan_status"] = "CLOSED"
            touch(plan)
    contract = current_rental_contract(patient)
    if contract is not None and contract["billing_status"] not in (
        "CONVERTED_TO_OWNERSHIP",
        "TERMINATED",
    ):
        contract["billing_status"] = "TERMINATED"
        touch(contract)
    enrollment = db["device_enrollments"].get(enrollment_id) if enrollment_id else None
    if enrollment is not None:
        target = "RETRIEVED" if recovered else "DECOMMISSIONED"
        if enrollment["enrollment_status"] != target:
            enrollment["enrollment_status"] = target
            touch(enrollment)
    return True


# ---------------------------------------------------------------------------
# Outstanding balance (PRD 3.5): sum of INVOICED orders' patient responsibility.
# ---------------------------------------------------------------------------

def compute_outstanding_balance_cents(patient_id) -> int:
    return sum(
        int(o.get("patient_responsibility_cents") or 0)
        for o in db["resupply_orders"].values()
        if o["patient_id"] == patient_id and o["fulfillment_status"] == "INVOICED"
    )


# ---------------------------------------------------------------------------
# Mask-exchange window anchor selector (PRD 3.6)
# ---------------------------------------------------------------------------

def select_window_anchor(patient, enrollment, payer, exclude_id=None):
    """Anchor for a new MaskExchange:
    - no prior exchange -> enrollment.setup_completed_on
    - prior window still open (today <= prior.anchor + window) -> prior.anchor
    - else -> prior.completed_on (rolls the window forward)
    """
    priors = [
        e for e in db["mask_exchanges"].values()
        if e["patient_id"] == patient["id"] and e["id"] != exclude_id
    ]
    priors.sort(key=lambda e: e["_seq"], reverse=True)
    if not priors:
        return enrollment.get("setup_completed_on")
    prior = priors[0]
    prior_anchor = prior.get("window_anchor_on")
    if prior_anchor is not None:
        window_end = add_days(parse_date(prior_anchor), int(payer["mask_exchange_window_days"]))
        if today() <= window_end:
            return prior_anchor
    return prior.get("completed_on")


def completed_exchanges_in_window(patient_id, window_anchor_on, exclude_id):
    return [
        e for e in db["mask_exchanges"].values()
        if e["patient_id"] == patient_id
        and e["exchange_status"] == "COMPLETED"
        and e.get("window_anchor_on") == window_anchor_on
        and e["id"] != exclude_id
    ]


# ---------------------------------------------------------------------------
# Rental month anniversaries (PRD 3.7)
# ---------------------------------------------------------------------------

def rental_period_due_date(contract, months_billed=None):
    billed = contract["rental_months_billed"] if months_billed is None else months_billed
    return add_months(parse_date(contract["rental_start_on"]), billed + 1)
