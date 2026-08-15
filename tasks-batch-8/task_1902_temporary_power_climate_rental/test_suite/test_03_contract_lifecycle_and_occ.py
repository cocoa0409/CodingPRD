"""Contract lifecycle cycles, quote expiry, terminal lockdown, OCC (PRD §2.5, §2.7, §3.4)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_equipment_line,
    add_kit_line,
    cancel_contract,
    confirm_contract,
    create_accessory_kit,
    create_contract,
    create_contract_payload,
    create_customer,
    create_equipment_line_payload,
    create_equipment_unit,
    create_site,
    get_contract,
    get_line,
    get_unit,
    quote_contract,
    revise_contract,
    run_size_load,
    set_logical_clock,
    setup_draft_contract,
    setup_quoted_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

TEST_SALES = TEST_USERS["sales_engineer_headers"]
TEST_DEPOT = TEST_USERS["depot_manager_headers"]


class TestQuoteReviseCycle:
    def test_revise_reverts_to_draft_and_reopens_line_assembly(self, api):
        """PRD §3.4: "Revision moves the contract `QUOTED → DRAFT`, invalidating the
        quote — `quoted_at` and `quoted_total_cents` are cleared — and reopening line
        assembly; the version increments again."

        Design: Difficulty/non_linear_state_machine/contract_quote_revise_cycle
        """
        bundle = setup_quoted_contract(with_kit=False)
        contract = bundle["contract"]
        # Equipment-only 7-day quote: 60000 + 35000 demob.
        assert contract["quoted_total_cents"] == 95000

        revised = revise_contract(contract["id"])
        assert revised["status"] == "DRAFT"
        assert revised["quoted_at"] is None
        assert revised["quoted_total_cents"] is None

        # Line assembly is open again in DRAFT.
        kit = create_accessory_kit()
        kit_line = add_kit_line(contract["id"], kit["id"], quantity=1)
        assert kit_line["status"] == "PENDING"

        requoted = quote_contract(contract["id"])
        # 95000 equipment + 15000 kit week = 110000.
        assert requoted["quoted_total_cents"] == 110000
        assert requoted["status"] == "QUOTED"

    def test_confirm_after_requote_lands_confirmed(self, api):
        """PRD §3.4: "Confirmation moves it `QUOTED → CONFIRMED` and may be performed
        by a `SalesEngineer` or by the `Customer` on their own contract".
        PRD §3.4: "Revision moves the contract `QUOTED → DRAFT`, invalidating the
        quote — `quoted_at` and `quoted_total_cents` are cleared — and reopening line
        assembly; the version increments again."

        Design: Difficulty/non_linear_state_machine/contract_quote_revise_cycle
        """
        bundle = setup_quoted_contract(with_kit=True)
        contract = bundle["contract"]
        assert contract["quoted_total_cents"] == 110000

        revise_contract(contract["id"])
        requoted = quote_contract(contract["id"])
        assert requoted["quoted_total_cents"] == 110000

        confirmed = confirm_contract(contract["id"])
        assert confirmed["status"] == "CONFIRMED"


class TestQuoteExpirySweep:
    def test_quote_expiry_sweep_releases_unit(self, api):
        """PRD §2.5: "Every clock advance runs a quote-expiry sweep. Any contract
        still in `QUOTED` status whose `quoted_at` lies more than seven days before
        the new logical now transitions `QUOTED → EXPIRED`, and the sweep performs the
        release cascade described in §2.9: each of that contract's lines still
        `PENDING` moves to `RELEASED`, and each unit still `RESERVED` for the contract
        returns to `AVAILABLE`."

        Design: Corner/state_machines/quote_expiry_sweep_releases_unit
        """
        bundle = setup_quoted_contract()
        contract = bundle["contract"]
        line = bundle["line"]
        unit = bundle["unit"]
        # Quoted at the startup logical instant 2026-08-01T00:00:00Z; advancing to
        # 2026-08-09 puts the quote more than seven days old.
        set_logical_clock("2026-08-09T00:00:00Z")

        fetched = get_contract(contract["id"])
        assert fetched["status"] == "EXPIRED"
        assert get_line(line["id"])["status"] == "RELEASED"
        assert get_unit(unit["id"])["status"] == "AVAILABLE"


class TestTerminalLockdown:
    def test_mobilize_cancelled_contract_returns_already_terminal(self, api):
        """PRD §3.9: "A contract in `CLOSED`, `CANCELLED`, or `EXPIRED`, a visit in
        `COMPLETED` or `CANCELLED`, an incident in `CHARGED` or `WAIVED`, and a permit
        in `APPROVED` each reject any further mutation with `ERR_ALREADY_TERMINAL`
        (HTTP 409)".

        Design: Corner/state_machines/terminal_contract_mutation_returns_already_terminal
        """
        customer = create_customer()
        site = create_site(customer["id"])
        contract = create_contract(customer["id"], site["id"])
        cancelled = cancel_contract(contract["id"])
        assert cancelled["status"] == "CANCELLED"

        res = api.mobilize_contract(contract["id"], TEST_DEPOT)
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)
        assert get_contract(contract["id"])["status"] == "CANCELLED"


class TestReserveCancelInvariant:
    def test_reservation_shrinks_available_pool(self, api):
        """PRD §3.3: "A successful equipment-line addition reserves the unit: it
        cascades `AVAILABLE → RESERVED` and binds itself to the new line".

        Design: Difficulty/compensating_invariant/reserve_then_cancel_restores_available_pool
        """
        customer = create_customer()
        site = create_site(customer["id"])
        unit = create_equipment_unit()
        extra = create_equipment_unit(
            unit_type="CHILLER", capacity_kw=50, nox_g_per_kwh=2.0,
            day_rate_cents=8000, week_rate_cents=40000, month_rate_cents=130000,
            demob_fee_cents=20000,
        )
        _, meta_before = validate_paginated(
            api.list_equipment_units(TEST_DEPOT, params={"status": "AVAILABLE"})
        )
        assert meta_before["total_count"] == 2

        contract = create_contract(customer["id"], site["id"])
        run_size_load(contract["id"])
        add_equipment_line(contract["id"], unit["id"])

        _, meta_after = validate_paginated(
            api.list_equipment_units(TEST_DEPOT, params={"status": "AVAILABLE"})
        )
        assert meta_after["total_count"] == 1, (
            "reserving one unit must shrink the AVAILABLE pool by exactly one"
        )
        assert get_unit(unit["id"])["status"] == "RESERVED"
        assert get_unit(extra["id"])["status"] == "AVAILABLE"

    def test_cancel_restores_available_pool_exactly(self, api):
        """PRD §2.9: "When a contract is cancelled or its quote expires, every one of
        its lines still `PENDING` moves to `RELEASED` and every unit still `RESERVED`
        for that contract is released back to `AVAILABLE` — a compensating release
        that restores the rentable pool."

        Design: Difficulty/compensating_invariant/reserve_then_cancel_restores_available_pool
        """
        bundle = setup_quoted_contract()
        unit = bundle["unit"]
        extra = create_equipment_unit(
            unit_type="CHILLER", capacity_kw=50, nox_g_per_kwh=2.0,
            day_rate_cents=8000, week_rate_cents=40000, month_rate_cents=130000,
            demob_fee_cents=20000,
        )
        _, meta_reserved = validate_paginated(
            api.list_equipment_units(TEST_DEPOT, params={"status": "AVAILABLE"})
        )
        assert meta_reserved["total_count"] == 1

        cancelled = cancel_contract(bundle["contract"]["id"])
        assert cancelled["status"] == "CANCELLED"

        _, meta_restored = validate_paginated(
            api.list_equipment_units(TEST_DEPOT, params={"status": "AVAILABLE"})
        )
        assert meta_restored["total_count"] == 2, (
            "the compensating release restores the pool to its pre-pair count"
        )
        assert get_unit(unit["id"])["status"] == "AVAILABLE"
        assert get_line(bundle["line"]["id"])["status"] == "RELEASED"


class TestOptimisticConcurrency:
    def test_occ_confirm_stale_version_rejected(self, api):
        """PRD §2.7: "If the supplied value does not equal the contract's current
        `version` at the moment the write is evaluated, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), and no part of the write takes effect."
        PRD §3.4: "it is the second OCC-guarded write, so the payload must carry
        `expected_rental_contract_version` matching the live version or the
        confirmation is rejected with `ERR_STALE_VERSION`".

        Design: Corner/cross_cutting_layers/occ_confirm_stale_version_returns_412
        """
        bundle = setup_quoted_contract()
        contract = bundle["contract"]
        stale_version = contract["version"]

        revise_contract(contract["id"])
        requoted = quote_contract(contract["id"])

        res = api.confirm_contract(
            contract["id"],
            {"expected_rental_contract_version": stale_version},
            TEST_SALES,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        assert get_contract(contract["id"])["status"] == "QUOTED", (
            "the stale confirmation takes no effect"
        )

        confirmed = confirm_contract(contract["id"], requoted["version"])
        assert confirmed["status"] == "CONFIRMED"

    def test_occ_line_add_stale_version_rejected(self, api):
        """PRD §2.7: "Exactly two write operations participate in optimistic
        concurrency control: confirming a quote
        (`POST /power-rental/rental-contracts/{id}/confirm`) and adding a rental line
        (`POST /power-rental/rental-contracts/{id}/lines`)."
        PRD §2.7: "If the supplied value does not equal the contract's current
        `version` at the moment the write is evaluated, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), and no part of the write takes effect."

        Design: Corner/cross_cutting_layers/occ_line_add_stale_version_returns_412
        """
        customer = create_customer()
        site = create_site(customer["id"])
        unit = create_equipment_unit()
        contract = create_contract(customer["id"], site["id"])
        create_version = contract["version"]
        sized = run_size_load(contract["id"])
        current_version = sized["version"]
        assert current_version != create_version

        res = api.add_line(
            contract["id"],
            create_equipment_line_payload(unit["id"], create_version),
            TEST_SALES,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        assert get_unit(unit["id"])["status"] == "AVAILABLE", (
            "the stale line add reserves nothing"
        )

        line = add_equipment_line(contract["id"], unit["id"])
        assert line["status"] == "PENDING"
        assert get_unit(unit["id"])["status"] == "RESERVED"


class TestRateSnapshotPinning:
    def test_rate_snapshot_pinned_at_line_add(self, api):
        """PRD §3.3: "at the moment a line is added, the referenced unit's or kit's
        three rates are copied onto the line as `day_rate_cents`, `week_rate_cents`,
        and `month_rate_cents`, along with `demob_fee_cents` — always 0 on kit lines —
        and those snapshots stay pinned for the life of the line regardless of later
        fleet repricing."

        Design: Corner/cross_cutting_layers/rate_snapshot_pinned_at_line_add
        """
        customer = create_customer()
        site = create_site(customer["id"])
        unit_a = create_equipment_unit()  # 12000 day / 35000 demob
        unit_b = create_equipment_unit(
            capacity_kw=100, nox_g_per_kwh=2.5,
            day_rate_cents=8000, week_rate_cents=40000, month_rate_cents=130000,
            demob_fee_cents=20000,
        )
        contract = create_contract(customer["id"], site["id"])
        run_size_load(contract["id"])

        line_a = add_equipment_line(contract["id"], unit_a["id"])
        line_b = add_equipment_line(contract["id"], unit_b["id"])

        assert line_a["day_rate_cents"] == 12000
        assert line_a["week_rate_cents"] == 60000
        assert line_a["month_rate_cents"] == 200000
        assert line_a["demob_fee_cents"] == 35000
        assert line_b["day_rate_cents"] == 8000
        assert line_b["week_rate_cents"] == 40000
        assert line_b["month_rate_cents"] == 130000
        assert line_b["demob_fee_cents"] == 20000
        assert line_a["status"] == "PENDING"
        assert line_b["status"] == "PENDING"
        assert get_unit(unit_a["id"])["status"] == "RESERVED"
        assert get_unit(unit_b["id"])["status"] == "RESERVED"
