"""Entity serializers — produce the public JSON shape for each entity.

Computed fields (usable_capacity_va, committed_load_va, zone_load_va,
fixture_count, total_committed_load_va, line_total_cents, visit_count) are kept
up to date by the recompute engine on every mutation, so serializers simply
emit the stored value. Internal-only keys (prefixed "_") are stripped.
"""

from common import public

# Field projection per entity (order is informational; JSON is unordered).
_FIELDS = {
    "customer": [
        "id",
        "full_name",
        "email",
        "wallet_credit_cents",
        "created_at",
        "updated_at",
        "version",
    ],
    "project": [
        "id",
        "customer_id",
        "property_address",
        "design_status",
        "commercial_status",
        "fixture_count",
        "total_committed_load_va",
        "created_at",
        "updated_at",
        "version",
    ],
    "transformer": [
        "id",
        "project_id",
        "model_code",
        "rated_capacity_va",
        "usable_capacity_va",
        "committed_load_va",
        "status",
        "created_at",
        "updated_at",
        "version",
    ],
    "zone": [
        "id",
        "project_id",
        "transformer_id",
        "label",
        "zone_load_va",
        "created_at",
        "updated_at",
        "version",
    ],
    "fixture": [
        "id",
        "zone_id",
        "project_id",
        "model_code",
        "category",
        "wattage_w",
        "purchase_price_cents",
        "warranty_months",
        "installed_at",
        "status",
        "created_at",
        "updated_at",
        "version",
    ],
    "quote": [
        "id",
        "project_id",
        "night_demo_requested",
        "night_demo_at",
        "subtotal_cents",
        "discount_cents",
        "tax_cents",
        "grand_total_cents",
        "revision_round",
        "status",
        "created_at",
        "updated_at",
        "version",
    ],
    "quote_line": [
        "id",
        "quote_id",
        "model_code",
        "quantity",
        "unit_price_cents",
        "line_total_cents",
        "created_at",
        "updated_at",
        "version",
    ],
    "install_job": [
        "id",
        "project_id",
        "quote_id",
        "wiring_status",
        "fixtures_status",
        "status",
        "created_at",
        "updated_at",
        "version",
    ],
    "schedule_program": [
        "id",
        "project_id",
        "scene_label",
        "window_start_min",
        "window_end_min",
        "status",
        "created_at",
        "updated_at",
        "version",
    ],
    "service_plan": [
        "id",
        "project_id",
        "tier",
        "annual_fee_cents",
        "refundable",
        "activated_at",
        "season_cycle_count",
        "status",
        "created_at",
        "updated_at",
        "version",
    ],
    "service_visit": [
        "id",
        "service_plan_id",
        "project_id",
        "visit_date",
        "window_start_min",
        "window_end_min",
        "route_id",
        "status",
        "created_at",
        "updated_at",
        "version",
    ],
    "crew_route": [
        "id",
        "technician_id",
        "route_date",
        "visit_count",
        "status",
        "created_at",
        "updated_at",
        "version",
    ],
    "warranty_claim": [
        "id",
        "fixture_id",
        "project_id",
        "reason",
        "credit_variant",
        "credit_cents",
        "status",
        "created_at",
        "updated_at",
        "version",
    ],
    "add_on": [
        "id",
        "project_id",
        "zone_id",
        "kind",
        "power_draw_va",
        "status",
        "created_at",
        "updated_at",
        "version",
    ],
}


def _project_fields(record, kind):
    fields = _FIELDS[kind]
    out = {}
    for f in fields:
        out[f] = record.get(f)
    return out


def ser_customer(r):
    return _project_fields(r, "customer")


def ser_project(r):
    return _project_fields(r, "project")


def ser_transformer(r):
    return _project_fields(r, "transformer")


def ser_zone(r):
    return _project_fields(r, "zone")


def ser_fixture(r):
    return _project_fields(r, "fixture")


def ser_quote(r):
    return _project_fields(r, "quote")


def ser_quote_line(r):
    return _project_fields(r, "quote_line")


def ser_install_job(r):
    return _project_fields(r, "install_job")


def ser_schedule_program(r):
    return _project_fields(r, "schedule_program")


def ser_service_plan(r):
    return _project_fields(r, "service_plan")


def ser_service_visit(r):
    return _project_fields(r, "service_visit")


def ser_crew_route(r):
    return _project_fields(r, "crew_route")


def ser_warranty_claim(r):
    return _project_fields(r, "warranty_claim")


def ser_add_on(r):
    return _project_fields(r, "add_on")
