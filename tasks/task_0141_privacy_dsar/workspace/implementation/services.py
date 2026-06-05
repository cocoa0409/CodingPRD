"""Domain services: calculations, computed fields, shared mutation primitives,
and the clock sweep. Pure-ish helpers over the in-memory store.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import store
from errors import err
from timeutil import (
    add_calendar_days,
    add_hours,
    business_days_remaining as _bdr,
)

# ---------------------------------------------------------------------------
# Constants from SCAFFOLD §1.3
# ---------------------------------------------------------------------------
BASE_DAYS = {"GDPR": 30, "CCPA": 45}
EXTENSION_DAYS = {"GDPR": 60, "CCPA": 45}

CATEGORY_WEIGHT = {
    "HEALTH": 5,
    "FINANCIAL": 4,
    "IDENTITY": 3,
    "CONTACT": 2,
    "BEHAVIORAL": 1,
}

ACTION_FOR_REQUEST_TYPE = {
    "ACCESS": "DISCLOSE",
    "DELETION": "ERASE",
    "OPT_OUT": "SUPPRESS",
}

NON_TERMINAL_REQUEST_STATES = {
    "PENDING_VERIFICATION",
    "VERIFICATION_REJECTED",
    "DISCOVERY",
    "UNDER_REVIEW",
    "FULFILLING",
}

CLOSED_REQUEST_STATES = {"CLOSED_FULFILLED", "CLOSED_REJECTED", "CLOSED_EXPIRED"}


# ---------------------------------------------------------------------------
# Mutation primitives
# ---------------------------------------------------------------------------
def touch(row):
    """Refresh updated_at and bump version by 1 (PRD §2.4). Used for every
    in-place mutation of a versioned resource, including cascade side effects."""
    row["updated_at"] = store.now()
    row["version"] += 1


def append_audit(dsar_request_id, actor_role, actor_user_id, event_type, detail):
    aid = store.new_id()
    now = store.now()
    audit = {
        "id": aid,
        "dsar_request_id": dsar_request_id,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "event_type": event_type,
        "detail": detail,
        "created_at": now,
        "_seq": store.next_seq(),
    }
    store.audit_events[aid] = audit
    return audit


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def compute_deadline(received_at, jurisdiction, extension_count):
    """received_at + (base_days + extension_count * extension_days) calendar days,
    preserving time-of-day (PRD §3.3)."""
    total = BASE_DAYS[jurisdiction] + extension_count * EXTENSION_DAYS[jurisdiction]
    return add_calendar_days(received_at, total)


def compute_business_days_remaining(deadline_at):
    return _bdr(store.now(), deadline_at)


def _round2(value):
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def items_for_request(dsar_request_id):
    return [
        i for i in store.fulfillment_items.values()
        if i["dsar_request_id"] == dsar_request_id
    ]


def compute_fulfillment_progress(dsar_request_id):
    """100 * terminal / total, single half-up rounding to 2 dp; 0.00 when empty
    (PRD §3.7). Terminal = COMPLETED or SKIPPED_EXEMPT."""
    items = items_for_request(dsar_request_id)
    if not items:
        return 0.00
    terminal = sum(1 for i in items if i["state"] in ("COMPLETED", "SKIPPED_EXEMPT"))
    return _round2(Decimal(100) * Decimal(terminal) / Decimal(len(items)))


def compute_discovery_finding_count(dsar_request_id):
    return sum(
        1 for f in store.discovery_findings.values()
        if f["dsar_request_id"] == dsar_request_id
    )


def compute_erasure_risk(dsar_request_id):
    """Returns (score, residual_weighted, total_weighted) over ERASE items
    (PRD §3.7). Residual counts QUEUED/DISPATCHED/BLOCKED/SKIPPED_EXEMPT;
    COMPLETED is fully remediated. Integer weighted sums, single rounding."""
    residual = 0
    total = 0
    for i in items_for_request(dsar_request_id):
        if i["action"] != "ERASE":
            continue
        weight = CATEGORY_WEIGHT[i["data_category"]] * i["record_count"]
        total += weight
        if i["state"] in ("QUEUED", "DISPATCHED", "BLOCKED", "SKIPPED_EXEMPT"):
            residual += weight
    if total == 0:
        return 0.00, residual, total
    score = _round2(Decimal(100) * Decimal(residual) / Decimal(total))
    return score, residual, total


def compute_ack_deadline(dispatched_at, sla_ack_hours):
    return add_hours(dispatched_at, sla_ack_hours)


# ---------------------------------------------------------------------------
# Derived/computed field bundle for a DsarRequest read
# ---------------------------------------------------------------------------
def request_computed_fields(r):
    return {
        "business_days_remaining": compute_business_days_remaining(r["deadline_at"]),
        "discovery_finding_count": compute_discovery_finding_count(r["id"]),
        "fulfillment_progress_pct": compute_fulfillment_progress(r["id"]),
    }


def controller_open_request_count(controller_id):
    return sum(
        1 for r in store.dsar_requests.values()
        if r["controller_id"] == controller_id
        and r["status"] not in CLOSED_REQUEST_STATES
    )


# ---------------------------------------------------------------------------
# Legal-hold / exemption helpers
# ---------------------------------------------------------------------------
def active_hold_covers(data_subject_id, data_category):
    """True if some ACTIVE LegalHold on the subject freezes this data_category."""
    for h in store.legal_holds.values():
        if (
            h["data_subject_id"] == data_subject_id
            and h["state"] == "ACTIVE"
            and data_category in h["data_categories"]
        ):
            return True
    return False


def upheld_exemption_categories(dsar_request_id):
    """Set of data_categories shielded by an UPHELD exemption on the request."""
    return {
        e["data_category"]
        for e in store.exemption_claims.values()
        if e["dsar_request_id"] == dsar_request_id and e["state"] == "UPHELD"
    }


# ---------------------------------------------------------------------------
# Clock sweep (PRD §3.8): expire requests + mark notifications overdue
# ---------------------------------------------------------------------------
def run_clock_sweeps():
    now = store.now()
    # 1. Expire every non-terminal request whose deadline now lies in the past.
    affected_controllers = set()
    for r in store.dsar_requests.values():
        if r["status"] in NON_TERMINAL_REQUEST_STATES and r["deadline_at"] < now:
            r["status"] = "CLOSED_EXPIRED"
            append_audit(
                r["id"], "system", "system", "REQUEST_CLOSED",
                "Request expired: deadline passed",
            )
            touch(r)
            affected_controllers.add(r["controller_id"])
    # open_request_count is recomputed live on read, so no stored counter to fix.

    # 2. Mark every still-SENT notification whose ack window passed as OVERDUE.
    for n in store.processor_notifications.values():
        if n["state"] == "SENT" and n["ack_deadline_at"] < now:
            n["state"] = "OVERDUE"
            touch(n)
