"""Entity -> response dict serializers (Scaffold Table 1).

Each serializer emits the entity's fields exactly as stored. Internal-only keys
(none currently) are excluded. All stored entities already hold their public
field set, so serialization is mostly identity with explicit field ordering for
readability and to guarantee computed/null fields are always present.
"""

_AGENCY_FIELDS = [
    "id", "name", "discipline", "response_sla_seconds", "status",
    "created_at", "updated_at", "version",
]
_STATION_FIELDS = [
    "id", "agency_id", "name", "grid_x", "grid_y",
    "created_at", "updated_at", "version",
]
_UNIT_FIELDS = [
    "id", "agency_id", "station_id", "call_sign", "capability", "status",
    "grid_x", "grid_y", "active_incident_id",
    "created_at", "updated_at", "version",
]
_PREMISE_FIELDS = [
    "id", "grid_x", "grid_y", "hazard_class", "min_priority_floor", "active",
    "created_at", "updated_at", "version",
]
_INCIDENT_FIELDS = [
    "id", "incident_number", "ani", "ali_grid_x", "ali_grid_y", "ali_confidence",
    "incident_type", "priority_level", "base_priority_level", "required_disciplines",
    "lifecycle_status", "premise_alert_id", "received_at", "first_dispatch_at",
    "first_onscene_at", "closed_at", "escalation_count", "disposition_code",
    "response_time_seconds", "total_handle_seconds", "sla_breached",
    "created_at", "updated_at", "version",
]
_ASSIGNMENT_FIELDS = [
    "id", "incident_id", "unit_id", "recommended", "travel_distance", "status",
    "dispatched_at", "enroute_at", "onscene_at", "cleared_at",
    "created_at", "updated_at", "version",
]
_DISPOSITION_FIELDS = [
    "id", "incident_id", "disposition_code", "narrative", "requires_nfirs",
    "created_at", "updated_at", "version",
]
_REPORT_FIELDS = [
    "id", "incident_id", "report_standard", "response_time_seconds",
    "total_handle_seconds", "sla_breached", "unit_count", "disposition_code",
    "created_at",
]


def _pick(entity, fields):
    return {f: entity.get(f) for f in fields}


def agency(e):
    return _pick(e, _AGENCY_FIELDS)


def station(e):
    return _pick(e, _STATION_FIELDS)


def unit(e):
    return _pick(e, _UNIT_FIELDS)


def premise_alert(e):
    return _pick(e, _PREMISE_FIELDS)


def incident(e):
    return _pick(e, _INCIDENT_FIELDS)


def assignment(e):
    return _pick(e, _ASSIGNMENT_FIELDS)


def disposition(e):
    return _pick(e, _DISPOSITION_FIELDS)


def report(e):
    return _pick(e, _REPORT_FIELDS)
