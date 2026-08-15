"""Platform contracts: auth, idempotency, envelopes, pagination, RBAC (PRD §2, §4)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_program, create_market, create_active_vendor,
    create_program_payload, create_shopper_payload,
    setup_booth_scenario, issue_tokens,
    make_vendor_headers, make_shopper_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
BOOTH = TEST_USERS["booth_operator_headers"]
MANAGER = TEST_USERS["market_manager_headers"]

_FORBIDDEN_QUOTE = (
    "An attempt to perform an operation outside the caller's designated role "
    "is rejected with `ERR_FORBIDDEN`."
)
_AUTHZ_ORDER_QUOTE = (
    "Authentication runs first, then authorization, including payload-scoped "
    "role rules such as the restriction that sending `override_variance` set "
    "to true on a day reconciliation is `ProgramAdmin`-only (a `MarketManager` "
    "sending it is refused with `ERR_FORBIDDEN`). Idempotency comes third for "
    "write requests, then identifier resolution (path before body, per §2.9)."
)


class TestAuthentication:
    def test_missing_role_header_unauthenticated(self, api):
        """PRD §2.1: "A request that arrives without `X-User-Role`, or carrying
        a role the system does not declare, is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/c_val_missing_auth_header_returns_unauthenticated
        """
        program = create_program(pool_cents=50000)
        resp = api.get_program(program["id"], headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestIdempotency:
    def test_missing_idempotency_key_rejected(self, api):
        """PRD §2.7: "Every write endpoint requires an `Idempotency-Key`
        header; a POST arriving without one is rejected with
        `ERR_MISSING_IDEMPOTENCY_KEY`."

        Design: Corner/validations/c_val_post_missing_required_idempotency_key_rejected
        """
        resp = api.post_raw("/programs", create_program_payload(
            name="P", season_start="2026-08-01T00:00:00Z",
            season_end="2026-09-01T00:00:00Z", match_pool_budget_cents=50000), ADMIN)
        validate_error(resp, ApiErrorId.ERR_MISSING_IDEMPOTENCY_KEY)

    def test_idempotent_replay_same_body_returns_original(self, api):
        """PRD §2.7: "Replaying a key together with an identical request body
        returns the original response and produces no new side effects."

        Design: Corner/validations/c_val_idempotent_replay_same_body_returns_original
        """
        payload = create_program_payload(name="P", season_start="2026-08-01T00:00:00Z",
                                         season_end="2026-09-01T00:00:00Z",
                                         match_pool_budget_cents=50000)
        first = validate_success(
            api.create_program(payload, ADMIN, idempotency_key="K-1"), expected_status=201)
        second = validate_success(
            api.create_program(dict(payload), ADMIN, idempotency_key="K-1"), expected_status=201)
        assert second["id"] == first["id"], "replay returns the original resource, not a new row"
        assert second["created_at"] == first["created_at"]
        assert second["version"] == 1, "no new side effects on the stored row"

    def test_idempotency_key_reuse_different_body_conflicts(self, api):
        """PRD §2.7: "Reusing a key with a different request body is a
        conflict, rejected with `ERR_IDEMPOTENCY_CONFLICT`."

        Design: Corner/validations/c_val_idempotency_key_reuse_different_body_conflicts
        """
        validate_success(api.create_program(
            create_program_payload(name="P", season_start="2026-08-01T00:00:00Z",
                                   season_end="2026-09-01T00:00:00Z",
                                   match_pool_budget_cents=50000),
            ADMIN, idempotency_key="K-2"), expected_status=201)
        conflict = api.create_program(
            create_program_payload(name="P-CHANGED", season_start="2026-08-01T00:00:00Z",
                                   season_end="2026-09-01T00:00:00Z",
                                   match_pool_budget_cents=50000),
            ADMIN, idempotency_key="K-2")
        validate_error(conflict, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT)


class TestEnvelopeContract:
    def test_envelope_shapes_success_and_error(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body"
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format:"
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/c_ep_envelope_shapes_success_and_error
        """
        program = create_program(pool_cents=50000, name="P")

        ok = api.get_program(program["id"], ADMIN)
        assert ok.status_code == 200
        body = ok.json()
        assert body["response_type"] == "object"
        assert body["data"]["name"] == "P"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")

        err = api.get_program(NON_EXISTENT_UUID, ADMIN)
        assert err.status_code == 404
        err_body = err.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"]


class TestTokenListPagination:
    def test_tokens_list_pagination_pages(self, api):
        """PRD §2.3: "The token list is the standing exception: it is ordered
        by `serial_number` ascending, which keeps indexed reads of the scrip
        inventory deterministic."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/c_ep_tokens_list_pagination_pages
        """
        sc = setup_booth_scenario(with_vendor=False)
        issuance, _tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 300)

        page1, meta1 = validate_paginated(
            api.list_tokens(BOOTH, params={"issuance_id": issuance["id"], "limit": 4, "offset": 0}))
        assert len(page1) == 4
        assert meta1["has_more"] is True
        assert meta1["total_count"] == 6
        assert [t["serial_number"] for t in page1] == [200001, 200002, 200003, 300001]

        page2, meta2 = validate_paginated(
            api.list_tokens(BOOTH, params={"issuance_id": issuance["id"], "limit": 4, "offset": 4}))
        assert [t["serial_number"] for t in page2] == [300002, 300003]
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 6


