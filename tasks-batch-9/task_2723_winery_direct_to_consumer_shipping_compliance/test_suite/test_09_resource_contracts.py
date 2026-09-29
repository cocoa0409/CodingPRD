"""Resource contracts of the Winery DTC Shipping Compliance API.

Creation, retrieval, listing, path- and body-level resolution, declared
defaults, computed fields, system-managed identity and immutability.  Every
expectation below is quoted from PRD.md and nothing else.
"""

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import DtcApiClient  # noqa: F401  (client under test)
from test_helpers.assertions import (
    assert_cents,
    assert_immutable_identity,
    assert_instant_equals,
    assert_liters,
    assert_order_dimensions,
    assert_request_id,
    assert_system_timestamp,
    assert_versioned_identity,
)
from test_helpers.constants import (
    CLOCK_DEFAULT_CANONICAL,
    DEFAULT_LIMIT,
    DEFAULT_MIN_PURCHASER_AGE,
    DEFAULT_OFFSET,
    DEFAULT_RENEWAL_LEAD_DAYS,
)
from test_helpers.fixtures import (
    append_manual_adjustment,
    create_consumer,
    create_state_rule,
    create_winery,
    set_clock,
)
from test_helpers.test_users import ADMIN, OFFICER_A


def _rows(response):
    """The data array of a list response, together with its meta window."""
    return validate_paginated(response)


# ---------------------------------------------------------------------------
# Winery creation and retrieval
# ---------------------------------------------------------------------------
def test_winery_creation_returns_every_declared_field(api, clock):
    """Registration answers 201 with every field already at its opening value.

    "A freshly registered winery opens in `status` `ACTIVE` with
    `suspension_reason` null, with `excise_accrued_cents`,
    `excise_reversed_cents`, `suspended_subscription_count` and
    `open_exception_count` all at 0, and at `version` 1." (PRD 3.1)

    "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`." (PRD 2.2)

    Design: Corner/entities/winery_creation_returns_201_with_every_declared_field
    """
    response = api.create_winery(f.winery_payload(), ADMIN)
    data = validate_success(response, expected_status=201)

    body = response.json()
    assert body["response_type"] == "object"
    assert_request_id(body["meta"])
    assert_system_timestamp(body["meta"]["api_request_timestamp"])

    assert data["name"] == "Estate 1"
    assert data["ttb_permit_number"] == "TTB-1001"
    assert data["home_state_code"] == "CA"
    assert data["annual_production_gallons"] == 120000

    assert data["status"] == "ACTIVE"
    assert data["suspension_reason"] is None
    assert_cents(data["excise_accrued_cents"], 0, "excise_accrued_cents")
    assert_cents(data["excise_reversed_cents"], 0, "excise_reversed_cents")
    assert data["suspended_subscription_count"] == 0
    assert data["open_exception_count"] == 0

    assert_versioned_identity(data, expected_version=1)
    assert_instant_equals(data["created_at"], CLOCK_DEFAULT_CANONICAL)
    assert_instant_equals(data["updated_at"], CLOCK_DEFAULT_CANONICAL)
    assert is_valid_uuid(data["id"]) and len(data["id"]) == 36
    assert "_" not in data["id"]


def test_winery_retrieval_returns_the_stored_row_unchanged(api, clock):
    """A read is not a mutation, so version and updated_at do not move.

    "**`version`** (integer): a counter that starts at 1 when the row is created
    and increments by exactly 1 on every mutation of that row." (PRD 2.5)

    "**`updated_at`** (string): an ISO 8601 UTC timestamp in the same format,
    refreshed on every mutation of the row, including mutations the server
    performs on its own initiative during a cascade." (PRD 2.5)

    Design: Corner/entities/winery_retrieval_returns_the_stored_row_unchanged
    """
    created = create_winery(api)

    data = validate_success(api.get_winery(created["id"], ADMIN), expected_status=200)

    assert data["id"] == created["id"]
    assert data["name"] == "Estate 1"
    assert data["annual_production_gallons"] == 120000
    assert data["status"] == "ACTIVE"
    assert_versioned_identity(data, expected_version=1)
    assert_instant_equals(data["updated_at"], CLOCK_DEFAULT_CANONICAL)
    assert_instant_equals(data["updated_at"], data["created_at"])


