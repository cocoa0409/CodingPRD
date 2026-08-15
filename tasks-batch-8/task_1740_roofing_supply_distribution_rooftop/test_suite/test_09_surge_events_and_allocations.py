"""Storm surge events: activation/close cascades, the allocation waterfall,
and grant-time optimistic concurrency."""
from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    get_success_data,
    make_account,
    make_branch,
    make_product,
    request_and_grant_allocation,
    setup_active_surge_event,
    create_surge_event_payload,
    request_allocation_payload,
    make_contractor_headers,
    validate_error,
    validate_success,
    ApiErrorId,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


class TestSurgeCloseCascade:
    def test_close_active_event_expires_allocations_and_releases_pool(self, api):
        """PRD §3.6: "Closing from `ACTIVE` flips the branch's `surge_mode`
        back to `NORMAL` and sweeps every allocation still in `PENDING`,
        `GRANTED`, or `PARTIALLY_CONSUMED` into the terminal `EXPIRED` state,
        releasing each one's unconsumed granted bundles from the event's
        `allocated_bundles`."

        VOLUME contractor (50% cap of 1000 = 500) granted 400, none consumed;
        closing returns the pool to zero allocated.

        Design: Difficulty/transitive_cascade/surge_close_cascades_to_allocation_expiry_and_pool_release
        """
        branch = make_branch("BR-S1")
        product = make_product("SH-S1", price=3000, color_code="WHT")
        account = make_account(tier="VOLUME", name="Surge Co")
        event = setup_active_surge_event(branch["id"], event_name="Hail-S1",
                                         allocation_pool_bundles=1000)
        allocation = request_and_grant_allocation(
            event["id"], account["id"], product["id"], 400)
        assert allocation["granted_bundles"] == 400

        closed = validate_success(api_client.close_surge_event(event["id"],
                                                               MANAGER))
        assert closed["status"] == "CLOSED"
        assert closed["allocated_bundles"] == 0
        branch_after = get_success_data(api_client.get_branch(branch["id"],
                                                              MANAGER))
        assert branch_after["surge_mode"] == "NORMAL"
        alloc_after = get_success_data(
            api_client.get_allocation(allocation["id"], MANAGER))
        assert alloc_after["status"] == "EXPIRED"

    def test_close_declared_event_revokes_pending_allocations(self, api):
        """PRD §3.6: "Closing from `DECLARED` — before the window ever opened
        — instead revokes every `PENDING` allocation into `REVOKED` and
        releases what they had allocated."
        PRD §3.6: "A `BranchManager` may close an event early — the close
        requires the event to be `DECLARED` or `ACTIVE`, otherwise
        `ERR_SURGE_NOT_ACTIVE` — and the system closes it automatically when
        the logical clock reaches `ends_at`."

        The window starts 2026-09-01, after the default clock, so the event is
        still DECLARED when closed.

        Design: Difficulty/transitive_cascade/surge_close_cascades_to_allocation_expiry_and_pool_release
        """
        branch = make_branch("BR-S2")
        product = make_product("SH-S2", price=3000, color_code="WHT")
        account = make_account(name="Surge Two")
        event = get_success_data(api_client.create_surge_event(
            branch["id"],
            create_surge_event_payload(
                event_name="Hail-S2", starts_at="2026-09-01T00:00:00Z",
                ends_at="2026-09-30T23:59:59Z"), MANAGER))
        allocation = get_success_data(api_client.request_allocation(
            event["id"],
            request_allocation_payload(account["id"], product["id"],
                                       requested_bundles=100),
            make_contractor_headers(account["id"])))
        assert allocation["status"] == "PENDING"

        closed = validate_success(api_client.close_surge_event(event["id"],
                                                               MANAGER))
        assert closed["status"] == "CLOSED"
        alloc_after = get_success_data(
            api_client.get_allocation(allocation["id"], MANAGER))
        assert alloc_after["status"] == "REVOKED"


