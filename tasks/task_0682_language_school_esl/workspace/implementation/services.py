"""Business-logic services: state transitions, cascades, computed fields.

All cascades are atomic within the triggering request (PRD §2.6, consistency
model: immediate).
"""
import calculations
import errors
from clock import iso_millis


# ---------------------------------------------------------------------------
# Record construction helpers
# ---------------------------------------------------------------------------
def _touch(store, rec):
    """Refresh updated_at and bump version on a mutation (PRD §2.4)."""
    from db import now_iso

    rec["updated_at"] = now_iso(store)
    rec["version"] = rec["version"] + 1


def make_common(store):
    from db import now_iso

    ts = now_iso(store)
    return {
        "id": store.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def make_append_only(store):
    from db import now_iso

    return {
        "id": store.new_id(),
        "created_at": now_iso(store),
        "_seq": store.next_seq(),
    }


# ---------------------------------------------------------------------------
# Compliance events (append-only audit log)
# ---------------------------------------------------------------------------
def append_compliance_event(store, student, event_type, prior_status, new_status, reason):
    ev = make_append_only(store)
    ev.update({
        "student_id": student["id"],
        "event_type": event_type,
        "prior_status": prior_status,
        "new_status": new_status,
        "reason": reason,
        "recorded_at": iso_millis(store.clock.now()),
    })
    store.compliance_events[ev["id"]] = ev
    return ev


# ---------------------------------------------------------------------------
# Computed-field recomputation for attendance
# ---------------------------------------------------------------------------
def recompute_attendance(store, enrollment):
    records = [a for a in store.attendance_records.values() if a["enrollment_id"] == enrollment["id"]]
    attended = sum(1 for a in records if a["status"] == "PRESENT")
    elapsed = len(records)
    enrollment["sessions_attended"] = attended
    enrollment["sessions_elapsed"] = elapsed
    if elapsed == 0:
        enrollment["attendance_rate"] = 1.0
    else:
        enrollment["attendance_rate"] = attended / elapsed


# ---------------------------------------------------------------------------
# Tuition pinning at the moment of ENROLLED
# ---------------------------------------------------------------------------
def compute_tuition_for_enrollment(store, enrollment, student, cohort):
    active_fees = [
        a["fee_cents"]
        for a in store.add_ons.values()
        if a["enrollment_id"] == enrollment["id"] and a["status"] == "ACTIVE"
    ]
    discount_tier = None
    if student["corporate_contract_id"]:
        contract = store.corporate_contracts.get(student["corporate_contract_id"])
        if contract:
            discount_tier = contract["discount_tier"]
    return calculations.tuition_invoice(cohort["base_tuition_cents"], active_fees, discount_tier)


# ---------------------------------------------------------------------------
# Cohort status helpers
# ---------------------------------------------------------------------------
def _set_cohort_status(cohort):
    if cohort["seats_taken"] >= cohort["capacity"]:
        cohort["status"] = "FULL"
    else:
        cohort["status"] = "OPEN"


def _set_contract_status(contract):
    # Only ACTIVE<->EXHAUSTED auto-flip here; CLOSED is terminal and set elsewhere.
    if contract["status"] == "CLOSED":
        return
    if contract["seats_consumed"] >= contract["contracted_seats"]:
        contract["status"] = "EXHAUSTED"
    else:
        contract["status"] = "ACTIVE"


# ---------------------------------------------------------------------------
# Seat acquisition / release (cohort + contract), with version bumps
# ---------------------------------------------------------------------------
def acquire_seats(store, enrollment, student, cohort):
    cohort["seats_taken"] += 1
    _set_cohort_status(cohort)
    _touch(store, cohort)
    if student["corporate_contract_id"]:
        contract = store.corporate_contracts.get(student["corporate_contract_id"])
        if contract:
            contract["seats_consumed"] += 1
            _set_contract_status(contract)
            _touch(store, contract)


def release_seats(store, enrollment, student, cohort):
    if cohort["seats_taken"] > 0:
        cohort["seats_taken"] -= 1
    _set_cohort_status(cohort)
    _touch(store, cohort)
    if student["corporate_contract_id"]:
        contract = store.corporate_contracts.get(student["corporate_contract_id"])
        if contract:
            if contract["seats_consumed"] > 0:
                contract["seats_consumed"] -= 1
            _set_contract_status(contract)
            _touch(store, contract)


# ---------------------------------------------------------------------------
# Move an enrollment into ENROLLED (fresh confirm or waitlist promotion)
# ---------------------------------------------------------------------------
def enter_enrolled(store, enrollment, student, cohort):
    enrollment["status"] = "ENROLLED"
    enrollment["enrolled_at"] = iso_millis(store.clock.now())
    enrollment["tuition_invoice_cents"] = compute_tuition_for_enrollment(
        store, enrollment, student, cohort
    )
    acquire_seats(store, enrollment, student, cohort)
    _touch(store, enrollment)


# ---------------------------------------------------------------------------
# Waitlist promotion (shared tail of withdraw / terminate / complete)
# ---------------------------------------------------------------------------
def promote_waitlist(store, cohort):
    """Promote the earliest WAITLISTED enrollment on the cohort if a seat is free.

    PRD §3.7: earliest by smallest created_at. If the promoted student is
    international, promotion proceeds only while visa_status is INITIAL or ACTIVE.
    """
    if cohort["seats_taken"] >= cohort["capacity"]:
        return
    waitlisted = [
        e for e in store.enrollments.values()
        if e["cohort_id"] == cohort["id"] and e["status"] == "WAITLISTED"
    ]
    if not waitlisted:
        return
    waitlisted.sort(key=lambda e: (e["created_at"], e["_seq"]))
    candidate = waitlisted[0]
    student = store.students.get(candidate["student_id"])
    if student["is_international"] and student["visa_status"] not in ("INITIAL", "ACTIVE"):
        # Promotion blocked for a non-compliant international student.
        return
    enter_enrolled(store, candidate, student, cohort)


# ---------------------------------------------------------------------------
# Certification rollup for a student (PRD §3.7)
# ---------------------------------------------------------------------------
def recompute_certification(store, student):
    completed = [
        e for e in store.enrollments.values()
        if e["student_id"] == student["id"] and e["status"] == "COMPLETED"
    ]
    scores = [e["completion_score"] for e in completed if e["completion_score"] is not None]
    status, final = calculations.certification_rollup(scores)
    student["certification_status"] = status
    student["final_progress_score"] = final
    _touch(store, student)


# ---------------------------------------------------------------------------
# Full course of study (PRD §3.8)
# ---------------------------------------------------------------------------
def meets_full_course(store, student):
    total = 0
    for e in store.enrollments.values():
        if e["student_id"] == student["id"] and e["status"] == "ENROLLED":
            cohort = store.cohorts.get(e["cohort_id"])
            if cohort:
                total += cohort["weekly_hours"]
    return total >= student["i20_required_weekly_hours"]


# ---------------------------------------------------------------------------
# Terminate a single ENROLLED enrollment with a reason (used by cascades & by
# the direct terminate endpoint).
# ---------------------------------------------------------------------------
def terminate_enrollment(store, enrollment, reason, cascade_visa):
    """ENROLLED -> TERMINATED.

    Releases cohort/contract seats, promotes the waitlist. When reason is
    VISA_NONCOMPLIANCE and cascade_visa is True, also drives the student's visa
    termination + certification void (PRD §3.7). The student-visa-termination
    endpoint sets cascade_visa=False because it already owns the visa transition.
    """
    student = store.students.get(enrollment["student_id"])
    cohort = store.cohorts.get(enrollment["cohort_id"])

    enrollment["status"] = "TERMINATED"
    enrollment["termination_reason"] = reason
    enrollment["refund_cents"] = 0
    _touch(store, enrollment)

    release_seats(store, enrollment, student, cohort)
    promote_waitlist(store, cohort)

    if cascade_visa and reason == "VISA_NONCOMPLIANCE":
        prior = student["visa_status"]
        student["visa_status"] = "TERMINATED"
        if student["certification_status"] in ("PROVISIONAL", "CERTIFIED"):
            student["certification_status"] = "VOIDED"
        _touch(store, student)
        append_compliance_event(
            store, student, "I20_TERMINATED", prior, "TERMINATED", None
        )
