"""Entity-shape behaviour of the dropship vendor program.

These tests pin what the platform persists and returns for its resource rows:
the registration defaults of a vendor, the housekeeping fields every row carries
(and the two a shipment confirmation deliberately lacks), derived fields the
client may not supply, list envelopes and ordering, and the existence, shape,
interval and fallback-graph rejections that guard row creation.
"""

from test_helpers import (
    DEFAULT_CLOCK_UTC,
    TEST_USERS,
    ApiErrorId,
    assert_dropship_item,
    assert_dropship_order,
    assert_integration_test,
    assert_shipment_confirmation,
    assert_vendor,
    create_active_vendor,
    create_blackout_payload,
    create_draft_item,
    create_draft_vendor,
    create_integration_test_payload,
    create_inventory_snapshot_payload,
    create_item_payload,
    create_order_payload,
    create_vendor_payload,
    get_success_data,
    is_iso8601_timestamp,
    make_vendor_ops_analyst_headers,
    make_vendor_user_headers,
    order_line_input,
    refresh_item,
    refresh_vendor,
    reset_clock,
    set_clock,
    setup_acknowledged_line,
    setup_vendor_with_active_offer,
    ship_confirm_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["vendor_ops_analyst_headers"]
MM = TEST_USERS["merchandise_manager_headers"]
CARE = TEST_USERS["care_agent_headers"]

# A syntactically valid identifier that never names a row in these tests.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000099"


def test_vendor_create_returns_201_with_every_declared_field(api):
    """PRD §3.1: "A freshly registered vendor lands in `onboarding_status` `DRAFT` with `integration_round` at 0, `performance_tier` at `UNRATED`, both `settlement_balance_cents` and `chargeback_balance_cents` at 0, and `certified_by_user_id`, `activated_by_user_id` and `suspension_reason` all null."

    Registration answers 201 with the whole vendor row: the echoed commercial
    terms, the onboarding fields the server itself decides, and the housekeeping
    triple minted on insertion.

    Design: Corner/entities/corner_vendor_create_returns_201_with_every_declared_field
    """
    reset_clock(api)

    payload = create_vendor_payload(
        vendor_code="V-CREATE",
        legal_name="Create Co LLC",
        cost_model="COMMISSION",
        commission_rate_bps=1500,
        inventory_refresh_cadence_minutes=60,
        safety_buffer_units=5,
        oversell_grace_units=0,
        default_lead_time_days=3,
        ack_sla_hours=24,
        ship_sla_grace_hours=12,
    )
    data = validate_success(api.create_vendor(payload, ADMIN), 201)

    assert_vendor(data)
    assert data["vendor_code"] == "V-CREATE"
    assert data["legal_name"] == "Create Co LLC"
    assert data["cost_model"] == "COMMISSION"
    assert data["commission_rate_bps"] == 1500
    assert data["onboarding_status"] == "DRAFT"
    assert data["integration_round"] == 0
    assert data["performance_tier"] == "UNRATED"
    assert data["settlement_balance_cents"] == 0
    assert data["chargeback_balance_cents"] == 0
    assert data["certified_by_user_id"] is None
    assert data["activated_by_user_id"] is None
    assert data["suspension_reason"] is None
    assert data["version"] == 1
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])


def test_vendor_get_returns_the_stored_row(api):
    """PRD §2.4: "`version` is an integer that starts at 1 on creation and increases by exactly 1 each time the row is mutated."

    Reading a vendor back hands over exactly what registration persisted, and a
    read is not a mutation: the row is still at version 1.

    Design: Corner/entities/corner_vendor_get_returns_the_stored_row
    """
    reset_clock(api)

    created = get_success_data(
        api.create_vendor(
            create_vendor_payload(
                vendor_code="V-READ",
                legal_name="Readback Co LLC",
                cost_model="COMMISSION",
                commission_rate_bps=1500,
                inventory_refresh_cadence_minutes=60,
                safety_buffer_units=5,
                default_lead_time_days=3,
            ),
            ADMIN,
        )
    )

    data = validate_success(api.get_vendor(created["id"], ADMIN))

    assert_vendor(data)
    assert data["id"] == created["id"]
    assert data["vendor_code"] == "V-READ"
    assert data["legal_name"] == "Readback Co LLC"
    assert data["commission_rate_bps"] == 1500
    assert data["inventory_refresh_cadence_minutes"] == 60
    assert data["safety_buffer_units"] == 5
    assert data["default_lead_time_days"] == 3
    assert data["created_at"] == created["created_at"]
    assert data["version"] == 1


