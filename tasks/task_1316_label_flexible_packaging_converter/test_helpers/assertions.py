"""Entity assertions and domain invariant checkers.

Structural assertions only: presence, type, format, enum membership — never
business values, so the same helper serves every test scenario.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_ARTWORK_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "OBSOLETE"]
_JOB_STATUSES = ["QUOTED", "APPROVED", "RELEASED", "ON_PRESS", "PRINTED",
                 "REWOUND", "SHIPPED", "CANCELLED"]
_VERDICTS = ["PENDING", "PASS", "FAIL"]
_ROLL_STATUSES = ["WOUND", "ACCEPTED", "REJECTED"]
_DIE_STATUSES = ["ACTIVE", "RETIRED"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_name"], str) and data["account_name"]
    assert isinstance(data["credit_hold"], bool)
    assert isinstance(data["preferred_currency"], str) and \
        data["preferred_currency"]


def assert_artwork_version(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str) and data["customer_id"]
    assert isinstance(data["artwork_code"], str) and data["artwork_code"]
    assert isinstance(data["revision_no"], int)
    assert isinstance(data["color_count"], int)
    assert isinstance(data["plate_set_cost_cents"], int)
    assert data["status"] in _ARTWORK_STATUSES


def assert_substrate(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["substrate_code"], str) and data["substrate_code"]
    assert isinstance(data["width_mm"], int)
    assert isinstance(data["cost_per_msq_cents"], int)
    assert isinstance(data["food_contact_certified"], bool)


def assert_ink_recipe(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["recipe_code"], str) and data["recipe_code"]
    assert isinstance(data["food_contact_compliant"], bool)
    assert isinstance(data["cost_per_lb_cents"], int)


def assert_die(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["die_code"], str) and data["die_code"]
    assert isinstance(data["shape_description"], str)
    assert isinstance(data["cavities_across"], int)
    assert data["status"] in _DIE_STATUSES
    assert isinstance(data["new_die_charge_cents"], int)
    assert isinstance(data["charge_collected"], bool)


def assert_press(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["press_code"], str) and data["press_code"]
    assert isinstance(data["station_count"], int)
    assert isinstance(data["setup_waste_ft"], int)
    assert isinstance(data["run_waste_pct_numerator"], int)


def assert_label_job(data: dict):
    _assert_common_fields(data)
    for fk in ("customer_id", "artwork_version_id", "substrate_id",
               "ink_recipe_id", "die_id", "press_id"):
        assert isinstance(data[fk], str) and data[fk], f"{fk} must be set"
    assert isinstance(data["quantity_ordered"], int)
    assert isinstance(data["repeat_length_mm"], int)
    assert isinstance(data["requires_food_contact_letter"], bool)
    assert isinstance(data["rewind_max_rolls"], int)
    assert isinstance(data["max_splices_per_roll"], int)
    assert data["status"] in _JOB_STATUSES
    assert isinstance(data["quoted_price_cents"], int)
    assert isinstance(data["die_charge_applied_cents"], int)
    # Computed-later fields: unset (null) until their lifecycle milestone.
    assert data.get("material_ft") is None or \
        isinstance(data["material_ft"], int)
    assert data.get("good_quantity_produced") is None or \
        isinstance(data["good_quantity_produced"], int)
    assert data.get("invoiced_price_cents") is None or \
        isinstance(data["invoiced_price_cents"], int)


def assert_color_measurement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["job_id"], str) and data["job_id"]
    assert isinstance(data["station_no"], int)
    assert isinstance(data["delta_e"], (int, float))
    assert data["verdict"] in _VERDICTS


def assert_rewind_roll(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["job_id"], str) and data["job_id"]
    assert isinstance(data["roll_seq"], int)
    assert isinstance(data["label_count"], int)
    assert isinstance(data["splice_count"], int)
    assert data["status"] in _ROLL_STATUSES


def assert_compliance_letter(data: dict):
    """ComplianceLetter is append-only: id + created_at only, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert isinstance(data["job_id"], str) and data["job_id"]
    assert data["letter_type"] == "FOOD_CONTACT"
    assert isinstance(data["body"], str)
    assert is_iso8601_timestamp(data.get("issued_at", "")), \
        "issued_at must be an ISO 8601 timestamp"
    assert "version" not in data, "ComplianceLetter must not expose version"
    assert "updated_at" not in data, "ComplianceLetter must not expose updated_at"
