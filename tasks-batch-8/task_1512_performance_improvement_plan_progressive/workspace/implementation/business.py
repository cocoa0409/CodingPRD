"""Business logic: attainment / risk / consistency calculations, the logical
clock sweeps, and plan-closure side effects."""

from decimal import Decimal

from core import (
    db, parse_dt, fmt_like, dec, round4, days, touch, clock_of,
    new_id, new_append_record, now_iso,
)

PIP_INFLIGHT = {"ISSUED", "ACTIVE", "EXTENDED"}
PIP_NONTERMINAL = {"DRAFT", "ISSUED", "ACTIVE", "EXTENDED"}
PIP_CLOSED_OUTCOME = {"CLOSED_SUCCESS", "CLOSED_FAILED", "CLOSED_TERMINATED"}

RISK_WEIGHTS = {
    "PROTECTED_CLASS": 20,
    "RECENT_LEAVE": 15,
    "WHISTLEBLOWER_HISTORY": 30,
    "PRIOR_COMPLAINT": 10,
    "RETALIATION_WINDOW": 25,
    "DOCUMENTATION_GAP": 0,
}

REBUTTAL_WINDOW_DAYS = 5


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def employee_of_pip(pip):
    return db.employees.get(pip["employee_id"])


def ou_of_employee(emp):
    return db.org_units.get(emp["hr_org_unit_id"])


def ou_of_pip(pip):
    emp = employee_of_pip(pip)
    return db.org_units.get(emp["hr_org_unit_id"]) if emp else None


def pips_of_ou(ou_id):
    out = []
    for p in db.pips.values():
        emp = db.employees.get(p["employee_id"])
        if emp and emp["hr_org_unit_id"] == ou_id:
            out.append(p)
    return out


def goals_of_pip(pip_id):
    gs = [g for g in db.goals.values() if g["pip_id"] == pip_id]
    gs.sort(key=lambda g: g["_seq"])
    return gs


def checkins_of_pip(pip_id):
    cs = [c for c in db.checkins.values() if c["pip_id"] == pip_id]
    cs.sort(key=lambda c: c["sequence_index"])
    return cs


def evidence_of_checkin(check_in_id):
    return [e for e in db.evidence.values() if e["check_in_id"] == check_in_id]


def evidence_of_goal(pip_goal_id):
    return [e for e in db.evidence.values() if e["pip_goal_id"] == pip_goal_id]


def decisions_of_pip(pip_id):
    ds = [d for d in db.decisions.values() if d["pip_id"] == pip_id]
    ds.sort(key=lambda d: d["_seq"])
    return ds


def rebuttals_of_pip(pip_id):
    return [r for r in db.rebuttals.values() if r["pip_id"] == pip_id]


def latest_approved_decision(pip_id):
    """The APPROVED outcome decision that currently governs the plan."""
    cands = [d for d in db.decisions.values()
             if d["pip_id"] == pip_id and d["status"] == "APPROVED"
             and d.get("decided_at")]
    if not cands:
        return None
    cands.sort(key=lambda d: (parse_dt(d["decided_at"]), d["created_at"], d["_seq"]))
    return cands[-1]


# ---------------------------------------------------------------------------
# Attainment calculations (PRD §2.9 / §3.4, scaffold pip_attainment_ratio)
# ---------------------------------------------------------------------------

def goal_status_for(current_value, target_value):
    pct = dec(current_value) / dec(target_value)
    if pct >= Decimal("1"):
        return "MET"
    if pct >= Decimal("0.7"):
        return "ON_TRACK"
    if pct >= Decimal("0.4"):
        return "AT_RISK"
    return "NOT_MET"


def _goal_has_admissible_evidence(goal):
    return any(e["admissibility"] == "ADMISSIBLE" for e in evidence_of_goal(goal["id"]))


