"""Every calculation rule from PRD section 3 / scaffold section 1.3."""

import math
from decimal import Decimal, ROUND_HALF_UP

import db
from db import store


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, digits):
    quant = Decimal(1).scaleb(-digits)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# change_risk_score  (PRD 3.3)
# ---------------------------------------------------------------------------
BLAST_POINTS = {"INTERNAL": 0, "SINGLE_TENANT": 10, "GLOBAL": 20}
CREDIT_STATES = ("DRAFT", "ACTIVE_ROLLING_OUT", "FULLY_ROLLED_OUT")
APPROVALS_REQUIRED = {
    "LOW": (),
    "MEDIUM": ("TECHNICAL",),
    "HIGH": ("TECHNICAL", "COMPLIANCE"),
    "CRITICAL": ("TECHNICAL", "COMPLIANCE", "CAB"),
}


def _flag_credit(change):
    """-15 for a qualifying GATES_ENTIRE_CHANGE guard, else -5 for a qualifying
    PARTIAL guard, else 0.  The larger credit magnitude wins."""
    whole = False
    partial = False
    for link in db.links_of_change(change["id"]):
        flag = store.feature_flags.get(link["feature_flag_id"])
        if flag is None or flag["state"] not in CREDIT_STATES:
            continue
        if link["guard_kind"] == "GATES_ENTIRE_CHANGE":
            whole = True
        elif link["guard_kind"] == "PARTIAL":
            partial = True
    if whole:
        return -15
    if partial:
        return -5
    return 0


def change_risk_score(change, depth_input):
    """Pinned evaluation order: raw points, then credits, then clamp."""
    size_points = min(30, int(math.ceil(change["lines_changed"] / 100.0)) * 5)
    spread_points = min(20, change["touched_subsystem_count"] * 4)
    migration_points = 25 if change["has_schema_migration"] else 0
    blast_points = BLAST_POINTS[change["declared_blast_radius"]]
    dependency_points = min(15, depth_input * 5)
    raw_points = (
        size_points + spread_points + migration_points + blast_points + dependency_points
    )

    if change["rollback_plan"] is not None and change["rollback_tested"]:
        rollback_credit = -10
    elif change["rollback_plan"] is not None:
        rollback_credit = -5
    else:
        rollback_credit = 0

    score = raw_points + rollback_credit + _flag_credit(change)
    return max(0, min(100, score))


def risk_tier(score):
    if score < 25:
        return "LOW"
    if score < 50:
        return "MEDIUM"
    if score < 70:
        return "HIGH"
    return "CRITICAL"


def preliminary_risk_score(change):
    """DEPTH_INPUT is unconditionally zero at submit time."""
    return change_risk_score(change, 0)


def final_risk_score(change):
    """Uses dependency_depth as it stands at approval."""
    return change_risk_score(change, change["dependency_depth"])


def dependency_depth(change_id, _seen=None):
    """Longest prerequisite chain reachable through dependency edges."""
    if _seen is None:
        _seen = set()
    if change_id in _seen:
        return 0
    _seen = _seen | {change_id}
    best = 0
    for edge in db.deps_from(change_id):
        candidate = 1 + dependency_depth(edge["to_change_id"], _seen)
        if candidate > best:
            best = candidate
    return best


def creates_cycle(from_id, to_id):
    """True when adding from->to would close a cycle: does `to` already reach
    `from` through existing prerequisite edges?"""
    if from_id == to_id:
        return True
    stack = [to_id]
    seen = set()
    while stack:
        current = stack.pop()
        if current == from_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        for edge in db.deps_from(current):
            stack.append(edge["to_change_id"])
    return False


# ---------------------------------------------------------------------------
# release_readiness_score  (PRD 3.2)
# ---------------------------------------------------------------------------
PROJECTED_STATES = (
    "RISK_CLASSIFIED",
    "CAB_REVIEW",
    "APPROVED",
    "MERGED",
    "DEPLOYED",
    "BLOCKED_BY_DEPENDENCY",
)
UNLANDED_STATES = (
    "RISK_CLASSIFIED",
    "CAB_REVIEW",
    "APPROVED",
    "BLOCKED_BY_DEPENDENCY",
    "DEFERRED",
)
STALE_CLEANUP_STATES = ("OVERDUE", "ENFORCED")


