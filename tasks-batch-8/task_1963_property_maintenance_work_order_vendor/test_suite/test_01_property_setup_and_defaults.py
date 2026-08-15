"""Property/resident/part registration: policy defaults, required fields, and
computed stock fields at creation time."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_part_payload,
    create_property,
    create_property_payload,
    create_resident_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]


class TestPropertySetupAndDefaults:
    def test_property_creation_applies_policy_defaults(self, api):
        """PRD §3.1: "The SLA configuration is expressed as six hour-valued fields: `emergency_response_hours` defaults to 4, `emergency_completion_hours` defaults to 24, `urgent_response_hours` defaults to 24, `urgent_completion_hours` defaults to 72, `routine_response_hours` defaults to 72, and `routine_completion_hours` defaults to 168."
        PRD §3.1: "`purchase_auto_approve_threshold_cents` defaults to 50000 (five hundred dollars) and is the ceiling at or under which a purchase request approves itself without manager involvement; `recall_window_days` defaults to 30 and bounds how long after completion a work order can be reopened as a recall; `vendor_travel_buffer_minutes` defaults to 60 and is the minimum gap between consecutive jobs assigned to the same vendor."
        PRD §3.1: "Finally, `entry_notice_min_hours` defaults to 24 and sets the minimum lead time between posting an entry notice and the start of the scheduled window when entry is by posted notice."
        PRD §2.5: "`version` (integer): starts at 1 on creation and increments by exactly one on every mutation of the resource."

        Design: Corner/entities/property_defaults_applied
        """
        resp = api.create_property(create_property_payload(name="Default Property"), MANAGER)
        data = validate_success(resp, 201)
        assert data["purchase_auto_approve_threshold_cents"] == 50000
        assert data["recall_window_days"] == 30
        assert data["vendor_travel_buffer_minutes"] == 60
        assert data["entry_notice_min_hours"] == 24
        assert data["emergency_response_hours"] == 4
        assert data["emergency_completion_hours"] == 24
        assert data["urgent_response_hours"] == 24
        assert data["urgent_completion_hours"] == 72
        assert data["routine_response_hours"] == 72
        assert data["routine_completion_hours"] == 168
        assert data["version"] == 1

    def test_resident_creation_missing_email_returns_400(self, api):
        """PRD §3.1: "A resident is created with `property_id`, `unit_number` (the unit identifier, e.g. "101"), `full_name`, and `email`; their `chargeback_balance_cents` starts at 0."
        PRD §2.1: "The precedence among all validation categories — authentication, authorization, ownership, existence, concurrency, state, business safety, business temporal, business constraint, business fiscal, and finally general shape validation — is honored across every endpoint: an unauthenticated request is rejected before a forbidden one, a forbidden one before a non-owner one, and so on, with malformed-payload errors of the general `ERR_VALIDATION` category evaluated last."

        Design: Corner/entities/resident_creation_missing_required_field_returns_400
        """
        prop = create_property("Req Property")
        payload = create_resident_payload(
            property_id=prop["id"], unit_number="201", full_name="No Email"
        )
        del payload["email"]
        resp = api.create_resident(payload, MANAGER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        data, meta = validate_paginated(
            api.list_residents(MANAGER, params={"property_id": prop["id"]})
        )
        assert meta["total_count"] == 0, f"nothing may be created, got {meta['total_count']}"
        assert data == []

    def test_part_creation_seeds_stock_and_computes_restock_status(self, api):
        """PRD §3.1: "At creation the part's `quantity_on_hand` is seeded to `initial_stock`, `reserved_quantity` starts at 0, and `restock_status` is computed immediately per the ledger rule of §2.8."
        PRD §2.8: "After every ledger event, the part's `restock_status` is recomputed: it is `LOW_STOCK` whenever `quantity_on_hand` is less than or equal to the part's `reorder_level` (equality counts as low stock), and `IN_STOCK` otherwise."

        Design: Corner/entities/part_computed_fields_at_creation
        """
        prop = create_property("Part Property")
        resp = api.create_part(
            create_part_payload(
                property_id=prop["id"], sku="FLT-1", name="Filter",
                unit_cost_cents=700, reorder_level=3, initial_stock=3,
            ),
            MANAGER,
        )
        data = validate_success(resp, 201)
        assert data["quantity_on_hand"] == 3, "quantity_on_hand seeded from initial_stock"
        assert data["reserved_quantity"] == 0
        assert data["restock_status"] == "LOW_STOCK", "3 <= reorder_level 3 counts as low stock"
