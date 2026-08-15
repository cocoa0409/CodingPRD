"""Fleet cycle, reservation overlap, emissions tier, kit sizing, credit gate (PRD §3.2–3.3)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_equipment_line,
    add_kit_line,
    complete_visit,
    confirm_contract,
    create_accessory_kit,
    create_contract,
    create_customer,
    create_equipment_line_payload,
    create_equipment_unit,
    create_kit_line_payload,
    create_site,
    get_contract,
    get_line,
    get_unit,
    mobilize_contract,
    off_hire_contract,
    quote_contract,
    return_line,
    run_size_load,
    setup_draft_contract,
    setup_on_rent_contract,
    setup_quoted_contract,
    start_rental,
    validate_error,
    validate_paginated,
    validate_success,
)

TEST_SALES = TEST_USERS["sales_engineer_headers"]
TEST_DEPOT = TEST_USERS["depot_manager_headers"]


class TestEquipmentUnitFleetCycle:
    def test_unit_reserved_then_deployed(self, api):
        """PRD §3.3: "A successful equipment-line addition reserves the unit: it
        cascades `AVAILABLE → RESERVED` and binds itself to the new line".
        PRD §3.6: "every unit still `RESERVED` deploys to `DEPLOYED` with its
        `current_site_id` set to the contract's site".

        Design: Difficulty/non_linear_state_machine/equipment_unit_fleet_cycle
        """
        customer = create_customer()
        site = create_site(customer["id"])
        unit = create_equipment_unit()
        contract = create_contract(customer["id"], site["id"])
        run_size_load(contract["id"])
        add_equipment_line(contract["id"], unit["id"])
        assert get_unit(unit["id"])["status"] == "RESERVED"

        quote_contract(contract["id"])
        confirm_contract(contract["id"])
        mobilize_contract(contract["id"])
        start_rental(contract["id"])

        deployed = get_unit(unit["id"])
        assert deployed["status"] == "DEPLOYED"
        assert deployed["current_site_id"] == site["id"]

    def test_unit_off_rent_maintenance_available_cycle(self, api):
        """PRD §3.9: "each deployed unit moves to `OFF_RENT`" (contract off-hire).
        PRD §3.9: "A `DepotManager` returns a line standing in `OFF_HIRED` — allowed
        while the parent contract is `OFF_HIRE` or `CLOSED` — moving the line to the
        terminal `RETURNED` state and sending its unit `OFF_RENT → MAINTENANCE` for
        inspection at its home depot."
        PRD §3.2: "the unit returns `MAINTENANCE → AVAILABLE`, its `version`
        increments by one, and it rejoins the rentable pool."

        Design: Difficulty/non_linear_state_machine/equipment_unit_fleet_cycle
        """
        bundle = setup_on_rent_contract(clock_after_start="2026-09-04T00:00:00Z")
        unit = bundle["unit"]
        line = bundle["line"]

        off_hire_contract(bundle["contract"]["id"])
        off_rent = get_unit(unit["id"])
        assert off_rent["status"] == "OFF_RENT"
        assert off_rent["current_site_id"] is None

        returned = validate_success(
            api.return_line(line["id"], TEST_DEPOT), 200
        )
        assert returned["status"] == "RETURNED"
        assert get_unit(unit["id"])["status"] == "MAINTENANCE"

        unit_before = get_unit(unit["id"])
        restored = validate_success(
            api.complete_maintenance(unit["id"], TEST_DEPOT), 200
        )
        assert restored["status"] == "AVAILABLE"
        assert restored["version"] == unit_before["version"] + 1


class TestUnitReservationWindows:
    def _setup_reserved_unit(self, api):
        """Unit reserved by contract KA over [2026-09-01, 2026-09-08)."""
        customer = create_customer()
        site = create_site(customer["id"])
        unit = create_equipment_unit()
        contract_a = create_contract(customer["id"], site["id"])
        run_size_load(contract_a["id"])
        add_equipment_line(contract_a["id"], unit["id"])
        return customer, site, unit

    def test_adjacent_window_allowed(self, api):
        """PRD §3.3: "because both windows are half-open, a new rental starting
        exactly when an existing reservation ends is adjacency, not overlap, and is
        allowed".

        Design: Difficulty/resource_temporal_overlap/unit_reservation_half_open_adjacency
        """
        customer, site, unit = self._setup_reserved_unit(api)
        contract_b = create_contract(
            customer["id"], site["id"],
            start_date="2026-09-08T00:00:00Z",
            expected_offhire_date="2026-09-15T00:00:00Z",
        )
        line_b = add_equipment_line(contract_b["id"], unit["id"])
        assert line_b["status"] == "PENDING"

    def test_overlapping_window_rejected(self, api):
        """PRD §3.3: "Third, the reservation-conflict rule fires: the named unit must
        have no other line in `PENDING` or `ON_RENT` whose contract window
        half-open-overlaps the new contract's window; because both windows are
        half-open, a new rental starting exactly when an existing reservation ends is
        adjacency, not overlap, and is allowed, while any true intersection is
        rejected with `ERR_UNIT_RESERVED_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/unit_reservation_half_open_adjacency
        """
        customer, site, unit = self._setup_reserved_unit(api)
        contract_b = create_contract(
            customer["id"], site["id"],
            start_date="2026-09-08T00:00:00Z",
            expected_offhire_date="2026-09-15T00:00:00Z",
        )
        add_equipment_line(contract_b["id"], unit["id"])

        contract_c = create_contract(
            customer["id"], site["id"],
            start_date="2026-09-14T00:00:00Z",
            expected_offhire_date="2026-09-20T00:00:00Z",
        )
        res = api.add_line(
            contract_c["id"],
            create_equipment_line_payload(unit["id"], contract_c["version"]),
            TEST_SALES,
        )
        validate_error(res, ApiErrorId.ERR_UNIT_RESERVED_CONFLICT, expected_status=409)
        assert get_unit(unit["id"])["status"] == "RESERVED"


class TestValidationPriorityPairs:
    def _setup_overlap_and_hold(self, api):
        """Unit reserved by a GOOD customer's contract over [09-01, 09-08); a HOLD
        customer's contract overlaps it over [09-05, 09-12)."""
        good = create_customer(name="Good Credit Co", billing_email="ap@good.example")
        hold = create_customer(
            name="Hold Credit Co", billing_email="ap@hold.example", credit_status="HOLD"
        )
        site = create_site(good["id"])
        unit = create_equipment_unit()
        contract_a = create_contract(good["id"], site["id"])
        run_size_load(contract_a["id"])
        add_equipment_line(contract_a["id"], unit["id"])
        contract_b = create_contract(
            hold["id"], site["id"],
            start_date="2026-09-05T00:00:00Z",
            expected_offhire_date="2026-09-12T00:00:00Z",
        )
        return unit, contract_a, contract_b

    def test_overlap_error_beats_credit_hold(self, api):
        """PRD §2.8: "Incoming writes are screened by a nine-tier validation pipeline,
        and the tiers are evaluated in strict priority order: a request that fails an
        earlier tier never surfaces an error from a later one."
        PRD §2.8: "The ninth and final tier is fiscal: the customer's credit posture
        is evaluated last, so a quote request, a quote confirmation, or a line
        addition against a credit-held customer fails with `ERR_CREDIT_HOLD` only
        after every earlier tier has passed."

        Design: Difficulty/priority_pair_validation_conflict/line_add_overlap_vs_credit_hold
        """
        unit, _, contract_b = self._setup_overlap_and_hold(api)
        res = api.add_line(
            contract_b["id"],
            create_equipment_line_payload(unit["id"], contract_b["version"]),
            TEST_SALES,
        )
        # Temporal tier (sixth) fires before the fiscal tier (ninth).
        validate_error(res, ApiErrorId.ERR_UNIT_RESERVED_CONFLICT, expected_status=409)

    def test_overlap_rejection_creates_no_line_and_keeps_unit(self, api):
        """PRD §2.8: "The sixth tier enforces temporal separation: equipment
        reservation windows may not overlap (`ERR_UNIT_RESERVED_CONFLICT`)".

        Design: Difficulty/priority_pair_validation_conflict/line_add_overlap_vs_credit_hold
        """
        unit, contract_a, contract_b = self._setup_overlap_and_hold(api)
        res = api.add_line(
            contract_b["id"],
            create_equipment_line_payload(unit["id"], contract_b["version"]),
            TEST_SALES,
        )
        validate_error(res, ApiErrorId.ERR_UNIT_RESERVED_CONFLICT)

        _, meta = validate_paginated(
            api.list_rental_lines(TEST_SALES, params={"contract_id": contract_b["id"]})
        )
        assert meta["total_count"] == 0, "the rejected line add persists nothing"
        assert get_unit(unit["id"])["status"] == "RESERVED"


class TestEmissionsTierRule:
    def test_tier2_unit_banned_in_strict_locale(self, api):
        """PRD §3.3: "Second, once state and staleness checks pass, the emissions-tier
        rule fires: a `TIER_2` unit may not be added to a contract whose site
        jurisdiction cap is 5.0 or lower — in practice the CA-SCAQMD locale — and the
        attempt is rejected with `ERR_EMISSIONS_TIER_NONCOMPLIANT` (HTTP 422)."

        Design: Corner/validations/tier2_unit_banned_in_strict_locale
        """
        customer = create_customer()
        site_ca = create_site(
            customer["id"], name="LA Basin Yard", jurisdiction_code="CA-SCAQMD"
        )
        site_tx = create_site(customer["id"])  # TX-TCEQ, cap 8.0
        tier2_unit = create_equipment_unit(emissions_tier="TIER_2", nox_g_per_kwh=4.0)

        contract_ca = create_contract(customer["id"], site_ca["id"])
        res = api.add_line(
            contract_ca["id"],
            create_equipment_line_payload(tier2_unit["id"], contract_ca["version"]),
            TEST_SALES,
        )
        validate_error(
            res, ApiErrorId.ERR_EMISSIONS_TIER_NONCOMPLIANT, expected_status=422
        )
        _, meta = validate_paginated(
            api.list_rental_lines(TEST_SALES, params={"contract_id": contract_ca["id"]})
        )
        assert meta["total_count"] == 0
        assert get_unit(tier2_unit["id"])["status"] == "AVAILABLE"

        # The same unit is acceptable under the TX-TCEQ cap (8.0 > 5.0).
        contract_tx = create_contract(customer["id"], site_tx["id"])
        line = add_equipment_line(contract_tx["id"], tier2_unit["id"])
        assert line["status"] == "PENDING"


class TestKitSizingRule:
    def test_kit_undersized_then_adequate(self, api):
        """PRD §3.3: "The required ampacity is the contract's `sized_kw` multiplied by
        one thousand, divided by the product of 480 — the three-phase voltage — and
        1.732 — the square-root-of-three factor — with the result rounded up to the
        next whole ampere. The line is adequate only when its `quantity` multiplied by
        the kit's `max_ampacity_a` is at least that required figure; an inadequate kit
        line is rejected with `ERR_KIT_UNDERSIZED` (HTTP 422)."

        Design: Corner/validations/kit_undersized_then_adequate
        """
        customer = create_customer()
        site = create_site(customer["id"])
        kit = create_accessory_kit(
            kit_code="CABLE-200A", description="200A cable kit", max_ampacity_a=200,
            day_rate_cents=2000, week_rate_cents=10000, month_rate_cents=32000,
        )
        contract = create_contract(
            customer["id"], site["id"],
            load_profile=[{"load_type": "CONTINUOUS", "nameplate_kw": 220}],
        )
        sized = run_size_load(contract["id"])
        assert sized["sized_kw"] == 275  # ceil(1.25 * 220)
        # required amps = ceil(275000 / (480 * 1.732)) = ceil(330.79) = 331
        current = get_contract(contract["id"])["version"]

        short = api.add_line(
            contract["id"],
            create_kit_line_payload(kit["id"], current, quantity=1),
            TEST_SALES,
        )
        validate_error(short, ApiErrorId.ERR_KIT_UNDERSIZED, expected_status=422)

        line = add_kit_line(contract["id"], kit["id"], quantity=2)
        assert line["status"] == "PENDING"
        assert line["quantity"] == 2


class TestCreditHold:
    def test_credit_hold_blocks_line_add(self, api):
        """PRD §3.1: "while a customer stands at `HOLD`, quoting, quote confirmation,
        and line addition are all rejected with `ERR_CREDIT_HOLD` (HTTP 402)".

        Design: Corner/validations/credit_hold_blocks_line_add
        """
        customer = create_customer(
            name="Hold Credit Co", billing_email="ap@hold.example", credit_status="HOLD"
        )
        site = create_site(customer["id"])
        unit = create_equipment_unit()
        contract = create_contract(customer["id"], site["id"])
        run_size_load(contract["id"])
        current = get_contract(contract["id"])["version"]

        res = api.add_line(
            contract["id"],
            create_equipment_line_payload(unit["id"], current),
            TEST_SALES,
        )
        validate_error(res, ApiErrorId.ERR_CREDIT_HOLD, expected_status=402)

        _, meta = validate_paginated(
            api.list_rental_lines(TEST_SALES, params={"contract_id": contract["id"]})
        )
        assert meta["total_count"] == 0
        assert get_unit(unit["id"])["status"] == "AVAILABLE"


class TestFleetListPagination:
    def test_list_pagination_limit_offset(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; when
        omitted it defaults to 10, and it may not be lower than 1 or greater than 100.
        The `offset` parameter states how many items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the four pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_limit_offset
        """
        create_equipment_unit()
        create_equipment_unit(
            capacity_kw=100, nox_g_per_kwh=2.5, day_rate_cents=8000,
            week_rate_cents=40000, month_rate_cents=130000, demob_fee_cents=20000,
        )
        create_equipment_unit(
            unit_type="CHILLER", capacity_kw=50, nox_g_per_kwh=2.0,
            day_rate_cents=6000, week_rate_cents=30000, month_rate_cents=100000,
            demob_fee_cents=15000, home_depot_code="DAL-02",
        )

        page1, meta1 = validate_paginated(
            api.list_equipment_units(TEST_DEPOT, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_equipment_units(TEST_DEPOT, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
