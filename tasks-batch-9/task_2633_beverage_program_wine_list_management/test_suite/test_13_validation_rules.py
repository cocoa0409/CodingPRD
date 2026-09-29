"""Validation-rule corners of the beverage-program API.

Every test in this file pins one of the declared validation checks at its exact
boundary: the strict period and event-window orderings, the pagination range,
the conditional pour-size requirement, the two differently scoped uniqueness
keys, the venue-scope check that outranks existence, segregation of duties on a
write-off, the aggregate pour ceiling on a slot close, the strict allocation
deadline, the claim size and uniqueness bounds, the future-receipt bound on a
lot, and the corkage validation ladder.

Each test asserts both sides of its boundary where the rule has two sides, and
asserts that a rejected request persisted nothing.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_BIN_CAPACITY_EXCEEDED,
    ERR_BIN_CODE_TAKEN,
    ERR_BYO_CATEGORY_PROHIBITED,
    ERR_BYO_LIMIT_EXCEEDED,
    ERR_DUPLICATE_CLAIM,
    ERR_INVALID_ENUM_VALUE,
    ERR_INVALID_EVENT_WINDOW,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_PERIOD,
    ERR_NO_REVENUE_IN_PERIOD,
    ERR_OFFER_DEADLINE_PASSED,
    ERR_POUR_SIZE_REQUIRED,
    ERR_POURS_EXCEED_BOTTLE,
    ERR_RECEIVED_AT_IN_FUTURE,
    ERR_REQUEST_EXCEEDS_OFFER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SLOT_NOT_OPEN,
    ERR_VENUE_CODE_TAKEN,
    ERR_VENUE_SCOPE_VIOLATION,
)
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_null_fields,
    depletion_entries_for,
)
from test_helpers.test_users import (
    BEVERAGE_DIRECTOR_HEADERS,
    CONTROLLER_HEADERS,
    second_controller_headers,
    sommelier_headers,
)

RED_TARGETS = dict(SPARKLING=30.0, WHITE=25.0, ROSE=28.0, RED=28.0,
                   DESSERT=32.0, FORTIFIED=35.0)


def _harbor_venue(**overrides):
    """A venue carrying the per-category cost targets these tests price against."""
    overrides.setdefault("cogs_target_pct_by_category", f.cogs_targets(**RED_TARGETS))
    return fx.create_venue(**overrides)


def _report(venue_id, period_start, period_end, headers=None):
    return api_client.get_pour_cost_report(
        venue_id, headers or CONTROLLER_HEADERS,
        params={"period_start": period_start, "period_end": period_end})


class TestPourCostPeriodBounds:
    """The reporting period must be strictly ordered, and that shape check is
    reported ahead of the revenue precondition on the very same window."""

    def test_reversed_reporting_period_is_refused_before_the_revenue_check(self):
        """A backwards window on a venue with no ledger history answers the period error, not the revenue error.

        "The run supplies `period_start` and `period_end`, which must be strictly ordered or the request is refused with `ERR_INVALID_PERIOD`."

        Design: Corner/validations/reversed_and_equal_pour_cost_periods_return_invalid_period
        """
        fx.set_clock("2026-09-05T00:00:00Z")
        venue = _harbor_venue()

        response = _report(venue["id"], "2026-09-04T00:00:00Z", "2026-09-01T00:00:00Z")

        validate_error(response, ERR_INVALID_PERIOD)

    def test_equal_reporting_bounds_are_refused_because_the_ordering_is_strict(self):
        """A zero-length window is as invalid as a reversed one, because the bound is a strict less-than.

        "A reporting period likewise starts strictly before it ends — otherwise `ERR_INVALID_PERIOD` (HTTP 422)."

        Design: Corner/validations/reversed_and_equal_pour_cost_periods_return_invalid_period
        """
        fx.set_clock("2026-09-05T00:00:00Z")
        venue = _harbor_venue()

        response = _report(venue["id"], "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z")

        validate_error(response, ERR_INVALID_PERIOD)

    def test_well_formed_empty_window_reaches_the_no_revenue_precondition(self):
        """Once the ordering holds, an empty window falls through to the revenue precondition.

        "If the total `revenue_cents` of the actual population is zero, or if the total `revenue_cents` of the theoretical population is zero, no percentage is defined and the run is refused with `ERR_NO_REVENUE_IN_PERIOD` (HTTP 422)."

        Design: Corner/validations/reversed_and_equal_pour_cost_periods_return_invalid_period
        """
        fx.set_clock("2026-09-05T00:00:00Z")
        venue = _harbor_venue()

        response = _report(venue["id"], "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z")

        validate_error(response, ERR_NO_REVENUE_IN_PERIOD)

    def test_reversed_period_on_the_pour_cost_run_persists_nothing(self):
        """The run shares the period rule with the report, and a rejected run leaves no investigation and no run stamp.

        "The same period ordering and revenue preconditions apply, with the same two error identifiers."

        Design: Corner/validations/reversed_and_equal_pour_cost_periods_return_invalid_period
        """
        fx.set_clock("2026-09-05T00:00:00Z")
        venue = _harbor_venue()

        response = api_client.create_pour_cost_run(
            venue["id"],
            f.pour_cost_run_payload("2026-09-04T00:00:00Z", "2026-09-01T00:00:00Z"),
            BEVERAGE_DIRECTOR_HEADERS)
        validate_error(response, ERR_INVALID_PERIOD)

        assert fx.open_investigations(venue) == [], (
            "a rejected pour-cost run must not open a variance investigation")
        assert_null_fields(fx.get_venue(venue), "last_pour_cost_run_at")


class TestDistributorListingPaginationBounds:
    """`limit` is accepted from 1 through 100 inclusive and `offset` from 0 up,
    so both ends of the declared range are exercised on the distributor
    collection."""

    @staticmethod
    def _two_distributors():
        first = fx.create_distributor(name="Coastal Selections",
                                      license_number="LIC-0001",
                                      allocation_tier="A")
        second = fx.create_distributor(name="Inland Cellars",
                                       license_number="LIC-0002",
                                       allocation_tier="B")
        return first, second

    def test_limit_one_hundred_at_offset_zero_is_inside_the_declared_range(self):
        """The inclusive upper bound of 100 is accepted and returns the whole collection.

        "`limit` controls page size: it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100."

        Design: Corner/validations/pagination_limit_and_offset_boundaries_on_distributor_listing
        """
        self._two_distributors()

        data, meta = validate_paginated(
            api_client.list_distributors(CONTROLLER_HEADERS,
                                         params={"limit": 100, "offset": 0}))

        assert len(data) == 2, "expected both distributors on a page of 100"
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 100
        assert meta["offset"] == 0

    def test_offset_one_with_limit_one_returns_the_single_remaining_row(self):
        """An offset of 1 with a page of 1 covers the second of two rows and reports no further page.

        "`offset` controls the starting position: it defaults to 0 and its minimum accepted value is 0."

        Design: Corner/validations/pagination_limit_and_offset_boundaries_on_distributor_listing
        """
        self._two_distributors()

        data, meta = validate_paginated(
            api_client.list_distributors(CONTROLLER_HEADERS,
                                         params={"limit": 1, "offset": 1}))

        assert len(data) == 1, "expected exactly one row at offset 1 with limit 1"
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

    def test_limit_above_one_hundred_is_rejected(self):
        """A page size of 101 sits outside the accepted range.

        "A `limit` outside the range 1 through 100, or an `offset` that is negative or not an integer, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/validations/pagination_limit_and_offset_boundaries_on_distributor_listing
        """
        self._two_distributors()

        response = api_client.list_distributors(CONTROLLER_HEADERS,
                                                params={"limit": 101})

        validate_error(response, ERR_INVALID_PAGINATION)

    def test_limit_zero_is_rejected_because_the_lower_bound_is_one(self):
        """A page size of 0 is below the accepted minimum of 1.

        "A `limit` outside the range 1 through 100, or an `offset` that is negative or not an integer, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/validations/pagination_limit_and_offset_boundaries_on_distributor_listing
        """
        self._two_distributors()

        response = api_client.list_distributors(CONTROLLER_HEADERS,
                                                params={"limit": 0})

        validate_error(response, ERR_INVALID_PAGINATION)

    def test_negative_offset_is_rejected(self):
        """A negative starting position is refused by the same pagination rule.

        "A `limit` outside the range 1 through 100, or an `offset` that is negative or not an integer, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/validations/pagination_limit_and_offset_boundaries_on_distributor_listing
        """
        self._two_distributors()

        response = api_client.list_distributors(CONTROLLER_HEADERS,
                                                params={"offset": -1})

        validate_error(response, ERR_INVALID_PAGINATION)


class TestEventWindowOrdering:
    """An event window must open strictly before it closes, and that shape check
    is reported ahead of the buffered occupancy conflict."""

    @staticmethod
    def _venue_with_a_planned_evening():
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = _harbor_venue()
        wine = fx.create_wine(producer="Ridge", cuvee="Monte Bello",
                              category="RED", reference_cost_cents=2400)
        chain = fx.setup_published_entry(venue=venue, wine=wine,
                                         by_the_glass=False,
                                         entry_overrides={"par_bottles": 6})
        fx.create_event(venue, chain["version"],
                        [f.pour_plan_line(chain["entry"]["id"], 2)],
                        name="Ridge Vertical",
                        starts_at="2026-10-10T18:00:00Z",
                        ends_at="2026-10-10T21:00:00Z",
                        seat_count=24)
        return chain

    def test_zero_length_window_is_refused_before_the_occupancy_conflict(self):
        """A window whose bounds are equal is refused for its shape even though it also collides with an existing dinner.

        "An event's window opens strictly before it closes — otherwise `ERR_INVALID_EVENT_WINDOW` (HTTP 422)."

        Design: Corner/validations/equal_and_reversed_event_bounds_return_invalid_event_window
        """
        chain = self._venue_with_a_planned_evening()
        venue_id = chain["venue"]["id"]

        response = api_client.create_wine_dinner_event(
            f.wine_dinner_event_payload(
                venue_id, chain["version"]["id"],
                [f.pour_plan_line(chain["entry"]["id"], 2)],
                name="Zero Length",
                starts_at="2026-10-10T19:00:00Z",
                ends_at="2026-10-10T19:00:00Z",
                seat_count=24),
            sommelier_headers(venue_id))

        validate_error(response, ERR_INVALID_EVENT_WINDOW)

    def test_reversed_window_on_a_free_night_is_refused(self):
        """A backwards window is refused even where nothing else occupies the venue.

        "The window must open strictly before it closes, otherwise `ERR_INVALID_EVENT_WINDOW`."

        Design: Corner/validations/equal_and_reversed_event_bounds_return_invalid_event_window
        """
        chain = self._venue_with_a_planned_evening()
        venue_id = chain["venue"]["id"]

        response = api_client.create_wine_dinner_event(
            f.wine_dinner_event_payload(
                venue_id, chain["version"]["id"],
                [f.pour_plan_line(chain["entry"]["id"], 2)],
                name="Backwards",
                starts_at="2026-11-02T21:00:00Z",
                ends_at="2026-11-02T18:00:00Z",
                seat_count=24),
            sommelier_headers(venue_id))

        validate_error(response, ERR_INVALID_EVENT_WINDOW)

    def test_well_formed_window_is_planned_and_the_rejected_ones_persisted_nothing(self):
        """A correctly ordered window on a free night is planned against the live version, and only it persisted.

        "A new event starts in state `PLANNED` with `pinned_version_no` set to the referenced version's `version_no`, `pinned_version_stale` false, and all five pricing fields — `beverage_cost_per_seat_cents`, `provisional_gross_cents`, `tier_discount_pct`, `final_ticket_price_cents` and `projected_pour_cost_pct` — null."

        Design: Corner/validations/equal_and_reversed_event_bounds_return_invalid_event_window
        """
        chain = self._venue_with_a_planned_evening()
        venue_id = chain["venue"]["id"]
        headers = sommelier_headers(venue_id)

        for bad in ({"name": "Zero Length", "starts_at": "2026-10-10T19:00:00Z",
                     "ends_at": "2026-10-10T19:00:00Z"},
                    {"name": "Backwards", "starts_at": "2026-11-02T21:00:00Z",
                     "ends_at": "2026-11-02T18:00:00Z"}):
            validate_error(
                api_client.create_wine_dinner_event(
                    f.wine_dinner_event_payload(
                        venue_id, chain["version"]["id"],
                        [f.pour_plan_line(chain["entry"]["id"], 2)],
                        seat_count=24, **bad),
                    headers),
                ERR_INVALID_EVENT_WINDOW)

        created = validate_success(
            api_client.create_wine_dinner_event(
                f.wine_dinner_event_payload(
                    venue_id, chain["version"]["id"],
                    [f.pour_plan_line(chain["entry"]["id"], 2)],
                    name="Clean Night",
                    starts_at="2026-11-02T18:00:00Z",
                    ends_at="2026-11-02T21:00:00Z",
                    seat_count=24),
                headers),
            201)

        assert created["state"] == "PLANNED"
        assert created["pinned_version_no"] == chain["version"]["version_no"]
        assert created["pinned_version_stale"] is False

        events, meta = validate_paginated(
            api_client.list_wine_dinner_events(headers,
                                               params={"venue_id": venue_id}))
        assert meta["total_count"] == 2, (
            "only the well-formed window may have persisted an event")
        assert [row["starts_at"] for row in events] == sorted(
            row["starts_at"] for row in events), (
            "wine dinner events are ordered by starts_at ascending")


class TestPourSizeIsRequiredOnlyForGlassEntries:
    """`pour_size_ml` is mandatory exactly when `by_the_glass` is true, on
    creation and again on every patch that flips the flag."""

    @staticmethod
    def _draft():
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = _harbor_venue()
        wine = fx.create_wine(producer="Ridge", cuvee="Monte Bello",
                              category="RED", reference_cost_cents=2400)
        draft = fx.setup_draft_version(venue)
        return venue, wine, draft["version"]

    def test_glass_entry_without_a_pour_size_is_refused_and_creates_nothing(self):
        """Marking a new entry for the rotation without a pour size is refused and leaves the draft untouched.

        "Marking an entry for the glass without a pour size is `ERR_POUR_SIZE_REQUIRED` (HTTP 400)."

        Design: Corner/validations/by_the_glass_without_pour_size_returns_pour_size_required
        """
        venue, wine, version = self._draft()
        venue_id = venue["id"]

        response = api_client.create_list_entry(
            version["id"],
            f.list_entry_payload(wine["id"], version["version"], sort_rank=1,
                                 by_the_glass=True, par_bottles=6),
            sommelier_headers(venue_id))
        validate_error(response, ERR_POUR_SIZE_REQUIRED)

        reread = validate_success(
            api_client.get_list_version(version["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert reread["entry_count"] == 0
        assert reread["version"] == version["version"], (
            "a refused entry must not bump the draft version")

    def test_identical_body_with_the_flag_false_is_accepted_without_glass_fields(self):
        """The same body is legal on a bottle-only listing, which carries no glass fields at all.

        "When `by_the_glass` is false, both `effective_pours` and `glass_price_cents` are null."

        Design: Corner/validations/by_the_glass_without_pour_size_returns_pour_size_required
        """
        venue, wine, version = self._draft()
        venue_id = venue["id"]

        entry = validate_success(
            api_client.create_list_entry(
                version["id"],
                f.list_entry_payload(wine["id"], version["version"], sort_rank=1,
                                     by_the_glass=False, par_bottles=6),
                sommelier_headers(venue_id)),
            201)

        assert_null_fields(entry, "effective_pours", "glass_price_cents")
        assert entry["bottle_price_cents"] == 8600, (
            "2400 cents takes the 3.00 markup band (7200) but the 28.00 percent "
            "target candidate 8571 wins and lifts to the next whole dollar")
        assert entry["price_band"] == "CORE"

    def test_patch_that_turns_on_the_glass_flag_alone_is_refused(self):
        """Flipping the flag on with no stored pour size re-runs the mandatory-pour-size check on the merged entry.

        "Changing either of the first two re-runs the glass-price computation — including the mandatory-pour-size and minimum-saleable-pours checks, which carry the same two error identifiers as at creation — and when `by_the_glass` becomes false both `effective_pours` and `glass_price_cents` are cleared to null."

        Design: Corner/validations/by_the_glass_without_pour_size_returns_pour_size_required
        """
        venue, wine, version = self._draft()
        venue_id = venue["id"]
        entry = fx.add_entry(version, wine, venue, sort_rank=1,
                             by_the_glass=False, par_bottles=6)

        response = api_client.patch_list_entry(entry["id"], {"by_the_glass": True},
                                               sommelier_headers(venue_id))
        validate_error(response, ERR_POUR_SIZE_REQUIRED)

        reread = validate_success(
            api_client.get_list_entry(entry["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert reread["by_the_glass"] is False, (
            "the refused patch must not have written the flag")
        assert_null_fields(reread, "pour_size_ml", "effective_pours",
                           "glass_price_cents")

    def test_patch_supplying_both_fields_prices_the_glass(self):
        """Supplying the flag and the pour size together yields the declared pour count and quarter-lifted glass price.

        "The glass price then follows from the same category target: multiply the wine's `reference_cost_cents` by 100, divide by the venue's category target percentage, divide again by `effective_pours`, round that half up to whole cents, and finally raise the result to the next whole multiple of 25 cents."

        Design: Corner/validations/by_the_glass_without_pour_size_returns_pour_size_required
        """
        venue, wine, version = self._draft()
        venue_id = venue["id"]
        entry = fx.add_entry(version, wine, venue, sort_rank=1,
                             by_the_glass=False, par_bottles=6)

        patched = validate_success(
            api_client.patch_list_entry(
                entry["id"], {"by_the_glass": True, "pour_size_ml": 177},
                sommelier_headers(venue_id)))

        assert patched["effective_pours"] == 3, (
            "750 ml over a 177 ml pour is 4 gross pours less the one-pour allowance")
        assert patched["glass_price_cents"] == 2875, (
            "240000 / 28.00 / 3 rounds to 2857 cents and lifts to 2875")


class TestCodeUniquenessScopes:
    """`venue_code` collides across the whole group while `bin_code` collides
    only inside one venue, so the same literal behaves differently at each
    level."""

    @staticmethod
    def _harbor_with_bin_a1():
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = _harbor_venue(name="Harbor Room", venue_code="HRB")
        bin_ = fx.create_bin(venue, bin_code="A1", zone="CELLAR",
                             capacity_bottles=48, temperature_controlled=True)
        return venue, bin_

    def test_reused_venue_code_is_refused_across_the_group(self):
        """A second venue may not take an operator code already in use, however different its name.

        "Registration takes the restaurant's `name` (1 to 120 characters) and a short operator code `venue_code` (1 to 12 characters) that must be unique across the whole group; a collision is refused with `ERR_VENUE_CODE_TAKEN`."

        Design: Corner/validations/venue_code_is_globally_unique_while_bin_code_is_venue_scoped
        """
        self._harbor_with_bin_a1()

        response = api_client.create_venue(
            f.venue_payload(name="Harbour Room Annex", venue_code="HRB",
                            cogs_target_pct_by_category=f.cogs_targets(**RED_TARGETS)),
            BEVERAGE_DIRECTOR_HEADERS)
        validate_error(response, ERR_VENUE_CODE_TAKEN)

        _rows, meta = validate_paginated(
            api_client.list_venues(BEVERAGE_DIRECTOR_HEADERS))
        assert meta["total_count"] == 1, "the refused registration persisted nothing"

    def test_the_same_bin_code_is_accepted_inside_a_second_venue(self):
        """Bin codes are scoped to their venue, so a fresh venue may reuse the literal A1.

        "Three computed fields describe occupancy: `bottles_stored` is the sum of `bottles_on_hand` across the lots sitting in this bin whose state is `ON_HAND` and starts at 0; `utilization_pct` is `bottles_stored` multiplied by 100, divided by `capacity_bottles`, rounded half up to two decimals, and starts at 0.00; and `bin_state` is `FULL` when `bottles_stored` equals `capacity_bottles` exactly and `ACTIVE` in every other case, starting at `ACTIVE`."

        Design: Corner/validations/venue_code_is_globally_unique_while_bin_code_is_venue_scoped
        """
        self._harbor_with_bin_a1()
        second = validate_success(
            api_client.create_venue(
                f.venue_payload(name="Garden Table", venue_code="GDN",
                                cogs_target_pct_by_category=f.cogs_targets(**RED_TARGETS)),
                BEVERAGE_DIRECTOR_HEADERS),
            201)

        created = validate_success(
            api_client.create_cellar_bin(
                second["id"],
                f.cellar_bin_payload(bin_code="A1", zone="CELLAR",
                                     capacity_bottles=24,
                                     temperature_controlled=False),
                sommelier_headers(second["id"])),
            201)

        assert created["venue_id"] == second["id"]
        assert created["capacity_bottles"] == 24
        assert created["bottles_stored"] == 0
        assert_decimal_equals(created["utilization_pct"], 0.00, "utilization_pct")
        assert created["bin_state"] == "ACTIVE"

    def test_reused_bin_code_inside_one_venue_is_refused(self):
        """A repeat of A1 inside the same venue is refused even with a different zone and capacity.

        "A bin carries a `bin_code` of 1 to 12 characters that must be unique within its venue — a repeat is `ERR_BIN_CODE_TAKEN` — a `zone` of `CELLAR`, `BACKBAR`, `RESERVE` or `OFFSITE`, a hard `capacity_bottles` of at least 1, and a reporting flag `temperature_controlled` that defaults to true."

        Design: Corner/validations/venue_code_is_globally_unique_while_bin_code_is_venue_scoped
        """
        venue, _bin = self._harbor_with_bin_a1()
        venue_id = venue["id"]

        response = api_client.create_cellar_bin(
            venue_id,
            f.cellar_bin_payload(bin_code="A1", zone="RESERVE",
                                 capacity_bottles=12, temperature_controlled=True),
            sommelier_headers(venue_id))
        validate_error(response, ERR_BIN_CODE_TAKEN)

        _rows, meta = validate_paginated(
            api_client.list_cellar_bins(BEVERAGE_DIRECTOR_HEADERS,
                                        params={"venue_id": venue_id}))
        assert meta["total_count"] == 1, (
            "the refused bin must not have been stored as a distinct row")


class TestSommelierVenueScope:
    """A sommelier's venue scope is checked before any foreign key in the body is
    resolved, and it applies to pure reads as much as to writes."""

    @staticmethod
    def _two_venues_one_lot():
        fx.set_clock("2026-09-01T12:00:00Z")
        first = _harbor_venue(name="Harbor Room", venue_code="HRB")
        second = _harbor_venue(name="Garden Table", venue_code="GDN")
        bin_ = fx.create_bin(first, bin_code="A1", zone="CELLAR",
                             capacity_bottles=48)
        wine = fx.create_wine(producer="Ridge", cuvee="Monte Bello",
                              category="RED", reference_cost_cents=2400)
        fx.create_lot(first, wine, bin_, bottles_received=6,
                      unit_cost_cents=2400, received_at="2026-08-10T00:00:00Z")
        return first, second, bin_, wine

    def test_lot_creation_into_another_venues_bin_is_refused_on_scope(self):
        """A sommelier posting a lot whose body names a foreign venue is refused on scope and writes nothing.

        "A sommelier acting on anything that resolves to a different venue is rejected with `ERR_VENUE_SCOPE_VIOLATION` (HTTP 403), and that rejection is evaluated before any existence check on foreign keys carried in the request body."

        Design: Corner/validations/sommelier_cannot_reach_another_venues_slot_or_par_report
        """
        first, second, bin_, wine = self._two_venues_one_lot()

        response = api_client.create_inventory_lot(
            f.inventory_lot_payload(first["id"], wine["id"], bin_["id"],
                                    bottles_received=6, unit_cost_cents=2400,
                                    received_at="2026-08-10T00:00:00Z"),
            sommelier_headers(second["id"]))
        validate_error(response, ERR_VENUE_SCOPE_VIOLATION)

        _rows, meta = validate_paginated(
            api_client.list_inventory_lots(sommelier_headers(first["id"]),
                                           params={"venue_id": first["id"]}))
        assert meta["total_count"] == 1, "the refused lot must not have persisted"

    def test_scope_is_reported_ahead_of_an_unresolvable_body_foreign_key(self):
        """The same cross-venue post carrying an unknown wine still answers scope rather than not-found.

        "A sommelier acting on anything that resolves to a different venue is rejected with `ERR_VENUE_SCOPE_VIOLATION` (HTTP 403), and that rejection is evaluated before any existence check on foreign keys carried in the request body."

        Design: Corner/validations/sommelier_cannot_reach_another_venues_slot_or_par_report
        """
        first, second, bin_, _wine = self._two_venues_one_lot()

        response = api_client.create_inventory_lot(
            f.inventory_lot_payload(first["id"], NON_EXISTENT_UUID, bin_["id"],
                                    bottles_received=6, unit_cost_cents=2400,
                                    received_at="2026-08-10T00:00:00Z"),
            sommelier_headers(second["id"]))

        validate_error(response, ERR_VENUE_SCOPE_VIOLATION)

    def test_par_report_of_another_venue_is_refused_on_scope(self):
        """Reading a foreign venue's par report is refused even though the call mutates nothing.

        "A sommelier acting on anything that resolves to a different venue is rejected with `ERR_VENUE_SCOPE_VIOLATION` (HTTP 403), and that rejection is evaluated before any existence check on foreign keys carried in the request body."

        Design: Corner/validations/sommelier_cannot_reach_another_venues_slot_or_par_report
        """
        first, second, _bin, _wine = self._two_venues_one_lot()

        response = api_client.get_par_report(first["id"],
                                             sommelier_headers(second["id"]))

        validate_error(response, ERR_VENUE_SCOPE_VIOLATION)

    def test_the_owning_sommelier_still_reads_its_own_par_report(self):
        """The identical read succeeds for the venue's own sommelier, so the rule is scope-based and not a blanket denial.

        "Replenishment is served by a par-level report available to the director and the sommelier, which reads the single live list version of the venue — the one in `PUBLISHED` or `REPRINT_PENDING` — and walks its entries."

        Design: Corner/validations/sommelier_cannot_reach_another_venues_slot_or_par_report
        """
        first, _second, _bin, _wine = self._two_venues_one_lot()

        report = validate_success(
            api_client.get_par_report(first["id"], sommelier_headers(first["id"])))

        assert report["venue_id"] == first["id"]


class TestWriteOffSegregationOfDuties:
    """The write-off submit endpoint is open to the Controller, so the same
    controller can attempt both halves — and the rule compares the acting user id
    against the recorded submitter, not the role."""

    @staticmethod
    def _submitted_by_the_controller():
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = _harbor_venue(name="Harbor Room", venue_code="HRB")
        bin_ = fx.create_bin(venue, bin_code="A1", zone="CELLAR",
                             capacity_bottles=48)
        wine = fx.create_wine(producer="Ridge", cuvee="Monte Bello",
                              category="RED", reference_cost_cents=2400)
        lot = fx.create_lot(venue, wine, bin_, bottles_received=6,
                            unit_cost_cents=2400,
                            received_at="2026-08-10T00:00:00Z")
        write_off = validate_success(
            api_client.create_spoilage_write_off(
                f.write_off_payload(venue["id"], lot["id"], bottles=2,
                                    reason_code="BREAKAGE",
                                    narrative="Two bottles dropped during a bin move."),
                CONTROLLER_HEADERS),
            201)
        assert write_off["submitted_by_user_id"] == CONTROLLER_HEADERS["X-User-ID"]
        assert write_off["state"] == "SUBMITTED"
        assert write_off["cogs_cents"] == 0
        return venue, bin_, lot, write_off

    def test_the_submitting_controller_cannot_approve_its_own_write_off(self):
        """Approving a write-off one submitted oneself is refused on identity, and no bottle moves.

        "Publishing a list version and approving or rejecting a spoilage write-off are both refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the acting `X-User-ID` equals the identifier recorded as the submitter on the object being acted on."

        Design: Corner/validations/same_user_cannot_submit_and_approve_a_write_off
        """
        _venue, bin_, lot, write_off = self._submitted_by_the_controller()

        response = api_client.approve_write_off(write_off["id"], CONTROLLER_HEADERS)
        validate_error(response, ERR_SEGREGATION_OF_DUTIES)

        reread = validate_success(
            api_client.get_spoilage_write_off(write_off["id"], CONTROLLER_HEADERS))
        assert reread["state"] == "SUBMITTED"
        assert validate_success(
            api_client.get_inventory_lot(lot["id"], CONTROLLER_HEADERS)
        )["bottles_on_hand"] == 6
        assert validate_success(
            api_client.get_cellar_bin(bin_["id"], CONTROLLER_HEADERS)
        )["bottles_stored"] == 6

    def test_the_submitting_controller_cannot_reject_its_own_write_off(self):
        """The rule covers rejection as well as approval, so the quiet branch is closed to the submitter too.

        "It is controller-exclusive, requires the write-off to be in `SUBMITTED` (`ERR_WRITE_OFF_NOT_SUBMITTED`) and the acting `X-User-ID` to differ from the submitter (`ERR_SEGREGATION_OF_DUTIES`), carries a mandatory `note` that is stored as the write-off's `resolution_note`, and moves the record `SUBMITTED → REJECTED`."

        Design: Corner/validations/same_user_cannot_submit_and_approve_a_write_off
        """
        _venue, _bin, _lot, write_off = self._submitted_by_the_controller()

        response = api_client.reject_write_off(
            write_off["id"], f.note_payload("Self-rejecting my own submission."),
            CONTROLLER_HEADERS)
        validate_error(response, ERR_SEGREGATION_OF_DUTIES)

        reread = validate_success(
            api_client.get_spoilage_write_off(write_off["id"], CONTROLLER_HEADERS))
        assert reread["state"] == "SUBMITTED"
        assert_null_fields(reread, "resolution_note", "approved_by_user_id")

    def test_a_second_controller_approves_the_very_same_write_off(self):
        """A different controller may approve it, which proves the block was identity and not role.

        "On approval the write-off moves `SUBMITTED → APPROVED`, records `approved_by_user_id` as the acting `X-User-ID`, and computes `cogs_cents` by pricing the written-off bottles out of that one nominated lot under the venue's costing method."

        Design: Corner/validations/same_user_cannot_submit_and_approve_a_write_off
        """
        _venue, bin_, lot, write_off = self._submitted_by_the_controller()
        other = second_controller_headers()

        approved = validate_success(
            api_client.approve_write_off(write_off["id"], other))

        assert approved["state"] == "APPROVED"
        assert approved["approved_by_user_id"] == other["X-User-ID"]
        assert approved["cogs_cents"] == 4800, "2 bottles priced at 2400 cents each"
        assert validate_success(
            api_client.get_inventory_lot(lot["id"], CONTROLLER_HEADERS)
        )["bottles_on_hand"] == 4
        assert validate_success(
            api_client.get_cellar_bin(bin_["id"], CONTROLLER_HEADERS)
        )["bottles_stored"] == 4


class TestSlotCloseAggregatePourCeiling:
    """The pour ceiling on a slot close is an aggregate over both submitted
    counts, and a sum exactly equal to the frozen `effective_pours` is legal."""

    @staticmethod
    def _open_slot_of_three_pours():
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = _harbor_venue(name="Harbor Room", venue_code="HRB")
        wine = fx.create_wine(producer="Ridge", cuvee="Monte Bello",
                              category="RED", reference_cost_cents=2400)
        chain = fx.setup_published_entry(venue=venue, wine=wine,
                                         pour_size_ml=177, bottles_received=6,
                                         unit_cost_cents=2400,
                                         received_at="2026-08-10T00:00:00Z",
                                         entry_overrides={"par_bottles": 6})
        slot = fx.open_slot(venue, chain["entry"], chain["lot"], slot_index=1,
                            preservation_method="ARGON")
        assert slot["effective_pours"] == 3, (
            "a 177 ml pour out of 750 ml leaves 3 saleable glasses")
        chain["slot"] = slot
        return chain

    def test_sold_plus_education_over_the_bottle_is_refused_on_the_sum(self):
        """Two sold and two educational glasses each fit the bottle alone but not together, and the close is refused.

        "The slot must be in `OPEN`, otherwise `ERR_SLOT_NOT_OPEN` (HTTP 409), and the two submitted pour counts together must not exceed the slot's frozen `effective_pours`, otherwise `ERR_POURS_EXCEED_BOTTLE` (HTTP 422)."

        Design: Corner/validations/close_with_sold_plus_education_over_effective_pours_rejected
        """
        chain = self._open_slot_of_three_pours()
        venue_id = chain["venue"]["id"]

        response = api_client.close_btg_slot(
            chain["slot"]["id"],
            f.close_slot_payload(2, staff_education_pours=2),
            sommelier_headers(venue_id))
        validate_error(response, ERR_POURS_EXCEED_BOTTLE)

        slot = validate_success(
            api_client.get_btg_slot(chain["slot"]["id"], CONTROLLER_HEADERS))
        assert slot["state"] == "OPEN"
        assert slot["pours_sold"] == 0
        assert validate_success(
            api_client.get_inventory_lot(chain["lot"]["id"], CONTROLLER_HEADERS)
        )["bottles_committed"] == 1, (
            "the refused close must leave the bottle committed to the rail")

    def test_a_sum_exactly_equal_to_the_bottle_closes_with_no_spoilage(self):
        """Two sold plus one educational glass exhausts the three saleable pours, so nothing spoils and no spoilage entry is written.

        "On the `OPEN → CLOSED` branch, `spoiled_pours` is set to the slot's `effective_pours` less `pours_sold` less `staff_education_pours`, and the cost of the bottle is split three ways."

        Design: Corner/validations/close_with_sold_plus_education_over_effective_pours_rejected
        """
        chain = self._open_slot_of_three_pours()
        venue_id = chain["venue"]["id"]

        closed = validate_success(
            api_client.close_btg_slot(
                chain["slot"]["id"],
                f.close_slot_payload(2, staff_education_pours=1),
                sommelier_headers(venue_id)))

        assert closed["state"] == "CLOSED"
        assert closed["spoiled_pours"] == 0
        entries = depletion_entries_for(CONTROLLER_HEADERS,
                                        btg_slot_id=chain["slot"]["id"])
        assert [entry["reason"] for entry in entries] == ["SALE_BTG",
                                                          "STAFF_EDUCATION"], (
            "a bucket whose pour count is zero produces no entry at all")

    def test_the_aggregate_rule_is_only_reached_from_the_open_state(self):
        """Once the slot has closed, a further close is refused on state rather than on the pour ceiling.

        "The slot must be in `OPEN`, otherwise `ERR_SLOT_NOT_OPEN` (HTTP 409), and the two submitted pour counts together must not exceed the slot's frozen `effective_pours`, otherwise `ERR_POURS_EXCEED_BOTTLE` (HTTP 422)."

        Design: Corner/validations/close_with_sold_plus_education_over_effective_pours_rejected
        """
        chain = self._open_slot_of_three_pours()
        venue_id = chain["venue"]["id"]
        fx.close_slot(chain["slot"], chain["venue"], pours_sold=2,
                      staff_education_pours=1)

        response = api_client.close_btg_slot(chain["slot"]["id"],
                                             f.close_slot_payload(1),
                                             sommelier_headers(venue_id))

        validate_error(response, ERR_SLOT_NOT_OPEN)


class TestOfferResponseDeadlineIsStrict:
    """Only an instant strictly earlier than the offer's `response_deadline` may
    carry a claim, and the deadline never moves the offer's own state."""

    @staticmethod
    def _offer_closing_at_noon():
        fx.set_clock("2026-09-01T11:59:59Z")
        first = _harbor_venue(name="Harbor Room", venue_code="HRB",
                              priority_rank=1)
        second = _harbor_venue(name="Garden Table", venue_code="GDN",
                               priority_rank=2)
        distributor = fx.create_distributor(name="Coastal Selections",
                                            license_number="LIC-0001",
                                            allocation_tier="A")
        wine = fx.create_wine(producer="Ridge", cuvee="Monte Bello",
                              category="RED", reference_cost_cents=2400,
                              is_allocated=True)
        offer = fx.create_offer(distributor, wine, offered_bottles=10,
                                unit_cost_cents=3000,
                                response_deadline="2026-09-01T12:00:00Z")
        return first, second, offer

    def test_a_claim_one_second_before_the_deadline_is_accepted(self):
        """A claim filed strictly before the deadline is created and bumps the offer it was sized against.

        "A successful claim is created in state `REQUESTED` with `granted_bottles` 0, `raw_share` 0.0000 and `remainder_awarded` false, and it increments the parent offer's `claim_count` by 1 and the offer's `version` by 1 — which is precisely why the next claimant's guard value must be re-read."

        Design: Corner/validations/claim_at_exact_response_deadline_returns_offer_deadline_passed
        """
        first, _second, offer = self._offer_closing_at_noon()

        claim = validate_success(
            api_client.create_allocation_claim(
                offer["id"],
                f.allocation_claim_payload(first["id"], 6, offer["version"]),
                sommelier_headers(first["id"])),
            201)

        assert claim["state"] == "REQUESTED"
        assert claim["granted_bottles"] == 0
        assert_decimal_equals(claim["raw_share"], 0.0, "raw_share")
        reread = validate_success(
            api_client.get_allocation_offer(offer["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert reread["version"] == offer["version"] + 1
        assert reread["claim_count"] == 1

    def test_a_claim_at_the_deadline_instant_is_refused_and_leaves_the_offer_open(self):
        """A claim filed at exactly the deadline is refused, and the offer stays open with its pool intact.

        "A claim is refused when the offer's fulfilment dimension is anything other than `OPEN` (`ERR_OFFER_NOT_OPEN`, HTTP 409); when this venue already holds a claim on this offer in *any* state, including a withdrawn or rejected one (`ERR_DUPLICATE_CLAIM`, HTTP 409); when `requested_bottles` exceeds the offer's `offered_bottles` (`ERR_REQUEST_EXCEEDS_OFFER`, HTTP 422); when the logical clock has reached or passed the offer's `response_deadline`, so that only an instant strictly earlier than the deadline is accepted (`ERR_OFFER_DEADLINE_PASSED`, HTTP 422); and when the distributor behind the offer stands in `HOLD` (`ERR_DISTRIBUTOR_COMPLIANCE_HOLD`, HTTP 422)."

        Design: Corner/validations/claim_at_exact_response_deadline_returns_offer_deadline_passed
        """
        first, second, offer = self._offer_closing_at_noon()
        fx.file_claim(offer, first, 6)
        fx.set_clock("2026-09-01T12:00:00Z")
        live_version = fx.current_version(api_client.get_allocation_offer,
                                          offer["id"])

        response = api_client.create_allocation_claim(
            offer["id"],
            f.allocation_claim_payload(second["id"], 4, live_version),
            sommelier_headers(second["id"]))
        validate_error(response, ERR_OFFER_DEADLINE_PASSED)

        reread = validate_success(
            api_client.get_allocation_offer(offer["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert reread["version"] == live_version, (
            "a refused claim must not bump the offer again")
        assert reread["claim_count"] == 1
        assert reread["fulfillment_state"] == "OPEN"
        assert reread["unallocated_bottles"] == 10


class TestClaimSizeAndPerVenueUniqueness:
    """`requested_bottles` is bounded by the whole offered pool, and one venue
    holds at most one claim per offer whatever its state."""

    @staticmethod
    def _offer_of_ten():
        fx.set_clock("2026-09-01T00:00:00Z")
        first = _harbor_venue(name="Harbor Room", venue_code="HRB",
                              priority_rank=1)
        second = _harbor_venue(name="Garden Table", venue_code="GDN",
                               priority_rank=2)
        distributor = fx.create_distributor(name="Coastal Selections",
                                            license_number="LIC-0001",
                                            allocation_tier="A")
        wine = fx.create_wine(producer="Ridge", cuvee="Monte Bello",
                              category="RED", reference_cost_cents=2400,
                              is_allocated=True)
        offer = fx.create_offer(distributor, wine, offered_bottles=10,
                                unit_cost_cents=3000,
                                response_deadline="2026-09-30T00:00:00Z")
        return first, second, offer

    def test_a_request_above_the_offered_pool_is_refused(self):
        """Eleven bottles against a pool of ten is refused and does not bump the offer.

        "A claim is refused when the offer's fulfilment dimension is anything other than `OPEN` (`ERR_OFFER_NOT_OPEN`, HTTP 409); when this venue already holds a claim on this offer in *any* state, including a withdrawn or rejected one (`ERR_DUPLICATE_CLAIM`, HTTP 409); when `requested_bottles` exceeds the offer's `offered_bottles` (`ERR_REQUEST_EXCEEDS_OFFER`, HTTP 422); when the logical clock has reached or passed the offer's `response_deadline`, so that only an instant strictly earlier than the deadline is accepted (`ERR_OFFER_DEADLINE_PASSED`, HTTP 422); and when the distributor behind the offer stands in `HOLD` (`ERR_DISTRIBUTOR_COMPLIANCE_HOLD`, HTTP 422)."

        Design: Corner/validations/oversized_and_duplicate_claims_on_one_offer_rejected
        """
        first, _second, offer = self._offer_of_ten()

        response = api_client.create_allocation_claim(
            offer["id"],
            f.allocation_claim_payload(first["id"], 11, offer["version"]),
            sommelier_headers(first["id"]))
        validate_error(response, ERR_REQUEST_EXCEEDS_OFFER)

        reread = validate_success(
            api_client.get_allocation_offer(offer["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert reread["version"] == offer["version"]
        assert reread["claim_count"] == 0

    def test_a_request_exactly_equal_to_the_pool_is_accepted(self):
        """The bound is inclusive, so a venue may claim the entire offered pool.

        "A `VenueSommelier` files a claim by naming its own `venue_id`, the `requested_bottles` it wants (at least 1) and the `expected_offer_version` guard described in Section 2.7."

        Design: Corner/validations/oversized_and_duplicate_claims_on_one_offer_rejected
        """
        first, _second, offer = self._offer_of_ten()

        claim = validate_success(
            api_client.create_allocation_claim(
                offer["id"],
                f.allocation_claim_payload(first["id"], 10, offer["version"]),
                sommelier_headers(first["id"])),
            201)

        assert claim["requested_bottles"] == 10
        assert claim["state"] == "REQUESTED"

    def test_the_same_venue_cannot_file_a_second_claim_on_one_offer(self):
        """A follow-up claim from the same venue is refused as a duplicate even though a single bottle would fit.

        "Uniqueness: `venue_code` across all venues (`ERR_VENUE_CODE_TAKEN`), `bin_code` within its venue (`ERR_BIN_CODE_TAKEN`), one claim per venue per offer (`ERR_DUPLICATE_CLAIM`), one entry per wine per list version (`ERR_DUPLICATE_LIST_ENTRY_WINE`) — each HTTP 409."

        Design: Corner/validations/oversized_and_duplicate_claims_on_one_offer_rejected
        """
        first, _second, offer = self._offer_of_ten()
        fx.file_claim(offer, first, 10)
        live_version = fx.current_version(api_client.get_allocation_offer,
                                          offer["id"])

        response = api_client.create_allocation_claim(
            offer["id"],
            f.allocation_claim_payload(first["id"], 1, live_version),
            sommelier_headers(first["id"]))
        validate_error(response, ERR_DUPLICATE_CLAIM)

        reread = validate_success(
            api_client.get_allocation_offer(offer["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert reread["claim_count"] == 1

    def test_a_second_venue_may_still_claim_the_whole_pool(self):
        """The uniqueness key is the venue and the offer together, so another venue may claim the full ten and nothing is reserved yet.

        "A successful claim is created in state `REQUESTED` with `granted_bottles` 0, `raw_share` 0.0000 and `remainder_awarded` false, and it increments the parent offer's `claim_count` by 1 and the offer's `version` by 1 — which is precisely why the next claimant's guard value must be re-read."

        Design: Corner/validations/oversized_and_duplicate_claims_on_one_offer_rejected
        """
        first, second, offer = self._offer_of_ten()
        fx.file_claim(offer, first, 10)
        live_version = fx.current_version(api_client.get_allocation_offer,
                                          offer["id"])

        claim = validate_success(
            api_client.create_allocation_claim(
                offer["id"],
                f.allocation_claim_payload(second["id"], 10, live_version),
                sommelier_headers(second["id"])),
            201)

        assert claim["venue_id"] == second["id"]
        reread = validate_success(
            api_client.get_allocation_offer(offer["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert reread["claim_count"] == 2
        assert reread["unallocated_bottles"] == 10, (
            "claiming reserves nothing until the waterfall runs")


class TestLotReceiptIsNotInTheFuture:
    """A direct receipt shares the future-receipt and capacity checks with an
    allocation receipt: `received_at` equal to the clock is legal, one second
    later is not, and a backdated stamp buys no capacity exemption."""

    @staticmethod
    def _bin_of_forty_eight():
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = _harbor_venue(name="Harbor Room", venue_code="HRB")
        bin_ = fx.create_bin(venue, bin_code="A1", zone="CELLAR",
                             capacity_bottles=48, temperature_controlled=True)
        wine = fx.create_wine(producer="Ridge", cuvee="Monte Bello",
                              category="RED", reference_cost_cents=2400)
        return venue, bin_, wine

    def test_received_at_one_second_after_the_clock_is_refused(self):
        """A receipt stamped one second ahead of the logical clock is refused and moves no stock.

        "Six checks guard it: the claim must be in `GRANTED` or `PARTIALLY_GRANTED` (`ERR_CLAIM_NOT_GRANTED`, HTTP 409); the offer's compliance dimension must not be `BLOCKED` (`ERR_OFFER_COMPLIANCE_BLOCKED`); the distributor must not stand in `HOLD` (`ERR_DISTRIBUTOR_COMPLIANCE_HOLD`); `received_at` must not be later than the logical clock (`ERR_RECEIVED_AT_IN_FUTURE`, HTTP 422); the nominated bin must belong to the claiming venue (`ERR_LOT_VENUE_MISMATCH`, HTTP 422); the bin's zone must not be `RESERVE` unless the wine is flagged allocated (`ERR_BIN_ZONE_MISMATCH`); and the bin's `bottles_stored` plus the incoming bottles must not exceed its `capacity_bottles` (`ERR_BIN_CAPACITY_EXCEEDED`, HTTP 409)."

        Design: Corner/validations/lot_received_at_after_the_clock_returns_received_at_in_future
        """
        venue, bin_, wine = self._bin_of_forty_eight()
        venue_id = venue["id"]

        response = api_client.create_inventory_lot(
            f.inventory_lot_payload(venue_id, wine["id"], bin_["id"],
                                    bottles_received=6, unit_cost_cents=2400,
                                    received_at="2026-09-01T12:00:01Z"),
            sommelier_headers(venue_id))
        validate_error(response, ERR_RECEIVED_AT_IN_FUTURE)

        assert validate_success(
            api_client.get_cellar_bin(bin_["id"], BEVERAGE_DIRECTOR_HEADERS)
        )["bottles_stored"] == 0
        _rows, meta = validate_paginated(
            api_client.list_inventory_lots(sommelier_headers(venue_id),
                                           params={"venue_id": venue_id}))
        assert meta["total_count"] == 0, "the refused receipt created no lot"

    def test_received_at_exactly_on_the_clock_is_accepted(self):
        """A receipt stamped exactly at the clock is legal and fills the bin.

        "The resulting lot has `bottles_on_hand` equal to `bottles_received`, `bottles_committed` 0, state `ON_HAND` and `source_claim_id` left null, which is what distinguishes a direct buy from an allocation receipt."

        Design: Corner/validations/lot_received_at_after_the_clock_returns_received_at_in_future
        """
        venue, bin_, wine = self._bin_of_forty_eight()
        venue_id = venue["id"]

        lot = validate_success(
            api_client.create_inventory_lot(
                f.inventory_lot_payload(venue_id, wine["id"], bin_["id"],
                                        bottles_received=6, unit_cost_cents=2400,
                                        received_at="2026-09-01T12:00:00Z"),
                sommelier_headers(venue_id)),
            201)

        assert lot["state"] == "ON_HAND"
        assert lot["bottles_on_hand"] == 6
        assert lot["bottles_committed"] == 0
        stored = validate_success(
            api_client.get_cellar_bin(bin_["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert stored["bottles_stored"] == 6
        assert_decimal_equals(stored["utilization_pct"], 12.50, "utilization_pct")

    def test_a_backdated_receipt_still_respects_the_bin_capacity(self):
        """A receipt in the past is refused when it would overfill the bin, so the past stamp is no exemption.

        "Six checks guard it: the claim must be in `GRANTED` or `PARTIALLY_GRANTED` (`ERR_CLAIM_NOT_GRANTED`, HTTP 409); the offer's compliance dimension must not be `BLOCKED` (`ERR_OFFER_COMPLIANCE_BLOCKED`); the distributor must not stand in `HOLD` (`ERR_DISTRIBUTOR_COMPLIANCE_HOLD`); `received_at` must not be later than the logical clock (`ERR_RECEIVED_AT_IN_FUTURE`, HTTP 422); the nominated bin must belong to the claiming venue (`ERR_LOT_VENUE_MISMATCH`, HTTP 422); the bin's zone must not be `RESERVE` unless the wine is flagged allocated (`ERR_BIN_ZONE_MISMATCH`); and the bin's `bottles_stored` plus the incoming bottles must not exceed its `capacity_bottles` (`ERR_BIN_CAPACITY_EXCEEDED`, HTTP 409)."

        Design: Corner/validations/lot_received_at_after_the_clock_returns_received_at_in_future
        """
        venue, bin_, wine = self._bin_of_forty_eight()
        venue_id = venue["id"]
        fx.create_lot(venue, wine, bin_, bottles_received=6,
                      unit_cost_cents=2400,
                      received_at="2026-09-01T12:00:00Z")

        response = api_client.create_inventory_lot(
            f.inventory_lot_payload(venue_id, wine["id"], bin_["id"],
                                    bottles_received=60, unit_cost_cents=2400,
                                    received_at="2026-08-10T00:00:00Z"),
            sommelier_headers(venue_id))
        validate_error(response, ERR_BIN_CAPACITY_EXCEEDED)

        _rows, meta = validate_paginated(
            api_client.list_inventory_lots(sommelier_headers(venue_id),
                                           params={"venue_id": venue_id}))
        assert meta["total_count"] == 1, "only the accepted lot may exist"


class TestCorkageValidationLadder:
    """One stateless corkage quote can break the enum rule, the prohibited-category
    safety rule and the bottle-limit constraint, and the declared check order
    decides which of them is reported."""

    @staticmethod
    def _sparkling_prohibiting_venue():
        fx.set_clock("2026-09-01T12:00:00Z")
        return _harbor_venue(name="Harbor Room", venue_code="HRB",
                             corkage_fee_cents=3500,
                             corkage_waiver_purchase_ratio=2,
                             byo_bottle_limit_per_party=2,
                             byo_prohibited_categories=["SPARKLING"])

    def test_prohibited_category_is_reported_ahead_of_the_bottle_limit(self):
        """A quote that breaks both the prohibited-category rule and the bottle limit answers the safety error.

        "Checks are evaluated strictly in the following sequence, and the first failure is the one reported:"
        "18. Compliance safety: distributor hold, offer block, prohibited by-your-own-bottle category."
        "21. Remaining value constraints: reserve-zone eligibility, bin capacity, request against offered pool, eligible claims, minimum saleable pours, pours against bottle, by-your-own-bottle limit."

        Design: Corner/validations/prohibited_byo_category_beats_byo_bottle_limit
        """
        venue = self._sparkling_prohibiting_venue()
        venue_id = venue["id"]

        response = api_client.quote_corkage(
            venue_id,
            f.corkage_payload(byo_bottle_count=3, bottles_purchased_from_list=0,
                              party_size=4, byo_categories=["SPARKLING", "RED"]),
            sommelier_headers(venue_id))

        validate_error(response, ERR_BYO_CATEGORY_PROHIBITED)

    def test_a_permitted_category_over_the_limit_reports_the_limit(self):
        """With no prohibited category in the party's bottles, the bottle limit is the rule that bites.

        "Two policy checks run first: a count above the venue's `byo_bottle_limit_per_party` is refused with `ERR_BYO_LIMIT_EXCEEDED` (HTTP 422), and any category present in the venue's `byo_prohibited_categories` is refused with `ERR_BYO_CATEGORY_PROHIBITED` (HTTP 422)."

        Design: Corner/validations/prohibited_byo_category_beats_byo_bottle_limit
        """
        venue = self._sparkling_prohibiting_venue()
        venue_id = venue["id"]

        response = api_client.quote_corkage(
            venue_id,
            f.corkage_payload(byo_bottle_count=3, bottles_purchased_from_list=0,
                              party_size=4, byo_categories=["RED"]),
            sommelier_headers(venue_id))

        validate_error(response, ERR_BYO_LIMIT_EXCEEDED)

    def test_an_undeclared_category_is_reported_as_an_enum_violation(self):
        """A category outside the six declared members is refused on shape, ahead of either policy rule.

        "Enum-typed fields carry a declared member value — otherwise `ERR_INVALID_ENUM_VALUE` (HTTP 422)."

        Design: Corner/validations/prohibited_byo_category_beats_byo_bottle_limit
        """
        venue = self._sparkling_prohibiting_venue()
        venue_id = venue["id"]

        response = api_client.quote_corkage(
            venue_id,
            f.corkage_payload(byo_bottle_count=1, bottles_purchased_from_list=0,
                              party_size=4, byo_categories=["MERLOT"]),
            sommelier_headers(venue_id))

        validate_error(response, ERR_INVALID_ENUM_VALUE)

    def test_the_legal_quote_waives_both_bottles_and_persists_nothing(self):
        """Four bottles bought at a ratio of two earn two waivers, which cover both outside bottles, and the quote stores nothing.

        "Divide `bottles_purchased_from_list` by the venue's `corkage_waiver_purchase_ratio`, discarding any remainder, to get how many waivers the party has earned; the waived bottles are the smaller of that figure and `byo_bottle_count`."

        Design: Corner/validations/prohibited_byo_category_beats_byo_bottle_limit
        """
        venue = self._sparkling_prohibiting_venue()
        venue_id = venue["id"]

        quote = validate_success(
            api_client.quote_corkage(
                venue_id,
                f.corkage_payload(byo_bottle_count=2,
                                  bottles_purchased_from_list=4,
                                  party_size=4, byo_categories=["RED"]),
                sommelier_headers(venue_id)))

        assert quote["waived_bottles"] == 2
        assert quote["chargeable_bottles"] == 0
        assert quote["corkage_total_cents"] == 0
        assert quote["large_party_discount_applied"] is False
        assert fx.get_venue(venue)["version"] == venue["version"], (
            "quoting corkage persists nothing, so the venue must not be re-versioned")
