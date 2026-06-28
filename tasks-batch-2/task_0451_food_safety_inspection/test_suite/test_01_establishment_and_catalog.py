"""Establishment creation, risk-category computation, catalog input validation, and listing.

Queue B (Corner) — section: entities.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    assert_establishment,
    create_establishment_payload, create_fda_food_code_payload,
    TEST_USERS, NON_EXISTENT_UUID,
)

CLERK = TEST_USERS["permit_clerk_headers"]
DIRECTOR = TEST_USERS["health_director_headers"]


def test_create_establishment_returns_201_with_system_fields(api):
    """PRD §2.4: "Each resource has an `id`, a unique server-minted UUID with no type
    prefix." and "a `version`, an integer that starts at the resource's creation and
    increments by one on every mutation of that resource."
    PRD §3.2: "A new establishment begins in the `PRELICENSE` status."

    Design: Corner/entities/entity_establishment_create_returns_201_with_system_fields
    """
    res = api.create_establishment(
        create_establishment_payload(name="Diner E1", address="1 Main St", seating_capacity=40),
        CLERK)
    est = validate_success(res, 201)
    assert_establishment(est)
    assert est["version"] == 1, f"new establishment version must be 1, got {est['version']}"
    assert est["status"] == "PRELICENSE", f"expected PRELICENSE, got {est['status']}"
    body = res.json()
    assert body["response_type"] == "object", "single-resource create is response_type object"


def test_create_establishment_missing_seating_capacity_rejected(api):
    """PRD §3.2: "a declared `seating_capacity` (a non-negative integer)".
    PRD §2.6: "Body well-formedness — required fields present ... is enforced with
    `ERR_INVALID_REQUEST` (HTTP 400) on every write endpoint."

    Design: Corner/entities/entity_establishment_missing_required_seating_capacity
    """
    payload = create_establishment_payload(name="Diner E1", address="1 Main St")
    payload.pop("seating_capacity", None)
    res = api.create_establishment(payload, CLERK)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_default_serves_raw_keeps_category_1(api):
    """PRD §3.2: "two optional boolean flags that both default to false:
    `serves_raw_animal_foods` ... and `does_onsite_processing`".
    PRD §3.2: "the base category is `CATEGORY_1`, but a seating capacity of at least 50
    raises the base to `CATEGORY_2`" and "365 days for `CATEGORY_1`".

    Design: Corner/entities/entity_establishment_default_serves_raw_false
    """
    res = api.create_establishment(
        create_establishment_payload(name="Diner E1", address="1 Main St", seating_capacity=40),
        CLERK)
    est = validate_success(res, 201)
    assert est["risk_category"] == "CATEGORY_1", f"seating 40 with no escalators is CATEGORY_1, got {est['risk_category']}"
    assert est["routine_interval_days"] == 365, f"CATEGORY_1 interval is 365, got {est['routine_interval_days']}"


def test_risk_category_escalators_reach_category_3(api):
    """PRD §3.2: "a seating capacity of at least 50 raises the base to `CATEGORY_2`".
    PRD §3.2: "Two escalators are then applied in their declared order, each lifting the
    category by exactly one band and capped at `CATEGORY_3`: first, if the establishment
    serves raw animal foods, the category is bumped up one band; then, if it does on-site
    processing, the category is bumped up one band again."
    PRD §3.2: "90 days for `CATEGORY_3`".

    Design: Corner/entities/entity_establishment_computed_risk_category_cat3_via_escalators
    """
    res = api.create_establishment(
        create_establishment_payload(
            name="Smokehouse", address="9 Pit Rd", seating_capacity=60,
            serves_raw_animal_foods=True, does_onsite_processing=True),
        CLERK)
    est = validate_success(res, 201)
    assert est["risk_category"] == "CATEGORY_3", (
        f"seating 60 (CAT2) + two escalators -> CATEGORY_3, got {est['risk_category']}")
    assert est["routine_interval_days"] == 90, f"CATEGORY_3 interval is 90, got {est['routine_interval_days']}"


def test_get_unknown_establishment_not_found(api):
    """PRD §2.5: "an unknown identifier yields the corresponding not-found error
    (for example `ERR_ESTABLISHMENT_NOT_FOUND` ...)."

    Design: Corner/entities/entity_establishment_get_not_found
    """
    res = api.get_establishment(NON_EXISTENT_UUID, CLERK)
    validate_error(res, "ERR_ESTABLISHMENT_NOT_FOUND", expected_status=404)


def test_create_fda_code_invalid_classification_rejected(api):
    """PRD §3.1: "a `classification` that is either `CRITICAL` or `NON_CRITICAL`".
    PRD §2.6: "Body well-formedness — required fields present, enum values valid, and
    integers within their declared ranges — is enforced with `ERR_INVALID_REQUEST`
    (HTTP 400) on every write endpoint."

    Design: Corner/entities/entity_fda_code_create_classification_invalid_enum
    """
    payload = create_fda_food_code_payload(
        code="X-1", title="Bad", classification="MAJOR", base_demerit_points=5)
    res = api.create_fda_food_code(payload, DIRECTOR)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_inspection_listing_returns_paginated_array_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the following
    fields in the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/entity_inspection_listing_pagination_envelope
    """
    res = api.list_inspections(DIRECTOR)
    data, meta = validate_paginated(res)
    assert isinstance(data, list), "inspection listing data must be an array"
    assert "total_count" in meta, "meta must carry total_count"
    assert "has_more" in meta, "meta must carry has_more"
    body = res.json()
    assert body["response_type"] == "array", "list endpoint is response_type array"
