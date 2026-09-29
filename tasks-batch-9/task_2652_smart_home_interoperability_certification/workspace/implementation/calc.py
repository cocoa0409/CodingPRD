"""Calculation engine (PRD 3). All money and score arithmetic uses Decimal."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import enums as E
import queries as Q
from db import now, store


def rhu(value, places):
    """ROUND_HALF_UP to `places` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def ratio4(numerator, denominator, vacuous=Decimal("0.0000")):
    if denominator == 0:
        return rhu(vacuous, 4)
    return rhu(Decimal(numerator) / Decimal(denominator), 4)


# ------------------------------------------------------------ certification fee

def certification_fee_cents(device_type, declared_code_count, baseline_level, tier, review_track):
    subtotal = (
        Decimal(E.BASE_FEE_CENTS[device_type])
        + Decimal(E.PER_FEATURE_FEE_CENTS) * Decimal(declared_code_count)
        + Decimal(E.BASELINE_SURCHARGE_CENTS[baseline_level])
    )
    discounted = rhu(subtotal * (Decimal("1") - E.TIER_DISCOUNT_RATE[tier]), 0)
    total = rhu(discounted * E.TRACK_MULTIPLIER[review_track], 0)
    return int(total)


# -------------------------------------------------------------- credit ledger

def member_escrow_cents(member_id):
    return sum(s["fee_escrowed_cents"] for s in Q.submissions_for_member(member_id))


def credit_ledger(member, variant):
    escrowed = member_escrow_cents(member["id"])
    purchased = member["credits_purchased_cents"]
    consumed = member["credits_consumed_cents"]
    if variant == "COMMITTED":
        balance = purchased - consumed
    else:
        balance = purchased - consumed - escrowed
    return {
        "member_id": member["id"],
        "variant": variant,
        "credits_purchased_cents": purchased,
        "credits_consumed_cents": consumed,
        "escrowed_credit_cents": escrowed,
        "balance_cents": balance,
    }


# --------------------------------------------------------------- plan closure

def plan_closure(specification_id, device_type, declared_feature_codes):
    candidates = Q.feature_sets_for(specification_id, device_type)
    by_id = {fs["id"]: fs for fs in candidates}
    declared = set(declared_feature_codes or [])

    working = {}
    for fs in candidates:
        if fs["obligation"] == "MANDATORY":
            working[fs["id"]] = fs
        elif fs["obligation"] == "OPTIONAL" and fs["feature_code"] in declared:
            working[fs["id"]] = fs

    for _ in range(E.MAX_PROPAGATION_ROUNDS):
        grew = False
        # Rule 1: dependency closure (transitive).
        for fs in list(working.values()):
            target_id = fs.get("depends_on_feature_set_id")
            while target_id and target_id in by_id and target_id not in working:
                target = by_id[target_id]
                working[target_id] = target
                grew = True
                target_id = target.get("depends_on_feature_set_id")
        # Rule 2: conditional activation.
        for fs in candidates:
            if fs["id"] in working:
                continue
            if fs["obligation"] == "CONDITIONAL" and fs.get("depends_on_feature_set_id") in working:
                working[fs["id"]] = fs
                grew = True
        if not grew:
            break

    included = sorted(working.values(), key=lambda fs: fs["feature_code"])
    required = sum(fs["test_case_count"] for fs in included)
    mandatory = sum(fs["test_case_count"] for fs in included
                    if fs["obligation"] in ("MANDATORY", "CONDITIONAL"))
    optional = sum(fs["test_case_count"] for fs in included if fs["obligation"] == "OPTIONAL")
    return [fs["id"] for fs in included], required, mandatory, optional


# ------------------------------------------------------------- readiness score

READINESS_COUNTED_STATES = {
    "PROVISIONAL": ("IN_PROGRESS", "COMPLETE"),
    "FINAL": ("COMPLETE",),
}
READINESS_PASS_SET = {
    "PROVISIONAL": ("PASS", "WAIVED", "BLOCKED"),
    "FINAL": ("PASS", "WAIVED"),
}


def _effective_outcomes(sessions):
    """Latest result line per feature_set_id across the counted sessions."""
    entries = []
    for session in sessions:
        for index, line in enumerate(session["result_lines"]):
            entries.append((line["recorded_at"], session["created_at"], session["_seq"],
                            index, line))
    entries.sort(key=lambda e: (e[0], e[1], e[2], e[3]))
    latest = {}
    for _, _, _, _, line in entries:
        latest[line["feature_set_id"]] = line["outcome"]
    return latest


