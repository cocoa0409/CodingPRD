"""Business logic: SLA/due_at, provider stats, gold-card program, determinations,
notice rendering, compliance events, TAT breach marking, delegation thresholds."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
from db import db, base_record, lean_record, touch

# ---------------------------------------------------------------- constants

# turnaround_due_at SLA matrix: (urgency, line_of_business) -> hours
SLA_HOURS = {
    ("URGENT", "MEDICARE"): 24,
    ("URGENT", "MEDICAID"): 24,
    ("URGENT", "COMMERCIAL"): 48,
    ("STANDARD", "MEDICARE"): 72,
    ("STANDARD", "MEDICAID"): 120,
    ("STANDARD", "COMMERCIAL"): 168,
}
APPEAL_SLA_HOURS = 720
ROLLING_WINDOW_HOURS = 2160          # 90 days
APPEAL_WINDOW_HOURS = 4320           # 180 days (notice APPEAL_BY)
GOLD_CARD_MIN_COUNT = 10
GOLD_CARD_MIN_RATE = Decimal("0.90")
SUSPEND_THRESHOLD = 3

# determination reason domains
DENIAL_REASONS = (
    "MEDICAL_NECESSITY_NOT_MET",
    "INSUFFICIENT_INFO",
    "EXPERIMENTAL_INVESTIGATIONAL",
)

HUMAN_ROLES = ("CLINICAL_REVIEWER", "MEDICAL_DIRECTOR")

# compliance event types
EV_AUTO_APPROVAL_FIRED = "AUTO_APPROVAL_FIRED"
EV_TAT_BREACHED = "TAT_BREACHED"
EV_GOLD_CARD_GRANTED = "GOLD_CARD_GRANTED"
EV_GOLD_CARD_SUSPENDED = "GOLD_CARD_SUSPENDED"
EV_DELEGATION_SUSPENDED = "DELEGATION_SUSPENDED"
EV_DETERMINATION_VOIDED = "DETERMINATION_VOIDED"
EV_APPEAL_OVERTURNED = "APPEAL_OVERTURNED"


# ------------------------------------------------------------------ helpers

def rate4(approvals, count):
    """approvals / count at 4 decimal places round-half-up; None when count == 0."""
    if count == 0:
        return None
    return (Decimal(approvals) / Decimal(count)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def rate4_json(dec):
    return float(dec) if dec is not None else None


def request_due_at(received_at, urgency, line_of_business):
    return received_at + timedelta(hours=SLA_HOURS[(urgency, line_of_business)])


def appeal_due_at(received_at):
    return received_at + timedelta(hours=APPEAL_SLA_HOURS)


# ------------------------------------------------------------- audit events

def add_event(event_type, request_id, provider_id, details):
    ev = lean_record()
    ev.update(
        {
            "event_type": event_type,
            "request_id": request_id,
            "provider_id": provider_id,
            "details": details,
        }
    )
    db.events[ev["id"]] = ev
    return ev


# ------------------------------------------------------------ notice render

def render_notice(outcome, service_code, reason_code, criteria_set,
                  guideline_version, issued_at, decided_by_role):
    """Exact-string template per notice_text_render (PRD §3.4)."""
    appeal_by = issued_at + timedelta(hours=APPEAL_WINDOW_HOURS)
    return (
        "OUTCOME:" + outcome
        + "|SERVICE:" + service_code
        + "|REASON:" + reason_code
        + "|CRITERIA:" + criteria_set["name"] + "@" + guideline_version["version_label"]
        + "|ISSUED:" + clock.fmt(issued_at)
        + "|APPEAL_BY:" + clock.fmt(appeal_by)
        + "|DECIDED_BY:" + decided_by_role
    )


# ------------------------------------------------------------- determinations

def create_determination(req, outcome, reason_code, decided_by_role,
                         decided_by_user_id, issued_at):
    criteria_set = db.criteria_sets[req["criteria_set_id"]]
    guideline = db.guideline_versions[req["guideline_version_id"]]
    det = base_record()
    det.update(
        {
            "request_id": req["id"],
            "outcome": outcome,
            "reason_code": reason_code,
            "decided_by_role": decided_by_role,
            "decided_by_user_id": decided_by_user_id,
            "guideline_version_id": req["guideline_version_id"],
            "notice_text": render_notice(
                outcome,
                req["service_code"],
                reason_code,
                criteria_set,
                guideline,
                issued_at,
                decided_by_role,
            ),
            "issued_at": issued_at,
            "status": "FINAL",
        }
    )
    db.determinations[det["id"]] = det
    return det


def mark_late_determination(req, issued_at):
    """A determination issued with issued_at strictly later than due_at marks the
    request breached at issuance (sticky) and emits TAT_BREACHED."""
    if issued_at > req["due_at"] and not req["is_tat_breached"]:
        req["is_tat_breached"] = True
        add_event(
            EV_TAT_BREACHED,
            req["id"],
            req["provider_id"],
            f"Determination issued late for request {req['id']} "
            f"(issued_at after due_at)",
        )


# --------------------------------------------------------- provider statistics

def compute_provider_stats(provider_id, now):
    """Inclusion set: this provider's determinations with status FINAL or
    OVERTURNED decided by CLINICAL_REVIEWER or MEDICAL_DIRECTOR. SYSTEM_RULE
    auto-approvals and VOID rows never count. Effective approval: FINAL with
    outcome APPROVED, or any OVERTURNED row."""
    dets = []
    for det in db.determinations.values():
        if det["decided_by_role"] not in HUMAN_ROLES:
            continue
        if det["status"] not in ("FINAL", "OVERTURNED"):
            continue
        req = db.requests.get(det["request_id"])
        if req is None or req["provider_id"] != provider_id:
            continue
        dets.append(det)

    def is_effective_approval(d):
        return (d["status"] == "FINAL" and d["outcome"] == "APPROVED") or (
            d["status"] == "OVERTURNED"
        )

    window_start = now - timedelta(hours=ROLLING_WINDOW_HOURS)
    rolling = [d for d in dets if window_start <= d["issued_at"] <= now]

    lt_count = len(dets)
    lt_appr = sum(1 for d in dets if is_effective_approval(d))
    ro_count = len(rolling)
    ro_appr = sum(1 for d in rolling if is_effective_approval(d))
    return {
        "window_start": window_start,
        "window_end": now,
        "rolling_count": ro_count,
        "rolling_approvals": ro_appr,
        "rolling_rate": rate4(ro_appr, ro_count),
        "lifetime_count": lt_count,
        "lifetime_approvals": lt_appr,
        "lifetime_rate": rate4(lt_appr, lt_count),
    }


def recompute_provider_stats(provider_id, run_suspend_check=False):
    """Persist recomputed stats onto the provider; optionally run the gold-card
    auto-suspend check. All field changes settle as ONE mutation (single
    updated_at refresh / version increment). Returns the computed stats."""
    provider = db.providers[provider_id]
    now = clock.now()
    s = compute_provider_stats(provider_id, now)

    changed = False
    new_values = {
        "rolling_determination_count": s["rolling_count"],
        "rolling_approval_count": s["rolling_approvals"],
        "rolling_approval_rate": rate4_json(s["rolling_rate"]),
        "lifetime_determination_count": s["lifetime_count"],
        "lifetime_approval_count": s["lifetime_approvals"],
        "lifetime_approval_rate": rate4_json(s["lifetime_rate"]),
    }
    for k, v in new_values.items():
        if provider.get(k) != v:
            provider[k] = v
            changed = True

    suspended = False
    if (
        run_suspend_check
        and provider["gold_card_status"] == "GOLD_CARDED"
        and s["rolling_count"] >= GOLD_CARD_MIN_COUNT
        and s["rolling_rate"] is not None
        and s["rolling_rate"] < GOLD_CARD_MIN_RATE
    ):
        provider["gold_card_status"] = "SUSPENDED"
        provider["gold_card_service_category"] = None
        changed = True
        suspended = True

    if changed:
        touch(provider)
    if suspended:
        add_event(
            EV_GOLD_CARD_SUSPENDED,
            None,
            provider["id"],
            f"Gold card suspended for provider {provider['id']}: rolling "
            f"approval rate fell below 0.90",
        )
    return s


# ------------------------------------------------------ delegation thresholds

def recompute_arrangement(arrangement):
    """open_deficiency_count = OPEN findings with finding_type != COMPLIANT.
    Reaching 3 suspends an ACTIVE arrangement; dropping below 3 resumes a
    SUSPENDED one."""
    count = sum(
        1
        for f in db.findings.values()
        if f["arrangement_id"] == arrangement["id"]
        and f["status"] == "OPEN"
        and f["finding_type"] != "COMPLIANT"
    )
    changed = False
    if arrangement["open_deficiency_count"] != count:
        arrangement["open_deficiency_count"] = count
        changed = True
    became_suspended = False
    if count >= SUSPEND_THRESHOLD and arrangement["status"] == "ACTIVE":
        arrangement["status"] = "SUSPENDED"
        changed = True
        became_suspended = True
    elif count < SUSPEND_THRESHOLD and arrangement["status"] == "SUSPENDED":
        arrangement["status"] = "ACTIVE"
        changed = True
    if changed:
        touch(arrangement)
    if became_suspended:
        add_event(
            EV_DELEGATION_SUSPENDED,
            None,
            None,
            f"Delegation arrangement {arrangement['id']} suspended: "
            f"open deficiency count reached {count}",
        )
