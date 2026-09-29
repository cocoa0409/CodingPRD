"""Domain enumerations, constants and path/body lookup helpers."""

from common import STORE, err

# --------------------------------------------------------------------------- #
# Enumerations (PRD 2.7, 3.x)
# --------------------------------------------------------------------------- #
STATE_CODES = ("CA", "TX", "NY")
DISCIPLINE_INCLUSION_MODES = ("ALL_INCIDENTS", "SUSPENSIONS_AND_EXPULSIONS", "EXPULSIONS_ONLY")

COMPONENT_TYPE_ORDER = ("ACADEMIC", "HEALTH", "DISCIPLINE", "SPECIAL_EDUCATION")
COMPONENT_TYPES = set(COMPONENT_TYPE_ORDER)
REQUIRED_BASE_TYPES = ("ACADEMIC", "HEALTH", "DISCIPLINE")

DIRECTORY_CATEGORY_ORDER = ("NAME", "ADDRESS", "PHONE", "PHOTO", "HONORS", "SPORTS_PARTICIPATION")
DIRECTORY_CATEGORIES = set(DIRECTORY_CATEGORY_ORDER)

WITHDRAWAL_REASONS = ("TRANSFER_OUT", "MOVED", "HOMESCHOOL", "OTHER")
HOLD_TYPES = ("UNRETURNED_PROPERTY", "LIBRARY_FINE", "MEAL_ACCOUNT", "SPED_EXIT_MEETING")

COMPONENT_TARGET_STATUSES = ("COLLECTED", "CERTIFIED", "EXCLUDED")
EXCLUSION_REASONS = ("OTHER_STUDENT_INFO", "SEALED_BY_COURT", "DUPLICATE_OF_TRANSCRIPT")

ACTION_TYPES = ("SUSPENSION", "EXPULSION", "DETENTION", "BEHAVIOR_PLAN")
INCIDENT_STATUSES = ("SUSTAINED", "PENDING_INVESTIGATION", "DISMISSED")

REQUEST_PRIORITIES = ("STANDARD", "UNACCOMPANIED_YOUTH")
DENIAL_REASONS = ("NO_ENROLLMENT_AUTHORIZATION", "STUDENT_NOT_IN_DISTRICT", "DUPLICATE_REQUEST", "COURT_SEALED")
TRANSMISSION_METHODS = ("SECURE_PORTAL", "ENCRYPTED_EMAIL", "CERTIFIED_MAIL")
OPEN_REQUEST_STATUSES = ("RECEIVED", "VALIDATED", "ASSEMBLING", "READY_FOR_RELEASE")

ROOM_STATUSES = ("ACTIVE", "CLOSED")
OFFICER_STATUSES = ("ACTIVE", "INACTIVE")
CREDENTIALS = ("ADMINISTRATIVE_LAW_JUDGE", "DISTRICT_DESIGNEE", "EXTERNAL_CONTRACTOR")

REQUESTER_ROLES = ("PARENT", "ELIGIBLE_STUDENT")
FEE_TRANSACTION_TYPES = ("PAYMENT", "WAIVER", "REVERSAL")

AMENDMENT_OUTCOMES = ("GRANT", "DENY")

DEMAND_TYPES = ("JUDICIAL_SUBPOENA", "GRAND_JURY_SUBPOENA", "LAW_ENFORCEMENT_REQUEST", "EX_PARTE_ORDER")
WAIVER_BASES = ("GRAND_JURY_ORDER", "EX_PARTE_COURT_ORDER", "LAW_ENFORCEMENT_DIRECTIVE")
NOTIFIED_PARTIES = ("PARENT", "ELIGIBLE_STUDENT")
OPEN_DEMAND_STATUSES = ("RECEIVED", "NOTIFIED")

DESTRUCTION_METHODS = ("CROSS_CUT_SHRED", "INCINERATION", "CERTIFIED_DIGITAL_WIPE")

DISCLOSURE_TYPES = ("INTERDISTRICT_TRANSFER", "DIRECTORY_INFORMATION", "LEGAL_DEMAND", "PARENT_INSPECTION")
SOURCE_TYPES = ("RECORDS_REQUEST", "LEGAL_DEMAND", "STUDENT_DIRECTORY", "INSPECTION_REQUEST")

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
ELIGIBLE_STUDENT_AGE_YEARS = 18
EXPEDITED_CAP_DAYS = 5
SPED_CONSENT_EXTENSION_DAYS = 10
INSPECTION_WINDOW_DAYS = 45
PER_PAGE_CENTS = "7.5"
COPY_SURCHARGE_PCT = "0.0825"
CERT_TIER_B_FLOOR_CENTS = 2000
CERT_TIER_C_FLOOR_CENTS = 10000
CERT_TIER_B_FEE_CENTS = 500
CERT_TIER_C_FEE_CENTS = 1500
SUMMARY_SUBSTITUTION_THRESHOLD_PAGES = 500
SUMMARY_PAGE_COUNT = 3
STATEMENT_PAGE_COUNT = 1
ROOM_TURNOVER_BUFFER_MINUTES = 15
OFFICER_DAILY_MINUTE_CAP = 240