# ---------------------------------------------------------------------------
# Listing and pagination
# ---------------------------------------------------------------------------
def test_consumers_list_reports_its_window_and_the_whole_filtered_count(api, clock):
    """limit/offset window the page while total_count counts the collection.

    "`limit` sets the maximum number of items returned; when it is omitted it
    defaults to 10, its minimum accepted value is 1 and its maximum accepted
    value is 100. `offset` sets the number of items to skip before the window
    begins; when it is omitted it defaults to 0." (PRD 2.3)

    "`total_count` is the number of items matching the filter across the entire
    collection, not the number in the returned page, and `has_more` is true
    exactly when items remain beyond the current window." (PRD 2.3)

    "A new consumer opens with `id_verification_method` at `NONE`,
    `id_verified_at` null, `rolling_liters_by_state` and
    `rolling_liters_settled_by_state` both empty maps, `return_credit_count` and
    `denied_exception_count` at 0, `risk_score_screening` and `risk_score_audit`
    at 0, and `screening_tier` at `STANDARD`." (PRD 3.4)

    Design: Corner/entities/consumers_list_is_paginated_with_total_count_and_has_more
    """
    create_consumer(api, full_name="Ada Buyer", email="ada@example.com",
                    birthdate="1985-04-02")
    create_consumer(api, full_name="Ben Buyer", email="ben@example.com",
                    birthdate="1979-11-30", address_line="14 Vine St")
    create_consumer(api, full_name="Cleo Buyer", email="cleo@example.com",
                    birthdate="1990-02-14", address_line="16 Vine St")

    first, first_meta = _rows(api.list_consumers(ADMIN, {"limit": 2, "offset": 0}))
    assert len(first) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert api.list_consumers(ADMIN, {"limit": 2, "offset": 0}).json()[
        "response_type"
    ] == "array"

    second, second_meta = _rows(api.list_consumers(ADMIN, {"limit": 2, "offset": 2}))
    assert len(second) == 1
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    defaulted, default_meta = _rows(api.list_consumers(ADMIN))
    assert default_meta["limit"] == DEFAULT_LIMIT
    assert default_meta["offset"] == DEFAULT_OFFSET
    assert default_meta["total_count"] == 3
    assert default_meta["has_more"] is False
    assert len(defaulted) == 3

    for row in defaulted:
        assert row["screening_tier"] == "STANDARD"
        assert row["risk_score_screening"] == 0
        assert row["return_credit_count"] == 0


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
NOT_FOUND_PROBES = [
    ("get_winery", "ERR_WINERY_NOT_FOUND"),
    ("get_state_rule", "ERR_STATE_RULE_NOT_FOUND"),
    ("get_state_permit", "ERR_STATE_PERMIT_NOT_FOUND"),
    ("get_carrier_program", "ERR_CARRIER_PROGRAM_NOT_FOUND"),
    ("get_carrier_enrollment", "ERR_CARRIER_ENROLLMENT_NOT_FOUND"),
    ("get_consumer", "ERR_CONSUMER_NOT_FOUND"),
    ("get_club_subscription", "ERR_CLUB_SUBSCRIPTION_NOT_FOUND"),
    ("get_order", "ERR_ORDER_NOT_FOUND"),
    ("get_shipment", "ERR_SHIPMENT_NOT_FOUND"),
    ("get_compliance_exception", "ERR_COMPLIANCE_EXCEPTION_NOT_FOUND"),
    ("get_remittance", "ERR_REMITTANCE_NOT_FOUND"),
    ("get_volume_ledger_entry", "ERR_VOLUME_LEDGER_ENTRY_NOT_FOUND"),
]


