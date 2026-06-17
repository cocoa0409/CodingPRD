"""Business logic: serialization, calculations, billing recompute, cascades.

All calculation rules follow PRD section 2.7, 3.5-3.9 and scaffold 1.3 exactly.
"""
import math

from db import db, now_iso, touch
from helpers import round_half_up

# Constants (scaffold 1.3)
SQFT_PER_MIN = 50
CALLBACK_FACTOR = 0.40
OVERAGE_MULTIPLIER = 1.5
MAJOR_BONUS_PCT = 0.05


# ---------------------------------------------------------------------------
# Serialization: present an entity dict to the client (drop internal fields)
# ---------------------------------------------------------------------------
_ACCOUNT_FIELDS = ["id", "name", "billing_email", "status", "open_complaint_count",
                   "created_at", "updated_at", "version"]
_SITE_FIELDS = ["id", "account_id", "contact_user_id", "label", "cleanable_sqft",
                "floor_type", "quality_target", "status", "created_at", "updated_at", "version"]
_CONTRACT_FIELDS = ["id", "site_id", "monthly_base_cents", "hourly_rate_cents",
                    "callback_credit_pct", "quality_holdback_pct", "status",
                    "created_at", "updated_at", "version"]
_SCHEDULE_FIELDS = ["id", "site_id", "weekday", "window_start_min", "window_end_min",
                    "assigned_crew_id", "status", "created_at", "updated_at", "version"]
_CREW_FIELDS = ["id", "full_name", "shift_capacity_min", "status",
                "created_at", "updated_at", "version"]
_VISIT_FIELDS = ["id", "site_id", "schedule_id", "crew_id", "visit_kind", "service_date",
                 "planned_start_min", "planned_end_min", "estimated_labor_min",
                 "actual_labor_min", "periodic_job_id", "complaint_id", "billing_period_id",
                 "status", "created_at", "updated_at", "version"]
_TIME_ENTRY_FIELDS = ["id", "visit_id", "crew_id", "clock_in_min", "clock_out_min",
                      "clocked_min", "status", "created_at", "updated_at", "version"]
_INSPECTION_FIELDS = ["id", "visit_id", "score", "deficient", "notes",
                      "created_at", "updated_at", "version"]
_PERIODIC_JOB_FIELDS = ["id", "site_id", "job_type", "quoted_hours", "requested_date",
                        "visit_id", "status", "created_at", "updated_at", "version"]
_COMPLAINT_FIELDS = ["id", "site_id", "visit_id", "severity", "description",
                     "callback_visit_id", "credit_applied_cents", "status",
                     "created_at", "updated_at", "version"]
_BILLING_PERIOD_FIELDS = ["id", "contract_id", "period_month", "base_cents",
                          "periodic_cents", "callback_credit_cents", "holdback_cents",
                          "total_cents", "mean_quality_score", "status",
                          "created_at", "updated_at", "version"]
_INVOICE_LINE_FIELDS = ["id", "billing_period_id", "line_type", "amount_cents",
                        "memo", "created_at"]
_SUPPLY_ORDER_FIELDS = ["id", "site_id", "sku", "quantity", "status",
                        "created_at", "updated_at", "version"]

_FIELD_MAP = {
    "account": _ACCOUNT_FIELDS,
    "site": _SITE_FIELDS,
    "contract": _CONTRACT_FIELDS,
    "schedule": _SCHEDULE_FIELDS,
    "crew": _CREW_FIELDS,
    "visit": _VISIT_FIELDS,
    "time_entry": _TIME_ENTRY_FIELDS,
    "inspection": _INSPECTION_FIELDS,
    "periodic_job": _PERIODIC_JOB_FIELDS,
    "complaint": _COMPLAINT_FIELDS,
    "billing_period": _BILLING_PERIOD_FIELDS,
    "invoice_line": _INVOICE_LINE_FIELDS,
    "supply_order": _SUPPLY_ORDER_FIELDS,
}


def serialize(entity, kind):
    fields = _FIELD_MAP[kind]
    return {f: entity.get(f) for f in fields}


# ---------------------------------------------------------------------------
# Calculation: estimate_labor_minutes (scaffold 1.3 / PRD 3.3)
# ---------------------------------------------------------------------------
def estimate_labor_minutes(site, visit_kind, periodic_job=None):
    base_min = math.ceil(site["cleanable_sqft"] / SQFT_PER_MIN)
    if visit_kind == "ROUTINE":
        return base_min
    if visit_kind == "CALLBACK":
        return math.ceil(base_min * CALLBACK_FACTOR)
    if visit_kind == "PERIODIC":
        # quote drives estimate, not sqft
        return math.ceil(periodic_job["quoted_hours"] * 60)
    return base_min


