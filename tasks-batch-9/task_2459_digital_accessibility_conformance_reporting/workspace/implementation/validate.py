"""Request-shape validation (PRD 2.7 step 6) and enumerations (PRD 2.10)."""
from flask import request

from db import parse_date, parse_datetime, db
from errors import ApiError, bad_request

# ------------------------------------------------------------------ enums ---
STANDARD_CODES = ["WCAG_2_1", "WCAG_2_2", "EN_301_549", "SECTION_508_SW"]
SURFACE_SCOPES = ["WEB", "SOFTWARE", "BOTH"]
SURFACES = ["WEB", "SOFTWARE"]
LEVELS = ["A", "AA", "AAA"]
DISABILITY_CATEGORIES = ["VISION", "HEARING", "MOTOR", "COGNITIVE"]
COMPONENT_TYPES = ["WEB_UI", "DESKTOP_APP", "MOBILE_APP", "AUTHORING_TOOL",
                   "DOCUMENTATION"]
ASSESSMENT_SCOPES = ["FULL", "SAMPLED", "EXCLUDED"]
AT_PROFILES = ["SCREEN_READER", "KEYBOARD", "MAGNIFICATION"]
OS_PLATFORMS = ["WINDOWS", "MACOS", "LINUX", "ANDROID", "IOS"]
METHODS = ["AUTOMATED", "MANUAL"]
SUPPORT_LEVELS = ["SUPPORTS", "PARTIALLY_SUPPORTS", "DOES_NOT_SUPPORT",
                  "NOT_APPLICABLE"]
SEVERITIES = ["BLOCKER", "SERIOUS", "MODERATE", "MINOR"]
PUBLISH_INTENTS = ["INCLUDED", "EXCLUDED"]
PUBLICATION_CHANNELS = ["CUSTOMER_TRUST_PORTAL", "PROCUREMENT_PACKET",
                        "PUBLIC_WEBSITE"]
QUESTIONNAIRE_KINDS = ["VPAT_ACR", "SECTION_508_CHECKLIST", "EN_301_549_ANNEX",
                       "CUSTOM_RFP"]
COMPLAINT_CHANNELS = ["EMAIL", "PHONE", "WEB_FORM", "REGULATOR_REFERRAL"]
CLOSURE_OUTCOMES = ["REMEDIATION_SCHEDULED", "ACCOMMODATION_PROVIDED",
                    "ACCOMMODATION_DENIED", "NOT_A_DEFECT"]
COMPLAINT_ROUTES = ["REMEDIATION", "ACCOMMODATION"]
REVIEW_DECISIONS = ["PASS", "BLOCK"]

ASSESSMENT_STATES = ["PLANNED", "IN_TESTING", "COMPLETE"]
DESIGN_REVIEW_STATES = ["NOT_REVIEWED", "REVIEWED_PASS", "REVIEWED_BLOCKED"]
RUN_STATUSES = ["SCHEDULED", "COMPLETED", "VOID"]
ATTESTATION_STATES = ["DRAFT", "ATTESTED", "NEEDS_REVALIDATION", "SUPERSEDED"]
REPORT_STATES = ["DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED",
                 "PUBLISHED", "SUPERSEDED", "WITHDRAWN"]
ISSUE_STATES = ["OPEN", "TRIAGED", "DEFERRED", "COMMITTED", "PUBLISHED_COMMITTED",
                "RESOLVED"]
REVIEW_STATUSES = ["DRAFT", "SUBMITTED", "ATTESTED"]
ACCURACY_STATUSES = ["CURRENT", "STALE", "CORRECTION_REQUIRED"]
COMPLAINT_STATES = ["NEW", "TRIAGED", "LINKED", "ACCOMMODATED", "CLOSED"]
POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]
READINESS = ["NOT_READY", "READY"]

LEVEL_RANK = {"A": 1, "AA": 2, "AAA": 3}


# ------------------------------------------------------------------- body ---
def body():
    payload = request.get_json(silent=True)
    if payload is None:
        if request.get_data(cache=True):
            raise bad_request("body is not valid JSON")
        return {}
    if not isinstance(payload, dict):
        raise bad_request("body must be a JSON object")
    return payload


def _missing(data, key, required):
    if key not in data or data[key] is None:
        if required:
            raise bad_request("missing required field '%s'" % key)
        return True
    return False


