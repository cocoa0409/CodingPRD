"""Domain logic: exclusion evaluation, cycle/vendor derived fields, top-box
scoring, star rating, VBP projection, initiative evaluation/progress, and
cascades. All rules trace to PRD section 3 and SCAFFOLD section 1.3.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import db
from util import pct2, round_half_up, parse_iso8601, clock_date


# ---------------------------------------------------------------------------
# Constants (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------

COMPOSITES = ("nurse_comm", "doctor_comm", "cleanliness", "overall_rating")
SCORE_FIELD = {
    "nurse_comm": "nurse_comm_score",
    "doctor_comm": "doctor_comm_score",
    "cleanliness": "cleanliness_score",
    "overall_rating": "overall_rating_score",
}
MODE_COEFF = {"MAIL": Decimal("0.0"), "PHONE": Decimal("-0.5")}
TOPBOX_RAW_MIN = 4
TOPBOX_ADJUSTED_THRESHOLD = Decimal("3.75")

MIN_COMPLETED_FOR_RATING = 25
RATE_CAP_THRESHOLD = Decimal("10.0")
RATE_CAP_MAX_STARS = 3

VBP_FLOOR_PCT = Decimal("50.0")
VBP_BENCHMARK_PCT = Decimal("95.0")
POINTS_PER_COMPOSITE = 10
MAX_TOTAL_POINTS = 40
MAX_ADJUSTMENT_PCT = Decimal("2.0")

SLA_HOURS = 48

CASE_LIVE_FOR_TARGET = ("SAMPLED", "IN_FIELD", "RESPONDED", "NONRESPONSE", "UNDELIVERABLE")
CASE_IN_DENOMINATOR = ("IN_FIELD", "RESPONDED", "NONRESPONSE")
RESPONSE_COUNTED = ("ACCEPTED", "INCLUDED")
RESPONSE_LIVE = ("ACCEPTED", "PENDING_REVIEW", "INCLUDED")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def active_vendor_for_program(program_id: str):
    for v in db.vendors.values():
        if v["program_id"] == program_id and v["status"] == "ACTIVE":
            return v
    return None


def live_response_for_case(case_id: str):
    for r in db.responses.values():
        if r["case_id"] == case_id and r["status"] in RESPONSE_LIVE:
            return r
    return None


def counted_responses(cycle_id: str) -> list:
    """Responses counting toward scoring: cycle's, in ACCEPTED or INCLUDED."""
    return [r for r in db.responses.values()
            if r["cycle_id"] == cycle_id and r["status"] in RESPONSE_COUNTED]


# ---------------------------------------------------------------------------
# Discharge exclusion evaluation (eligible_discharge_evaluation)
# ---------------------------------------------------------------------------

def evaluate_exclusion_reasons(d: dict) -> list:
    reasons = []
    if d["discharge_disposition"] == "EXPIRED":
        reasons.append("EXPIRED")
    if d["discharge_disposition"] == "SNF":
        reasons.append("SNF_DISCHARGE")
    if d["discharge_disposition"] == "PSYCH_FACILITY":
        reasons.append("PSYCH_DISCHARGE")
    if d["primary_dx_group"] == "PSYCHIATRIC":
        reasons.append("PSYCH_DX")
    if d["age_years"] < 18:
        reasons.append("MINOR")
    if d["address_country"] != "US":
        reasons.append("NON_US_ADDRESS")
    if d["no_publicity_flag"] is True:
        reasons.append("NO_PUBLICITY")
    if d["custody_status"] == "LAW_ENFORCEMENT":
        reasons.append("CUSTODY")
    if d["discharge_date"] <= d["admit_date"]:
        reasons.append("SHORT_STAY")
    return sorted(reasons)


def apply_discharge_evaluation(d: dict) -> None:
    reasons = evaluate_exclusion_reasons(d)
    d["exclusion_reasons"] = reasons
    d["status"] = "EXCLUDED" if reasons else "ELIGIBLE"


def cascade_discharge_excluded(d: dict) -> None:
    """Cascade hops B and C: linked SAMPLED/IN_FIELD cases -> EXCLUDED_POST_SAMPLE
    with compensating vendor credit; affected cycle counters recomputed."""
    for case in list(db.sample_cases.values()):
        if case["discharge_id"] != d["id"]:
            continue
        if case["status"] not in ("SAMPLED", "IN_FIELD"):
            continue
        case["status"] = "EXCLUDED_POST_SAMPLE"
        credited = False
        if case["billing_status"] == "CHARGED":
            case["billing_status"] = "CREDITED"
            credited = True
        db.touch(case)
        if credited:
            vendor = db.vendors.get(case["vendor_id"])
            if vendor is not None:
                recompute_vendor_budget(vendor)
                db.touch(vendor)
        cycle = db.cycles.get(case["cycle_id"])
        if cycle is not None:
            recompute_cycle_derived(cycle)
            db.touch(cycle)


