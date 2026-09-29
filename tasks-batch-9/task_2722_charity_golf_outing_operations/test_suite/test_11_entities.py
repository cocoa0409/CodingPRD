"""Envelope shape, stored-row reads, declared defaults and server-minted fields."""

import pytest

from test_helpers import (
    CLOCK_START_UTC,
    COURSE_HEADERS,
    DEFAULT_CANCELLATION_NOTICE_DAYS,
    DEFAULT_CART_ALLOWANCE_COUNT,
    DEFAULT_COURSE_RATING,
    DEFAULT_FNB_MINIMUM_CENTS,
    DEFAULT_FNB_PER_PLAYER_CENTS,
    DEFAULT_GUARANTEED_PLAYER_COUNT,
    DEFAULT_PAR,
    DEFAULT_RAIN_DATE_CREDIT_PCT,
    DEFAULT_RAIN_DATE_TERMS,
    DEFAULT_SLOPE_RATING,
    DEFAULT_TEE_INTERVAL_MINUTES,
    DIRECTOR_HEADERS,
    NON_EXISTENT_UUID,
    SPONSORSHIP_HEADERS,
    TREASURER_HEADERS,
    TREASURER_USER_ID,
    ApiErrorId,
    assert_instant_equals,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ENVELOPE_OUTING = {
    "name": "Envelope Open",
    "format": "SCRAMBLE",
    "field_capacity_teams": 20,
    "prize_pool_cents": 250000,
}
ROLLUP_FIELDS = (
    "gross_revenue_cents",
    "refunded_cents",
    "course_charge_cents",
    "fnb_shortfall_cents",
    "insurance_cost_cents",
    "prize_cost_cents",
    "fulfillment_credit_cents",
    "direct_costs_cents",
    "net_proceeds_before_fee_cents",
    "admin_fee_cents",
    "net_proceeds_cents",
    "unclaimed_prize_cents",
    "receipted_deductible_total_cents",
)
COUNTER_FIELDS = (
    "reopen_count",
    "confirmed_player_slots",
    "checked_in_player_count",
    "waitlisted_registration_count",
    "reserved_asset_slot_count",
)


class TestCreateOuting:
    def test_the_success_envelope_carries_the_row_with_every_default_materialised(self, api):
        """A creation answers 201 and the body reports the initial posture in full.

        The envelope is fixed: `api_request_id` is "a server-generated unique
        identifier for the request that starts with `req_`" and
        `api_request_timestamp` is "a server-generated ISO 8601 UTC timestamp with
        three fractional digits".  The identifier is "a server-minted UUID. It
        carries no type prefix and clients never supply it." and `version` is "a
        counter that starts at 1 and is incremented by exactly 1 on every accepted
        mutation of that row".

        "A freshly created outing sits at `DRAFT` on its play dimension and
        `COLLECTING` on its finance dimension."  Every rollup figure "is initialised
        to 0, as are the operational counters `reopen_count`,
        `confirmed_player_slots`, `checked_in_player_count`,
        `waitlisted_registration_count`, and `reserved_asset_slot_count`", "The
        `proceeds_variant` marker is initialised to `PROVISIONAL`", and of the rain
        date and the wave B window, "all three optional inputs default to null when
        omitted".

        Design: Corner/entities/create_outing_returns_201_with_success_envelope_and_system_fields
        """
        fx.set_clock(api, CLOCK_START_UTC)

        response = api.create_outing(f.outing_payload(**ENVELOPE_OUTING), DIRECTOR_HEADERS)
        assert response.status_code == 201
        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

        data = validate_success(response, 201)
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1
        assert_instant_equals(data["created_at"], CLOCK_START_UTC)
        assert data["updated_at"] == data["created_at"]

        assert data["play_status"] == "DRAFT"
        assert data["finance_status"] == "COLLECTING"
        assert data["proceeds_variant"] == "PROVISIONAL"
        for field in ROLLUP_FIELDS + COUNTER_FIELDS:
            assert data[field] == 0, f"{field} should start at 0"
        assert data["rain_date"] is None
        assert data["wave_b_start"] is None
        assert data["wave_b_end"] is None


PLATINUM_TIER = {
    "code": "PLATINUM",
    "price_cents": 500000,
    "player_slots": 4,
    "gsv_cents": 24000,
    "inventory_cap": 2,
    "entitled_asset_type": "CONTEST",
    "entitled_asset_count": 1,
}


class TestReadPackageTier:
    def test_the_single_resource_read_echoes_the_written_row_and_a_zero_sold_count(self, api):
        """Nobody has bought the tier yet, so its live counter reads 0.

        A tier declares "the `kind` of registration it sells (`TEAM`, `INDIVIDUAL`,
        or `SPONSOR`), its `price_cents`, and the number of `player_slots` it
        includes, which must be between 0 and 4 inclusive", and the read is
        documented as "Read one package tier including its live sold_count."  That
        counter is a derivation: "Each tier also exposes a live `sold_count`: the
        number of registrations currently holding it whose status is `CONFIRMED`,
        `AMENDED`, or `CHECKED_IN`."

        Design: Corner/entities/read_package_tier_returns_the_stored_row
        """
        fx.set_clock(api, CLOCK_START_UTC)
        outing = fx.new_outing(api, name="Read Back Open", format="BEST_BALL",
                               field_capacity_teams=10)
        tier = fx.new_sponsor_tier(api, outing["id"], **PLATINUM_TIER)

        data = validate_success(api.get_package_tier(tier["id"], SPONSORSHIP_HEADERS))
        assert data["id"] == tier["id"]
        assert data["outing_id"] == outing["id"]
        assert data["code"] == "PLATINUM"
        assert data["kind"] == "SPONSOR"
        assert data["price_cents"] == 500000
        assert data["player_slots"] == 4
        assert data["gsv_cents"] == 24000
        assert data["inventory_cap"] == 2
        assert data["entitled_asset_type"] == "CONTEST"
        assert data["entitled_asset_count"] == 1
        assert data["sold_count"] == 0


PAGE_ONE_OUTING = {"name": "Page One Open", "field_capacity_teams": 20}
PAGE_TWO_OUTING = {
    "name": "Page Two Open",
    "beneficiary_name": "Southside Literacy Trust",
    "field_capacity_teams": 20,
    "scheduled_date": "2026-09-26T12:00:00Z",
    "wave_a_start": "2026-09-26T12:00:00Z",
    "wave_a_end": "2026-09-26T16:30:00Z",
}
PAGE_TWO_CONTRACT = {"course_name": "Birch Hollow GC", "rate_per_player_cents": 8000}
BIG_TEAM_TIER = {"inventory_cap": 50}
OTHER_TEAM_TIER = {"price_cents": 100000, "gsv_cents": 20000, "inventory_cap": 50}


class TestListRegistrations:
    def test_the_outing_filter_is_applied_before_the_window_and_total_count_counts_matches(
        self, api
    ):
        """Three rows on one outing, a fourth on another, and a window of two.

        The count is defined against the filter rather than the page:
        "`total_count` is the number of rows matching the filters before the window
        is applied, and `has_more` is true exactly when rows remain beyond the
        returned window."  Ordering is the default one, since "list results are
        ordered by the resource's `created_at` timestamp in ascending order".

        Design: Corner/entities/list_registrations_filtered_by_outing_paginates_with_total_count
        """
        first = fx.open_outing(api, outing=PAGE_ONE_OUTING, tier=BIG_TEAM_TIER)
        wanted = [
            fx.new_registration(api, first["outing_id"], first["tier_id"], buyer_name=name)["id"]
            for name in ("Buyer One", "Buyer Two", "Buyer Three")
        ]
        second = fx.open_outing(
            api,
            clock=None,
            outing=PAGE_TWO_OUTING,
            contract=PAGE_TWO_CONTRACT,
            tier=OTHER_TEAM_TIER,
        )
        elsewhere = fx.new_registration(
            api, second["outing_id"], second["tier_id"], buyer_name="Other Outing Buyer"
        )

        response = api.list_registrations(
            TREASURER_HEADERS, outing_id=first["outing_id"], limit=2, offset=0
        )
        page_one, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array"
        assert len(page_one) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

        page_two, meta_two = validate_paginated(
            api.list_registrations(
                TREASURER_HEADERS, outing_id=first["outing_id"], limit=2, offset=2
            )
        )
        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert meta_two["offset"] == 2

        returned = [row["id"] for row in page_one + page_two]
        assert returned == wanted
        assert elsewhere["id"] not in returned
        stamps = [row["created_at"] for row in page_one + page_two]
        assert stamps == sorted(stamps)


class TestReadTeamNotFound:
    def test_an_unknown_team_uuid_reports_the_team_family_at_404(self, api):
        """The path tier names the family that is missing, not a generic code.

        The ladder's fourth rung requires that "every identifier embedded in the
        path resolves to a live row", and "the reported error names the missing
        family: `ERR_OUTING_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_TIER_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_PLAYER_NOT_FOUND`,
        `ERR_TEAM_NOT_FOUND`".  The body follows the error envelope, in which "The
        `message` provides a human-readable explanation of what went wrong."

        Design: Corner/entities/read_team_with_unknown_uuid_returns_team_not_found
        """
        fx.set_clock(api, CLOCK_START_UTC)

        response = api.get_team(NON_EXISTENT_UUID, DIRECTOR_HEADERS)
        data = validate_error(response, ApiErrorId.TEAM_NOT_FOUND.value, 404)
        assert response.json()["response_type"] == "error"
        assert isinstance(data["message"], str) and data["message"].strip() != ""


class TestCreateOutingMissingRequiredField:
    def test_omitting_the_scheduled_date_is_a_schema_failure_that_persists_nothing(self, api):
        """The date of play has no default, so its absence stops the request at tier 3.

        "The director also supplies the `scheduled_date` of play", and only three
        inputs are optional - "a contracted alternate date as `rain_date`, and the
        wave B window as `wave_b_start` and `wave_b_end`".  The schema tier answers
        first, because "Requests are rejected with `ERR_INVALID_REQUEST` when a
        required input is absent".

        Design: Corner/entities/create_outing_missing_required_scheduled_date_returns_422
        """
        fx.set_clock(api, CLOCK_START_UTC)
        payload = f.outing_payload(name="No Date Open", field_capacity_teams=10)
        del payload["scheduled_date"]

        validate_error(
            api.create_outing(payload, DIRECTOR_HEADERS), ApiErrorId.INVALID_REQUEST.value, 422
        )

        _, meta = validate_paginated(api.list_outings(DIRECTOR_HEADERS))
        assert meta["total_count"] == 0


class TestCreateContractDefaults:
    def test_the_three_required_inputs_are_enough_and_every_other_term_defaults(self, api):
        """A bare contract body still reads back a complete club agreement.

        The contract "must state the `rate_per_player_cents`", and every other term
        stands in from the declared defaults: "the `guaranteed_player_count` the
        organizer will pay for regardless of turnout defaults to 72 (that is,
        eighteen full foursomes); the `fnb_minimum_cents` food-and-beverage minimum
        spend defaults to 0; the `fnb_per_player_cents` credited against that
        minimum for each billable player defaults to 4500", "the `course_rating`
        defaults to 71.4; the `slope_rating` defaults to 128; the `par` defaults to
        72", "the `tee_interval_minutes` length of one tee-sheet slot defaults to 10
        and must be at least 1; the `cart_allowance_count` of distinct carts the
        course supplies defaults to 40 and must be at least 1", "the
        `rain_date_terms` default to `NONE`", "the `rain_date_credit_pct` fraction
        credited under partial terms defaults to 0.5", and "the
        `cancellation_notice_days` window defaults to 30 whole days".  The row
        starts clean, since "A new contract begins at `DRAFT` with `signed_at` null,
        `amendment_count` 0, `rain_credit_cents` 0, and `settled_charge_cents` 0."

        Design: Corner/entities/create_contract_omitting_optional_fields_applies_declared_defaults
        """
        fx.set_clock(api, CLOCK_START_UTC)
        outing = fx.new_outing(api, name="Defaults Open", format="STROKE_PLAY",
                               field_capacity_teams=10)

        data = validate_success(
            api.create_contract(f.minimal_contract_payload(outing["id"]), COURSE_HEADERS), 201
        )
        assert data["status"] == "DRAFT"
        assert data["signed_at"] is None
        assert data["amendment_count"] == 0
        assert data["version"] == 1
        assert data["rate_per_player_cents"] == 9500

        assert data["guaranteed_player_count"] == DEFAULT_GUARANTEED_PLAYER_COUNT
        assert data["fnb_minimum_cents"] == DEFAULT_FNB_MINIMUM_CENTS
        assert data["fnb_per_player_cents"] == DEFAULT_FNB_PER_PLAYER_CENTS
        assert data["course_rating"] == pytest.approx(DEFAULT_COURSE_RATING, abs=0.01)
        assert data["slope_rating"] == DEFAULT_SLOPE_RATING
        assert data["par"] == DEFAULT_PAR
        assert data["tee_interval_minutes"] == DEFAULT_TEE_INTERVAL_MINUTES
        assert data["cart_allowance_count"] == DEFAULT_CART_ALLOWANCE_COUNT
        assert data["cancellation_notice_days"] == DEFAULT_CANCELLATION_NOTICE_DAYS
        assert data["rain_date_terms"] == DEFAULT_RAIN_DATE_TERMS
        assert data["rain_date_credit_pct"] == pytest.approx(
            DEFAULT_RAIN_DATE_CREDIT_PCT, abs=0.01
        )
        assert data["rain_credit_cents"] == 0
        assert data["settled_charge_cents"] == 0


class TestComputedTierSoldCount:
    def test_supplying_the_computed_sold_count_is_refused_and_the_clean_payload_lands(self, api):
        """`sold_count` is derived, so it is not an accepted input key.

        The schema tier covers exactly this case: a request is rejected with
        `ERR_INVALID_REQUEST` "when the body attempts to write a field that the
        server computes or manages itself".  The counter only ever moves as a
        derivation, because "Each tier also exposes a live `sold_count`: the number
        of registrations currently holding it whose status is `CONFIRMED`,
        `AMENDED`, or `CHECKED_IN`."

        Design: Corner/entities/computed_tier_sold_count_ignores_a_client_supplied_value
        """
        ctx = fx.signed_contract_outing(
            api, outing={"name": "Computed Field Open", "field_capacity_teams": 5}
        )
        payload = f.package_tier_payload(ctx["outing_id"], inventory_cap=50, sold_count=7)

        validate_error(
            api.create_package_tier(payload, DIRECTOR_HEADERS),
            ApiErrorId.INVALID_REQUEST.value,
            422,
        )
        _, meta = validate_paginated(
            api.list_package_tiers(DIRECTOR_HEADERS, outing_id=ctx["outing_id"])
        )
        assert meta["total_count"] == 0

        del payload["sold_count"]
        data = validate_success(api.create_package_tier(payload, DIRECTOR_HEADERS), 201)
        assert data["sold_count"] == 0
        assert data["code"] == "TEAM4"
        assert data["price_cents"] == 120000


RECEIPT_TIER = {"price_cents": 120000, "player_slots": 4, "gsv_cents": 24000, "inventory_cap": 50}
ISSUE_INSTANT = "2026-08-05T09:30:00Z"


def _paid_registration(api, outing_name, buyer_name):
    """One CONFIRMED 120000 package on an open outing."""
    ctx = fx.open_outing(
        api, outing={"name": outing_name, "field_capacity_teams": 5}, tier=RECEIPT_TIER
    )
    registration = fx.new_registration(
        api, ctx["outing_id"], ctx["tier_id"], buyer_name=buyer_name, player_count=4
    )
    fx.pay_registration(api, registration["id"], 120000)
    ctx["registration_id"] = registration["id"]
    return ctx


class TestReceiptServerMintedFields:
    def test_the_number_the_instant_and_the_issuer_all_come_from_the_server(self, api):
        """The client names only the subject; everything else is stamped.

        Numbering is per outing: the `receipt_number` is "a per-outing sequential
        string in the form `GR-0001` assigned in `created_at` ascending order, so
        the first receipt of an outing reads `GR-0001`".  Identity and time are
        taken, not supplied: "The acting user is stamped into `issued_by_user_id` and
        the logical clock into `issued_at`.", and that clock is authoritative since
        "All temporal comparisons in this system read a logical clock rather than
        wall-clock time."  The row itself is thin, because "it carries only `id` and
        `created_at`; it has neither an `updated_at` field nor a `version` field".

        Design: Corner/entities/receipt_number_and_issued_at_are_server_minted_not_client_supplied
        """
        ctx = _paid_registration(api, "System Field Open", "Stamped Co")
        fx.set_clock(api, ISSUE_INSTANT, TREASURER_HEADERS)

        data = validate_success(
            api.create_receipt(
                f.registration_receipt_payload(ctx["outing_id"], ctx["registration_id"]),
                TREASURER_HEADERS,
            ),
            201,
        )
        assert data["receipt_number"] == "GR-0001"
        assert_instant_equals(data["issued_at"], ISSUE_INSTANT)
        assert_instant_equals(data["created_at"], ISSUE_INSTANT)
        assert data["issued_by_user_id"] == TREASURER_USER_ID
        assert "version" not in data
        assert data["payment_cents"] == 120000
        assert data["gsv_cents"] == 24000
        assert data["deductible_amount_cents"] == 96000


class TestTypeConstraints:
    def test_an_unknown_format_and_a_negative_price_both_stop_at_the_schema_tier(self, api):
        """Two different constraint kinds, one error code, and nothing written.

        The format is a closed set - "the tournament `format` — one of `SCRAMBLE`,
        `BEST_BALL`, or `STROKE_PLAY`" - and money may not go below zero, since a
        tier names "its `price_cents`".  Both are schema failures: a request is
        rejected with `ERR_INVALID_REQUEST` "when an enum-typed input carries a value
        outside its declared set" and "when a field whose name ends in `_cents` or
        `_count` is supplied as a negative number".

        Design: Corner/entities/enum_and_numeric_type_constraints_are_rejected_with_422
        """
        fx.set_clock(api, CLOCK_START_UTC)
        outing = fx.new_outing(api, name="Type Guard Open", field_capacity_teams=5)

        validate_error(
            api.create_outing(
                f.outing_payload(name="Match Play Open", format="MATCH_PLAY",
                                 field_capacity_teams=5),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            422,
        )
        validate_error(
            api.create_package_tier(
                f.package_tier_payload(
                    outing["id"], code="NEGATIVE", price_cents=-1, gsv_cents=0, inventory_cap=10
                ),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            422,
        )

        _, outings = validate_paginated(api.list_outings(DIRECTOR_HEADERS))
        assert outings["total_count"] == 1
        _, tiers = validate_paginated(
            api.list_package_tiers(DIRECTOR_HEADERS, outing_id=outing["id"])
        )
        assert tiers["total_count"] == 0


class TestReceiptImmutability:
    def test_a_reversal_cannot_be_reversed_and_the_original_row_still_reads_as_written(self, api):
        """Two rows stand for good, and the only correction mechanism is exhausted.

        A receipt is append-only: "Correcting a receipt is done by appending a
        reversal, never by editing the original."  The second-order attempt is closed
        off, since "A reversal may never itself be reversed, and a receipt that
        already carries a live reversal may not be reversed a second time; both are
        refused with `ERR_RECEIPT_IMMUTABLE`."  The pair cancels out because "The
        outing's `receipted_deductible_total_cents` is the signed sum of
        `deductible_amount_cents` over every receipt of the outing, reversals
        included".

        Design: Corner/entities/charitable_receipt_is_immutable_and_carries_no_version_field
        """
        ctx = _paid_registration(api, "Append Only Open", "Immutable Inc")
        original = fx.issue_registration_receipt(api, ctx["outing_id"], ctx["registration_id"])
        reversal = fx.reverse_receipt(api, original["id"], "Reissue to the parent company")

        validate_error(
            api.reverse_receipt(
                reversal["id"], f.reversal_payload("Reversing the reversal"), TREASURER_HEADERS
            ),
            ApiErrorId.RECEIPT_IMMUTABLE.value,
            409,
        )

        stored = fx.read_receipt(api, original["id"])
        assert stored["deductible_amount_cents"] == 96000
        assert stored["receipt_number"] == "GR-0001"
        assert "version" not in stored

        _, meta = validate_paginated(
            api.list_receipts(TREASURER_HEADERS, outing_id=ctx["outing_id"])
        )
        assert meta["total_count"] == 2
        assert fx.read_outing(api, ctx["outing_id"])["receipted_deductible_total_cents"] == 0


class TestCreatePlayerUnknownParent:
    def test_an_unresolvable_registration_id_in_the_body_is_a_404_on_that_family(self, api):
        """The parent arrives as a body foreign key, so tier 5 answers.

        The fifth rung requires that "every foreign key supplied in the request body
        resolves to a live row, checked in the order the endpoint declares its
        inputs, and reported with the same family-specific 404 codes. This tier
        applies to registration creation, player creation", so an unknown parent is
        `ERR_REGISTRATION_NOT_FOUND` rather than a schema failure or a business
        rejection.

        Design: Corner/entities/create_player_with_unresolvable_registration_id_returns_registration_not_found
        """
        fx.set_clock(api, CLOCK_START_UTC)

        validate_error(
            api.create_player(
                f.player_payload(NON_EXISTENT_UUID, full_name="Orphan Golfer"), DIRECTOR_HEADERS
            ),
            ApiErrorId.REGISTRATION_NOT_FOUND.value,
            404,
        )

        _, meta = validate_paginated(api.list_players(DIRECTOR_HEADERS))
        assert meta["total_count"] == 0


class TestCrossOutingTierReference:
    def test_a_tier_belonging_to_another_outing_is_refused_at_the_integrity_tier(self, api):
        """Both identifiers resolve, so this is an integrity failure rather than a 404.

        The sixth rung demands that "every row named by one request belongs to the
        same outing, otherwise `ERR_CROSS_OUTING_REFERENCE` (HTTP 409). This governs
        a registration and its tier", and it sits above every business rule, so
        neither the field capacity nor the tier inventory is consulted.

        Design: Corner/entities/registration_naming_a_tier_from_another_outing_is_a_cross_outing_reference
        """
        first = fx.open_outing(
            api, outing={"name": "Outing A", "field_capacity_teams": 5}, tier=BIG_TEAM_TIER
        )
        second = fx.open_outing(
            api,
            clock=None,
            outing={
                "name": "Outing B",
                "beneficiary_name": "Southside Literacy Trust",
                "field_capacity_teams": 5,
                "scheduled_date": "2026-09-26T12:00:00Z",
                "wave_a_start": "2026-09-26T12:00:00Z",
                "wave_a_end": "2026-09-26T16:30:00Z",
            },
            contract=PAGE_TWO_CONTRACT,
            tier=OTHER_TEAM_TIER,
        )

        validate_error(
            api.create_registration(
                f.registration_payload(
                    first["outing_id"], second["tier_id"], buyer_name="Wrong Outing Co"
                ),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.CROSS_OUTING_REFERENCE.value,
            409,
        )

        _, meta = validate_paginated(
            api.list_registrations(DIRECTOR_HEADERS, outing_id=first["outing_id"])
        )
        assert meta["total_count"] == 0
        assert fx.read_tier(api, second["tier_id"])["sold_count"] == 0