def v_str(data, key, required=False, min_len=None, max_len=None, default=None):
    if _missing(data, key, required):
        return default
    value = data[key]
    if not isinstance(value, str):
        raise bad_request("'%s' must be a string" % key)
    if min_len is not None and len(value) < min_len:
        raise bad_request("'%s' must be at least %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad_request("'%s' must be at most %d characters" % (key, max_len))
    return value


def v_int(data, key, required=False, min_value=None, max_value=None, default=None):
    if _missing(data, key, required):
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("'%s' must be an integer" % key)
    if min_value is not None and value < min_value:
        raise bad_request("'%s' must be >= %s" % (key, min_value))
    if max_value is not None and value > max_value:
        raise bad_request("'%s' must be <= %s" % (key, max_value))
    return value


def v_bool(data, key, required=False, default=None):
    if _missing(data, key, required):
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise bad_request("'%s' must be a boolean" % key)
    return value


def v_enum(data, key, allowed, required=False, default=None):
    if _missing(data, key, required):
        return default
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("'%s' must be one of %s" % (key, ", ".join(allowed)))
    return value


def v_enum_array(data, key, allowed, required=False, default=None):
    if _missing(data, key, required):
        return default
    value = data[key]
    if not isinstance(value, list) or not value:
        raise bad_request("'%s' must be a non-empty array" % key)
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise bad_request("'%s' members must be one of %s"
                              % (key, ", ".join(allowed)))
        if item in seen:
            raise bad_request("'%s' must not contain duplicates" % key)
        seen.add(item)
    return list(value)


def v_date(data, key, required=False, default=None):
    """Returns (raw_string, date) or (default, None)."""
    if _missing(data, key, required):
        return default, None
    value = data[key]
    parsed = parse_date(value) if isinstance(value, str) else None
    if parsed is None:
        raise bad_request("'%s' must be a YYYY-MM-DD date" % key)
    return value, parsed


def v_datetime(data, key, required=False, default=None):
    """Returns (raw_string, datetime) or (default, None)."""
    if _missing(data, key, required):
        return default, None
    value = data[key]
    parsed = parse_datetime(value) if isinstance(value, str) else None
    if parsed is None:
        raise bad_request("'%s' must be an ISO 8601 timestamp" % key)
    return value, parsed


# ------------------------------------------------------------- pagination ---
def pagination():
    """limit default 10 (1..100), offset default 0 (>=0) — PRD 2.3."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise bad_request("'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise bad_request("'limit' must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise bad_request("'offset' must be an integer")
        if offset < 0:
            raise bad_request("'offset' must be >= 0")
    return limit, offset


def q_enum(key, allowed):
    if key not in request.args:
        return None
    value = request.args.get(key)
    if value not in allowed:
        raise bad_request("'%s' must be one of %s" % (key, ", ".join(allowed)))
    return value


def q_str(key):
    if key not in request.args:
        return None
    return request.args.get(key)


def q_bool(key):
    if key not in request.args:
        return None
    value = (request.args.get(key) or "").strip().lower()
    if value in ("true", "1"):
        return True
    if value in ("false", "0"):
        return False
    raise bad_request("'%s' must be a boolean" % key)


# ---------------------------------------------- foreign key resolution ------
def _fk(collection, value, error_id):
    """Step 5: body reference existence.  Absent/ill-typed values defer to shape."""
    if not isinstance(value, str):
        return None
    row = collection.get(value)
    if row is None:
        raise ApiError(error_id)
    return row


def fk_standard(value):
    return _fk(db.standards, value, "ERR_STANDARD_NOT_FOUND")


def fk_criterion(value):
    return _fk(db.criteria, value, "ERR_CRITERION_NOT_FOUND")


def fk_product(value):
    return _fk(db.products, value, "ERR_PRODUCT_NOT_FOUND")


def fk_component(value):
    return _fk(db.components, value, "ERR_COMPONENT_NOT_FOUND")


def fk_environment(value):
    return _fk(db.environments, value, "ERR_ENVIRONMENT_NOT_FOUND")


def fk_run(value):
    return _fk(db.runs, value, "ERR_RUN_NOT_FOUND")


def fk_report(value):
    return _fk(db.reports, value, "ERR_REPORT_NOT_FOUND")


def fk_train(value):
    return _fk(db.trains, value, "ERR_RELEASE_TRAIN_NOT_FOUND")


def fk_issue(value):
    return _fk(db.issues, value, "ERR_KNOWN_ISSUE_NOT_FOUND")


# ----------------------------------------------- path resolution (step 4) ---
def path_standard(standard_id):
    row = db.standards.get(standard_id)
    if row is None:
        raise ApiError("ERR_STANDARD_NOT_FOUND", "Standard %s not found" % standard_id)
    return row


def path_criterion(criterion_id):
    row = db.criteria.get(criterion_id)
    if row is None:
        raise ApiError("ERR_CRITERION_NOT_FOUND",
                       "Success criterion %s not found" % criterion_id)
    return row


def path_product(product_id):
    row = db.products.get(product_id)
    if row is None:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", "Product %s not found" % product_id)
    return row


def path_component(component_id):
    row = db.components.get(component_id)
    if row is None:
        raise ApiError("ERR_COMPONENT_NOT_FOUND",
                       "Product component %s not found" % component_id)
    return row


def path_environment(environment_id):
    row = db.environments.get(environment_id)
    if row is None:
        raise ApiError("ERR_ENVIRONMENT_NOT_FOUND",
                       "Test environment %s not found" % environment_id)
    return row


def path_run(run_id):
    row = db.runs.get(run_id)
    if row is None:
        raise ApiError("ERR_RUN_NOT_FOUND", "Assessment run %s not found" % run_id)
    return row


def path_assessment(assessment_id):
    row = db.assessments.get(assessment_id)
    if row is None:
        raise ApiError("ERR_ASSESSMENT_NOT_FOUND",
                       "Criterion assessment %s not found" % assessment_id)
    return row


def path_report(report_id):
    row = db.reports.get(report_id)
    if row is None:
        raise ApiError("ERR_REPORT_NOT_FOUND",
                       "Conformance report %s not found" % report_id)
    return row


def path_train(train_id):
    row = db.trains.get(train_id)
    if row is None:
        raise ApiError("ERR_RELEASE_TRAIN_NOT_FOUND",
                       "Release train %s not found" % train_id)
    return row


def path_issue(issue_id):
    row = db.issues.get(issue_id)
    if row is None:
        raise ApiError("ERR_KNOWN_ISSUE_NOT_FOUND",
                       "Known issue %s not found" % issue_id)
    return row


def path_questionnaire(questionnaire_id):
    row = db.questionnaires.get(questionnaire_id)
    if row is None:
        raise ApiError("ERR_QUESTIONNAIRE_NOT_FOUND",
                       "Questionnaire response %s not found" % questionnaire_id)
    return row


def path_complaint(complaint_id):
    row = db.complaints.get(complaint_id)
    if row is None:
        raise ApiError("ERR_COMPLAINT_NOT_FOUND", "Complaint %s not found" % complaint_id)
    return row


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
