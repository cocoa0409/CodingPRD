"""Entity-record corners: persistence, declared defaults, server-minted system
fields, computed-field authority, per-resource not-found errors, the validation
ladder's enum-before-range ordering, the append-only depletion ledger's shape,
parent-before-body foreign-key resolution, and the AllocationClaim junction.

Every test in this file translates exactly one instance of the `entities`
section of SCAFFOLD_CORNER_DESIGN.yaml.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_DUPLICATE_CLAIM,
    ERR_INVALID_ENUM_VALUE,
    ERR_INVALID_REQUEST,
    ERR_LIST_VERSION_NOT_FOUND,
    ERR_LOT_NOT_FOUND,
    ERR_VALUE_OUT_OF_RANGE,
    ERR_WINE_NOT_FOUND,
)
from test_helpers.constants import WINE_CATEGORIES
from test_helpers.test_users import (
    BEVERAGE_DIRECTOR_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    CONTROLLER_HEADERS,
    distributor_rep_headers,
    sommelier_headers,
)

# The six-category COGS map the corner recipes use throughout.
TARGETS = {
    "SPARKLING": 30.0,
    "WHITE": 25.0,
    "ROSE": 28.0,
    "RED": 28.0,
    "DESSERT": 32.0,
    "FORTIFIED": 35.0,
}

# A syntactically valid v4 UUID that names no row in an empty database.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_LIST_VERSION_ID = "00000000-0000-4000-8000-0000000000aa"

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_STAMP = "2026-08-01T00:00:00.000Z"


def _director_venue(**overrides):
    """Register a venue as the director with the recipe's six-category map."""
    payload = {
        "name": "Harbor Room",
        "venue_code": "HRB",
        "cogs_target_pct_by_category": dict(TARGETS),
        "priority_rank": 1,
    }
    payload.update(overrides)
    return validate_success(
        api_client.create_venue(payload, BEVERAGE_DIRECTOR_HEADERS), 201)


def _director_wine(**overrides):
    payload = {
        "producer": "Ridge",
        "cuvee": "Monte Bello",
        "vintage_year": 2019,
        "category": "RED",
        "reference_cost_cents": 2400,
    }
    payload.update(overrides)
    return validate_success(
        api_client.create_wine(payload, BEVERAGE_DIRECTOR_HEADERS), 201)


class TestVenueRegistrationRecord:
    """Registration must persist every declared input field and initialise every
    computed field, and must fall back to the declared defaults when the
    optional policy fields are omitted."""

    def test_venue_creation_persists_every_declared_input_field(self):
        """A venue registered with every optional policy field supplied echoes all of them back unchanged.

        "The commercially significant part of registration is `cogs_target_pct_by_category`, an object whose keys must be exactly the six wine categories the group trades in — `SPARKLING`, `WHITE`, `ROSE`, `RED`, `DESSERT` and `FORTIFIED` — and whose values are each a percentage between 5.0 and 60.0 inclusive."
        "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/entities/venue_creation_persists_every_declared_input_field
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        payload = {
            "name": "Harbor Room",
            "venue_code": "HRB",
            "costing_method": "WEIGHTED_AVERAGE",
            "cogs_target_pct_by_category": dict(TARGETS),
            "event_cogs_target_pct": 26.5,
            "corkage_fee_cents": 4000,
            "corkage_waiver_purchase_ratio": 3,
            "byo_bottle_limit_per_party": 4,
            "byo_prohibited_categories": ["SPARKLING"],
            "priority_rank": 1,
        }
        response = api_client.create_venue(payload, BEVERAGE_DIRECTOR_HEADERS)
        venue = validate_success(response, 201)
        assert response.json()["response_type"] == "object"
        assert response.json()["meta"]["api_request_id"].startswith("req_")

        assertions.assert_common_fields(venue, "Venue")
        assert venue["version"] == 1, "a freshly created venue starts at version 1"
        assertions.assert_fields_equal(venue, {
            "name": "Harbor Room",
            "venue_code": "HRB",
            "costing_method": "WEIGHTED_AVERAGE",
            "corkage_fee_cents": 4000,
            "corkage_waiver_purchase_ratio": 3,
            "byo_bottle_limit_per_party": 4,
            "byo_prohibited_categories": ["SPARKLING"],
            "priority_rank": 1,
        }, "Venue")
        assertions.assert_decimal_equals(venue["event_cogs_target_pct"], 26.5,
                                         "Venue.event_cogs_target_pct")

        targets = venue["cogs_target_pct_by_category"]
        assert sorted(targets.keys()) == sorted(WINE_CATEGORIES), (
            "the stored COGS map must carry exactly the six wine categories, got %r"
            % (sorted(targets.keys()),))
        assertions.assert_decimal_equals(targets["RED"], 28.0, "RED target")
        assertions.assert_decimal_equals(targets["WHITE"], 25.0, "WHITE target")

    def test_venue_creation_initialises_every_computed_field(self):
        """A newly registered venue starts OPEN with a zero variance, a null last run and both ledgers at zero.

        "On creation the venue's `program_posture` starts at `OPEN`, its `last_variance_pct` at 0.00, its `last_pour_cost_run_at` at null, and both `cogs_ledger_cents` and `revenue_ledger_cents` at 0."

        Design: Corner/entities/venue_creation_persists_every_declared_input_field
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        venue = _director_venue(costing_method="WEIGHTED_AVERAGE",
                                event_cogs_target_pct=26.5)

        assert venue["program_posture"] == "OPEN"
        assertions.assert_decimal_equals(venue["last_variance_pct"], 0.00,
                                         "Venue.last_variance_pct")
        assertions.assert_null_fields(venue, "last_pour_cost_run_at")
        assert venue["cogs_ledger_cents"] == 0
        assert venue["revenue_ledger_cents"] == 0


