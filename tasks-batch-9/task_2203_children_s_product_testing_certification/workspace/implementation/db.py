"""In-memory store. No persistence of any kind; a fresh process starts empty.

Rows are plain dicts keyed by their server-minted UUID. Datetime-valued fields
are held as timezone-aware datetimes and rendered to ISO 8601 on the way out.
"""

import uuid

import clock

TABLES = (
    "applicable_rules",
    "product_categories",
    "category_rule_mappings",
    "suppliers",
    "laboratories",
    "lab_accreditations",
    "products",
    "component_parts",
    "component_part_certificates",
    "sampling_plans",
    "test_orders",
    "certificates",
    "production_batches",
    "noncompliance_cases",
    "material_change_events",
)

# Datetime-valued fields per table, used purely for output rendering.
DATETIME_FIELDS = {
    "applicable_rules": ("created_at", "updated_at"),
    "product_categories": ("created_at", "updated_at"),
    "category_rule_mappings": ("created_at", "updated_at", "effective_from"),
    "suppliers": ("created_at", "updated_at"),
    "laboratories": ("created_at", "updated_at", "influence_attestation_valid_through"),
    "lab_accreditations": ("created_at", "updated_at", "valid_from", "valid_through"),
    "products": ("created_at", "updated_at"),
    "component_parts": ("created_at", "updated_at", "last_material_change_at"),
    "component_part_certificates": (
        "created_at",
        "updated_at",
        "coverage_from",
        "coverage_through",
    ),
    "sampling_plans": (
        "created_at",
        "updated_at",
        "activated_at",
        "last_verified_at",
        "periodic_due_at",
    ),
    "test_orders": (
        "created_at",
        "updated_at",
        "window_start",
        "window_end",
        "reported_at",
    ),
    "certificates": ("created_at", "updated_at", "issued_at"),
    "production_batches": ("created_at", "updated_at", "produced_on", "released_at"),
    "noncompliance_cases": ("created_at", "updated_at"),
    "material_change_events": ("created_at", "occurred_at"),
}

# The two audit stamps PRD 2.4 requires in three-fractional-digit form.
AUDIT_STAMP_FIELDS = ("created_at", "updated_at")

_store = {name: {} for name in TABLES}


def reset():
    for name in TABLES:
        _store[name] = {}
    clock.reset()


def table(name):
    return _store[name]


def new_id():
    return str(uuid.uuid4())


def insert(name, row, with_version=True):
    """Persist a new row, stamping identity and audit fields from the clock."""
    now = clock.now()
    full = {"id": new_id()}
    full.update(row)
    full["created_at"] = now
    if with_version:
        full["updated_at"] = now
        full["version"] = 1
    _store[name][full["id"]] = full
    return full


def touch(name, row):
    """Refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = clock.now()
    row["version"] = row.get("version", 0) + 1
    return row


def get(name, row_id):
    if not isinstance(row_id, str):
        return None
    return _store[name].get(row_id)


def all_rows(name):
    return list(_store[name].values())


def find(name, **filters):
    out = []
    for row in _store[name].values():
        if all(row.get(k) == v for k, v in filters.items()):
            out.append(row)
    return out


def serialize(name, row):
    """Render a row for the wire: datetimes to ISO 8601, lists copied."""
    dt_fields = DATETIME_FIELDS[name]
    out = {}
    for key, value in row.items():
        if key in dt_fields:
            # PRD 2.4 pins the three-fractional-digit format on the audit stamps
            # only; every other instant renders at second precision.
            render = clock.iso_millis if key in AUDIT_STAMP_FIELDS else clock.iso_instant
            out[key] = render(value) if value is not None else None
        elif isinstance(value, list):
            out[key] = list(value)
        else:
            out[key] = value
    return out


def serialize_many(name, rows):
    return [serialize(name, r) for r in rows]
