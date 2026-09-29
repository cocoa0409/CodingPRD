"""Shared roll-ups, ledger arithmetic and cascades."""
from datetime import timedelta

import calc
from envelope import touch
from store import by_created, parse_date, parse_datetime, store

TERMINAL_STAGES = ("CLOSED", "WITHDRAWN", "DENIED_FINAL")


def assign(row, **changes):
    """Apply changes; mark the row mutated only when a value actually moved."""
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


# --- collection helpers ---------------------------------------------------
def options_of(request_id):
    return [o for o in store.options.values() if o["request_id"] == request_id]


def trials_of(request_id):
    return [t for t in store.trials.values() if t["request_id"] == request_id]


def analyses_of(request_id):
    return [a for a in store.function_analyses.values() if a["request_id"] == request_id]


def denials_of(request_id):
    return [d for d in store.denials.values() if d["request_id"] == request_id]


def appeals_of_denial(denial_id):
    return [a for a in store.appeals.values() if a["denial_record_id"] == denial_id]


def appeals_of_case(request_id):
    out = []
    for denial in denials_of(request_id):
        out.extend(appeals_of_denial(denial["id"]))
    return out


def case_of_appeal(appeal):
    denial = store.denials.get(appeal["denial_record_id"])
    if denial is None:
        return None, None
    return denial, store.requests.get(denial["request_id"])


def assessments_of(option_id):
    return [a for a in store.assessments.values() if a["option_id"] == option_id]


def current_assessment(option_id):
    rows = [a for a in assessments_of(option_id) if a["status"] == "CURRENT"]
    return rows[-1] if rows else None


def profile_of_case(req):
    return store.job_profiles.get(req["job_profile_id"])


# --- roll-ups -------------------------------------------------------------
def recompute_profile_rollups(profile):
    duties = [f for f in store.essential_functions.values()
              if f["job_profile_id"] == profile["id"]]
    active = [f for f in duties if f["status"] == "ACTIVE"]
    weight = sum(f["criticality_weight"] for f in active if f["is_essential"] is True)
    assign(profile,
           essential_function_count=len(active),
           total_essential_weight=weight)


def recompute_option_counts(req):
    opts = options_of(req["id"])
    assign(req,
           cleared_option_count=len([o for o in opts if o["status"] == "CLEARED"]),
           blocked_option_count=len([o for o in opts if o["status"] == "HARDSHIP_BLOCKED"]))


def recompute_open_case_count(employee):
    count = len([r for r in store.requests.values()
                 if r["employee_id"] == employee["id"]
                 and r["stage"] not in TERMINAL_STAGES])
    assign(employee, open_case_count=count)


def recompute_denial_count(employee):
    total = 0
    for req in store.requests.values():
        if req["employee_id"] != employee["id"]:
            continue
        for denial in denials_of(req["id"]):
            if denial["status"] in ("ISSUED", "APPEALED", "FINAL"):
                total += 1
    assign(employee, lifetime_denial_count=total)


def recompute_option_coverage(option):
    req = store.requests.get(option["request_id"])
    if req is None:
        return
    ratio = calc.coverage_ratio(req["job_profile_id"], option["coverage_function_ids"])
    assign(option, coverage_ratio=calc.as_number(ratio))


def refresh_integrity(req):
    assign(req, interactive_process_integrity_score=calc.integrity_score(req))


def refresh_doc_budget(req):
    limit = req["medical_doc_request_limit"]
    count = len([d for d in calc.doc_rounds_of(req["id"]) if d["status"] != "WITHDRAWN"])
    assign(req,
           medical_doc_request_count=count,
           documentation_budget_remaining=max(0, limit - count))


def refresh_doc_limit(req):
    """Recompute the ceiling itself (base + bonuses, capped)."""
    limit, count, remaining = calc.documentation_budget(req)
    assign(req,
           medical_doc_request_limit=limit,
           medical_doc_request_count=count,
           documentation_budget_remaining=remaining)


# --- committed-cost ledger (PRD 2.11) ------------------------------------
def ledger_commit(option, req):
    profile = profile_of_case(req)
    amount = int(option["option_net_cost_cents"])
    assign(option, committed_cost_cents=amount)
    if profile is not None:
        assign(profile,
               committed_accommodation_cost_cents=int(
                   profile["committed_accommodation_cost_cents"]) + amount)


def ledger_release(option, req):
    profile = profile_of_case(req)
    held = int(option["committed_cost_cents"])
    if profile is not None:
        assign(profile,
               committed_accommodation_cost_cents=int(
                   profile["committed_accommodation_cost_cents"]) - held)
    assign(option, committed_cost_cents=0)


# --- confidentiality seal cascade (PRD 3.9) ------------------------------
def seal_case(req):
    """Hops 2 and 3 of the unauthorized-disclosure cascade."""
    assign(req, confidentiality_posture="SEALED")
    refresh_integrity(req)
    for appeal in by_created(appeals_of_case(req["id"])):
        if appeal["status"] == "UNDER_REVIEW":
            assign(appeal,
                   status="SUPPLEMENT_REQUESTED",
                   stay_count=appeal["stay_count"] + 1)