class TestVenuePolicyDefaults:
    """Omitting every optional field must produce the exact declared defaults."""

    @staticmethod
    def _minimal_venue():
        return validate_success(api_client.create_venue({
            "name": "Marina Grill",
            "venue_code": "MAR",
            "cogs_target_pct_by_category": dict(TARGETS),
        }, BEVERAGE_DIRECTOR_HEADERS), 201)

    def test_venue_costing_pricing_and_queue_fields_take_declared_defaults(self):
        """A venue registered with only the required fields costs FIFO, targets 30.0 for events and queues at rank 3.

        "`costing_method` defaults to `FIFO` and may instead be `WEIGHTED_AVERAGE`; Section 3.7 explains what each choice does to the numbers."
        "A separate `event_cogs_target_pct`, defaulting to 30.0 and likewise bounded to 5.0 through 60.0, is used for wine-dinner ticket pricing instead of the per-category targets."
        "Finally `priority_rank`, an integer from 1 to 5 defaulting to 3 where a lower number means higher priority, is the venue's standing in the allocation queue and appears again in Section 3.3."

        Design: Corner/entities/venue_optional_policy_fields_apply_declared_defaults
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        venue = self._minimal_venue()

        assert venue["costing_method"] == "FIFO"
        assertions.assert_decimal_equals(venue["event_cogs_target_pct"], 30.0,
                                         "Venue.event_cogs_target_pct")
        assert venue["priority_rank"] == 3

    def test_venue_corkage_policy_fields_take_declared_defaults(self):
        """The four corkage policy fields default to 3500 cents, a ratio of 2, a limit of 2 and an empty prohibition list.

        "Four fields configure the venue's corkage policy and are quoted, never charged, by the corkage capability described in Section 3.9: `corkage_fee_cents` is the per-bottle fee before any waiver or discount and defaults to 3500 (that is, thirty-five dollars) with 0 permitted; `corkage_waiver_purchase_ratio` is how many bottles a party must buy off the list to earn one corkage waiver and defaults to 2, with a minimum of 1; `byo_bottle_limit_per_party` caps how many outside bottles one party may bring and defaults to 2, with 0 permitted; and `byo_prohibited_categories` is a possibly empty array — the default — of wine categories the venue simply refuses."

        Design: Corner/entities/venue_optional_policy_fields_apply_declared_defaults
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        venue = self._minimal_venue()

        assertions.assert_fields_equal(venue, {
            "corkage_fee_cents": 3500,
            "corkage_waiver_purchase_ratio": 2,
            "byo_bottle_limit_per_party": 2,
            "byo_prohibited_categories": [],
        }, "Venue")


