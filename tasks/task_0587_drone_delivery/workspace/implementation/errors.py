"""Error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> http status
CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_ORDER_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_PAYLOAD_EXCEEDS_LIMIT": 422,
    "ERR_OUT_OF_SERVICE_RANGE": 422,
    "ERR_SERVICE_AREA_NOT_FOUND": 404,
    "ERR_NEST_NOT_FOUND": 404,
    "ERR_DRONE_NOT_FOUND": 404,
    "ERR_BATTERY_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_FLIGHT_NOT_FOUND": 404,
    "ERR_AUTHORIZATION_NOT_FOUND": 404,
    "ERR_GEOFENCE_ZONE_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_MAINTENANCE_LOG_NOT_FOUND": 404,
    "ERR_STALE_ORDER_VERSION": 412,
    "ERR_STALE_DRONE_VERSION": 412,
    "ERR_DUPLICATE_TAIL_NUMBER": 409,
    "ERR_ORDER_NOT_QUOTED": 409,
    "ERR_ORDER_NOT_CANCELLABLE": 409,
    "ERR_FLIGHT_NOT_PLANNED": 409,
    "ERR_FLIGHT_INVALID_STATE": 409,
    "ERR_FLIGHT_TERMINAL": 409,
    "ERR_FLIGHT_NOT_CLEARED": 409,
    "ERR_AUTHORIZATION_NOT_PENDING": 409,
    "ERR_AUTHORIZATION_NOT_APPROVED": 409,
    "ERR_AUTHORIZATION_WINDOW_EXPIRED": 409,
    "ERR_INCIDENT_NOT_OPEN": 409,
    "ERR_INCIDENT_NOT_UNDER_REVIEW": 409,
    "ERR_MAINTENANCE_NOT_SCHEDULED": 409,
    "ERR_MAINTENANCE_WINDOW_CONFLICT": 409,
    "ERR_SERVICE_AREA_SUSPENDED": 409,
    "ERR_WEATHER_NO_GO": 409,
    "ERR_GEOFENCE_VIOLATION": 409,
    "ERR_DRONE_GROUNDED": 409,
    "ERR_DRONE_RISK_TOO_HIGH": 409,
    "ERR_NEST_UNAVAILABLE": 409,
    "ERR_NEST_PADS_FULL": 409,
    "ERR_BATTERY_NOT_READY": 409,
    "ERR_INSUFFICIENT_BATTERY": 409,
    "ERR_NO_ELIGIBLE_DRONE": 409,
    # Not in the PRD catalogue: the two immutable entities are readable by id, so
    # they need *some* 404 code. HTTP status is what matters here.
    "ERR_WEATHER_OBSERVATION_NOT_FOUND": 404,
    "ERR_DELIVERY_DROP_NOT_FOUND": 404,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this operation.",
    "ERR_NOT_ORDER_OWNER": "A customer may only act on their own orders.",
    "ERR_SEGREGATION_OF_DUTIES": "The releasing flight director may not be the user who filed the authorization.",
    "ERR_INVALID_REQUEST": "The request payload is invalid.",
}


def err(error_id, message=None):
    return ApiError(error_id, CATALOG[error_id], message)


# Entity name -> not-found error id
NOT_FOUND = {
    "ServiceArea": "ERR_SERVICE_AREA_NOT_FOUND",
    "Nest": "ERR_NEST_NOT_FOUND",
    "Drone": "ERR_DRONE_NOT_FOUND",
    "Battery": "ERR_BATTERY_NOT_FOUND",
    "Customer": "ERR_CUSTOMER_NOT_FOUND",
    "Order": "ERR_ORDER_NOT_FOUND",
    "Flight": "ERR_FLIGHT_NOT_FOUND",
    "AirspaceAuthorization": "ERR_AUTHORIZATION_NOT_FOUND",
    "GeofenceZone": "ERR_GEOFENCE_ZONE_NOT_FOUND",
    "WeatherObservation": "ERR_WEATHER_OBSERVATION_NOT_FOUND",
    "DeliveryDrop": "ERR_DELIVERY_DROP_NOT_FOUND",
    "Incident": "ERR_INCIDENT_NOT_FOUND",
    "MaintenanceLog": "ERR_MAINTENANCE_LOG_NOT_FOUND",
}
