"""Entity creation defaults, required fields, computed fields, ledger entry
shape, per-resource 404s, and filtered-list reachability (PRD §2.5, §3)."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_customer_account, assert_unit, assert_floor_plan_entry,
    is_valid_uuid, is_iso8601_timestamp,
    create_account, create_slot_pool, create_order, create_new_unit,
    create_repair_order, create_bay, create_bay_booking,
    create_customer_account_payload,
)

MGR = TEST_USERS["sales_manager_headers"]
CONSULTANT = TEST_USERS["sales_consultant_headers"]
ADVISOR = TEST_USERS["service_advisor_headers"]
PARTS_REP = TEST_USERS["parts_counter_rep_headers"]
WARRANTY_ADMIN = TEST_USERS["warranty_admin_headers"]
CONTROLLER = TEST_USERS["controller_headers"]


def test_customer_account_creation_defaults_applied(api):
    """PRD §3.1: "an optional `fleet_tier` of `STANDARD`, `GOLD`, or `PLATINUM`
    (defaulting to `STANDARD`), and an optional `credit_limit_cents`. New
    accounts start `ACTIVE` with an `open_ar_cents` of zero."
    PRD §2.5: "Every persisted entity carries an `id` that is a server-minted
    UUID ... a `created_at` timestamp ... an `updated_at` timestamp ... and a
    `version` integer that increments on every mutation."

    Design: Corner/entities/customer_account_creation_defaults_applied
    """
    resp = api.create_customer_account(
        create_customer_account_payload(account_name="DefaultCo", account_type="RETAIL"),
        MGR)
    data = validate_success(resp, 201)
    assert_customer_account(data)
    assert data["fleet_tier"] == "STANDARD"
    assert data["credit_limit_cents"] == 0
    assert data["status"] == "ACTIVE"
    assert data["open_ar_cents"] == 0
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def test_customer_account_missing_required_field_rejected(api):
    """PRD §2.10(4): "Body well-formedness: required fields present, enum values
    valid, numeric ranges valid ... — `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: "A `SalesManager` opens a customer account with an
    `account_name`, an `account_type` of `FLEET` or `RETAIL`".

    Design: Corner/entities/customer_account_missing_required_field_rejected
    """
    resp = api.create_customer_account({"account_name": "NoType"}, MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_unit_computed_fields_after_receive(api):
    """PRD §3.2: "a new `Unit` is born: `unit_kind` `NEW`, status `IN_STOCK`,
    `invoice_cost_cents` equal to the order's `committed_total_cents`,
    `stocking_date` the current clock date, `floorplan_active` true ... its
    creation also posts the first ledger entry: an `ADVANCE` equal to
    `invoice_cost_cents`, establishing `floorplan_balance_cents` at the invoice
    cost and `last_accrual_date` at the stocking date."
    PRD §3.3: "The `aging_bucket` bands are `B0_90` through day 90".

    Design: Corner/entities/unit_computed_fields_ignore_client_input
    """
    unit = create_new_unit(vin="1FUJGBDV1CLW88326")
    assert_unit(unit)
    assert unit["invoice_cost_cents"] == 10085000  # M2_106/DD13/A4X2 + destination fee
    assert unit["floorplan_balance_cents"] == 10085000
    assert unit["days_in_stock"] == 0
    assert unit["aging_bucket"] == "B0_90"
    assert unit["curtailment_due_cents"] == 0
    assert unit["floorplan_active"] is True
    assert unit["unit_kind"] == "NEW"
    assert unit["status"] == "IN_STOCK"
    assert unit["last_accrual_date"] == "2026-08-15"


def test_floorplan_entry_is_append_only_advance_first(api):
    """PRD §2.5: "The sole exception is `FloorPlanEntry`, which is an
    append-only ledger line: it carries `id` and `created_at` but has neither
    `updated_at` nor `version`."
    PRD §3.2: "its creation also posts the first ledger entry: an `ADVANCE`
    equal to `invoice_cost_cents`".

    Design: Corner/entities/floorplan_entry_immutable_no_update_endpoint
    """
    unit = create_new_unit(vin="1FUJGBDV1CLW88327")
    entries, meta = validate_paginated(api.list_floor_plan_entries(unit["id"], CONTROLLER))
    assert len(entries) == 1
    entry = entries[0]
    assert_floor_plan_entry(entry)
    assert entry["entry_type"] == "ADVANCE"
    assert entry["amount_cents"] == 10085000
    assert entry["resulting_balance_cents"] == 10085000
    assert entry["entry_date"] == "2026-08-15"


def test_get_nonexistent_resources_return_per_entity_404(api):
    """PRD §2.5: "path-identifier validation is simply confirming that each
    referenced identifier exists, producing the appropriate
    `ERR_<RESOURCE>_NOT_FOUND` (HTTP 404) from the catalogue in §5."

    Design: Corner/entities/get_nonexistent_resources_return_per_entity_404
    """
    validate_error(api.get_unit(NON_EXISTENT_UUID, MGR), ApiErrorId.ERR_UNIT_NOT_FOUND, 404)
    validate_error(api.get_part(NON_EXISTENT_UUID, PARTS_REP), ApiErrorId.ERR_PART_NOT_FOUND, 404)
    validate_error(api.get_warranty_claim(NON_EXISTENT_UUID, WARRANTY_ADMIN),
                   ApiErrorId.ERR_WARRANTY_CLAIM_NOT_FOUND, 404)


def test_fk_reverse_reachability_filtered_lists(api):
    """PRD §3.2: "Orders may be listed with filters on `customer_account_id`,
    `factory_build_slot_id`, and `status`".
    PRD §3.5: "Bookings list with filters on `repair_order_id`,
    `service_bay_id`, `mobile_service_unit_id`, and `status`."

    Design: Corner/entities/fk_reverse_reachability_filtered_lists
    """
    slot_a = create_slot_pool(build_month="2026-08")
    slot_b = create_slot_pool(build_month="2026-09")
    create_order(slot_a["id"])
    create_order(slot_a["id"], chassis_model="SD_114", engine_option="DD15", axle_config="A6X4")
    acct = create_account(name="FKCo")
    ro = create_repair_order(acct["id"])
    bay = create_bay()
    create_bay_booking(ro["id"], bay["id"], "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z")

    _, meta_a = validate_paginated(
        api.list_factory_orders(MGR, params={"factory_build_slot_id": slot_a["id"]}))
    assert meta_a["total_count"] == 2
    _, meta_b = validate_paginated(
        api.list_factory_orders(MGR, params={"factory_build_slot_id": slot_b["id"]}))
    assert meta_b["total_count"] == 0
    bookings, meta_bk = validate_paginated(
        api.list_service_bookings(ADVISOR, params={"service_bay_id": bay["id"]}))
    assert meta_bk["total_count"] == 1
    assert bookings[0]["repair_order_id"] == ro["id"]
