"""Corner (cross-cutting + endpoints + consistency) — versioning, scheduled actions,
list filters, immediate visibility."""
from test_helpers import (
    validate_success,
    validate_paginated,
    get_success_data,
    set_clock,
    tick_clock,
    create_default_package,
    register_customer,
    create_pending_contract,
    activate_contract,
    setup_active_contract,
    setup_active_contract_with_item,
    file_claim,
    assess_claim,
    dispatch_claim,
    make_customer_headers,
    make_admin_headers,
    make_dispatcher_headers,
    create_covered_item_payload,
)


_ADMIN = make_admin_headers()
_DISPATCHER = make_dispatcher_headers()


class TestOccVersionIncrementsOnEachWrite:

    def test_activate_increments_version_by_one(self, api):
        """PRD §2.4: "a `version` integer that begins at 1 on creation and
        increments by one on every server-side mutation"
        PRD §3.2: "On activation, the server stamps `coverage_start_utc` to the
        current clock, stamps `coverage_end_utc` to exactly 365 days after
        `coverage_start_utc`, pins `annual_premium_due_cents` to the package's
        `annual_premium_cents` (unless renewal has already stamped it — see §3.6),
        and increments `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_write
        """
        set_clock("2026-01-01T00:00:00Z")
        package = create_default_package(code="VINC")
        customer = register_customer(email="vinc@example.com")
        pending = create_pending_contract(customer, package)
        assert pending["version"] == 1
        active = activate_contract(pending)
        assert active["version"] == 2


class TestClockTickEmitsRenewalReminderEvent:

    def test_first_tick_into_window_emits_one_reminder_with_correct_days(self, api):
        """PRD §3.8: "The clock-tick capability scans every contract in `ACTIVE`
        or `EXPIRING_SOON` and, for any active contract whose `coverage_end_utc`
        is at most 30 days away (and not yet reached), drives the auto-transition
        `ACTIVE → EXPIRING_SOON`."
        PRD §3.8: "The same transition writes a `RenewalReminder` row carrying
        the parent `contract_id`, `sent_utc` equal to the contract's just-stamped
        `renewal_reminder_sent_at`, and `days_to_expiry` equal to the whole number
        of days between the current clock and the contract's `coverage_end_utc`,
        computed by taking the total seconds remaining, dividing by 86400, and
        rounding down to a whole number."

        Design: Corner/cross_cutting_complexity_layers/clock_tick_emits_renewal_reminder_event
        """
        package, customer, contract = setup_active_contract(
            activate_at="2026-01-01T00:00:00Z",
        )
        # Clock to 2026-12-05 (= coverage_end - 27 days).
        set_clock("2026-12-05T00:00:00Z")
        tick_res = get_success_data(api.tick_clock(_ADMIN))
        assert tick_res["transitions_fired"] == 1
        assert tick_res["reminders_emitted"] == 1
        cust_h = make_customer_headers(customer["id"])
        rems_res = api.list_renewal_reminders(contract["id"], cust_h)
        data, _meta = validate_paginated(rems_res)
        assert len(data) == 1
        # floor((2027-01-01 - 2026-12-05)/86400) = 27.
        assert data[0]["days_to_expiry"] == 27


class TestClockTickIdempotent:

    def test_second_tick_at_same_clock_does_not_double_emit(self, api):
        """PRD §3.8: "This transition fires at most once per contract — it is
        guarded by the contract's `renewal_reminder_sent_at` field, which is null
        until the transition and pinned to the current clock at the moment it fires."

        Design: Corner/cross_cutting_complexity_layers/clock_tick_idempotent_no_double_reminder
        """
        package, customer, contract = setup_active_contract(
            activate_at="2026-01-01T00:00:00Z",
        )
        set_clock("2026-12-12T00:00:00Z")
        tick_clock()
        # Second tick at the same clock should not re-emit.
        tick2_res = get_success_data(api.tick_clock(_ADMIN))
        assert tick2_res["transitions_fired"] == 0
        assert tick2_res["reminders_emitted"] == 0
        cust_h = make_customer_headers(customer["id"])
        data, _meta = validate_paginated(
            api.list_renewal_reminders(contract["id"], cust_h)
        )
        assert len(data) == 1


