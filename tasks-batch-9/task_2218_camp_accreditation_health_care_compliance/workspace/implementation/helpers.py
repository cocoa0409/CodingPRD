"""Existence resolution, ownership scope and collection filtering."""

import db
import domain
import response
import validators
from errors import api_error
from middleware import CAMP_SCOPED_ROLES


# ------------------------------------------------------------- resolvers ----
def _resolve(collection, identifier, error_id):
    row = collection.get(identifier) if isinstance(identifier, str) else None
    if row is None:
        raise api_error(error_id, "The referenced resource does not exist.")
    return row


def camp_or_404(camp_id):
    return _resolve(db.camps, camp_id, "ERR_CAMP_NOT_FOUND")


def set_or_404(set_id):
    return _resolve(db.standards_sets, set_id, "ERR_STANDARDS_SET_NOT_FOUND")


def standard_or_404(standard_id):
    return _resolve(db.standards, standard_id, "ERR_STANDARD_NOT_FOUND")


def cycle_or_404(cycle_id):
    return _resolve(db.cycles, cycle_id, "ERR_CYCLE_NOT_FOUND")


def evaluation_or_404(evaluation_id):
    return _resolve(db.evaluations, evaluation_id, "ERR_EVALUATION_NOT_FOUND")


def plan_or_404(plan_id):
    return _resolve(db.written_plans, plan_id, "ERR_WRITTEN_PLAN_NOT_FOUND")


def visitor_or_404(visitor_id):
    return _resolve(db.visitors, visitor_id, "ERR_VISITOR_NOT_FOUND")


def visit_or_404(visit_id):
    return _resolve(db.visits, visit_id, "ERR_VISIT_NOT_FOUND")


def assignment_or_404(assignment_id):
    return _resolve(db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")


def deficiency_or_404(deficiency_id):
    return _resolve(db.deficiencies, deficiency_id, "ERR_DEFICIENCY_NOT_FOUND")


def med_record_or_404(record_id):
    return _resolve(db.med_records, record_id, "ERR_MED_RECORD_NOT_FOUND")


def report_or_404(report_id):
    return _resolve(db.annual_reports, report_id, "ERR_ANNUAL_REPORT_NOT_FOUND")


def disclosure_or_404(disclosure_id):
    return _resolve(db.disclosures, disclosure_id, "ERR_DISCLOSURE_NOT_FOUND")


# ----------------------------------------------------------------- scope ----
def scope(ident, camp_id):
    if ident.role in CAMP_SCOPED_ROLES and ident.user_id != camp_id:
        raise api_error(
            "ERR_FORBIDDEN_SCOPE",
            "The acting principal does not own the target resource.",
        )


def camp_id_of_cycle(cycle):
    return cycle["camp_id"]


def camp_id_of_evaluation(evaluation):
    cycle = db.cycles.get(evaluation["cycle_id"])
    return cycle["camp_id"] if cycle else None


def camp_id_of_visit(visit):
    cycle = db.cycles.get(visit["cycle_id"])
    return cycle["camp_id"] if cycle else None


def camp_id_of_disclosure(disclosure):
    report = db.annual_reports.get(disclosure["annual_report_id"])
    return report["camp_id"] if report else None


# ------------------------------------------------------------- serialize ----
def public(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]


# --------------------------------------------------------------- filters ----
STR = "str"
INT = "int"
BOOL = "bool"


def collection_response(collection, spec):
    """Apply equality filters, order by created_at ascending and paginate."""
    limit, offset = validators.pagination()
    filters = {}
    for field, kind in spec.items():
        if kind is INT:
            value = validators.q_int(field)
        elif kind is BOOL:
            value = validators.q_bool(field)
        elif isinstance(kind, tuple):
            value = validators.q_enum(field, kind)
        else:
            value = validators.q_str(field)
        if value is not None:
            filters[field] = value

    def matches(row):
        for field, value in filters.items():
            if row.get(field) != value:
                return False
        return True

    rows = db.ordered(collection, matches)
    page, total = response.paginate(rows, limit, offset)
    return response.listing(public_list(page), limit, offset, total)


CAMP_FILTERS = {
    "state_code": STR,
    "camp_type": domain.CAMP_TYPES,
    "accreditation_status": domain.ACCREDITATION_STATUSES,
    "state_license_status": domain.LICENSE_STATUSES,
    "compliance_posture": domain.POSTURES,
}
SET_FILTERS = {"status": domain.SET_STATUSES, "effective_year": INT}
STANDARD_FILTERS = {
    "standards_set_id": STR,
    "domain": domain.DOMAINS,
    "mandatory": BOOL,
    "requires_state_licensed": BOOL,
}
CYCLE_FILTERS = {
    "camp_id": STR,
    "standards_set_id": STR,
    "status": domain.CYCLE_STATUSES,
    "cycle_year": INT,
    "decision_level": domain.DECISION_LEVELS,
}
EVALUATION_FILTERS = {
    "cycle_id": STR,
    "standard_id": STR,
    "visit_id": STR,
    "scored_by_visitor_id": STR,
    "written_plan_id": STR,
    "applicable": BOOL,
    "mandatory": BOOL,
    "self_status": domain.SELF_STATUSES,
    "visit_status": domain.VISIT_SCORE_STATUSES,
    "self_score": domain.SELF_SCORES,
    "visitor_score": domain.VISITOR_SCORES,
}
PLAN_FILTERS = {
    "camp_id": STR,
    "supersedes_plan_id": STR,
    "plan_type": domain.PLAN_TYPES,
    "status": domain.PLAN_STATUSES,
    "physician_reviewed": BOOL,
}
VISITOR_FILTERS = {
    "employer_camp_id": STR,
    "home_state_code": STR,
    "status": domain.VISITOR_STATUSES,
    "trained_through_year": INT,
}
VISIT_FILTERS = {
    "cycle_id": STR,
    "lead_visitor_id": STR,
    "status": domain.VISIT_STATUSES,
}
ASSIGNMENT_FILTERS = {
    "visit_id": STR,
    "visitor_id": STR,
    "team_role": domain.TEAM_ROLES,
    "status": domain.ASSIGNMENT_STATUSES,
}
DEFICIENCY_FILTERS = {
    "visit_id": STR,
    "standard_id": STR,
    "status": domain.DEFICIENCY_STATUSES,
    "severity": domain.SEVERITIES,
}
MED_FILTERS = {
    "camp_id": STR,
    "camper_reference": STR,
    "medication_class": domain.MEDICATION_CLASSES,
    "record_status": domain.RECORD_STATUSES,
    "compliance_flag": domain.COMPLIANCE_FLAGS,
}
REPORT_FILTERS = {"camp_id": STR, "report_year": INT, "status": domain.REPORT_STATUSES}
DISCLOSURE_FILTERS = {
    "annual_report_id": STR,
    "incident_type": domain.INCIDENT_TYPES,
    "status": domain.DISCLOSURE_STATUSES,
    "state_notification_required": BOOL,
}
