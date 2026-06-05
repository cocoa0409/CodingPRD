"""Public JSON projections for each entity. Computed fields are maintained on
the stored record by the service layer; serializers project the public field
set and drop internal bookkeeping keys (those prefixed with '_')."""


def _public(record, fields):
    return {f: record.get(f) for f in fields}


def license_view(r):
    return _public(r, [
        "id", "license_number", "license_type", "status", "state_code",
        "expires_on", "daily_purchase_limit_grams",
        "created_at", "updated_at", "version",
    ])


def plant_batch_view(r):
    return _public(r, [
        "id", "license_id", "lot_tag", "strain", "status",
        "plant_count", "live_plant_count", "planted_at",
        "created_at", "updated_at", "version",
    ])


def harvest_view(r):
    return _public(r, [
        "id", "plant_batch_id", "license_id", "harvest_name", "status",
        "wet_weight_grams", "dry_weight_grams", "packaged_weight_grams",
        "remaining_weight_grams",
        "created_at", "updated_at", "version",
    ])


def package_view(r):
    return _public(r, [
        "id", "harvest_id", "license_id", "package_tag", "product_category",
        "quantity_grams", "remaining_grams", "status", "lab_hold", "thc_pct",
        "created_at", "updated_at", "version",
    ])


def lab_result_view(r):
    return _public(r, [
        "id", "package_id", "testing_license_id", "thc_pct", "pesticide_pass",
        "overall_result", "tested_at", "created_at",
    ])


def manifest_view(r):
    return _public(r, [
        "id", "origin_license_id", "destination_license_id", "status",
        "line_count", "total_grams", "departed_at",
        "created_at", "updated_at", "version",
    ])


def manifest_line_view(r):
    return _public(r, [
        "id", "manifest_id", "package_id", "grams", "created_at",
    ])


def customer_view(r):
    return _public(r, [
        "id", "medical_card_number", "is_medical", "birthdate",
        "created_at", "updated_at", "version",
    ])


def sale_view(r):
    return _public(r, [
        "id", "retail_license_id", "customer_id", "sale_date", "status",
        "flower_equiv_grams",
        "created_at", "updated_at", "version",
    ])


def sale_line_view(r):
    return _public(r, [
        "id", "sale_id", "package_id", "grams", "flower_equiv_grams",
        "created_at",
    ])


def reconciliation_count_view(r):
    return _public(r, [
        "id", "package_id", "counted_by_user_id", "counted_grams",
        "expected_grams", "variance_grams", "outcome", "counted_at",
        "created_at",
    ])


def waste_event_view(r):
    return _public(r, [
        "id", "source_type", "plant_batch_id", "package_id", "reason",
        "destroyed_grams", "destroyed_plant_count", "destroyed_at",
        "created_at",
    ])
