"""Customer onboarding, rate-card supersede OCC, version semantics, suspension."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_customer,
    assert_instant_equals,
    assert_invoice,
    create_customer,
    create_customer_with_card,
    create_rate_card_payload,
    create_zone,
    get_customer,
    get_open_invoice,
    list_invoices,
    make_customer_admin_headers,
    patch_customer,
    validate_error,
    validate_paginated,
    validate_success,
)

BILLING = TEST_USERS["billing_admin_headers"]


class TestCustomerOnboarding:
    def test_new_customer_active_with_open_invoice(self, api):
        """PRD §3.1: "The Customer record begins life at status `ACTIVE`, and
        creation automatically opens the customer's first invoice: status `OPEN`,
        `period_start` at the first instant of the calendar month containing now,
        `period_end` at the first instant of the following month, and every charge
        component at zero."
        PRD §2.4: "At startup the clock reads exactly 2026-08-01T00:00:00Z, and it
        never consults wall-clock time."

        Design: Corner/entities/customer_creation_defaults_and_open_invoice_side_effect
        """
        resp = api.create_customer(
            {"name": "New Co", "credit_limit_cents": 50000}, BILLING)
        customer = validate_success(resp, expected_status=201)
        assert_customer(customer)
        assert customer["status"] == "ACTIVE", (
            f"new customer must be ACTIVE, got {customer['status']}")

        data, _meta = validate_paginated(
            api.list_invoices(BILLING, params={"customer_id": customer["id"],
                                               "status": "OPEN"}))
        assert len(data) == 1, f"exactly one OPEN invoice expected, got {len(data)}"
        invoice = data[0]
        assert_invoice(invoice)
        assert_instant_equals(invoice["period_start"], "2026-08-01T00:00:00Z")
        assert_instant_equals(invoice["period_end"], "2026-09-01T00:00:00Z")
        for field in ("storage_cents", "handling_in_cents", "handling_out_cents",
                      "blast_freeze_cents", "dwell_surcharge_cents",
                      "claim_credit_cents", "total_cents"):
            assert invoice[field] == 0, f"{field} must start at zero"
        assert invoice["rate_card_id"] is None, "OPEN invoice has no rate card yet"


class TestRateCardOccSupersede:
    def test_stale_customer_version_rejected_then_fresh_succeeds(self, api):
        """PRD §2.7: "If the value does not match the Customer's current `version`
        — because the customer's record has advanced since the client last read it
        — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing
        the caller from pricing against a customer state it has not observed."
        PRD §3.1: "The new card is created `ACTIVE`; any prior `ACTIVE` card for
        the same customer is immediately superseded, moving to `SUPERSEDED`, and
        the Customer's `version` increments by one. At most one card per customer
        is ever `ACTIVE`."

        Design: Corner/complexity_layers/occ_rate_card_stale_version_rejected
        """
        customer = create_customer("Occ Co")
        created_version = customer["version"]
        card1_payload = create_rate_card_payload(customer["id"], created_version)
        card1 = validate_success(
            api.create_rate_card(card1_payload, BILLING), expected_status=201)

        # Replay the pre-card1 version: stale.
        stale = api.create_rate_card(
            create_rate_card_payload(customer["id"], created_version,
                                     storage_method="FULL_MONTH",
                                     frozen_storage_cents_per_pallet_month=9999),
            BILLING)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        # Refetch and retry with the live version: succeeds and supersedes card1.
        fresh_version = get_customer(customer["id"])["version"]
        assert fresh_version == created_version + 1, (
            "first card creation increments Customer.version by one")
        card2 = validate_success(
            api.create_rate_card(
                create_rate_card_payload(customer["id"], fresh_version,
                                         storage_method="FULL_MONTH",
                                         frozen_storage_cents_per_pallet_month=9999),
                BILLING),
            expected_status=201)
        assert card2["status"] == "ACTIVE"

        card1_after = validate_success(api.get_rate_card(card1["id"], BILLING))
        assert card1_after["status"] == "SUPERSEDED", (
            "prior ACTIVE card must be superseded")
        active = validate_paginated(
            api.list_rate_cards(BILLING, params={"customer_id": customer["id"],
                                                 "status": "ACTIVE"}))[0]
        assert len(active) == 1 and active[0]["id"] == card2["id"], (
            "at most one ACTIVE card per customer")
        assert get_customer(customer["id"])["version"] == created_version + 2, (
            "each successful card creation increments Customer.version by one")


class TestCustomerVersionIncrements:
    def test_patch_increments_version_reads_do_not(self, api):
        """PRD §2.5: "`version` (integer): A system-managed integer that
        increments by one with every modification to the resource, including
        modifications driven by system cascades rather than by a direct client
        request."
        PRD §3.1: "A `BillingAdmin` may patch a customer's `status` to `SUSPENDED`
        or restore it to `ACTIVE`, and may likewise adjust `credit_limit_cents`;
        each such update increments the customer's `version`."

        Design: Corner/complexity_layers/version_increments_on_every_mutation
        """
        customer = create_customer("Ver Co", credit_limit_cents=50000)
        v0 = customer["version"]

        after_patch1 = patch_customer(customer["id"], credit_limit_cents=60000)
        assert after_patch1["version"] == v0 + 1, (
            f"PATCH must increment version by one: {v0} -> {after_patch1['version']}")

        after_read = get_customer(customer["id"])
        assert after_read["version"] == v0 + 1, "a read must never modify version"

        after_patch2 = patch_customer(customer["id"], credit_limit_cents=70000)
        assert after_patch2["version"] == v0 + 2, (
            f"second PATCH increments by one again: {after_patch2['version']}")


class TestSuspendedCustomer:
    def test_suspended_customer_blocked_from_new_work(self, api):
        """PRD §3.1: "While a customer stands at `SUSPENDED`, no new inbound
        receipt may be scheduled for them and no outbound order may be created or
        submitted on their behalf — each attempt is rejected with
        `ERR_CUSTOMER_SUSPENDED`."

        Design: Corner/validations/suspended_customer_blocked_from_new_work
        """
        customer, _card = create_customer_with_card("Susp Co")
        zone = create_zone("FZ-SU", capacity_pallets=5)
        patch_customer(customer["id"], status="SUSPENDED")
        headers = make_customer_admin_headers(customer["id"])

        receipt_resp = api.create_inbound_receipt(
            {"customer_id": customer["id"], "zone_id": zone["id"],
             "product_code": "PEAS", "lot_code": "SU",
             "production_date": "2026-01-15", "temp_class": "FROZEN",
             "expected_pallets": 1, "window_start": "2026-08-02T08:00:00Z",
             "window_end": "2026-08-02T10:00:00Z"},
            headers)
        validate_error(receipt_resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED)

        order_resp = api.create_outbound_order(
            {"customer_id": customer["id"], "product_code": "PEAS",
             "requested_pallets": 1},
            headers)
        validate_error(order_resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED)

        patch_customer(customer["id"], status="ACTIVE")
        order = validate_success(
            api.create_outbound_order(
                {"customer_id": customer["id"], "product_code": "PEAS",
                 "requested_pallets": 1},
                headers),
            expected_status=201)
        assert order["status"] == "DRAFT", "reactivation restores order creation"
