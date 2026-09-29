"""Entity representations. Field sets follow the scaffold entity tables."""
from db import store
from services import clinical
from services import outings as outing_svc
from services import volunteers as volunteer_svc

COMMON = ("id", "created_at", "updated_at", "version")

RESIDENT_FIELDS = (
    "id",
    "full_name",
    "room_number",
    "admission_date",
    "status",
    "cognitive_level",
    "functional_mobility",
    "interest_domains",
    "supervision_tier",
    "engagement_index",
    "refusal_streak",
    "absence_count",
    "enrollment_gate",
    "care_plan_review_due",
) + COMMON[1:]

ASSESSMENT_FIELDS = (
    "id",
    "resident_id",
    "cognitive_level",
    "functional_mobility",
    "interest_domains",
    "adaptive_equipment_needs",
    "preferred_group_size",
    "effective_date",
    "assessed_by_user_id",
    "superseded",
    "created_at",
)

PLAN_FIELDS = (
    "id",
    "resident_id",
    "source_assessment_id",
    "status",
    "cycle_start_at",
    "domain_frequency_targets",
    "target_total_sessions",
    "credited_attainment_pct",
    "offered_attainment_pct",
    "revision_count",
    "review_reason",
    "activated_at",
) + COMMON[1:]

PROGRAM_FIELDS = (
    "id",
    "name",
    "domain",
    "staffing_ratio_denominator",
    "max_group_size",
    "max_supervision_tier",
    "required_adaptive_equipment",
    "volunteer_eligible",
    "required_screening_level",
    "council_preference_weight",
) + COMMON[1:]

ROOM_FIELDS = (
    "id",
    "name",
    "capacity",
    "buffer_minutes",
    "equipment_available",
) + COMMON[1:]

SESSION_FIELDS = (
    "id",
    "program_id",
    "room_id",
    "starts_at",
    "ends_at",
    "assigned_staff_count",
    "status",
    "enrolled_count",
    "weighted_supervision_load",
    "required_staff_count",
    "effective_capacity",
    "documented_at",
    "cancel_reason",
) + COMMON[1:]

RECORD_FIELDS = (
    "id",
    "session_id",
    "resident_id",
    "status",
    "finalized_from",
    "outcome",
    "engagement_level",
    "refusal_reason",
    "adaptive_equipment_used",
    "gate_override_reason",
    "documented_by_user_id",
    "documented_at",
) + COMMON[1:]

VOLUNTEER_FIELDS = (
    "id",
    "full_name",
    "volunteer_type",
    "screening_level",
    "background_check_cleared_on",
    "background_check_expires_on",
    "orientation_completed_on",
    "status",
    "scheduled_hours_week",
    "credited_service_hours",
) + COMMON[1:]

ASSIGNMENT_FIELDS = (
    "id",
    "volunteer_id",
    "session_id",
    "role_type",
    "status",
    "hours",
    "withdrawn_reason",
) + COMMON[1:]

VEHICLE_FIELDS = (
    "id",
    "label",
    "ambulatory_seats",
    "wheelchair_stations",
    "turnaround_minutes",
    "status",
    "reserved_ambulatory_seats",
    "reserved_wheelchair_stations",
) + COMMON[1:]

OUTING_FIELDS = (
    "id",
    "program_id",
    "vehicle_id",
    "destination",
    "departure_at",
    "return_at",
    "escort_count",
    "logistics_status",
    "consent_status",
    "roster_count",
    "manifest_count",
    "weighted_supervision_load",
    "required_escorts",
    "ambulatory_seats_required",
    "wheelchair_seats_required",
    "seat_shortfall_total",
    "departed_at",
    "returned_at",
    "cancel_reason",
) + COMMON[1:]

CONSENT_FIELDS = (
    "id",
    "outing_id",
    "resident_id",
    "responsible_party_name",
    "responsible_party_relation",
    "status",
    "expires_on",
    "effective",
    "decided_at",
) + COMMON[1:]

COUNCIL_FIELDS = (
    "id",
    "resident_id",
    "requested_domain",
    "requested_program_id",
    "vote_count",
    "note",
    "status",
    "decision_note",
    "reviewed_by_user_id",
) + COMMON[1:]

PACKET_FIELDS = (
    "id",
    "window_start",
    "window_end",
    "status",
    "offered_sessions_targeted",
    "offered_sessions_delivered",
    "base_score",
    "domain_coverage_penalty",
    "refusal_penalty",
    "preliminary_score",
    "deficiency_flags",
    "provision_score",
    "compiled_by_user_id",
    "attested_by_user_id",
    "amendment_count",
    "remediation_note",
) + COMMON[1:]


def _pick(entity, fields, extra=None):
    out = {}
    for name in fields:
        out[name] = entity.get(name)
    if extra:
        out.update(extra)
    return out


def resident(entity):
    return _pick(entity, RESIDENT_FIELDS)


def assessment(entity):
    return _pick(entity, ASSESSMENT_FIELDS)


def plan(entity):
    return _pick(entity, PLAN_FIELDS)


def program(entity):
    return _pick(entity, PROGRAM_FIELDS)


def room(entity):
    return _pick(entity, ROOM_FIELDS)


def session(entity):
    return _pick(entity, SESSION_FIELDS)


def record(entity):
    return _pick(entity, RECORD_FIELDS, {"outcome": clinical.record_outcome(entity)})


def volunteer(entity):
    live = {
        "scheduled_hours_week": volunteer_svc.scheduled_hours_week(
            store, entity["id"]
        ),
        "credited_service_hours": volunteer_svc.credited_service_hours(
            store, entity["id"]
        ),
    }
    return _pick(entity, VOLUNTEER_FIELDS, live)


def assignment(entity):
    return _pick(entity, ASSIGNMENT_FIELDS)


def vehicle(entity):
    return _pick(entity, VEHICLE_FIELDS)


def outing(entity):
    return _pick(entity, OUTING_FIELDS)


def consent(entity):
    parent = store.outings.get(entity["outing_id"])
    effective = (
        outing_svc.consent_effective(entity, parent) if parent is not None else False
    )
    return _pick(entity, CONSENT_FIELDS, {"effective": effective})


def council_request(entity):
    return _pick(entity, COUNCIL_FIELDS)


def packet(entity):
    return _pick(entity, PACKET_FIELDS)
