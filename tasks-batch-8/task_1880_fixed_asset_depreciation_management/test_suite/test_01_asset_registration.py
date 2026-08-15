"""Asset registration, asset-class policy, envelope, and pagination claims."""
from test_helpers import (
    ACCT,
    CLERK,
    CTRL,
    NON_EXISTENT_UUID,
    TAX,
    ApiErrorId,
    assert_asset_class,
    assert_fixed_asset,
    create_asset,
    create_asset_class_payload,
    create_class,
    create_fixed_asset_payload,
    create_in_service_asset,
    create_inventory_run,
    create_open_review,
    create_project,
    create_schedule,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_asset_class_and_get_it_back(api):
    """PRD §3.1: "A `Controller` defines an **asset class** — the capitalization
    policy for a family of assets — by supplying a unique `class_code`, a display
    `name`, the `capitalization_threshold_cents` below which no cost may be
    capitalized, a `default_useful_life_months` greater than zero, the default
    `book_method` (either `STRAIGHT_LINE` or `DOUBLE_DECLINING`), the default
    `tax_method` (one of `MACRS_5YR`, `MACRS_7YR`, or `TAX_STRAIGHT_LINE`), and a
    `bonus_depreciation_allowed` flag controlling whether assets of the class may
    elect first-year bonus depreciation."
    PRD §2.4: "an integer `version` that starts at 1 on creation and increments
    by 1 on every mutation of that resource"

    Design: Corner/entities/create_asset_class_and_get_it_back
    """
    created = validate_success(
        api.create_asset_class(
            create_asset_class_payload(
                class_code="FURN",
                name="Furniture",
                capitalization_threshold_cents=100000,
                default_useful_life_months=36,
                book_method="STRAIGHT_LINE",
                tax_method="TAX_STRAIGHT_LINE",
                bonus_depreciation_allowed=False,
            ),
            CTRL,
        ),
        201,
    )
    assert_asset_class(created)
    assert is_valid_uuid(created["id"])
    assert is_iso8601_timestamp(created["created_at"])
    assert is_iso8601_timestamp(created["updated_at"])
    assert created["version"] == 1

    fetched = validate_success(api.get_asset_class(created["id"], TAX), 200)
    assert_asset_class(fetched)
    assert fetched["id"] == created["id"]
    assert fetched["class_code"] == "FURN"
    assert fetched["name"] == "Furniture"
    assert fetched["capitalization_threshold_cents"] == 100000
    assert fetched["default_useful_life_months"] == 36
    assert fetched["book_method"] == "STRAIGHT_LINE"
    assert fetched["tax_method"] == "TAX_STRAIGHT_LINE"
    assert fetched["bonus_depreciation_allowed"] is False


def test_create_asset_missing_required_field_returns_invalid_request(api):
    """PRD §2.10: "A malformed payload — a missing required field, an unknown
    enum value, or a wrongly typed value — is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400) before any business rule is evaluated."
    PRD §3.2: "A directly purchased asset is registered by an `AssetAccountant`
    with a unique `asset_tag` (duplicates rejected with `ERR_DUPLICATE_TAG`), a
    free-text `description`, the `asset_class_id`, an `acquisition_cost_cents`
    strictly greater than zero, the owning `cost_center`, and a `location` code."

    Design: Corner/entities/create_asset_missing_required_field_returns_invalid_request
    """
    cls = create_class()
    payload = {
        "asset_tag": "A-001",
        "description": "No cost",
        "asset_class_id": cls["id"],
        "cost_center": "CC1",
        "location": "PLANT-1",
    }
    resp = api.create_fixed_asset(payload, ACCT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(api.list_fixed_assets(ACCT))
    assert meta["total_count"] == 0 and rows == [], (
        "rejected create must not persist a FixedAsset row"
    )


def test_asset_defaults_pulled_from_class(api):
    """PRD §3.2: "Four policy fields may be overridden at registration or left to
    default from the class: `salvage_value_cents` (default zero; it must be at
    least zero and strictly less than `acquisition_cost_cents`, else
    `ERR_INVALID_SALVAGE_VALUE`), `useful_life_months` (defaulting from the
    class's `default_useful_life_months`), `book_method`, and `tax_method`."
    PRD §3.2: "The `bonus_elected` flag defaults to false"
    PRD §3.2: "A directly registered asset is born in status `DRAFT` with
    `source` equal to `PURCHASE`."

    Design: Corner/entities/asset_defaults_pulled_from_class
    """
    cls = create_class(bonus_depreciation_allowed=True)
    asset = validate_success(
        api.create_fixed_asset(
            create_fixed_asset_payload(
                cls["id"],
                asset_tag="A-002",
                description="Defaults asset",
                acquisition_cost_cents=500000,
            ),
            ACCT,
        ),
        201,
    )
    assert_fixed_asset(asset)
    assert asset["salvage_value_cents"] == 0
    assert asset["useful_life_months"] == 60
    assert asset["book_method"] == "STRAIGHT_LINE"
    assert asset["tax_method"] == "MACRS_5YR"
    assert asset["bonus_elected"] is False
    assert asset["source"] == "PURCHASE"
    assert asset["status"] == "DRAFT"


def test_get_asset_not_found_returns_404(api):
    """PRD §2.10: "**(3) existence** — every path id and every body foreign-key
    reference must resolve (`ERR_NOT_FOUND`, or `ERR_ASSET_NOT_IN_SCOPE` for a
    count line whose asset was not seeded into the run)"

    Design: Corner/entities/get_asset_not_found_returns_404
    """
    resp = api.get_fixed_asset(NON_EXISTENT_UUID, ACCT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_component_below_threshold_rejected(api):
    """PRD §3.2: "Because a minor repair is an expense rather than an asset, a
    component whose `acquisition_cost_cents` is below its class's
    `capitalization_threshold_cents` is rejected with
    `ERR_BELOW_CAPITALIZATION_THRESHOLD` and must be expensed outside the system
    instead."

    Design: Corner/entities/component_below_threshold_rejected
    """
    cls = create_class()
    parent = create_in_service_asset(
        cls["id"], asset_tag="A-005", acquisition_cost_cents=600000
    )
    resp = api.create_fixed_asset(
        create_fixed_asset_payload(
            cls["id"],
            asset_tag="A-005-R",
            description="Minor repair",
            acquisition_cost_cents=100000,
            parent_asset_id=parent["id"],
        ),
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_BELOW_CAPITALIZATION_THRESHOLD, 422)

    rows, _meta = validate_paginated(
        api.list_fixed_assets(ACCT, params={"parent_asset_id": parent["id"]})
    )
    assert rows == [], "below-threshold component must not be persisted"


def test_cost_line_with_unknown_project_not_found(api):
    """PRD §2.10: "**(3) existence** — every path id and every body foreign-key
    reference must resolve (`ERR_NOT_FOUND`, or `ERR_ASSET_NOT_IN_SCOPE` for a
    count line whose asset was not seeded into the run)"

    Design: Corner/entities/cost_line_with_unknown_project_not_found
    """
    resp = api.create_cip_cost_line(
        {
            "project_id": NON_EXISTENT_UUID,
            "amount_cents": 1000,
            "cost_type": "OTHER",
            "incurred_date": "2026-01-01",
        },
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_asset_list_pagination_envelope(api):
    """PRD §2.3: "List responses include `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object, where `total_count` reports the full number
    of matching records and `has_more` indicates whether records remain beyond
    the returned window."
    PRD §2.3: "Unless a list endpoint states otherwise, results are sorted by
    `created_at` in ascending order."

    Design: Corner/entities/asset_list_pagination_envelope
    """
    cls = create_class()
    first = create_asset(cls["id"], asset_tag="A-010", description="One",
                         acquisition_cost_cents=500000)
    second = create_asset(cls["id"], asset_tag="A-011", description="Two",
                          acquisition_cost_cents=600000)

    page1, meta1 = validate_paginated(
        api.list_fixed_assets(CLERK, params={"limit": 1, "offset": 0})
    )
    assert len(page1) == 1
    assert meta1["limit"] == 1
    assert meta1["offset"] == 0
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_fixed_assets(CLERK, params={"limit": 1, "offset": 1})
    )
    assert len(page2) == 1
    assert meta2["offset"] == 1
    assert meta2["has_more"] is False

    paged_ids = {page1[0]["id"], page2[0]["id"]}
    assert paged_ids == {first["id"], second["id"]}, (
        "the two pages together contain both assets with no overlap"
    )


def test_initial_states_on_creation(api):
    """PRD §3.1: "The project is born in status `OPEN`, its
    `total_accumulated_cents` starts at zero"
    PRD §3.2: "A directly registered asset is born in status `DRAFT` with
    `source` equal to `PURCHASE`."
    PRD §3.3: "Creating a run requires only the target `period`; the run is born
    `OPEN`"
    PRD §3.4: "At most one review per asset may be `OPEN` at a time — a second
    open attempt is rejected with `ERR_IMPAIRMENT_REVIEW_OPEN`."
    PRD §3.5: "A new request is born in status `REQUESTED` with the requester's
    `X-User-ID` recorded as `requested_by_user_id`."
    PRD §3.6: "The run is born in status `COUNTING`."
    PRD §3.7: "The row is born in status `IMPORTED`."

    Design: Corner/state_machines/initial_states_on_creation
    """
    cls = create_class()
    asset = create_asset(cls["id"], asset_tag="A-020",
                         acquisition_cost_cents=500000)
    assert asset["status"] == "DRAFT"
    asset = validate_success(
        api.place_in_service(asset["id"], {"in_service_date": "2026-01-10"}, ACCT),
        200,
    )
    assert asset["status"] == "IN_SERVICE"

    project = create_project(cls["id"], project_code="PROJ-I", name="Init")
    assert project["status"] == "OPEN"
    assert project["total_accumulated_cents"] == 0

    disposal = validate_success(
        api.create_disposal(
            {"asset_id": asset["id"], "disposal_type": "SCRAP",
             "effective_date": "2026-06-15"},
            ACCT,
        ),
        201,
    )
    assert disposal["status"] == "REQUESTED"
    assert disposal["requested_by_user_id"] == "u_acct_1"

    review = create_open_review(asset["id"], indicator="DAMAGE")
    assert review["status"] == "OPEN"

    run = validate_success(
        api.create_depreciation_run({"period": "2026-01"}, ACCT), 201
    )
    assert run["status"] == "OPEN"

    schedule = create_schedule(
        asset["id"], schedule_type="PROPERTY_TAX", schedule_year=2026,
        assessed_value_cents=8000000,
    )
    assert schedule["status"] == "IMPORTED"

    inv_run = create_inventory_run(name="Init run", scope_type="ALL")
    assert inv_run["status"] == "COUNTING"


def test_invalid_enum_value_returns_invalid_request(api):
    """PRD §2.10: "A malformed payload — a missing required field, an unknown
    enum value, or a wrongly typed value — is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400) before any business rule is evaluated."
    PRD §3.1: "the default `book_method` (either `STRAIGHT_LINE` or
    `DOUBLE_DECLINING`)"

    Design: Corner/validations/invalid_enum_value_returns_invalid_request
    """
    cls = create_class()
    resp = api.create_fixed_asset(
        create_fixed_asset_payload(
            cls["id"], asset_tag="A-051", acquisition_cost_cents=500000,
            book_method="SIDWAYS",
        ),
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_salvage_equal_cost_rejected(api):
    """PRD §3.2: "`salvage_value_cents` (default zero; it must be at least zero
    and strictly less than `acquisition_cost_cents`, else
    `ERR_INVALID_SALVAGE_VALUE`)"

    Design: Corner/validations/salvage_equal_cost_rejected
    """
    cls = create_class()
    resp = api.create_fixed_asset(
        create_fixed_asset_payload(
            cls["id"], asset_tag="A-042", acquisition_cost_cents=500000,
            salvage_value_cents=500000,
        ),
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_SALVAGE_VALUE, 422)


def test_bonus_on_disallowing_class_rejected(api):
    """PRD §3.2: "The `bonus_elected` flag defaults to false; setting it to true
    elects first-year bonus depreciation and is permitted only when the class's
    `bonus_depreciation_allowed` is true — otherwise the registration is rejected
    with `ERR_BONUS_NOT_ALLOWED`."

    Design: Corner/validations/bonus_on_disallowing_class_rejected
    """
    cls = create_class(
        class_code="VEH", name="Vehicles", tax_method="MACRS_7YR",
        bonus_depreciation_allowed=False,
    )
    resp = api.create_fixed_asset(
        create_fixed_asset_payload(
            cls["id"], asset_tag="A-044", acquisition_cost_cents=500000,
            bonus_elected=True,
        ),
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_BONUS_NOT_ALLOWED, 422)


def test_duplicate_asset_tag_rejected(api):
    """PRD §3.2: "A directly purchased asset is registered by an
    `AssetAccountant` with a unique `asset_tag` (duplicates rejected with
    `ERR_DUPLICATE_TAG`)"

    Design: Corner/validations/duplicate_asset_tag_rejected
    """
    cls = create_class()
    create_asset(cls["id"], asset_tag="A-050", description="First",
                 acquisition_cost_cents=500000)
    resp = api.create_fixed_asset(
        create_fixed_asset_payload(
            cls["id"], asset_tag="A-050", description="Duplicate tag",
            acquisition_cost_cents=600000, cost_center="CC2", location="PLANT-2",
        ),
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TAG, 409)
