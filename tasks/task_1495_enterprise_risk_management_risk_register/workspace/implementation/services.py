"""Business logic: scoring, breach evaluation, cascades, aggregation, sweeps,
and entity serializers."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from db import store, clock_now, wall_now, new_id, next_seq
from util import band_of, fmt_dt

# Risk statuses included in board-report aggregation and KRI red cascades.
INCLUDED_STATUSES = ("ASSESSED", "TREATMENT", "MONITORING", "REASSESSMENT")
# Plan statuses that hold a budget reservation.
RESERVED_PLAN_STATUSES = ("APPROVED", "IN_PROGRESS", "OVERDUE")
# Plan statuses that block monitor/close.
ACTIVE_PLAN_STATUSES = ("PROPOSED", "APPROVED", "IN_PROGRESS", "OVERDUE")
# Breach statuses that block monitor/close and dedupe new breaches.
OPEN_BREACH_STATUSES = ("OPEN", "ACKNOWLEDGED")
LIVE_BREACH_STATUSES = ("OPEN", "ACKNOWLEDGED", "ACCEPTED")


# ---------------------------------------------------------------------------
# Entity bookkeeping
# ---------------------------------------------------------------------------

def new_entity():
    now = wall_now()
    return {"id": new_id(), "created_at": now, "updated_at": now,
            "version": 1, "_seq": next_seq()}


def new_event():
    """Append-only records (RiskAssessment, KRIObservation): id + created_at only."""
    return {"id": new_id(), "created_at": wall_now(), "_seq": next_seq()}


def touch(e):
    e["updated_at"] = wall_now()
    e["version"] += 1


# ---------------------------------------------------------------------------
# Residual scoring (PRD 3.3) and appetite breach evaluation (PRD 3.4)
# ---------------------------------------------------------------------------

def compute_residual(risk):
    """Diminishing-returns control discount. Returns (score, band) or (None, None)."""
    inh = risk["inherent_score"]
    if inh is None:
        return None, None
    contribs = []
    for m in store["mappings"].values():
        if m["risk_id"] != risk["id"] or m["status"] != "ACTIVE":
            continue
        c = store["controls"].get(m["control_id"])
        if c is None or c["status"] not in ("ACTIVE", "UNDER_REVIEW"):
            continue
        contribs.append((c["effectiveness_pct"] * m["coverage_weight"], m["_seq"]))
    # descending contribution; ties by mapping creation time, earliest first
    contribs.sort(key=lambda t: (-t[0], t[1]))
    acc = Decimal("0")
    for v, _ in contribs:
        acc = acc + v * (Decimal("1") - acc)
    discount = min(Decimal("0.90"), acc)
    raw = Decimal(inh) * (Decimal("1") - discount)
    score = int(raw.quantize(Decimal("1"), rounding=ROUND_CEILING))
    if score < 1:
        score = 1
    return score, band_of(score)


def recompute_residual(risk):
    score, band = compute_residual(risk)
    risk["residual_score"] = score
    risk["residual_band"] = band


def effective_appetite(category_id):
    """The APPROVED appetite statement whose half-open window contains the clock."""
    now = clock_now()
    for a in store["appetite_statements"].values():
        if (a["category_id"] == category_id and a["status"] == "APPROVED"
                and a["effective_from"] <= now < a["effective_to"]):
            return a
    return None


def evaluate_breach(risk):
    """Runs after every residual recompute. Returns True when a breach opened."""
    if risk["residual_score"] is None:
        return False
    stmt = effective_appetite(risk["category_id"])
    if stmt is None:
        return False
    if risk["residual_score"] < stmt["tolerance_score"]:  # equality breaches
        return False
    for b in store["breaches"].values():
        if b["risk_id"] == risk["id"] and b["status"] in LIVE_BREACH_STATUSES:
            return False
    b = new_entity()
    b.update({
        "risk_id": risk["id"],
        "appetite_statement_id": stmt["id"],
        "residual_at_breach": risk["residual_score"],
        "status": "OPEN",
        "rationale": None,
        "review_by": None,
    })
    store["breaches"][b["id"]] = b
    return True


def cascade_recompute_risk(risk):
    """Mapping/control cascade: only when inherent score is present."""
    if risk["inherent_score"] is None:
        return
    recompute_residual(risk)
    evaluate_breach(risk)
    touch(risk)


# ---------------------------------------------------------------------------
# Treatment plan progress rollup (PRD 3.5)
# ---------------------------------------------------------------------------

def rollup_progress(plan):
    acts = [a for a in store["actions"].values() if a["plan_id"] == plan["id"]]
    total = len(acts)
    done = sum(1 for a in acts if a["status"] == "DONE")
    if total == 0:
        pct = Decimal("0.00")
    else:
        pct = (Decimal(100 * done) / Decimal(total)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
    if pct != plan["progress_pct"]:
        plan["progress_pct"] = pct
        touch(plan)


# ---------------------------------------------------------------------------
# KRI breach evaluation and alert cascade (PRD 3.6)
# ---------------------------------------------------------------------------

def eval_kri_breach(direction, amber, red, value):
    """Strict comparisons; equality with a threshold is never a breach."""
    if direction == "ABOVE":
        if value > red:
            return "RED_BREACH"
        if value > amber:
            return "AMBER_BREACH"
        return "NORMAL"
    if value < red:
        return "RED_BREACH"
    if value < amber:
        return "AMBER_BREACH"
    return "NORMAL"


def kri_cascade(kri, result):
    """RED raises alerts + ratchets plan priority; NORMAL clears alerts when no
    other ACTIVE indicator in the category remains red. AMBER changes nothing."""
    if result == "RED_BREACH":
        for r in store["risks"].values():
            if r["category_id"] == kri["category_id"] and r["status"] in INCLUDED_STATUSES:
                r["kri_alert"] = True
                touch(r)
                for p in store["plans"].values():
                    if p["risk_id"] == r["id"] and p["status"] in RESERVED_PLAN_STATUSES:
                        p["priority"] = "URGENT"
                        touch(p)
    elif result == "NORMAL":
        other_red = any(
            k for k in store["kris"].values()
            if k["id"] != kri["id"] and k["category_id"] == kri["category_id"]
            and k["status"] == "ACTIVE" and k["current_breach_status"] == "RED_BREACH")
        if not other_red:
            for r in store["risks"].values():
                if (r["category_id"] == kri["category_id"]
                        and r["status"] in INCLUDED_STATUSES and r["kri_alert"]):
                    r["kri_alert"] = False
                    touch(r)


# ---------------------------------------------------------------------------
# Logical clock sweeps and lazy evaluations (PRD 2.4)
# ---------------------------------------------------------------------------

def sweep_clock():
    now = clock_now()
    for p in store["plans"].values():
        if p["status"] == "IN_PROGRESS" and now > p["due_date"]:
            p["status"] = "OVERDUE"
            touch(p)
    for b in store["breaches"].values():
        if b["status"] == "ACCEPTED" and b["review_by"] is not None and now >= b["review_by"]:
            b["status"] = "OPEN"
            touch(b)


def lazy_plan_sweep(plan):
    if plan["status"] == "IN_PROGRESS" and clock_now() > plan["due_date"]:
        plan["status"] = "OVERDUE"
        touch(plan)


def lazy_breach_sweep(breach):
    if (breach["status"] == "ACCEPTED" and breach["review_by"] is not None
            and clock_now() >= breach["review_by"]):
        breach["status"] = "OPEN"
        touch(breach)


# ---------------------------------------------------------------------------
# Board report aggregation (PRD 3.8)
# ---------------------------------------------------------------------------

def aggregate_report(variant):
    included = [r for r in store["risks"].values() if r["status"] in INCLUDED_STATUSES]

    def metric(r):
        if variant == "PROVISIONAL":
            return r["inherent_score"]
        return r["residual_score"] if r["residual_score"] is not None else r["inherent_score"]

    by_cat = {}
    band_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for r in included:
        m = metric(r)
        by_cat.setdefault(r["category_id"], []).append(m)
        band_counts[band_of(m)] += 1

    total = Decimal("0")
    entries = []
    for cid, scores in by_cat.items():
        cat = store["categories"][cid]
        # round per category first, then sum the rounded values
        heat = (Decimal(sum(scores)) * cat["weight_factor"]).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        total += heat
        entries.append({"category_id": cid, "risk_count": len(scores),
                        "_heat": heat, "_cat_seq": cat["_seq"]})
    entries.sort(key=lambda b: (-b["_heat"], b["_cat_seq"]))
    breakdown = [{"category_id": e["category_id"], "risk_count": e["risk_count"],
                  "heat_score": float(e["_heat"])} for e in entries]
    heat_total = float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return heat_total, breakdown, band_counts


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def serialize_category(c):
    tol = None
    stmt = effective_appetite(c["id"])
    if stmt is not None:
        tol = stmt["tolerance_score"]
    return {
        "id": c["id"],
        "name": c["name"],
        "parent_category_id": c["parent_category_id"],
        "weight_factor": float(c["weight_factor"]),
        "current_tolerance_score": tol,
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def serialize_risk(r):
    return {
        "id": r["id"],
        "category_id": r["category_id"],
        "source_emerging_risk_id": r["source_emerging_risk_id"],
        "title": r["title"],
        "description": r["description"],
        "owner_user_id": r["owner_user_id"],
        "treatment_budget_cents": r["treatment_budget_cents"],
        "status": r["status"],
        "likelihood": r["likelihood"],
        "impact": r["impact"],
        "inherent_score": r["inherent_score"],
        "inherent_band": r["inherent_band"],
        "residual_score": r["residual_score"],
        "residual_band": r["residual_band"],
        "reserved_treatment_cents": r["reserved_treatment_cents"],
        "available_treatment_cents":
            r["treatment_budget_cents"] - r["reserved_treatment_cents"],
        "kri_alert": r["kri_alert"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def serialize_assessment(a):
    return {
        "id": a["id"],
        "risk_id": a["risk_id"],
        "kind": a["kind"],
        "likelihood": a["likelihood"],
        "impact": a["impact"],
        "notes": a["notes"],
        "inherent_score": a["inherent_score"],
        "residual_score": a["residual_score"],
        "breach_created": a["breach_created"],
        "created_at": fmt_dt(a["created_at"]),
    }


def mapped_active_count(control_id):
    return sum(1 for m in store["mappings"].values()
               if m["control_id"] == control_id and m["status"] == "ACTIVE")


def serialize_control(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "description": c["description"],
        "effectiveness_pct": float(c["effectiveness_pct"]),
        "max_mapped_risks": c["max_mapped_risks"],
        "mapped_active_count": mapped_active_count(c["id"]),
        "status": c["status"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def serialize_mapping(m):
    return {
        "id": m["id"],
        "risk_id": m["risk_id"],
        "control_id": m["control_id"],
        "coverage_weight": float(m["coverage_weight"]),
        "status": m["status"],
        "created_at": fmt_dt(m["created_at"]),
        "updated_at": fmt_dt(m["updated_at"]),
        "version": m["version"],
    }


def serialize_appetite(a):
    return {
        "id": a["id"],
        "category_id": a["category_id"],
        "tolerance_score": a["tolerance_score"],
        "acceptance_cap_score": a["acceptance_cap_score"],
        "effective_from": fmt_dt(a["effective_from"]),
        "effective_to": fmt_dt(a["effective_to"]),
        "status": a["status"],
        "created_by": a["created_by"],
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def serialize_breach(b):
    return {
        "id": b["id"],
        "risk_id": b["risk_id"],
        "appetite_statement_id": b["appetite_statement_id"],
        "residual_at_breach": b["residual_at_breach"],
        "status": b["status"],
        "rationale": b["rationale"],
        "review_by": fmt_dt(b["review_by"]) if b["review_by"] is not None else None,
        "created_at": fmt_dt(b["created_at"]),
        "updated_at": fmt_dt(b["updated_at"]),
        "version": b["version"],
    }


def serialize_plan(p):
    return {
        "id": p["id"],
        "risk_id": p["risk_id"],
        "title": p["title"],
        "budget_cents": p["budget_cents"],
        "due_date": fmt_dt(p["due_date"]),
        "owner_user_id": p["owner_user_id"],
        "proposer_user_id": p["proposer_user_id"],
        "status": p["status"],
        "priority": p["priority"],
        "extension_count": p["extension_count"],
        "progress_pct": float(p["progress_pct"]),
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def serialize_action(a):
    return {
        "id": a["id"],
        "plan_id": a["plan_id"],
        "title": a["title"],
        "status": a["status"],
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def serialize_kri(k):
    return {
        "id": k["id"],
        "category_id": k["category_id"],
        "name": k["name"],
        "direction": k["direction"],
        "amber_threshold": float(k["amber_threshold"]),
        "red_threshold": float(k["red_threshold"]),
        "min_observation_interval_days": k["min_observation_interval_days"],
        "unit": k["unit"],
        "status": k["status"],
        "current_breach_status": k["current_breach_status"],
        "last_observation_at": (fmt_dt(k["last_observation_at"])
                                if k["last_observation_at"] is not None else None),
        "created_at": fmt_dt(k["created_at"]),
        "updated_at": fmt_dt(k["updated_at"]),
        "version": k["version"],
    }


def serialize_observation(o):
    return {
        "id": o["id"],
        "kri_id": o["kri_id"],
        "observed_value": float(o["observed_value"]),
        "observed_at": fmt_dt(o["observed_at"]),
        "resulting_breach_status": o["resulting_breach_status"],
        "created_at": fmt_dt(o["created_at"]),
    }


def serialize_report(rep):
    return {
        "id": rep["id"],
        "period_start": fmt_dt(rep["period_start"]),
        "period_end": fmt_dt(rep["period_end"]),
        "variant": rep["variant"],
        "status": rep["status"],
        "heat_score_total": rep["heat_score_total"],
        "category_breakdown": rep["category_breakdown"],
        "band_counts": rep["band_counts"],
        "created_at": fmt_dt(rep["created_at"]),
        "updated_at": fmt_dt(rep["updated_at"]),
        "version": rep["version"],
    }


def serialize_emerging(e):
    return {
        "id": e["id"],
        "category_id": e["category_id"],
        "title": e["title"],
        "description": e["description"],
        "scenario_severity": e["scenario_severity"],
        "scenario_probability": e["scenario_probability"],
        "stress_factor": float(e["stress_factor"]),
        "scenario_score": e["scenario_score"],
        "status": e["status"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def sorted_by_creation(items):
    return sorted(items, key=lambda e: e["_seq"])
