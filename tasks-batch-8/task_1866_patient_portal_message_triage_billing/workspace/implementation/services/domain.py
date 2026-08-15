"""Business logic: calculations, state-machine side effects, cascades.

Implements SCAFFOLD §1.3 (calculations) and the side effects of §1.2.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import CLOCK, _parse_dt
from middleware import touch, COUNTED_STATUSES

OVERLOAD_THRESHOLD = 5
EVISIT_MIN_MINUTES = 5
FEE_99421_CENTS = 5000
FEE_99422_CENTS = 8000
FEE_99423_CENTS = 12000

CLAIM_OUTSTANDING_STATUSES = {"SUBMITTED", "DENIED"}
CLAIM_ACTIVE_STATUSES = {"DRAFT", "SUBMITTED", "DENIED"}
CLAIM_IN_FLIGHT_FOR_CLOSE = {"DRAFT", "SUBMITTED", "DENIED"}
CLAIM_IN_FLIGHT_FOR_REDETERMINE = {"SUBMITTED", "DENIED"}


# ---------------------------------------------------------------------------
# open_inbox_count maintenance + overload flag (§2.11)
# ---------------------------------------------------------------------------

def recompute_staff_counts(staff_id):
    member = db.staff.get(staff_id)
    if member is None:
        return
    count = 0
    for m in db.portal_messages.values():
        if m.get("assignee_id") == staff_id and m["status"] in COUNTED_STATUSES:
            count += 1
    member["open_inbox_count"] = count
    member["inbox_overloaded"] = count >= OVERLOAD_THRESHOLD
    touch(member)


def recompute_all_staff_counts():
    for sid in list(db.staff.keys()):
        recompute_staff_counts(sid)


# ---------------------------------------------------------------------------
# education gate (§3.7)
# ---------------------------------------------------------------------------

def recompute_education_gate(patient_id):
    patient = db.patients.get(patient_id)
    if patient is None:
        return
    open_gate = any(
        n["patient_id"] == patient_id and n.get("blocking") and n["status"] == "ISSUED"
        for n in db.education_notices.values()
    )
    patient["education_gate_open"] = open_gate
    touch(patient)


# ---------------------------------------------------------------------------
# outstanding_billed_cents (§3.6)
# ---------------------------------------------------------------------------

def recompute_outstanding(patient_id):
    patient = db.patients.get(patient_id)
    if patient is None:
        return
    total = sum(
        c["patient_responsibility_cents"]
        for c in db.e_visit_claims.values()
        if c["patient_id"] == patient_id and c["status"] in CLAIM_OUTSTANDING_STATUSES
    )
    patient["outstanding_billed_cents"] = total
    touch(patient)


# ---------------------------------------------------------------------------
# clinical_minutes_total (§3.4)
# ---------------------------------------------------------------------------

def recompute_clinical_minutes(message):
    total = 0
    for e in db.time_entries.values():
        if e["message_id"] != message["id"]:
            continue
        if e["entry_kind"] != "CLINICAL_REVIEW":
            continue
        author = db.staff.get(e["staff_id"])
        if author is None or author["staff_type"] != "PROVIDER":
            continue
        total += e["minutes"]
    message["clinical_minutes_total"] = total


# ---------------------------------------------------------------------------
# response deadline (§3.3) — computed at triage
# ---------------------------------------------------------------------------

def compute_response_due_at(message, pool):
    urgency = message["urgency"]
    if urgency == "EMERGENT":
        target = pool["target_minutes_emergent"]
    elif urgency == "URGENT":
        target = pool["target_minutes_urgent"]
    else:
        target = pool["target_minutes_routine"]
    if pool["deadline_policy"] == "FROM_RECEIPT":
        base = _parse_dt(message["received_at"])
    else:  # FROM_TRIAGE
        base = _parse_dt(message["triaged_at"])
    due = base + timedelta(minutes=target)
    from db import fmt_ts
    return fmt_ts(due)


# ---------------------------------------------------------------------------
# SLA breach evaluation (§2.12)
# ---------------------------------------------------------------------------

def latch_sla_at_resolution(message):
    """Latched when the message reaches RESOLVED."""
    if message.get("sla_breached"):
        return
    due = message.get("response_due_at")
    if not due:
        return
    effective = message.get("first_response_at")
    effective_dt = _parse_dt(effective) if effective else CLOCK.now()
    if effective_dt > _parse_dt(due):
        message["sla_breached"] = True


def latch_sla_at_staff_reply(message):
    """Re-evaluated on every staff reply (first_response_at set once)."""
    if message.get("sla_breached"):
        return
    due = message.get("response_due_at")
    if not due:
        return
    effective = message.get("first_response_at")
    effective_dt = _parse_dt(effective) if effective else CLOCK.now()
    if effective_dt > _parse_dt(due):
        message["sla_breached"] = True


# ---------------------------------------------------------------------------
# e-visit tier selection (§3.6)
# ---------------------------------------------------------------------------

def evisit_tier(minutes):
    """Return (code, fee_cents) or None when below the billable minimum."""
    if minutes < EVISIT_MIN_MINUTES:
        return None
    if minutes <= 10:
        return ("CPT_99421", FEE_99421_CENTS)
    if minutes <= 20:
        return ("CPT_99422", FEE_99422_CENTS)
    return ("CPT_99423", FEE_99423_CENTS)


def patient_responsibility(patient, fee_cents):
    if patient["plan_type"] == "COPAY":
        return min(patient["copay_cents"], fee_cents)
    pct = Decimal(str(patient["coinsurance_pct"]))
    raw = Decimal(fee_cents) * pct
    rounded = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return min(fee_cents, rounded)


# ---------------------------------------------------------------------------
# on-call selector (§3.5)
# ---------------------------------------------------------------------------

def select_on_call_provider():
    now = CLOCK.now()
    candidates = []
    for shift in db.on_call_shifts.values():
        start = _parse_dt(shift["start_utc"])
        end = _parse_dt(shift["end_utc"])
        if start <= now <= end:  # CLOSED interval containment
            provider = db.staff.get(shift["provider_id"])
            if provider is not None and provider["staff_type"] == "PROVIDER":
                candidates.append((start, shift["created_at"], shift["id"], provider))
    if not candidates:
        return None
    # rank: covering shift.start_utc ASC, tie: shift.created_at ASC.
    # id NEVER participates — use it only as a stable no-op final key.
    candidates.sort(key=lambda c: (c[0], c[1], c[2]))
    return candidates[0][3]


# ---------------------------------------------------------------------------
# delegation helpers
# ---------------------------------------------------------------------------

def find_active_grant(delegate_staff_id, pool_id, now=None):
    """ACTIVE grant linking delegate to pool whose CLOSED window covers now."""
    now = now or CLOCK.now()
    for g in db.delegation_grants.values():
        if g["status"] != "ACTIVE":
            continue
        if g["delegate_staff_id"] != delegate_staff_id or g["pool_id"] != pool_id:
            continue
        start = _parse_dt(g["start_utc"])
        end = _parse_dt(g["end_utc"])
        if start <= now <= end:
            return g
    return None


def has_coverage(staff_id, pool_id):
    """CoverageWindow for pool covering now (half-open), or ACTIVE grant."""
    now = CLOCK.now()
    for w in db.coverage_windows.values():
        if w["staff_id"] != staff_id or w["pool_id"] != pool_id:
            continue
        start = _parse_dt(w["start_utc"])
        end = _parse_dt(w["end_utc"])
        if start <= now < end:  # HALF-OPEN containment
            return True
    return find_active_grant(staff_id, pool_id, now) is not None


def pool_kind_eligible(staff_type, pool_kind, staff_id, pool_id):
    """Pool-kind/staff-type eligibility, incl. delegation for PROVIDER_INBOX."""
    direct = {
        "NURSE_TRIAGE": "NURSE",
        "FRONT_DESK": "FRONT_DESK",
        "BILLING": "BILLING_SPECIALIST",
        "PROVIDER_INBOX": "PROVIDER",
    }.get(pool_kind)
    if staff_type == direct:
        return True
    if pool_kind == "PROVIDER_INBOX":
        return find_active_grant(staff_id, pool_id) is not None
    return False


# ---------------------------------------------------------------------------
# claim helpers
# ---------------------------------------------------------------------------

def claims_for_message(message_id):
    return [c for c in db.e_visit_claims.values() if c["message_id"] == message_id]


def granted_consent_for_message(message_id):
    """The message's GRANTED (not superseded) ConsentRecord, if any."""
    for c in db.consent_records.values():
        if c["message_id"] == message_id and c["status"] == "GRANTED":
            return c
    return None


def requested_consent_for_message(message_id):
    for c in db.consent_records.values():
        if c["message_id"] == message_id and c["status"] == "REQUESTED":
            return c
    return None


def supersede_responded_consents(message_id):
    """Prior GRANTED/DECLINED consents on the message -> SUPERSEDED."""
    for c in db.consent_records.values():
        if c["message_id"] == message_id and c["status"] in ("GRANTED", "DECLINED"):
            c["status"] = "SUPERSEDED"
            touch(c)
