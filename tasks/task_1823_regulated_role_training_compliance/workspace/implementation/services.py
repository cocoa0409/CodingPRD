"""Business logic: assignment seeding, due dates, deadline stages, posture, cascades, sweep."""
from datetime import timedelta

from db import new_entity, now, store, touch
from util import DAY, add_business_days, add_months, add_years, pct2, round2
from decimal import Decimal

COVERING = ("ASSIGNED", "IN_PROGRESS", "SUBMITTED", "VERIFIED_COMPLETED")
NON_TERMINAL = ("ASSIGNED", "IN_PROGRESS", "SUBMITTED")
EVIDENCE_TIERS = {"NONE": 0, "CERTIFICATE": 1, "PROCTORED_CERTIFICATE": 2}


# ---------------------------------------------------------------- assignments

def compute_base_due(assigned_at, due_in_days, mode):
    if mode == "BUSINESS_DAYS":
        return add_business_days(assigned_at, due_in_days)
    return assigned_at + timedelta(days=due_in_days)


def threshold_days(assignment):
    """Escalation threshold: full interval for SOFT, ceil(interval/2) for HARD."""
    req = store.requirements.get(assignment["role_requirement_id"])
    interval = assignment["_escalation_interval_days"]
    if req is not None and req["criticality"] == "HARD":
        return -(-interval // 2)  # ceil(interval / 2)
    return interval


def deadline_stage(assignment, employee, at=None):
    """PRD 3.5: FROZEN on leave; else clock vs due_at with strict boundary pins."""
    at = at if at is not None else now()
    if employee["status"] == "ON_LEAVE":
        return "FROZEN"
    due = assignment["due_at"]
    rem = assignment["_reminder_days"]
    threshold = threshold_days(assignment)
    if at <= due:
        return "DUE_SOON" if (due - at).total_seconds() <= rem * DAY else "ON_TRACK"
    if at <= due + timedelta(days=threshold):
        return "OVERDUE"
    return "ESCALATED"


def create_assignment(employee, requirement, trigger_source, source_role_change_id=None):
    """Shared seeding path. due_at invariant: base_due_at + active_extension_days days."""
    curriculum = store.curricula[requirement["curriculum_id"]]
    regulator = store.regulators[curriculum["regulator_id"]]
    t = now()
    base_due = compute_base_due(t, requirement["due_in_days"], regulator["deadline_mode"])
    a = new_entity()
    a.update({
        "employee_id": employee["id"],
        "role_requirement_id": requirement["id"],
        "curriculum_id": curriculum["id"],
        "trigger_source": trigger_source,
        "source_role_change_id": source_role_change_id,
        "assigned_at": t,
        "base_due_at": base_due,
        "active_extension_days": 0,
        "due_at": base_due,
        "attempts_used": 0,
        "progress_status": "ASSIGNED",
        "deadline_status": "ON_TRACK",
        "completed_at": None,
        "expires_at": None,
        # PRD 3.1: configuration is not retroactive — thresholds snapshotted at creation.
        "_reminder_days": regulator["reminder_days_before_due"],
        "_escalation_interval_days": regulator["escalation_interval_days"],
    })
    a["deadline_status"] = deadline_stage(a, employee, t)
    store.assignments[a["id"]] = a
    return a


def covering_assignment_exists(employee_id, curriculum_id):
    """Coverage is keyed by curriculum, not by requirement (PRD 3.2/3.3)."""
    for a in store.assignments.values():
        if (a["employee_id"] == employee_id and a["curriculum_id"] == curriculum_id
                and a["progress_status"] in COVERING):
            return True
    return False


def void_pending_completions(assignment):
    for c in store.completions.values():
        if c["assignment_id"] == assignment["id"] and c["review_status"] == "PENDING_REVIEW":
            c["review_status"] = "VOIDED"
            touch(c)


def cancel_assignment(assignment):
    """ASSIGNED/IN_PROGRESS/SUBMITTED -> CANCELLED; PENDING_REVIEW completions -> VOIDED."""
    assignment["progress_status"] = "CANCELLED"
    touch(assignment)
    void_pending_completions(assignment)


# ---------------------------------------------------------------- posture

def posture_blocked(employee):
    """PRD 3.6 posture_block_evaluation, evaluated against current facts."""
    if employee["status"] == "TERMINATED":
        return False
    for a in store.assignments.values():
        if a["employee_id"] != employee["id"]:
            continue
        req = store.requirements.get(a["role_requirement_id"])
        if req is None or req["criticality"] != "HARD":
            continue
        if req["role_id"] != employee["current_role_id"]:
            continue
        if a["deadline_status"] == "ESCALATED":
            return True
        if a["progress_status"] == "FAILED":
            cured = False
            for b in store.assignments.values():
                if (b["employee_id"] == employee["id"]
                        and b["role_requirement_id"] == a["role_requirement_id"]
                        and b["progress_status"] == "VERIFIED_COMPLETED"
                        and b["assigned_at"] > a["assigned_at"]):
                    cured = True
                    break
            if not cured:
                return True
    return False


def recompute_posture(employee):
    """Flip compliance_blocked and cascade OPEN-campaign attestations on transitions.

    Returns number of attestations that flipped PENDING -> BLOCKED (sweep counter)."""
    new_val = posture_blocked(employee)
    old_val = employee["compliance_blocked"]
    if new_val == old_val:
        return 0
    employee["compliance_blocked"] = new_val
    touch(employee)
    flipped = 0
    if new_val:
        for att in store.attestations.values():
            if att["employee_id"] != employee["id"] or att["status"] != "PENDING":
                continue
            camp = store.campaigns.get(att["campaign_id"])
            if camp is not None and camp["status"] == "OPEN":
                att["status"] = "BLOCKED"
                touch(att)
                flipped += 1
    else:
        for att in store.attestations.values():
            if att["employee_id"] != employee["id"] or att["status"] != "BLOCKED":
                continue
            camp = store.campaigns.get(att["campaign_id"])
            if camp is not None and camp["status"] == "OPEN":
                att["status"] = "PENDING"
                touch(att)
    return flipped


def recompute_verified_count(employee):
    n = sum(1 for a in store.assignments.values()
            if a["employee_id"] == employee["id"] and a["progress_status"] == "VERIFIED_COMPLETED")
    if n != employee["verified_completed_count"]:
        employee["verified_completed_count"] = n
        touch(employee)


# ------------------------------------------------------------- role changes

def apply_role_change(rc):
    """EmployeeRoleChange SCHEDULED -> APPLIED (or synchronous at creation). PRD 3.3."""
    emp = store.employees[rc["employee_id"]]
    new_role = store.roles[rc["to_role_id"]]
    t = now()
    rc["status"] = "APPLIED"
    rc["applied_at"] = t
    touch(rc)
    emp["current_role_id"] = new_role["id"]
    touch(emp)
    new_reqs = [r for r in store.requirements.values()
                if r["role_id"] == new_role["id"] and r["status"] == "ACTIVE"]
    new_reqs.sort(key=lambda r: r["created_at"])
    new_curr_ids = {r["curriculum_id"] for r in new_reqs}
    # Cancel non-terminal assignments whose curriculum is not required by the new role.
    for a in sorted(store.assignments.values(), key=lambda x: x["created_at"]):
        if (a["employee_id"] == emp["id"] and a["progress_status"] in NON_TERMINAL
                and a["curriculum_id"] not in new_curr_ids):
            cancel_assignment(a)
    # Create assignments for uncovered ACTIVE requirements of the new role.
    for r in new_reqs:
        if not covering_assignment_exists(emp["id"], r["curriculum_id"]):
            create_assignment(emp, r, "ROLE_CHANGE", rc["id"])
    recompute_verified_count(emp)
    recompute_posture(emp)


def reverse_role_change(rc, from_role):
    """APPLIED -> REVERSED with compensating cascades. PRD 3.3."""
    emp = store.employees[rc["employee_id"]]
    t = now()
    for a in sorted(store.assignments.values(), key=lambda x: x["created_at"]):
        if (a["employee_id"] == emp["id"] and a["source_role_change_id"] == rc["id"]
                and a["progress_status"] in NON_TERMINAL):
            cancel_assignment(a)
    emp["current_role_id"] = from_role["id"]
    touch(emp)
    rc["status"] = "REVERSED"
    rc["reversed_at"] = t
    touch(rc)
    reqs = [r for r in store.requirements.values()
            if r["role_id"] == from_role["id"] and r["status"] == "ACTIVE"]
    reqs.sort(key=lambda r: r["created_at"])
    for r in reqs:
        if not covering_assignment_exists(emp["id"], r["curriculum_id"]):
            create_assignment(emp, r, "REVERSAL", rc["id"])
    recompute_verified_count(emp)
    recompute_posture(emp)


# -------------------------------------------------------------- termination

def terminate_employee(emp):
    """Heaviest cascade in the system (PRD 3.3)."""
    for a in sorted(store.assignments.values(), key=lambda x: x["created_at"]):
        if a["employee_id"] == emp["id"] and a["progress_status"] in NON_TERMINAL:
            cancel_assignment(a)
    for rc in store.role_changes.values():
        if rc["employee_id"] == emp["id"] and rc["status"] == "SCHEDULED":
            rc["status"] = "CANCELLED"
            touch(rc)
    for att in store.attestations.values():
        if att["employee_id"] == emp["id"] and att["status"] in ("PENDING", "BLOCKED", "EXCEPTION_PENDING"):
            att["status"] = "EXPIRED"
            touch(att)
            for exc in store.exceptions.values():
                if exc["attestation_id"] == att["id"] and exc["status"] == "REQUESTED":
                    exc["status"] = "DENIED"
                    exc["decision_note"] = "AUTO_DENIED_AT_CLOSE"
                    touch(exc)
    emp["status"] = "TERMINATED"
    emp["compliance_blocked"] = False
    touch(emp)


# ------------------------------------------------------------------ notices

def ensure_notice(assignment, level, kind, recipient_id):
    """Existence-deduped per (assignment, level) across notices of any status."""
    for n in store.notices.values():
        if n["assignment_id"] == assignment["id"] and n["level"] == level:
            return None
    notice = new_entity()
    notice.update({
        "assignment_id": assignment["id"],
        "level": level,
        "kind": kind,
        "recipient_employee_id": recipient_id,
        "triggered_at": now(),
        "status": "OPEN",
    })
    store.notices[notice["id"]] = notice
    return notice


# ------------------------------------------------------------------ campaigns

def close_campaign(campaign):
    """OPEN -> CLOSED with expiry cascade. Returns (attestations_expired, exceptions_auto_denied)."""
    expired = denied = 0
    campaign["status"] = "CLOSED"
    touch(campaign)
    for att in store.attestations.values():
        if att["campaign_id"] != campaign["id"]:
            continue
        if att["status"] in ("PENDING", "BLOCKED", "EXCEPTION_PENDING"):
            att["status"] = "EXPIRED"
            touch(att)
            expired += 1
            for exc in store.exceptions.values():
                if exc["attestation_id"] == att["id"] and exc["status"] == "REQUESTED":
                    exc["status"] = "DENIED"
                    exc["decision_note"] = "AUTO_DENIED_AT_CLOSE"
                    touch(exc)
                    denied += 1
    return expired, denied


# --------------------------------------------------------------------- sweep

def run_sweep():
    """Deterministic five-step sweep (PRD 2.5). Steps run in pinned order."""
    t = now()
    out = {
        "role_changes_applied": 0,
        "leaves_started": 0,
        "leaves_ended": 0,
        "assignments_transitioned": 0,
        "notices_created": 0,
        "assignments_expired": 0,
        "recurrences_created": 0,
        "campaigns_closed": 0,
        "attestations_expired": 0,
        "attestations_blocked": 0,
        "exceptions_auto_denied": 0,
    }

    # Step 1: apply due role changes (the ONLY path from SCHEDULED to APPLIED).
    due = [rc for rc in store.role_changes.values()
           if rc["status"] == "SCHEDULED" and rc["effective_at"] <= t]
    due.sort(key=lambda rc: rc["created_at"])
    for rc in due:
        apply_role_change(rc)
        out["role_changes_applied"] += 1

    # Step 2: leave flips. Employee status follows whether any leave window covers now.
    for emp in sorted(store.employees.values(), key=lambda e: e["created_at"]):
        if emp["status"] == "TERMINATED":
            continue
        covering = any(lv["employee_id"] == emp["id"]
                       and lv["start_date"] <= t <= lv["end_date"]
                       for lv in store.leaves.values())
        if covering and emp["status"] == "ACTIVE":
            emp["status"] = "ON_LEAVE"
            touch(emp)
            out["leaves_started"] += 1
        elif not covering and emp["status"] == "ON_LEAVE":
            emp["status"] = "ACTIVE"
            touch(emp)
            out["leaves_ended"] += 1

    # Step 3: deadline statuses + notices + HARD-escalation block cascade.
    for a in sorted(store.assignments.values(), key=lambda x: x["created_at"]):
        if a["progress_status"] not in NON_TERMINAL:
            continue
        emp = store.employees[a["employee_id"]]
        stage = deadline_stage(a, emp, t)
        if stage != a["deadline_status"]:
            a["deadline_status"] = stage
            touch(a)
            out["assignments_transitioned"] += 1
        # Notices ensured per observed stage, deduped per (assignment, level).
        if stage == "DUE_SOON":
            if ensure_notice(a, 1, "DUE_SOON_REMINDER", emp["id"]):
                out["notices_created"] += 1
        elif stage == "OVERDUE":
            if ensure_notice(a, 2, "OVERDUE_MANAGER", emp["manager_id"]):
                out["notices_created"] += 1
        elif stage == "ESCALATED":
            if ensure_notice(a, 2, "OVERDUE_MANAGER", emp["manager_id"]):
                out["notices_created"] += 1
            if ensure_notice(a, 3, "ESCALATION_COMPLIANCE", None):
                out["notices_created"] += 1
    for emp in sorted(store.employees.values(), key=lambda e: e["created_at"]):
        if emp["status"] != "TERMINATED":
            out["attestations_blocked"] += recompute_posture(emp)

    # Step 4: validity expiry (inclusive boundary) + recurrence creation.
    for a in sorted(store.assignments.values(), key=lambda x: x["created_at"]):
        if (a["progress_status"] == "VERIFIED_COMPLETED" and a["expires_at"] is not None
                and t >= a["expires_at"]):
            a["progress_status"] = "EXPIRED"
            touch(a)
            out["assignments_expired"] += 1
            emp = store.employees[a["employee_id"]]
            recompute_verified_count(emp)
            req = store.requirements.get(a["role_requirement_id"])
            if (req is not None and req["status"] == "ACTIVE"
                    and req["recurrence"] == "VALIDITY_CYCLE"
                    and emp["status"] in ("ACTIVE", "ON_LEAVE")):
                create_assignment(emp, req, "RECURRENCE")
                out["recurrences_created"] += 1
            out["attestations_blocked"] += recompute_posture(emp)

    # Step 5: campaign auto-close once now is strictly past window_close_at.
    for camp in sorted(store.campaigns.values(), key=lambda c: c["created_at"]):
        if camp["status"] == "OPEN" and t > camp["window_close_at"]:
            expired, denied = close_campaign(camp)
            out["campaigns_closed"] += 1
            out["attestations_expired"] += expired
            out["exceptions_auto_denied"] += denied

    return out


# --------------------------------------------------------------- attestations

def eligible_for_campaign(emp, regulator_id):
    """ACTIVE/ON_LEAVE and >=1 non-CANCELLED assignment under the campaign's regulator."""
    if emp["status"] not in ("ACTIVE", "ON_LEAVE"):
        return False
    for a in store.assignments.values():
        if a["employee_id"] != emp["id"] or a["progress_status"] == "CANCELLED":
            continue
        curr = store.curricula.get(a["curriculum_id"])
        if curr is not None and curr["regulator_id"] == regulator_id:
            return True
    return False


def open_campaign(campaign):
    """DRAFT -> OPEN; create one Attestation per eligible employee in pinned order."""
    campaign["status"] = "OPEN"
    touch(campaign)
    emps = [e for e in store.employees.values() if eligible_for_campaign(e, campaign["regulator_id"])]
    emps.sort(key=lambda e: (e["created_at"], e["employee_no"]))
    for emp in emps:
        att = new_entity()
        att.update({
            "campaign_id": campaign["id"],
            "employee_id": emp["id"],
            "status": "BLOCKED" if emp["compliance_blocked"] else "PENDING",
            "attested_at": None,
            "statement_version_snapshot": None,
        })
        store.attestations[att["id"]] = att


def finalize_metrics(campaign):
    """campaign_response_rate over the campaign's attestation rows (any status)."""
    rows = [a for a in store.attestations.values() if a["campaign_id"] == campaign["id"]]
    pop = len(rows)
    attested = sum(1 for a in rows if a["status"] == "ATTESTED")
    exempted = sum(1 for a in rows if a["status"] == "EXEMPTED")
    expired = sum(1 for a in rows if a["status"] == "EXPIRED")
    return {
        "population_size": pop,
        "attested_count": attested,
        "exempted_count": exempted,
        "expired_count": expired,
        "response_rate_pct": float(pct2(attested + exempted, pop)),
    }


# ------------------------------------------------------------- audit reports

def generate_audit_metrics(population_spec, metric_variant):
    regulator_id = population_spec["regulator_id"]
    role_id = population_spec.get("role_id")
    manager_id = population_spec.get("manager_id")
    open_set = (("ASSIGNED", "IN_PROGRESS", "SUBMITTED", "FAILED") if metric_variant == "STRICT"
                else ("ASSIGNED", "IN_PROGRESS", "FAILED"))

    population = []
    for emp in store.employees.values():
        if emp["status"] not in ("ACTIVE", "ON_LEAVE"):
            continue
        if role_id is not None and emp["current_role_id"] != role_id:
            continue
        if manager_id is not None and emp["manager_id"] != manager_id:
            continue
        in_scope = False
        for a in store.assignments.values():
            if a["employee_id"] != emp["id"] or a["progress_status"] == "CANCELLED":
                continue
            curr = store.curricula.get(a["curriculum_id"])
            if curr is not None and curr["regulator_id"] == regulator_id:
                in_scope = True
                break
        if in_scope:
            population.append(emp)

    pop_size = len(population)
    compliant = 0
    overdue = 0
    for emp in population:
        has_open = any(a["employee_id"] == emp["id"] and a["progress_status"] in open_set
                       for a in store.assignments.values())
        if not has_open:
            compliant += 1
        for a in store.assignments.values():
            if (a["employee_id"] == emp["id"] and a["progress_status"] in NON_TERMINAL
                    and a["deadline_status"] in ("OVERDUE", "ESCALATED")):
                overdue += 1

    # Weighted first-attempt pass rate: per-curriculum rates rounded FIRST, then weighted mean.
    weighted_sum = Decimal(0)
    weight_total = 0
    for curr in store.curricula.values():
        if curr["regulator_id"] != regulator_id:
            continue
        total_c = accepted_c = 0
        for c in store.completions.values():
            a = store.assignments.get(c["assignment_id"])
            if (a is not None and a["curriculum_id"] == curr["id"] and c["attempt_no"] == 1
                    and c["review_status"] in ("ACCEPTED", "REJECTED")):
                total_c += 1
                if c["review_status"] == "ACCEPTED":
                    accepted_c += 1
        if total_c == 0:
            continue
        rate_c = pct2(accepted_c, total_c)  # round first
        weighted_sum += Decimal(total_c) * rate_c
        weight_total += total_c
    if weight_total == 0:
        weighted_rate = Decimal("0.00")
    else:
        weighted_rate = round2(weighted_sum / Decimal(weight_total))

    return {
        "population_size": pop_size,
        "compliant_count": compliant,
        "compliance_rate_pct": float(pct2(compliant, pop_size)),
        "overdue_count": overdue,
        "weighted_first_attempt_pass_rate_pct": float(weighted_rate),
    }


def effectiveness(curriculum_id):
    """Computed-on-read first-attempt reviewed stats for one curriculum."""
    records = []
    for c in store.completions.values():
        a = store.assignments.get(c["assignment_id"])
        if (a is not None and a["curriculum_id"] == curriculum_id and c["attempt_no"] == 1
                and c["review_status"] in ("ACCEPTED", "REJECTED")):
            records.append(c)
    count = len(records)
    passed = sum(1 for c in records if c["review_status"] == "ACCEPTED")
    if count == 0:
        avg = Decimal("0.00")
    else:
        avg = round2(sum(c["score_pct"] for c in records) / Decimal(count))
    return {
        "curriculum_id": curriculum_id,
        "first_attempt_count": count,
        "first_attempt_pass_count": passed,
        "first_attempt_pass_rate_pct": float(pct2(passed, count)),
        "average_score_pct": float(avg),
    }


def recordkeeping_expiry(generated_at, regulator):
    return add_years(generated_at, regulator["recordkeeping_years"])