class TestVenueSystemFields:
    """id, created_at, updated_at, version and the derived posture are all
    server-minted and can never be seeded from the request body."""

    def test_venue_creation_ignores_client_supplied_system_fields(self):
        """A create payload carrying its own id, created_at, version and posture is ignored in favour of server-minted values.

        "Every resource carries a server-minted `id`: a UUID string with no type prefix, never supplied by the client."
        "All resources except the depletion ledger additionally carry `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that resource."
        "Each venue carries a derived gate called `program_posture`, taking one of `OPEN`, `RESTRICTED` or `FROZEN`, and initialised to `OPEN` when the venue is registered."

        Design: Corner/entities/venue_system_fields_server_minted_extra_field_ignored
        """
        fixtures.set_clock("2026-08-15T09:30:00Z")
        seeded_id = "11111111-1111-4111-8111-111111111111"
        venue = validate_success(api_client.create_venue({
            "name": "Cliff House",
            "venue_code": "CLF",
            "cogs_target_pct_by_category": dict(TARGETS),
            "id": seeded_id,
            "created_at": "2020-01-01T00:00:00.000Z",
            "version": 47,
            "program_posture": "FROZEN",
        }, BEVERAGE_DIRECTOR_HEADERS), 201)

        assertions.assert_common_fields(venue, "Venue")
        assert venue["id"] != seeded_id, (
            "the server must mint a fresh id rather than honour the submitted one")
        assert venue["created_at"] == "2026-08-15T09:30:00.000Z", (
            "created_at must be the logical clock, not the submitted string")
        assert venue["updated_at"] == venue["created_at"]
        assert venue["version"] == 1, "version starts at 1, never at the submitted 47"
        assert venue["program_posture"] == "OPEN", (
            "a computed field is never seeded from input")


