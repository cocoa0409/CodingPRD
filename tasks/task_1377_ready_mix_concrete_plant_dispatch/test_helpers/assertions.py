"""Entity assertions and domain invariant checkers for the Ready Mix Dispatch API."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_plant(data: dict):
    """Validate Plant response structure against the PRD contract."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["batch_cycle_minutes"], int)
    assert data["status"] in ("ACTIVE", "DOWN")


def assert_mix_design(data: dict):
    """Validate MixDesign response structure."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["design_strength_psi"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_price_list(data: dict):
    """Validate PriceList response structure."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert isinstance(data["base_price_per_yd3_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")


def assert_customer(data: dict):
    """Validate Customer response structure."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["credit_exposure_cents"], int)
    assert data["credit_status"] in ("GOOD", "HOLD")


def assert_order(data: dict):
    """Validate Order response structure."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["delivery_status"] in (
        "PLACED",
        "CONFIRMED",
        "SCHEDULED",
        "IN_PROGRESS",
        "DELIVERED",
        "CANCELLED",
    )
    assert data["billing_status"] in (
        "UNPRICED",
        "PRICED",
        "INVOICED",
        "DISPUTED",
        "PAID",
        "VOID",
    )


def assert_truck(data: dict):
    """Validate Truck response structure."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["status"] in (
        "AVAILABLE",
        "ON_DELIVERY",
        "IN_WASHOUT",
        "OUT_OF_SERVICE",
    )


def assert_load(data: dict):
    """Validate Load response structure."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["status"] in (
        "SCHEDULED",
        "BATCHED",
        "EN_ROUTE",
        "ON_SITE",
        "POURING",
        "COMPLETED",
        "RETURNED",
        "WASHED_OUT",
        "CANCELLED",
    )
    assert data["strength_liability"] in ("NONE", "CUSTOMER", "PLANT")


def assert_batch_ticket(data: dict):
    """Validate BatchTicket response structure (append-only: no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "batch tickets are append-only: no version field"
    assert "updated_at" not in data, "batch tickets are append-only: no updated_at field"
    assert isinstance(data["ticket_number"], int)
    assert isinstance(data["cement_lb"], int)
    assert isinstance(data["batch_water_lb"], int)


def assert_water_addition(data: dict):
    """Validate WaterAddition response shape (append-only: no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("added_at", "")), "added_at must be ISO 8601"
    assert "version" not in data, "water additions are append-only: no version field"
    assert "updated_at" not in data, "water additions are append-only: no updated_at"


def assert_cylinder_set(data: dict):
    """Validate CylinderSet response structure."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["status"] in (
        "CURING",
        "SEVEN_DAY_RECORDED",
        "FINAL_RECORDED",
        "CERTIFIED",
        "FLAGGED",
    )
    assert data["acceptance_basis"] in ("DESIGN_BASIS", "AS_PLACED")


def assert_return_record(data: dict):
    """Validate ReturnRecord response structure."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["disposition"] in ("DUMPED", "RECYCLED", "FILL")


def assert_invoice(data: dict):
    """Validate Invoice response structure and its total/line-items invariant."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "PAID", "VOID")
    assert isinstance(data["line_items"], list)
    assert isinstance(data["total_cents"], int)


def assert_invoice_total_invariant(data: dict):
    """Domain invariant: total_cents == sum(line_items.amount_cents) at all times."""
    line_sum = sum(line["amount_cents"] for line in data["line_items"])
    assert data["total_cents"] == line_sum, (
        f"Invoice total_cents {data['total_cents']} != sum of line_items {line_sum}"
    )
