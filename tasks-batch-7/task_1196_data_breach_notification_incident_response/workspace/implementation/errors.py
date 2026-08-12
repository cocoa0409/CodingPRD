"""Error classes and error-id constants."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_DEADLINE_PASSED = "ERR_DEADLINE_PASSED"
ERR_CUSTODY_OVERLAP = "ERR_CUSTODY_OVERLAP"
ERR_DATA_ELEMENT_OUT_OF_SCOPE = "ERR_DATA_ELEMENT_OUT_OF_SCOPE"
ERR_SUPERSESSION_CYCLE = "ERR_SUPERSESSION_CYCLE"
ERR_STAFFING_PLAN_OVERLAP = "ERR_STAFFING_PLAN_OVERLAP"
ERR_DUPLICATE_SUBJECT = "ERR_DUPLICATE_SUBJECT"
ERR_OFFER_ALREADY_ACTIVE = "ERR_OFFER_ALREADY_ACTIVE"
ERR_INCIDENT_NOT_CONFIRMED = "ERR_INCIDENT_NOT_CONFIRMED"
ERR_NOTICE_NOT_APPROVABLE = "ERR_NOTICE_NOT_APPROVABLE"
ERR_NO_ACTIVE_STAFFING_PLAN = "ERR_NO_ACTIVE_STAFFING_PLAN"
ERR_BATCH_NOT_SHIPPABLE = "ERR_BATCH_NOT_SHIPPABLE"
ERR_EVIDENCE_NOT_SEALED = "ERR_EVIDENCE_NOT_SEALED"
ERR_REMEDIATION_INCOMPLETE = "ERR_REMEDIATION_INCOMPLETE"
ERR_NO_AFFECTED_SUBJECTS = "ERR_NO_AFFECTED_SUBJECTS"


def unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def forbidden(msg="Role not permitted to invoke this endpoint"):
    return ApiError(ERR_FORBIDDEN, msg, 403)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def invalid_request(msg="Invalid request payload"):
    return ApiError(ERR_INVALID_REQUEST, msg, 422)


def invalid_state(msg="Entity not in a state permitting the requested transition"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def stale_version(msg="expected_incident_version does not match current incident.version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)


def segregation(msg="Segregation of duties violation"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, msg, 409)


def deadline_passed(msg="Statutory deadline or temporal precondition violated"):
    return ApiError(ERR_DEADLINE_PASSED, msg, 409)


def custody_overlap(msg="Custody interval overlap or invalid preservation hash"):
    return ApiError(ERR_CUSTODY_OVERLAP, msg, 409)


def out_of_scope(msg="data_elements_exposed not a subset of baselined scope"):
    return ApiError(ERR_DATA_ELEMENT_OUT_OF_SCOPE, msg, 422)


def supersession_cycle(msg="supersedes_notice_id would create a cycle"):
    return ApiError(ERR_SUPERSESSION_CYCLE, msg, 422)


def staffing_overlap(msg="Staffing plan interval overlap"):
    return ApiError(ERR_STAFFING_PLAN_OVERLAP, msg, 409)


def duplicate_subject(msg="external_subject_ref already exists on this incident"):
    return ApiError(ERR_DUPLICATE_SUBJECT, msg, 409)


def offer_active(msg="An ISSUED offer already exists for this subject"):
    return ApiError(ERR_OFFER_ALREADY_ACTIVE, msg, 409)


def not_confirmed(msg="Operation requires incident.investigation_status == CONFIRMED"):
    return ApiError(ERR_INCIDENT_NOT_CONFIRMED, msg, 409)


def not_approvable(msg="Notice not approvable"):
    return ApiError(ERR_NOTICE_NOT_APPROVABLE, msg, 409)


def no_active_plan(msg="No ACTIVE CallCenterStaffingPlan exists"):
    return ApiError(ERR_NO_ACTIVE_STAFFING_PLAN, msg, 409)


def batch_not_shippable(msg="MailingBatch cannot transition to SHIPPED"):
    return ApiError(ERR_BATCH_NOT_SHIPPABLE, msg, 409)


def evidence_not_sealed(msg="No SEALED evidence item exists"):
    return ApiError(ERR_EVIDENCE_NOT_SEALED, msg, 409)


def remediation_incomplete(msg="Technical remediation actions remain non-terminal"):
    return ApiError(ERR_REMEDIATION_INCOMPLETE, msg, 409)


def no_subjects(msg="Confirm requires total_affected_subjects > 0"):
    return ApiError(ERR_NO_AFFECTED_SUBJECTS, msg, 409)