@pytest.mark.parametrize("method_name,expected_error", NOT_FOUND_PROBES)
def test_every_path_parameter_reports_its_own_not_found_error(
    api, clock, method_name, expected_error
):
    """Each single-resource read names the entity of the failing segment.

    "The 404 that comes back names the entity of the failing segment, drawn from
    `ERR_WINERY_NOT_FOUND`, `ERR_STATE_RULE_NOT_FOUND`,
    `ERR_STATE_PERMIT_NOT_FOUND`, `ERR_CARRIER_PROGRAM_NOT_FOUND`,
    `ERR_CARRIER_ENROLLMENT_NOT_FOUND`, `ERR_CONSUMER_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_COMPLIANCE_EXCEPTION_NOT_FOUND`, `ERR_CLUB_SUBSCRIPTION_NOT_FOUND`,
    `ERR_REMITTANCE_NOT_FOUND` and `ERR_VOLUME_LEDGER_ENTRY_NOT_FOUND`."
    (PRD 2.8)

    Design: Corner/entities/every_path_parameter_reports_its_own_not_found_error
    """
    response = getattr(api, method_name)(NON_EXISTENT_UUID, OFFICER_A)
    assert response.json()["response_type"] == "error"
    validate_error(response, expected_error, expected_status=404)


# ---------------------------------------------------------------------------
# The request-body gate
# ---------------------------------------------------------------------------
def test_a_missing_required_body_field_is_refused_before_anything_else(landscape):
    """A body omission is 400, decided ahead of the FK gate and of screening.

    "The request body is checked second. Every required input field must be
    present and non-null; every field must carry its declared type; every
    enum-typed field must carry a declared member of that enum; and numeric
    fields must respect their ranges." (PRD 2.8)

    "Any failure at this gate is `ERR_INVALID_REQUEST` (HTTP 400)." (PRD 2.8)

    "Foreign keys named in the request *body* are resolved third." (PRD 2.8)

    Design: Corner/entities/a_missing_required_body_field_is_refused_before_anything_else
    """
    api = landscape.api
    consumer_version = landscape.consumer_version()

    rule_body = {
        "allows_dtc": True,
        "per_consumer_limit_liters": 27.000,
        "per_consumer_period": "ROLLING_12_MONTHS",
    }
    validate_error(
        api.create_state_rule(rule_body, ADMIN), "ERR_INVALID_REQUEST",
        expected_status=400,
    )

    winery_body = {
        "name": "Estate 2",
        "home_state_code": "CA",
        "annual_production_gallons": 5000,
    }
    validate_error(
        api.create_winery(winery_body, ADMIN), "ERR_INVALID_REQUEST",
        expected_status=400,
    )

    order_body = f.order_payload(
        landscape.winery_id, landscape.consumer_id, consumer_version
    )
    order_body.pop("lines")
    validate_error(
        api.create_order(order_body, landscape.operator), "ERR_INVALID_REQUEST",
        expected_status=400,
    )

    subscription_body = f.club_subscription_payload(
        landscape.consumer_id, landscape.winery_id, next_run_date="2026-08-15"
    )
    subscription_body.pop("annual_allotment")
    validate_error(
        api.create_club_subscription(subscription_body, landscape.operator),
        "ERR_INVALID_REQUEST", expected_status=400,
    )

    orders, order_meta = _rows(api.list_orders(OFFICER_A, {"limit": 100}))
    assert orders == []
    assert order_meta["total_count"] == 0

    subs, sub_meta = _rows(api.list_club_subscriptions(OFFICER_A, {"limit": 100}))
    assert subs == []
    assert sub_meta["total_count"] == 0