class TestContractActivationVisibleImmediately:

    def test_get_after_activate_returns_active_with_coverage_window(self, api):
        """PRD §3.2: "On activation, the server stamps `coverage_start_utc` to the
        current clock, stamps `coverage_end_utc` to exactly 365 days after
        `coverage_start_utc`"

        Design: Corner/consistency_model/contract_activation_visible_immediately
        """
        set_clock("2026-01-01T00:00:00Z")
        package = create_default_package(code="VISIM")
        customer = register_customer(email="visim@example.com")
        pending = create_pending_contract(customer, package)
        active = activate_contract(pending)
        assert active["status"] == "ACTIVE"
        # Read back through GET; status must match.
        cust_h = make_customer_headers(customer["id"])
        body = validate_success(api.get_contract(active["id"], cust_h), 200)
        assert body["status"] == "ACTIVE"
        # coverage_start_utc reflects the clock at activation; coverage_end_utc = +365 days.
        assert body["coverage_start_utc"].startswith("2026-01-01T00:00:00")
        assert body["coverage_end_utc"].startswith("2027-01-01T00:00:00")


class TestCoveredItemsListFilterByContractId:

    def test_list_with_contract_id_filter_returns_only_matching_items(self, api):
        """PRD §4: "| GET | `/covered-items` | List covered items; supports
        `contract_id` and `last_dispatch_id` filters. | `PlatformAdmin`, `Customer`, `Dispatcher` |"

        Design: Corner/endpoints/covered_items_list_filter_by_contract_id
        """
        package = create_default_package(code="LFIL")
        cust1 = register_customer(email="lfa@example.com")
        cust2 = register_customer(email="lfb@example.com")
        c_a = activate_contract(create_pending_contract(cust1, package))
        c_b = activate_contract(create_pending_contract(cust2, package))
        cust1_h = make_customer_headers(cust1["id"])
        cust2_h = make_customer_headers(cust2["id"])
        # 2 items on A, 1 on B.
        get_success_data(api.create_covered_item(
            create_covered_item_payload(c_a["id"], category="HVAC",
                                         brand="B", model="A1"), cust1_h))
        get_success_data(api.create_covered_item(
            create_covered_item_payload(c_a["id"], category="WATER_HEATER",
                                         brand="B", model="A2"), cust1_h))
        get_success_data(api.create_covered_item(
            create_covered_item_payload(c_b["id"], category="WASHER",
                                         brand="B", model="B1"), cust2_h))
        # Filter for A.
        data, meta = validate_paginated(api.list_covered_items(
            _ADMIN, params={"contract_id": c_a["id"]}
        ))
        assert meta["total_count"] == 2
        assert len(data) == 2
        for item in data:
            assert item["contract_id"] == c_a["id"]


class TestDispatchesListFilterByClaimId:

    def test_list_with_claim_id_filter_returns_dispatch_for_that_claim(self, api):
        """PRD §4: "| GET | `/dispatches` | List dispatches; supports `claim_id`
        and `status` filters. | `PlatformAdmin`, `Dispatcher`, `Technician` |"

        Design: Corner/endpoints/dispatches_list_filter_by_claim_id
        """
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
            category="OVEN",
        )
        claim = file_claim(contract, customer, item, issue="Test")
        assess_claim(claim, 8_000)
        set_clock("2026-02-01T08:00:00Z")
        dispatch_claim(claim, "tech-FD", "2026-02-01T10:00:00Z")
        # Filter by claim_id.
        data, _meta = validate_paginated(
            api.list_dispatches(_DISPATCHER, params={"claim_id": claim["id"]})
        )
        assert len(data) == 1
        assert data[0]["claim_id"] == claim["id"]
