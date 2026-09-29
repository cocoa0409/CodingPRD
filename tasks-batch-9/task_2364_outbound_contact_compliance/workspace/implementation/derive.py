"""Derived-field recomputation and the synchronous cascades of PRD §2.10.

Computed fields are stored on the row that owns them and recomputed whenever
that row is served or mutated. A recomputation that leaves every value
unchanged does not bump ``version`` — that keeps GET idempotent, which matters
because the optimistic-concurrency preconditions of §2.6 compare against the
version a client just read.
"""

from datetime import timedelta

import calculations as calc
from db import base_row, by_created_at, db, now, now_iso, public, touch
from util import D, add_days, date_str, dt_of, pct, round_half_up

CONSENT_STATUSES = ("ACTIVE", "SUSPENDED", "REVOKED", "SUPERSEDED")


# =============================================================================
# small collection helpers
# =============================================================================


def rows(collection):
    return list(getattr(db, collection).values())


def attempts_of_contact(contact_id):
    return [a for a in rows("contact_attempts") if a["contact_id"] == contact_id]


def attempts_of_campaign(campaign_id):
    return [a for a in rows("contact_attempts") if a["campaign_id"] == campaign_id]


def consents_of_contact(contact_id):
    return [c for c in rows("consent_records") if c["contact_id"] == contact_id]


def complaints_of_contact(contact_id):
    return [c for c in rows("complaints") if c["contact_id"] == contact_id]


def revocations_of_contact(contact_id):
    return [r for r in rows("revocation_requests") if r["contact_id"] == contact_id]


def jobs_of_campaign(campaign_id):
    return [j for j in rows("scrub_jobs") if j["campaign_id"] == campaign_id]


def _newest_first(jobs):
    """Order jobs newest-first: requested_at DESC, ties broken by created_at ASC.

    Both stamps are written from the same logical-clock instant, so whenever
    requested_at ties, created_at ties with it and the documented tiebreak
    resolves nothing. The remaining ambiguity is settled by insertion order, so
    that the most recently queued job is the newest one.
    """
    ordered = sorted(jobs, key=lambda j: j["_seq"], reverse=True)
    ordered.sort(key=lambda j: j["created_at"])
    ordered.sort(key=lambda j: j["requested_at"], reverse=True)
    return ordered


def newest_scrub_job(campaign_id):
    """Newest job by requested_at DESC, ties broken by created_at ASC."""
    jobs = _newest_first(jobs_of_campaign(campaign_id))
    return jobs[0] if jobs else None


def newest_completed_job(campaign_id):
    jobs = _newest_first(
        [j for j in jobs_of_campaign(campaign_id) if j["status"] == "COMPLETED"]
    )
    return jobs[0] if jobs else None


def select_consent(contact_id, channel):
    """§3.2 consent basis selector: ACTIVE only, captured_at DESC, created_at ASC."""
    candidates = [
        c
        for c in consents_of_contact(contact_id)
        if c["channel"] == channel and c["status"] == "ACTIVE"
    ]
    if not candidates:
        return None
    candidates = by_created_at(candidates)
    candidates.sort(key=lambda c: c["captured_at"], reverse=True)
    return candidates[0]


def select_policy(state_code):
    """§3.5 policy selector: ACTIVE, half-open period, effective_from DESC."""
    stamp = now()
    candidates = []
    for policy in rows("calling_window_policies"):
        if policy["state_code"] != state_code or policy["status"] != "ACTIVE":
            continue
        start = dt_of(policy["effective_from"])
        end = dt_of(policy["effective_to"])
        if start <= stamp < end:
            candidates.append(policy)
    if not candidates:
        return None
    candidates = by_created_at(candidates)
    candidates.sort(key=lambda p: p["effective_from"], reverse=True)
    return candidates[0]


def active_policies_for_state(state_code):
    return [
        p
        for p in rows("calling_window_policies")
        if p["state_code"] == state_code and p["status"] == "ACTIVE"
    ]


def contact_by_phone(phone_number):
    for contact in rows("contacts"):
        if contact["phone_number"] == phone_number:
            return contact
    return None


# =============================================================================
# Contact
# =============================================================================