# ---------------------------------------------------------------------------
# Calculation: actual_labor_minutes (scaffold 1.3 / PRD 3.5)
# ---------------------------------------------------------------------------
def actual_labor_minutes(visit):
    entries = [te for te in db.time_entries.values()
               if te["visit_id"] == visit["id"] and te["status"] == "COMPLETED"]
    entries.sort(key=lambda te: (te.get("created_at", ""), te.get("_seq", 0)))
    total = 0
    for te in entries:
        total += te["clocked_min"]
    return total


# ---------------------------------------------------------------------------
# Calculation: periodic_charge_cents (scaffold 1.3 / PRD 3.6)
# ---------------------------------------------------------------------------
def periodic_charge_cents(visit, periodic_job, contract):
    quoted_min = math.ceil(periodic_job["quoted_hours"] * 60)
    actual_min = visit["actual_labor_min"]
    billable_min = max(quoted_min, actual_min)
    overage_min = max(0, actual_min - quoted_min)
    straight_min = billable_min - overage_min
    rate_per_min = contract["hourly_rate_cents"] / 60.0
    straight_cents = round_half_up(straight_min * rate_per_min)
    overage_cents = round_half_up(overage_min * rate_per_min * OVERAGE_MULTIPLIER)
    return straight_cents + overage_cents


# ---------------------------------------------------------------------------
# Calculation: callback_credit (scaffold 1.3 / PRD 3.7)
# ---------------------------------------------------------------------------
def callback_credit(complaint, contract):
    base = contract["monthly_base_cents"]
    pct = contract["callback_credit_pct"]
    if complaint["severity"] == "MAJOR":
        pct = pct + MAJOR_BONUS_PCT
    raw = round_half_up(base * pct)
    return min(raw, base)


# ---------------------------------------------------------------------------
# Billing period total recompute (scaffold 1.3 / PRD 3.9)
# ---------------------------------------------------------------------------
def _captured_visits(period):
    return [v for v in db.visits.values() if v.get("billing_period_id") == period["id"]]


def _period_mean_quality(period):
    """Mean Inspection.score over COMPLETED ROUTINE visits captured into the period.
    One inspection per visit; if several, use the latest by created_at ASC tie-break.
    Returns None if no such inspection.
    """
    scores = []
    for v in _captured_visits(period):
        if v["status"] != "COMPLETED" or v["visit_kind"] != "ROUTINE":
            continue
        insps = [i for i in db.inspections.values() if i["visit_id"] == v["id"]]
        if not insps:
            continue
        insps.sort(key=lambda i: (i.get("created_at", ""), i.get("_seq", 0)))
        scores.append(insps[-1]["score"])
    if not scores:
        return None
    return sum(scores) / len(scores)


def compute_period_total(period, final):
    """Recompute the period's derived figures in PINNED order (scaffold 1.3)."""
    contract = db.contracts.get(period["contract_id"])
    site = db.sites.get(contract["site_id"]) if contract else None

    # (1) base_cents is the snapshot taken at open; do not recompute it here.
    base_cents = period["base_cents"]

    # (2) periodic_cents = sum of periodic_charge_cents over captured PERIODIC visits.
    periodic_total = 0
    for v in _captured_visits(period):
        if v["visit_kind"] == "PERIODIC" and v["status"] == "COMPLETED":
            pj = db.periodic_jobs.get(v.get("periodic_job_id"))
            if pj is not None and contract is not None:
                periodic_total += periodic_charge_cents(v, pj, contract)
    period["periodic_cents"] = periodic_total

    # (3) callback_credit_cents = sum of credit_applied_cents over RESOLVED complaints
    #     posted to this period.
    credit_total = 0
    for c in db.complaints.values():
        if c.get("posted_billing_period_id") == period["id"]:
            credit_total += c.get("credit_applied_cents", 0)
    period["callback_credit_cents"] = credit_total

    # (4) mean_quality_score
    mean_q = _period_mean_quality(period)
    period["mean_quality_score"] = mean_q

    # (5) holdback_cents
    if not final:
        holdback = 0
    else:
        if mean_q is not None and site is not None and mean_q < site["quality_target"]:
            holdback = round_half_up(base_cents * contract["quality_holdback_pct"])
        else:
            holdback = 0
    period["holdback_cents"] = holdback

    # (6) total_cents
    period["total_cents"] = base_cents + periodic_total - credit_total - holdback
    return period


# ---------------------------------------------------------------------------
# Account derived field: open_complaint_count (PRD 3.1 / 3.7)
# ---------------------------------------------------------------------------
_OPEN_COMPLAINT_STATES = {"OPEN", "ACKNOWLEDGED", "CALLBACK_SCHEDULED"}


def recompute_open_complaint_count(account):
    site_ids = {s["id"] for s in db.sites.values() if s["account_id"] == account["id"]}
    count = 0
    for c in db.complaints.values():
        if c["site_id"] in site_ids and c["status"] in _OPEN_COMPLAINT_STATES:
            count += 1
    account["open_complaint_count"] = count
    touch(account)


def account_for_site(site):
    return db.accounts.get(site["account_id"])


def account_for_contract(contract):
    site = db.sites.get(contract["site_id"])
    return account_for_site(site) if site else None
