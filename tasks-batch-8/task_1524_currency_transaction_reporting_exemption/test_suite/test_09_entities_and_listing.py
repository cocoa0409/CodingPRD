"""Entity defaults, computed fields, FK integrity, 404 family, listing (PRD §2, §3)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_branch,
    create_customer,
    get_success_data,
    make_admin_headers,
    make_manager_headers,
    make_officer_headers,
    make_teller_headers,
    post_cash_txn,
    post_instrument_sale,
    set_clock,
    setup_branch_and_customer,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEntityDefaults:
    def test_branch_creation_defaults_and_system_fields(self, api):
        """PRD §3.1: "Every branch carries a system-managed `status` of `ACTIVE`
        or `INACTIVE` and is born `ACTIVE`."
        PRD §3.1: "an optional `region` label that defaults to null when omitted".
        PRD §2.4: "Before the clock has been set by any call, the logical clock
        starts at exactly `2026-08-01T00:00:00Z`."

        Design: Corner/entities/branch_creation_defaults_and_system_fields
        """
        # No explicit clock-set: branch is stamped with the default logical clock
        resp = api_client.create_branch(
            {"name": "Main", "branch_code": "BR1"}, headers=make_admin_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"
        assert data["region"] is None
        assert data["version"] == 1
        assert data["created_at"] == "2026-08-01T00:00:00.000Z"

    def test_customer_creation_tin_optional_defaults(self, api):
        """PRD §3.1: "an optional `tin` (taxpayer identification number, nullable
        at creation but required before any CTR for the customer can be
        validated)".
        PRD §3.1: "A customer is born `ACTIVE` and carries two system-maintained
        fields: `structuring_referral_count`, the number of structuring alerts
        ever referred for the customer (initially zero), and
        `active_exemption_id`, the `id` of the designation currently in `ACTIVE`
        status for the customer (null when none)."

        Design: Corner/entities/customer_creation_tin_optional_defaults
        """
        resp = api_client.create_customer(
            {
                "legal_name": "No Tin Nancy",
                "customer_type": "INDIVIDUAL",
                "account_opened_date": "2026-01-15T00:00:00Z",
            },
            headers=make_manager_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert data["tin"] is None
        assert data["status"] == "ACTIVE"
        assert data["structuring_referral_count"] == 0
        assert data["active_exemption_id"] is None

    def test_cash_transaction_computed_business_date(self, api):
        """PRD §3.2: "On acceptance the transaction is born `POSTED`, its
        `business_date` is derived as the UTC date of `occurred_at`, and
        `voided_at` remains null."

        Design: Corner/entities/cash_transaction_computed_business_date
        """
        branch, customer = setup_branch_and_customer()
        txn = post_cash_txn(customer["id"], branch["id"], amount_cents=500_000,
                            occurred_at="2026-08-01T08:59:00Z")
        assert txn["business_date"] == "2026-08-01"
        assert txn["status"] == "POSTED"

    def test_instrument_sale_computed_fee_record_retention(self, api):
        """PRD §3.3: "The system computes `record_required` as true exactly when
        the amount is at least 300000 cents and at most 1000000 cents—the
        recordkeeping band."
        PRD §3.3: "Each sale carries a per-instrument `fee_cents`, computed as
        the greater of 150 cents and the sale's `amount_cents` multiplied by 50
        basis points ... rounded half-up to whole cents."
        PRD §3.3: "Every recorded sale also derives a `retention_until`
        timestamp exactly five years after `occurred_at`, the statutory
        retention horizon for the record."
        PRD §3.3: "A sale is born `RECORDED`".

        Design: Corner/entities/instrument_sale_computed_fee_record_retention
        """
        branch, customer = setup_branch_and_customer()
        sale = post_instrument_sale(
            customer["id"], branch["id"], amount_cents=500_000,
            occurred_at="2026-08-01T08:00:00Z",
            purchaser_name="Sally", purchaser_tin="20-2020202",
            purchaser_address="2 Oak Ave", purchaser_id_number="PP-9",
        )
        assert sale["fee_cents"] == 2500
        assert sale["record_required"] is True
        # PRD §3.3 pins the retention instant (exactly five years after
        # occurred_at), not the string format — compare parsed instants.
        from datetime import datetime, timezone
        retention = datetime.fromisoformat(sale["retention_until"].replace("Z", "+00:00"))
        assert retention == datetime(2031, 8, 1, 8, 0, 0, tzinfo=timezone.utc)
        assert sale["status"] == "RECORDED"


class TestNotFoundFamily:
    def test_not_found_family_sweep_returns_entity_specific_404(self, api):
        """PRD §2.6: "Requests that target nested resources validate path
        identifiers sequentially from left to right, rejecting immediately with
        the per-entity 404 error for the first identifier that fails to resolve.
        ... analogous lookups surface `ERR_BRANCH_NOT_FOUND`,
        `ERR_CUSTOMER_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`,
        `ERR_INSTRUMENT_SALE_NOT_FOUND`, `ERR_AGGREGATION_NOT_FOUND`,
        `ERR_CTR_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, or `ERR_FINDING_NOT_FOUND`
        according to the path segment that failed."

        Design: Corner/entities/not_found_family_sweep_returns_entity_specific_404
        """
        h = make_teller_headers()
        cases = [
            (api_client.get_customer, ApiErrorId.ERR_CUSTOMER_NOT_FOUND),
            (api_client.get_ctr, ApiErrorId.ERR_CTR_NOT_FOUND),
            (api_client.get_structuring_alert, ApiErrorId.ERR_ALERT_NOT_FOUND),
            (api_client.get_examination_case, ApiErrorId.ERR_CASE_NOT_FOUND),
            (api_client.get_daily_aggregation, ApiErrorId.ERR_AGGREGATION_NOT_FOUND),
            (api_client.get_examination_finding, ApiErrorId.ERR_FINDING_NOT_FOUND),
            (api_client.get_cash_transaction, ApiErrorId.ERR_TRANSACTION_NOT_FOUND),
            (api_client.get_instrument_sale, ApiErrorId.ERR_INSTRUMENT_SALE_NOT_FOUND),
            (api_client.get_exemption_designation, ApiErrorId.ERR_EXEMPTION_NOT_FOUND),
            (api_client.get_branch, ApiErrorId.ERR_BRANCH_NOT_FOUND),
        ]
        for fn, expected_err in cases:
            resp = fn(NON_EXISTENT_UUID, headers=h)
            validate_error(resp, expected_err)


class TestForeignKeyIntegrity:
    def test_fk_integrity_body_references_validated(self, api):
        """PRD §2.6: "Body-supplied foreign keys are checked in the order the
        endpoint declares them: on cash transaction and instrument sale creation
        the `customer_id` reference is resolved first (yielding
        `ERR_CUSTOMER_NOT_FOUND` when unresolvable), then the `branch_id`
        reference (yielding `ERR_BRANCH_NOT_FOUND`)."

        Design: Corner/entities/fk_integrity_body_references_validated
        """
        branch, customer = setup_branch_and_customer()
        r1 = api_client.create_cash_transaction(
            {
                "customer_id": NON_EXISTENT_UUID, "branch_id": branch["id"],
                "direction": "CASH_IN", "amount_cents": 100,
                "occurred_at": "2026-08-01T08:00:00Z",
            },
            headers=make_teller_headers(),
        )
        validate_error(r1, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)
        r2 = api_client.create_cash_transaction(
            {
                "customer_id": customer["id"], "branch_id": NON_EXISTENT_UUID,
                "direction": "CASH_IN", "amount_cents": 100,
                "occurred_at": "2026-08-01T08:00:00Z",
            },
            headers=make_teller_headers(),
        )
        validate_error(r2, ApiErrorId.ERR_BRANCH_NOT_FOUND)


class TestPagination:
    def test_list_pagination_limit_offset_has_more(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10 when omitted, accepts a minimum of 1, and
        accepts a maximum of 100. The `offset` parameter sets the number of
        items skipped before the page begins and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/entities/list_pagination_limit_offset_has_more
        """
        branch, customer = setup_branch_and_customer()
        for i in range(3):
            post_cash_txn(customer["id"], branch["id"], amount_cents=100_000,
                          occurred_at=f"2026-08-01T07:{i*5:02d}:00Z")
        r1 = api_client.list_cash_transactions(
            headers=make_teller_headers(),
            params={"customer_id": customer["id"], "limit": 2, "offset": 0},
        )
        page1, meta1 = validate_paginated(r1)
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2
        r2 = api_client.list_cash_transactions(
            headers=make_teller_headers(),
            params={"customer_id": customer["id"], "limit": 2, "offset": 2},
        )
        page2, meta2 = validate_paginated(r2)
        assert meta2["has_more"] is False
        assert len(page2) == 1


class TestCrossEntityStateDependency:
    def test_cash_transaction_requires_active_customer(self, api):
        """PRD §3.1: "Transactions, instrument sales, and exemption designation
        requests may only be posted for an `ACTIVE` customer; posting for a
        `SUSPENDED` or `CLOSED` customer is rejected with
        `ERR_CUSTOMER_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/cash_transaction_requires_active_customer
        """
        branch, customer = setup_branch_and_customer()
        get_success_data(api_client.suspend_customer(customer["id"], headers=make_manager_headers()))
        resp = api_client.create_cash_transaction(
            {
                "customer_id": customer["id"], "branch_id": branch["id"],
                "direction": "CASH_IN", "amount_cents": 500_000,
                "occurred_at": "2026-08-01T08:00:00Z",
            },
            headers=make_teller_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE)
        # Reactivate unblocks posting
        get_success_data(api_client.reactivate_customer(customer["id"], headers=make_manager_headers()))
        ok = post_cash_txn(customer["id"], branch["id"], amount_cents=500_000,
                           occurred_at="2026-08-01T08:05:00Z")
        assert ok["status"] == "POSTED"

    def test_cash_transaction_blocked_again_when_customer_closed(self, api):
        """PRD §3.1: "Transactions, instrument sales, and exemption designation
        requests may only be posted for an `ACTIVE` customer; posting for a
        `SUSPENDED` or `CLOSED` customer is rejected with
        `ERR_CUSTOMER_NOT_ACTIVE`."

        Independent confirmation on the CLOSED branch (instead of SUSPENDED).

        Design: Difficulty/cross_entity_state_dependency/cash_transaction_requires_active_customer
        """
        branch, customer = setup_branch_and_customer()
        get_success_data(api_client.close_customer(customer["id"], headers=make_manager_headers()))
        resp = api_client.create_cash_transaction(
            {
                "customer_id": customer["id"], "branch_id": branch["id"],
                "direction": "CASH_IN", "amount_cents": 500_000,
                "occurred_at": "2026-08-01T08:00:00Z",
            },
            headers=make_teller_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE)


class TestBranchPrecondition:
    def test_branch_inactive_blocks_posting(self, api):
        """PRD §3.1: "Posting cash activity to an `INACTIVE` branch is refused
        with `ERR_BRANCH_INACTIVE`."
        PRD §3.1: "A `SystemAdmin` may deactivate an `ACTIVE` branch, moving it
        `ACTIVE → INACTIVE`, and may later reactivate an `INACTIVE` branch,
        moving it `INACTIVE → ACTIVE`".

        Design: Corner/state_machines/branch_inactive_blocks_posting
        """
        branch, customer = setup_branch_and_customer()
        get_success_data(api_client.deactivate_branch(branch["id"], headers=make_admin_headers()))
        resp = api_client.create_cash_transaction(
            {
                "customer_id": customer["id"], "branch_id": branch["id"],
                "direction": "CASH_IN", "amount_cents": 100_000,
                "occurred_at": "2026-08-01T08:00:00Z",
            },
            headers=make_teller_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_BRANCH_INACTIVE)
        get_success_data(api_client.reactivate_branch(branch["id"], headers=make_admin_headers()))
        ok = post_cash_txn(customer["id"], branch["id"], amount_cents=100_000,
                           occurred_at="2026-08-01T08:05:00Z")
        assert ok["status"] == "POSTED"


class TestCustomerCloseGuard:
    def test_customer_closed_terminal_and_close_guard(self, api):
        """PRD §3.1: "Closing a customer is permitted from either `ACTIVE` or
        `SUSPENDED`, moving the customer to the terminal `CLOSED` state, but
        only when the customer has no open items: no CTR in `DRAFT`,
        `VALIDATED`, `FILED`, or `AMENDMENT_REQUIRED`, and no structuring alert
        in `OPEN` or `UNDER_REVIEW`. A close attempted against either kind of
        open item is rejected with `ERR_CUSTOMER_HAS_OPEN_ITEMS`."
        PRD §2.10 step 6: "the requested action is a valid transition from the
        record's current status (else `ERR_INVALID_STATE_TRANSITION`)".

        Design: Corner/state_machines/customer_closed_terminal_and_close_guard
        """
        branch, customer = setup_branch_and_customer()
        txn = post_cash_txn(customer["id"], branch["id"], amount_cents=1_100_000,
                            occurred_at="2026-08-01T08:00:00Z")
        # Live DRAFT CTR blocks close
        r1 = api_client.close_customer(customer["id"], headers=make_manager_headers())
        validate_error(r1, ApiErrorId.ERR_CUSTOMER_HAS_OPEN_ITEMS)
        # Void the only transaction -> ctr_required flips false -> CTR auto-VOIDED
        get_success_data(api_client.void_cash_transaction(
            txn["id"], {"void_reason": "rescinded"}, headers=make_manager_headers(),
        ))
        closed = get_success_data(api_client.close_customer(
            customer["id"], headers=make_manager_headers(),
        ))
        assert closed["status"] == "CLOSED"
        # CLOSED is terminal: suspend is rejected
        r2 = api_client.suspend_customer(customer["id"], headers=make_manager_headers())
        validate_error(r2, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestInstrumentRecordkeepingBand:
    def test_instrument_recordkeeping_band_floor_2999_vs_3000(self, api):
        """PRD §3.3: "The system computes `record_required` as true exactly when
        the amount is at least 300000 cents and at most 1000000 cents—the
        recordkeeping band. When `record_required` is true, all four purchaser
        fields are mandatory: `purchaser_name`, `purchaser_tin`,
        `purchaser_address`, and `purchaser_id_number`; a sale in the band
        missing any of the four is rejected with
        `ERR_INSTRUMENT_RECORD_INCOMPLETE`. Outside the band the four fields
        are optional and default to null."

        Design: Difficulty/boundary_precision_check/instrument_recordkeeping_band_floor_2999_vs_3000
        """
        branch, customer = setup_branch_and_customer()
        # 299999: below the band floor -> no record required
        s1 = post_instrument_sale(customer["id"], branch["id"], amount_cents=299_999,
                                  occurred_at="2026-08-01T08:00:00Z")
        assert s1["record_required"] is False
        # 300000 (band floor, inclusive) without purchaser fields -> rejected
        resp = api_client.create_instrument_sale(
            {
                "customer_id": customer["id"], "branch_id": branch["id"],
                "instrument_type": "CASHIERS_CHECK", "amount_cents": 300_000,
                "occurred_at": "2026-08-01T08:05:00Z",
            },
            headers=make_teller_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INSTRUMENT_RECORD_INCOMPLETE)
        # Same amount with all four purchaser fields succeeds
        s3 = post_instrument_sale(
            customer["id"], branch["id"], amount_cents=300_000,
            occurred_at="2026-08-01T08:06:00Z",
            purchaser_name="Irene", purchaser_tin="45-4545454",
            purchaser_address="1 Main St", purchaser_id_number="DL-123",
        )
        assert s3["record_required"] is True

    def test_instrument_recordkeeping_band_ceiling(self, api):
        """PRD §3.3: "The system computes `record_required` as true exactly when
        the amount is at least 300000 cents and at most 1000000 cents—the
        recordkeeping band."
        PRD §3.3: "Outside the band the four fields are optional and default to
        null."

        Independent confirmation at the band ceiling: 1000000 (inclusive, in
        band) requires purchaser fields; 1000001 (just over) does not.

        Design: Difficulty/boundary_precision_check/instrument_recordkeeping_band_floor_2999_vs_3000
        """
        branch, customer = setup_branch_and_customer()
        # 1000000: at ceiling (inclusive) -> record required
        resp = api_client.create_instrument_sale(
            {
                "customer_id": customer["id"], "branch_id": branch["id"],
                "instrument_type": "CASHIERS_CHECK", "amount_cents": 1_000_000,
                "occurred_at": "2026-08-01T08:00:00Z",
            },
            headers=make_teller_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INSTRUMENT_RECORD_INCOMPLETE)
        # 1000001: just above the ceiling -> purchaser fields optional
        ok = post_instrument_sale(customer["id"], branch["id"], amount_cents=1_000_001,
                                  occurred_at="2026-08-01T08:05:00Z")
        assert ok["record_required"] is False