# ---------------------------------------------------------------------------
# Vendor budget ledger (vendor_budget_reconciliation)
# ---------------------------------------------------------------------------

def recompute_vendor_budget(vendor: dict) -> None:
    charged = sum(
        c["postage_cost_cents"]
        for c in db.sample_cases.values()
        if c["vendor_id"] == vendor["id"] and c["billing_status"] == "CHARGED"
    )
    vendor["cycle_budget_remaining_cents"] = vendor["cycle_budget_cents"] - charged


# ---------------------------------------------------------------------------
# Cycle derived counters (response_rate, completed_responses_reconciliation)
# ---------------------------------------------------------------------------

def recompute_cycle_derived(cycle: dict) -> None:
    cases = [c for c in db.sample_cases.values() if c["cycle_id"] == cycle["id"]]
    denominator = sum(1 for c in cases if c["status"] in CASE_IN_DENOMINATOR)
    completed = 0
    for c in cases:
        if c["status"] != "RESPONDED":
            continue
        r = live_response_for_case(c["id"])
        if r is not None and r["status"] in RESPONSE_COUNTED:
            completed += 1
    cycle["eligible_denominator"] = denominator
    cycle["completed_responses"] = completed
    if denominator == 0:
        cycle["response_rate"] = None
    else:
        cycle["response_rate"] = pct2(Decimal(100) * Decimal(completed) / Decimal(denominator))
    cycle["publication_eligible"] = (
        completed >= 25
        and cycle["response_rate"] is not None
        and Decimal(str(cycle["response_rate"])) >= RATE_CAP_THRESHOLD
    )


# ---------------------------------------------------------------------------
# Top-box composite scores (top_box_composite_scores)
# ---------------------------------------------------------------------------

def topbox_pcts(responses: list) -> tuple[dict, dict]:
    """RAW and MODE_ADJUSTED top-box percentages over a response set."""
    n = len(responses)
    raw_pcts: dict = {}
    adj_pcts: dict = {}
    for comp in COMPOSITES:
        field = SCORE_FIELD[comp]
        if n == 0:
            raw_pcts[comp] = None
            adj_pcts[comp] = None
            continue
        raw_count = sum(1 for r in responses if r[field] == TOPBOX_RAW_MIN)
        adj_count = sum(
            1
            for r in responses
            if Decimal(r[field]) + MODE_COEFF[r["mode_used"]] >= TOPBOX_ADJUSTED_THRESHOLD
        )
        raw_pcts[comp] = pct2(Decimal(100) * Decimal(raw_count) / Decimal(n))
        adj_pcts[comp] = pct2(Decimal(100) * Decimal(adj_count) / Decimal(n))
    return raw_pcts, adj_pcts


def _subject_seq(subject_id: str, store: dict) -> int:
    subject = store.get(subject_id)
    return subject.get("_seq", 0) if subject else 0


def compute_scoring_snapshot(cycle: dict) -> None:
    """Freeze the analytical snapshot at begin-scoring (PRD 3.6)."""
    responses = counted_responses(cycle["id"])
    raw, adj = topbox_pcts(responses)
    cycle["scored_raw_composite_pcts"] = raw
    cycle["scored_adjusted_composite_pcts"] = adj

    by_unit: dict[str, list] = {}
    by_provider: dict[str, list] = {}
    for r in responses:
        case = db.sample_cases.get(r["case_id"])
        if case is None:
            continue
        by_unit.setdefault(case["unit_id"], []).append(r)
        by_provider.setdefault(case["provider_id"], []).append(r)

    unit_entries = []
    for unit_id, rs in by_unit.items():
        ur, ua = topbox_pcts(rs)
        unit_entries.append({
            "unit_id": unit_id,
            "completed_responses": len(rs),
            "raw_pcts": ur,
            "adjusted_pcts": ua,
        })
    unit_entries.sort(key=lambda e: _subject_seq(e["unit_id"], db.units))
    cycle["scored_unit_breakdown"] = unit_entries

    provider_entries = []
    for provider_id, rs in by_provider.items():
        pr, pa = topbox_pcts(rs)
        provider_entries.append({
            "provider_id": provider_id,
            "completed_responses": len(rs),
            "raw_pcts": pr,
            "adjusted_pcts": pa,
        })
    provider_entries.sort(key=lambda e: _subject_seq(e["provider_id"], db.providers))
    cycle["scored_provider_breakdown"] = provider_entries

    cycle["scored_response_rate"] = cycle["response_rate"]
    cycle["scored_completed_responses"] = cycle["completed_responses"]


