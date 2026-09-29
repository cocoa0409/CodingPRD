"""Shared domain services: lookups, conserved-quantity recomputation, queue and
reviewer selection, SLA arithmetic and the accuracy gate."""

from datetime import timedelta

from core import (
    ACTION_WEIGHT, ESCALATION_SLA_MINUTES, LEGAL_SLA_MINUTES,
    MEDIA_EXPOSURE_MULTIPLIER, MIN_GATE_SAMPLE, OPEN_CASE_STATUSES,
    REPEAT_MULTIPLIER_CAP_REMOVALS, REPEAT_MULTIPLIER_STEP, RETRAIN_FLOOR,
    SEVERITY_POINTS, SEVERITY_SLA_DIVISOR, STANDING_BANNED_AT,
    STANDING_LIMITED_AT, STANDING_SUSPENDED_AT, SUSPEND_FLOOR,
    ceil_int, db, dec, div4, fail, fmt_ts, now, sort_key, touch,
)

# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def find(table, record_id, error_id):
    record = table.get(record_id) if isinstance(record_id, str) else None
    if record is None:
        fail(error_id)
    return record


def content_of(case):
    return db.content_items.get(case["content_item_id"])


def version_of(case):
    return db.policy_versions.get(case.get("policy_version_id"))


def category_of_case(case):
    version = version_of(case)
    if version is None:
        return None
    return db.policy_categories.get(version["policy_category_id"])


def account_of_case(case):
    content = content_of(case)
    if content is None:
        return None
    return db.accounts.get(content["account_id"])


def exposure_charge(content):
    return int(content.get("graphic_weight") or 0) * MEDIA_EXPOSURE_MULTIPLIER[content["media_kind"]]


def cases_of_account(account_id):
    item_ids = {c["id"] for c in db.content_items.values() if c["account_id"] == account_id}
    return [mc for mc in db.moderation_cases.values() if mc["content_item_id"] in item_ids]


def cases_decided_by(reviewer_id):
    return [mc for mc in db.moderation_cases.values()
            if mc.get("decided_by_reviewer_id") == reviewer_id]


# --------------------------------------------------------------------------
# Conserved quantity 1: the account strike ledger (PRD §2.10, §3.1)
# --------------------------------------------------------------------------

def standing_for(strike_points):
    if strike_points >= STANDING_BANNED_AT:
        return "BANNED"
    if strike_points >= STANDING_SUSPENDED_AT:
        return "SUSPENDED"
    if strike_points >= STANDING_LIMITED_AT:
        return "LIMITED"
    return "GOOD_STANDING"


def recompute_account(account):
    """Full recompute of lifetime_removed_count, strike_points and standing --
    never an incremental delta (PRD §2.10)."""
    total = 0
    removed = 0
    for mc in cases_of_account(account["id"]):
        if mc["status"] != "DECIDED" or mc.get("is_overturned"):
            continue
        total += int(mc.get("strike_points_applied") or 0)
        if mc.get("decision_outcome") == "REMOVE":
            removed += 1
    account["lifetime_removed_count"] = removed
    account["strike_points"] = total
    account["standing"] = standing_for(total)
    touch(account)


def strike_points_applied(category, outcome, prior_removals):
    """Multiply base x weight x repeat multiplier, then ceil ONCE (PRD §3.5)."""
    base = dec(SEVERITY_POINTS[category["severity_tier"]])
    weight = ACTION_WEIGHT[outcome]
    mult = dec(1) + REPEAT_MULTIPLIER_STEP * dec(min(prior_removals, REPEAT_MULTIPLIER_CAP_REMOVALS))
    return ceil_int(base * weight * mult)


# --------------------------------------------------------------------------
# Queue selection and the review deadline (PRD §3.3)
# --------------------------------------------------------------------------

def select_queue(policy_category_id, language):
    candidates = [q for q in db.review_queues.values()
                  if q["policy_category_id"] == policy_category_id and q["language"] == language]
    if not candidates:
        return None
    candidates.sort(key=lambda q: (q["unassigned_case_count"], sort_key(q)))
    return candidates[0]


