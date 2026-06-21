"""Serialize internal records to API output.

Internal records are stored already in API shape, so serialization is a shallow
copy. Field lists are defined explicitly per entity to guarantee the exact
surface (and ordering) the PRD describes.
"""

COMMON = ["id", "created_at", "updated_at", "version"]
APPEND_ONLY = ["id", "created_at"]

EMPLOYEE = ["email", "full_name", "department", "job_role", "manager_id",
            "total_ceu_earned", "compliant_required_count", "compliance_score",
            "status"]
COURSE = ["code", "title", "content_type", "passing_score", "max_attempts",
          "ceu_credits", "grading_policy", "ceu_policy", "is_recurring",
          "recurrence_months", "status"]
COURSE_PREREQUISITE = ["course_id", "prerequisite_course_id"]
LEARNING_PATH = ["code", "title", "enforce_sequence", "status"]
PATH_STEP = ["learning_path_id", "course_id", "sequence_index", "is_mandatory", "weight"]
ASSIGNMENT_RULE = ["target_department", "target_job_role", "course_id",
                   "learning_path_id", "due_in_days", "effective_from",
                   "effective_to", "status"]
ENROLLMENT = ["employee_id", "course_id", "path_enrollment_id", "assignment_rule_id",
              "is_required", "due_date", "best_score", "latest_score",
              "final_grade", "attempts_used", "cycle_index", "escalation_tier",
              "certificate_id", "status"]
QUIZ_ATTEMPT = ["enrollment_id", "cycle_index", "attempt_number", "score", "passed"]
PATH_ENROLLMENT = ["employee_id", "learning_path_id", "assignment_rule_id",
                   "due_date", "progress_pct", "status"]
CERTIFICATE = ["employee_id", "course_id", "enrollment_id", "ceu_credited",
               "issued_at", "expires_at", "status"]
TRACKING_SESSION = ["enrollment_id", "content_type", "started_at", "terminated_at",
                    "lesson_status", "progress_pct", "reported_score", "status"]
ESCALATION_EVENT = ["enrollment_id", "employee_id", "manager_id", "tier",
                    "days_overdue", "acknowledged"]
CLOCK = ["current_utc"]


def _ser(record, fields, common_fields=True):
    out = {"id": record["id"]}
    for f in fields:
        out[f] = record.get(f)
    out["created_at"] = record.get("created_at")
    if common_fields:
        out["updated_at"] = record.get("updated_at")
        out["version"] = record.get("version")
    return out


def employee(r):
    return _ser(r, EMPLOYEE)


def course(r):
    return _ser(r, COURSE)


def course_prerequisite(r):
    return _ser(r, COURSE_PREREQUISITE)


def learning_path(r):
    return _ser(r, LEARNING_PATH)


def path_step(r):
    return _ser(r, PATH_STEP)


def assignment_rule(r):
    return _ser(r, ASSIGNMENT_RULE)


def enrollment(r):
    out = _ser(r, ENROLLMENT)
    # escalation_tier is a derived field: always reflect current days_overdue
    from services import calculations as _calc
    out["escalation_tier"] = _calc.compute_escalation_tier(r)
    return out


def quiz_attempt(r):
    return _ser(r, QUIZ_ATTEMPT, common_fields=False)


def path_enrollment(r):
    return _ser(r, PATH_ENROLLMENT)


def certificate(r):
    return _ser(r, CERTIFICATE)


def tracking_session(r):
    return _ser(r, TRACKING_SESSION)


def escalation_event(r):
    return _ser(r, ESCALATION_EVENT, common_fields=False)


def clock(r):
    return _ser(r, CLOCK)