def test_declared_enum_and_numeric_constraints_are_enforced_on_input(landscape):
    """Enum membership, the closed bottle_ml set, the bps range and period order.

    "The concrete bounds enforced here are: a line's `bottles` is at least 1; a
    line's `bottle_ml` is one of 375, 500, 750, 1000, 1500 or 3000; a line's
    `unit_price_cents` is at least 1; the `lines` array holds at least 1 and at
    most 20 elements; `sales_tax_rate_bps` lies between 0 and 2000 inclusive; a
    remittance's `period_start` is strictly before its `period_end`;
    `horizon_days` lies between 1 and 365 inclusive; and `run_date` parses as a
    valid ISO 8601 date." (PRD 2.8)

    "every enum-typed field must carry a declared member of that enum" (PRD 2.8)

    Design: Corner/entities/declared_enum_and_numeric_constraints_are_enforced_on_input
    """
    api = landscape.api

    validate_error(
        api.create_state_rule(
            f.state_rule_payload(state_code="AZ", per_consumer_period="ROLLING_7_DAYS"),
            ADMIN,
        ),
        "ERR_INVALID_REQUEST", expected_status=400,
    )

    validate_error(
        api.create_state_rule(
            f.state_rule_payload(state_code="AZ", sales_tax_rate_bps=2500), ADMIN
        ),
        "ERR_INVALID_REQUEST", expected_status=400,
    )

    bad_line = [f.order_line(sku="CAB-900", bottle_ml=900, bottles=6,
                             unit_price_cents=4200)]
    validate_error(
        api.create_order(
            f.order_payload(
                landscape.winery_id, landscape.consumer_id,
                landscape.consumer_version(), lines=bad_line,
            ),
            landscape.operator,
        ),
        "ERR_INVALID_REQUEST", expected_status=400,
    )

    validate_error(
        api.create_remittance(
            f.remittance_payload(
                landscape.winery_id, "TX", "2026-08-01", "2026-07-01"
            ),
            OFFICER_A,
        ),
        "ERR_INVALID_REQUEST", expected_status=400,
    )

    rules, _ = _rows(api.list_state_rules(ADMIN, {"limit": 100}))
    assert [row for row in rules if row["state_code"] == "AZ"] == []

    remittances, remittance_meta = _rows(
        api.list_remittances(OFFICER_A, {"limit": 100})
    )
    assert remittances == []
    assert remittance_meta["total_count"] == 0


def test_body_foreign_keys_are_resolved_before_business_rules(api, cleared_order):
    """Each body foreign key answers its own 404, ahead of every screening rule.

    "Every one of `winery_id`, `state_rule_id`, `consumer_id`,
    `carrier_program_id`, `carrier_enrollment_id`, `order_id`, `shipment_id`,
    `club_subscription_id`, `replacement_of_shipment_id` and
    `supersedes_remittance_id` must resolve to a stored row when supplied, and a
    supplied `ship_to_state_code` or `state_code` must have a `StateRule` row
    governing it." (PRD 2.8)

    "The 404 again names the entity that could not be found, using the same
    catalogue as path resolution; a `ship_to_state_code` with no configured state
    answers `ERR_STATE_RULE_NOT_FOUND`." (PRD 2.8)

    Design: Corner/entities/body_foreign_keys_are_resolved_before_business_rules
    """
    landscape, order = cleared_order
    consumer_version = landscape.consumer_version()

    validate_error(
        api.create_order(
            f.order_payload(landscape.winery_id, NON_EXISTENT_UUID, consumer_version),
            landscape.operator,
        ),
        "ERR_CONSUMER_NOT_FOUND", expected_status=404,
    )

    validate_error(
        api.create_order(
            f.order_payload(NON_EXISTENT_UUID, landscape.consumer_id,
                            consumer_version),
            OFFICER_A,
        ),
        "ERR_WINERY_NOT_FOUND", expected_status=404,
    )

    validate_error(
        api.create_order(
            f.order_payload(
                landscape.winery_id, landscape.consumer_id, consumer_version,
                ship_to_state_code="WY", ship_to_zip="82001",
            ),
            landscape.operator,
        ),
        "ERR_STATE_RULE_NOT_FOUND", expected_status=404,
    )

    validate_error(
        api.create_shipment(
            f.shipment_payload(order["id"], NON_EXISTENT_UUID), landscape.operator
        ),
        "ERR_CARRIER_ENROLLMENT_NOT_FOUND", expected_status=404,
    )

    assert_order_dimensions(
        landscape.read_order(order["id"]), fulfillment_status="UNFULFILLED"
    )

    orders, order_meta = _rows(api.list_orders(OFFICER_A, {"limit": 100}))
    assert len(orders) == 1
    assert order_meta["total_count"] == 1
    assert orders[0]["id"] == order["id"]

    shipments, shipment_meta = _rows(api.list_shipments(OFFICER_A, {"limit": 100}))
    assert shipments == []
    assert shipment_meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Declared defaults