def recompute_contact(contact):
    """Refresh every computed field of a contact; returns True when it changed."""
    before = dict(contact)

    charged = len([a for a in attempts_of_contact(contact["id"]) if a["voided_at"] is None])
    contact["attempts_charged"] = charged
    remaining = contact["attempt_budget_total"] - charged
    contact["attempt_budget_remaining"] = remaining if remaining > 0 else 0

    consents = consents_of_contact(contact["id"])
    counts = {status: 0 for status in CONSENT_STATUSES}
    for record in consents:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    contact["active_consent_count"] = counts["ACTIVE"]
    contact["suspended_consent_count"] = counts["SUSPENDED"]
    contact["revoked_consent_count"] = counts["REVOKED"]
    contact["superseded_consent_count"] = counts["SUPERSEDED"]
    contact["total_consent_count"] = len(consents)

    peak = None
    for complaint in complaints_of_contact(contact["id"]):
        if complaint["status"] != "SUBSTANTIATED":
            continue
        score = complaint.get("adjudicated_risk_score")
        if score is None:
            continue
        value = D(score)
        if peak is None or value > peak:
            peak = value
    contact["risk_tier"] = calc.risk_tier(peak)

    suppressed = counts["REVOKED"] > 0 or contact["risk_tier"] == "CRITICAL"
    contact["internal_dnc_status"] = "SUPPRESSED" if suppressed else "CLEAR"

    contact["overdue_propagation_count"] = len(
        [r for r in revocations_of_contact(contact["id"]) if r["propagation_status"] == "OVERDUE"]
    )
    contact["rnd_safe_harbor_eligible"] = contact["rnd_result"] == "NO_DATA"

    return any(before.get(key) != value for key, value in contact.items())


def contact_view(contact):
    recompute_contact(contact)
    return public(contact)


def touch_contact(contact):
    recompute_contact(contact)
    touch(contact)


# =============================================================================
# Campaign
# =============================================================================


def _day_counts(campaign, target_date):
    """(live, abandoned) recorded on ``target_date`` for this campaign."""
    live = 0
    aband = 0
    for attempt in attempts_of_campaign(campaign["id"]):
        if attempt["voided_at"] is not None or attempt["outcome_recorded_at"] is None:
            continue
        if date_str(dt_of(attempt["outcome_recorded_at"])) != target_date:
            continue
        if attempt["outcome"] == "ABANDONED":
            live += 1
            aband += 1
        elif attempt["outcome"] == "CONNECTED_LIVE":
            live += 1
    return live, aband


def _today_counters(campaign):
    measurement_date = campaign["measurement_date"]
    counters = {
        "live_answer_count_today": 0,
        "abandoned_count_today": 0,
        "machine_count_today": 0,
        "no_answer_count_today": 0,
    }
    if measurement_date is None:
        return counters
    for attempt in attempts_of_campaign(campaign["id"]):
        if attempt["voided_at"] is not None or attempt["outcome_recorded_at"] is None:
            continue
        if date_str(dt_of(attempt["outcome_recorded_at"])) != measurement_date:
            continue
        outcome = attempt["outcome"]
        if outcome == "CONNECTED_LIVE":
            counters["live_answer_count_today"] += 1
        elif outcome == "ABANDONED":
            counters["live_answer_count_today"] += 1
            counters["abandoned_count_today"] += 1
        elif outcome == "MACHINE_ANSWERED":
            counters["machine_count_today"] += 1
        elif outcome == "NO_ANSWER":
            counters["no_answer_count_today"] += 1
    return counters


def _rolling_rate(campaign):
    measurement_date = campaign["measurement_date"]
    if measurement_date is None:
        return D("0.00")
    anchor = dt_of(measurement_date + "T00:00:00Z")
    history = {entry["date"]: entry for entry in campaign["daily_rate_history"]}
    samples = []
    for back in range(calc.ROLLING_WINDOW_DAYS - 1, -1, -1):
        day = date_str(anchor - timedelta(days=back))
        if day == measurement_date:
            samples.append(
                (campaign["live_answer_count_today"], campaign["abandoned_count_today"])
            )
        elif day in history:
            entry = history[day]
            samples.append((entry["live_answer_count"], entry["abandoned_count"]))
    return calc.rolling_compliance_rate(samples)


