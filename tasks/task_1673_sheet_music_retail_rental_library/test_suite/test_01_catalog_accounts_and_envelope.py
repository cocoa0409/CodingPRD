"""Catalog onboarding, account creation shape rules, and list-envelope behavior."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_publisher,
    assert_rental_order,
    assert_rental_set,
    create_account,
    create_publisher,
    create_rental_set,
    create_work,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ADMIN, CLERK


class TestPublisherOnboarding:
    def test_create_publisher_applies_flag_defaults(self, api):
        """PRD §3.1: "`rental_discount_pct` — a value from 0 to 0.60 inclusive,
        defaulting to 0"; "`allows_digital_perusal` (default false)";
        "`print_only_rental` (default false)"; "`out_of_print` (default false)".
        PRD §3.1: "A publisher's `status` is `ACTIVE` or `SUSPENDED`; suspension
        blocks all new rental, perusal, and purchase activity on its works."

        Design: Corner/entities/create_publisher_applies_defaults
        """
        created = validate_success(
            api.create_publisher({"name": "Default Pub"}, ADMIN), 201
        )
        assert_publisher(created)

        fetched = validate_success(api.get_publisher(created["id"], ADMIN))
        assert fetched["rental_discount_pct"] == 0
        assert fetched["allows_digital_perusal"] is False
        assert fetched["print_only_rental"] is False
        assert fetched["out_of_print"] is False
        assert fetched["status"] == "ACTIVE"


class TestWorkCataloging:
    def test_create_work_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.9: "request-payload shape — required fields present, enum values
        valid, `due_date` later than `checkout_date`, quantities at least 1, dates
        well-formed — else `ERR_INVALID_REQUEST`".
        PRD §3.1: "`base_rental_rate_cents` (the per-copy, per-loan-period rate)
        and `sale_price_cents` (the per-copy retail price) must both be greater
        than zero."

        Design: Corner/entities/create_work_missing_required_field_returns_invalid_request
        """
        publisher = create_publisher("Req Pub")

        resp = api.create_work(
            {
                "publisher_id": publisher["id"],
                "title": "No Rate",
                "catalog_number": "RP-1",
                "ensemble_tier": "CHAMBER",
                "sale_price_cents": 500,
                "license_format": "PRINT_ONLY",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_nonexistent_work_returns_not_found(self, api):
        """PRD §2.8: "The first identifier that does not correspond to an existing
        resource produces the resource-specific 404 error: `ERR_ACCOUNT_NOT_FOUND`,
        `ERR_PUBLISHER_NOT_FOUND`, `ERR_WORK_NOT_FOUND`, ..."

        Design: Corner/entities/get_nonexistent_work_returns_not_found
        """
        resp = api.get_work("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN)
        validate_error(resp, ApiErrorId.ERR_WORK_NOT_FOUND)

    def test_work_list_pagination_envelope(self, api):
        """PRD §2.3: "`limit` specifies the maximum number of items to return; it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
        specifies how many items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of list responses carries `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/work_list_pagination_envelope
        """
        publisher = create_publisher("Page Pub")
        for idx in (1, 2, 3):
            create_work(
                publisher["id"],
                title=f"W{idx}",
                catalog_number=f"PG-{idx}",
                base_rental_rate_cents=1000,
                sale_price_cents=500,
            )

        resp_page1 = api.list_works(CLERK, params={"limit": 2})
        page1, meta1 = validate_paginated(resp_page1)
        assert resp_page1.json()["response_type"] == "array"
        assert len(page1) == 2, f"limit=2 must return 2 rows, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        resp_page2 = api.list_works(CLERK, params={"limit": 2, "offset": 2})
        page2, meta2 = validate_paginated(resp_page2)
        assert len(page2) == 1, f"offset=2 must skip to the last row, got {len(page2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestRentalSetCreation:
    def test_rental_set_computed_available_copy_count_ignores_client_input(self, api):
        """PRD §3.2: "`available_copy_count` is a computed ledger field: any
        client-supplied value at creation is ignored, and it always starts equal
        to `copy_count`."
        PRD §3.2: "Creation initializes `condition_grade` to `A` and `status` to
        `IN_SERVICE`."

        Design: Corner/entities/rental_set_computed_available_copy_count_ignores_client_input
        """
        publisher = create_publisher("CF Pub")
        work = create_work(
            publisher["id"], title="CF Work", catalog_number="CF-1",
            ensemble_tier="BAND", base_rental_rate_cents=8000, sale_price_cents=1200,
        )

        created = validate_success(
            api.create_rental_set(
                {
                    "work_id": work["id"],
                    "set_code": "CF-SET",
                    "copy_count": 12,
                    "replacement_value_cents": 96000,
                    "available_copy_count": 999,
                },
                ADMIN,
            ),
            201,
        )
        assert_rental_set(created)
        assert created["available_copy_count"] == 12, (
            f"client-supplied 999 must be ignored; got "
            f"{created['available_copy_count']}"
        )
        assert created["condition_grade"] == "A"
        assert created["status"] == "IN_SERVICE"


class TestAccountCreation:
    def test_invalid_enum_value_rejected_on_account_create(self, api):
        """PRD §2.9: "request-payload shape — required fields present, enum values
        valid, `due_date` later than `checkout_date`, quantities at least 1, dates
        well-formed — else `ERR_INVALID_REQUEST`."
        PRD §3.3: "`account_kind` (`INDIVIDUAL`, `SCHOOL`, or `INSTITUTION`)".

        Design: Corner/entities/invalid_enum_value_rejected_on_account_create
        """
        resp = api.create_customer_account(
            {"account_name": "Bad Enum", "account_kind": "DISTRICT"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestRentalOrderCreation:
    def test_due_date_not_after_checkout_rejected(self, api):
        """PRD §3.5: "`due_date`, which must be later than `checkout_date` or the
        request fails shape validation with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/due_date_not_after_checkout_rejected
        """
        publisher = create_publisher("DD Pub")
        work = create_work(publisher["id"], title="DD Work", catalog_number="DD-1")
        rental_set = create_rental_set(work["id"], set_code="DD-SET", copy_count=5,
                                       replacement_value_cents=40000)
        account = create_account("DD Acct", account_kind="INDIVIDUAL")
        advance_clock()

        resp = api.create_rental_order(
            {
                "account_id": account["id"],
                "rental_set_id": rental_set["id"],
                "copies_requested": 1,
                "checkout_date": "2026-08-05",
                "due_date": "2026-08-05",
            },
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_rental_order_initial_state_is_draft(self, api):
        """PRD §3.5: "The order is born in `DRAFT` with `loan_periods` already
        computed — the number of 30-day loan periods spanned by the half-open
        window from `checkout_date` to `due_date`, rounded up, and never less than
        one — and with `renewal_count` and `prepayment_cents` at 0."

        Design: Corner/state_machines/rental_order_initial_state_is_draft
        """
        publisher = create_publisher("IS Pub")
        work = create_work(publisher["id"], title="IS Work", catalog_number="IS-1")
        rental_set = create_rental_set(work["id"], set_code="IS-SET", copy_count=5,
                                       replacement_value_cents=40000)
        account = create_account("IS Acct", account_kind="INDIVIDUAL")

        created = validate_success(
            api.create_rental_order(
                {
                    "account_id": account["id"],
                    "rental_set_id": rental_set["id"],
                    "copies_requested": 1,
                    "checkout_date": "2026-08-05",
                    "due_date": "2026-09-04",
                },
                CLERK,
            ),
            201,
        )
        assert_rental_order(created)
        assert created["status"] == "DRAFT"
        assert created["renewal_count"] == 0
        assert created["prepayment_cents"] == 0
        # [2026-08-05, 2026-09-04) spans exactly 30 days -> ceil(30/30) == 1 period.
        assert created["loan_periods"] == 1
