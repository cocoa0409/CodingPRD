"""Error catalog (PRD section 5 / SCAFFOLD 1.6) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        spec = ERROR_CATALOG.get(error_id)
        if spec is None:  # defensive: never happens for catalog ids
            spec = (500, "Internal error.")
        self.http_status = spec[0]
        self.message = message if message is not None else spec[1]


ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Authentication headers are missing or invalid."),
    "ERR_UNAUTHORIZED": (403, "This role may not perform this operation."),
    "ERR_INVALID_REQUEST": (400, "The request payload is malformed or violates a field constraint."),
    "ERR_COURSE_NOT_FOUND": (404, "No course with that id exists."),
    "ERR_TURF_AREA_NOT_FOUND": (404, "No turf area with that id exists."),
    "ERR_PLAN_NOT_FOUND": (404, "No agronomic plan with that id exists."),
    "ERR_PLAN_TASK_NOT_FOUND": (404, "No plan task with that id exists."),
    "ERR_APPLICATOR_NOT_FOUND": (404, "No applicator with that id exists."),
    "ERR_PRODUCT_NOT_FOUND": (404, "No pesticide product with that id exists."),
    "ERR_APPLICATION_NOT_FOUND": (404, "No application record with that id exists."),
    "ERR_PUMP_STATION_NOT_FOUND": (404, "No pump station with that id exists."),
    "ERR_IRRIGATION_RUN_NOT_FOUND": (404, "No irrigation run with that id exists."),
    "ERR_WINDOW_NOT_FOUND": (404, "No maintenance window with that id exists."),
    "ERR_PLAY_EVENT_NOT_FOUND": (404, "No play event with that id exists."),
    "ERR_EQUIPMENT_NOT_FOUND": (404, "No equipment unit with that id exists."),
    "ERR_WEATHER_EVENT_NOT_FOUND": (404, "No weather event with that id exists."),
    "ERR_PLAN_STATE_INVALID": (409, "The agronomic plan is not in a state that permits this operation."),
    "ERR_TASK_STATE_INVALID": (409, "The plan task is not in a state that permits this operation."),
    "ERR_WINDOW_STATE_INVALID": (409, "The maintenance window is not in a state that permits this operation."),
    "ERR_RUN_STATE_INVALID": (409, "The irrigation run is not in a state that permits this operation."),
    "ERR_APPLICATION_STATE_INVALID": (409, "The application record is not in a state that permits this operation."),
    "ERR_EQUIPMENT_STATE_INVALID": (409, "The equipment unit is not in a state that permits this operation."),
    "ERR_WEATHER_STATE_INVALID": (409, "The weather event is not active."),
    "ERR_PLAY_EVENT_STATE_INVALID": (409, "The play event is not in a state that permits certification."),
    "ERR_STALE_COURSE_VERSION": (412, "The course has changed since it was read."),
    "ERR_STALE_PLAN_VERSION": (412, "The agronomic plan has changed since it was read."),
    "ERR_STALE_PUMP_VERSION": (412, "The pump station has changed since it was read."),
    "ERR_LICENSE_EXPIRED": (422, "The applicator's license does not cover this application."),
    "ERR_WIND_LIMIT_EXCEEDED": (422, "Wind speed exceeds the product's label limit."),
    "ERR_BUFFER_ZONE_VIOLATION": (422, "The treated area is inside the product's surface-water buffer."),
    "ERR_NITROGEN_LOAD_LIMIT": (422, "The area's regulatory nitrogen load would be exceeded."),
    "ERR_REI_ACTIVE": (409, "A restricted-entry interval is still running on this area."),
    "ERR_COURSE_CLOSED": (409, "The course is closed to this activity."),
    "ERR_TURF_AREA_OUT_OF_PLAY": (409, "The turf area is out of play."),
    "ERR_LICENSE_CATEGORY_MISMATCH": (422, "The applicator's license category does not authorise this product."),
    "ERR_TASK_TURF_AREA_MISMATCH": (422, "The referenced records do not agree on turf area or course."),
    "ERR_REPLACEMENT_UNIT_TYPE_MISMATCH": (422, "The named replacement unit is not an equivalent machine."),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The same person may not perform both steps."),
    "ERR_WINDOW_OVERLAP": (409, "Another crew window already occupies this area at that time."),
    "ERR_WINDOW_CONFLICTS_PLAY": (409, "The crew window collides with play on that hole."),
    "ERR_APPLICATION_OUTSIDE_PLAN_WINDOW": (422, "The record falls outside the plan task's planned window."),
    "ERR_DUPLICATE_LICENSE_NUMBER": (409, "That applicator license number is already registered."),
    "ERR_PUMP_OFFLINE": (409, "The pump station is offline."),
    "ERR_PUMP_ZONE_CAPACITY": (409, "The station has no free zone in that window."),
    "ERR_PUMP_FLOW_CAPACITY": (409, "The station's flow capacity would be exceeded."),
    "ERR_DEFERRAL_LIMIT_REACHED": (409, "This window has been deferred as many times as the policy allows."),
    "ERR_REVISION_LIMIT_REACHED": (409, "This plan has been returned as many times as the policy allows."),
    "ERR_INSUFFICIENT_READINGS": (422, "Not enough greens have been measured to certify conditions."),
    "ERR_ZERO_ALLOTMENT": (422, "The computed irrigation allotment is zero."),
    "ERR_WATER_ALLOCATION_EXCEEDED": (422, "The annual water allocation would be exceeded."),
    "ERR_NITROGEN_BUDGET_EXCEEDED": (422, "The plan's nitrogen budget would be exceeded."),
}


def fail(error_id, message=None):
    raise ApiError(error_id, message)
