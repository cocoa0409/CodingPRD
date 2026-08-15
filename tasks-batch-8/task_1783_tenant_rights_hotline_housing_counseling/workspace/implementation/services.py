"""Business logic: calculations, state-machine side effects, cascades, sweep."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store, now, new_id, next_seq


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ISSUE_CATEGORIES = ("EVICTION", "HABITABILITY", "DEPOSIT")
TTL_DAYS = {"RECORDING": 7, "FOLLOW_UP": 30, "LEGAL_AID_RELEASE": 90, "DATA_SHARING": 365}
TIER_FOLLOWUPS = {"STANDARD": 1, "ELEVATED": 2, "CRITICAL": 3}
SLA_HOURS = {"CRITICAL": 24, "ELEVATED": 72, "STANDARD": 168}
DUE_WINDOW_HOURS = 48
BUFFER_MINUTES = 10
PENALTY_MULTIPLIER = Decimal("1.5")
NONTERMINAL_FOLLOWUP = ("SCHEDULED", "DUE")
OPEN_COUNSELING_STATES = ("IN_PROGRESS", "PENDING_FOLLOW_UP", "ESCALATED")


# ---------------------------------------------------------------------------
# Record plumbing
# ---------------------------------------------------------------------------

def make_record(fields):
    t = now()
    rec = {
        "id": new_id(),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(fields)
    return rec


def make_note(fields):
    rec = {"id": new_id(), "created_at": now(), "_seq": next_seq()}
    rec.update(fields)
    return rec


def bump(rec):
    """Every mutation of a resource refreshes updated_at and adds 1 to version."""
    rec["version"] += 1
    rec["updated_at"] = now()


# ---------------------------------------------------------------------------
# Script chain helpers
# ---------------------------------------------------------------------------

def current_published_script(jurisdiction_id, issue_category):
    """The PUBLISHED script for the pair whose window covers the current time."""
    t = now()
    for s in store.scripts.values():
        if s["jurisdiction_id"] != jurisdiction_id or s["issue_category"] != issue_category:
            continue
        if s["status"] != "PUBLISHED":
            continue
        if s["effective_from"] is not None and s["effective_from"] <= t and (
            s["effective_until"] is None or t < s["effective_until"]
        ):
            return s
    return None


def any_published_script(jurisdiction_id, issue_category):
    for s in store.scripts.values():
        if (
            s["jurisdiction_id"] == jurisdiction_id
            and s["issue_category"] == issue_category
            and s["status"] == "PUBLISHED"
        ):
            return s
    return None


def outdate_resource_cascade(resource, reason):
    """Cancel still-PROPOSED referrals pointing at a resource leaving CURRENT."""
    for ref in store.referrals.values():
        if ref["self_help_resource_id"] == resource["id"] and ref["status"] == "PROPOSED":
            ref["status"] = "CANCELLED"
            ref["cancel_reason"] = reason
            bump(ref)


def outdate_script_cascade(superseded_script, effective_until):
    """Cascade links 1-3 of publish/retire: supersede script, outdate linked
    CURRENT resources, cancel their PROPOSED referrals."""
    superseded_script["status"] = "SUPERSEDED"
    superseded_script["effective_until"] = effective_until
    bump(superseded_script)
    for res in store.resources.values():
        if res["linked_script_id"] == superseded_script["id"] and res["status"] == "CURRENT":
            res["status"] = "OUTDATED"
            bump(res)
            outdate_resource_cascade(res, "SCRIPT_OUTDATED")


def retire_script_cascade(script):
    """PUBLISHED -> RETIRED cascade: linked CURRENT resources go OUTDATED and
    their PROPOSED referrals cancel with SCRIPT_OUTDATED. Pinned session
    scripts are grandfathered (untouched)."""
    for res in store.resources.values():
        if res["linked_script_id"] == script["id"] and res["status"] == "CURRENT":
            res["status"] = "OUTDATED"
            bump(res)
            outdate_resource_cascade(res, "SCRIPT_OUTDATED")


# ---------------------------------------------------------------------------
# Case scoring (case_priority_score, urgency_tier_from_score, follow_up_cadence,
# deposit_exposure_estimate)
# ---------------------------------------------------------------------------

def compute_priority_score(case):
    jur = store.jurisdictions[case["jurisdiction_id"]]
    verified = case["score_variant"] == "VERIFIED"
    base = 0
    # (1) eviction component, tiered on whole calendar days to deadline
    if case["eviction_notice_date"] is not None:
        d = (case["eviction_notice_date"] - now().date()).days  # may be negative
        if d <= 5:
            ev = 50
        elif d <= 14:
            ev = 30
        elif d <= 30:
            ev = 15
        else:
            ev = 0
        # VERIFIED variant only: defective-notice halving (rounds down)
        if verified and case["notice_served_at"] is not None:
            given_days = (case["eviction_notice_date"] - case["notice_served_at"].date()).days
            if given_days < jur["eviction_notice_days"]:
                ev = ev // 2
        base += ev
    # (2) habitability component, conditional on landlord cure period
    if case["habitability_reported_at"] is not None:
        h = int((now() - case["habitability_reported_at"]).total_seconds() // 86400)
        if h > 2 * jur["habitability_repair_days"]:
            base += 25
        elif h > jur["habitability_repair_days"]:
            base += 15
    # (3) deposit component
    if case["deposit_amount_cents"] is not None and case["monthly_rent_cents"] is not None:
        cap = Decimal(str(case["monthly_rent_cents"])) * Decimal(str(jur["deposit_cap_months"]))
        if Decimal(case["deposit_amount_cents"]) > cap:
            base += 10
    # (4) history components
    base += case["missed_follow_up_count"] * 5
    if verified:
        base += case["escalation_level"] * 8
    return min(100, max(0, base))


def tier_from_score(score):
    if score >= 70:
        return "CRITICAL"
    if score >= 40:
        return "ELEVATED"
    return "STANDARD"


def compute_deposit_exposure(case):
    """Integer cents; each component rounded half-up BEFORE summation."""
    if (
        case["deposit_amount_cents"] is None
        or case["monthly_rent_cents"] is None
        or case["deposit_days_held"] is None
    ):
        return None
    jur = store.jurisdictions[case["jurisdiction_id"]]
    cap_cents = int(
        (Decimal(str(case["monthly_rent_cents"])) * Decimal(str(jur["deposit_cap_months"])))
        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    over_cap_cents = max(0, case["deposit_amount_cents"] - cap_cents)
    if jur["deposit_interest_required"]:
        interest_cents = int(
            (
                Decimal(case["deposit_amount_cents"])
                * Decimal(str(jur["deposit_interest_rate_pct"]))
                * Decimal(case["deposit_days_held"])
                / Decimal(36500)
            ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
    else:
        interest_cents = 0
    penalty_cents = int(
        (Decimal(over_cap_cents) * PENALTY_MULTIPLIER).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    return over_cap_cents + interest_cents + penalty_cents


def recompute_case(case):
    """Pinned evaluation order: score -> tier -> required_follow_up_count.
    Never retroactively reclassifies existing follow-ups."""
    case["priority_score"] = compute_priority_score(case)
    case["urgency_tier"] = tier_from_score(case["priority_score"])
    case["required_follow_up_count"] = TIER_FOLLOWUPS[case["urgency_tier"]]
    case["deposit_exposure_cents"] = compute_deposit_exposure(case)


# ---------------------------------------------------------------------------
# Case notes / follow-ups / escalation cascades
# ---------------------------------------------------------------------------

def add_system_note(case, body):
    note = make_note({
        "case_id": case["id"],
        "counselor_id": None,
        "body": body,
        "is_confidential": False,
        "system_generated": True,
    })
    store.notes[note["id"]] = note
    bump(case)
    return note


def bubble_up_case(case, exclude_follow_up_id=None):
    """If the case is PENDING_FOLLOW_UP and no non-terminal follow-ups remain,
    it returns to IN_PROGRESS."""
    if case["status"] != "PENDING_FOLLOW_UP":
        return
    for fu in store.follow_ups.values():
        if (
            fu["case_id"] == case["id"]
            and fu["id"] != exclude_follow_up_id
            and fu["status"] in NONTERMINAL_FOLLOWUP
        ):
            return
    case["status"] = "IN_PROGRESS"
    bump(case)


def create_follow_up(case, scheduled_for, auto_created):
    fu = make_record({
        "case_id": case["id"],
        "scheduled_for": scheduled_for,
        "status": "SCHEDULED",
        "completed_at": None,
        "outcome": None,
        "auto_created": auto_created,
        "required_count_at_schedule": case["required_follow_up_count"],
    })
    store.follow_ups[fu["id"]] = fu
    return fu


def escalate_case(case):
    """Shared manual/auto escalation side effects."""
    case["status"] = "ESCALATED"
    case["escalation_level"] += 1
    case["last_escalated_at"] = now()
    bump(case)
    create_follow_up(case, now() + timedelta(hours=24), auto_created=True)
    add_system_note(case, "Case escalated to ESCALATED (escalation_level=%d)."
                          % case["escalation_level"])


def miss_follow_up(fu):
    """DUE -> MISSED side effects: missed count, score recompute (+5 per miss),
    maybe auto-escalate. The miss cascade applies the history component to the
    case's current score (the fact components are not re-evaluated against the
    advanced clock); tier and cadence re-derive from the new score."""
    case = store.cases[fu["case_id"]]
    fu["status"] = "MISSED"
    bump(fu)
    case["missed_follow_up_count"] += 1
    case["priority_score"] = min(100, max(0, case["priority_score"] + 5))
    case["urgency_tier"] = tier_from_score(case["priority_score"])
    case["required_follow_up_count"] = TIER_FOLLOWUPS[case["urgency_tier"]]
    bump(case)
    if (
        case["score_variant"] == "VERIFIED"
        and case["urgency_tier"] == "CRITICAL"
        and case["status"] in ("IN_PROGRESS", "PENDING_FOLLOW_UP")
    ):
        escalate_case(case)


# ---------------------------------------------------------------------------
# Consent cascades (revoke / expiry / purge)
# ---------------------------------------------------------------------------

def _cancel_follow_ups_for_caller(caller_id):
    for fu in sorted(
        (f for f in store.follow_ups.values() if f["status"] == "SCHEDULED"),
        key=lambda f: (f["created_at"], f["_seq"]),
    ):
        case = store.cases.get(fu["case_id"])
        if case is None or case["caller_id"] != caller_id:
            continue
        fu["status"] = "CANCELLED"
        bump(fu)
        bubble_up_case(case, exclude_follow_up_id=fu["id"])


def _cancel_legal_aid_referrals(caller_id, reason, include_dispatched):
    for ref in sorted(store.referrals.values(), key=lambda r: (r["created_at"], r["_seq"])):
        if ref["referral_type"] != "LEGAL_AID":
            continue
        if ref["status"] == "PROPOSED" or (include_dispatched and ref["status"] == "DISPATCHED"):
            case = store.cases.get(ref["case_id"])
            if case is None or case["caller_id"] != caller_id:
                continue
            ref["status"] = "CANCELLED"
            ref["cancel_reason"] = reason
            bump(ref)
            # DISPATCHED cancellation releases the org slot; current_week_reserved
            # is computed on read from current statuses, so this is automatic.


def consent_follow_up_cascade(caller_id):
    _cancel_follow_ups_for_caller(caller_id)


def consent_legal_aid_revoke_cascade(caller_id):
    _cancel_legal_aid_referrals(caller_id, "CONSENT_REVOKED", include_dispatched=True)


def consent_legal_aid_expire_cascade(caller_id):
    _cancel_legal_aid_referrals(caller_id, "CONSENT_EXPIRED", include_dispatched=False)


def consent_data_sharing_cascade(caller):
    if not caller["do_not_aggregate"]:
        caller["do_not_aggregate"] = True
        bump(caller)


def expire_consent(consent):
    """GRANTED -> EXPIRED with the (narrower) expiry cascades."""
    caller = store.callers.get(consent["caller_id"])
    consent["status"] = "EXPIRED"
    bump(consent)
    if caller is None:
        return
    if consent["consent_type"] == "FOLLOW_UP":
        consent_follow_up_cascade(caller["id"])
    elif consent["consent_type"] == "LEGAL_AID_RELEASE":
        consent_legal_aid_expire_cascade(caller["id"])
    elif consent["consent_type"] == "DATA_SHARING":
        consent_data_sharing_cascade(caller)


def revoke_consent_cascades(consent):
    caller = store.callers.get(consent["caller_id"])
    if caller is None:
        return
    if consent["consent_type"] == "FOLLOW_UP":
        consent_follow_up_cascade(caller["id"])
    elif consent["consent_type"] == "LEGAL_AID_RELEASE":
        consent_legal_aid_revoke_cascade(caller["id"])
    elif consent["consent_type"] == "DATA_SHARING":
        consent_data_sharing_cascade(caller)


# ---------------------------------------------------------------------------
# Interpreter window conflict (buffered half-open intervals)
# ---------------------------------------------------------------------------

def interpreter_window_conflict(interpreter_id, start, end, exclude_session_id=None):
    buf = timedelta(minutes=BUFFER_MINUTES)
    for s in store.sessions.values():
        if s["id"] == exclude_session_id:
            continue
        if s["interpreter_id"] != interpreter_id:
            continue
        if s["interpretation_status"] not in ("REQUESTED", "CONNECTED"):
            continue
        if s["session_status"] not in ("QUEUED", "ASSIGNED", "ACTIVE"):
            continue
        s2, e2 = s["scheduled_start_at"], s["scheduled_end_at"]
        if s2 is None or e2 is None:
            continue
        if start < e2 + buf and s2 < end + buf:
            return True
    return False


# ---------------------------------------------------------------------------
# Org weekly capacity (ISO week, Monday 00:00:00Z half-open)
# ---------------------------------------------------------------------------

def iso_week_start(t):
    monday = t.date() - timedelta(days=t.date().weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


def org_week_reserved(org_id, at=None):
    at = at or now()
    week_start = iso_week_start(at)
    week_end = week_start + timedelta(days=7)
    count = 0
    for ref in store.referrals.values():
        if ref["legal_aid_org_id"] != org_id:
            continue
        if ref["status"] not in ("DISPATCHED", "ACCEPTED"):
            continue
        d = ref["dispatched_at"]
        if d is not None and week_start <= d < week_end:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Retention / purge
# ---------------------------------------------------------------------------

def applicable_policy(jurisdiction_id, issue_category):
    """Precedence: exact pair; (J, null); (null, C); (null, null). ACTIVE only."""
    def find(j, c):
        for p in store.policies.values():
            if p["status"] == "ACTIVE" and p["jurisdiction_id"] == j and p["issue_category"] == c:
                return p
        return None

    return (
        find(jurisdiction_id, issue_category)
        or find(jurisdiction_id, None)
        or find(None, issue_category)
        or find(None, None)
    )


def retention_anchor(caller_id):
    """(max closed_at, anchor case) over the caller's CLOSED cases."""
    best_case = None
    for c in store.cases.values():
        if c["caller_id"] != caller_id or c["status"] != "CLOSED" or c["closed_at"] is None:
            continue
        if best_case is None or c["closed_at"] > best_case["closed_at"]:
            best_case = c
    if best_case is None:
        return None, None
    return best_case["closed_at"], best_case