def recompute_campaign(campaign):
    before = dict(campaign)

    campaign.update(_today_counters(campaign))
    live = campaign["live_answer_count_today"]
    aband = campaign["abandoned_count_today"]
    machine = campaign["machine_count_today"]
    campaign["regulatory_abandonment_rate_pct"] = pct(calc.regulatory_rate(live, aband))
    campaign["internal_abandonment_rate_pct"] = pct(calc.internal_rate(live, machine, aband))
    campaign["rolling_compliance_rate_pct"] = pct(_rolling_rate(campaign))

    attempts = attempts_of_campaign(campaign["id"])
    campaign["permitted_attempt_count"] = len([a for a in attempts if a["voided_at"] is None])
    campaign["voided_attempt_count"] = len([a for a in attempts if a["voided_at"] is not None])

    newest = newest_scrub_job(campaign["id"])
    campaign["latest_scrub_status"] = newest["status"] if newest else None
    completed = newest_completed_job(campaign["id"])
    campaign["eligible_target_count"] = completed["eligible_target_count"] if completed else 0

    return any(before.get(key) != value for key, value in campaign.items())


def campaign_view(campaign):
    recompute_campaign(campaign)
    return public(campaign)


def touch_campaign(campaign):
    recompute_campaign(campaign)
    touch(campaign)


def rollover_measurement_day(campaign):
    """§3.8: close the previous measurement day before counting a new outcome."""
    today = date_str(now())
    previous = campaign["measurement_date"]
    if previous is None or previous == today:
        return
    entry = {
        "date": previous,
        "live_answer_count": campaign["live_answer_count_today"],
        "abandoned_count": campaign["abandoned_count_today"],
        "rate_pct": pct(
            calc.regulatory_rate(
                campaign["live_answer_count_today"], campaign["abandoned_count_today"]
            )
        ),
    }
    history = [e for e in campaign["daily_rate_history"] if e["date"] != previous]
    history.append(entry)
    history.sort(key=lambda e: e["date"])
    campaign["daily_rate_history"] = history
    campaign["measurement_date"] = today
    campaign["live_answer_count_today"] = 0
    campaign["abandoned_count_today"] = 0
    campaign["machine_count_today"] = 0
    campaign["no_answer_count_today"] = 0


# =============================================================================
# DialerProfile pacing snapshot
# =============================================================================


def pacing_lines(profile, campaign=None):
    rate = campaign["regulatory_abandonment_rate_pct"] if campaign else D("0.00")
    return calc.dialer_pacing_lines(
        profile["mode"], profile["agents_available"], profile["abandonment_limit_pct"], rate
    )


def refresh_profile_lines(profile, campaign=None):
    value = pacing_lines(profile, campaign)
    if profile["max_lines_last_computed"] != value:
        profile["max_lines_last_computed"] = value
        touch(profile)


# =============================================================================
# Attempt voiding and campaign suspension cascades
# =============================================================================


def void_attempt(attempt, reason, bump_campaign=True):
    attempt["voided_at"] = now_iso()
    attempt["void_reason"] = reason
    attempt["outcome"] = "VOIDED"
    touch(attempt)

    contact = db.contacts.get(attempt["contact_id"])
    if contact is not None:
        touch_contact(contact)
    campaign = db.campaigns.get(attempt["campaign_id"])
    if campaign is not None:
        if bump_campaign:
            touch_campaign(campaign)
        else:
            recompute_campaign(campaign)
    profile = None
    if campaign is not None:
        profile = db.dialer_profiles.get(campaign["dialer_profile_id"])
    if profile is not None:
        refresh_profile_lines(profile, campaign)


def _void_pending_attempts(campaign):
    for attempt in by_created_at(attempts_of_campaign(campaign["id"])):
        if attempt["outcome"] == "PENDING" and attempt["voided_at"] is None:
            void_attempt(attempt, "CAMPAIGN_SUSPENDED", bump_campaign=False)


def suspend_campaign(campaign, reason):
    """Every suspension path: status change, pending attempts voided, one bump."""
    campaign["status"] = "SUSPENDED"
    campaign["suspension_reason"] = reason
    _void_pending_attempts(campaign)
    touch_campaign(campaign)


# =============================================================================
# Internal suppression cascades (§3.2, §3.3, §3.4, §3.9)
# =============================================================================


def ensure_internal_suppression(contact):
    for entry in rows("suppression_entries"):
        if (
            entry["list_type"] == "INTERNAL"
            and entry["status"] == "ACTIVE"
            and entry["phone_number"] == contact["phone_number"]
        ):
            return None
    entry = base_row()
    entry.update(
        {
            "list_type": "INTERNAL",
            "phone_number": contact["phone_number"],
            "state_code": None,
            "source": "CONSUMER_REQUEST",
            "source_refreshed_at": now_iso(),
            "status": "ACTIVE",
            "removed_at": None,
            "removal_reason": None,
        }
    )
    db.suppression_entries[entry["id"]] = entry
    return entry