class TestAllocationGrantTemporalWindow:
    def _event_with_pending_allocation(self):
        branch = make_branch("BR-O3")
        product = make_product("SH-O3", price=2000, color_code="WHT")
        account = make_account(name="Overlap Two")
        event = get_success_data(api_client.create_surge_event(
            branch["id"],
            create_surge_event_payload(
                event_name="Hail-O2", starts_at="2026-08-01T00:00:00Z",
                ends_at="2026-08-10T00:00:00Z",
                allocation_pool_bundles=500), MANAGER))
        advance_clock("2026-08-05T00:00:00Z")
        allocation = get_success_data(api_client.request_allocation(
            event["id"],
            request_allocation_payload(account["id"], product["id"],
                                       requested_bundles=100),
            make_contractor_headers(account["id"])))
        return branch, event, allocation

    def test_grant_after_window_close_rejected(self, api):
        """PRD §3.6: "the system closes it automatically when the logical
        clock reaches `ends_at`."
        PRD §3.6: "The allocation must be `PENDING` (otherwise
        `ERR_ALLOCATION_NOT_PENDING`) and the parent event must be `DECLARED`
        or `ACTIVE` (otherwise `ERR_SURGE_NOT_OPEN`)."

        The clock moved past ends_at: the event auto-closed, the PENDING
        allocation cascaded to EXPIRED, and the grant now fails the
        target-state check.

        Design: Difficulty/resource_temporal_overlap/allocation_grant_outside_surge_window
        """
        _branch, event, allocation = self._event_with_pending_allocation()
        advance_clock("2026-08-15T00:00:00Z")
        event_after = get_success_data(
            api_client.get_surge_event(event["id"], MANAGER))
        assert event_after["status"] == "CLOSED"
        alloc_after = get_success_data(
            api_client.get_allocation(allocation["id"], MANAGER))
        assert alloc_after["status"] == "EXPIRED"
        resp = api_client.grant_allocation(allocation["id"],
                                           event_after["version"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_PENDING)

    def test_grant_inside_window_succeeds(self, api):
        """PRD §3.6: "The allocation must be `PENDING` (otherwise
        `ERR_ALLOCATION_NOT_PENDING`) and the parent event must be `DECLARED`
        or `ACTIVE` (otherwise `ERR_SURGE_NOT_OPEN`)."
        PRD §3.6: "The event activates itself: when the logical clock reaches
        `starts_at`, the event moves from `DECLARED` to `ACTIVE` and the
        branch's `surge_mode` flips to `SURGE`."

        Control arm: the same grant inside the window succeeds.

        Design: Difficulty/resource_temporal_overlap/allocation_grant_outside_surge_window
        """
        _branch, event, allocation = self._event_with_pending_allocation()
        event_now = get_success_data(
            api_client.get_surge_event(event["id"], MANAGER))
        assert event_now["status"] == "ACTIVE"
        granted = validate_success(api_client.grant_allocation(
            allocation["id"], event_now["version"], MANAGER))
        assert granted["status"] == "GRANTED"
        assert granted["granted_bundles"] == 100


class TestAllocationWaterfall:
    def test_standard_tier_cap_binds_below_request(self, api):
        """PRD §3.6: "Each allocation in its turn receives the smallest of
        three quantities: its own `requested_bundles`; its contractor's
        remaining tier allowance, where a single contractor may receive at
        most fifty percent of the event's `allocation_pool_bundles` on the
        `VOLUME` tier, thirty-five percent on `PREFERRED`, or twenty-five
        percent on `STANDARD`, each computed by rounding half down to whole
        bundles; and the event's `remaining_pool_bundles` at that moment."

        STANDARD cap 25% of 1000 = 250 binds below the requested 400.

        Design: Corner/calculations/storm_surge_allocation_tier_cap_binds
        """
        branch = make_branch("BR-CA5")
        product = make_product("SH-CA5", price=2000, color_code="WHT")
        account = make_account(tier="STANDARD", name="Calc5 Co")
        event = setup_active_surge_event(branch["id"], event_name="Hail-CA5",
                                         allocation_pool_bundles=1000)
        allocation = get_success_data(api_client.request_allocation(
            event["id"],
            request_allocation_payload(account["id"], product["id"],
                                       requested_bundles=400),
            make_contractor_headers(account["id"])))
        event_now = get_success_data(
            api_client.get_surge_event(event["id"], MANAGER))
        granted = validate_success(api_client.grant_allocation(
            allocation["id"], event_now["version"], MANAGER))
        assert granted["granted_bundles"] == 250
        assert granted["status"] == "GRANTED"

    def test_regrant_of_granted_allocation_rejected(self, api):
        """PRD §3.6: "The allocation must be `PENDING` (otherwise
        `ERR_ALLOCATION_NOT_PENDING`) and the parent event must be `DECLARED`
        or `ACTIVE` (otherwise `ERR_SURGE_NOT_OPEN`)."

        Design: Corner/errors/error_allocation_not_pending_on_regrant
        """
        branch = make_branch("BR-ER2")
        product = make_product("SH-ER2", price=2000, color_code="WHT")
        account = make_account(name="ER2 Co")
        event = setup_active_surge_event(branch["id"], event_name="Hail-ER2",
                                         allocation_pool_bundles=1000)
        allocation = request_and_grant_allocation(
            event["id"], account["id"], product["id"], 100)
        event_now = get_success_data(
            api_client.get_surge_event(event["id"], MANAGER))
        resp = api_client.grant_allocation(allocation["id"],
                                           event_now["version"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_PENDING)

    def test_grant_with_stale_event_version_rejected(self, api):
        """PRD §2.10: "Granting a surge allocation requires the request to
        carry `expected_storm_surge_event_version`, holding the `version` of
        the parent StormSurgeEvent as the client last observed it. A mismatch
        with the event's current `version` — for instance because an earlier
        grant has already consumed part of the pool — is likewise rejected
        with `ERR_STALE_VERSION` (HTTP 412), so no grant is computed from a
        `remaining_pool_bundles` view the writer has not actually seen."

        Design: Corner/cross_cutting_layers/occ_allocation_grant_stale_event_version_rejected
        """
        branch = make_branch("BR-CC2")
        product = make_product("SH-CC2", price=2000, color_code="WHT")
        account = make_account(name="CC2 Co")
        event = setup_active_surge_event(branch["id"], event_name="Hail-CC2",
                                         allocation_pool_bundles=1000)
        alloc_a = get_success_data(api_client.request_allocation(
            event["id"],
            request_allocation_payload(account["id"], product["id"],
                                       requested_bundles=100),
            make_contractor_headers(account["id"])))
        alloc_b = get_success_data(api_client.request_allocation(
            event["id"],
            request_allocation_payload(account["id"], product["id"],
                                       requested_bundles=50),
            make_contractor_headers(account["id"])))
        stale_version = get_success_data(
            api_client.get_surge_event(event["id"], MANAGER))["version"]
        # The first grant advances the event version.
        get_success_data(api_client.grant_allocation(alloc_a["id"],
                                                     stale_version, MANAGER))
        resp = api_client.grant_allocation(alloc_b["id"], stale_version,
                                           MANAGER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