# ---------------------------------------------------------------------------
# Star rating (star_rating) — computed from the scored snapshot
# ---------------------------------------------------------------------------

def star_rating_from_snapshot(cycle: dict) -> tuple:
    """Return (stars, rating_status, capped) from the scored_* snapshot."""
    completed = cycle.get("scored_completed_responses")
    if completed is None or completed < MIN_COMPLETED_FOR_RATING:
        return None, "NOT_RATED", False
    adjusted = cycle.get("scored_adjusted_composite_pcts") or {}
    p_raw = adjusted.get("overall_rating")
    p = Decimal(str(p_raw)) if p_raw is not None else Decimal("0")
    if p >= Decimal("90.0"):
        stars = 5
    elif p >= Decimal("80.0"):
        stars = 4
    elif p >= Decimal("70.0"):
        stars = 3
    elif p >= Decimal("60.0"):
        stars = 2
    else:
        stars = 1
    capped = False
    rate = cycle.get("scored_response_rate")
    if rate is None or Decimal(str(rate)) < RATE_CAP_THRESHOLD:
        stars = min(stars, RATE_CAP_MAX_STARS)
        capped = True
    return stars, "RATED", capped


# ---------------------------------------------------------------------------
# VBP projection (vbp_payment_adjustment) — per-line rounding order pinned
# ---------------------------------------------------------------------------

def vbp_projection(cycle: dict, overrides: dict) -> dict:
    adjusted = cycle.get("scored_adjusted_composite_pcts") or {}
    composite_points: dict = {}
    for comp in COMPOSITES:
        if comp + "_pct" in overrides and overrides[comp + "_pct"] is not None:
            pct = Decimal(str(overrides[comp + "_pct"]))
        else:
            snap = adjusted.get(comp)
            pct = Decimal(str(snap)) if snap is not None else Decimal("0")
        raw_points = (pct - VBP_FLOOR_PCT) / (VBP_BENCHMARK_PCT - VBP_FLOOR_PCT) * POINTS_PER_COMPOSITE
        points = int(round_half_up(raw_points, 0))
        points = max(0, min(POINTS_PER_COMPOSITE, points))
        composite_points[comp] = points
    total_points = sum(composite_points.values())
    adjustment = pct2(Decimal(total_points) / Decimal(MAX_TOTAL_POINTS) * MAX_ADJUSTMENT_PCT)
    return {
        "cycle_id": cycle["id"],
        "composite_points": composite_points,
        "total_points": total_points,
        "vbp_adjustment_pct": adjustment,
    }


# ---------------------------------------------------------------------------
# Initiative helpers (initiative_evaluation, initiative_progress)
# ---------------------------------------------------------------------------

DOMAIN_TO_COMPOSITE = {d: d.lower() for d in
                       ("NURSE_COMM", "DOCTOR_COMM", "CLEANLINESS", "OVERALL_RATING")}


def unit_adjusted_pct(cycle: dict, unit_id: str, domain: str) -> float:
    """Unit's adjusted top-box pct for domain in a cycle's scored breakdown.
    Absent unit or zero completed responses -> 0.0 (PRD 3.8)."""
    breakdown = cycle.get("scored_unit_breakdown") or []
    comp = DOMAIN_TO_COMPOSITE[domain]
    for entry in breakdown:
        if entry["unit_id"] == unit_id:
            if entry["completed_responses"] == 0:
                return 0.0
            value = entry["adjusted_pcts"].get(comp)
            return 0.0 if value is None else value
    return 0.0


