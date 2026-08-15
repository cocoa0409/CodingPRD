"""Physical estate and catalog stand-up: terminals, zones, trucks, the
append-only price-index publication log, and season-driven reserve floors."""
from test_helpers import (
    CREDIT_MANAGER,
    DISPATCHER,
    PRICING_DESK,
    SUPPLY_ADMIN,
    SUPPLY_PLANNER,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_price_index_publication,
    assert_terminal,
    base_terminal_fixture,
    create_terminal,
    create_terminal_payload,
    create_truck,
    create_truck_payload,
    create_zone,
    get_success_data,
    publish_index,
    set_clock,
    validate_error,
    validate_success,
)


class TestTerminalCreation:

    def test_terminal_create_applies_defaults_and_clock_default(self):
        """PRD section 3.1: "The new terminal starts with `on_hand_gal` at 0,
        `allocation_posture` of `NORMAL`, an `ops_epoch` of 0, and `version` 1."
        PRD section 2.5: "At startup the clock reads exactly
        `2026-08-01T00:00:00Z`, and it continues to read that instant until a
        `SystemAdmin` sets it."
        PRD section 2.8: "It is reported exactly as computed and may be
        negative before the first inventory arrives"

        Design: Corner/entities/terminal_create_applies_defaults_and_clock_default
        """
        # Clock is never set: the startup default (August) drives season.
        resp = api_client.create_terminal(
            create_terminal_payload(name="T-E1"), SUPPLY_ADMIN)
        term = validate_success(resp, expected_status=201)
        assert_terminal(term)
        assert term["version"] == 1, "a fresh terminal starts at version 1"
        assert term["on_hand_gal"] == 0
        assert term["allocation_posture"] == "NORMAL"
        assert term["ops_epoch"] == 0

        summary = get_success_data(api_client.get_inventory_summary(
            term["id"], SUPPLY_PLANNER))
        assert summary["season_posture"] == "SUMMER_BUILD", \
            "August (default clock) is outside October through March"
        assert summary["effective_reserve_floor_gal"] == 50_000
        assert summary["available_to_promise_gal"] == -50_000, (
            "0 on_hand - 50000 floor - 0 reserved, reported negative as "
            f"computed; got {summary['available_to_promise_gal']}")

    def test_terminal_create_missing_required_field_returns_invalid_request(self):
        """PRD section 2.1: "a request whose shape is malformed — a missing
        required field, a wrong type, or an invalid enum member — is rejected
        with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD section 3.1: "A `SupplyAdmin` commissions a terminal by providing
        its `name`, a `region_code` such as a regional designator, the physical
        `storage_capacity_gal` (strictly positive), the `reserve_floor_gal`
        (zero or more), the `winter_reserve_floor_gal` (at least the non-winter
        floor), and the `rack_bay_count` (at least one)."

        Design: Corner/entities/terminal_create_missing_required_field_returns_invalid_request
        """
        payload = create_terminal_payload(name="T-E2")
        del payload["rack_bay_count"]
        resp = api_client.create_terminal(payload, SUPPLY_ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_dealer_get_not_found_returns_404(self):
        """PRD section 2.9: "Fourth, path identifiers are resolved
        left-to-right, and the first id that does not exist yields
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/dealer_get_not_found_returns_404
        """
        resp = api_client.get_dealer(NON_EXISTENT_UUID, CREDIT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestZoneAndTruckUniqueness:

    def test_zone_duplicate_code_rejected(self):
        """PRD section 3.1: "Against a terminal, a `SupplyAdmin` registers
        freight zones with a `zone_code` unique within that terminal (a
        duplicate is rejected with `ERR_DUPLICATE_ZONE_CODE`)"

        Design: Corner/entities/zone_duplicate_code_rejected
        """
        ta = create_terminal(name="T-ZA")
        tb = create_terminal(name="T-ZB", region_code="MW",
                             storage_capacity_gal=500_000,
                             reserve_floor_gal=20_000,
                             winter_reserve_floor_gal=60_000,
                             rack_bay_count=1)
        create_zone(ta["id"], zone_code="Z1")

        resp = api_client.create_freight_zone(
            {"terminal_id": ta["id"], "zone_code": "Z1",
             "one_way_drive_minutes": 90, "freight_mc_per_gal": 7_000,
             "min_freight_cents": 100_000},
            SUPPLY_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ZONE_CODE)

        # Uniqueness is per terminal: the same code on another terminal is fine.
        resp = api_client.create_freight_zone(
            {"terminal_id": tb["id"], "zone_code": "Z1",
             "one_way_drive_minutes": 90, "freight_mc_per_gal": 7_000,
             "min_freight_cents": 100_000},
            SUPPLY_ADMIN,
        )
        zone_b = validate_success(resp, expected_status=201)
        assert zone_b["zone_code"] == "Z1"
        assert zone_b["terminal_id"] == tb["id"]

    def test_duplicate_truck_unit_rejected(self):
        """PRD section 3.1: "each transport truck is created under a home
        terminal with a `unit_number` unique per terminal (duplicates rejected
        with `ERR_DUPLICATE_TRUCK_UNIT`)"

        Design: Corner/validations/duplicate_truck_unit_rejected
        """
        term = create_terminal(name="T-V13")
        create_truck(term["id"], unit_number="U-01")
        resp = api_client.create_truck(
            create_truck_payload(term["id"], unit_number="U-01",
                                 capacity_gal=9_500,
                                 weekly_hours_limit_minutes=2_400),
            SUPPLY_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TRUCK_UNIT)

    def test_truck_transition_invalid_enum_rejected(self):
        """PRD section 2.1: "a request whose shape is malformed — a missing
        required field, a wrong type, or an invalid enum member — is rejected
        with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD section 3.1: "A truck starts `AVAILABLE`." and the only other
        status named is `OUT_OF_SERVICE`.

        Design: Corner/entities/truck_transition_invalid_enum_rejected
        """
        term = create_terminal(name="T-E8")
        truck = create_truck(term["id"], unit_number="U-01")
        resp = api_client.transition_truck(truck["id"], {"to_state": "FLYING"},
                                           DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestPriceIndexCatalog:

    def test_index_publication_immutable_no_version_field(self):
        """PRD section 2.4: "The one exception is the `PriceIndexPublication`,
        which is append-only configuration: it carries `id` and `created_at`
        only. Both `updated_at` and `version` are absent from it, and no update
        or delete endpoint exists for it."

        Design: Corner/entities/index_publication_immutable_no_version_field
        """
        resp = api_client.create_price_index_publication(
            {"index_name": "CONWAY", "effective_date": "2026-08-01",
             "price_mc_per_gal": 91_000},
            PRICING_DESK,
        )
        pub = validate_success(resp, expected_status=201)
        assert_price_index_publication(pub)

        reread = get_success_data(
            api_client.get_price_index_publication(pub["id"], PRICING_DESK))
        assert_price_index_publication(reread)
        assert reread["index_name"] == "CONWAY"
        assert reread["effective_date"] == "2026-08-01"
        assert reread["price_mc_per_gal"] == 91_000

    def test_duplicate_index_publication_rejected(self):
        """PRD section 3.5: "publications are unique per index and date, and a
        duplicate pair is rejected with `ERR_DUPLICATE_INDEX_PUBLICATION`."

        Design: Corner/validations/duplicate_index_publication_rejected
        """
        publish_index(price_mc_per_gal=95_000, effective_date="2026-08-01")

        resp = api_client.create_price_index_publication(
            {"index_name": "MT_BELVIEU", "effective_date": "2026-08-01",
             "price_mc_per_gal": 96_000},
            PRICING_DESK,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INDEX_PUBLICATION)

        # The same date on a different index is a different pair: allowed.
        resp = api_client.create_price_index_publication(
            {"index_name": "CONWAY", "effective_date": "2026-08-01",
             "price_mc_per_gal": 91_000},
            PRICING_DESK,
        )
        pub2 = validate_success(resp, expected_status=201)
        assert_price_index_publication(pub2)

    def test_index_resolve_selector_determinism(self):
        """PRD section 3.5: "Resolving the index for a reference date means
        finding the publication for that index whose `effective_date` is the
        greatest one on or before the reference date"

        Design: Corner/endpoints/index_resolve_selector_determinism
        """
        publish_index(price_mc_per_gal=95_000, effective_date="2026-08-01")
        publish_index(price_mc_per_gal=98_000, effective_date="2026-08-10")

        early = get_success_data(api_client.resolve_price_index(
            PRICING_DESK,
            params={"index_name": "MT_BELVIEU", "on_date": "2026-08-05"}))
        assert early["price_mc_per_gal"] == 95_000, (
            "on 2026-08-05 the greatest effective_date <= on_date is "
            f"2026-08-01; got {early['price_mc_per_gal']}")

        exact = get_success_data(api_client.resolve_price_index(
            PRICING_DESK,
            params={"index_name": "MT_BELVIEU", "on_date": "2026-08-10"}))
        assert exact["price_mc_per_gal"] == 98_000, (
            "the effective date itself is inclusive (on or before); got "
            f"{exact['price_mc_per_gal']}")


class TestSeasonalReserveFloor:

    def test_winter_season_floor_switch(self):
        """PRD section 2.5: "when the current month falls in October through
        March the posture is `WINTER_DRAW`; in all other months it is
        `SUMMER_BUILD`."
        PRD section 2.8: "The `effective_reserve_floor_gal` is the winter floor
        while `season_posture` is `WINTER_DRAW`, and the regular floor
        otherwise."
        PRD section 2.8: "The terminal's `available_to_promise_gal` is
        `on_hand_gal` minus the effective reserve floor minus `reserved_gal`."

        Design: Corner/calculations/winter_season_floor_switch
        """
        ctx = base_terminal_fixture(name="T-L5", truck_count=0)
        term = ctx["terminal"]

        summer = get_success_data(api_client.get_inventory_summary(
            term["id"], SUPPLY_PLANNER))
        assert summer["season_posture"] == "SUMMER_BUILD"
        assert summer["effective_reserve_floor_gal"] == 50_000
        assert summer["available_to_promise_gal"] == 350_000, (
            f"400000 on hand - 50000 summer floor; got "
            f"{summer['available_to_promise_gal']}")

        set_clock("2026-12-01T00:00:00Z")
        winter = get_success_data(api_client.get_inventory_summary(
            term["id"], SUPPLY_PLANNER))
        assert winter["season_posture"] == "WINTER_DRAW", \
            "December falls in October through March"
        assert winter["effective_reserve_floor_gal"] == 150_000
        assert winter["available_to_promise_gal"] == 250_000, (
            "the floor switch drops ATP by 100000 with no inventory movement; "
            f"got {winter['available_to_promise_gal']}")
