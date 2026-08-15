"""Borrower registration, loan origination defaults, ledger shape, envelope."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_budget_line,
    assert_borrower,
    assert_budget_line,
    assert_interest_reserve_entry,
    assert_loan,
    create_borrower,
    create_borrower_payload,
    create_loan,
    create_loan_payload,
    get_loan,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_borrower_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["lender_admin_headers"]
PROCESSOR = TEST_USERS["draw_processor_headers"]
OFFICER = TEST_USERS["credit_officer_headers"]
SERVICER = TEST_USERS["loan_servicer_headers"]


class TestBorrowerCreation:
    def test_borrower_creation_and_retrieval(self, api):
        """PRD §3.1: "Registration captures the borrower's `legal_name`, a primary
        `contact_email`, and an `entity_type` of `INDIVIDUAL`, `LLC`, `CORPORATION`,
        or `PARTNERSHIP`."
        PRD §2.4: "a `version` integer that starts at 1 when the resource is created
        and increments by one on every mutation of that resource."
        PRD §3.1: "A borrower record can be fetched by id by any role."

        Design: Corner/entities/borrower_creation_and_retrieval
        """
        resp = api.create_borrower(
            create_borrower_payload(legal_name="Acme Builders LLC",
                                    contact_email="ops@acme.example",
                                    entity_type="LLC"),
            ADMIN,
        )
        borrower = validate_success(resp, 201)
        assert_borrower(borrower)
        assert borrower["legal_name"] == "Acme Builders LLC"
        assert borrower["entity_type"] == "LLC"
        assert borrower["version"] == 1, "A new borrower is born with version 1"
        assert is_valid_uuid(borrower["id"])
        assert is_iso8601_timestamp(borrower["created_at"])

        fetched = validate_success(api.get_borrower(borrower["id"], PROCESSOR))
        assert_borrower(fetched)
        assert fetched["id"] == borrower["id"]
        assert fetched["legal_name"] == borrower["legal_name"]
        assert fetched["created_at"] == borrower["created_at"]
        assert fetched["updated_at"] == borrower["updated_at"]


class TestLoanOrigination:
    def test_loan_creation_seeds_initial_deposit(self, api):
        """PRD §3.1: "A new loan is born `OPEN`. Origination seeds the interest
        reserve ledger with an `INITIAL_DEPOSIT` entry: its `entry_index` is 1, its
        `amount_cents` is the positive `interest_reserve_initial_cents`, and its
        `reserve_balance_after_cents` equals that same initial amount."
        PRD §3.1: "Four policy knobs are optional and default when omitted:
        `day_count_convention` selects the interest accrual variant and defaults to
        `ACTUAL_360` (the alternative being `THIRTY_360`); `retainage_pct`, the
        standard percent withheld from each approved draw line, defaults to 10.00;
        `reduced_retainage_pct`, the percent withheld once the completion milestone
        is reached, defaults to 5.00; `retainage_milestone_pct`, the
        inspection-verified percent complete at or above which retainage reduces,
        defaults to 50.00; and `stored_materials_max_pct`, the maximum advance
        against a stored-materials line's invoice value, defaults to 75.00."

        Design: Corner/entities/loan_creation_seeds_initial_deposit
        """
        borrower = create_borrower()
        resp = api.create_loan(
            create_loan_payload(borrower["id"], commitment_amount_cents=100_000_000,
                                interest_reserve_initial_cents=200_000),
            ADMIN,
        )
        loan = validate_success(resp, 201)
        assert_loan(loan)
        assert loan["status"] == "OPEN", "A new loan is born OPEN"
        assert loan["version"] == 1
        assert loan["day_count_convention"] == "ACTUAL_360", "default convention"
        assert loan["retainage_pct"] == 10.00
        assert loan["reduced_retainage_pct"] == 5.00
        assert loan["retainage_milestone_pct"] == 50.00
        assert loan["stored_materials_max_pct"] == 75.00
        assert loan["interest_reserve_balance_cents"] == 200_000

        entries, meta = validate_paginated(
            api.list_interest_ledger(loan["id"], SERVICER))
        assert meta["total_count"] == 1, "origination writes exactly one entry"
        entry = entries[0]
        assert_interest_reserve_entry(entry)
        assert entry["entry_index"] == 1
        assert entry["entry_type"] == "INITIAL_DEPOSIT"
        assert entry["amount_cents"] == 200_000
        assert entry["reserve_balance_after_cents"] == 200_000

    def test_loan_get_not_found_returns_404(self, api):
        """PRD §2.9: "Every identifier appearing in a URL path or a request body —
        including `loan_id`, `draw_id`, `budget_line_id`, `from_budget_line_id`,
        `to_budget_line_id`, and `borrower_id` — must resolve to an existing
        resource; an unresolvable reference is rejected with `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/loan_get_not_found_returns_404
        """
        resp = api.get_loan(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_budget_line_defaults_applied(self, api):
        """PRD §3.2: "an optional `is_contingency` flag that defaults to false."
        PRD §3.2: "A budget line is born `ACTIVE`, with `revised_amount_cents`
        initialized to its `original_amount_cents` and `disbursed_cents`,
        `retained_cents`, and `approved_unfunded_cents` all starting at 0. Creating
        a line also refreshes the loan's `total_original_budget_cents`, and that
        recomputation increments the loan's `version`."

        Design: Corner/entities/budget_line_defaults_applied
        """
        borrower = create_borrower()
        loan = create_loan(borrower["id"], commitment_amount_cents=100_000_000)
        resp = api.create_budget_line(
            {
                "loan_id": loan["id"],
                "cost_code": "SITE",
                "description": "Site work",
                "original_amount_cents": 40_000_000,
            },
            ADMIN,
        )
        line = validate_success(resp, 201)
        assert_budget_line(line)
        assert line["is_contingency"] is False, "is_contingency defaults to false"
        assert line["status"] == "ACTIVE", "A budget line is born ACTIVE"
        assert line["revised_amount_cents"] == 40_000_000
        assert line["disbursed_cents"] == 0
        assert line["retained_cents"] == 0
        assert line["approved_unfunded_cents"] == 0

        loan_after = get_loan(loan["id"])
        assert loan_after["total_original_budget_cents"] == 40_000_000

    def test_interest_ledger_immutability(self, api):
        """PRD §2.4: "Interest reserve ledger entries are an append-only audit
        trail: once written they never change, so an entry carries only `id` and
        `created_at`; both `updated_at` and `version` are absent from it."
        PRD §3.8: "Each entry bears a per-loan monotone `entry_index` starting at
        1 — the `INITIAL_DEPOSIT` written at origination is index 1."

        Design: Corner/entities/interest_ledger_immutability
        """
        borrower = create_borrower()
        loan = create_loan(borrower["id"], commitment_amount_cents=100_000_000,
                           reserve_cents=200_000)
        entries, meta = validate_paginated(
            api.list_interest_ledger(loan["id"], SERVICER))
        assert meta["total_count"] == 1
        entry = entries[0]
        assert is_valid_uuid(entry["id"]), "entry carries id"
        assert is_iso8601_timestamp(entry["created_at"]), "entry carries created_at"
        assert "version" not in entry, "version is absent from an append-only entry"
        assert "updated_at" not in entry, "updated_at is absent from an append-only entry"
        assert entry["entry_index"] == 1, "entry_index is 1-based from origination"


class TestResponseEnvelope:
    def test_success_envelope_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`." and "The `response_type` is either
        "object" for a single resource or "array" for a list of resources."
        PRD §2.3: "List endpoints accept two query parameters: `limit` and `offset`.
        `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset`
        defaults to 0."

        Design: Corner/endpoints/success_envelope_shape
        """
        borrower = create_borrower()
        loan = create_loan(borrower["id"], commitment_amount_cents=100_000_000,
                           reserve_cents=200_000)

        obj_resp = api.get_loan(loan["id"], ADMIN)
        obj_data = validate_success(obj_resp, 200)
        obj_body = obj_resp.json()
        assert obj_body["response_type"] == "object"
        assert obj_body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(obj_body["meta"]["api_request_timestamp"])
        assert obj_data["id"] == loan["id"]

        list_resp = api.list_loans(ADMIN)
        _rows, meta = validate_paginated(list_resp)
        list_body = list_resp.json()
        assert list_body["response_type"] == "array"
        assert meta["limit"] == 10, "limit defaults to 10"
        assert meta["offset"] == 0, "offset defaults to 0"
        assert meta["total_count"] == 1
        assert meta["has_more"] is False


class TestAuthContext:
    def test_loan_create_missing_auth_headers(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role outside
        the declared role set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400)."

        Design: Corner/validations/loan_create_missing_auth_headers
        """
        payload = create_loan_payload(NON_EXISTENT_UUID,
                                      commitment_amount_cents=1000,
                                      interest_reserve_initial_cents=0)
        resp = api.create_loan(payload, {})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)

        _rows, meta = validate_paginated(api.list_loans(ADMIN))
        assert meta["total_count"] == 0, "No loan may be persisted by the rejected create"


class TestImmediateConsistency:
    def test_immediate_visibility_after_write(self, api):
        """PRD §1: "the server recomputes them from child events as they land, with
        immediate consistency, so that every read reflects the full history of the
        loan."
        PRD §3.1: "The `interest_reserve_balance_cents` is initialized to
        `interest_reserve_initial_cents`".

        Design: Corner/consistency_model/immediate_visibility_after_write
        """
        borrower = create_borrower()
        created = validate_success(api.create_loan(
            create_loan_payload(borrower["id"], commitment_amount_cents=100_000_000,
                                interest_reserve_initial_cents=200_000),
            ADMIN,
        ), 201)

        fetched = validate_success(api.get_loan(created["id"], OFFICER), 200)
        assert_loan(fetched)
        assert fetched["interest_reserve_balance_cents"] == 200_000
        assert fetched["status"] == "OPEN"
        assert fetched["version"] == 1
