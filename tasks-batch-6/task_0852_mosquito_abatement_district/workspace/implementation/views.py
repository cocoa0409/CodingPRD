"""Resource representations. Every datetime/date/Decimal is converted by
common.jsonable() at the envelope boundary, so there is exactly one renderer."""

_COMMON = ("id", "created_at", "updated_at", "version")
_APPEND_ONLY = ("id", "created_at")


def _pick(record, keys):
    return dict((k, record.get(k)) for k in keys)


SERVICE_AREA_FIELDS = _COMMON + (
    "name", "code", "season_start_date", "population",
    "risk_posture", "posture_source", "latest_confirmed_vector_index",
    "seasonal_application_count",
    "request_total_count", "request_open_count",
    "request_resolved_count", "request_closed_count",
)

SENSITIVE_SITE_FIELDS = _COMMON + (
    "service_area_id", "site_type", "operator_name", "contact_email",
    "x_m", "y_m", "buffer_meters_override", "buffer_meters", "registered_on",
)

TRAP_SITE_FIELDS = _COMMON + (
    "service_area_id", "site_code", "trap_type", "habitat", "x_m", "y_m",
    "is_active", "season_positive_count", "last_positive_at",
)

TRAP_COLLECTION_FIELDS = _COMMON + (
    "trap_site_id", "recorded_by_applicator_id", "collection_date",
    "trap_nights", "female_count", "species", "status",
    "pooled_mosquito_count", "positive_pool_count", "wnv_detected",
    "void_reason",
)

LAB_POOL_FIELDS = _COMMON + (
    "trap_collection_id", "pool_size", "assay", "status", "retest_count",
    "ct_value", "result_recorded_at",
)

LARVAL_INSPECTION_FIELDS = _APPEND_ONLY + (
    "service_area_id", "inspection_date", "dips", "larvae_count", "habitat",
    "treated_on_site",
)

WEATHER_OBSERVATION_FIELDS = _APPEND_ONLY + (
    "service_area_id", "obs_date", "tmax_c", "tmin_c", "rainfall_mm",
    "degree_day",
)

RISK_ASSESSMENT_FIELDS = _COMMON + (
    "service_area_id", "as_of_date", "status", "is_stale", "stale_reason",
    "abundance_index", "larval_index", "degree_days",
    "mir_provisional", "mir_confirmed",
    "vector_index_provisional", "vector_index_confirmed",
    "posture_at_confirm", "confirmed_at",
)

PESTICIDE_PRODUCT_FIELDS = _COMMON + (
    "name", "epa_reg_no", "active_ingredient", "application_method",
    "label_rate_ml_per_acre", "reentry_interval_hours", "cost_cents_per_liter",
    "restricted_use", "received_total_ml", "on_hand_ml", "committed_ml",
    "applied_ml",
)

APPLICATOR_FIELDS = _COMMON + (
    "full_name", "license_no", "license_category", "license_expires_on",
    "status", "assigned_route_count",
)

TREATMENT_PLAN_FIELDS = _COMMON + (
    "service_area_id", "trigger_assessment_id", "treatment_type", "status",
    "required_approvals", "submitted_by_user_id", "approver_user_ids",
    "notification_required", "revision_count", "scheduled_start_at",
    "estimated_total_ml", "material_cost_cents", "labor_cost_cents",
    "subtotal_cents", "admin_fee_rate", "admin_fee_cents", "total_cost_cents",
    "completed_at", "cancel_reason", "return_reason",
)

TREATMENT_ROUTE_FIELDS = _COMMON + (
    "treatment_plan_id", "applicator_id", "pesticide_product_id", "route_code",
    "window_start", "window_end", "planned_acres", "center_x_m", "center_y_m",
    "swath_radius_m", "status", "duration_minutes", "estimated_volume_ml",
    "actual_acres", "wind_speed_mph", "actual_volume_ml", "executed_at",
    "void_reason",
)

NOTIFICATION_FIELDS = _COMMON + (
    "treatment_plan_id", "sensitive_site_id", "channel", "status",
    "attempt_count", "sent_at", "acknowledged_at", "failure_reason",
)

SERVICE_REQUEST_FIELDS = _COMMON + (
    "service_area_id", "assigned_applicator_id", "reporter_contact",
    "category", "description", "x_m", "y_m", "reported_by_user_id",
    "handling_status", "verification_status", "priority", "triaged_at",
    "due_at", "resolved_at", "reopen_count", "resolution_note",
)


def area_view(r):
    return _pick(r, SERVICE_AREA_FIELDS)


def sensitive_site_view(r):
    return _pick(r, SENSITIVE_SITE_FIELDS)


def trap_site_view(r):
    return _pick(r, TRAP_SITE_FIELDS)


def trap_collection_view(r):
    return _pick(r, TRAP_COLLECTION_FIELDS)


def lab_pool_view(r):
    return _pick(r, LAB_POOL_FIELDS)


def larval_inspection_view(r):
    return _pick(r, LARVAL_INSPECTION_FIELDS)


def weather_observation_view(r):
    return _pick(r, WEATHER_OBSERVATION_FIELDS)


def risk_assessment_view(r):
    return _pick(r, RISK_ASSESSMENT_FIELDS)


def product_view(r):
    return _pick(r, PESTICIDE_PRODUCT_FIELDS)


def applicator_view(r):
    return _pick(r, APPLICATOR_FIELDS)


def plan_view(r):
    out = _pick(r, TREATMENT_PLAN_FIELDS)
    out["approver_user_ids"] = list(r.get("approver_user_ids") or [])
    return out


def route_view(r):
    return _pick(r, TREATMENT_ROUTE_FIELDS)


def notification_view(r):
    return _pick(r, NOTIFICATION_FIELDS)


def service_request_view(r):
    return _pick(r, SERVICE_REQUEST_FIELDS)