def attainment_ratio(pip, variant):
    """Weighted attainment, rounded half-up to 4 dp (once, at the end)."""
    goals = goals_of_pip(pip["id"])
    if not goals:
        return 1.0
    if all(g["goal_status"] == "WAIVED" for g in goals):
        return 1.0
    denom = sum(g["weight"] for g in goals if g["goal_status"] != "WAIVED")
    missed = sum(1 for c in db.checkins.values()
                 if c["pip_id"] == pip["id"] and c["status"] == "MISSED")
    total = Decimal("0")
    for g in goals:
        if g["goal_status"] == "WAIVED":
            att = Decimal("1")
        else:
            if variant == "PROVISIONAL" and not _goal_has_admissible_evidence(g):
                att = Decimal("0")
            else:
                att = dec(g["current_value"]) / dec(g["target_value"])
                if att < 0:
                    att = Decimal("0")
                if att > 1:
                    att = Decimal("1")
                if variant == "FINAL" and missed:
                    att = att * (Decimal("0.5") ** missed)
        total += att * Decimal(g["weight"])
    ratio = total / Decimal(denom)
    if ratio > 1:
        ratio = Decimal("1")
    return round4(ratio)


def recompute_provisional(pip, bump=True):
    new_val = attainment_ratio(pip, "PROVISIONAL")
    if new_val != pip.get("provisional_attainment_ratio"):
        pip["provisional_attainment_ratio"] = new_val
        if bump:
            touch(pip)


# ---------------------------------------------------------------------------
# Legal risk score (scaffold legal_risk_score)
# ---------------------------------------------------------------------------

def legal_risk_score(risk_factors):
    base = sum(RISK_WEIGHTS.get(f, 0) for f in risk_factors)
    if "DOCUMENTATION_GAP" in risk_factors:
        base = base * 2  # integer floor is identity on integers
    if base >= 50 and "WHISTLEBLOWER_HISTORY" in risk_factors:
        base += 10
    return max(0, min(100, int(base)))


# ---------------------------------------------------------------------------
# Plan closure + rating-cycle outcome links
# ---------------------------------------------------------------------------

def _windows_overlap(c_start, c_end, p_start, p_end):
    return c_start < p_end and p_start < c_end


def _create_outcome_links(pip, ou, outcome):
    emp = employee_of_pip(pip)
    p_start, p_end = parse_dt(pip["start_date"]), parse_dt(pip["end_date"])
    for cyc in db.cycles.values():
        if cyc["hr_org_unit_id"] != ou["id"]:
            continue
        if cyc["status"] not in ("OPEN", "CALIBRATION", "PUBLISHED"):
            continue
        if not _windows_overlap(parse_dt(cyc["window_start"]), parse_dt(cyc["window_end"]),
                                p_start, p_end):
            continue
        link = new_append_record()
        link.update({
            "pip_id": pip["id"],
            "rating_cycle_id": cyc["id"],
            "employee_id": emp["id"],
            "pip_outcome_at_link": outcome,
            "rating_cycle_status_at_link": cyc["status"],
            "link_created_at": ou["current_utc"],
        })
        db.links[link["id"]] = link


def close_pip(pip, ou, outcome):
    """Close a plan: outcome in SUCCESS / TERMINATION / FAILED.
    Applies employee + link cascades. Caller ensures no pending rebuttal."""
    emp = employee_of_pip(pip)
    pip["closed_at"] = ou["current_utc"]
    if outcome == "SUCCESS":
        pip["status"] = "CLOSED_SUCCESS"
    elif outcome == "TERMINATION":
        pip["status"] = "CLOSED_TERMINATED"
        if emp["employment_status"] != "TERMINATED":
            emp["employment_status"] = "TERMINATED"
            emp["terminated_at"] = ou["current_utc"]
    else:
        pip["status"] = "CLOSED_FAILED"
    if emp.get("active_pip_id") == pip["id"]:
        emp["active_pip_id"] = None
    touch(emp)
    touch(pip)
    if outcome in ("SUCCESS", "TERMINATION"):
        _create_outcome_links(pip, ou, outcome)


def pending_rebuttal(pip_id):
    return any(r["status"] in ("SUBMITTED", "UNDER_REVIEW")
               for r in rebuttals_of_pip(pip_id))


def apply_approved_outcome_closure(pip, ou, decision):
    """Close the plan per an APPROVED decision (used by the clock sweep and
    by rebuttal resolution). No-op if the plan already closed."""
    if pip["status"] not in ("ACTIVE", "EXTENDED"):
        return
    outcome = decision["proposed_outcome"]
    if outcome == "SUCCESS":
        close_pip(pip, ou, "SUCCESS")
    elif outcome == "TERMINATION":
        close_pip(pip, ou, "TERMINATION")
    # EXTENSION approvals never close the plan.