# --------------------------------------------------------------------------- #
# Lookups (PRD 2.8) — resolved left to right, first failure terminates
# --------------------------------------------------------------------------- #
def _get(table, key, error_id):
    row = table.get(key)
    if row is None:
        err(error_id, 404, "Referenced resource does not exist.")
    return row


def get_state_rule(state_code):
    return _get(STORE.state_rules, state_code, "ERR_STATE_RULE_NOT_FOUND")


def get_district(district_id):
    return _get(STORE.districts, district_id, "ERR_DISTRICT_NOT_FOUND")


def get_student(student_id):
    return _get(STORE.students, student_id, "ERR_STUDENT_NOT_FOUND")


def get_withdrawal(withdrawal_id):
    return _get(STORE.withdrawals, withdrawal_id, "ERR_WITHDRAWAL_NOT_FOUND")


def get_cumulative_file(file_id):
    return _get(STORE.cumulative_files, file_id, "ERR_CUMULATIVE_FILE_NOT_FOUND")


def get_component(component_id):
    return _get(STORE.file_components, component_id, "ERR_FILE_COMPONENT_NOT_FOUND")


def get_scoped_component(file_row, component_id):
    component = STORE.file_components.get(component_id)
    if component is None or component["cumulative_file_id"] != file_row["id"]:
        err("ERR_FILE_COMPONENT_NOT_FOUND", 404, "Component does not belong to this cumulative file.")
    return component


def get_incident(incident_id):
    return _get(STORE.discipline_incidents, incident_id, "ERR_DISCIPLINE_INCIDENT_NOT_FOUND")


def get_records_request(request_id):
    return _get(STORE.records_requests, request_id, "ERR_RECORDS_REQUEST_NOT_FOUND")


def get_room(room_id):
    return _get(STORE.inspection_rooms, room_id, "ERR_INSPECTION_ROOM_NOT_FOUND")


def get_inspection_request(request_id):
    return _get(STORE.inspection_requests, request_id, "ERR_INSPECTION_REQUEST_NOT_FOUND")


def get_appointment(appointment_id):
    return _get(STORE.review_appointments, appointment_id, "ERR_REVIEW_APPOINTMENT_NOT_FOUND")


def get_hearing_officer(officer_id):
    return _get(STORE.hearing_officers, officer_id, "ERR_HEARING_OFFICER_NOT_FOUND")


def get_amendment_request(amendment_id):
    return _get(STORE.amendment_requests, amendment_id, "ERR_AMENDMENT_REQUEST_NOT_FOUND")


def get_legal_demand(demand_id):
    return _get(STORE.legal_demands, demand_id, "ERR_LEGAL_DEMAND_NOT_FOUND")


def get_retention_schedule(schedule_id):
    return _get(STORE.retention_schedules, schedule_id, "ERR_RETENTION_SCHEDULE_NOT_FOUND")


# --------------------------------------------------------------------------- #
# Relationship helpers
# --------------------------------------------------------------------------- #
def file_of_student(student_id):
    for row in STORE.cumulative_files.values():
        if row["student_id"] == student_id:
            return row
    return None


def components_of_file(file_id):
    rows = [row for row in STORE.file_components.values() if row["cumulative_file_id"] == file_id]
    rows.sort(key=lambda row: COMPONENT_TYPE_ORDER.index(row["component_type"]))
    return rows


def schedule_of_file(file_id):
    for row in STORE.retention_schedules.values():
        if row["cumulative_file_id"] == file_id:
            return row
    return None


def schedule_of_student(student_id):
    file_row = file_of_student(student_id)
    if file_row is None:
        return None
    return schedule_of_file(file_row["id"])


def student_of_file(file_row):
    return STORE.students.get(file_row["student_id"])


def state_rule_for_student(student_row):
    district = STORE.districts.get(student_row["district_id"])
    if district is None:
        return None
    return STORE.state_rules.get(district["state_code"])


def incidents_of_student(student_id):
    """Ascending (incident_date, created_at) — the order the inclusion pass walks."""
    rows = [row for row in STORE.discipline_incidents.values() if row["student_id"] == student_id]
    rows.sort(key=lambda row: (row["incident_date"], row["created_at"], row["_seq"]))
    return rows


def requests_of_student(student_id):
    rows = [row for row in STORE.records_requests.values() if row["student_id"] == student_id]
    return sorted(rows, key=lambda row: (row["created_at"], row["_seq"]))


def demands_of_student(student_id):
    rows = [row for row in STORE.legal_demands.values() if row["student_id"] == student_id]
    return sorted(rows, key=lambda row: (row["created_at"], row["_seq"]))


def disclosures_of_student(student_id):
    rows = [row for row in STORE.disclosure_entries.values() if row["student_id"] == student_id]
    return sorted(rows, key=lambda row: (row["created_at"], row["_seq"]))


def appointments_of_request(inspection_request_id):
    rows = [row for row in STORE.review_appointments.values()
            if row["inspection_request_id"] == inspection_request_id]
    return sorted(rows, key=lambda row: (row["created_at"], row["_seq"]))
