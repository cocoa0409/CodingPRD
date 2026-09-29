"""Derived-field recomputation (section 2.9).

Nothing here patches a counter incrementally: every value is recounted from the
entities it summarises, so a read of a program always agrees with a full recount.
"""

import calc
import clock
import constants as K
import db


# ------------------------------------------------------------------ dependents


def recompute_dependent(dependent):
    accepted = set()
    for sub in db.collection("submissions").values():
        if sub["dependent_id"] != dependent["id"]:
            continue
        if sub["review_status"] != "ACCEPTED":
            continue
        if sub["privacy_status"] not in ("NOT_REQUIRED", "REDACTED", "PURGED"):
            continue
        accepted.add(sub["proof_type"])
    paid_total = sum(
        line["paid_cents"]
        for line in db.collection("claim_lines").values()
        if line["dependent_id"] == dependent["id"]
    )
    db.set_fields(
        dependent,
        accepted_proof_type_count=len(accepted),
        paid_claims_total_cents=paid_total,
    )


def dependent_case(dependent):
    """The non-voided AuditCase whose frozen in-scope set holds this dependent."""
    for case in db.ordered("cases"):
        if case["status"] == "VOIDED":
            continue
        if dependent["id"] in (case.get("in_scope_dependent_ids") or []):
            return case
    return None


def dependent_program(dependent):
    """The program whose documentation policy governs this dependent right now."""
    case = dependent_case(dependent)
    if case is not None:
        return db.get("programs", case["program_id"])
    poe_program_id = dependent.get("poe_program_id")
    if poe_program_id is not None:
        return db.get("programs", poe_program_id)
    return None


def apply_completeness(dependent, program):
    """Run the completeness test; returns True when it newly flipped to true."""
    count, complete = calc.documentation_completeness(dependent, program)
    was_complete = bool(dependent.get("documentation_complete"))
    db.set_fields(dependent, accepted_proof_type_count=count)
    if complete and not was_complete:
        db.set_fields(dependent, documentation_complete=True)
        return True
    return False


# ------------------------------------------------------------------ employees


def recompute_employee(employee):
    if employee is None:
        return
    count = 0
    for dep in db.collection("dependents").values():
        if dep["employee_id"] == employee["id"] and dep["coverage_status"] == "ENROLLED":
            count += 1
    db.set_fields(employee, enrolled_dependent_count=count)


def recompute_employee_by_id(employee_id):
    recompute_employee(db.get("employees", employee_id))


# ------------------------------------------------------------------ cases


def case_has_response(case):
    for sub in db.collection("submissions").values():
        if sub["case_id"] == case["id"]:
            return True
    for removal in db.collection("amnesty_removals").values():
        if removal["case_id"] == case["id"]:
            return True
    return False


def recompute_case(case):
    ids = case.get("in_scope_dependent_ids") or []
    unverified = 0
    for dep_id in ids:
        dependent = db.get("dependents", dep_id)
        if dependent is None:
            continue
        if dependent["coverage_status"] in K.UNRESOLVED_COVERAGE_STATUSES:
            unverified += 1
    proof_count = sum(
        1
        for sub in db.collection("submissions").values()
        if sub["case_id"] == case["id"]
    )
    reminders = sum(
        1
        for ev in db.collection("communications").values()
        if ev["case_id"] == case["id"] and ev["kind"] == "REMINDER"
    )
    db.set_fields(
        case,
        in_scope_dependent_count=len(ids),
        unverified_dependent_count=unverified,
        proof_submission_count=proof_count,
        reminders_sent_count=reminders,
    )
    program = db.get("programs", case["program_id"])
    db.set_fields(case, priority_score=calc.case_escalation_priority_score(case, program))


def first_response(case):
    """The first response of any kind on a notified case opens it for work."""
    if case["status"] == "NOTIFIED":
        db.set_fields(case, status="IN_PROGRESS")


def case_is_resolved(case):
    ids = case.get("in_scope_dependent_ids") or []
    if not ids:
        return False
    for dep_id in ids:
        dependent = db.get("dependents", dep_id)
        if dependent is None:
            return False
        if dependent["coverage_status"] not in K.RESOLVED_COVERAGE_STATUSES:
            return False
    return True


def maybe_complete_case(case):
    if case["status"] not in ("NOTIFIED", "IN_PROGRESS", "ESCALATED"):
        return False
    if not case_is_resolved(case):
        return False
    db.set_fields(case, status="COMPLETE", completed_at=clock.now())
    return True


# ------------------------------------------------------------------ programs


def program_cases(program):
    return db.ordered("cases", lambda c: c["program_id"] == program["id"])


def recoveries_of(dependent_ids):
    wanted = set(dependent_ids)
    rows = [
        r
        for r in db.collection("recoveries").values()
        if r["dependent_id"] in wanted
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def recompute_program(program):
    cases = program_cases(program)
    live_cases = [c for c in cases if c["status"] != "VOIDED"]

    dependent_ids = []
    for case in live_cases:
        dependent_ids.extend(case.get("in_scope_dependent_ids") or [])

    buckets = {
        "PENDING_VERIFICATION": 0,
        "VERIFIED": 0,
        "REINSTATED": 0,
        "AMNESTY_REMOVED": 0,
        "TERMINATION_PENDING": 0,
        "TERMINATED": 0,
    }
    for dep_id in dependent_ids:
        dependent = db.get("dependents", dep_id)
        if dependent is None:
            continue
        status = dependent["coverage_status"]
        if status in buckets:
            buckets[status] += 1

    responded = 0
    non_responsive = 0
    for case in cases:
        if case["status"] in ("IN_PROGRESS", "COMPLETE", "CLOSED") and case_has_response(
            case
        ):
            responded += 1
        if case["status"] in ("NON_RESPONSIVE", "ESCALATED"):
            non_responsive += 1

    ledger = 0
    recovered = 0
    refund_due = 0
    for recovery in recoveries_of(dependent_ids):
        if recovery["status"] in ("DEMAND_ISSUED", "PARTIALLY_RECOVERED", "RECOVERED"):
            ledger += recovery["net_demand_cents"]
        if recovery["status"] != "VOIDED":
            recovered += recovery["recovered_cents"]
        refund_due += recovery["refund_due_cents"]

    db.set_fields(
        program,
        in_scope_case_count=len(live_cases),
        in_scope_dependent_count=len(dependent_ids),
        pending_dependent_count=buckets["PENDING_VERIFICATION"],
        verified_dependent_count=buckets["VERIFIED"] + buckets["REINSTATED"],
        amnesty_removed_count=buckets["AMNESTY_REMOVED"],
        termination_pending_count=buckets["TERMINATION_PENDING"],
        terminated_dependent_count=buckets["TERMINATED"],
        responded_case_count=responded,
        non_responsive_case_count=non_responsive,
        provisional_annual_savings_cents=calc.savings(program, "PROVISIONAL"),
        audited_annual_savings_cents=calc.savings(program, "AUDITED"),
        recovery_ledger_cents=ledger,
        recovered_total_cents=recovered,
        refund_due_total_cents=refund_due,
    )


# ------------------------------------------------------------------ whole graph


def refresh_all():
    """Recompute every derived field after a mutating request.

    Only values that actually changed mark their record dirty, so entities the
    request merely read keep their updated_at and version untouched.
    """
    for dependent in db.collection("dependents").values():
        recompute_dependent(dependent)
    for employee in db.collection("employees").values():
        recompute_employee(employee)
    for case in db.collection("cases").values():
        recompute_case(case)
    for program in db.collection("programs").values():
        recompute_program(program)
