"""Business logic: standing cascade, preemption, sweeps, billing (SCAFFOLD §1.3)."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import store
from helpers import touch, sorted_created, base_entity

PRIORITY_RANK = {"ROUTINE": 0, "URGENT": 1, "STAT": 2}
LEVEL_RANK = {"NONE": 0, "ESCALATED": 1, "CRITICAL": 2}
TIER_MAX = {"TIER_1": 1, "TIER_2": 3, "TIER_3": 5}

WORK_TYPES = {"CONSULT", "OP_NOTE", "DISCHARGE_SUMMARY", "CLINIC_NOTE", "RADIOLOGY_REPORT"}
PRIORITIES = {"STAT", "URGENT", "ROUTINE"}
SPECIALTIES = {"RADIOLOGY", "CARDIOLOGY", "ORTHOPEDICS", "GENERAL"}
MEASUREMENT_BASES = {"END_TO_END", "PRODUCTION_WINDOW"}
DISPUTE_OUTCOMES = {"UPHELD", "REVERSED"}

ASR_CHARS_PER_SECOND = 2
CHARS_PER_LINE = 65
PASS_THRESHOLD = Decimal("80.0")
STANDING_MIN_REVIEWS = 5
ROLLING_WINDOW = 20


def ceil_div(a, b):
    return -(-a // b)


def policy_for(clinic_account_id, priority):
    for p in store.db["sla_policies"].values():
        if p["clinic_account_id"] == clinic_account_id and p["priority"] == priority:
            return p
    return None


def job_of_transcript(t):
    return store.db["jobs"].get(t["dictation_job_id"])


def editor_of_review(review):
    t = store.db["transcripts"].get(review["transcript_id"])
    return t["editor_id"] if t else None


def reviews_of_editor(editor_id):
    out = []
    for r in store.db["qa_reviews"].values():
        if editor_of_review(r) == editor_id:
            out.append(r)
    return out


def current_transcript(job):
    cands = [t for t in store.db["transcripts"].values() if t["dictation_job_id"] == job["id"]]
    if not cands:
        return None
    return max(cands, key=lambda t: t["version_number"])


def visible_chars_and_line_count(final_text):
    vcc = sum(1 for ch in final_text if ch not in " \t\n\r\x0b\x0c")
    return vcc, ceil_div(vcc, CHARS_PER_LINE) if vcc > 0 else 0


def derive_skill_tier(rolling, qa_review_count):
    if qa_review_count < STANDING_MIN_REVIEWS:
        return "TIER_2"  # provisional
    if rolling >= Decimal("95"):
        return "TIER_3"
    if rolling >= Decimal("85"):
        return "TIER_2"
    return "TIER_1"


# ---------------------------------------------------------------------------
# Provider unsigned counters / compliance status (calculations.unsigned_aging_sweep)
# ---------------------------------------------------------------------------

def recompute_provider(p):
    changed = False
    tier1 = 0
    aged = 0
    for t in store.db["transcripts"].values():
        if t["status"] != "DELIVERED":
            continue
        j = job_of_transcript(t)
        if j is None or j["provider_id"] != p["id"]:
            continue
        if t["aging_tier"] == "TIER_1":
            tier1 += 1
        elif t["aging_tier"] == "TIER_2":
            aged += 1
    if p["unsigned_tier1_count"] != tier1:
        p["unsigned_tier1_count"] = tier1
        changed = True
    if p["unsigned_aged_count"] != aged:
        p["unsigned_aged_count"] = aged
        changed = True
    if p["status"] != "SUSPENDED":
        # SUSPENDED never lifts itself; exit is manual via reinstate only.
        clinic = store.db["clinics"][p["clinic_account_id"]]
        new_status = p["status"]
        new_reason = p["suspension_reason"]
        if aged >= clinic["unsigned_report_threshold"]:
            new_status = "SUSPENDED"
            new_reason = "UNSIGNED_REPORT_AGING"
        elif tier1 + aged >= 1:
            new_status = "WARNING"
            new_reason = None
        else:
            new_status = "ACTIVE"
            new_reason = None
        if new_status != p["status"]:
            p["status"] = new_status
            changed = True
        if new_reason != p["suspension_reason"]:
            p["suspension_reason"] = new_reason
            changed = True
    if changed:
        touch(p)


def recompute_clinic_counters(clinic):
    changed = False
    cnt = sum(
        1
        for p in store.db["providers"].values()
        if p["clinic_account_id"] == clinic["id"] and p["status"] == "SUSPENDED"
    )
    if clinic["suspended_provider_count"] != cnt:
        clinic["suspended_provider_count"] = cnt
        changed = True
    if changed:
        touch(clinic)


def compute_billing_hold(clinic, now):
    grace = timedelta(seconds=clinic["payment_grace_days"] * 86400)
    for bp in store.db["billing_periods"].values():
        if bp["clinic_account_id"] != clinic["id"]:
            continue
        if bp["status"] != "FINALIZED" or bp["finalized_at"] is None:
            continue
        if now >= bp["finalized_at"] + grace:
            return True
    return False


def recompute_billing_hold(clinic, now):
    hold = compute_billing_hold(clinic, now)
    if clinic["billing_hold"] != hold:
        clinic["billing_hold"] = hold
        touch(clinic)


# ---------------------------------------------------------------------------
# Editor standing cascade (calculations.editor_rolling_quality_and_standing
# + editor_capacity_reevaluation)
# ---------------------------------------------------------------------------

def editor_standing_cascade(editor, latest_review):
    reviews = reviews_of_editor(editor["id"])
    editor["qa_review_count"] = len(reviews)
    # 20 most recent, created_at DESC with editor_sequence DESC tie-break;
    # editor_sequence is monotonic per editor so it orders the window exactly.
    window = sorted(reviews, key=lambda r: r["editor_sequence"], reverse=True)[:ROLLING_WINDOW]
    total = sum(Decimal(str(r["accuracy_score"])) for r in window)
    rolling = (total / Decimal(len(window))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    editor["rolling_quality_score"] = rolling

    # Standing transitions are evaluated only once the editor has >= 5 reviews.
    if editor["qa_review_count"] >= STANDING_MIN_REVIEWS:
        st = editor["status"]
        if st == "ACTIVE":
            if rolling < Decimal("70"):
                st = "SUSPENDED"
            elif rolling < Decimal("85"):
                st = "PROBATION"
        elif st == "PROBATION":
            if rolling >= Decimal("90"):
                st = "ACTIVE"
            elif rolling < Decimal("75") or (
                latest_review is not None and latest_review["critical_error_count"] > 0
            ):
                st = "SUSPENDED"
        editor["status"] = st

    editor["skill_tier"] = derive_skill_tier(rolling, editor["qa_review_count"])
    if editor["status"] == "SUSPENDED":
        editor["max_concurrent_claims"] = 0
    else:
        editor["max_concurrent_claims"] = TIER_MAX[editor["skill_tier"]]

    # Capacity reevaluation: pinned order (rolling -> standing -> tier -> max -> preempt).
    excess = editor["active_claim_count"] - editor["max_concurrent_claims"]
    if excess > 0:
        cands = [
            j
            for j in store.db["jobs"].values()
            if j["workflow_status"] == "EDITING"
            and j["claimed_by_editor_id"] == editor["id"]
        ]
        cands.sort(key=_preemption_sort_key)
        for victim in cands[:excess]:
            _preempt_job(victim)
            editor["active_claim_count"] -= 1
    touch(editor)


def _preemption_sort_key(j):
    # priority ASC (ROUTINE first), claimed_at DESC, created_at DESC
    claimed = j["claimed_at"].timestamp() if j["claimed_at"] is not None else 0.0
    return (PRIORITY_RANK[j["priority"]], -claimed, -j["created_at"].timestamp())


def _preempt_job(job):
    job["workflow_status"] = "QUEUED"
    job["claimed_by_editor_id"] = None
    job["claimed_at"] = None
    job["preempted_count"] += 1
    touch(job)


# ---------------------------------------------------------------------------
# STAT preemption (calculations.escalation_and_preemption)
# ---------------------------------------------------------------------------

def stat_preemption(stat_job, now):
    free_capacity = 0
    for e in store.db["editors"].values():
        if e["status"] == "ACTIVE":
            free_capacity += max(0, e["max_concurrent_claims"] - e["active_claim_count"])
    if free_capacity > 0:
        return
    cands = [
        j
        for j in store.db["jobs"].values()
        if j["workflow_status"] == "EDITING" and j["priority"] in ("ROUTINE", "URGENT")
    ]
    cands.sort(key=_preemption_sort_key)
    if not cands:
        return  # deferred; the STAT job simply remains QUEUED
    victim = cands[0]
    editor = store.db["editors"][victim["claimed_by_editor_id"]]
    _preempt_job(victim)
    editor["active_claim_count"] -= 1
    # Auto-assign the STAT job to the victim's former editor, bypassing
    # the shift-window gate and the capacity ceiling.
    stat_job["workflow_status"] = "EDITING"
    stat_job["claimed_by_editor_id"] = editor["id"]
    stat_job["claimed_at"] = now
    if stat_job["first_claimed_at"] is None:
        stat_job["first_claimed_at"] = now
    editor["active_claim_count"] += 1
    touch(stat_job)
    touch(editor)


# ---------------------------------------------------------------------------
# Full system sweep on clock set (PRD §2.4, pinned phase order)
# ---------------------------------------------------------------------------

def run_sweep(now):
    # (1) unsigned-transcript aging tiers
    for t in list(store.db["transcripts"].values()):
        if t["status"] != "DELIVERED":
            continue
        job = job_of_transcript(t)
        if job is None:
            continue
        clinic = store.db["clinics"][job["clinic_account_id"]]
        age = now - t["delivered_at"]
        if age >= timedelta(hours=clinic["aging_tier2_hours"]):
            tier = "TIER_2"
        elif age >= timedelta(hours=clinic["aging_tier1_hours"]):
            tier = "TIER_1"
        else:
            tier = "NONE"
        if t["aging_tier"] != tier:
            t["aging_tier"] = tier
            touch(t)

    # (2) per-provider unsigned counts and compliance statuses
    for p in list(store.db["providers"].values()):
        recompute_provider(p)

    # (3) clinic suspended_provider_count
    for c in list(store.db["clinics"].values()):
        recompute_clinic_counters(c)

    # (4) clinic billing_hold
    for c in list(store.db["clinics"].values()):
        recompute_billing_hold(c, now)

    # (5) escalation levels (monotonic non-decreasing; frozen in DELIVERED/CANCELLED)
    for j in list(store.db["jobs"].values()):
        if j["workflow_status"] not in ("QUEUED", "EDITING", "SUBMITTED"):
            continue
        policy = policy_for(j["clinic_account_id"], j["priority"])
        if policy is None:
            continue
        buffer = timedelta(minutes=policy["tat_minutes"] // 4)
        if now >= j["due_at"]:
            target = "CRITICAL"
        elif now >= j["due_at"] - buffer:
            target = "ESCALATED"
        else:
            target = "NONE"
        if LEVEL_RANK[target] > LEVEL_RANK[j["escalation_level"]]:
            j["escalation_level"] = target
            touch(j)

    # STAT CRITICAL preemptions, processed in job creation order (earliest first)
    stat_jobs = sorted(
        (
            j
            for j in store.db["jobs"].values()
            if j["workflow_status"] == "QUEUED"
            and j["priority"] == "STAT"
            and j["escalation_level"] == "CRITICAL"
        ),
        key=lambda j: j["_seq"],
    )
    for j in stat_jobs:
        stat_preemption(j, now)


# ---------------------------------------------------------------------------
# Billing (calculations.provisional_vs_final_line_billing, sla_credit_and_period_rollup)
# ---------------------------------------------------------------------------

def generate_line_items(period):
    clinic_jobs = sorted_created(
        j
        for j in store.db["jobs"].values()
        if j["clinic_account_id"] == period["clinic_account_id"]
    )
    for job in clinic_jobs:
        qualifying = [
            t
            for t in store.db["transcripts"].values()
            if t["dictation_job_id"] == job["id"]
            and t["status"] in ("DELIVERED", "SIGNED", "AMENDED")
            and t["delivered_at"] is not None
            and period["period_start"] <= t["delivered_at"] <= period["period_end"]
        ]
        if not qualifying:
            continue
        billed = max(qualifying, key=lambda t: t["version_number"])
        policy = policy_for(job["clinic_account_id"], job["priority"])
        rate = policy["rate_per_line_cents"] if policy else 0
        plc = ceil_div(job["asr_char_estimate"], CHARS_PER_LINE)
        item = base_entity()
        item.update(
            {
                "billing_period_id": period["id"],
                "transcript_id": billed["id"],
                "priority": job["priority"],
                "rate_per_line_cents": rate,
                "provisional_line_count": plc,
                "provisional_amount_cents": plc * rate,
                "final_line_count": None,
                "final_amount_cents": None,
                "sla_breach": None,
                "credit_cents": None,
                "status": "PROVISIONAL",
            }
        )
        store.db["line_items"][item["id"]] = item


def finalize_line_items(period, now):
    items = sorted_created(
        i for i in store.db["line_items"].values() if i["billing_period_id"] == period["id"]
    )
    gross = 0
    credit_total = 0
    for item in items:
        t = store.db["transcripts"][item["transcript_id"]]
        job = store.db["jobs"][t["dictation_job_id"]]
        policy = policy_for(period["clinic_account_id"], item["priority"])
        flc = t["line_count"]
        famt = flc * item["rate_per_line_cents"]
        if policy and policy["measurement_basis"] == "END_TO_END":
            breach = t["delivered_at"] > job["due_at"]
        else:
            # PRODUCTION_WINDOW: accepted transcript's submission vs first claim.
            elapsed_seconds = (t["created_at"] - job["first_claimed_at"]).total_seconds()
            breach = elapsed_seconds > policy["tat_minutes"] * 60
        if breach:
            # Round each item's credit half-up FIRST, then sum (pinned order).
            credit = int(
                (Decimal(famt * policy["breach_credit_pct"]) / Decimal(100)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
        else:
            credit = 0
        item["final_line_count"] = flc
        item["final_amount_cents"] = famt
        item["sla_breach"] = breach
        item["credit_cents"] = credit
        item["status"] = "FINAL"
        touch(item)
        gross += famt
        credit_total += credit
    period["gross_amount_cents"] = gross
    period["credit_amount_cents"] = credit_total
    period["net_amount_cents"] = gross - credit_total
    period["finalized_at"] = now
    period["status"] = "FINALIZED"
    touch(period)