class TestAuthorizationPrecedence:
    def test_forbidden_role_beats_not_found_on_approve(self, api):
        """PRD §2.10: "Authentication runs first, then authorization, including
        payload-scoped role rules such as the restriction that sending
        `override_variance` set to true on a day reconciliation is
        `ProgramAdmin`-only (a `MarketManager` sending it is refused with
        `ERR_FORBIDDEN`). Idempotency comes third for write requests, then
        identifier resolution (path before body, per §2.9)."
        PRD §2.1: "An attempt to perform an operation outside the caller's
        designated role is rejected with `ERR_FORBIDDEN`."

        Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_not_found_on_approve
        """
        create_program()
        resp = api.approve_vendor(NON_EXISTENT_UUID, BOOTH)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_forbidden_approve_masks_existence(self, api):
        """PRD §2.10: "Authentication runs first, then authorization, including
        payload-scoped role rules such as the restriction that sending
        `override_variance` set to true on a day reconciliation is
        `ProgramAdmin`-only (a `MarketManager` sending it is refused with
        `ERR_FORBIDDEN`). Idempotency comes third for write requests, then
        identifier resolution (path before body, per §2.9)."
        PRD §2.1: "An attempt to perform an operation outside the caller's
        designated role is rejected with `ERR_FORBIDDEN`."

        Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_not_found_on_approve
        """
        program = create_program()
        market = create_market(program["id"])
        vendor = get_success_data(api.create_vendor(
            {"market_id": market["id"], "legal_name": "V", "stall_number": "S1"}, ADMIN))

        missing = api.approve_vendor(NON_EXISTENT_UUID, BOOTH)
        existing = api.approve_vendor(vendor["id"], BOOTH)
        validate_error(missing, ApiErrorId.ERR_FORBIDDEN)
        validate_error(existing, ApiErrorId.ERR_FORBIDDEN)
        assert missing.status_code == existing.status_code == 403, (
            "authorization refuses both before existence is examined — no leak")


class TestRoleSegregation:
    def test_market_manager_cannot_issue_tokens(self, api):
        """PRD §2.1: "`MarketManager` — runs market days (scheduling, opening,
        closing, reconciling) and verifies vendor reimbursement claims. It is
        segregated from approval and payment and from issuance."
        PRD §2.1: "An attempt to perform an operation outside the caller's
        designated role is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/c_rbac_market_manager_cannot_issue_tokens
        """
        sc = setup_booth_scenario(with_vendor=False)
        resp = api.create_issuance(
            {"shopper_id": sc["shopper"]["id"],
             "market_day_id": sc["market_day"]["id"],
             "benefit_charged_cents": 500,
             "expected_shopper_version": sc["shopper"]["version"]},
            MANAGER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_shopper_is_read_only(self, api):
        """PRD §2.1: "`Shopper` — the benefit recipient, with read-only access
        to its own record and issuance history."
        PRD §2.1: "When `X-User-Role` is `Shopper`, `X-User-ID` is the `id` of
        the acting Shopper, granting read access to that shopper's own record."
        PRD §2.1: "An attempt to perform an operation outside the caller's
        designated role is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/c_rbac_shopper_is_read_only
        """
        program = create_program(pool_cents=50000)
        shopper = validate_success(api.create_shopper(
            create_shopper_payload(program_id=program["id"], external_benefit_ref="EBT-1",
                                   benefit_type="SNAP"), BOOTH), expected_status=201)
        self_headers = make_shopper_headers(shopper["id"])

        write = api.create_shopper(
            create_shopper_payload(program_id=program["id"], external_benefit_ref="EBT-2",
                                   benefit_type="WIC"),
            self_headers)
        validate_error(write, ApiErrorId.ERR_FORBIDDEN)

        read = validate_success(api.get_shopper(shopper["id"], self_headers))
        assert read["id"] == shopper["id"], "self-read allowed"

    def test_vendor_reads_own_resources(self, api):
        """PRD §2.1: "When `X-User-Role` is `Vendor`, `X-User-ID` is the `id`
        of the acting Vendor; ownership checks on any resource that references
        a Vendor — a token's `redeemed_vendor_id`, a claim's `vendor_id` —
        compare the resource's foreign-key field to `X-User-ID`, and acting on
        another vendor's resource is rejected with `ERR_FORBIDDEN`."
        PRD §3.5: "The `payable_cents` figure is the vendor's
        approved-but-unpaid balance: the sum of `approved_amount_cents` over
        its claims in `APPROVED` or `PAID` status, minus the sum of
        `paid_amount_cents` over its paid claims."

        Design: Corner/rbac/c_rbac_vendor_reads_own_resources
        """
        program = create_program(pool_cents=50000)
        market = create_market(program["id"])
        vendor = create_active_vendor(market["id"])
        self_headers = make_vendor_headers(vendor["id"])

        own = validate_success(api.get_vendor(vendor["id"], self_headers))
        assert own["status"] == "ACTIVE"
        assert own["payable_cents"] == 0, "no approved or paid claims yet"

        subs, meta = validate_paginated(
            api.list_submissions(self_headers, params={"vendor_id": vendor["id"]}))
        assert subs == []
        assert meta["total_count"] == 0