def _penalty(change_set):
    penalty = 0
    for change in change_set:
        if change["risk_class"] in ("HIGH", "CRITICAL") and not change["rollback_tested"]:
            penalty += 4
        if change["state"] == "BLOCKED_BY_DEPENDENCY":
            penalty += 5
    stale_flags = set()
    for change in change_set:
        for link in db.links_of_change(change["id"]):
            flag = store.feature_flags.get(link["feature_flag_id"])
            if flag is not None and flag["cleanup_state"] in STALE_CLEANUP_STATES:
                stale_flags.add(flag["id"])
    penalty += 3 * len(stale_flags)
    return penalty


def readiness_projected(release):
    changes = [
        c for c in db.changes_of_release(release["id"]) if c["state"] in PROJECTED_STATES
    ]
    return max(0, 100 - _penalty(changes))


def readiness_attested(release):
    freeze_at = release["freeze_at"]
    all_changes = db.changes_of_release(release["id"])
    landed = [
        c
        for c in all_changes
        if c["state"] in ("MERGED", "DEPLOYED")
        and c["merged_at"] is not None
        and c["merged_at"] < freeze_at
    ]
    late = len(
        [
            c
            for c in all_changes
            if c["state"] in ("MERGED", "DEPLOYED")
            and c["merged_at"] is not None
            and c["merged_at"] >= freeze_at
        ]
    )
    unlanded = len([c for c in all_changes if c["state"] in UNLANDED_STATES])
    return max(0, 100 - _penalty(landed) - 6 * late - 6 * unlanded)


def rollback_plan_confirmed(release):
    for change in db.changes_of_release(release["id"]):
        if change["state"] not in ("MERGED", "DEPLOYED"):
            continue
        if change["risk_class"] not in ("HIGH", "CRITICAL"):
            continue
        if change["rollback_plan"] is None or not change["rollback_tested"]:
            return False
    return True


def evidence_packet_required(release):
    for deployment in db.deployments_of_release(release["id"]):
        env = store.environments.get(deployment["environment_id"])
        if env is not None and env["requires_compliance_evidence"]:
            return True
    return False


def verified_change_count(release):
    return len([c for c in db.changes_of_release(release["id"]) if c["deployment_verified"]])


# ---------------------------------------------------------------------------
# canary_health_verdict  (PRD 3.7)
# ---------------------------------------------------------------------------
def canary_health_verdict(deployment, window_start, window_end):
    rows = [
        h
        for h in db.signals_of_deployment(deployment["id"])
        if h["cohort"] == "CANARY"
        and h["observed_at"] >= window_start
        and h["observed_at"] < window_end
    ]
    rows = sorted(rows, key=lambda r: (r["observed_at"], r["created_at"], r["_seq"]))

    sample_count = sum(r["request_count"] for r in rows)

    if sample_count < deployment["min_sample_count"]:
        return {
            "sample_count": sample_count,
            "error_rate_pct_rounded": 0,
            "latency_p95_ms": 0,
            "weighted_health_score": 0,
            "verdict": "INCONCLUSIVE",
            "abort_triggered": False,
        }

    # Step 1: per-row error rate rounded half up to one decimal.
    weighted_sum = Decimal(0)
    for row in rows:
        row_rate = round_half_up(
            dec(row["error_count"]) / dec(row["request_count"]) * dec(100), 1
        )
        weighted_sum += row_rate * dec(row["request_count"])
    # Step 2: request-weighted mean of the already rounded rates, 2 decimals.
    if sample_count > 0:
        error_rate = round_half_up(weighted_sum / dec(sample_count), 2)
    else:
        error_rate = Decimal(0)
    latency = max([r["latency_p95_ms"] for r in rows]) if rows else 0

    # Step 3: components at full precision, only the final score rounded.
    error_component = dec(100) - (error_rate / dec(deployment["abort_error_rate_pct"])) * dec(60)
    if error_component < 0:
        error_component = Decimal(0)
    latency_component = dec(100) - (
        dec(latency) / dec(deployment["abort_latency_p95_ms"])
    ) * dec(40)
    if latency_component < 0:
        latency_component = Decimal(0)
    score = round_half_up(
        dec("0.6") * error_component + dec("0.4") * latency_component, 2
    )

    abort = error_rate >= dec(deployment["abort_error_rate_pct"]) or latency >= deployment[
        "abort_latency_p95_ms"
    ]
    return {
        "sample_count": sample_count,
        "error_rate_pct_rounded": db.num(error_rate),
        "latency_p95_ms": latency,
        "weighted_health_score": db.num(score),
        "verdict": "FAIL" if abort else "PASS",
        "abort_triggered": bool(abort),
    }


