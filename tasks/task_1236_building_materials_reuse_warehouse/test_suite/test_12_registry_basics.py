"""Registry basics: donor defaults, required fields, system-field handling,
pagination envelope (PRD §2.2, §2.3, §2.10, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    create_category,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

INTAKE = TEST_USERS["intake_staff_headers"]
MANAGER = TEST_USERS["store_manager_headers"]


# ---------------------------------------------------------------------------
# Corner: entities / donor_create_defaults_applied
# ---------------------------------------------------------------------------

def test_donor_create_defaults_applied(api):
    """PRD §3.1: "Everything a donor ever gives accumulates into a single `Donor`
    record, opened by an `IntakeStaff` operator or a `WarehouseAdmin` with a
    `full_name` (an individual or an organization), a `donor_type` of
    `INDIVIDUAL`, `BUSINESS`, or `CONTRACTOR`, a contact `email`, an optional
    `phone` that defaults to an empty string, and the `address_text` to which tax
    receipts are mailed. A donor is `ACTIVE` on creation"
    PRD §3.1: "A freshly registered donor starts at 0 cents and tier `NONE`."

    Design: Corner/entities/donor_create_defaults_applied
    """
    donor = validate_success(api.create_donor(
        {"full_name": "C One", "donor_type": "INDIVIDUAL",
         "email": "c1@x.com", "address_text": "1 Rd"},
        INTAKE), expected_status=201)
    assert donor["status"] == "ACTIVE"
    assert donor["recognition_tier"] == "NONE"
    assert donor["trailing_receipt_value_cents"] == 0
    assert donor["phone"] == "", "omitted phone defaults to an empty string"


# ---------------------------------------------------------------------------
# Corner: entities / donor_create_missing_required_email
# ---------------------------------------------------------------------------

def test_donor_create_missing_required_email(api):
    """PRD §2.10: "Malformed requests — a missing required field, a type mismatch,
    an unknown enum member, or a non-positive quantity where a positive one is
    required — fail with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: a donor is opened "with a `full_name` ..., a `donor_type` of
    `INDIVIDUAL`, `BUSINESS`, or `CONTRACTOR`, a contact `email`, an optional
    `phone` that defaults to an empty string, and the `address_text`" — only
    `phone` is optional.

    Design: Corner/entities/donor_create_missing_required_email
    """
    response = api.create_donor(
        {"full_name": "No Email", "donor_type": "INDIVIDUAL", "address_text": "2 Rd"},
        INTAKE)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Corner: entities / category_create_computed_field_input_ignored
# ---------------------------------------------------------------------------

def test_category_create_computed_field_input_ignored(api):
    """PRD §3.2: "Categories are born `ACCEPTING`, can be paused to `PAUSED` and
    resumed, and can be retired from either `ACCEPTING` or `PAUSED` to terminal
    `RETIRED`; retirement leaves existing items to finish their lifecycle but new
    offers and items naming the category are refused."

    Design: Corner/entities/category_create_computed_field_input_ignored
    """
    category = validate_success(api.create_category(
        {
            "code": "SYSFL", "display_name": "Sys Field", "pricing_model": "PER_UNIT",
            "base_rate_cents": 100, "hazmat_risk_flag": False,
            "markdown_after_days": 30, "markdown_step_pct": 0.20,
            "markdown_interval_days": 15, "max_markdown_steps": 2,
            "floor_price_pct": 0.40, "target_turn_days": 45,
            "acceptance_status": "RETIRED",
        },
        MANAGER), expected_status=201)
    assert category["acceptance_status"] == "ACCEPTING", (
        "acceptance status is system-managed at creation; client input is ignored")


# ---------------------------------------------------------------------------
# Corner: endpoints / category_list_pagination_envelope
# ---------------------------------------------------------------------------

def test_category_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of resources returned: it
    defaults to 10 when omitted, and clients may ask for no fewer than 1 and no
    more than 100 per page. The `offset` parameter says how many resources to skip
    and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries four pagination
    fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/category_list_pagination_envelope
    """
    for i in (1, 2, 3):
        create_category(code=f"PG{i}", display_name=f"Pg {i}")

    rows, meta = validate_paginated(api.list_categories(MANAGER, params={"limit": 2, "offset": 0}))
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    rows, meta = validate_paginated(api.list_categories(MANAGER, params={"limit": 2, "offset": 2}))
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
