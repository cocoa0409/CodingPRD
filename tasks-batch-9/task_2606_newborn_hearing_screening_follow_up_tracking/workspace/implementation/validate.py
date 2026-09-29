"""Request-schema validation helpers (priority 3: ERR_INVALID_REQUEST)."""
from flask import request

import db
from errors import ApiError

_MISSING = object()

# --- declared enum sets -----------------------------------------------------
FACILITY_TYPES = ("BIRTH_HOSPITAL", "BIRTHING_CENTER", "MIDWIFE_PRACTICE",
                  "AUDIOLOGY_CLINIC", "EI_PROGRAM")
REGION_CODES = ("R1", "R2", "R3", "R4")
PROVIDER_TYPES = ("SCREENER", "AUDIOLOGIST", "NAVIGATOR", "EI_COORDINATOR")
LANGUAGES = ("EN", "ES", "ZH", "VI", "AR", "ASL", "OTHER")
CREDENTIAL_STATUSES = ("ACTIVE", "LAPSED", "SUSPENDED")
BIRTH_SETTINGS = ("INPATIENT", "BIRTHING_CENTER", "OUT_OF_HOSPITAL", "HOME_BIRTH")
CONSENT_STATUSES = ("PENDING", "GRANTED", "REFUSED")
SCREENING_STATUSES = ("NOT_SCREENED", "PASSED", "REFERRED", "DIAGNOSTIC_IN_PROGRESS",
                      "DIAGNOSED_NO_LOSS", "DIAGNOSED_LOSS", "LOST_TO_FOLLOW_UP")
INTERVENTION_STATUSES = ("NOT_APPLICABLE", "REFERRAL_DUE", "REFERRED", "ENROLLED",
                         "DECLINED")
PRIORITY_BANDS = ("LOW", "ELEVATED", "HIGH", "CRITICAL")
ENCOUNTER_TYPES = ("BIRTH_ADMISSION", "OUTPATIENT_RESCREEN", "HOME_VISIT", "SURVEILLANCE")
SCREEN_METHODS = ("OAE", "AABR")
EAR_RESULTS = ("PASS", "REFER", "NOT_TESTED")
OVERALL_RESULTS = ("PASS", "REFER", "INCOMPLETE")
EPISODE_TYPES = ("INITIAL_SCREEN", "RESCREEN", "DIAGNOSTIC")
EPISODE_STATUSES = ("PENDING_SCHEDULING", "SCHEDULED", "ESCALATED_DIAGNOSTIC",
                    "LOST_TO_FOLLOW_UP", "RESOLVED_PASS", "RESOLVED_DIAGNOSED",
                    "RESOLVED_NO_LOSS", "CLOSED_DECLINED", "SUPERSEDED")
OWNER_SCOPES = ("FACILITY", "STATE_PROGRAM")
CLOSURE_REASONS = ("RESCREEN_PASSED", "DIAGNOSIS_CONFIRMED", "DIAGNOSIS_NO_LOSS",
                   "FAMILY_DECLINED", "MOVED_OUT_OF_STATE", "SUPERSEDED",
                   "LOST_TO_FOLLOW_UP")
ADMIN_CLOSURE_REASONS = ("FAMILY_DECLINED", "MOVED_OUT_OF_STATE")
SLOT_TYPES = ("RESCREEN", "DIAGNOSTIC")
SLOT_STATUSES = ("OPEN", "FULL")
APPOINTMENT_STATUSES = ("BOOKED", "ATTENDED", "NO_SHOW", "CANCELLED")
APPOINTMENT_DISPOSITIONS = ("NO_SHOW", "CANCELLED")
EVALUATION_METHODS = ("DIAGNOSTIC_ABR", "ASSR", "BEHAVIORAL")
EVALUATION_OUTCOMES = ("NO_LOSS", "UNILATERAL_LOSS", "BILATERAL_LOSS")
EVALUATION_STATUSES = ("DRAFT", "PENDING_ATTESTATION", "ATTESTED", "FINALIZED_LOSS",
                       "FINALIZED_NO_LOSS")
