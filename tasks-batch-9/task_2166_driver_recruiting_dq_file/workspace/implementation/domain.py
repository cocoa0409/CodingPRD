"""Derived-field reconciliation and cascades (PRD 2.11, 3.2-3.8)."""
from datetime import timedelta

import calc
from core import (DB, all_rows, d, dt, fail, fmt_date, fmt_instant, new_row, now,
                  today, touch)

APP_QUAL_TERMINAL = ("HIRED", "DISQUALIFIED")


# ---------------------------------------------------------------------------
# navigation helpers
# ---------------------------------------------------------------------------
def carrier_of(carrier_id):
    return DB["carriers"].get(carrier_id)


def applicant_of_application(application):
    return DB["driver_applicants"].get(application["applicant_id"])


def carrier_of_application(application):
    return DB["carriers"].get(application["carrier_id"])


def carrier_of_applicant(applicant):
    return DB["carriers"].get(applicant["carrier_id"])


def application_of(application_id):
    return DB["driver_applications"].get(application_id)


def file_of_application(application):
    return calc.file_of_application(application)


def application_of_file(dq_file):
    return DB["driver_applications"].get(dq_file["application_id"])


def apply_changes(row, changes):
    """Write changed values onto a row; touch it once if anything moved."""
    dirty = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            dirty = True
    if dirty:
        touch(row)
    return dirty


# ---------------------------------------------------------------------------
# Carrier posture
# ---------------------------------------------------------------------------
def recompute_carrier(carrier, force_touch=False):
    if carrier is None:
        return False
    changed = apply_changes(carrier, calc.carrier_posture(carrier))
    if force_touch:
        touch(carrier)
    return changed


def recompute_all_carriers():
    for carrier in all_rows("carriers"):
        recompute_carrier(carrier)


# ---------------------------------------------------------------------------
# Applicant derived fields
# ---------------------------------------------------------------------------
def applicant_derived(applicant):
    carrier = carrier_of_applicant(applicant)
    values = {}
    values.update(calc.cdl_downgrade_risk(applicant, carrier))
    values.update(calc.rehire_eligibility(applicant, carrier))
    return values


def recompute_applicant(applicant):
    if applicant is None:
        return False
    return apply_changes(applicant, applicant_derived(applicant))


def refresh_applicant_silent(applicant):
    """Recompute derived applicant fields for a read: no version bump."""
    if applicant is None:
        return
    for key, value in applicant_derived(applicant).items():
        applicant[key] = value


# ---------------------------------------------------------------------------
# DQ documents
# ---------------------------------------------------------------------------
def set_document(dq_file, doc_type, status, effective_on=None, expires_on=None,
                 source_ref=None, clear_effective=False):
    doc = calc.document_of(dq_file, doc_type)
    if doc is None:
        return None
    changes = {"status": status}
    if clear_effective:
        changes["effective_on"] = None
        changes["expires_on"] = None
    else:
        if effective_on is not None:
            changes["effective_on"] = effective_on
        if expires_on is not None:
            changes["expires_on"] = expires_on
    if source_ref is not None:
        changes["source_ref"] = source_ref
    apply_changes(doc, changes)
    return doc


# ---------------------------------------------------------------------------
# DQ file completeness / review schedule
# ---------------------------------------------------------------------------
def compute_file_status(dq_file, pct):
    current = dq_file["status"]
    if current == "ARCHIVED":
        return current
    if current in ("OPEN", "DEFICIENT") and pct == 100.00:
        return "COMPLETE"
    if current == "COMPLETE" and pct < 100.00:
        return "DEFICIENT"
    return current


def recompute_file(dq_file, force_touch=False):
    """Recompute completeness figures and the completeness posture."""
    if dq_file is None:
        return False
    result = calc.dq_completeness(dq_file, "pre_hire_provisional")
    new_status = compute_file_status(dq_file, result["completeness_pct"])
    old_status = dq_file["status"]
    changed = apply_changes(dq_file, {
        "completeness_pct": result["completeness_pct"],
        "deficiency_count": result["deficiency_count"],
        "total_weight": sum(x["weight"] for x in calc.documents_of(dq_file)),
        "status": new_status,
    })
    if force_touch:
        touch(dq_file)
    if new_status != old_status:
        application = application_of_file(dq_file)
        if application is not None:
            recompute_carrier(carrier_of_application(application))
            evaluate_qualified_join(application)
    return changed


def recompute_review(dq_file):
    application = application_of_file(dq_file)
    carrier = carrier_of_application(application) if application else None
    if carrier is None:
        return False
    return apply_changes(dq_file, calc.dq_review_schedule(dq_file, carrier))


def refresh_file_silent(dq_file):
    """Recompute the review schedule for a read: no version bump."""
    application = application_of_file(dq_file)
    carrier = carrier_of_application(application) if application else None
    if carrier is None:
        return
    for key, value in calc.dq_review_schedule(dq_file, carrier).items():
        dq_file[key] = value


# ---------------------------------------------------------------------------
# Employment coverage
# ---------------------------------------------------------------------------
def recompute_coverage(application):
    result = calc.employment_coverage(application, "strict_verified")
    return apply_changes(application, {
        "verified_coverage_days": result["verified_coverage_days"],
        "gap_days_unexplained": result["gap_days_unexplained"],
    })


