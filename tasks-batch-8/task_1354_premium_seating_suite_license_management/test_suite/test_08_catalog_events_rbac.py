"""Catalog resources (venues/suites/seasons/events/accounts), pagination, RBAC gates."""
from test_helpers import (
    ADMIN, ESM, FIN, REP,
    NON_EXISTENT_UUID, ApiClient, ApiErrorId, EVENT_E1,
    anonymous_headers, complete_event, make_account, make_account_holder_headers,
    make_active_account, make_draft_agreement, make_event, make_executed_agreement,
    make_issued_invoice, make_season, make_suite, make_venue, set_clock, submit_agreement,
    validate_error, validate_paginated, validate_success,
)

GOLD_SUITE = dict(suite_code="G-101", tier="GOLD", capacity_seats=20,
                  base_annual_fee_cents=12000000, f_b_minimum_cents=4000000)


class TestCatalogDefaultsAndConstraints:
    def test_venue_create_applies_cutoff_default(self, api: ApiClient):
        """PRD §3.1: "A `StadiumAdmin` creates one with a display `name` and a street
        `address`, plus an optional `default_catering_cutoff_hours` that defaults to
        72 hours".
        Design: Corner/entities/venue_create_applies_cutoff_default
        """
        venue = validate_success(api.create_venue(
            {"name": "Metro Stadium", "address": "1 Arena Way"}, ADMIN), expected_status=201)
        assert venue["default_catering_cutoff_hours"] == 72
        # PRD §2.5 common system fields are server-stamped on every resource.
        assert isinstance(venue["id"], str) and venue["id"]
        assert isinstance(venue["created_at"], str) and venue["created_at"]
        assert isinstance(venue["updated_at"], str) and venue["updated_at"]
        assert isinstance(venue["version"], int) and venue["version"] >= 1

    def test_suite_create_missing_required_returns_invalid_request(self, api: ApiClient):
        """PRD §2.8: "Required fields must be present ... Violations yield
        `ERR_INVALID_REQUEST` (HTTP 400)"; PRD §3.1 names `tier` among the suite's
        creation inputs ("a `tier` of `FOUNDERS`, `PLATINUM`, `GOLD`, or `SILVER`").
        Design: Corner/entities/suite_create_missing_required_returns_invalid_request
        """
        venue = make_venue()
        resp = api.create_suite(
            {"venue_id": venue["id"], "suite_code": "G-101", "capacity_seats": 20,
             "base_annual_fee_cents": 12000000, "f_b_minimum_cents": 4000000}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows, meta = validate_paginated(api.list_suites(ADMIN, params={"venue_id": venue["id"]}))
        assert meta["total_count"] == 0, "no Suite row may be created by a rejected call"

    def test_suite_create_invalid_enum_rejected(self, api: ApiClient):
        """PRD §2.8: "enum values must be in their declared domains ... Violations
        yield `ERR_INVALID_REQUEST` (HTTP 400)"; the tier domain is "`FOUNDERS`,
        `PLATINUM`, `GOLD`, or `SILVER`" (§3.1).
        Design: Corner/entities/suite_create_invalid_enum_rejected
        """
        venue = make_venue()
        resp = api.create_suite(
            {"venue_id": venue["id"], "suite_code": "D-100", "tier": "DIAMOND",
             "capacity_seats": 20, "base_annual_fee_cents": 12000000,
             "f_b_minimum_cents": 4000000}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_suite_code_unique_per_venue(self, api: ApiClient):
        """PRD §3.1: "a human-readable `suite_code` such as "S-201" that must be unique
        within its venue"; §2.8: "Violations yield `ERR_INVALID_REQUEST` (HTTP 400), as
        do a duplicate `tax_id` or duplicate `suite_code` within a venue."
        Design: Corner/entities/suite_code_unique_per_venue
        """
        v1 = make_venue(name="Metro Stadium", address="1 Arena Way")
        v2 = make_venue(name="North Dome", address="9 Field Rd")
        make_suite(v1["id"], suite_code="G-101")
        dup = api.create_suite(
            {"venue_id": v1["id"], "suite_code": "G-101", "tier": "GOLD",
             "capacity_seats": 18, "base_annual_fee_cents": 11000000,
             "f_b_minimum_cents": 3800000}, ADMIN)
        validate_error(dup, ApiErrorId.ERR_INVALID_REQUEST)
        ok = api.create_suite(
            {"venue_id": v2["id"], "suite_code": "G-101", "tier": "GOLD",
             "capacity_seats": 18, "base_annual_fee_cents": 11000000,
             "f_b_minimum_cents": 3800000}, ADMIN)
        validate_success(ok, expected_status=201)

    def test_account_tax_id_globally_unique(self, api: ApiClient):
        """PRD §3.2: "a `tax_id` that must be unique across all accounts ... A
        duplicate `tax_id` is rejected with `ERR_INVALID_REQUEST`."
        Design: Corner/entities/account_tax_id_globally_unique
        """
        make_account(legal_name="Acme Corp", account_type="CORPORATE", tax_id="T-100",
                     billing_email="ap@acme.example")
        resp = api.create_account(
            {"legal_name": "Acme Clone", "account_type": "INDIVIDUAL", "tax_id": "T-100",
             "billing_email": "other@acme.example"}, REP)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_account_created_with_zeroed_computed_ledger(self, api: ApiClient):
        """PRD §3.2: "New accounts begin as `PROSPECT`"; "`credit_standing` is `HOLD`
        when any non-void invoice of the account is 30 or more days past due ... and
        otherwise `GOOD`"; "`balance_due_cents` is the sum of `amount_due_cents` across
        the account's invoices currently in `ISSUED` or `PARTIALLY_PAID`";
        "`lifetime_spend_cents` is the sum of `amount_cents` across the account's
        payments that have ever reached `CLEARED`".
        Design: Corner/entities/account_created_with_zeroed_computed_ledger
        """
        account = validate_success(api.create_account(
            {"legal_name": "Acme Corp", "account_type": "CORPORATE", "tax_id": "T-100",
             "billing_email": "ap@acme.example"}, REP), expected_status=201)
        assert account["status"] == "PROSPECT"
        assert account["credit_standing"] == "GOOD"
        assert account["balance_due_cents"] == 0
        assert account["lifetime_spend_cents"] == 0


class TestNotFound:
    def test_suite_get_nonexistent_returns_not_found(self, api: ApiClient):
        """PRD §2.8: "Identifiers embedded in the URL are resolved left to right; the
        first identifier that does not resolve to an existing resource yields
        `ERR_NOT_FOUND` (HTTP 404)".
        Design: Corner/entities/suite_get_nonexistent_returns_not_found
        """
        resp = api.get_suite(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_action_on_ghost_agreement_returns_not_found(self, api: ApiClient):
        """PRD §2.8: "Identifiers embedded in the URL are resolved left to right; the
        first identifier that does not resolve to an existing resource yields
        `ERR_NOT_FOUND` (HTTP 404), and no later identifier is examined."
        Design: Corner/validations/action_on_ghost_agreement_returns_not_found_before_state
        """
        resp = api.submit_agreement(NON_EXISTENT_UUID, REP)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_agreement_create_with_ghost_suite_returns_not_found(self, api: ApiClient):
        """PRD §2.8: "Foreign keys supplied in the request body — such as `suite_id`,
        `account_id`, `event_id`, `season_id`, `agreement_id`, `rental_id`, or the
        invoice ids inside payment `allocations` — must resolve to existing resources,
        else `ERR_NOT_FOUND`."
        Design: Corner/validations/agreement_create_with_ghost_suite_returns_not_found
        """
        venue = make_venue()
        season = make_season(venue["id"])
        account = make_account()
        resp = api.create_agreement(
            {"suite_id": NON_EXISTENT_UUID, "account_id": account["id"],
             "start_season_id": season["id"], "term_seasons": 1,
             "base_annual_fee_cents": 12000000, "escalator_bp": 300,
             "f_b_minimum_cents": 4000000}, REP)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestEventOverlap:
    def _setup(self, api: ApiClient):
        set_clock("2026-08-01T00:00:00Z")
        venue = make_venue()
        season = make_season(venue["id"])
        make_event(season["id"], **EVENT_E1)  # [2026-09-10T17:00Z, 21:00Z)
        return season

    def test_adjacent_event_touching_is_allowed(self, api: ApiClient):
        """PRD §3.1: "creating an event whose interval intersects another `SCHEDULED`
        event at the same venue is rejected with `ERR_EVENT_OVERLAP`, while two events
        that merely touch — one ending exactly when the other begins — are allowed."
        Design: Difficulty/resource_temporal_overlap/event_overlap_half_open_adjacency_allowed_touching_rejected
        """
        season = self._setup(api)
        ok = api.create_event(
            {"season_id": season["id"], "name": "Late Concert", "event_type": "CONCERT",
             "starts_at": "2026-09-10T21:00:00Z", "duration_hours": 3,
             "rental_base_price_cents": 900000}, ADMIN)
        validate_success(ok, expected_status=201)

    def test_one_second_intersection_rejected(self, api: ApiClient):
        """PRD §3.1: "An event occupies the half-open interval from its `starts_at` up
        to but not including `starts_at` plus `duration_hours`; creating an event whose
        interval intersects another `SCHEDULED` event at the same venue is rejected
        with `ERR_EVENT_OVERLAP`".
        Design: Difficulty/resource_temporal_overlap/event_overlap_half_open_adjacency_allowed_touching_rejected
        """
        season = self._setup(api)
        resp = api.create_event(
            {"season_id": season["id"], "name": "Overlap Attempt", "event_type": "CONCERT",
             "starts_at": "2026-09-10T20:59:59Z", "duration_hours": 3,
             "rental_base_price_cents": 900000}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_EVENT_OVERLAP)

    def test_event_complete_before_end_rejected(self, api: ApiClient):
        """PRD §3.1: "Marking an event `COMPLETED` requires the clock to have reached
        the end of the occupancy interval — `starts_at` plus `duration_hours` — and
        earlier attempts are rejected with `ERR_INVALID_STATE_TRANSITION`."
        Design: Corner/state_machines/event_complete_before_end_rejected
        """
        season = self._setup(api)
        rows = validate_paginated(api.list_events(ADMIN, params={"season_id": season["id"]}))[0]
        event = rows[0]
        set_clock("2026-09-10T20:00:00Z")  # one hour before the 21:00 interval end
        resp = api.set_event_status(event["id"], {"target_status": "COMPLETED"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert validate_success(api.get_event(event["id"], ADMIN))["status"] == "SCHEDULED"


class TestPaginationAndFilters:
    def test_list_pagination_defaults_and_offset(self, api: ApiClient):
        """PRD §2.3: "`limit` caps the number of items returned; it defaults to 10,
        with a minimum of 1 and a maximum of 100. `offset` specifies how many items to
        skip and defaults to 0. The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."
        Design: Corner/endpoints/list_pagination_defaults_and_offset
        """
        venue = make_venue()
        for i in range(1, 13):
            make_suite(venue["id"], suite_code=f"S-{i:03d}", tier="SILVER",
                       capacity_seats=10, base_annual_fee_cents=6000000,
                       f_b_minimum_cents=2000000)
        page1, meta1 = validate_paginated(api.list_suites(ADMIN, params={"venue_id": venue["id"]}))
        assert len(page1) == 10 and meta1["limit"] == 10 and meta1["offset"] == 0
        assert meta1["total_count"] == 12 and meta1["has_more"] is True
        page2, meta2 = validate_paginated(api.list_suites(
            ADMIN, params={"venue_id": venue["id"], "offset": 10}))
        assert len(page2) == 2 and meta2["total_count"] == 12 and meta2["has_more"] is False

    def test_list_filter_by_status_returns_subset(self, api: ApiClient):
        """PRD §3.3: "Agreements can be listed filtered by `suite_id`, `account_id`,
        `start_season_id`, or `status`, with an `AccountHolder` seeing only its own."
        Design: Corner/endpoints/list_filter_by_status_returns_subset
        """
        set_clock("2026-08-01T00:00:00Z")
        venue = make_venue()
        su1 = make_suite(venue["id"], suite_code="G-101")
        su2 = make_suite(venue["id"], suite_code="G-102")
        season = make_season(venue["id"])
        ac1 = make_active_account()
        ac2 = make_active_account()
        aga = make_executed_agreement(su1, ac1, season)
        agb = make_draft_agreement(su2["id"], ac2["id"], season["id"],
                                   base_annual_fee_cents=13000000)
        rows, meta = validate_paginated(api.list_agreements(REP, params={"status": "ACTIVE"}))
        assert meta["total_count"] == 1
        assert [r["id"] for r in rows] == [aga["id"]], "the DRAFT agreement is excluded"


class TestRbac:
    def test_missing_role_header_returns_unauthenticated(self, api: ApiClient):
        """PRD §2.1: "A request missing either header, carrying a malformed value, or
        naming a role outside the five declared roles is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        Design: Corner/rbac/missing_role_header_returns_unauthenticated
        """
        resp = api.get_suite(NON_EXISTENT_UUID, anonymous_headers())
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_holder_cannot_create_venue_forbidden(self, api: ApiClient):
        """PRD §2.1: "a caller whose role is valid but not listed for that endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)"; §4 lists
        POST /api/venues as StadiumAdmin-only.
        Design: Corner/rbac/holder_cannot_create_venue_forbidden
        """
        account = make_account()
        resp = api.create_venue({"name": "Sneaky Stadium", "address": "2 Nowhere"},
                                make_account_holder_headers(account["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_holder_reading_others_agreement_returns_scope_violation(self, api: ApiClient):
        """PRD §2.1: "ownership checks on any resource that references an Account
        compare the resource's owning-account field — `agreement.account_id`, ... — to
        `X-User-ID`, and a mismatch is rejected with `ERR_ACCOUNT_SCOPE_VIOLATION`
        (HTTP 403). Staff roles are exempt from this scope check."
        Design: Corner/rbac/holder_reading_others_agreement_returns_scope_violation
        """
        set_clock("2026-08-01T00:00:00Z")
        venue = make_venue()
        suite = make_suite(venue["id"], **GOLD_SUITE)
        season = make_season(venue["id"])
        ac1 = make_active_account()
        ac2 = make_active_account()
        ag = make_executed_agreement(suite, ac1, season)
        resp = api.get_agreement(ag["id"], make_account_holder_headers(ac2["id"]))
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SCOPE_VIOLATION)
        own = api.get_agreement(ag["id"], make_account_holder_headers(ac1["id"]))
        validate_success(own)

    def test_event_services_cannot_create_agreement(self, api: ApiClient):
        """PRD §2.1: "a caller whose role is valid but not listed for that endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)"; §4 lists POST
        /api/agreements as PremiumSalesRep, StadiumAdmin.
        Design: Corner/rbac/event_services_cannot_create_agreement
        """
        venue = make_venue()
        suite = make_suite(venue["id"], **GOLD_SUITE)
        season = make_season(venue["id"])
        account = make_account()
        resp = api.create_agreement(
            {"suite_id": suite["id"], "account_id": account["id"],
             "start_season_id": season["id"], "term_seasons": 1,
             "base_annual_fee_cents": 12000000, "escalator_bp": 300,
             "f_b_minimum_cents": 4000000}, ESM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_finance_cannot_publish_season(self, api: ApiClient):
        """PRD §2.1: "a caller whose role is valid but not listed for that endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)"; §4 lists POST
        /api/seasons/{id}/publish as StadiumAdmin-only.
        Design: Corner/rbac/finance_cannot_publish_season
        """
        venue = make_venue()
        season = make_season(venue["id"], publish=False)
        resp = api.publish_season(season["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert validate_success(api.get_season(season["id"], ADMIN))["status"] == "DRAFT"

    def test_sales_rep_cannot_settle_season(self, api: ApiClient):
        """PRD §2.1: "a caller whose role is valid but not listed for that endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)"; §4 lists POST
        /api/seasons/{id}/settle as FinanceController, StadiumAdmin.
        Design: Corner/rbac/sales_rep_cannot_settle_season
        """
        set_clock("2026-08-01T00:00:00Z")
        venue = make_venue()
        season = make_season(venue["id"])
        event = make_event(season["id"], **EVENT_E1)
        complete_event(event["id"], "2027-02-16T00:00:00Z")
        resp = api.settle_season(season["id"], REP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert validate_success(api.get_season(season["id"], ADMIN))["status"] == "PUBLISHED"

    def test_holder_can_pay_own_invoice(self, api: ApiClient):
        """PRD §3.4: "A **Payment** is created by an `AccountHolder` paying its own
        account or by `FinanceController` or `StadiumAdmin` staff"; "Payments begin
        `INITIATED`".
        Design: Corner/rbac/holder_can_pay_own_invoice
        """
        account = make_active_account()
        inv = make_issued_invoice(account["id"])
        payment = validate_success(api.create_payment(
            {"account_id": account["id"], "amount_cents": 5000, "method": "CARD",
             "allocations": [{"invoice_id": inv["id"], "amount_cents": 5000}]},
            make_account_holder_headers(account["id"])), expected_status=201)
        assert payment["status"] == "INITIATED"

    def test_holder_cannot_pay_for_other_account(self, api: ApiClient):
        """PRD §2.1: "ownership checks on any resource that references an Account
        compare the resource's owning-account field — ... `payment.account_id`, ... —
        to `X-User-ID`, and a mismatch is rejected with `ERR_ACCOUNT_SCOPE_VIOLATION`
        (HTTP 403)."
        Design: Corner/rbac/holder_cannot_pay_for_other_account
        """
        ac_a = make_active_account()
        ac_b = make_active_account()
        inv_b = make_issued_invoice(ac_b["id"])
        resp = api.create_payment(
            {"account_id": ac_b["id"], "amount_cents": 5000, "method": "CARD",
             "allocations": [{"invoice_id": inv_b["id"], "amount_cents": 5000}]},
            make_account_holder_headers(ac_a["id"]))
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SCOPE_VIOLATION)