# --- employee absence-driven employment status ---------------------------
def has_other_live_absence(employee_id, exclude_id):
    for row in store.absences.values():
        if row["employee_id"] != employee_id or row["id"] == exclude_id:
            continue
        if row["status"] in ("ACTIVE", "MODIFIED_DUTY"):
            return True
    return False


def absence_activate(record):
    employee = store.employees.get(record["employee_id"])
    assign(record, status="ACTIVE")
    if employee is not None:
        status = "RESTRICTED_DUTY" if record["record_type"] == "WC_RESTRICTION" else "ON_LEAVE"
        assign(employee, employment_status=status)


def absence_release(record):
    employee = store.employees.get(record["employee_id"])
    if employee is None:
        return
    if not has_other_live_absence(employee["id"], record["id"]):
        assign(employee, employment_status="ACTIVE")


# --- employee withdrawal cascade (PRD 3.3) -------------------------------
def withdraw_case(req):
    assign(req, stage="WITHDRAWN")
    for option in by_created(options_of(req["id"])):
        if option["status"] in ("PROPOSED", "CLEARED", "HARDSHIP_BLOCKED"):
            assign(option, status="WITHDRAWN")
    recompute_option_counts(req)
    for round_row in by_created(calc.doc_rounds_of(req["id"])):
        if round_row["status"] in ("ISSUED", "RESPONDED"):
            assign(round_row, status="WITHDRAWN")
    refresh_doc_budget(req)
    for trial in by_created(trials_of(req["id"])):
        if trial["status"] in ("SCHEDULED", "ACTIVE", "UNDER_REVIEW"):
            assign(trial, status="ABORTED")
    employee = store.employees.get(req["employee_id"])
    if employee is not None:
        recompute_open_case_count(employee)


# --- daily sweep (PRD 2.5) -----------------------------------------------
def run_daily_sweep():
    now = store.now()
    today = store.today()

    # Snapshot every phase's candidate set before any change is applied, so
    # that no row promoted by an earlier phase becomes eligible for a later
    # one within the same sweep.
    phase1 = [d for d in by_created(store.doc_requests.values())
              if d["status"] == "ISSUED"
              and parse_datetime(d["due_date"]) is not None
              and parse_datetime(d["due_date"]) <= now]
    phase2 = [a for a in by_created(store.absences.values())
              if a["status"] == "SCHEDULED" and parse_date(a["start_date"]) <= today]
    phase3 = [a for a in by_created(store.absences.values())
              if a["status"] == "ACTIVE"
              and a["record_type"] in ("FMLA_CONTINUOUS", "FMLA_INTERMITTENT", "STATE_LEAVE")
              and parse_date(a["end_date"]) <= today]
    phase4 = [t for t in by_created(store.trials.values())
              if t["status"] == "SCHEDULED" and parse_date(t["start_date"]) <= today]
    phase5 = [t for t in by_created(store.trials.values())
              if t["status"] == "ACTIVE" and parse_date(t["end_date"]) <= today]
    phase6 = [r for r in by_created(store.requests.values())
              if r["stage"] == "GRANTED_PERMANENT"
              and r.get("review_due_date") is not None
              and parse_date(r["review_due_date"]) <= today]
    phase7 = [d for d in by_created(store.denials.values())
              if d["status"] == "ISSUED" and d["appeal_count"] == 0
              and parse_date(d["appeal_deadline_date"]) < today]

    touched_cases = {}

    for row in phase1:
        assign(row, status="EXPIRED")
        req = store.requests.get(row["request_id"])
        if req is not None:
            touched_cases[req["id"]] = req

    for row in phase2:
        absence_activate(row)

    for row in phase3:
        assign(row, status="EXHAUSTED")
        absence_release(row)

    for row in phase4:
        assign(row, status="ACTIVE")

    for row in phase5:
        assign(row, status="UNDER_REVIEW",
               effectiveness_score=calc.effectiveness_score(row))

    for row in phase6:
        assign(row, stage="RENEWAL_DUE")
        touched_cases[row["id"]] = row

    for row in phase7:
        assign(row, status="FINAL")
        req = store.requests.get(row["request_id"])
        if req is not None:
            assign(req, stage="DENIED_FINAL")
            employee = store.employees.get(req["employee_id"])
            if employee is not None:
                recompute_open_case_count(employee)
                recompute_denial_count(employee)

    for req in touched_cases.values():
        refresh_integrity(req)

    return {
        "swept_at": store.now_iso(),
        "doc_requests_expired": len(phase1),
        "absence_records_activated": len(phase2),
        "absence_records_exhausted": len(phase3),
        "trials_activated": len(phase4),
        "trials_moved_to_review": len(phase5),
        "requests_moved_to_renewal_due": len(phase6),
        "denials_finalized": len(phase7),
    }