# ---------------------------------------------------------------------------
# Application axis joins and cascades
# ---------------------------------------------------------------------------
def evaluate_screen_cleared(application):
    if application["screening_status"] != "SCREENING":
        return False
    checks = calc.rows_where("screening_checks", application_id=application["id"])
    for check_type in ("MVR", "PSP", "CRIMINAL"):
        matching = [c for c in checks if c["check_type"] == check_type]
        if len(matching) != 1 or matching[0]["status"] != "ADJUDICATED_PASS":
            return False
    queries = calc.rows_where("clearinghouse_queries", application_id=application["id"])
    if not any(q["status"] == "RESULT_CLEAR" for q in queries):
        return False
    orders = calc.rows_where("drug_test_orders", application_id=application["id"])
    if not any(o["test_type"] == "PRE_EMPLOYMENT"
               and o["status"] == "MRO_VERIFIED_NEGATIVE" for o in orders):
        return False
    apply_changes(application, {"screening_status": "SCREEN_CLEARED"})
    evaluate_qualified_join(application)
    return True


def evaluate_qualified_join(application):
    if application["qualification_status"] != "ORIENTATION_COMPLETE":
        return False
    if application["screening_status"] != "SCREEN_CLEARED":
        return False
    dq_file = file_of_application(application)
    if dq_file is None or dq_file["status"] != "COMPLETE":
        return False
    apply_changes(application, {"qualification_status": "QUALIFIED"})
    return True


def recompute_session_count(session):
    enrollments = calc.rows_where("orientation_enrollments", session_id=session["id"])
    count = len([e for e in enrollments
                 if e["status"] in ("RESERVED", "ATTENDED", "ABSENT")])
    return apply_changes(session, {"enrolled_count": count})


def cancel_enrollment(enrollment):
    apply_changes(enrollment, {"status": "CANCELLED"})
    session = DB["orientation_sessions"].get(enrollment["session_id"])
    if session is not None:
        recompute_session_count(session)
        touch(session)


def cascade_disqualify(application, reason):
    """qualification_status -> DISQUALIFIED plus its full fan-out."""
    if application["qualification_status"] in APP_QUAL_TERMINAL:
        return False
    apply_changes(application, {
        "qualification_status": "DISQUALIFIED",
        "disqualifying_reason": reason,
    })
    for enrollment in calc.rows_where("orientation_enrollments",
                                      application_id=application["id"]):
        if enrollment["status"] == "RESERVED":
            cancel_enrollment(enrollment)
    dq_file = file_of_application(application)
    if dq_file is not None and dq_file["status"] != "ARCHIVED":
        apply_changes(dq_file, {"status": "ARCHIVED"})
        touch(dq_file)
    # PRD 3.5: the final hop of the disqualification fan-out "recomputes the
    # carrier's filled_requisitions, deficiency_ratio and posture and increments
    # the carrier's version by one" — unconditionally, even when the recomputed
    # triple happens to land on the same values it already held.
    recompute_carrier(carrier_of_application(application), force_touch=True)
    return True


def cascade_screen_fail(application, reason):
    if application["screening_status"] != "SCREEN_FAILED":
        apply_changes(application, {"screening_status": "SCREEN_FAILED"})
    cascade_disqualify(application, reason)


# ---------------------------------------------------------------------------
# Blocking gates shared by several endpoints (PRD 3.5)
# ---------------------------------------------------------------------------
def clearinghouse_blocked(application):
    for q in calc.rows_where("clearinghouse_queries", application_id=application["id"]):
        if q["status"] in ("RESULT_PROHIBITED", "CONSENT_DENIED"):
            return True
        if (q["status"] == "RESULT_INFO_EXISTS" and q["query_type"] == "LIMITED"
                and q.get("follow_up_full_query_id") is None):
            return True
    return False


def has_negative_pre_employment(application):
    for o in calc.rows_where("drug_test_orders", application_id=application["id"]):
        if o["test_type"] == "PRE_EMPLOYMENT" and o["status"] == "MRO_VERIFIED_NEGATIVE":
            return True
    return False


# ---------------------------------------------------------------------------
# DQ file creation (submit is the sole producer)
# ---------------------------------------------------------------------------
def create_dq_file(application):
    dq_file = new_row("dq_files", {
        "application_id": application["id"],
        "status": "OPEN",
        "review_state": "NOT_DUE",
        "completeness_pct": 0.0,
        "deficiency_count": 10,
        "total_weight": calc.TOTAL_WEIGHT,
        "opened_on": fmt_date(today()),
        "last_annual_review_at": None,
        "next_review_due_on": None,
        "certified_by_user_id": None,
    })
    for doc_type in calc.DOC_TYPES:
        new_row("dq_documents", {
            "dq_file_id": dq_file["id"],
            "doc_type": doc_type,
            "weight": calc.DOC_WEIGHTS[doc_type],
            "status": "MISSING",
            "effective_on": None,
            "expires_on": None,
            "source_ref": None,
        })
    return dq_file


# ---------------------------------------------------------------------------
# Logical clock reconciliation sweep (PRD 2.5)
# ---------------------------------------------------------------------------
def clock_sweep():
    for dq_file in all_rows("dq_files"):
        if dq_file["status"] != "ARCHIVED":
            recompute_review(dq_file)
    for dq_file in all_rows("dq_files"):
        recompute_file(dq_file)
    for applicant in all_rows("driver_applicants"):
        recompute_applicant(applicant)
    recompute_all_carriers()
