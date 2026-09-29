"""Lookup helpers.  Path/body existence checks (validation priorities 4-5)."""
from db import db
from errors import ApiError


def _get(collection, row_id, error_id):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id, "Referenced resource %r was not found" % (row_id,))
    return row


def term_or_404(term_id):
    return _get(db.academic_terms, term_id, "ERR_TERM_NOT_FOUND")


def department_or_404(department_id):
    return _get(db.departments, department_id, "ERR_DEPARTMENT_NOT_FOUND")


def student_or_404(student_id):
    return _get(db.students, student_id, "ERR_STUDENT_NOT_FOUND")


def source_or_404(source_id):
    return _get(db.funding_sources, source_id, "ERR_FUNDING_SOURCE_NOT_FOUND")


def appointment_or_404(appointment_id):
    return _get(db.appointments, appointment_id, "ERR_APPOINTMENT_NOT_FOUND")


def allocation_or_404(allocation_id):
    return _get(db.funding_allocations, allocation_id, "ERR_ALLOCATION_NOT_FOUND")


def disbursement_or_404(disbursement_id):
    return _get(db.stipend_disbursements, disbursement_id, "ERR_DISBURSEMENT_NOT_FOUND")


def renewal_or_404(renewal_id):
    return _get(db.renewal_decisions, renewal_id, "ERR_RENEWAL_DECISION_NOT_FOUND")


def assessment_or_404(assessment_id):
    return _get(db.tax_assessments, assessment_id, "ERR_ASSESSMENT_NOT_FOUND")


# ---------------------------------------------------------------------------
# collection scans
# ---------------------------------------------------------------------------
def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def policies_of_term(term_id):
    return [p for p in db.stipend_policies.values() if p["term_id"] == term_id]


def pay_periods_of_term(term_id):
    return [p for p in db.pay_periods.values() if p["term_id"] == term_id]


def appointments_of_term(term_id):
    return [a for a in db.appointments.values() if a["term_id"] == term_id]


def allocations_of_appointment(appointment_id):
    return [a for a in db.funding_allocations.values()
            if a["appointment_id"] == appointment_id]


def active_allocations(appointment_id, statuses=("PROPOSED", "COMMITTED")):
    return [a for a in allocations_of_appointment(appointment_id)
            if a["status"] in statuses]


def disbursements_of_appointment(appointment_id):
    return [d for d in db.stipend_disbursements.values()
            if d["appointment_id"] == appointment_id]


def disbursements_of_term(term_id):
    period_ids = set(p["id"] for p in pay_periods_of_term(term_id))
    return [d for d in db.stipend_disbursements.values()
            if d["pay_period_id"] in period_ids]


def assessments_of_term(term_id):
    return [a for a in db.tax_assessments.values() if a["term_id"] == term_id]


def find_policy(term_id, assistantship_type, degree_level):
    for policy in db.stipend_policies.values():
        if (policy["term_id"] == term_id
                and policy["assistantship_type"] == assistantship_type
                and policy["degree_level"] == degree_level):
            return policy
    return None


def term_exempt_cap(term_id):
    """The tuition_tax_exempt_cap_cents declared by the term's policies."""
    policies = by_created(policies_of_term(term_id))
    if policies:
        return policies[0]["tuition_tax_exempt_cap_cents"]
    return 525000


def renewals_of_appointment(appointment_id):
    return [r for r in db.renewal_decisions.values()
            if r["appointment_id"] == appointment_id]