# ---------------------------------------------------------------------------
def test_state_rule_optional_inputs_fall_back_to_their_declared_defaults(api, clock):
    """The two optional inputs persist their declared values, not null.

    "Two fields have defaults and may be omitted: `min_purchaser_age`, the
    minimum purchaser age in whole years, defaults to 21, and
    `renewal_lead_days`, the number of days before a permit's expiration at which
    renewal becomes due, defaults to 60." (PRD 3.1)

    Design: Corner/entities/state_rule_optional_inputs_fall_back_to_their_declared_defaults
    """
    payload = f.state_rule_payload(
        state_code="OK",
        excise_rate_per_liter_cents=70,
        sales_tax_rate_bps=450,
        tax_on_shipping=False,
        excise_in_tax_base=True,
    )
    payload.pop("min_purchaser_age")
    payload.pop("renewal_lead_days")

    data = validate_success(api.create_state_rule(payload, ADMIN), expected_status=201)

    assert data["min_purchaser_age"] == DEFAULT_MIN_PURCHASER_AGE == 21
    assert data["renewal_lead_days"] == DEFAULT_RENEWAL_LEAD_DAYS == 60

    assert data["excise_rate_per_liter_cents"] == 70
    assert data["sales_tax_rate_bps"] == 450
    assert data["excise_in_tax_base"] is True
    assert data["tax_on_shipping"] is False
    assert data["state_code"] == "OK"
    assert_versioned_identity(data, expected_version=1)


# ---------------------------------------------------------------------------
# Computed money
# ---------------------------------------------------------------------------
def test_order_money_fields_are_computed_and_have_no_input_channel(api, landscape):
    """Creation freezes all twelve chain outputs from the lines alone.

    "`shipping_gross_cents` is a flat base of 1,500 cents — fifteen dollars —
    plus 220 cents for every litre of `total_liters`, the whole expression
    rounded half up to whole cents." (PRD 3.5)

    "`compliance_handling_fee_cents` is 0 when `pre_fee_total_cents` is at least
    20,000 cents — two hundred dollars — and otherwise 900 cents." (PRD 3.5)

    "The order itself opens with `compliance_status` `DRAFT` and
    `fulfillment_status` `UNFULFILLED`, with `rejection_error_id` null,
    `override_applied` false, `cleared_at` and `returned_at` null, and both
    `excise_reversed_cents` and `sales_tax_reversed_cents` at 0." (PRD 3.5)

    Design: Corner/entities/order_money_fields_are_computed_and_have_no_input_channel
    """
    response = api.create_order(
        f.order_payload(
            landscape.winery_id, landscape.consumer_id, landscape.consumer_version(),
            lines=f.canonical_lines(),
        ),
        landscape.operator,
    )
    order = validate_success(response, expected_status=201)

    assert_liters(order["total_liters"], 4.500, "total_liters")
    assert_cents(order["subtotal_cents"], 25200, "subtotal_cents")
    assert_cents(order["shipping_gross_cents"], 2490, "shipping_gross_cents")
    assert_cents(order["shipping_tiered_cents"], 2490, "shipping_tiered_cents")
    assert_cents(order["shipping_discount_cents"], 0, "shipping_discount_cents")
    assert_cents(order["shipping_cents"], 2490, "shipping_cents")
    assert_cents(order["excise_tax_cents"], 211, "excise_tax_cents")
    assert_cents(order["sales_tax_cents"], 2284, "sales_tax_cents")
    assert_cents(order["pre_fee_total_cents"], 30185, "pre_fee_total_cents")
    assert_cents(order["compliance_handling_fee_cents"], 0,
                 "compliance_handling_fee_cents")
    assert_cents(order["total_cents"], 30185, "total_cents")

    assert_order_dimensions(order, compliance_status="DRAFT",
                            fulfillment_status="UNFULFILLED")
    assert order["override_applied"] is False
    assert order["cleared_at"] is None

    lines, _ = _rows(api.list_order_lines(order["id"], OFFICER_A, {"limit": 100}))
    assert len(lines) == 1
    line = lines[0]
    assert line["line_index"] == 1
    assert_liters(line["line_liters"], 4.500, "line_liters")
    assert_cents(line["line_subtotal_cents"], 25200, "line_subtotal_cents")
    assert_cents(line["allocated_shipping_cents"], 2490, "allocated_shipping_cents")
    assert_cents(line["line_taxable_cents"], 27690, "line_taxable_cents")
    assert_cents(line["line_sales_tax_cents"], 2284, "line_sales_tax_cents")


