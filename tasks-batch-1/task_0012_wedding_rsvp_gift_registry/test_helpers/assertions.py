"""Entity assertions for the API contract.

Each per-entity assertion validates structural invariants the PRD declares —
PRD §2.4 requires every resource to carry the (id, created_at, updated_at,
version) quartet — plus entity-specific enum membership and basic typing.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_WEDDING_STATES = {"DRAFT", "RSVP_OPEN", "RSVP_CLOSED", "SEATED", "ARCHIVED"}
_GUEST_STATES = {"INVITED", "ATTENDING", "DECLINED"}
_PLUS_ONE_STATES = {"ATTENDING", "DECLINED"}
_ASSIGNEE_TYPES = {"GUEST", "PLUS_ONE"}
_REGISTRY_STATES = {"OPEN", "FULFILLED", "ARCHIVED"}
_PURCHASE_STATES = {"CONFIRMED", "PENDING_REVIEW", "CANCELLED"}
_THANK_YOU_STATES = {"PENDING", "DRAFTED", "SENT"}


def _assert_common_fields(data: dict, entity_label: str) -> None:
    """Validate id + created_at + updated_at + version per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be a valid UUID (got {data.get('id')!r})"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be a positive integer"
    )


def assert_wedding(data: dict) -> None:
    _assert_common_fields(data, "Wedding")
    assert isinstance(data.get("title"), str) and len(data["title"]) > 0
    assert data.get("status") in _WEDDING_STATES, (
        f"Wedding.status must be one of {_WEDDING_STATES}"
    )
    assert isinstance(data.get("seating_dirty"), bool)
    assert isinstance(data.get("total_capacity"), int)
    assert data["total_capacity"] >= 0
    assert isinstance(data.get("couple_user_id"), str)


def assert_meal_option(data: dict) -> None:
    _assert_common_fields(data, "MealOption")
    assert isinstance(data.get("code"), str) and len(data["code"]) > 0
    assert isinstance(data.get("label"), str)
    assert isinstance(data.get("is_kids"), bool)
    assert isinstance(data.get("max_servings"), int) and data["max_servings"] >= 1
    assert isinstance(data.get("wedding_id"), str)


def assert_table(data: dict) -> None:
    _assert_common_fields(data, "Table")
    assert isinstance(data.get("table_number"), int) and data["table_number"] >= 1
    assert isinstance(data.get("capacity"), int) and data["capacity"] >= 1
    assert isinstance(data.get("kids_only"), bool)
    assert isinstance(data.get("wedding_id"), str)


def assert_guest(data: dict) -> None:
    _assert_common_fields(data, "Guest")
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) > 0
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("is_child"), bool)
    assert isinstance(data.get("plus_one_allowed"), bool)
    assert data.get("rsvp_status") in _GUEST_STATES
    assert isinstance(data.get("wedding_id"), str)
    assert isinstance(data.get("invitation_token"), str) and len(data["invitation_token"]) > 0
    meal_id = data.get("meal_option_id")
    assert meal_id is None or isinstance(meal_id, str)


def assert_plus_one(data: dict) -> None:
    _assert_common_fields(data, "PlusOne")
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) > 0
    assert isinstance(data.get("is_child"), bool)
    assert data.get("rsvp_status") in _PLUS_ONE_STATES
    assert isinstance(data.get("wedding_id"), str)
    assert isinstance(data.get("guest_id"), str)
    meal_id = data.get("meal_option_id")
    assert meal_id is None or isinstance(meal_id, str)


def assert_seating_assignment(data: dict) -> None:
    _assert_common_fields(data, "SeatingAssignment")
    assert data.get("assignee_type") in _ASSIGNEE_TYPES
    assert isinstance(data.get("assignee_id"), str)
    assert isinstance(data.get("table_id"), str)
    assert isinstance(data.get("wedding_id"), str)


def assert_registry_item(data: dict) -> None:
    _assert_common_fields(data, "RegistryItem")
    assert isinstance(data.get("sku"), str) and len(data["sku"]) > 0
    assert isinstance(data.get("title"), str)
    assert isinstance(data.get("target_quantity"), int) and data["target_quantity"] >= 1
    assert isinstance(data.get("unit_price_cents"), int) and data["unit_price_cents"] >= 0
    assert data.get("status") in _REGISTRY_STATES
    assert isinstance(data.get("fulfilled_quantity"), int) and data["fulfilled_quantity"] >= 0
    # pending_quantity is only surfaced on the provisional view (PRD §3.5),
    # so we accept either presence or absence here.
    pq = data.get("pending_quantity")
    if pq is not None:
        assert isinstance(pq, int) and pq >= 0
    assert isinstance(data.get("wedding_id"), str)


def assert_purchase(data: dict) -> None:
    _assert_common_fields(data, "Purchase")
    assert isinstance(data.get("platform_code"), str)
    assert isinstance(data.get("external_purchase_id"), str)
    assert isinstance(data.get("purchaser_name"), str)
    assert isinstance(data.get("quantity"), int) and data["quantity"] >= 1
    assert is_iso8601_timestamp(data.get("occurred_at", ""))
    assert data.get("status") in _PURCHASE_STATES
    dup = data.get("dup_of_purchase_id")
    assert dup is None or isinstance(dup, str)
    assert isinstance(data.get("registry_item_id"), str)


def assert_thank_you_note(data: dict) -> None:
    _assert_common_fields(data, "ThankYouNote")
    assert data.get("status") in _THANK_YOU_STATES
    body = data.get("drafted_body")
    assert body is None or isinstance(body, str)
    sent_at = data.get("sent_at")
    assert sent_at is None or is_iso8601_timestamp(sent_at)
    assert isinstance(data.get("purchase_id"), str)
    assert isinstance(data.get("wedding_id"), str)