def initiative_progress(ini: dict) -> tuple:
    """Live (progress_pinned, progress_rolling); null until evaluation cycle
    is PUBLISHED (progress_rolling also null without a published prior cycle)."""
    pinned = None
    rolling = None
    eval_cycle = db.cycles.get(ini["evaluation_cycle_id"])
    if eval_cycle is not None and eval_cycle["status"] == "PUBLISHED":
        current = Decimal(str(unit_adjusted_pct(eval_cycle, ini["unit_id"], ini["domain"])))
        if ini.get("baseline_score") is not None:
            pinned = pct2(current - Decimal(str(ini["baseline_score"])))
        priors = [
            c for c in db.cycles.values()
            if c["program_id"] == ini["program_id"]
            and c["status"] == "PUBLISHED"
            and c["cycle_index"] < eval_cycle["cycle_index"]
        ]
        priors.sort(key=lambda c: (c["cycle_index"], c.get("created_at", ""), c.get("_seq", 0)),
                    reverse=True)
        priors = priors[:2]
        if priors:
            values = [Decimal(str(unit_adjusted_pct(c, ini["unit_id"], ini["domain"])))
                      for c in priors]
            rolling_baseline = round_half_up(sum(values) / Decimal(len(values)), 2)
            rolling = pct2(current - rolling_baseline)
    return pinned, rolling


def evaluate_initiatives_at_publish(cycle: dict) -> None:
    """Publish cascade hops B, C, D (PRD 3.6)."""
    for ini in sorted(
        (i for i in db.initiatives.values()
         if i["evaluation_cycle_id"] == cycle["id"] and i["status"] == "ACTIVE"),
        key=lambda i: i.get("_seq", 0),
    ):
        current = Decimal(str(unit_adjusted_pct(cycle, ini["unit_id"], ini["domain"])))
        target = Decimal(str(ini["target_score"]))
        if current >= target:
            ini["status"] = "TARGET_MET"
            ini["achieved_at"] = db.clock_now()
        else:
            ini["status"] = "TARGET_MISSED"
            # Hop C: escalate OPEN tickets on the same unit + domain
            for tkt in sorted(
                (t for t in db.tickets.values()
                 if t["unit_id"] == ini["unit_id"]
                 and t["domain"] == ini["domain"]
                 and t["status"] == "OPEN"),
                key=lambda t: t.get("_seq", 0),
            ):
                tkt["status"] = "ESCALATED"
                db.touch(tkt)
                # Hop D: flag the routed response
                resp = db.responses.get(tkt["response_id"])
                if resp is not None and not resp["has_escalated_recovery"]:
                    resp["has_escalated_recovery"] = True
                    db.touch(resp)
        db.touch(ini)


# ---------------------------------------------------------------------------
# Initiative window guards (activate / replan)
# ---------------------------------------------------------------------------

def check_initiative_window(ini: dict, evaluation_cycle_id: str,
                            baseline_cycle_id: str, self_id: str | None) -> None:
    """Half-open (baseline_index, evaluation_index] overlap check against same
    (unit_id, domain) initiatives in ACTIVE / UNDER_EVALUATION / TARGET_MISSED.
    Adjacency (a.evaluation_index == b.baseline_index) is permitted."""
    from errors import raise_err, ERR_INITIATIVE_WINDOW_OVERLAP

    eval_cycle = db.cycles[evaluation_cycle_id]
    base_cycle = db.cycles[baseline_cycle_id]
    lo = base_cycle["cycle_index"]          # exclusive
    hi = eval_cycle["cycle_index"]          # inclusive
    for peer in db.initiatives.values():
        if self_id is not None and peer["id"] == self_id:
            continue
        if peer["unit_id"] != ini["unit_id"] or peer["domain"] != ini["domain"]:
            continue
        if peer["status"] not in ("ACTIVE", "UNDER_EVALUATION", "TARGET_MISSED"):
            continue
        peer_base = db.cycles.get(peer["baseline_cycle_id"])
        peer_eval = db.cycles.get(peer["evaluation_cycle_id"])
        if peer_base is None or peer_eval is None:
            continue
        p_lo = peer_base["cycle_index"]
        p_hi = peer_eval["cycle_index"]
        # Half-open interval intersection: (lo, hi] vs (p_lo, p_hi] share a
        # point iff max(lo, p_lo) < min(hi, p_hi); equality is mere adjacency.
        if max(lo, p_lo) < min(hi, p_hi):
            raise_err(
                ERR_INITIATIVE_WINDOW_OVERLAP,
                "Initiative window overlaps an existing initiative for this unit and domain",
            )


def service_recovery_sla(created_at: str, acknowledged_at: str) -> bool:
    """48h SLA, boundary inclusive (PRD 3.9)."""
    delta = parse_iso8601(acknowledged_at, "acknowledged_at") - parse_iso8601(created_at, "created_at")
    return delta <= timedelta(hours=SLA_HOURS)