# ---------------------------------------------------------------------------
# System-managed fields
# ---------------------------------------------------------------------------
def test_system_fields_are_server_minted_and_version_advances_on_mutation(api, clock):
    """One mutation moves updated_at and version by exactly one step.

    "**`version`** (integer): a counter that starts at 1 when the row is created
    and increments by exactly 1 on every mutation of that row." (PRD 2.5)

    "**`created_at`** (string): an ISO 8601 UTC timestamp with three fractional
    digits (for example `2026-08-01T00:00:00.000Z`), stamped from the logical
    clock when the row was created." (PRD 2.5)

    "Suspending an `ACTIVE` winery — an `ACTIVE` → `SUSPENDED` move — accepts an
    optional free-text `suspension_reason` which is recorded on the row"
    (PRD 3.1)

    Design: Corner/entities/system_fields_are_server_minted_and_version_advances_on_mutation
    """
    winery = create_winery(api)
    set_clock(api, "2026-08-02T00:00:00Z")

    data = validate_success(
        api.set_winery_status(
            winery["id"],
            f.winery_status_payload("SUSPENDED", "Excise filing overdue"),
            ADMIN,
        ),
        expected_status=200,
    )

    assert data["status"] == "SUSPENDED"
    assert data["suspension_reason"] == "Excise filing overdue"
    assert_versioned_identity(data, expected_version=2)
    assert_instant_equals(data["updated_at"], "2026-08-02T00:00:00.000Z")
    assert_instant_equals(data["created_at"], CLOCK_DEFAULT_CANONICAL)
    assert data["id"] == winery["id"]
    assert is_valid_uuid(data["id"]) and len(data["id"]) == 36
    assert_cents(data["excise_accrued_cents"], 0, "excise_accrued_cents")
    assert data["open_exception_count"] == 0


# ---------------------------------------------------------------------------
# Immutable records
# ---------------------------------------------------------------------------
def test_order_lines_and_ledger_entries_are_immutable_records(api, landscape):
    """Lines and ledger rows carry id and created_at only, and are never edited.

    "Three resource kinds are deliberately immutable once written and therefore
    carry only `id` and `created_at` — for these, both `updated_at` and `version`
    are absent from the resource entirely: **`ProhibitedZip`** (a prohibited-ZIP
    declaration is appended, never edited or withdrawn), **`OrderLine`** (a line
    is frozen with its computed money the moment its order is created), and
    **`VolumeLedgerEntry`** (the ledger is append-only by design; a correction is
    a new signed entry, never an edit)." (PRD 2.5)

    "Creation records one line per element of the `lines` array and assigns each
    an `order_id` pointing back at the order plus a `line_index` running from 1
    upward in exactly the request's array order." (PRD 3.5)

    "It appends an offsetting ledger entry with the opposite sign" (PRD 2.10)

    Design: Corner/entities/order_lines_and_ledger_entries_are_immutable_records
    """
    lines = [
        f.order_line(sku="CAB-750", bottle_ml=750, bottles=3, unit_price_cents=2921),
        f.order_line(sku="CAB-750-B", bottle_ml=750, bottles=3, unit_price_cents=2921),
    ]
    order = landscape.create_order(lines=lines)
    landscape.screen(order["id"])

    entry = append_manual_adjustment(
        api, landscape.consumer_id, landscape.winery_id, -1.500,
        occurred_at="2026-08-01T00:00:00Z",
        reason="Two bottles broken in transit and written off",
    )

    stored_lines, _ = _rows(
        api.list_order_lines(order["id"], OFFICER_A, {"limit": 100})
    )
    assert len(stored_lines) == 2
    for row in stored_lines:
        assert_immutable_identity(row)
        assert row["order_id"] == order["id"]

    by_index = sorted(stored_lines, key=lambda row: row["line_index"])
    assert [row["line_index"] for row in by_index] == [1, 2]
    assert by_index[0]["sku"] == "CAB-750"
    assert by_index[1]["sku"] == "CAB-750-B"
    for row in by_index:
        assert_liters(row["line_liters"], 2.250, "line_liters")
        assert_cents(row["line_subtotal_cents"], 8763, "line_subtotal_cents")
        assert_cents(row["allocated_shipping_cents"], 1245,
                     "allocated_shipping_cents")
        assert_cents(row["line_taxable_cents"], 10008, "line_taxable_cents")
        assert_cents(row["line_sales_tax_cents"], 826, "line_sales_tax_cents")

    ledger_row = validate_success(
        api.get_volume_ledger_entry(entry["id"], OFFICER_A), expected_status=200
    )
    assert_immutable_identity(ledger_row)
    assert ledger_row["event_type"] == "MANUAL_ADJUSTMENT"
    assert_liters(ledger_row["liters"], -1.500, "liters")

    rows = landscape.ledger_rows(consumer_id=landscape.consumer_id)
    assert len(rows) == 2
    accepted = [r for r in rows if r["event_type"] == "SHIPMENT_ACCEPTED"]
    adjusted = [r for r in rows if r["event_type"] == "MANUAL_ADJUSTMENT"]
    assert len(accepted) == 1 and len(adjusted) == 1
    assert_liters(accepted[0]["liters"], 4.500, "liters")
    assert_liters(adjusted[0]["liters"], -1.500, "liters")


