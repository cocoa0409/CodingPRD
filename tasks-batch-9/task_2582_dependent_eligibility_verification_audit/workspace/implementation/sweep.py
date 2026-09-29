"""The deferred-action checkpoint (section 3.6): six ordered, idempotent steps."""

import calc
import clock
import constants as K
import db
import derive
import emit


def _program_notices(program):
    """Notices this program is responsible for: its cases' plus its POE lapses."""
    rows = []
    for notice in db.ordered("notices"):
        case_id = notice.get("case_id")
        if case_id is not None:
            case = db.get("cases", case_id)
            if case is not None and case["program_id"] == program["id"]:
                rows.append(notice)
            continue
        dependent = db.get("dependents", notice["dependent_id"])
        if dependent is not None and dependent.get("poe_program_id") == program["id"]:
            rows.append(notice)
    return rows


# ------------------------------------------------------------------ S1


def step_close_amnesty(program, now):
    if program["status"] != "AMNESTY_OPEN":
        return False
    end = program.get("amnesty_end_at")
    if end is None or now < end:
        return False
    return db.set_fields(program, status="RESPONSE_WINDOW")


# ------------------------------------------------------------------ S2


def step_escalate(program, now):
    if program["status"] != "RESPONSE_WINDOW":
        return False
    deadline = program.get("response_deadline_at")
    if deadline is None or now < deadline:
        return False

    db.set_fields(program, status="ESCALATION")

    candidates = [
        c
        for c in db.ordered("cases", lambda c: c["program_id"] == program["id"])
        if c["status"] in ("NOTIFIED", "IN_PROGRESS")
    ]
    # priority_score is refreshed before any ordering decision is made
    for case in candidates:
        derive.recompute_case(case)
    candidates.sort(key=lambda c: (-c["priority_score"], c["created_at"], c["_seq"]))

    batch_sequence_no = 0
    for case in candidates:
        db.set_fields(case, status="NON_RESPONSIVE", non_responsive_at=now)
        dependents = []
        for dep_id in case.get("in_scope_dependent_ids") or []:
            dependent = db.get("dependents", dep_id)
            if dependent is not None and dependent["coverage_status"] == "PENDING_VERIFICATION":
                dependents.append(dependent)
        dependents.sort(key=lambda d: (d["created_at"], d["_seq"]))
        issued_any = False
        for dependent in dependents:
            db.set_fields(dependent, coverage_status="TERMINATION_PENDING")
            batch_sequence_no += 1
            emit.termination_notice(
                dependent, case, "AUDIT_ESCALATION", program, batch_sequence_no
            )
            emit.communication(case, "TERMINATION_NOTICE")
            issued_any = True
        if issued_any:
            db.set_fields(case, status="ESCALATED", escalated_at=now)
    return True


# ------------------------------------------------------------------ S3


def step_poe_lapse(program, now):
    mutated = False
    dependents = db.ordered(
        "dependents", lambda d: d.get("poe_program_id") == program["id"]
    )
    batch_sequence_no = 0
    for dependent in dependents:
        if dependent["coverage_status"] != "PENDING_VERIFICATION":
            continue
        # the completeness test is re-evaluated for POE dependents here
        if derive.apply_completeness(dependent, program):
            db.set_fields(dependent, coverage_status="VERIFIED")
            mutated = True
            continue
        deadline = dependent.get("poe_deadline_at")
        if deadline is None or deadline > now:
            continue
        if dependent.get("documentation_complete"):
            continue
        rule = calc.find_rule(
            program["id"], dependent["relationship_type"], "POINT_OF_ENROLLMENT"
        )
        if rule is None or not rule.get("auto_terminate_on_lapse"):
            continue
        db.set_fields(dependent, coverage_status="TERMINATION_PENDING")
        batch_sequence_no += 1
        emit.termination_notice(dependent, None, "POE_LAPSE", program, batch_sequence_no)
        mutated = True
    return mutated


# ------------------------------------------------------------------ S4


def step_finalize(program, now):
    mutated = False
    today = clock.fmt_date(now.date())
    notices = _program_notices(program)

    for notice in notices:
        if notice["status"] != "ISSUED":
            continue
        if notice["effective_date"] >= today:
            continue
        db.set_fields(notice, status="FINAL")
        dependent = db.get("dependents", notice["dependent_id"])
        if dependent is not None and dependent["coverage_status"] == "TERMINATION_PENDING":
            db.set_fields(
                dependent,
                coverage_status="TERMINATED",
                coverage_end_date=notice["effective_date"],
            )
        mutated = True

    for case in db.ordered("cases", lambda c: c["program_id"] == program["id"]):
        if case["status"] != "ESCALATED":
            continue
        case_notices = [n for n in notices if n.get("case_id") == case["id"]]
        if any(n["status"] not in ("FINAL", "RESCINDED") for n in case_notices):
            continue
        unresolved = False
        for dep_id in case.get("in_scope_dependent_ids") or []:
            dependent = db.get("dependents", dep_id)
            if dependent is None:
                continue
            if dependent["coverage_status"] in K.UNRESOLVED_COVERAGE_STATUSES:
                unresolved = True
                break
        if unresolved:
            continue
        window_open = False
        for notice in case_notices:
            if now <= clock.add_days_dt(notice["issued_at"], K.APPEAL_WINDOW_DAYS):
                window_open = True
                break
        if window_open:
            continue
        if db.set_fields(case, status="CLOSED"):
            mutated = True
    return mutated


# ------------------------------------------------------------------ S5


def step_reconcile(program, now):
    if program["status"] != "ESCALATION":
        return False
    cases = db.ordered("cases", lambda c: c["program_id"] == program["id"])
    for case in cases:
        if case["status"] not in ("COMPLETE", "CLOSED", "VOIDED"):
            return False
    return db.set_fields(program, status="RECONCILIATION")


# ------------------------------------------------------------------ S6


def step_expire_elections(program, now):
    mutated = False
    for notice in _program_notices(program):
        if notice["status"] not in ("ISSUED", "FINAL"):
            continue
        if notice["continuation_election_status"] != "NOT_ELECTED":
            continue
        deadline = notice.get("continuation_election_deadline")
        if deadline is None or deadline >= now:
            continue
        if db.set_fields(notice, continuation_election_status="WINDOW_EXPIRED"):
            mutated = True
    return mutated


# ------------------------------------------------------------------ driver


def run(program):
    now = clock.now()
    mutated = False
    mutated = step_close_amnesty(program, now) or mutated
    mutated = step_escalate(program, now) or mutated
    mutated = step_poe_lapse(program, now) or mutated
    mutated = step_finalize(program, now) or mutated
    mutated = step_reconcile(program, now) or mutated
    mutated = step_expire_elections(program, now) or mutated
    if mutated:
        db.set_fields(program, sweep_epoch=(program.get("sweep_epoch") or 0) + 1)
        db.mark_dirty(program)
    return mutated