# ---------------------------------------------------------------------------
# Logical-clock sweeps (PRD §2.5). Order: activation, missed sweep, then
# rebuttal-window-lapse closures.
# ---------------------------------------------------------------------------

def run_clock_sweeps(ou):
    now = clock_of(ou)
    pips = pips_of_ou(ou["id"])

    # 1. ISSUED -> ACTIVE activation
    for pip in pips:
        if pip["status"] != "ISSUED":
            continue
        if now < parse_dt(pip["start_date"]):
            continue
        if any(c["status"] == "SCHEDULED"
               for c in db.checkins.values() if c["pip_id"] == pip["id"]):
            pip["status"] = "ACTIVE"
            touch(pip)

    # 2. CheckIn SCHEDULED -> MISSED sweep (now > scheduled_for + 3 days)
    for pip in pips:
        changed = False
        for c in checkins_of_pip(pip["id"]):
            if c["status"] == "SCHEDULED" and now > parse_dt(c["scheduled_for"]) + days(3):
                c["status"] = "MISSED"
                touch(c)
                changed = True
        if changed:
            recompute_provisional(pip)

    # 3. Approved outcomes whose rebuttal window lapsed finalize closure
    for pip in pips:
        if pip["status"] not in ("ACTIVE", "EXTENDED"):
            continue
        closes = pip.get("rebuttal_window_closes_at")
        if not closes:
            continue
        if now <= parse_dt(closes):
            continue
        if pending_rebuttal(pip["id"]):
            continue
        decision = latest_approved_decision(pip["id"])
        if decision is None:
            continue
        apply_approved_outcome_closure(pip, ou, decision)


# ---------------------------------------------------------------------------
# Consistency review cohort + scores (PRD §3.8)
# ---------------------------------------------------------------------------

def compute_cohort(ou, target_pip):
    """Cohort of comparable closed PIPs (target excluded), ordered by the
    cohort decisions' decided_at ASC, tie-break created_at ASC."""
    target_emp = employee_of_pip(target_pip)
    target_tmpl = db.templates.get(target_pip["template_id"])
    target_dec = latest_approved_decision(target_pip["id"])
    if target_dec is None or target_emp is None or target_tmpl is None:
        return []
    t_when = parse_dt(target_dec["decided_at"])
    rows = []
    for pip in pips_of_ou(ou["id"]):
        if pip["id"] == target_pip["id"]:
            continue
        if pip["status"] not in PIP_CLOSED_OUTCOME:
            continue
        emp = employee_of_pip(pip)
        tmpl = db.templates.get(pip["template_id"])
        if emp is None or tmpl is None:
            continue
        if tmpl["category"] != target_tmpl["category"]:
            continue
        if emp["job_family"] != target_emp["job_family"]:
            continue
        if abs(int(emp["job_level"]) - int(target_emp["job_level"])) > 1:
            continue
        dec = latest_approved_decision(pip["id"])
        if dec is None:
            continue
        d_when = parse_dt(dec["decided_at"])
        if d_when is None:
            continue
        if not (t_when - days(365) <= d_when <= t_when):
            continue
        rows.append((pip, dec))
    rows.sort(key=lambda r: (parse_dt(r[1]["decided_at"]), r[0]["created_at"], r[0]["_seq"]))
    return rows


def disparity_score(target_pip, cohort_rows):
    target_dec = latest_approved_decision(target_pip["id"])
    target_outcome = target_dec["proposed_outcome"]
    size = len(cohort_rows)
    match = sum(1 for _, d in cohort_rows if d["proposed_outcome"] == target_outcome)
    terms = sum(1 for _, d in cohort_rows if d["proposed_outcome"] == "TERMINATION")
    p_target = Decimal(match) / Decimal(size)
    p_term = Decimal(terms) / Decimal(size)
    indicator = Decimal(1) if target_outcome == "TERMINATION" else Decimal(0)
    score = abs(p_term - indicator) + Decimal("0.5") * (Decimal(1) - p_target)
    return round4(score)


def rating_alignment(pip_id):
    links = [l for l in db.links.values() if l["pip_id"] == pip_id]
    if not links:
        return 0.0
    pub = sum(1 for l in links if l["rating_cycle_status_at_link"] == "PUBLISHED")
    return round4(Decimal(pub) / Decimal(len(links)))