def remove_internal_entries_for(phone_number):
    for entry in rows("suppression_entries"):
        if (
            entry["list_type"] == "INTERNAL"
            and entry["status"] == "ACTIVE"
            and entry["phone_number"] == phone_number
        ):
            entry["status"] = "REMOVED"
            entry["removed_at"] = now_iso()
            entry["removal_reason"] = "CONSENT_REINSTATED"
            touch(entry)


def invalidate_internal_scrubs(state_code):
    """Hops 3 and 4: invalidate current INTERNAL scrubs, suspend their campaigns."""
    stamp = now()
    affected = []
    for job in by_created_at(rows("scrub_jobs")):
        if job["status"] != "COMPLETED":
            continue
        if "INTERNAL" not in job["list_types"]:
            continue
        expires = dt_of(job["expires_at"])
        if expires is None or not expires > stamp:
            continue
        campaign = db.campaigns.get(job["campaign_id"])
        if campaign is None or state_code not in campaign["target_state_codes"]:
            continue
        job["status"] = "INVALIDATED"
        job["invalidation_reason"] = "NEW_INTERNAL_SUPPRESSION"
        touch(job)
        if campaign["id"] not in affected:
            affected.append(campaign["id"])

    for campaign_id in affected:
        campaign = db.campaigns.get(campaign_id)
        if campaign is None:
            continue
        recompute_campaign(campaign)
        if campaign["status"] == "ACTIVE" and campaign["latest_scrub_status"] == "INVALIDATED":
            suspend_campaign(campaign, "SCRUB_STALE")
        else:
            touch_campaign(campaign)


def suppress_contact_internally(contact):
    """Hop 2 + hops 3/4 of the revocation cascade."""
    touch_contact(contact)
    ensure_internal_suppression(contact)
    invalidate_internal_scrubs(contact["state_code"])


# =============================================================================
# Suppression coverage of a number (§3.8)
# =============================================================================


def number_is_suppressed(contact):
    for entry in rows("suppression_entries"):
        if entry["status"] != "ACTIVE":
            continue
        if entry["phone_number"] != contact["phone_number"]:
            continue
        if entry["list_type"] == "STATE":
            if entry.get("state_code") == contact["state_code"]:
                return True
            continue
        return True
    return False


# =============================================================================
# Complaint pattern clusters (§3.9)
# =============================================================================


def _cluster_size(anchor):
    anchor_at = dt_of(anchor["received_at"])
    window = timedelta(days=calc.PATTERN_WINDOW_DAYS)
    size = 0
    for other in rows("complaints"):
        if other["campaign_id"] != anchor["campaign_id"]:
            continue
        if other["alleged_violation_type"] != anchor["alleged_violation_type"]:
            continue
        if other["status"] not in ("OPEN", "SUBSTANTIATED"):
            continue
        delta = dt_of(other["received_at"]) - anchor_at
        if abs(delta) <= window:
            size += 1
    return size


def recompute_clusters(anchor, skip_anchor_touch=False):
    """Rewrite pattern_cluster_size for every row sharing the anchor's pair."""
    peers = [
        c
        for c in rows("complaints")
        if c["campaign_id"] == anchor["campaign_id"]
        and c["alleged_violation_type"] == anchor["alleged_violation_type"]
    ]
    for complaint in by_created_at(peers):
        size = _cluster_size(complaint)
        if complaint["pattern_cluster_size"] == size:
            continue
        complaint["pattern_cluster_size"] = size
        if complaint["id"] == anchor["id"] and skip_anchor_touch:
            continue
        touch(complaint)


def verified_attempt_count(contact_id, campaign_id):
    total = 0
    for attempt in rows("contact_attempts"):
        if attempt["contact_id"] != contact_id or attempt["campaign_id"] != campaign_id:
            continue
        if attempt["voided_at"] is not None or attempt["outcome"] == "PENDING":
            continue
        total += 1
    return total


# =============================================================================
# Consent census bookkeeping
# =============================================================================


def revoke_consents_in_scope(contact, scope):
    """Hop 1 of the revocation cascade; returns the number of rows moved."""
    channels = ("VOICE", "SMS") if scope == "ALL_CHANNELS" else (scope,)
    moved = 0
    for record in by_created_at(consents_of_contact(contact["id"])):
        if record["channel"] not in channels:
            continue
        if record["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        record["status"] = "REVOKED"
        record["revoked_at"] = now_iso()
        touch(record)
        moved += 1
    return moved