ATTEST_DECISIONS = ("ACCEPT", "RETURN")
REFERRAL_STATUSES = ("PENDING", "ACCEPTED", "ENROLLED", "DECLINED_BY_FAMILY",
                     "REJECTED_BY_PROGRAM")
REFERRAL_DECISIONS = ("ACCEPT", "REJECT", "FAMILY_DECLINED")
RISK_FACTOR_CODES = ("CMV", "FAMILY_HISTORY", "CRANIOFACIAL_ANOMALY", "SYNDROME",
                     "BACTERIAL_MENINGITIS", "ECMO", "HYPERBILIRUBINEMIA_EXCHANGE",
                     "OTOTOXIC_MEDICATION", "NICU_5_PLUS_DAYS")
RISK_SOURCES = ("BIRTH_FACILITY", "AUDIOLOGY", "REGISTRY_AUTO")
RISK_STATUSES = ("ACTIVE", "SURVEILLANCE_DUE", "SURVEILLANCE_OVERDUE", "CLEARED",
                 "LOSS_IDENTIFIED")
TASK_TYPES = ("OUTREACH_CALL", "INTERPRETER_SESSION", "HOME_VISIT", "EI_LINKAGE",
              "APPOINTMENT_NAVIGATION")
TASK_STATUSES = ("UNASSIGNED", "OPEN", "COMPLETED", "CANCELLED")
TASK_DISPOSITIONS = ("COMPLETED", "CANCELLED")
TASK_OUTCOMES = ("CONTACTED", "FAMILY_REENGAGED", "NO_CONTACT", "INTERPRETER_PROVIDED",
                 "LINKED")
LANGUAGE_OUTCOMES = ("CONTACTED", "FAMILY_REENGAGED", "INTERPRETER_PROVIDED")
PERIOD_STATUSES = ("OPEN", "CLOSED")
REPORT_STATUSES = ("SUBMITTED", "RETURNED_FOR_CORRECTION", "ACCEPTED", "SUPERSEDED",
                   "PENALTY_WAIVED")
REVIEW_DECISIONS = ("ACCEPT", "RETURN")
TIMELINESS_STATUSES = ("PENDING", "ON_TIME", "LATE", "OVERDUE")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            bad("Request body must be a JSON object.")
        return {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def present(data, key):
    return key in data and data[key] is not None


def _get(data, key, required):
    if key not in data or data[key] is None:
        if required:
            bad("Field '%s' is required." % key)
        return _MISSING
    return data[key]


def string_field(data, key, required=True, min_len=None, max_len=None, default=None):
    value = _get(data, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' is shorter than %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is longer than %d characters." % (key, max_len))
    return value


def enum_field(data, key, allowed, required=True, default=None):
    value = _get(data, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def int_field(data, key, required=True, minimum=None, maximum=None, default=None):
    value = _get(data, key, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %d." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %d." % (key, maximum))
    return value


def bool_field(data, key, required=True, default=None):
    value = _get(data, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def datetime_field(data, key, required=True, default=None):
    value = _get(data, key, required)
    if value is _MISSING:
        return default
    try:
        return db.parse_dt(value)
    except (ValueError, TypeError):
        bad("Field '%s' must be an ISO 8601 UTC instant." % key)


def id_field(data, key, required=True):
    value = _get(data, key, required)
    if value is _MISSING:
        return None
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be an identifier string." % key)
    return value


def language_list(data, key, default=None):
    value = _get(data, key, False)
    if value is _MISSING:
        return list(default or ["EN"])
    if not isinstance(value, list) or not value:
        bad("Field '%s' must be a non-empty array of language codes." % key)
    for item in value:
        if not isinstance(item, str) or item not in LANGUAGES:
            bad("Field '%s' contains an unsupported language code." % key)
    return list(value)


def flag_query(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None