class TestWineCatalogueRecord:
    """The catalogue read path returns persisted state, and the create path
    enforces required fields before enum membership and numeric range."""

    def test_wine_retrieval_returns_stored_representation_with_defaults(self):
        """Reading a wine by id returns exactly what creation stored, including every catalogue default.

        "A wine record carries a `producer` and a `cuvee` (each 1 to 120 characters), a `vintage_year` between 1900 and 2100, a `category` drawn from the six above, a `bottle_size_ml` between 187 and 6000 defaulting to 750, a `reference_cost_cents` of at least 1, a `case_pack` between 1 and 24 defaulting to 6, and a boolean `is_allocated` defaulting to false."
        "Each row also carries `successor_count`, starting at 0 and counting how many catalogue rows name this one as their predecessor."

        Design: Corner/entities/wine_retrieval_returns_stored_representation_with_defaults
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        created = _director_wine()

        wine = validate_success(
            api_client.get_wine(created["id"], BEVERAGE_DIRECTOR_HEADERS))

        assertions.assert_common_fields(wine, "Wine")
        assertions.assert_fields_equal(wine, {
            "producer": "Ridge",
            "cuvee": "Monte Bello",
            "vintage_year": 2019,
            "category": "RED",
            "reference_cost_cents": 2400,
            "bottle_size_ml": 750,
            "case_pack": 6,
            "is_allocated": False,
            "successor_count": 0,
        }, "Wine")
        assertions.assert_null_fields(wine, "predecessor_wine_id")
        assert wine["version"] == 1
        assert wine["created_at"] == DEFAULT_CLOCK_STAMP, (
            "created_at is minted from the logical clock")
        assert wine == created, (
            "the read must return the stored row, not a partial projection: "
            "created=%r read=%r" % (created, wine))

    def test_wine_creation_missing_required_producer_returns_invalid_request(self):
        """Omitting the required producer is a 400 ERR_INVALID_REQUEST and writes no catalogue row.

        "Required body fields are present and carry the declared JSON type — otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/wine_creation_missing_required_producer_returns_invalid_request
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        response = api_client.create_wine({
            "cuvee": "Monte Bello",
            "vintage_year": 2019,
            "category": "RED",
            "reference_cost_cents": 2400,
        }, BEVERAGE_DIRECTOR_HEADERS)
        validate_error(response, ERR_INVALID_REQUEST)

        _rows, meta = validate_paginated(
            api_client.list_wines(BEVERAGE_DIRECTOR_HEADERS))
        assert meta["total_count"] == 0, (
            "a refused create must leave the catalogue empty")

    def test_wine_category_outside_enum_rejected(self):
        """A category outside the six wine categories is refused with ERR_INVALID_ENUM_VALUE.

        "Enum-typed fields carry a declared member value — otherwise `ERR_INVALID_ENUM_VALUE` (HTTP 422)."

        Design: Corner/entities/wine_category_outside_enum_rejected
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        response = api_client.create_wine({
            "producer": "Ridge",
            "cuvee": "Orange Experiment",
            "vintage_year": 2019,
            "category": "ORANGE",
            "reference_cost_cents": 2400,
        }, BEVERAGE_DIRECTOR_HEADERS)
        validate_error(response, ERR_INVALID_ENUM_VALUE)

        _rows, meta = validate_paginated(
            api_client.list_wines(BEVERAGE_DIRECTOR_HEADERS))
        assert meta["total_count"] == 0

    def test_wine_vintage_year_below_range_rejected(self):
        """A vintage_year of 1800 sits outside the declared 1900 to 2100 range and is refused with ERR_VALUE_OUT_OF_RANGE.

        "Numeric fields respect their declared ranges — otherwise `ERR_VALUE_OUT_OF_RANGE` (HTTP 422)."

        Design: Corner/entities/wine_category_outside_enum_rejected
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        response = api_client.create_wine({
            "producer": "Ridge",
            "cuvee": "Monte Bello",
            "vintage_year": 1800,
            "category": "RED",
            "reference_cost_cents": 2400,
        }, BEVERAGE_DIRECTOR_HEADERS)
        validate_error(response, ERR_VALUE_OUT_OF_RANGE)

        _rows, meta = validate_paginated(
            api_client.list_wines(BEVERAGE_DIRECTOR_HEADERS))
        assert meta["total_count"] == 0

    def test_enum_check_precedes_range_check_when_both_are_violated(self):
        """A payload breaking both the category enum and the vintage range reports the enum failure, which sits earlier in the ladder.

        "Checks are evaluated strictly in the following sequence, and the first failure is the one reported:"

        Design: Corner/entities/wine_category_outside_enum_rejected
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        response = api_client.create_wine({
            "producer": "Ridge",
            "cuvee": "Monte Bello",
            "vintage_year": 1800,
            "category": "ORANGE",
            "reference_cost_cents": 2400,
        }, BEVERAGE_DIRECTOR_HEADERS)
        validate_error(response, ERR_INVALID_ENUM_VALUE)

        _rows, meta = validate_paginated(
            api_client.list_wines(BEVERAGE_DIRECTOR_HEADERS))
        assert meta["total_count"] == 0


class TestCellarBinListing:
    """The bin collection is a paginated array envelope whose filter is applied
    before the page window."""

    @staticmethod
    def _two_venues_with_bins():
        """Venue HRB with bins A1, A2, A3 plus venue MAR with bin B1.

        The clock is advanced an hour between bin creates so that the declared
        `created_at` ascending order is well defined rather than a tie.
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        harbor = _director_venue()
        marina = _director_venue(name="Marina Grill", venue_code="MAR",
                                 priority_rank=2)
        bins = []
        for index, code in enumerate(["A1", "A2", "A3"], start=1):
            fixtures.set_clock("2026-08-01T0%d:00:00Z" % index)
            bins.append(validate_success(api_client.create_cellar_bin(
                harbor["id"],
                {"bin_code": code, "zone": "CELLAR", "capacity_bottles": 48,
                 "temperature_controlled": True},
                sommelier_headers(harbor["id"])), 201))
        fixtures.set_clock("2026-08-01T04:00:00Z")
        other_bin = validate_success(api_client.create_cellar_bin(
            marina["id"],
            {"bin_code": "B1", "zone": "CELLAR", "capacity_bottles": 24,
             "temperature_controlled": True},
            sommelier_headers(marina["id"])), 201)
        return harbor, bins, other_bin

    def test_cellar_bin_listing_returns_pagination_envelope_and_declared_order(self):
        """Three bins read two at a time come back oldest first with total_count 3 and has_more true on the first page only.

        "Unless a specific collection states otherwise in Section 3, list results are ordered by `created_at` ascending."
        "`total_count` is the number of records matching the filters before pagination is applied, and `has_more` is true when records beyond the current page remain."

        Design: Corner/entities/cellar_bin_listing_returns_pagination_envelope_and_declared_order
        """
        harbor, bins, other_bin = self._two_venues_with_bins()
        bin_a1, bin_a2, bin_a3 = bins

        first = api_client.list_cellar_bins(
            BEVERAGE_DIRECTOR_HEADERS,
            params={"venue_id": harbor["id"], "limit": 2, "offset": 0})
        page1, meta1 = validate_paginated(first)
        assert first.json()["response_type"] == "array"
        assert [row["id"] for row in page1] == [bin_a1["id"], bin_a2["id"]]
        assert (meta1["limit"], meta1["offset"]) == (2, 0)
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        for row in page1:
            assertions.assert_common_fields(row, "CellarBin")

        page2, meta2 = validate_paginated(api_client.list_cellar_bins(
            BEVERAGE_DIRECTOR_HEADERS,
            params={"venue_id": harbor["id"], "limit": 2, "offset": 2}))
        assert [row["id"] for row in page2] == [bin_a3["id"]]
        assert (meta2["limit"], meta2["offset"]) == (2, 2)
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        seen = {row["id"] for row in page1} | {row["id"] for row in page2}
        assert other_bin["id"] not in seen, (
            "the venue_id filter must exclude the other venue's bin")

    def test_cellar_bin_listing_without_limit_uses_the_default_page_size(self):
        """An unfiltered, unpaged read of four bins returns all of them under the default limit of 10.

        "`limit` controls page size: it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100."

        Design: Corner/entities/cellar_bin_listing_returns_pagination_envelope_and_declared_order
        """
        _harbor, bins, other_bin = self._two_venues_with_bins()

        rows, meta = validate_paginated(
            api_client.list_cellar_bins(BEVERAGE_DIRECTOR_HEADERS))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 4
        assert meta["has_more"] is False
        expected = {row["id"] for row in bins} | {other_bin["id"]}
        assert {row["id"] for row in rows} == expected