def congestion_multiplier(open_count):
    if open_count <= 5:
        return dec("1.0")
    if open_count <= 15:
        return dec("1.5")
    return dec("2.0")


def sla_minutes(queue, pinned_version, category):
    """Steps 2-4 of calculations.review_sla_due_at: read the POST-increment
    open_case_count, convert to a congestion multiplier, then ceil the single
    quotient."""
    congestion = congestion_multiplier(queue["open_case_count"])
    divisor = dec(SEVERITY_SLA_DIVISOR[category["severity_tier"]])
    return ceil_int(dec(pinned_version["review_sla_minutes"]) * congestion / divisor)


def plus_minutes(instant, minutes):
    return fmt_ts(instant + timedelta(minutes=int(minutes)))


# --------------------------------------------------------------------------
# Conserved quantity 3: reviewer exposure, and the accuracy gate (PRD §3.8)
# --------------------------------------------------------------------------

def recompute_reviewer_accuracy(reviewer, run_gate=True):
    """Re-derive the four quality counters and both accuracy variants, then run
    the accuracy gate.  Returns nothing; mutates the reviewer in place."""
    if reviewer is None:
        return
    decided_ids = {mc["id"] for mc in cases_decided_by(reviewer["id"])}
    audited = 0
    agree = 0
    for sample in db.audit_samples.values():
        if sample["case_id"] not in decided_ids:
            continue
        if sample["status"] != "AUDITED" or not sample.get("counts_toward_accuracy"):
            continue
        audited += 1
        if sample.get("verdict") == "AGREE":
            agree += 1
    appeals = 0
    upheld = 0
    for ap in db.appeals.values():
        if ap["case_id"] not in decided_ids:
            continue
        if ap["status"] not in ("UPHELD", "OVERTURNED"):
            continue
        appeals += 1
        if ap["status"] == "UPHELD":
            upheld += 1

    reviewer["audited_count"] = audited
    reviewer["agree_count"] = agree
    reviewer["appealed_count"] = appeals
    reviewer["upheld_appeal_count"] = upheld
    reviewer["accuracy_score_audit_only"] = div4(agree, audited) if audited >= 1 else None
    blended_denominator = audited + appeals
    reviewer["accuracy_score_blended"] = (
        div4(agree + upheld, blended_denominator) if blended_denominator >= 1 else None
    )
    touch(reviewer)

    if not run_gate:
        return
    if blended_denominator < MIN_GATE_SAMPLE:
        return
    gate_score = (reviewer["accuracy_score_blended"] if appeals >= 1
                  else reviewer["accuracy_score_audit_only"])
    if gate_score is None:
        return
    if reviewer["status"] != "ACTIVE":
        return
    if gate_score < SUSPEND_FLOOR:
        suspend_reviewer(reviewer)
    elif gate_score < RETRAIN_FLOOR:
        demote_to_retraining(reviewer)


def held_assigned_cases(reviewer_id):
    cases = [mc for mc in db.moderation_cases.values()
             if mc.get("assigned_reviewer_id") == reviewer_id and mc["status"] == "ASSIGNED"]
    cases.sort(key=sort_key)
    return cases


def demote_to_retraining(reviewer):
    """PENDING_RETRAINING keeps the reviewer's ASSIGNED cases assigned but flags
    each of them for recertified review (PRD §3.8)."""
    reviewer["status"] = "PENDING_RETRAINING"
    for case in held_assigned_cases(reviewer["id"]):
        case["requires_recertified_review"] = True
        touch(case)


def release_cases_to_queue(reviewer):
    """Shared by the wellness break and the SUSPENDED arm of the accuracy gate:
    every ASSIGNED case returns to PENDING_ASSIGNMENT, the reviewer's workload
    and exposure counters reset to 0, and each affected queue's
    unassigned_case_count rises by one.  Queue open_case_count and each case's
    sla_due_at are deliberately left untouched."""
    for case in held_assigned_cases(reviewer["id"]):
        case["status"] = "PENDING_ASSIGNMENT"
        case["assigned_reviewer_id"] = None
        touch(case)
        queue = db.review_queues.get(case.get("queue_id"))
        if queue is not None:
            queue["unassigned_case_count"] += 1
            touch(queue)
    reviewer["open_case_count"] = 0
    reviewer["exposure_points_today"] = 0


