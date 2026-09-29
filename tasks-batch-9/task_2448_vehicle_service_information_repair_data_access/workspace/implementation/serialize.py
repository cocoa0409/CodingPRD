"""Row -> JSON projections.  Internal keys (prefixed with '_') never surface.

PRD 2.4: vehicle models, system areas and audit events carry only `id` and
`created_at` -- they have no `updated_at` and no `version` at all.
"""

COMMON = ("id", "created_at", "updated_at", "version")
IMMUTABLE_COMMON = ("id", "created_at")

FIELDS = {
    "manufacturer": (
        "name",
        "oem_code",
        "region",
        "independent_list_monthly_cents",
        "independent_covered_system_count",
        "oem_dealer_monthly_cents",
        "oem_dealer_covered_system_count",
        "parity_index",
        "parity_status",
    ),
    "vehicle_model": ("manufacturer_id", "model_code", "model_year"),
    "system_area": ("code", "name", "requires_calibration_doc", "requires_security_credential"),
    "license": (
        "manufacturer_id",
        "license_model",
        "monthly_fee_cents",
        "per_vehicle_fee_cents",
        "seat_cap",
        "covered_system_area_ids",
        "effective_start",
        "effective_end",
        "status",
        "suspension_reason",
    ),
    "shop": (
        "name",
        "tier",
        "funded_credit_total_cents",
        "data_credit_balance_cents",
        "gateway_fee_accrued_cents",
        "coverage_completeness_pct",
    ),
    "technician": (
        "shop_id",
        "full_name",
        "identity_status",
        "credential_expires_at",
        "identity_document_ref",
        "verified_by_user_id",
    ),
    "entitlement": (
        "shop_id",
        "license_id",
        "entitlement_model",
        "seats_total",
        "vin_quota",
        "window_start",
        "window_end",
        "status",
        "charged_cents",
        "settled_cents",
        "settlement_status",
        "seats_assigned",
        "seats_available",
    ),
    "seat_assignment": ("entitlement_id", "technician_id", "status", "revocation_reason"),
    "diagnostic_tool": (
        "shop_id",
        "serial_no",
        "oem_attestation_expires_at",
        "status",
        "occupied_by_session_id",
    ),
    "publication": (
        "vehicle_model_id",
        "system_area_id",
        "publication_type",
        "current_version_no",
        "published_version_id",
    ),
    "publication_version": (
        "publication_id",
        "version_no",
        "source_tsb_ref",
        "calibration_procedure_ref",
        "review_status",
        "distribution_status",
        "validated_by_user_id",
        "published_by_user_id",
        "active_pin_count",
    ),
    "gateway_session": (
        "seat_assignment_id",
        "diagnostic_tool_id",
        "vin",
        "window_start",
        "window_end",
        "status",
        "credential_token",
        "base_subtotal_cents",
        "discount_cents",
        "surcharge_cents",
        "total_access_fee_cents",
        "termination_reason",
    ),
    "job": ("session_id", "job_type", "pinned_publication_version_id", "status", "repin_count", "abort_reason"),
    "audit_event": (
        "actor_role",
        "actor_user_id",
        "subject_entity",
        "subject_id",
        "event_type",
        "detail",
        "occurred_at",
    ),
}

IMMUTABLE_KINDS = ("vehicle_model", "system_area", "audit_event")


def project(kind, row):
    common = IMMUTABLE_COMMON if kind in IMMUTABLE_KINDS else COMMON
    out = {}
    for key in common:
        out[key] = row.get(key)
    for key in FIELDS[kind]:
        out[key] = row.get(key)
    return out


def project_many(kind, rows):
    return [project(kind, row) for row in rows]