class TestInventoryLotRetrieval:
    """An unknown lot id on the path produces the lot-specific 404."""

    def test_inventory_lot_get_with_unknown_id_returns_lot_not_found(self):
        """A valid but unknown UUID on the lot read path is a 404 ERR_LOT_NOT_FOUND, not a generic bad request.

        "The not-found catalogue is per resource type: `ERR_VENUE_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_WINE_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DEPLETION_ENTRY_NOT_FOUND`, `ERR_WINE_LIST_NOT_FOUND`, `ERR_LIST_VERSION_NOT_FOUND`, `ERR_LIST_ENTRY_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_WRITE_OFF_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` and `ERR_INVESTIGATION_NOT_FOUND` — each HTTP 404."

        Design: Corner/entities/inventory_lot_get_with_unknown_id_returns_lot_not_found
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        response = api_client.get_inventory_lot(UNKNOWN_UUID,
                                                BEVERAGE_DIRECTOR_HEADERS)
        error = validate_error(response, ERR_LOT_NOT_FOUND)

        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(error["message"], str) and error["message"], (
            "the error envelope must carry a human-readable message")
        assert body["meta"]["api_request_id"].startswith("req_")


def _draft_version_setup():
    """Venue HRB (RED target 28.0), one RED wine at 2400 cents, and a DRAFT
    ListVersion on the venue's wine list."""
    fixtures.set_clock(DEFAULT_CLOCK)
    venue = _director_venue()
    wine = _director_wine(bottle_size_ml=750, case_pack=6, is_allocated=False)
    headers = sommelier_headers(venue["id"])
    wine_list = validate_success(api_client.create_wine_list(
        venue["id"], {"name": "Dinner List"}, headers), 201)
    version = validate_success(api_client.create_list_version(
        wine_list["id"], {}, headers), 201)
    return venue, wine, version


class TestListEntryComputedFields:
    """bottle_price_cents, price_band, glass_price_cents, effective_pours and
    contest_points are computed by the server; client-supplied values for them
    are ignored."""

    @staticmethod
    def _entry_with_bogus_computed_inputs(venue, wine, version):
        return validate_success(api_client.create_list_entry(version["id"], {
            "wine_id": wine["id"],
            "sort_rank": 1,
            "expected_list_version_version": version["version"],
            "by_the_glass": False,
            "par_bottles": 6,
            "education_verified": False,
            "bottle_price_cents": 100,
            "price_band": "RESERVE",
            "contest_points": 999,
        }, sommelier_headers(venue["id"])), 201)

    def test_list_entry_bottle_price_is_computed_not_taken_from_the_body(self):
        """A 2400-cent RED wine on a 28.0 target prices at 8600 cents in the CORE band whatever the body claims.

        "The bottle price is derived from the wine's catalogue cost in a fixed sequence, and it is frozen onto the entry as `bottle_price_cents` at creation."
        "Independently, take the venue's target percentage for this wine's category out of `cogs_target_pct_by_category`, multiply the cost by 100, divide by that percentage and round half up to whole cents; call this the target candidate."
        "That price then fixes the entry's `price_band`: `VALUE` at 6000 cents or below, `CORE` above 6000 and at most 12000, `PREMIUM` above 12000 and at most 25000, and `RESERVE` above 25000."

        Design: Corner/entities/list_entry_computed_price_fields_input_ignored
        """
        venue, wine, version = _draft_version_setup()
        entry = self._entry_with_bogus_computed_inputs(venue, wine, version)

        assertions.assert_common_fields(entry, "ListEntry")
        assert entry["bottle_price_cents"] == 8600, (
            "markup candidate 2400*3.00 = 7200 loses to the target candidate "
            "round_half_up(2400*100/28.0) = 8571, which lifts to the next dollar")
        assert entry["price_band"] == "CORE", (
            "8600 cents sits above 6000 and at or below 12000, not in RESERVE")

    def test_list_entry_glass_fields_and_contest_points_are_server_computed(self):
        """A bottle-only entry carries null glass fields and a contest score of 0.00, never the submitted 999.

        "When `by_the_glass` is false, both `effective_pours` and `glass_price_cents` are null."
        "And `contest_points` is computed from the ledger, which for a brand-new entry means a score of 0.00 unless staff education has already been signed off."

        Design: Corner/entities/list_entry_computed_price_fields_input_ignored
        """
        venue, wine, version = _draft_version_setup()
        entry = self._entry_with_bogus_computed_inputs(venue, wine, version)

        assertions.assert_null_fields(entry, "effective_pours", "glass_price_cents")
        assertions.assert_decimal_equals(entry["contest_points"], 0.00,
                                         "ListEntry.contest_points")


