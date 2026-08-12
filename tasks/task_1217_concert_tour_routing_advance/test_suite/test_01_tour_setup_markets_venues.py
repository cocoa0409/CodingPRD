"""Tour setup, markets, venues: creation contracts, listing, not-found,
referential integrity, and auth/RBAC gates (PRD §2.1, §2.3, §2.9, §2.10, §3.1).
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_tour_payload, create_market_payload, create_venue_payload,
    create_show_payload, create_staged_tour, create_tour, create_market,
    create_venue, set_clock, assert_tour, assert_market,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
)

TM = TEST_USERS["tour_manager_headers"]
PROMOTER = TEST_USERS["promoter_headers"]


class TestTourCreation:
    @pytest.mark.parametrize("missing_field", [
        "tour_name", "artist_name", "window_start_date", "window_end_date",
    ])
    def test_missing_required_field_rejected(self, api, missing_field):
        """PRD §2.10: "any request with a malformed body, a missing required
        field, or a wrong-typed value is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400)." PRD §3.1: a tour is opened "by supplying its `tour_name`,
        the headlining `artist_name`, and the routing window bounded by
        `window_start_date` and `window_end_date`."

        Design: Corner/entities/tour_creation_required_fields
        """
        payload = create_tour_payload()
        del payload[missing_field]
        res = api.create_tour(payload, TM)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_tour_initial_state_and_rollups(self, api):
        """PRD §3.1: "A freshly created tour begins with `status` of `PLANNING`
        and `posture` of `OPEN`, and all four financial rollups —
        `projected_gross_cents`, `projected_cost_cents`, `settled_gross_cents`,
        and `settled_cost_cents` — start at zero."

        Design: Corner/entities/tour_creation_required_fields
        """
        set_clock("2026-05-01T00:00:00Z")
        tour = validate_success(
            api.create_tour(create_tour_payload(), TM), 201)
        assert_tour(tour)
        assert tour["status"] == "PLANNING"
        assert tour["posture"] == "OPEN"
        assert tour["projected_gross_cents"] == 0
        assert tour["projected_cost_cents"] == 0
        assert tour["settled_gross_cents"] == 0
        assert tour["settled_cost_cents"] == 0
        assert isinstance(tour["version"], int)

    def test_window_end_not_after_start_rejected(self, api):
        """PRD §3.1: "The window end must fall strictly after the window start;
        a tour whose dates do not satisfy this is rejected as malformed."

        Design: Corner/entities/tour_creation_required_fields
        """
        payload = create_tour_payload(window_start_date="2026-08-01",
                                      window_end_date="2026-07-01")
        res = api.create_tour(payload, TM)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestTourInitialState:
    def test_fresh_tour_is_planning_open_zeroed(self, api):
        """PRD §3.1: "A freshly created tour begins with `status` of `PLANNING`
        and `posture` of `OPEN`, and all four financial rollups —
        `projected_gross_cents`, `projected_cost_cents`, `settled_gross_cents`,
        and `settled_cost_cents` — start at zero."

        Design: Corner/state_machines/initial_state_tour_is_planning
        """
        set_clock("2026-05-01T00:00:00Z")
        tour = validate_success(api.create_tour(create_tour_payload(), TM), 201)
        assert tour["status"] == "PLANNING"
        assert tour["posture"] == "OPEN"
        assert tour["projected_gross_cents"] == 0
        assert tour["settled_gross_cents"] == 0


class TestStartRouting:
    def test_start_routing_twice_rejected(self, api):
        """PRD §3.1: "A staged tour leaves `PLANNING` for `ROUTING` when the
        manager starts routing — but only if the tour is still in `PLANNING`
        (otherwise `ERR_TOUR_NOT_PLANNING`) and at least one market and one
        venue exist under it (otherwise `ERR_TOUR_UNSTAGED`)."

        Design: Corner/errors/err_tour_not_planning
        """
        staged = create_staged_tour(start_clock="2026-05-01T00:00:00Z")
        tid = staged["tour"]["id"]
        assert staged["tour"]["status"] == "ROUTING"
        res = api.start_routing(tid, TM)
        validate_error(res, ApiErrorId.ERR_TOUR_NOT_PLANNING.value)


class TestMarkets:
    def test_market_listing_pagination_defaults(self, api):
        """PRD §2.3: "`limit` caps the number of items returned; it defaults to
        10, with a minimum of 1 and a maximum of 100. `offset` skips that many
        items from the start of the result set and defaults to 0." And: "The
        `meta` object of a list response carries four pagination fields:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/market_listing_pagination_defaults
        """
        tour = create_tour(start_clock="2026-05-01T00:00:00Z")
        for i, code in enumerate(("A", "B", "C"), start=1):
            market = create_market(tour["id"], market_code=code, metro_name=code,
                                   territory_rank=i)
            assert_market(market)

        data, meta = validate_paginated(api.list_markets(tour["id"], TM))
        assert len(data) == 3, f"expected 3 markets, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is False
        assert {m["market_code"] for m in data} == {"A", "B", "C"}
        assert all(m["id"] for m in data)

    def test_duplicate_territory_rank_rejected(self, api):
        """PRD §3.1: "the rank must be unique within the tour, and a duplicate
        is rejected with `ERR_DUPLICATE_KEY`."

        Design: Corner/errors/err_duplicate_key_territory_rank
        """
        tour = create_tour(start_clock="2026-05-01T00:00:00Z")
        create_market(tour["id"], market_code="A", territory_rank=1)
        res = api.create_market(
            tour["id"], create_market_payload(market_code="B", metro_name="B",
                                              territory_rank=1), TM)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_KEY.value)


class TestVenueRetrieval:
    def test_get_nonexistent_venue_returns_not_found(self, api):
        """PRD §2.9: "the first identifier that does not resolve to an existing
        resource produces a 404 rejection with `ERR_NOT_FOUND`, and no later
        segment is examined."

        Design: Corner/entities/venue_retrieval_not_found
        """
        tour = create_tour(start_clock="2026-05-01T00:00:00Z")
        res = api.get_venue(tour["id"], NON_EXISTENT_UUID, TM)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


class TestReferentialIntegrity:
    def test_show_with_venue_from_other_tour_rejected(self, api):
        """PRD §2.10: "Fourth, referential integrity of any foreign keys
        supplied in the request body — each such reference must resolve within
        the same tour (`ERR_REFERENTIAL_INTEGRITY`, HTTP 422)."

        Design: Corner/validations/referential_integrity_venue_from_other_tour
        """
        tour_a = create_tour(start_clock="2026-05-01T00:00:00Z",
                             tour_name="Tour A", artist_name="A")
        market_a = create_market(tour_a["id"], market_code="X", territory_rank=1)
        venue_a = create_venue(tour_a["id"], market_a["id"], venue_name="V")

        tour_b = create_tour(start_clock=None, tour_name="Tour B", artist_name="B")
        market_b = create_market(tour_b["id"], market_code="Y", territory_rank=1)
        create_venue(tour_b["id"], market_b["id"], venue_name="VB")
        validate_success(api.start_routing(tour_b["id"], TM), 200)

        res = api.create_show(
            tour_b["id"],
            create_show_payload(market_b["id"], venue_a["id"]), TM)
        validate_error(res, ApiErrorId.ERR_REFERENTIAL_INTEGRITY.value)


class TestAuthAndRbac:
    def test_missing_user_context_header_rejected(self, api):
        """PRD §2.1: "A request in which either header is missing or malformed
        is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_user_context_header
        """
        res = api.create_tour(create_tour_payload(), headers={})
        validate_error(res,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

        res = api.create_tour(create_tour_payload(),
                              headers={"X-User-ID": "u1", "Content-Type": "application/json"})
        validate_error(res,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_promoter_cannot_create_tour(self, api):
        """PRD §2.1: a TourManager owns "creating the tour", and "An attempt to
        perform an operation outside the caller's role is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/validations/rbac_promoter_cannot_create_tour
        """
        set_clock("2026-05-01T00:00:00Z")
        res = api.create_tour(create_tour_payload(), PROMOTER)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
