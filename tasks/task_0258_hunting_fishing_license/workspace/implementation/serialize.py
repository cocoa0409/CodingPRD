"""Serializers: project stored records to the public field set (entities §1.1).

Internal-only keys (e.g. _seq) are stripped. Common system fields id,
created_at, updated_at, version are always included (PRD §2.4).
"""

_COMMON = ["id", "created_at", "updated_at", "version"]


def _pub(record, fields):
    out = {}
    for f in _COMMON:
        out[f] = record[f]
    for f in fields:
        out[f] = record.get(f)
    return out


def applicant(r):
    return _pub(r, [
        "full_name", "birth_date", "declared_state_code",
        "residency_status", "education_certified",
        "preference_points", "bonus_points",
    ])


def residency_verification(r):
    return _pub(r, [
        "applicant_id", "proof_type", "proof_state_code",
        "continuous_months", "status", "resulting_residency",
    ])


def education_certificate(r):
    return _pub(r, [
        "applicant_id", "course_code", "completion_date", "status",
    ])


def license_product(r):
    return _pub(r, [
        "sku", "product_kind", "species_season_id", "requires_education",
        "residency_restriction", "base_fee_cents", "min_age_years", "status",
    ])


def species_season(r):
    return _pub(r, [
        "species", "season_open", "season_close", "bag_limit",
        "draw_required", "status",
    ])


def draw_pool(r):
    return _pub(r, [
        "species_season_id", "license_product_id", "quota", "scoring_model",
        "status", "awarded_count", "entry_deadline",
    ])


def draw_application(r):
    return _pub(r, [
        "draw_pool_id", "applicant_id", "points_at_entry", "bonus_at_entry",
        "priority_score", "status", "issued_license_id",
    ])


def license(r):
    return _pub(r, [
        "applicant_id", "license_product_id", "draw_application_id",
        "issued_via", "fee_charged_cents", "status", "superseded_by_id",
    ])


def harvest_report(r):
    return _pub(r, [
        "license_id", "harvest_datetime", "quantity", "status",
    ])


def replacement(r):
    return _pub(r, [
        "original_license_id", "reason", "replacement_license_id",
        "admin_fee_cents",
    ])