def caller_retention_eligible(caller, at=None):
    at = at or now()
    if caller["pii_purged"]:
        return False
    anchor, anchor_case = retention_anchor(caller["id"])
    if anchor is None:
        return False
    policy = applicable_policy(anchor_case["jurisdiction_id"], anchor_case["issue_category"])
    if policy is None:
        return False
    return at >= anchor + timedelta(days=policy["retention_days"])


# ---------------------------------------------------------------------------
# Time sweep (pinned order: consents, follow-ups, referrals, purge jobs)
# ---------------------------------------------------------------------------

def run_time_sweep():
    t = now()
    consents_expired = 0
    follow_ups_due = 0
    follow_ups_missed = 0
    referrals_expired = 0
    purge_jobs_created = 0

    # 1. consent expirations (strictly past expires_at)
    for consent in sorted(store.consents.values(), key=lambda c: (c["created_at"], c["_seq"])):
        if consent["status"] == "GRANTED" and t > consent["expires_at"]:
            expire_consent(consent)
            consents_expired += 1

    # 2. follow-ups by scheduled_for ASC, ties by created_at ASC; one sweep may
    #    walk SCHEDULED -> DUE -> MISSED
    follow_ups = sorted(
        store.follow_ups.values(), key=lambda f: (f["scheduled_for"], f["created_at"], f["_seq"])
    )
    for fu in follow_ups:
        if fu["status"] == "SCHEDULED" and t >= fu["scheduled_for"]:
            fu["status"] = "DUE"
            bump(fu)
            follow_ups_due += 1
        if fu["status"] == "DUE" and t > fu["scheduled_for"] + timedelta(hours=DUE_WINDOW_HOURS):
            miss_follow_up(fu)
            follow_ups_missed += 1

    # 3. referral expirations by created_at ASC (strictly past the deadline)
    for ref in sorted(store.referrals.values(), key=lambda r: (r["created_at"], r["_seq"])):
        if ref["status"] == "PROPOSED" and t > ref["sla_dispatch_by"]:
            ref["status"] = "EXPIRED"
            bump(ref)
            referrals_expired += 1
        elif (
            ref["status"] == "DISPATCHED"
            and ref["accept_by"] is not None
            and t > ref["accept_by"]
        ):
            ref["status"] = "EXPIRED"  # releases the org slot (computed on read)
            bump(ref)
            referrals_expired += 1

    # 4. purge-job creation for retention-eligible callers, caller created_at ASC
    for caller in sorted(store.callers.values(), key=lambda c: (c["created_at"], c["_seq"])):
        pending = any(
            j["caller_id"] == caller["id"] and j["status"] == "PENDING"
            for j in store.purge_jobs.values()
        )
        if pending:
            continue
        if not caller_retention_eligible(caller, at=t):
            continue
        job = make_record({
            "caller_id": caller["id"],
            "status": "PENDING",
            "created_by_sweep": True,
            "executed_at": None,
            "blocked_reason": None,
        })
        store.purge_jobs[job["id"]] = job
        purge_jobs_created += 1

    return {
        "consents_expired": consents_expired,
        "follow_ups_due": follow_ups_due,
        "follow_ups_missed": follow_ups_missed,
        "referrals_expired": referrals_expired,
        "purge_jobs_created": purge_jobs_created,
    }