# ---------------------------------------------------------------------------
# flag_stale_debt  (PRD 3.6)
# ---------------------------------------------------------------------------
DEBT_PER_DAY = 3
ENFORCED_THRESHOLD = 60
OVERDUE_THRESHOLD = 30
WARNING_LEAD_SECONDS = 604800


def flag_stale_debt(flag, now):
    if flag["permanent"] or flag["state"] == "ARCHIVED":
        return 0, "COMPLIANT"

    expires_at = flag["expires_at"]
    if now > expires_at:
        days_past = int((now - expires_at).total_seconds() // 86400)
    else:
        days_past = 0
    exposure_penalty = (
        20 if (flag["state"] == "PAUSED" and flag["current_exposure_pct"] > 0) else 0
    )
    orphan_penalty = 15 if len(db.links_of_flag(flag["id"])) == 0 else 0
    debt = min(100, days_past * DEBT_PER_DAY + exposure_penalty + orphan_penalty)

    if debt >= ENFORCED_THRESHOLD:
        cleanup = "ENFORCED"
    elif debt >= OVERDUE_THRESHOLD:
        cleanup = "OVERDUE"
    elif debt > 0:
        cleanup = "WARNING"
    elif (expires_at - now).total_seconds() <= WARNING_LEAD_SECONDS:
        cleanup = "WARNING"
    else:
        cleanup = "COMPLIANT"
    return debt, cleanup


# ---------------------------------------------------------------------------
# rollout_step_ladder  (PRD 3.5)
# ---------------------------------------------------------------------------
FIRST_RUNG_PCT = 5
RUNG_MULTIPLIER = 3


def ladder_ceiling(current_exposure_pct):
    prev = round_half_up(current_exposure_pct, 2)
    tripled = prev * dec(RUNG_MULTIPLIER)
    ceiling = tripled if tripled > dec(FIRST_RUNG_PCT) else dec(FIRST_RUNG_PCT)
    if ceiling > dec(100):
        ceiling = dec(100)
    return prev, round_half_up(ceiling, 2)


def target_pct_valid(current_exposure_pct, target_pct):
    prev, ceiling = ladder_ceiling(current_exposure_pct)
    target = round_half_up(target_pct, 2)
    return target > prev and target <= ceiling


def required_soak_minutes(target_pct):
    target = round_half_up(target_pct, 2)
    if target <= dec(10):
        return 30
    if target <= dec(50):
        return 60
    return 120


def next_step_index(flag_id):
    return len([s for s in db.steps_of_flag(flag_id) if s["state"] != "VOIDED"]) + 1


# ---------------------------------------------------------------------------
# release_note_generation  (PRD 3.9)
# ---------------------------------------------------------------------------
def release_note_generation(release, audience):
    candidates = [
        c
        for c in db.changes_of_release(release["id"])
        if c["state"] in ("MERGED", "DEPLOYED")
        and c["merged_at"] is not None
        and c["merged_at"] <= release["cut_at"]
    ]
    if audience == "CUSTOMER":
        included = [
            c
            for c in candidates
            if c["customer_facing"]
            and c["summary_customer_facing"] is not None
            and c["summary_customer_facing"] != ""
        ]
    else:
        included = list(candidates)
    included = sorted(included, key=lambda c: (c["merged_at"], c["created_at"], c["_seq"]))
    ids = [c["id"] for c in included]
    return ids, len(ids), len(candidates) - len(ids)


# ---------------------------------------------------------------------------
# incident_release_linkage  (PRD 3.8)
# ---------------------------------------------------------------------------
LINKAGE_WINDOW_HOURS = 72


def incident_release_linkage(train_id, detected_at):
    candidates = [
        r
        for r in db.releases_of_train(train_id)
        if r["phase"] in ("CUT", "STABILIZING", "RELEASED")
        and r["cut_at"] <= detected_at
        and (detected_at - r["cut_at"]).total_seconds() <= LINKAGE_WINDOW_HOURS * 3600
    ]
    if not candidates:
        return None, None
    ranked = sorted(candidates, key=lambda r: (-r["cut_at"].timestamp(), r["created_at"], r["_seq"]))
    release = ranked[0]

    completed = [
        d for d in db.deployments_of_release(release["id"]) if d["delivery_state"] == "COMPLETED"
    ]
    if not completed:
        return release["id"], None
    ranked_deps = sorted(
        completed,
        key=lambda d: (-d["window_start_at"].timestamp(), d["created_at"], d["_seq"]),
    )
    return release["id"], ranked_deps[0]["id"]


# ---------------------------------------------------------------------------
# evidence_completeness_index  (PRD 3.9)
# ---------------------------------------------------------------------------
ITEM_WEIGHTS = {
    "approvals_complete": 25,
    "rollback_plans": 20,
    "canary_pass": 15,
    "freeze_discipline": 15,
    "flag_hygiene": 15,
    "release_notes": 10,
}
ITEM_CODES = (
    "approvals_complete",
    "rollback_plans",
    "canary_pass",
    "freeze_discipline",
    "flag_hygiene",
    "release_notes",
)
WAIVER_CREDIT_RATE = Decimal("0.5")


def evidence_items(release):
    merged = [
        c for c in db.changes_of_release(release["id"]) if c["state"] in ("MERGED", "DEPLOYED")
    ]

    approvals_complete = True
    for change in merged:
        needed = APPROVALS_REQUIRED.get(change["risk_class"], ())
        rows = db.approvals_of_change(change["id"])
        for kind in needed:
            if not any(a["kind"] == kind and a["decision"] == "APPROVE" for a in rows):
                approvals_complete = False
                break
        if not approvals_complete:
            break

    rollback_plans = True
    for change in merged:
        if change["risk_class"] in ("HIGH", "CRITICAL"):
            if change["rollback_plan"] is None or not change["rollback_tested"]:
                rollback_plans = False
                break

    canary_pass = False
    for deployment in db.deployments_of_release(release["id"]):
        env = store.environments.get(deployment["environment_id"])
        if (
            env is not None
            and env["tier"] == "PROD"
            and deployment["verification_state"] == "PASSING"
        ):
            canary_pass = True
            break

    if release["freeze_exception_approved"]:
        freeze_discipline = True
    else:
        freeze_discipline = True
        for change in merged:
            if change["merged_at"] is None or not (change["merged_at"] < release["freeze_at"]):
                freeze_discipline = False
                break

    flag_hygiene = True
    for change in merged:
        for link in db.links_of_change(change["id"]):
            flag = store.feature_flags.get(link["feature_flag_id"])
            if flag is not None and flag["cleanup_state"] in STALE_CLEANUP_STATES:
                flag_hygiene = False
                break
        if not flag_hygiene:
            break

    release_notes = any(
        n["audience"] == "CUSTOMER" and n["state"] == "PUBLISHED"
        for n in db.notes_of_release(release["id"])
    )

    return {
        "approvals_complete": approvals_complete,
        "rollback_plans": rollback_plans,
        "canary_pass": canary_pass,
        "freeze_discipline": freeze_discipline,
        "flag_hygiene": flag_hygiene,
        "release_notes": release_notes,
    }


def waiver_cap(base_index):
    if base_index >= 85:
        return 15
    if base_index >= 70:
        return 10
    if base_index >= 50:
        return 5
    return 0


def waiver_totals(base_index, satisfied, waivers):
    """Steps two and three of the index, keyed on the supplied base_index."""
    # Step 2: cap tier keyed on base_index, never on the running total.
    cap = waiver_cap(base_index)
    # Step 3: credit, then clamp.
    raw_credit = round_half_up(
        sum((dec(ITEM_WEIGHTS[w["item_code"]]) * WAIVER_CREDIT_RATE for w in waivers), Decimal(0)),
        2,
    )
    credit = raw_credit if raw_credit < dec(cap) else dec(cap)
    completeness = dec(base_index) + credit
    if completeness > dec(100):
        completeness = dec(100)

    waived_codes = set(w["item_code"] for w in waivers)
    missing = [
        code for code in ITEM_CODES if not satisfied[code] and code not in waived_codes
    ]
    return {
        "base_index": base_index,
        "waiver_credit_points": db.num(credit),
        "completeness_index": db.num(completeness),
        "missing_items": missing,
        "waiver_count": len(waivers),
        "_satisfied": satisfied,
    }


def evidence_completeness(release, waivers):
    satisfied = evidence_items(release)
    # Step 1: base index, waivers excluded.
    base_index = sum(ITEM_WEIGHTS[code] for code in ITEM_CODES if satisfied[code])
    return waiver_totals(base_index, satisfied, waivers)
