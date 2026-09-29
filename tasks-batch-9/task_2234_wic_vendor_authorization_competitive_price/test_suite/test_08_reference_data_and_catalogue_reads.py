"""
Reference-data creates, catalogue reads, and the rejections that guard them.

Every test builds the state it needs through the documented endpoints, because
the server is restarted and the database emptied before each one runs.
"""

from test_helpers import (
    ANALYST_HEADERS,
    DEFAULT_LOGICAL_CLOCK_ISO,
    NON_EXISTENT_UUID,
    SUPERVISOR_HEADERS,
    ApiErrorId,
    assert_authorized_food_item,
    assert_field_values,
    assert_food_category,
    assert_no_data_payload,
    assert_peer_group,
    assert_vendor,
    factories,
    fixtures,
    make_vendor_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.types import (
    FoodItemStatus,
    FormulaRestrictionLevel,
    MarMethod,
    PeerGroupStatus,
    RiskFlag,
    RiskTier,
    StoreType,
    VendorStatus,
)


def test_create_peer_group_returns_declared_fields_and_defaults(api):
    """
    Creating a peer group echoes every declared input and seeds the computed fields.

    "The group declares the `store_type` it covers, one of `SUPERMARKET`, `SUPERSTORE`,
    `MEDIUM_GROCERY`, `SMALL_GROCERY`, or `PHARMACY`, and a monthly redemption volume
    band whose lower bound `min_monthly_redemption_cents` must be at least 0 and whose
    upper bound `max_monthly_redemption_cents` is either null, meaning the band is
    unbounded above, or a value at least equal to the lower bound."
    "The group also declares its competitive price criterion `mar_method`, one of
    `PEER_MEDIAN`, `PEER_PERCENTILE_75`, or `LOWEST_HALF_AVG`; a
    `competitive_allowance_pct` between 0 and 0.25 inclusive, expressed as a fraction
    rather than a percentage figure; a `min_submissions_for_ceiling` of at least 1, which
    defaults to 3 when the field is omitted from the create payload; and a
    `min_stock_multiplier` between 0.5 and 3.0 inclusive that scales every minimum stock
    requirement for its members."
    "A new peer group begins with `status` `ACTIVE`, a `member_count` of 0, and a null
    `retired_at`."
    "Operations that create a new resource — a peer group, a food category, an authorized
    food item, a vendor application, a price cycle, a price submission, a redemption
    claim, a reimbursement adjustment, or a sanction case — return `201 Created`."
    "Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`,
    and the server never falls back to real time."
    "All instants persisted and returned by the API use ISO 8601 UTC with three
    fractional digits."
    "`version` (integer): a counter that increments by one on every mutation of the row."

    Design: Corner/entities/create_peer_group_returns_declared_fields_and_defaults
    """
    payload = factories.peer_group_payload(
        code="PG-SUPER-A",
        store_type=StoreType.SUPERMARKET.value,
        min_monthly_redemption_cents=5_000_000,
        max_monthly_redemption_cents=20_000_000,
        mar_method=MarMethod.PEER_MEDIAN.value,
        competitive_allowance_pct=0.05,
        min_submissions_for_ceiling=3,
        min_stock_multiplier=1.5,
    )

    peer_group = validate_success(api.create_peer_group(payload, SUPERVISOR_HEADERS), 201)

    assert_peer_group(
        peer_group,
        code="PG-SUPER-A",
        store_type=StoreType.SUPERMARKET.value,
        min_monthly_redemption_cents=5_000_000,
        max_monthly_redemption_cents=20_000_000,
        mar_method=MarMethod.PEER_MEDIAN.value,
        competitive_allowance_pct=0.05,
        min_submissions_for_ceiling=3,
        min_stock_multiplier=1.5,
        status=PeerGroupStatus.ACTIVE.value,
        member_count=0,
        retired_at=None,
        version=1,
        created_at=DEFAULT_LOGICAL_CLOCK_ISO,
        updated_at=DEFAULT_LOGICAL_CLOCK_ISO,
    )


def test_get_vendor_returns_stored_data_after_create(api):
    """
    A recorded application reads back with every computed field at its baseline.

    "A `VendorUnitAnalyst` records an application with the store's `store_name`, its
    declared `store_type` from the same five-value list the peer groups use, and its
    self-reported `reported_monthly_redemption_cents`, which must be at least 0."
    "The new Vendor begins in `authorization_status` `APPLICANT` with a null
    `peer_group_id`, a `risk_score` of 0.0, and a `risk_tier` of `LOW`."
    "Every other computed field starts at its documented baseline:
    `reauth_completed_count`, `accepted_submission_count`, `open_finding_count`,
    `recoupment_balance_cents`, `avg_monthly_redemption_cents`, and `sanction_points` at
    0; `price_submission_complete` and `compliance_buy_required` and
    `reauthorization_hold` false; `risk_flag` `NONE`; and `authorized_at`,
    `reauthorization_due_at`, `training_type`, `training_completed_at`,
    `training_expires_at`, `cure_deadline_at`, `risk_epoch_at`, `reauth_blocked_reason`,
    `authorization_blocked_reason`, `disqualified_until`, and `denial_reason` all null."
    "All list and read endpoints expose the full field set of the resource they return,
    including computed fields, so that a client can observe a `version` before attempting
    a version-guarded write."

    Design: Corner/entities/get_vendor_returns_stored_data_after_create
    """
    created = fixtures.create_vendor(
        api,
        store_name="Alpha Market",
        store_type=StoreType.SUPERMARKET.value,
        reported_monthly_redemption_cents=6_000_000,
    )

    vendor = validate_success(api.get_vendor(created["id"], ANALYST_HEADERS))

    assert vendor["id"] == created["id"], (
        f"expected the read to return the created vendor, got {vendor}"
    )
    assert_vendor(
        vendor,
        store_name="Alpha Market",
        store_type=StoreType.SUPERMARKET.value,
        reported_monthly_redemption_cents=6_000_000,
        authorization_status=VendorStatus.APPLICANT.value,
        peer_group_id=None,
        authorized_at=None,
        reauthorization_due_at=None,
        reauth_completed_count=0,
        training_type=None,
        training_completed_at=None,
        training_expires_at=None,
        accepted_submission_count=0,
        price_submission_complete=False,
        open_finding_count=0,
        cure_deadline_at=None,
        compliance_buy_required=False,
        risk_flag=RiskFlag.NONE.value,
        risk_score=0.0,
        risk_tier=RiskTier.LOW.value,
        risk_epoch_at=None,
        reauthorization_hold=False,
        reauth_blocked_reason=None,
        authorization_blocked_reason=None,
        recoupment_balance_cents=0,
        avg_monthly_redemption_cents=0,
        sanction_points=0,
        disqualified_until=None,
        denial_reason=None,
        version=1,
    )


def test_list_authorized_food_items_filters_by_status_and_paginates(api):
    """
    The status filter fixes the counted population and the offset window rides on it.

    "List authorized food list items, filterable by category, UPC and status"
    "List endpoints accept two query parameters. `limit` caps the number of items
    returned; it defaults to 10, must be at least 1, and must not exceed 100. `offset` is
    the number of items to skip; it defaults to 0 and must not be negative."
    "Unless a specific endpoint says otherwise, list results are sorted by `created_at` in
    ascending order."
    "The `meta` object of every list response carries `limit`, `offset`, `total_count`,
    and `has_more`."
    "A new item begins `ACTIVE`, with `delisted_at` and `delist_reason` both null."
    "In the first hop, the item's `status` becomes `DELISTED` while `delisted_at` takes
    the logical clock and `delist_reason` is stored."

    Design: Corner/entities/list_authorized_food_items_filters_by_status_and_paginates
    """
    category = fixtures.create_food_category(api, code="MILK", name="Fluid Milk")
    item_one = fixtures.create_food_item(
        api, category["id"], upc="00011122233", brand="Statewide Dairy"
    )
    item_two = fixtures.create_food_item(
        api,
        category["id"],
        upc="00044455566",
        brand="Valley Dairy",
        required_for_authorization=False,
    )
    item_three = fixtures.create_food_item(
        api,
        category["id"],
        upc="00077788899",
        brand="Legacy Dairy",
        container_size_oz=64,
        required_for_authorization=False,
    )
    delisted = validate_success(
        api.delist_authorized_food_item(
            item_three["id"],
            factories.delist_payload(delist_reason="brand withdrawn by the manufacturer"),
            SUPERVISOR_HEADERS,
        )
    )
    assert_authorized_food_item(
        delisted,
        status=FoodItemStatus.DELISTED.value,
        delisted_at=DEFAULT_LOGICAL_CLOCK_ISO,
        delist_reason="brand withdrawn by the manufacturer",
    )

    # Two items remain ACTIVE, and skipping one of them leaves only the later-created one.
    active_page, active_meta = validate_paginated(
        api.list_authorized_food_items(
            SUPERVISOR_HEADERS,
            {"status": FoodItemStatus.ACTIVE.value, "limit": 1, "offset": 1},
        )
    )
    assert len(active_page) == 1, f"expected a single row on the page, got {active_page}"
    assert active_page[0]["id"] == item_two["id"], (
        f"expected the second-created ACTIVE item, got {active_page[0]}"
    )
    assert_field_values(
        active_meta, limit=1, offset=1, total_count=2, has_more=False
    )

    delisted_page, delisted_meta = validate_paginated(
        api.list_authorized_food_items(
            SUPERVISOR_HEADERS, {"status": FoodItemStatus.DELISTED.value}
        )
    )
    assert_field_values(delisted_meta, limit=10, offset=0, total_count=1, has_more=False)
    assert len(delisted_page) == 1, f"expected one delisted row, got {delisted_page}"
    assert_authorized_food_item(
        delisted_page[0],
        id=item_three["id"],
        upc="00077788899",
        status=FoodItemStatus.DELISTED.value,
        delisted_at=DEFAULT_LOGICAL_CLOCK_ISO,
        delist_reason="brand withdrawn by the manufacturer",
    )

    # Without a status filter the category holds all three rows, in creation order.
    category_page, category_meta = validate_paginated(
        api.list_authorized_food_items(
            SUPERVISOR_HEADERS, {"food_category_id": category["id"]}
        )
    )
    assert_field_values(category_meta, limit=10, offset=0, total_count=3, has_more=False)
    assert [row["id"] for row in category_page] == [
        item_one["id"],
        item_two["id"],
        item_three["id"],
    ], f"expected the three items in ascending created_at order, got {category_page}"


def test_get_vendor_with_unknown_id_returns_not_found(api):
    """
    An unresolved path identifier is answered by that entity's own 404, with no resource.

    "Path identifiers resolve, **left to right**. On every path-parameterised endpoint the
    segments are resolved in the order they appear in the URL, and the first unresolved
    segment decides the error: `ERR_PEER_GROUP_NOT_FOUND`, `ERR_FOOD_CATEGORY_NOT_FOUND`,
    `ERR_FOOD_ITEM_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_PRICE_CYCLE_NOT_FOUND`,
    `ERR_PRICE_SUBMISSION_NOT_FOUND`, `ERR_PRICE_CEILING_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CLAIM_LINE_NOT_FOUND`,
    `ERR_ADJUSTMENT_NOT_FOUND`, or `ERR_SANCTION_CASE_NOT_FOUND`, each HTTP 404."
    "The `error_id` is a unique, machine-readable string that identifies the specific
    error."
    "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/get_vendor_with_unknown_id_returns_not_found
    """
    vendor_response = api.get_vendor(NON_EXISTENT_UUID, ANALYST_HEADERS)

    validate_error(vendor_response, ApiErrorId.VENDOR_NOT_FOUND.value)
    assert_no_data_payload(vendor_response)

    peer_group_response = api.get_peer_group(NON_EXISTENT_UUID, ANALYST_HEADERS)

    validate_error(peer_group_response, ApiErrorId.PEER_GROUP_NOT_FOUND.value)
    assert_no_data_payload(peer_group_response)


def test_create_food_category_missing_required_field_returns_invalid_request(api):
    """
    A create that omits a required field is rejected and writes nothing.

    "A `FoodCategory` is created with a `code` unique across all categories and a display
    `name`, plus the rules that govern everything inside it: `is_formula` marks the
    category as infant formula; `formula_restriction_level` is `NONE`,
    `CONTRACT_BRAND_ONLY`, or `MEDICAL_DOC_REQUIRED`; `min_stock_units` (at least 0) is
    the baseline unit count a store must carry before the peer group multiplier is
    applied; `min_variety_count` (at least 0) is the number of distinct varieties
    required; `max_units_per_transaction` (at least 1) is the per-line quantity ceiling
    enforced during claim adjudication; and `stock_required` decides whether the category
    participates in minimum stock verification at all."
    "Request shape: required fields present, enum values in range, integers not negative,"
    "Otherwise `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_food_category_missing_required_field_returns_invalid_request
    """
    incomplete = factories.food_category_payload(code="MILK", name="Fluid Milk")
    del incomplete["min_stock_units"]

    validate_error(
        api.create_food_category(incomplete, SUPERVISOR_HEADERS),
        ApiErrorId.INVALID_REQUEST.value,
    )

    # The rejected create stored nothing, so the same code is still free to use.
    complete = factories.food_category_payload(
        code="MILK",
        name="Fluid Milk",
        is_formula=False,
        formula_restriction_level=FormulaRestrictionLevel.NONE.value,
        min_stock_units=4,
        min_variety_count=2,
        max_units_per_transaction=6,
        stock_required=True,
    )

    category = validate_success(
        api.create_food_category(complete, SUPERVISOR_HEADERS), 201
    )

    assert_food_category(
        category,
        code="MILK",
        name="Fluid Milk",
        is_formula=False,
        formula_restriction_level=FormulaRestrictionLevel.NONE.value,
        min_stock_units=4,
        min_variety_count=2,
        max_units_per_transaction=6,
        stock_required=True,
        version=1,
    )


def test_create_peer_group_omitting_min_submissions_applies_default_three(api):
    """
    An omitted ceiling threshold is stored as three, and a zero allowance is kept as zero.

    "a `min_submissions_for_ceiling` of at least 1, which defaults to 3 when the field is
    omitted from the create payload"
    "a `competitive_allowance_pct` between 0 and 0.25 inclusive, expressed as a fraction
    rather than a percentage figure"
    "A new peer group begins with `status` `ACTIVE`, a `member_count` of 0, and a null
    `retired_at`."
    "All list and read endpoints expose the full field set of the resource they return,
    including computed fields, so that a client can observe a `version` before attempting
    a version-guarded write."

    Design: Corner/entities/create_peer_group_omitting_min_submissions_applies_default_three
    """
    payload = factories.peer_group_payload(
        code="PG-SMALL-DEFAULTS",
        store_type=StoreType.SMALL_GROCERY.value,
        min_monthly_redemption_cents=0,
        max_monthly_redemption_cents=1_000_000,
        mar_method=MarMethod.PEER_MEDIAN.value,
        competitive_allowance_pct=0.0,
        min_submissions_for_ceiling=None,
        min_stock_multiplier=0.5,
    )
    assert "min_submissions_for_ceiling" not in payload, (
        f"the create payload must omit the threshold, got {payload}"
    )

    created = validate_success(api.create_peer_group(payload, SUPERVISOR_HEADERS), 201)

    assert_peer_group(
        created,
        code="PG-SMALL-DEFAULTS",
        store_type=StoreType.SMALL_GROCERY.value,
        min_monthly_redemption_cents=0,
        max_monthly_redemption_cents=1_000_000,
        competitive_allowance_pct=0.0,
        min_submissions_for_ceiling=3,
        min_stock_multiplier=0.5,
        status=PeerGroupStatus.ACTIVE.value,
        member_count=0,
        retired_at=None,
        version=1,
    )

    stored = validate_success(api.get_peer_group(created["id"], SUPERVISOR_HEADERS))

    assert_field_values(
        stored,
        id=created["id"],
        min_submissions_for_ceiling=3,
        competitive_allowance_pct=0.0,
        min_stock_multiplier=0.5,
        version=1,
    )


def test_create_vendor_extra_field_input_ignored(api):
    """
    Fields the vendor create does not declare cannot override server-managed values.

    "A `VendorUnitAnalyst` records an application with the store's `store_name`, its
    declared `store_type` from the same five-value list the peer groups use, and its
    self-reported `reported_monthly_redemption_cents`, which must be at least 0."
    "The new Vendor begins in `authorization_status` `APPLICANT` with a null
    `peer_group_id`, a `risk_score` of 0.0, and a `risk_tier` of `LOW`."
    "`id` (string): a server-minted UUID."
    "`created_at` (string): an ISO 8601 UTC timestamp with three fractional digits
    recording when the row was first written."
    "`version` (integer): a counter that increments by one on every mutation of the row."
    "A peer group's `member_count` is the number of vendors assigned to it whose
    `authorization_status` is `AUTHORIZED`, `REAUTH_PENDING`, or `SUSPENDED`."

    Design: Corner/entities/create_vendor_extra_field_input_ignored
    """
    peer_group = fixtures.create_peer_group(api)
    smuggled_id = "11111111-1111-1111-1111-111111111111"
    payload = factories.vendor_payload(
        store_name="Alpha Market",
        store_type=StoreType.SUPERMARKET.value,
        reported_monthly_redemption_cents=6_000_000,
        id=smuggled_id,
        created_at="2001-01-01T00:00:00.000Z",
        version=99,
        authorization_status=VendorStatus.AUTHORIZED.value,
        peer_group_id=peer_group["id"],
        risk_score=100.0,
        risk_tier=RiskTier.HIGH.value,
        sanction_points=7,
    )

    vendor = validate_success(api.create_vendor(payload, ANALYST_HEADERS), 201)

    assert vendor["id"] != smuggled_id, (
        f"expected a server-minted id, got the client's own {vendor['id']!r}"
    )
    assert_vendor(
        vendor,
        store_name="Alpha Market",
        store_type=StoreType.SUPERMARKET.value,
        reported_monthly_redemption_cents=6_000_000,
        created_at=DEFAULT_LOGICAL_CLOCK_ISO,
        updated_at=DEFAULT_LOGICAL_CLOCK_ISO,
        version=1,
        authorization_status=VendorStatus.APPLICANT.value,
        peer_group_id=None,
        risk_score=0.0,
        risk_tier=RiskTier.LOW.value,
        sanction_points=0,
    )

    untouched = validate_success(api.get_peer_group(peer_group["id"], SUPERVISOR_HEADERS))

    assert_field_values(untouched, member_count=0, version=1)


def test_create_price_submission_with_unknown_food_item_id_returns_not_found(api):
    """
    Body foreign keys are resolved in declared order, so the first bad one names the error.

    "Body foreign keys resolve, in the order the endpoint's input list declares them, on
    `POST /authorized-food-items`, `POST /price-submissions`, `POST /monitoring-visits`,
    `POST /monitoring-visits/{id}/observations`, `POST /redemption-claims`,
    `POST /reimbursement-adjustments`, and `POST /sanction-cases`. The same 404 family
    applies — an unresolvable `food_item_id` yields `ERR_FOOD_ITEM_NOT_FOUND`, an
    unresolvable `vendor_id` yields `ERR_VENDOR_NOT_FOUND`, an unresolvable
    `source_visit_id` yields `ERR_VISIT_NOT_FOUND`, an unresolvable
    `redemption_claim_id` yields `ERR_CLAIM_NOT_FOUND`, an unresolvable
    `food_category_id` yields `ERR_FOOD_CATEGORY_NOT_FOUND`, and an unresolvable
    `price_cycle_id` yields `ERR_PRICE_CYCLE_NOT_FOUND`."
    "A `VendorOperator` reports a shelf price by supplying the `vendor_id` it is acting
    as, the `food_item_id` being priced, the `price_cycle_id` it belongs to, and the
    `shelf_price_cents` for one container, which must be at least 1."

    Design: Corner/entities/create_price_submission_with_unknown_food_item_id_returns_not_found
    """
    cycle = fixtures.create_price_cycle(api)
    vendor = fixtures.create_vendor(api)

    # vendor_id resolves, so the unresolvable food_item_id decides the error even though
    # the price_cycle_id is unresolvable too.
    item_missing = api.create_price_submission(
        factories.price_submission_payload(
            vendor["id"], NON_EXISTENT_UUID, NON_EXISTENT_UUID, 320
        ),
        make_vendor_operator_headers(vendor["id"]),
    )

    validate_error(item_missing, ApiErrorId.FOOD_ITEM_NOT_FOUND.value)

    # With the vendor_id itself unresolvable, the earlier-declared key wins instead.
    vendor_missing = api.create_price_submission(
        factories.price_submission_payload(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, cycle["id"], 320
        ),
        make_vendor_operator_headers(NON_EXISTENT_UUID),
    )

    validate_error(vendor_missing, ApiErrorId.VENDOR_NOT_FOUND.value)

    submissions, meta = validate_paginated(api.list_price_submissions(ANALYST_HEADERS))

    assert submissions == [], f"expected no submission to be stored, got {submissions}"
    assert_field_values(meta, total_count=0, limit=10, offset=0, has_more=False)


def test_create_peer_group_with_unknown_store_type_returns_invalid_request(api):
    """
    An out-of-range enum or fraction is a shape rejection, and the inclusive edge passes.

    "The group declares the `store_type` it covers, one of `SUPERMARKET`, `SUPERSTORE`,
    `MEDIUM_GROCERY`, `SMALL_GROCERY`, or `PHARMACY`"
    "a `competitive_allowance_pct` between 0 and 0.25 inclusive, expressed as a fraction
    rather than a percentage figure"
    "Request shape: required fields present, enum values in range, integers not negative,
    `recoupment_rate` greater than 0 and at most 1, `competitive_allowance_pct` at least
    0 and at most 0.25"
    "Otherwise `ERR_INVALID_REQUEST` (HTTP 422)."
    "The `meta` object of every list response carries `limit`, `offset`, `total_count`,
    and `has_more`."

    Design: Corner/entities/create_peer_group_with_unknown_store_type_returns_invalid_request
    """
    bad_store_type = factories.peer_group_payload(
        code="PG-CONVENIENCE", store_type="CONVENIENCE"
    )

    validate_error(
        api.create_peer_group(bad_store_type, SUPERVISOR_HEADERS),
        ApiErrorId.INVALID_REQUEST.value,
    )

    over_allowance = factories.peer_group_payload(
        code="PG-OVER-ALLOWANCE", competitive_allowance_pct=0.26
    )

    validate_error(
        api.create_peer_group(over_allowance, SUPERVISOR_HEADERS),
        ApiErrorId.INVALID_REQUEST.value,
    )

    at_the_edge = factories.peer_group_payload(
        code="PG-EDGE-ALLOWANCE", competitive_allowance_pct=0.25
    )

    accepted = validate_success(
        api.create_peer_group(at_the_edge, SUPERVISOR_HEADERS), 201
    )

    assert_peer_group(
        accepted,
        code="PG-EDGE-ALLOWANCE",
        competitive_allowance_pct=0.25,
        status=PeerGroupStatus.ACTIVE.value,
        version=1,
    )

    groups, meta = validate_paginated(api.list_peer_groups(SUPERVISOR_HEADERS))

    assert_field_values(meta, total_count=1, limit=10, offset=0, has_more=False)
    assert [group["id"] for group in groups] == [accepted["id"]], (
        f"expected only the accepted peer group to have been stored, got {groups}"
    )


def test_duplicate_natural_keys_rejected_and_upc_uniqueness_is_active_scoped(api):
    """
    Codes are unique outright, while a UPC is unique only among the items still active.

    "A **peer group** is created with a `code` — a human-readable label between 1 and 32
    characters, unique across all peer groups regardless of their status, compared
    case-sensitively, so `SUPER-A` and `super-a` are two different codes and both may
    exist."
    "A `FoodCategory` is created with a `code` unique across all categories and a display
    `name`"
    "The `upc` must be unique among items whose `status` is `ACTIVE`; a delisted item's
    UPC may be reused, and duplicate live UPCs are refused with `ERR_DUPLICATE_UPC`."
    "Peer group `code` uniqueness on `POST /peer-groups` — otherwise
    `ERR_DUPLICATE_PEER_GROUP_CODE`."
    "Food category `code` uniqueness on `POST /food-categories` — otherwise
    `ERR_DUPLICATE_FOOD_CATEGORY_CODE`."
    "`upc` uniqueness among `ACTIVE` items on `POST /authorized-food-items` — otherwise
    `ERR_DUPLICATE_UPC`."
    "In the first hop, the item's `status` becomes `DELISTED` while `delisted_at` takes
    the logical clock and `delist_reason` is stored."
    "List authorized food list items, filterable by category, UPC and status"

    Design: Corner/errors/duplicate_natural_keys_rejected_and_upc_uniqueness_is_active_scoped
    """
    fixtures.create_peer_group(api, code="PG-SUPER-A")
    category = fixtures.create_food_category(api, code="MILK", name="Fluid Milk")
    original = fixtures.create_food_item(api, category["id"], upc="00011122233")

    duplicate_group = factories.peer_group_payload(
        code="PG-SUPER-A",
        store_type=StoreType.PHARMACY.value,
        min_monthly_redemption_cents=0,
        max_monthly_redemption_cents=100_000,
        mar_method=MarMethod.PEER_PERCENTILE_75.value,
        competitive_allowance_pct=0.10,
        min_stock_multiplier=0.5,
    )

    validate_error(
        api.create_peer_group(duplicate_group, SUPERVISOR_HEADERS),
        ApiErrorId.DUPLICATE_PEER_GROUP_CODE.value,
    )

    duplicate_category = factories.food_category_payload(
        code="MILK",
        name="Infant Formula",
        is_formula=True,
        formula_restriction_level=FormulaRestrictionLevel.MEDICAL_DOC_REQUIRED.value,
        min_stock_units=1,
        min_variety_count=1,
        max_units_per_transaction=2,
        stock_required=False,
    )

    validate_error(
        api.create_food_category(duplicate_category, SUPERVISOR_HEADERS),
        ApiErrorId.DUPLICATE_FOOD_CATEGORY_CODE.value,
    )

    rival = factories.authorized_food_item_payload(
        category["id"],
        upc="00011122233",
        brand="Rival Dairy",
        container_size_oz=64,
        contract_brand=True,
        required_for_authorization=False,
    )

    validate_error(
        api.create_authorized_food_item(rival, SUPERVISOR_HEADERS),
        ApiErrorId.DUPLICATE_UPC.value,
    )

    delisted = validate_success(
        api.delist_authorized_food_item(
            original["id"],
            factories.delist_payload(delist_reason="brand withdrawn by the manufacturer"),
            SUPERVISOR_HEADERS,
        )
    )

    assert_authorized_food_item(
        delisted,
        id=original["id"],
        status=FoodItemStatus.DELISTED.value,
        delisted_at=DEFAULT_LOGICAL_CLOCK_ISO,
        delist_reason="brand withdrawn by the manufacturer",
    )

    # The very same body now succeeds, because no ACTIVE item holds that UPC any more.
    reissued = validate_success(
        api.create_authorized_food_item(rival, SUPERVISOR_HEADERS), 201
    )

    assert_authorized_food_item(
        reissued,
        upc="00011122233",
        brand="Rival Dairy",
        status=FoodItemStatus.ACTIVE.value,
        delisted_at=None,
        delist_reason=None,
        version=1,
    )
    assert reissued["id"] != original["id"], (
        "the reissued UPC must be a new row, not the delisted one"
    )

    all_rows, all_meta = validate_paginated(
        api.list_authorized_food_items(SUPERVISOR_HEADERS, {"upc": "00011122233"})
    )

    assert_field_values(all_meta, total_count=2)  # one DELISTED plus one ACTIVE
    assert {row["id"] for row in all_rows} == {original["id"], reissued["id"]}, (
        f"expected both rows to survive under the reused UPC, got {all_rows}"
    )

    active_rows, active_meta = validate_paginated(
        api.list_authorized_food_items(
            SUPERVISOR_HEADERS,
            {"upc": "00011122233", "status": FoodItemStatus.ACTIVE.value},
        )
    )

    assert_field_values(active_meta, total_count=1)
    assert [row["id"] for row in active_rows] == [reissued["id"]], (
        f"expected only the reissued item to be ACTIVE, got {active_rows}"
    )