class TestListEntryParentResolution:
    """The path parent is resolved before the body's own foreign keys."""

    def test_list_entry_creation_under_unknown_list_version_returns_not_found(self):
        """Adding an entry under an unknown list version is a 404 ERR_LIST_VERSION_NOT_FOUND and writes nothing.

        "Path identifiers are resolved left to right."
        "Foreign keys carried in a request body are resolved after all path identifiers, in the order the body fields are listed for that operation."

        Design: Corner/entities/list_entry_creation_under_unknown_list_version_returns_not_found
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        venue = _director_venue()
        wine = _director_wine()

        response = api_client.create_list_entry(UNKNOWN_LIST_VERSION_ID, {
            "wine_id": wine["id"],
            "sort_rank": 1,
            "expected_list_version_version": 1,
        }, sommelier_headers(venue["id"]))
        validate_error(response, ERR_LIST_VERSION_NOT_FOUND)

        _rows, meta = validate_paginated(
            api_client.list_list_entries(BEVERAGE_DIRECTOR_HEADERS))
        assert meta["total_count"] == 0, (
            "a refused create must leave the entry collection empty")

    def test_list_entry_creation_with_unknown_wine_returns_wine_not_found(self):
        """Once the path version resolves, an unknown wine_id in the body is reported as ERR_WINE_NOT_FOUND.

        "Foreign keys carried in a request body are resolved after all path identifiers, in the order the body fields are listed for that operation."

        Design: Corner/entities/list_entry_creation_under_unknown_list_version_returns_not_found
        """
        venue, _wine, version = _draft_version_setup()

        response = api_client.create_list_entry(version["id"], {
            "wine_id": UNKNOWN_UUID,
            "sort_rank": 1,
            "expected_list_version_version": version["version"],
        }, sommelier_headers(venue["id"]))
        validate_error(response, ERR_WINE_NOT_FOUND)

        _rows, meta = validate_paginated(
            api_client.list_list_entries(BEVERAGE_DIRECTOR_HEADERS))
        assert meta["total_count"] == 0


def _closed_slot_ledger_setup():
    """Mint one ledger row the cheapest declared way: publish a by-the-glass
    listing, open a rail slot on a 12-bottle lot and close it having sold every
    saleable pour."""
    fixtures.set_clock("2026-09-01T12:00:00Z")
    venue = _director_venue()
    headers = sommelier_headers(venue["id"])
    bin_ = validate_success(api_client.create_cellar_bin(
        venue["id"],
        {"bin_code": "A1", "zone": "CELLAR", "capacity_bottles": 48,
         "temperature_controlled": True}, headers), 201)
    wine = _director_wine(bottle_size_ml=750, case_pack=6, is_allocated=False)
    lot = validate_success(api_client.create_inventory_lot({
        "venue_id": venue["id"],
        "wine_id": wine["id"],
        "bin_id": bin_["id"],
        "bottles_received": 12,
        "unit_cost_cents": 2400,
        "received_at": "2026-08-10T00:00:00Z",
    }, headers), 201)
    wine_list = validate_success(api_client.create_wine_list(
        venue["id"], {"name": "Dinner List"}, headers), 201)
    version = validate_success(api_client.create_list_version(
        wine_list["id"], {}, headers), 201)
    entry = validate_success(api_client.create_list_entry(version["id"], {
        "wine_id": wine["id"],
        "sort_rank": 1,
        "expected_list_version_version": version["version"],
        "by_the_glass": True,
        "pour_size_ml": 177,
        "par_bottles": 6,
        "education_verified": False,
    }, headers), 201)
    validate_success(api_client.submit_list_version(version["id"], headers))
    validate_success(api_client.publish_list_version(version["id"],
                                                    BEVERAGE_DIRECTOR_HEADERS))
    slot = validate_success(api_client.create_btg_slot({
        "venue_id": venue["id"],
        "list_entry_id": entry["id"],
        "lot_id": lot["id"],
        "slot_index": 1,
        "preservation_method": "ARGON",
    }, headers), 201)
    validate_success(api_client.close_btg_slot(slot["id"], {"pours_sold": 3},
                                               headers))
    return {"venue": venue, "wine": wine, "lot": lot, "entry": entry,
            "slot": slot}


class TestDepletionEntryImmutability:
    """A DepletionEntry is an immutable event, not a resource: it carries id and
    created_at and nothing that implies mutation."""

    def test_depletion_entry_carries_no_updated_at_and_no_version(self):
        """The ledger row a slot close writes exposes id and created_at but neither updated_at nor version.

        "Ledger entries are immutable events, not resources: a depletion entry carries only `id` and `created_at`."
        "It has no `updated_at` and no `version`, because it is never modified after it is written."

        Design: Corner/entities/depletion_entry_immutability_no_update_endpoint_and_no_version_field
        """
        chain = _closed_slot_ledger_setup()

        rows, meta = validate_paginated(api_client.list_depletion_entries(
            CONTROLLER_HEADERS, params={"btg_slot_id": chain["slot"]["id"]}))
        assert meta["total_count"] == 1, (
            "selling every saleable pour leaves only the SALE_BTG bucket, so the "
            "close writes exactly one entry")
        listed = rows[0]
        assertions.assert_append_only_fields(listed)

        fetched = validate_success(
            api_client.get_depletion_entry(listed["id"], CONTROLLER_HEADERS))
        assertions.assert_append_only_fields(fetched)
        assertions.assert_entry_unchanged(listed, fetched, "DepletionEntry")

    def test_depletion_entry_records_the_slot_closure_sale_row(self):
        """The single closure row is a SALE_BTG movement of one bottle and three pours worth 2400 cents of cost and 8625 cents of revenue.

        "The sale entry carries reason `SALE_BTG`, the whole-bottle movement of 1 in its `bottles`, `pours` equal to `pours_sold`, the sale bucket's cost and the computed revenue."
        "Every deadline comparison, every preservation expiry, every occupancy interval, and every timestamp the server mints — `opened_at`, `published_at`, `printed_at`, `allocated_at`, `resolved_at`, `last_pour_cost_run_at`, `occurred_at` — is taken from this logical clock."

        Design: Corner/entities/depletion_entry_immutability_no_update_endpoint_and_no_version_field
        """
        chain = _closed_slot_ledger_setup()

        rows, _meta = validate_paginated(api_client.list_depletion_entries(
            CONTROLLER_HEADERS, params={"btg_slot_id": chain["slot"]["id"]}))
        assert len(rows) == 1
        entry = rows[0]

        assertions.assert_fields_equal(entry, {
            "reason": "SALE_BTG",
            "bottles": 1,
            "pours": 3,
            "cogs_cents": 2400,
            "revenue_cents": 8625,
            "venue_id": chain["venue"]["id"],
            "wine_id": chain["wine"]["id"],
            "lot_id": chain["lot"]["id"],
            "list_entry_id": chain["entry"]["id"],
            "btg_slot_id": chain["slot"]["id"],
        }, "DepletionEntry")
        assert entry["occurred_at"] == "2026-09-01T12:00:00.000Z", (
            "occurred_at is the logical clock at close time")


def _two_offers_two_venues():
    """Two venues, one CLEARED distributor and one 6-bottle offer per wine."""
    fixtures.set_clock(DEFAULT_CLOCK)
    harbor = _director_venue()
    marina = _director_venue(name="Marina Grill", venue_code="MAR",
                             priority_rank=2)
    distributor = validate_success(api_client.create_distributor({
        "name": "Coastal Selections",
        "license_number": "LIC-88120",
        "allocation_tier": "A",
        "on_time_delivery_pct": 96.5,
    }, BEVERAGE_DIRECTOR_HEADERS), 201)
    validate_success(api_client.create_compliance_review(
        distributor["id"], {"decision": "CLEARED", "note": "Licence verified."},
        COMPLIANCE_OFFICER_HEADERS))
    rep = distributor_rep_headers(distributor["id"])
    offers = []
    for cuvee in ["Monte Bello", "Geyserville"]:
        wine = _director_wine(cuvee=cuvee, bottle_size_ml=750, case_pack=6,
                              is_allocated=True)
        offers.append(validate_success(api_client.create_allocation_offer({
            "distributor_id": distributor["id"],
            "wine_id": wine["id"],
            "offered_bottles": 6,
            "unit_cost_cents": 4500,
            "response_deadline": "2026-09-30T00:00:00Z",
        }, rep), 201))
    return harbor, marina, offers[0], offers[1]


def _live_offer_version(offer_id):
    return validate_success(
        api_client.get_allocation_offer(offer_id, BEVERAGE_DIRECTOR_HEADERS)
    )["version"]


def _file_claim(offer_id, venue_id, requested_bottles):
    return api_client.create_allocation_claim(offer_id, {
        "venue_id": venue_id,
        "requested_bottles": requested_bottles,
        "expected_offer_version": _live_offer_version(offer_id),
    }, sommelier_headers(venue_id))


class TestAllocationClaimJunction:
    """AllocationClaim is the many-to-many junction between Venue and
    AllocationOffer, and both traversal directions are filterable."""

    def test_allocation_claim_junction_links_offer_and_venue_in_graph_topology(self):
        """Two venues may claim one offer and one venue may claim two offers, and both traversals are reachable from the filtered claim list.

        "A successful claim is created in state `REQUESTED` with `granted_bottles` 0, `raw_share` 0.0000 and `remainder_awarded` false, and it increments the parent offer's `claim_count` by 1 and the offer's `version` by 1 — which is precisely why the next claimant's guard value must be re-read."
        "Claims may be listed filtered by `offer_id`, by `venue_id` and by `state`; the single-claim read exposes `granted_bottles` and `raw_share`."

        Design: Corner/entities/allocation_claim_junction_links_offer_and_venue_in_graph_topology
        """
        harbor, marina, offer_one, offer_two = _two_offers_two_venues()

        claim_one = validate_success(
            _file_claim(offer_one["id"], harbor["id"], 3), 201)
        claim_two = validate_success(
            _file_claim(offer_one["id"], marina["id"], 3), 201)
        claim_three = validate_success(
            _file_claim(offer_two["id"], harbor["id"], 6), 201)

        for claim in (claim_one, claim_two, claim_three):
            assertions.assert_common_fields(claim, "AllocationClaim")
            assert claim["state"] == "REQUESTED"

        offer = validate_success(api_client.get_allocation_offer(
            offer_one["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert offer["claim_count"] == 2
        assert offer["unallocated_bottles"] == 6, (
            "nothing is awarded until the waterfall runs")

        by_offer, meta_offer = validate_paginated(
            api_client.list_allocation_claims(
                BEVERAGE_DIRECTOR_HEADERS, params={"offer_id": offer_one["id"]}))
        assert meta_offer["total_count"] == 2
        assert {row["id"] for row in by_offer} == {claim_one["id"], claim_two["id"]}

        by_venue, meta_venue = validate_paginated(
            api_client.list_allocation_claims(
                BEVERAGE_DIRECTOR_HEADERS, params={"venue_id": harbor["id"]}))
        assert meta_venue["total_count"] == 2
        assert {row["id"] for row in by_venue} == {claim_one["id"], claim_three["id"]}

    def test_second_claim_on_the_same_offer_and_venue_pair_is_a_duplicate(self):
        """A venue that already holds a claim on an offer cannot file a second one against it.

        "A claim is refused when the offer's fulfilment dimension is anything other than `OPEN` (`ERR_OFFER_NOT_OPEN`, HTTP 409); when this venue already holds a claim on this offer in *any* state, including a withdrawn or rejected one (`ERR_DUPLICATE_CLAIM`, HTTP 409); when `requested_bottles` exceeds the offer's `offered_bottles` (`ERR_REQUEST_EXCEEDS_OFFER`, HTTP 422); when the logical clock has reached or passed the offer's `response_deadline`, so that only an instant strictly earlier than the deadline is accepted (`ERR_OFFER_DEADLINE_PASSED`, HTTP 422); and when the distributor behind the offer stands in `HOLD` (`ERR_DISTRIBUTOR_COMPLIANCE_HOLD`, HTTP 422)."

        Design: Corner/entities/allocation_claim_junction_links_offer_and_venue_in_graph_topology
        """
        harbor, marina, offer_one, offer_two = _two_offers_two_venues()

        validate_success(_file_claim(offer_one["id"], harbor["id"], 3), 201)
        validate_success(_file_claim(offer_one["id"], marina["id"], 3), 201)
        validate_success(_file_claim(offer_two["id"], harbor["id"], 6), 201)

        # Same (offer, venue) pair a second time, on a freshly read version so
        # the OCC guard of Section 2.7 cannot be what refuses the call.
        validate_error(_file_claim(offer_one["id"], harbor["id"], 1),
                       ERR_DUPLICATE_CLAIM)

        _rows, meta = validate_paginated(api_client.list_allocation_claims(
            BEVERAGE_DIRECTOR_HEADERS, params={"offer_id": offer_one["id"]}))
        assert meta["total_count"] == 2, (
            "the refused duplicate must not create a third claim on the offer")