def suspend_reviewer(reviewer):
    reviewer["status"] = "SUSPENDED"
    release_cases_to_queue(reviewer)


# --------------------------------------------------------------------------
# Reviewer eligibility and the ranked selector (PRD §3.4)
# --------------------------------------------------------------------------

def certification_target(case):
    """Conditional on the case flag: the PINNED version normally, the category's
    CURRENT active version once requires_recertified_review is true."""
    if case.get("requires_recertified_review"):
        category = category_of_case(case)
        return category.get("active_version_id") if category else None
    return case.get("policy_version_id")


def local_hour(reviewer, instant):
    utc_minutes = instant.hour * 60 + instant.minute
    return ((utc_minutes + int(reviewer["utc_offset_minutes"])) // 60) % 24


def in_shift(reviewer, instant):
    hour = local_hour(reviewer, instant)
    start = int(reviewer["shift_start_local_hour"])
    end = int(reviewer["shift_end_local_hour"])
    if end > start:
        return start <= hour < end
    return hour >= start or hour < end


def blended_rank(reviewer):
    score = reviewer.get("accuracy_score_blended")
    return dec("1.0000") if score is None else dec(score)


def rank_candidates(candidates):
    return sorted(
        candidates,
        key=lambda r: (r["open_case_count"], -blended_rank(r), sort_key(r)[0], sort_key(r)[1]),
    )


def eligible_reviewer(reviewer, case, queue, charge, exclude_ids, require_senior):
    if reviewer["status"] != "ACTIVE":
        return False
    target = certification_target(case)
    if target is None or target not in (reviewer.get("certified_policy_version_ids") or []):
        return False
    if queue is not None:
        if queue["language"] not in reviewer["languages"]:
            return False
        if queue["specialty"] not in reviewer["specialties"]:
            return False
    if reviewer["open_case_count"] >= reviewer["max_concurrent_cases"]:
        return False
    if reviewer["exposure_points_today"] + charge > reviewer["daily_exposure_cap_points"]:
        return False
    if not in_shift(reviewer, now()):
        return False
    if reviewer["id"] in exclude_ids:
        return False
    if case.get("assigned_reviewer_id") and reviewer["id"] == case["assigned_reviewer_id"]:
        return False
    if require_senior and reviewer["role_class"] not in ("SENIOR", "QA"):
        return False
    return True


def select_reviewer(case, queue, charge, exclude_ids, require_senior):
    pool = [r for r in db.reviewers.values()
            if eligible_reviewer(r, case, queue, charge, exclude_ids, require_senior)]
    if not pool:
        return None
    return rank_candidates(pool)[0]


def vet_directed_reviewer(reviewer, case, queue, charge, require_senior):
    """When target_reviewer_id names a specific reviewer each predicate is
    checked individually, in the order fixed by PRD §2.8."""
    if reviewer["status"] != "ACTIVE":
        fail("ERR_REVIEWER_NOT_ACTIVE")
    target = certification_target(case)
    if target is None or target not in (reviewer.get("certified_policy_version_ids") or []):
        fail("ERR_REVIEWER_NOT_CERTIFIED")
    if queue is not None:
        if queue["language"] not in reviewer["languages"]:
            fail("ERR_REVIEWER_LANGUAGE_MISMATCH")
        if queue["specialty"] not in reviewer["specialties"]:
            fail("ERR_REVIEWER_LANGUAGE_MISMATCH")
    if reviewer["exposure_points_today"] + charge > reviewer["daily_exposure_cap_points"]:
        fail("ERR_EXPOSURE_CAP_EXCEEDED")
    if not in_shift(reviewer, now()):
        fail("ERR_REVIEWER_OFF_SHIFT")
    if reviewer["open_case_count"] >= reviewer["max_concurrent_cases"]:
        fail("ERR_REVIEWER_AT_CAPACITY")
    if require_senior and reviewer["role_class"] not in ("SENIOR", "QA"):
        fail("ERR_REVIEWER_NOT_ELIGIBLE_FOR_ESCALATION")
