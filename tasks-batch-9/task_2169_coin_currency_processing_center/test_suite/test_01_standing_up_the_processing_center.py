"""Registering vaults, machines and depositor accounts, and lodging intake tickets."""

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    assert_deposit_ticket,
    assert_sealed_bag,
    assert_vault,
    create_account,
    create_ticket,
    create_vault,
    create_counting_machine_payload,
    create_customer_account_payload,
    create_deposit_ticket_payload,
    create_sealed_bag_payload,
    create_vault_payload,
    make_carrier_headers,
    make_manager_headers,
    CARRIER_1,
    MANAGER_1,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVaultRegistration:
    def test_vault_registration_applies_declared_defaults(self, api):
        """PRD §3.1: "A newly registered vault comes up with `posture` set to `OPEN`,
        `version` at 1, `cash_letter_adjustment_cents` at 0 and
        `coin_face_value_on_hand_cents` at 0."
        PRD §3.1: "The manager may also supply `pickup_concurrency_limit`, the maximum
        number of coin-order pickup windows whose closed intervals may cover any single
        instant on this vault's dock; when omitted it defaults to 2, and it must be at
        least 1."
        PRD §4: "Creating a brand-new resource returns HTTP 201; every other successful
        call — reads, lifecycle transitions, allocations, adjustments and projections —
        returns HTTP 200."

        Design: Corner/entities/vault_creation_applies_defaults_and_starts_at_version_one
        """
        payload = create_vault_payload(vault_code="CV-C01", name="Corner Vault One")
        response = api.create_vault(payload, make_manager_headers(MANAGER_1))
        vault = validate_success(response, 201)

        assert_vault(vault)
        assert vault["posture"] == "OPEN", f"Expected posture OPEN, got {vault['posture']}"
        assert vault["pickup_concurrency_limit"] == 2, (
            f"Expected the default pickup_concurrency_limit 2, got {vault['pickup_concurrency_limit']}"
        )
        assert vault["version"] == 1, f"Expected version 1 at creation, got {vault['version']}"
        assert vault["coin_face_value_on_hand_cents"] == 0
        assert vault["cash_letter_adjustment_cents"] == 0

    def test_duplicate_business_identifiers_are_rejected_across_collections(self, api):
        """PRD §3.1: "A `vault_code` that collides with an existing vault is rejected
        with `ERR_DUPLICATE_IDENTIFIER`."
        PRD §3.1: "A duplicate `account_number` is `ERR_DUPLICATE_IDENTIFIER`."
        PRD §3.2: "the `courier_manifest_number` covering the run — unique across all
        deposit tickets, and a collision is `ERR_DUPLICATE_IDENTIFIER`"

        Design: Corner/validations/duplicate_business_identifiers_rejected_across_collections
        """
        manager = make_manager_headers(MANAGER_1)
        carrier = make_carrier_headers(CARRIER_1)

        vault = create_vault(vault_code="CV-C24", name="Corner Vault TwentyFour")
        account = create_account(account_number="ACC-C24", customer_name="Corner Copy TwentyFour")
        create_ticket(
            account["id"], vault["id"], courier_manifest_number="MAN-C24", declared_bag_count=1
        )

        duplicate_vault = api.create_vault(
            create_vault_payload(vault_code="CV-C24", name="Duplicate Vault Code"), manager
        )
        validate_error(duplicate_vault, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

        duplicate_account = api.create_customer_account(
            create_customer_account_payload(
                account_number="ACC-C24", customer_name="Duplicate Account Number"
            ),
            manager,
        )
        validate_error(duplicate_account, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

        duplicate_ticket = api.create_deposit_ticket(
            create_deposit_ticket_payload(
                account["id"],
                vault["id"],
                courier_manifest_number="MAN-C24",
                declared_bag_count=1,
            ),
            carrier,
        )
        validate_error(duplicate_ticket, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

        for response in (duplicate_vault, duplicate_account, duplicate_ticket):
            assert response.status_code == 409, (
                f"ERR_DUPLICATE_IDENTIFIER must be HTTP 409, got {response.status_code}"
            )


class TestDepositorAccounts:
    def test_customer_account_without_customer_name_is_rejected(self, api):
        """PRD §3.1: "Depositor accounts are opened by a manager against an
        `account_number` unique across all accounts, together with the depositor's legal
        `customer_name`."
        PRD §2.6: "**Request shape.** Required fields present, types correct, enum members
        recognised, constrained integers non-negative, `limit` within 1 through 100 and
        `offset` at least 0, `window_end` strictly after `window_start`,
        `pickup_window_end` strictly after `pickup_window_start`, a coin order's `lines`
        array non-empty, and a count-completion's `lots` array non-empty —
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/customer_account_missing_required_field_returns_invalid_request
        """
        create_vault(vault_code="CV-C02", name="Corner Vault Two")

        response = api.create_customer_account(
            {"account_number": "ACC-C02"}, make_manager_headers(MANAGER_1)
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert response.status_code == 400, (
            f"ERR_INVALID_REQUEST must be HTTP 400, got {response.status_code}"
        )


class TestCountingMachines:
    def test_unrecognised_machine_type_is_rejected(self, api):
        """PRD §3.1: "A manager commissions a machine on a vault floor by naming the
        `vault_id` it sits on, a `machine_code` that must be unique across all machines,
        and a `machine_type` of `CURRENCY_SORTER`, `COIN_COUNTER`, or `MIXED_PROCESSOR`."
        PRD §2.6: "**Request shape.** Required fields present, types correct, enum members
        recognised, constrained integers non-negative, `limit` within 1 through 100 and
        `offset` at least 0, `window_end` strictly after `window_start`,
        `pickup_window_end` strictly after `pickup_window_start`, a coin order's `lines`
        array non-empty, and a count-completion's `lots` array non-empty —
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/counting_machine_invalid_enum_machine_type_rejected
        """
        manager = make_manager_headers(MANAGER_1)
        vault = create_vault(vault_code="CV-C06", name="Corner Vault Six")

        response = api.create_counting_machine(
            create_counting_machine_payload(
                vault["id"], machine_code="BAD-1", machine_type="SHREDDER"
            ),
            manager,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert response.status_code == 400

        listing = api.list_counting_machines(manager, params={"vault_id": vault["id"]})
        machines, meta = validate_paginated(listing)
        assert meta["total_count"] == 0, (
            f"No machine may exist after a rejected commissioning, got {meta['total_count']}"
        )
        assert machines == []


class TestIntakeTickets:
    def test_new_deposit_ticket_starts_in_intake_with_zeroed_money_fields(self, api):
        """PRD §3.2: "The ticket is created in `INTAKE`, its `carrier_courier_user_id`
        captured from the caller's `X-User-ID`, and every computed money field —
        `declared_total_cents`, `counted_total_cents`, `processing_fee_total_cents`,
        `provisional_credit_cents`, `final_settlement_cents`, `settlement_delta_cents` —
        and the counter `material_variance_open_count` all starting at 0, with
        `hold_reason` null."

        Design: Corner/state_machines/deposit_ticket_initial_state_is_intake
        """
        vault = create_vault(vault_code="CV-C10", name="Corner Vault Ten")
        account = create_account(account_number="ACC-C10", customer_name="Corner Bistro Ten")

        response = api.create_deposit_ticket(
            create_deposit_ticket_payload(
                account["id"],
                vault["id"],
                courier_manifest_number="MAN-C10",
                declared_bag_count=1,
            ),
            make_carrier_headers(CARRIER_1),
        )
        ticket = validate_success(response, 201)

        assert_deposit_ticket(ticket)
        assert ticket["status"] == "INTAKE", f"Expected INTAKE, got {ticket['status']}"
        assert ticket["carrier_courier_user_id"] == CARRIER_1, (
            "carrier_courier_user_id must be captured from the caller's X-User-ID"
        )
        assert ticket["counted_total_cents"] == 0
        assert ticket["provisional_credit_cents"] == 0
        assert ticket["material_variance_open_count"] == 0

    def test_reading_an_unknown_deposit_ticket_returns_ticket_not_found(self, api):
        """PRD §2.5: "The not-found errors are entity-specific: `ERR_VAULT_NOT_FOUND`,
        `ERR_CUSTOMER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_BAG_NOT_FOUND`,
        `ERR_MACHINE_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_FED_DEPOSIT_NOT_FOUND`, and
        `ERR_COIN_ORDER_NOT_FOUND`, all returning HTTP 404."

        Design: Corner/entities/deposit_ticket_get_with_unknown_id_returns_not_found
        """
        create_vault(vault_code="CV-C04", name="Corner Vault Four")

        response = api.get_deposit_ticket(UNKNOWN_UUID, make_manager_headers(MANAGER_1))
        validate_error(response, ApiErrorId.ERR_TICKET_NOT_FOUND.value)
        assert response.status_code == 404

    def test_deposit_ticket_list_filters_by_depositor_and_pages(self, api):
        """PRD §3.2: "Tickets can be read one at a time or listed with optional
        `customer_account_id`, `vault_id` and `status` filters alongside `limit` and
        `offset`."
        PRD §2.3: "For list responses the `meta` object carries `limit`, `offset`,
        `total_count` and `has_more` in addition to `api_request_id` and
        `api_request_timestamp`; `total_count` is the number of rows matching the filters
        before the page window is applied, and `has_more` is true exactly when rows remain
        beyond the current page."

        Design: Corner/entities/deposit_ticket_list_paginates_and_filters_by_customer
        """
        manager = make_manager_headers(MANAGER_1)
        vault = create_vault(vault_code="CV-C08", name="Corner Vault Eight")
        account = create_account(account_number="ACC-C08", customer_name="Corner Grocer Eight")
        for manifest in ("MAN-C08A", "MAN-C08B", "MAN-C08C"):
            create_ticket(
                account["id"],
                vault["id"],
                courier_manifest_number=manifest,
                declared_bag_count=1,
            )

        first_page, first_meta = validate_paginated(
            api.list_deposit_tickets(
                manager, params={"customer_account_id": account["id"], "limit": 2, "offset": 0}
            )
        )
        assert len(first_page) == 2, f"Expected 2 rows on the first page, got {len(first_page)}"
        assert first_meta["total_count"] == 3, (
            f"Expected total_count 3, got {first_meta['total_count']}"
        )
        assert first_meta["has_more"] is True, "Rows remain beyond the first page"

        second_page, second_meta = validate_paginated(
            api.list_deposit_tickets(
                manager, params={"customer_account_id": account["id"], "limit": 2, "offset": 2}
            )
        )
        assert len(second_page) == 1, f"Expected 1 row on the second page, got {len(second_page)}"
        assert second_meta["has_more"] is False, "No rows remain beyond the second page"

        for ticket in first_page + second_page:
            assert_deposit_ticket(ticket)
            assert ticket["customer_account_id"] == account["id"], (
                "The customer_account_id filter must exclude other depositors' tickets"
            )

    def test_pagination_limit_above_one_hundred_is_rejected(self, api):
        """PRD §2.3: "`limit` controls page size: it defaults to 10, its minimum accepted
        value is 1, and its maximum accepted value is 100."
        PRD §2.3: "A `limit` outside the range 1 through 100 inclusive, or a negative
        `offset`, is a malformed query and is rejected with `ERR_INVALID_REQUEST` (HTTP
        400)."

        Design: Corner/entities/pagination_limit_above_maximum_returns_invalid_request
        """
        manager = make_manager_headers(MANAGER_1)
        create_vault(vault_code="CV-C09", name="Corner Vault Nine")
        account = create_account(account_number="ACC-C09", customer_name="Corner Market Nine")

        response = api.list_deposit_tickets(
            manager, params={"customer_account_id": account["id"], "limit": 101, "offset": 0}
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert response.status_code == 400


class TestSealedBagRegistration:
    def test_sealed_bag_optional_declared_counts_default_to_zero(self, api):
        """PRD §3.2: "The declared contents follow: `declared_amount_cents`, the amount
        the customer wrote on the bag manifest, which may be zero but not negative; and
        optionally `declared_note_count` and `declared_coin_weight_grams`, both defaulting
        to 0."
        PRD §3.2: "A newly registered bag is `SEALED` on the custody axis and `PENDING` on
        the counting axis."
        PRD §3.2: "Registering a bag recomputes the parent ticket's
        `declared_total_cents` as the sum of `declared_amount_cents` across every bag
        carrying that `deposit_ticket_id`."

        Design: Corner/entities/sealed_bag_defaults_zero_when_optional_declared_counts_omitted
        """
        vault = create_vault(vault_code="CV-C03", name="Corner Vault Three")
        account = create_account(account_number="ACC-C03", customer_name="Corner Cafe Three")
        ticket = create_ticket(
            account["id"], vault["id"], courier_manifest_number="MAN-C03", declared_bag_count=1
        )

        response = api.create_sealed_bag(
            {
                "deposit_ticket_id": ticket["id"],
                "seal_number": "S-C03",
                "bag_type": "CURRENCY",
                "declared_amount_cents": 50_000,
            },
            make_carrier_headers(CARRIER_1),
        )
        bag = validate_success(response, 201)

        assert_sealed_bag(bag)
        assert bag["declared_note_count"] == 0, "declared_note_count defaults to 0"
        assert bag["declared_coin_weight_grams"] == 0, "declared_coin_weight_grams defaults to 0"
        assert bag["custody_status"] == "SEALED"
        assert bag["count_status"] == "PENDING"
        assert bag["version"] == 1, f"A freshly created row starts at version 1, got {bag['version']}"

        refreshed_ticket = validate_success(
            api.get_deposit_ticket(ticket["id"], make_manager_headers(MANAGER_1))
        )
        assert refreshed_ticket["declared_total_cents"] == 50_000, (
            "Registering a bag recomputes the ticket's declared_total_cents"
        )

    def test_sealed_bag_naming_an_unknown_ticket_returns_ticket_not_found(self, api):
        """PRD §2.5: "The same family of not-found errors covers foreign-key identifiers
        supplied inside a request body."
        PRD §2.5: "This body-reference resolution applies to the creation of deposit
        tickets, sealed bags, counting machines, count sessions, counterfeit reports,
        discrepancy claims, cash letters, and coin orders."

        Design: Corner/entities/sealed_bag_with_unknown_deposit_ticket_returns_not_found
        """
        create_vault(vault_code="CV-C07", name="Corner Vault Seven")

        response = api.create_sealed_bag(
            create_sealed_bag_payload(
                UNKNOWN_UUID,
                seal_number="S-C07",
                bag_type="CURRENCY",
                declared_amount_cents=50_000,
            ),
            make_carrier_headers(CARRIER_1),
        )
        validate_error(response, ApiErrorId.ERR_TICKET_NOT_FOUND.value)
        assert response.status_code == 404