def readiness(submission, variant, credits_override=None):
    plan = Q.live_plan(submission["id"])
    counted_states = READINESS_COUNTED_STATES[variant]
    pass_set = READINESS_PASS_SET[variant]

    mandatory_cases = 0
    optional_cases = 0
    mandatory_passed = 0
    optional_passed = 0
    counted_sessions = []
    if plan is not None:
        counted_sessions = [s for s in Q.sessions_for_plan(plan["id"])
                            if s["state"] in counted_states]
        outcomes = _effective_outcomes(counted_sessions)
        for fs_id in plan["included_feature_set_ids"]:
            fs = store.feature_sets.get(fs_id)
            if fs is None:
                continue
            cases = fs["test_case_count"]
            passed = outcomes.get(fs_id) in pass_set
            if fs["obligation"] in ("MANDATORY", "CONDITIONAL"):
                mandatory_cases += cases
                if passed:
                    mandatory_passed += cases
            elif fs["obligation"] == "OPTIONAL":
                optional_cases += cases
                if passed:
                    optional_passed += cases

    mand_ratio = ratio4(mandatory_passed, mandatory_cases, Decimal("0.0000"))
    opt_ratio = ratio4(optional_passed, optional_cases, Decimal("1.0000"))

    credits = (submission["plugfest_credit_count"] if credits_override is None
               else credits_override)
    capped = Decimal(min(credits, int(E.INTEROP_CREDIT_TARGET)))
    interop_ratio = rhu(capped / E.INTEROP_CREDIT_TARGET, 4)

    counted_count = len(counted_sessions)
    late_count = sum(1 for s in counted_sessions if s["completed_late"])
    late_ratio = ratio4(late_count, counted_count, Decimal("0.0000"))
    if variant == "PROVISIONAL":
        timeliness_ratio = Decimal("1.0000")
    else:
        timeliness_ratio = rhu(Decimal("1.0000") - late_ratio, 4)

    score = (
        rhu(E.WEIGHT_MANDATORY * mand_ratio, 2)
        + rhu(E.WEIGHT_OPTIONAL * opt_ratio, 2)
        + rhu(E.WEIGHT_INTEROP * interop_ratio, 2)
        + rhu(E.WEIGHT_TIMELINESS * timeliness_ratio, 2)
    )
    return {
        "submission_id": submission["id"],
        "variant": variant,
        "mandatory_case_count": mandatory_cases,
        "mandatory_passed_cases": mandatory_passed,
        "optional_case_count": optional_cases,
        "optional_passed_cases": optional_passed,
        "plugfest_credit_count": credits,
        "counted_session_count": counted_count,
        "late_session_count": late_count,
        "score": score,
    }


# ------------------------------------------------------------ competency score

def competency_sessions(laboratory_id, variant):
    rows = [s for s in Q.sessions_for_lab(laboratory_id) if s["state"] == "COMPLETE"]
    if variant == "ROLLING_90D":
        cutoff = now() - timedelta(seconds=E.ROLLING_WINDOW_DAYS * 86400)
        rows = [s for s in rows if s["completed_at"] is not None and s["completed_at"] >= cutoff]
    return rows


def competency(laboratory, variant):
    sessions = competency_sessions(laboratory["id"], variant)
    counted = len(sessions)
    on_time = sum(1 for s in sessions if not s["completed_late"])
    lines = sum(len(s["result_lines"]) for s in sessions)
    disputed = sum(s["disputed_line_count"] for s in sessions)

    on_time_ratio = ratio4(on_time, counted, Decimal("0.0000"))
    dispute_free_ratio = ratio4(lines - disputed, lines, Decimal("1.0000"))
    score = (
        rhu(E.WEIGHT_PUNCTUALITY * on_time_ratio, 2)
        + rhu(E.WEIGHT_DISPUTE_FREE * dispute_free_ratio, 2)
    )
    return {
        "laboratory_id": laboratory["id"],
        "variant": variant,
        "counted_session_count": counted,
        "counted_line_count": lines,
        "disputed_line_count": disputed,
        "on_time_ratio": on_time_ratio,
        "dispute_free_ratio": dispute_free_ratio,
        "competency_score": score,
    }


# ------------------------------------------------------------------- penalties

def penalty(claimed_impact_units, category):
    units = int(claimed_impact_units)
    first = min(units, 100)
    second = min(max(units - 100, 0), 900)
    third = max(units - 1000, 0)
    subtotal = first * 500 + second * 300 + third * 150
    surcharge = int(rhu(Decimal(subtotal) * E.PENALTY_SURCHARGE_RATE[category], 0))
    total = min(subtotal + surcharge, E.PENALTY_TOTAL_CAP_CENTS)
    return subtotal, surcharge, total


# --------------------------------------------------------------- bench minutes

def session_minutes(window_start, window_end):
    seconds = (window_end - window_start).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 60)