# ---------------------------------------------------------------------------
# The one nested resource
# ---------------------------------------------------------------------------
def test_prohibited_zip_requires_its_parent_state_rule(api, clock):
    """The parent id comes from the path, and an unknown parent is a 404.

    "A prohibited-ZIP creation aimed at a state rule that does not exist
    therefore returns `ERR_STATE_RULE_NOT_FOUND`, never a validation error about
    the ZIP itself." (PRD 2.8)

    "They are enumerated as **prohibited ZIPs** hung beneath a state rule by
    either a `PlatformAdmin` or a `ComplianceOfficer`, each carrying the owning
    `state_rule_id`, a `zip_code` of exactly five digits, a `reason` drawn from
    `DRY_COUNTY`, `PROHIBITED_MUNICIPALITY`, `PO_BOX_ONLY` or `CARRIER_UNSERVED`,
    and an `effective_from` date." (PRD 3.1)

    "The reverse lookup of every ZIP declared under a state rule can be filtered
    by `reason`." (PRD 3.1)

    Design: Corner/entities/prohibited_zip_requires_its_parent_state_rule
    """
    tx_rule = create_state_rule(api)
    ok_rule = create_state_rule(
        api,
        state_code="OK",
        excise_rate_per_liter_cents=70,
        sales_tax_rate_bps=450,
        tax_on_shipping=False,
        excise_in_tax_base=True,
    )

    payload = f.prohibited_zip_payload(
        zip_code="78702", reason="DRY_COUNTY", effective_from="2026-01-01"
    )

    validate_error(
        api.create_prohibited_zip(NON_EXISTENT_UUID, payload, OFFICER_A),
        "ERR_STATE_RULE_NOT_FOUND", expected_status=404,
    )

    created = validate_success(
        api.create_prohibited_zip(tx_rule["id"], payload, OFFICER_A),
        expected_status=201,
    )
    assert created["state_rule_id"] == tx_rule["id"]
    assert created["zip_code"] == "78702"
    assert created["reason"] == "DRY_COUNTY"
    assert created["effective_from"] == "2026-01-01"
    assert_immutable_identity(created)

    ok_zips, ok_meta = _rows(
        api.list_prohibited_zips(ok_rule["id"], OFFICER_A, {"limit": 100})
    )
    assert ok_zips == []
    assert ok_meta["total_count"] == 0

    tx_zips, tx_meta = _rows(
        api.list_prohibited_zips(tx_rule["id"], OFFICER_A, {"limit": 100})
    )
    assert len(tx_zips) == 1
    assert tx_meta["total_count"] == 1
    assert tx_zips[0]["zip_code"] == "78702"

    filtered, filtered_meta = _rows(
        api.list_prohibited_zips(
            tx_rule["id"], OFFICER_A, {"reason": "PO_BOX_ONLY", "limit": 100}
        )
    )
    assert filtered == []
    assert filtered_meta["total_count"] == 0