def test_item_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "Each list response repeats the effective `limit` and `offset` in the `meta` block alongside `total_count`, the number of rows matching the filter before pagination, and `has_more`, which is true when rows remain beyond the current page."

    Three offers on one vendor, read two at a time: total_count counts the whole
    filtered set rather than the page, has_more flips on the last page, and rows
    arrive oldest first.

    Design: Corner/entities/corner_item_list_paginates_with_total_count_and_has_more
    """
    reset_clock(api)
    vendor = create_active_vendor(api, suffix="PAGE")

    for sku, retail in (("SKU-P-1", 1000), ("SKU-P-2", 2000), ("SKU-P-3", 3000)):
        create_draft_item(api, vendor["id"], sku=sku, unit_retail_cents=retail)

    first, first_meta = validate_paginated(
        api.list_items(ADMIN, params={"vendor_id": vendor["id"], "limit": 2, "offset": 0})
    )
    second, second_meta = validate_paginated(
        api.list_items(ADMIN, params={"vendor_id": vendor["id"], "limit": 2, "offset": 2})
    )

    assert [row["sku"] for row in first] == ["SKU-P-1", "SKU-P-2"]
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True

    assert [row["sku"] for row in second] == ["SKU-P-3"]
    assert second_meta["total_count"] == 3
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False


def test_vendor_get_with_unknown_id_returns_not_found(api):
    """PRD §2.5: "A request naming a vendor that does not exist therefore fails with `ERR_VENDOR_NOT_FOUND` before the platform ever looks at the inner identifier, even when that inner identifier is also bogus."

    A well-formed but unknown vendor identifier is a 404 with an error envelope,
    not a 200 carrying an empty body.

    Design: Corner/entities/corner_vendor_get_with_unknown_id_returns_not_found
    """
    reset_clock(api)

    response = api.get_vendor(UNKNOWN_ID, ADMIN)

    validate_error(response, ApiErrorId.ERR_VENDOR_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"


def test_item_create_without_required_sku_is_rejected(api):
    """PRD §2.6: "All required body fields are present and of the declared type, every numeric field lies inside its declared range, and every enum-typed field holds one of its declared values."

    An offer names the sku it fulfills, so a creation body that omits it fails
    the structural check with ERR_INVALID_REQUEST and no offer is written.

    Design: Corner/entities/corner_item_create_without_required_sku_is_rejected
    """
    reset_clock(api)
    vendor = create_active_vendor(api, suffix="NOSKU")

    payload = create_item_payload(
        vendor["id"], sku=None, unit_retail_cents=24999, ship_method="GROUND", lead_time_days=3
    )
    assert "sku" not in payload

    validate_error(
        api.create_item(payload, MM), ApiErrorId.ERR_INVALID_REQUEST.value
    )

    rows, meta = validate_paginated(
        api.list_items(ADMIN, params={"vendor_id": vendor["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_vendor_create_omitting_optional_tuning_applies_declared_defaults(api):
    """PRD §3.1: "The same payload carries the operating parameters that will later drive availability and service levels: `inventory_refresh_cadence_minutes`, the contracted maximum gap between inventory feed messages, at least 1 minute and at most 1440 (a full day); `safety_buffer_units`, the units held back from every offer's availability as oversell protection, defaulting to 0 and never negative; `oversell_grace_units`, the units of deliberate oversell the vendor is willing to absorb above its buffered on-hand, also defaulting to 0 and never negative; `default_lead_time_days`, the fallback fulfillment lead time of between 0 and 60 days applied to offers that do not declare their own; `ack_sla_hours`, the hours after transmission within which the vendor must respond to a line, defaulting to 24 and constrained to between 1 and 168 (one week); and `ship_sla_grace_hours`, the grace added on top of the offer's lead time to form the ship-confirm deadline, defaulting to 12 and constrained to between 0 and 168."

    Leaving out every tuning input that declares a default leaves those defaults
    in place: no buffer, no oversell grace, a day of acknowledgment SLA and
    twelve hours of ship grace. The promise padding starts at 2 days, which the
    request never mentions.

    Design: Corner/entities/corner_vendor_create_omitting_optional_tuning_applies_declared_defaults
    """
    reset_clock(api)

    payload = create_vendor_payload(
        vendor_code="V-DEFAULTS",
        legal_name="Defaults Only LLC",
        cost_model="COMMISSION",
        commission_rate_bps=1500,
        inventory_refresh_cadence_minutes=60,
        default_lead_time_days=3,
        safety_buffer_units=None,
        oversell_grace_units=None,
        ack_sla_hours=None,
        ship_sla_grace_hours=None,
    )
    for omitted in ("safety_buffer_units", "oversell_grace_units", "ack_sla_hours",
                    "ship_sla_grace_hours", "promise_padding_days"):
        assert omitted not in payload

    data = validate_success(api.create_vendor(payload, ADMIN), 201)

    assert_vendor(data)
    assert data["safety_buffer_units"] == 0
    assert data["oversell_grace_units"] == 0
    assert data["ack_sla_hours"] == 24
    assert data["ship_sla_grace_hours"] == 12
    assert data["promise_padding_days"] == 2
    assert data["performance_tier"] == "UNRATED"
    assert data["onboarding_status"] == "DRAFT"
    assert data["integration_round"] == 0


def test_item_unit_cost_cents_is_computed_and_client_value_is_input_ignored(api):
    """PRD §3.3: "For a `COMMISSION` vendor, the offer's `unit_cost_cents` is the offer's `unit_retail_cents` multiplied by the quantity 10000 minus the vendor's `commission_rate_bps`, divided by 10000, with the result rounded half up to a whole cent; `unit_wholesale_cost_cents` plays no part whatsoever."

    Retail of 24999 at 1500 basis points of commission derives 21249 cents of
    cost. The figure is derived, so a client-supplied unit_cost_cents of 1 is
    discarded rather than stored.

    Design: Corner/entities/corner_item_unit_cost_cents_is_computed_and_client_value_is_input_ignored
    """
    reset_clock(api)
    vendor = create_active_vendor(api, suffix="COST", commission_rate_bps=1500)

    payload = create_item_payload(
        vendor["id"],
        sku="SKU-COMPUTED-1",
        unit_retail_cents=24999,
        ship_method="GROUND",
        lead_time_days=3,
    )
    payload["unit_cost_cents"] = 1

    data = validate_success(api.create_item(payload, MM), 201)

    assert_dropship_item(data)
    assert data["unit_cost_cents"] == 21249
    assert data["unit_retail_cents"] == 24999
    assert data["status"] == "DRAFT"


def test_order_system_fields_generated_and_client_extra_field_ignored(api):
    """PRD §3.5: "The order itself records `placed_at` from the logical clock, opens on the fulfillment axis at `OPEN` and on the financial axis at `PENDING`, and sets `refunded_cents` to 0 and `retailer_absorbed_cents` to 0."

    placed_at comes from the logical clock, which the test holds at
    2026-08-03T10:00:00Z, and the identifier is server-minted: neither the
    client's id nor its placed_at survives into the stored order.

    Design: Corner/entities/corner_order_system_fields_generated_and_client_extra_field_ignored
    """
    base = setup_vendor_with_active_offer(api, suffix="SYS")

    payload = create_order_payload(
        "ORD-SYS-1",
        [order_line_input(base["item_id"], 1)],
        customer_zone_code="US-WEST",
    )
    payload["id"] = UNKNOWN_ID
    payload["placed_at"] = "1999-01-01T00:00:00Z"

    data = validate_success(api.create_order(payload, CARE), 201)

    assert_dropship_order(data)
    assert data["id"] != UNKNOWN_ID
    assert data["placed_at"].startswith("2026-08-03T10:00:00")
    assert data["fulfillment_status"] == "OPEN"
    assert data["financial_status"] == "PENDING"
    assert data["refunded_cents"] == 0
    assert data["retailer_absorbed_cents"] == 0
    assert data["version"] == 1
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])


def test_integration_test_evaluate_with_invalid_enum_outcome_is_rejected(api):
    """PRD §3.1: "The evaluator supplies an `outcome` of either `PASS` or `FAIL`, may supply `defect_notes` of up to 500 characters, and may supply an advisory `reported_error_count` — the vendor's own count of parse errors in the sample payload, which must not be negative and which never decides the outcome."

    outcome is a closed pair of values, so MAYBE is rejected as a structural
    error and nothing is coerced: the run is still PENDING and unevaluated, and
    its vendor is still in integration testing.

    Design: Corner/entities/corner_integration_test_evaluate_with_invalid_enum_outcome_is_rejected
    """
    reset_clock(api)
    vendor = create_draft_vendor(api, suffix="ENUM", legal_name="Enum Guard LLC")
    get_success_data(api.begin_integration(vendor["id"], OPS))

    recorder = make_vendor_ops_analyst_headers("ops-recorder-enum")
    evaluator = make_vendor_ops_analyst_headers("ops-evaluator-enum")
    run = get_success_data(
        api.record_integration_test(
            vendor["id"], create_integration_test_payload("CATALOG"), recorder
        )
    )

    validate_error(
        api.evaluate_integration_test(run["id"], {"outcome": "MAYBE"}, evaluator),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    rows, _ = validate_paginated(api.list_integration_tests(vendor["id"], ADMIN))
    stored = [row for row in rows if row["id"] == run["id"]][0]
    assert_integration_test(stored)
    assert stored["status"] == "PENDING"
    assert stored["evaluated_at"] is None
    assert stored["evaluated_by_user_id"] is None
    assert refresh_vendor(api, vendor["id"])["onboarding_status"] == "INTEGRATION_TESTING"


def test_blackout_create_with_end_date_before_start_date_is_rejected(api):
    """PRD §3.2: "A window whose `end_date` falls before its `start_date` is rejected with `ERR_INVALID_INTERVAL`."

    A blackout is a fully-closed date interval, so an inverted pair is refused
    with the 422 interval error and no window row is created.

    Design: Corner/entities/corner_blackout_create_with_end_date_before_start_date_is_rejected
    """
    reset_clock(api)
    vendor = create_active_vendor(api, suffix="INTERVAL")

    validate_error(
        api.create_blackout(
            vendor["id"],
            create_blackout_payload(
                start_date="2026-08-20",
                end_date="2026-08-18",
                reason="HOLIDAY",
                reopen_buffer_days=0,
            ),
            OPS,
        ),
        ApiErrorId.ERR_INVALID_INTERVAL.value,
    )

    rows, meta = validate_paginated(api.list_blackouts(vendor["id"], ADMIN))
    assert rows == []
    assert meta["total_count"] == 0


def test_shipment_confirmation_is_immutable_with_no_update_path_and_no_version(api):
    """PRD §2.4: "A shipment confirmation is an immutable record of a physical hand-off, so it carries only `id` and `created_at`: it has no `updated_at` and no `version` field at all, and nothing in the platform ever edits one after creation."

    Confirming the hand-off appends an evidence row that carries neither
    updated_at nor version, and the line's shipment list holds exactly that one
    entry.

    Design: Corner/entities/corner_shipment_confirmation_is_immutable_with_no_update_path_and_no_version
    """
    state = setup_acknowledged_line(api, quantity=1, order_ref="ORD-IMMUT-1", suffix="IMMUT")
    set_clock(api, "2026-08-04T10:00:00Z")

    data = validate_success(
        api.ship_confirm_line(
            state["line_id"],
            ship_confirm_payload(1, carrier="UPS", tracking_number="1Z-IM-001"),
            make_vendor_user_headers(state["vendor_id"]),
        ),
        201,
    )

    assert_shipment_confirmation(data)
    assert "version" not in data
    assert "updated_at" not in data
    assert data["shipped_units"] == 1
    assert data["on_time"] is True
    assert float(data["ship_hours"]) == 24.0

    rows, meta = validate_paginated(
        api.list_shipment_confirmations(state["line_id"], ADMIN)
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert rows[0]["id"] == data["id"]
    assert "version" not in rows[0]
    assert "updated_at" not in rows[0]


def test_snapshot_create_under_unknown_item_returns_not_found(api):
    """PRD §2.6: "Checks are evaluated strictly in the sequence below, lowest number first, and the first failure short-circuits the request."

    Offer existence is checked long before the offer-version concurrency check,
    so a feed message posted against an unknown offer answers
    ERR_ITEM_NOT_FOUND and the supplied expected_item_version is never compared.

    Design: Corner/entities/corner_snapshot_create_under_unknown_item_returns_not_found
    """
    reset_clock(api)
    vendor = create_active_vendor(api, suffix="SNAPNF")

    response = api.create_inventory_snapshot(
        UNKNOWN_ID,
        create_inventory_snapshot_payload(
            expected_item_version=vendor["version"],
            on_hand_units=10,
            effective_from=DEFAULT_CLOCK_UTC,
            feed_sequence=1,
        ),
        make_vendor_user_headers(vendor["id"]),
    )

    error = validate_error(response, ApiErrorId.ERR_ITEM_NOT_FOUND.value)
    assert error["error_id"] != ApiErrorId.ERR_STALE_ITEM_VERSION.value


def test_item_fallback_pointing_at_itself_is_rejected(api):
    """PRD §3.3: "Three conditions are enforced whenever it is supplied, whether at creation or on a later amendment: the referenced offer must exist, it must carry an identical `sku`, and its `vendor_id` must differ from the referencing offer's; pointing an offer at itself is likewise forbidden."

    An offer may not be its own endless-aisle substitute, so the amendment is
    refused with ERR_FALLBACK_INVALID and the row is not mutated: the pointer
    stays null and the version stays where it was.

    Design: Corner/entities/corner_item_fallback_pointing_at_itself_is_rejected
    """
    reset_clock(api)
    vendor = create_active_vendor(api, suffix="CYCLE")
    item = create_draft_item(
        api, vendor["id"], sku="SKU-CYCLE-1", unit_retail_cents=5000
    )
    assert item["version"] == 1

    validate_error(
        api.update_item(item["id"], {"fallback_item_id": item["id"]}, MM),
        ApiErrorId.ERR_FALLBACK_INVALID.value,
    )

    after = refresh_item(api, item["id"])
    assert after["fallback_item_id"] is None
    assert after["version"] == 1
