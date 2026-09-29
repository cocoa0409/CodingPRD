"""
Who may act, and on whose behalf.

The role grants of §4 read as four exclusive territories — reference data, shrink
closure and vendor money, count adjudication, and the narrow store-receiving
surface — while the three entity-backed roles are additionally confined to the
Store, Vendor or CounterFirm their `X-User-ID` names.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_IDENTITY_SCOPE_VIOLATION,
    ERR_PHYSICAL_INVENTORY_INVALID_STATE,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SHRINK_PERIOD_NOT_FOUND,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import assert_pct
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    CONTROLLER,
    ROLE_INVENTORY_ANALYST,
    ROLE_INVENTORY_SUPERVISOR,
    ROLE_SHRINK_CONTROLLER,
    ROLE_STORE_OPS,
    ROLE_THIRD_PARTY_COUNTER,
    ROLE_VENDOR_REP,
    SUPERVISOR,
    headers_for,
    headers_without_role,
    make_counter_headers,
    make_store_ops_headers,
    make_vendor_rep_headers,
)

NON_ADMIN_ROLES = (
    ROLE_INVENTORY_ANALYST,
    ROLE_INVENTORY_SUPERVISOR,
    ROLE_SHRINK_CONTROLLER,
    ROLE_STORE_OPS,
    ROLE_VENDOR_REP,
    ROLE_THIRD_PARTY_COUNTER,
)


def _read_period(api, shrink_period_id):
    """Read one shrink period as the controller who owns its closure."""
    return validate_success(api.get_shrink_period(shrink_period_id, CONTROLLER))


class TestReferenceDataIsAdminOnly:
    def test_an_analyst_may_not_register_a_category(self, api):
        """
        The write is refused while the read stays open.

        "When the headers are well-formed but the declared role is not among the roles
        authorized for the requested operation in §4, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/reference_data_writes_by_non_admin_roles_return_forbidden
        """
        validate_error(
            api.create_category(f.apparel_category_payload(), ANALYST),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )

        rows, meta = validate_paginated(api.list_categories(ANALYST))
        assert rows == []
        assert meta["total_count"] == 0

        created = validate_success(
            api.create_category(f.apparel_category_payload(), ADMIN), 201
        )
        assert created["code"] == "APPAREL"

    def test_every_other_role_is_refused_the_identical_write(self, api):
        """
        Six roles, one payload, one error identifier.

        "`SystemAdmin` owns reference data. It registers merchandise categories, stores,
        vendors, SKUs and third-party counting firms, opens stock positions, may open and
        encode tag batches, may schedule and abandon physical inventories, drives the
        logical clock, and may perform every read in the system."

        Design: Corner/rbac/reference_data_writes_by_non_admin_roles_return_forbidden
        """
        for role in NON_ADMIN_ROLES:
            validate_error(
                api.create_category(
                    f.apparel_category_payload(), headers_for(role, "u_actor_1")
                ),
                ERR_ROLE_NOT_PERMITTED,
                403,
            )

        validate_success(api.create_category(f.apparel_category_payload(), ADMIN), 201)
        rows, meta = validate_paginated(api.list_categories(ADMIN))
        assert meta["total_count"] == 1
        assert rows[0]["code"] == "APPAREL"

    def test_the_whole_reference_surface_and_the_clock_move_together(self, api):
        """
        Stores, vendors, firms, SKUs and the logical clock share the one grant.

        "When the headers are well-formed but the declared role is not among the roles
        authorized for the requested operation in §4, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/reference_data_writes_by_non_admin_roles_return_forbidden
        """
        category = fx.create_category(api, f.apparel_category_payload())
        vendor = fx.create_vendor(api)

        refused = (
            api.create_category(
                f.apparel_category_payload(code="SEASONAL", name="Seasonal"),
                CONTROLLER,
            ),
            api.create_store(f.store_payload(), CONTROLLER),
            api.create_vendor(f.vendor_payload(code="VEND9"), CONTROLLER),
            api.create_counter_firm(f.counter_firm_payload(), CONTROLLER),
            api.create_item(f.item_payload(category["id"], vendor["id"]), CONTROLLER),
            api.set_clock(DEFAULT_CLOCK_UTC, CONTROLLER),
        )
        for response in refused:
            validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)

        store = validate_success(api.create_store(f.store_payload(), ADMIN), 201)
        assert store["code"] == "S100"
        firm = validate_success(
            api.create_counter_firm(f.counter_firm_payload(), ADMIN), 201
        )
        assert firm["code"] == "CF1"
        item = validate_success(
            api.create_item(f.item_payload(category["id"], vendor["id"]), ADMIN), 201
        )
        assert item["sku"] == "TEE-001"
        clock = validate_success(api.set_clock(DEFAULT_CLOCK_UTC, ADMIN))
        assert clock["current_utc"] == DEFAULT_CLOCK_UTC


class TestShrinkClosureAndVendorMoneyAreControllerOnly:
    def test_a_supervisor_may_open_a_period_but_never_close_it(self, api):
        """
        The shared open operation frames the exclusive closure.

        "`ShrinkController` is the financial owner of shrink. It alone provisionally
        closes, reopens and finally closes shrink periods, issues vendor chargebacks and
        chargeback credits, reconciles and certifies physical inventories, and approves
        adjustments whose value impact exceeds the supervisor's single-approval cap."

        Design: Corner/rbac/shrink_closure_and_chargeback_ops_by_supervisor_return_forbidden
        """
        store = fx.create_store(api, f.store_payload())
        period = validate_success(
            api.create_shrink_period(f.shrink_period_payload(store["id"]), SUPERVISOR),
            201,
        )
        assert period["status"] == "OPEN"

        validate_error(
            api.provisional_close_shrink_period(period["id"], SUPERVISOR),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )
        assert _read_period(api, period["id"])["status"] == "OPEN"

        closed = validate_success(
            api.provisional_close_shrink_period(period["id"], CONTROLLER)
        )
        assert closed["status"] == "PROVISIONAL_CLOSED"

    def test_reopen_and_final_close_are_closed_to_every_other_role(self, api):
        """
        The two remaining closure verbs follow the same grant.

        "`ShrinkController` is the financial owner of shrink. It alone provisionally
        closes, reopens and finally closes shrink periods, issues vendor chargebacks and
        chargeback credits, reconciles and certifies physical inventories, and approves
        adjustments whose value impact exceeds the supervisor's single-approval cap."

        Design: Corner/rbac/shrink_closure_and_chargeback_ops_by_supervisor_return_forbidden
        """
        store = fx.create_store(api, f.store_payload())
        period = fx.create_shrink_period(api, store["id"])
        validate_success(api.provisional_close_shrink_period(period["id"], CONTROLLER))

        for headers in (SUPERVISOR, ANALYST, ADMIN):
            validate_error(
                api.reopen_shrink_period(period["id"], headers),
                ERR_ROLE_NOT_PERMITTED,
                403,
            )
            validate_error(
                api.final_close_shrink_period(period["id"], headers),
                ERR_ROLE_NOT_PERMITTED,
                403,
            )
        assert _read_period(api, period["id"])["status"] == "PROVISIONAL_CLOSED"

        reopened = validate_success(api.reopen_shrink_period(period["id"], CONTROLLER))
        assert reopened["status"] == "OPEN"

    def test_the_two_vendor_money_paths_are_controller_only(self, api):
        """
        Neither a chargeback nor a credit may be authored by a supervisor.

        "`ShrinkController` is the financial owner of shrink. It alone provisionally
        closes, reopens and finally closes shrink periods, issues vendor chargebacks and
        chargeback credits, reconciles and certifies physical inventories, and approves
        adjustments whose value impact exceeds the supervisor's single-approval cap."

        Design: Corner/rbac/shrink_closure_and_chargeback_ops_by_supervisor_return_forbidden
        """
        store = fx.create_store(api, f.store_payload())
        vendor = fx.create_vendor(api)
        period = fx.create_shrink_period(api, store["id"])

        for headers in (SUPERVISOR, ANALYST, ADMIN):
            validate_error(
                api.create_chargeback(
                    vendor["id"], f.chargeback_payload(period["id"]), headers
                ),
                ERR_ROLE_NOT_PERMITTED,
                403,
            )
            validate_error(
                api.create_chargeback_credit(
                    vendor["id"], f.chargeback_credit_payload(1000), headers
                ),
                ERR_ROLE_NOT_PERMITTED,
                403,
            )

        settled = fx.read_vendor(api, vendor["id"])
        assert settled["chargeback_balance_cents"] == 0
        assert settled["lifetime_chargeback_gross_cents"] == 0
        assert settled["credited_cents"] == 0

    def test_reconcile_and_certify_are_controller_only_while_recount_is_shared(self, api):
        """
        The supervisor holds the recount but neither of the closing verbs.

        "`InventorySupervisor` is the store-level approver. It approves, rejects, posts
        and reverses adjustments it did not itself request, approves and returns cause
        proposals it did not itself make, closes investigations, returns counts to the
        floor, reconciles and voids count tasks, pauses and resumes count schedules,
        receives, verifies, reworks and scraps tag batches, opens shrink periods, and
        orders physical-inventory recounts."

        Design: Corner/rbac/shrink_closure_and_chargeback_ops_by_supervisor_return_forbidden
        """
        world = fx.physical_inventory_world(api)
        inventory_id = world["physical_inventory_id"]

        validate_error(
            api.reconcile_physical_inventory(inventory_id, SUPERVISOR),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            api.certify_physical_inventory(inventory_id, SUPERVISOR),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            api.order_recount(inventory_id, SUPERVISOR),
            ERR_PHYSICAL_INVENTORY_INVALID_STATE,
            409,
        )
        assert fx.read_physical_inventory(api, inventory_id)["status"] == "PLANNED"


class TestCountAdjudicationIsSupervisorSide:
    def test_an_analyst_may_build_a_schedule_but_not_pause_it(self, api):
        """
        Building the calendar and controlling it are different grants.

        "`InventorySupervisor` is the store-level approver. It approves, rejects, posts
        and reverses adjustments it did not itself request, approves and returns cause
        proposals it did not itself make, closes investigations, returns counts to the
        floor, reconciles and voids count tasks, pauses and resumes count schedules,
        receives, verifies, reworks and scraps tag batches, opens shrink periods, and
        orders physical-inventory recounts."

        Design: Corner/rbac/count_calendar_control_ops_by_analyst_return_forbidden
        """
        category = fx.create_category(api, f.apparel_category_payload())
        store = fx.create_store(api, f.store_payload())
        schedule = validate_success(
            api.create_count_schedule(
                f.count_schedule_payload(store["id"], category["id"]), ANALYST
            ),
            201,
        )
        assert schedule["status"] == "ACTIVE"

        validate_error(
            api.pause_count_schedule(schedule["id"], ANALYST),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )
        assert fx.read_schedule(api, schedule["id"])["status"] == "ACTIVE"

        paused = validate_success(api.pause_count_schedule(schedule["id"], SUPERVISOR))
        assert paused["status"] == "PAUSED"
        resumed = validate_success(
            api.resume_count_schedule(schedule["id"], SUPERVISOR)
        )
        assert resumed["status"] == "ACTIVE"

    def test_the_analyst_who_produced_the_count_may_not_adjudicate_it(self, api):
        """
        Return, reconcile and void are all closed to the counting side.

        "`InventoryAnalyst` is the day-to-day integrity analyst. It opens stock positions,
        runs integrity scans, requests on-hand adjustments, builds cycle-count schedules
        and tasks, starts counts, records counted lines, submits counts, assigns
        investigators and proposes root causes. It approves nothing."

        Design: Corner/rbac/count_calendar_control_ops_by_analyst_return_forbidden
        """
        world = fx.counted_variance_world(api, counted_units=90, baseline=100)
        task_id = world["task_id"]
        assert fx.read_task(api, task_id)["status"] == "COUNTED"

        for response in (
            api.return_count_task_to_count(task_id, ANALYST),
            api.reconcile_count_task(task_id, ANALYST),
            api.void_count_task(task_id, ANALYST),
        ):
            validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)
        assert fx.read_task(api, task_id)["status"] == "COUNTED"

        returned = validate_success(
            api.return_count_task_to_count(task_id, SUPERVISOR)
        )
        assert returned["status"] == "IN_PROGRESS"
        assert returned["recount_round"] == 1

    def test_the_controller_holds_the_same_calendar_controls(self, api):
        """
        Both adjudicating roles are listed on the schedule verbs.

        "When the headers are well-formed but the declared role is not among the roles
        authorized for the requested operation in §4, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/count_calendar_control_ops_by_analyst_return_forbidden
        """
        category = fx.create_category(api, f.apparel_category_payload())
        store = fx.create_store(api, f.store_payload())
        schedule = fx.create_schedule(api, store["id"], category["id"])

        validate_error(
            api.resume_count_schedule(schedule["id"], ANALYST),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )

        paused = validate_success(api.pause_count_schedule(schedule["id"], CONTROLLER))
        assert paused["status"] == "PAUSED"
        resumed = validate_success(
            api.resume_count_schedule(schedule["id"], CONTROLLER)
        )
        assert resumed["status"] == "ACTIVE"


class TestStoreOpsHasTheNarrowestSurface:
    def test_the_receiving_crew_may_not_author_an_adjustment(self, api):
        """
        A perfectly current version quote does not widen the grant.

        "When the headers are well-formed but the declared role is not among the roles
        authorized for the requested operation in §4, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/store_ops_write_outside_the_counting_surface_returns_forbidden
        """
        world = fx.apparel_reference_world(api)
        store_headers = make_store_ops_headers(world["store_id"])
        version = fx.position_version(api, world["position_id"])

        validate_error(
            api.create_adjustment(
                world["position_id"],
                f.adjustment_payload(-3, version, reason_code="COUNT_VARIANCE"),
                store_headers,
            ),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )

        rows, meta = validate_paginated(api.list_adjustments(ANALYST))
        assert rows == []
        assert meta["total_count"] == 0
        assert fx.read_position(api, world["position_id"])["on_hand_units"] == 100

    def test_the_analyst_side_writes_are_all_closed_to_store_ops(self, api):
        """
        Schedules, positions and integrity scans belong to the analyst.

        "`InventoryAnalyst` is the day-to-day integrity analyst. It opens stock positions,
        runs integrity scans, requests on-hand adjustments, builds cycle-count schedules
        and tasks, starts counts, records counted lines, submits counts, assigns
        investigators and proposes root causes. It approves nothing."

        Design: Corner/rbac/store_ops_write_outside_the_counting_surface_returns_forbidden
        """
        world = fx.apparel_reference_world(api)
        store_headers = make_store_ops_headers(world["store_id"])

        for response in (
            api.create_count_schedule(
                f.count_schedule_payload(world["store_id"], world["category_id"]),
                store_headers,
            ),
            api.create_stock_position(
                f.stock_position_payload(world["store_id"], world["item_id"]),
                store_headers,
            ),
            api.run_integrity_scan(world["position_id"], store_headers),
        ):
            validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)

        rows, meta = validate_paginated(api.list_stock_positions(ANALYST))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == world["position_id"]

    def test_store_ops_does_not_carry_the_blanket_read_grant(self, api):
        """
        The four opaque roles read the position; the store crew does not.

        "When the headers are well-formed but the declared role is not among the roles
        authorized for the requested operation in §4, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/store_ops_write_outside_the_counting_surface_returns_forbidden
        """
        world = fx.apparel_reference_world(api)
        store_headers = make_store_ops_headers(world["store_id"])

        validate_error(
            api.list_stock_positions(store_headers), ERR_ROLE_NOT_PERMITTED, 403
        )
        validate_error(
            api.get_stock_position(world["position_id"], store_headers),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )

        for headers in (ADMIN, ANALYST, SUPERVISOR, CONTROLLER):
            position = validate_success(
                api.get_stock_position(world["position_id"], headers)
            )
            assert position["id"] == world["position_id"]


class TestVendorRepIsScopedToItsOwnVendor:
    def test_a_second_vendor_may_not_encode_the_first_vendors_batch(self, api):
        """
        The scoping comparison is against the batch's own vendor.

        "When `X-User-Role` is `VendorRep`, `X-User-ID` is the `id` of the acting
        `Vendor`; ownership checks compare a tag batch's `vendor_id`, or the vendor
        identifier named in the request path, to `X-User-ID`. When `X-User-Role` is
        `ThirdPartyCounter`, `X-User-ID` is the `id` of the acting `CounterFirm`;
        ownership checks compare a physical inventory's `counter_firm_id` to `X-User-ID`.
        A write attempted by one of these three roles against a resource scoped to a
        different entity is rejected with `ERR_IDENTITY_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/vendor_rep_encode_of_another_vendors_batch_returns_forbidden
        """
        world = fx.apparel_reference_world(api)
        other_vendor = fx.create_vendor(api, f.vendor_payload(code="VEND2"))
        owner = make_vendor_rep_headers(world["vendor_id"])
        rival = make_vendor_rep_headers(other_vendor["id"])

        batch = validate_success(
            api.create_tag_batch(
                f.tag_batch_payload(
                    world["vendor_id"], world["item_id"], world["store_id"]
                ),
                owner,
            ),
            201,
        )
        assert batch["status"] == "DRAFT"

        validate_error(
            api.encode_tag_batch(batch["id"], f.encode_payload(), rival),
            ERR_IDENTITY_SCOPE_VIOLATION,
            403,
        )
        assert fx.read_tag_batch(api, batch["id"])["status"] == "DRAFT"

        encoded = validate_success(
            api.encode_tag_batch(batch["id"], f.encode_payload(), owner)
        )
        assert encoded["status"] == "ENCODED"
        assert encoded["encoding_scheme"] == "SGTIN_96"

    def test_the_body_vendor_and_the_header_vendor_must_agree(self, api):
        """
        A batch may not be opened in another vendor's name.

        "When `X-User-Role` is `VendorRep`, `X-User-ID` is the `id` of the acting
        `Vendor`; ownership checks compare a tag batch's `vendor_id`, or the vendor
        identifier named in the request path, to `X-User-ID`. When `X-User-Role` is
        `ThirdPartyCounter`, `X-User-ID` is the `id` of the acting `CounterFirm`;
        ownership checks compare a physical inventory's `counter_firm_id` to `X-User-ID`.
        A write attempted by one of these three roles against a resource scoped to a
        different entity is rejected with `ERR_IDENTITY_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/vendor_rep_encode_of_another_vendors_batch_returns_forbidden
        """
        world = fx.apparel_reference_world(api)
        other_vendor = fx.create_vendor(api, f.vendor_payload(code="VEND2"))
        payload = f.tag_batch_payload(
            world["vendor_id"], world["item_id"], world["store_id"]
        )

        validate_error(
            api.create_tag_batch(payload, make_vendor_rep_headers(other_vendor["id"])),
            ERR_IDENTITY_SCOPE_VIOLATION,
            403,
        )
        rows, meta = validate_paginated(api.list_tag_batches(ADMIN))
        assert rows == []
        assert meta["total_count"] == 0

        accepted = validate_success(
            api.create_tag_batch(
                payload, make_vendor_rep_headers(world["vendor_id"])
            ),
            201,
        )
        assert accepted["status"] == "DRAFT"
        assert accepted["vendor_id"] == world["vendor_id"]


def _counter_line(api, world, counted_units, headers=None):
    """Submit a physical-inventory line quoting the inventory's live version."""
    current = validate_success(
        api.get_physical_inventory(world["physical_inventory_id"], CONTROLLER)
    )
    return api.create_physical_inventory_line(
        world["physical_inventory_id"],
        f.physical_line_payload(world["item_id"], counted_units, current["version"]),
        headers or world["counter_headers"],
    )


class TestTheCountingFirmCannotBlessItsOwnWork:
    @staticmethod
    def _completed_first_pass(api):
        """A first pass counted and closed by the assigned firm itself."""
        world = fx.physical_inventory_world(api)
        validate_success(
            api.start_physical_inventory(
                world["physical_inventory_id"], world["counter_headers"]
            )
        )
        validate_success(_counter_line(api, world, 100), 201)
        completed = validate_success(
            api.complete_pass(
                world["physical_inventory_id"], world["counter_headers"]
            )
        )
        assert completed["status"] == "FIRST_PASS_COMPLETE"
        assert completed["net_variance_bps"] == 0
        return world

    def test_the_firm_holds_the_counting_verbs_but_not_the_reconcile(self, api):
        """
        Every state precondition is satisfied and only the role is wrong.

        "When the headers are well-formed but the declared role is not among the roles
        authorized for the requested operation in §4, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/third_party_counter_cannot_reconcile_or_certify_its_own_count_returns_forbidden
        """
        world = self._completed_first_pass(api)

        validate_error(
            api.reconcile_physical_inventory(
                world["physical_inventory_id"], world["counter_headers"]
            ),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )
        assert (
            fx.read_physical_inventory(api, world["physical_inventory_id"])["status"]
            == "FIRST_PASS_COMPLETE"
        )

        reconciled = validate_success(
            api.reconcile_physical_inventory(
                world["physical_inventory_id"], CONTROLLER
            )
        )
        assert reconciled["status"] == "RECONCILING"

    def test_certify_and_order_recount_are_closed_to_the_firm_as_well(self, api):
        """
        The firm's grant is exactly the three-verb counting window.

        "`ThirdPartyCounter` is the independent physical-inventory counting crew."

        Design: Corner/rbac/third_party_counter_cannot_reconcile_or_certify_its_own_count_returns_forbidden
        """
        world = self._completed_first_pass(api)

        validate_error(
            api.certify_physical_inventory(
                world["physical_inventory_id"], world["counter_headers"]
            ),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            api.order_recount(
                world["physical_inventory_id"], world["counter_headers"]
            ),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )

        recounting = validate_success(
            api.order_recount(world["physical_inventory_id"], SUPERVISOR)
        )
        assert recounting["status"] == "COUNTING"
        assert recounting["recount_round"] == 1


class TestPhysicalInventoryScopeFollowsTheAssignedFirm:
    def test_a_rival_firm_may_not_submit_a_line(self, api):
        """
        A current version quote is refused as out of scope, not as stale.

        "When `X-User-Role` is `ThirdPartyCounter`, `X-User-ID` is the `id` of the acting
        `CounterFirm`; ownership checks compare a physical inventory's `counter_firm_id`
        to `X-User-ID`. A write attempted by one of these three roles against a resource
        scoped to a different entity is rejected with `ERR_IDENTITY_SCOPE_VIOLATION`
        (HTTP 403)."

        Design: Corner/rbac/third_party_counter_line_on_another_firms_inventory_returns_forbidden
        """
        world = fx.physical_inventory_world(api)
        rival_firm = fx.create_counter_firm(
            api,
            f.counter_firm_payload(
                code="CF2",
                name="Counting Firm Two",
                certification_level="TIER_2",
                max_lines_per_pass=200,
            ),
        )
        validate_success(
            api.start_physical_inventory(
                world["physical_inventory_id"], world["counter_headers"]
            )
        )

        validate_error(
            _counter_line(
                api, world, 77, headers=make_counter_headers(rival_firm["id"])
            ),
            ERR_IDENTITY_SCOPE_VIOLATION,
            403,
        )
        rows, meta = validate_paginated(
            api.list_physical_inventory_lines(
                ANALYST, {"physical_inventory_id": world["physical_inventory_id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

        line = validate_success(_counter_line(api, world, 77), 201)
        assert line["counted_units"] == 77
        assert line["superseded"] is False

    def test_start_and_complete_pass_are_scoped_the_same_way(self, api):
        """
        All three counting verbs read the inventory's assigned firm.

        "When `X-User-Role` is `ThirdPartyCounter`, `X-User-ID` is the `id` of the acting
        `CounterFirm`; ownership checks compare a physical inventory's `counter_firm_id`
        to `X-User-ID`. A write attempted by one of these three roles against a resource
        scoped to a different entity is rejected with `ERR_IDENTITY_SCOPE_VIOLATION`
        (HTTP 403)."

        Design: Corner/rbac/third_party_counter_line_on_another_firms_inventory_returns_forbidden
        """
        world = fx.physical_inventory_world(api)
        rival_firm = fx.create_counter_firm(
            api,
            f.counter_firm_payload(
                code="CF2",
                name="Counting Firm Two",
                certification_level="TIER_2",
                max_lines_per_pass=200,
            ),
        )
        rival = make_counter_headers(rival_firm["id"])

        validate_error(
            api.start_physical_inventory(world["physical_inventory_id"], rival),
            ERR_IDENTITY_SCOPE_VIOLATION,
            403,
        )
        started = validate_success(
            api.start_physical_inventory(
                world["physical_inventory_id"], world["counter_headers"]
            )
        )
        assert started["status"] == "COUNTING"

        validate_success(_counter_line(api, world, 100), 201)
        validate_error(
            api.complete_pass(world["physical_inventory_id"], rival),
            ERR_IDENTITY_SCOPE_VIOLATION,
            403,
        )
        completed = validate_success(
            api.complete_pass(
                world["physical_inventory_id"], world["counter_headers"]
            )
        )
        assert completed["status"] == "FIRST_PASS_COMPLETE"


class TestCountTaskScopeFollowsTheSchedulesStore:
    @staticmethod
    def _task_at_the_first_store(api):
        """A SCHEDULED task at S100 alongside an unrelated second store."""
        world = fx.apparel_reference_world(api)
        world["other_store"] = fx.create_store(api, f.handheld_only_store_payload())
        schedule = fx.create_schedule(api, world["store_id"], world["category_id"])
        task = fx.create_task(api, schedule["id"])
        assert task["status"] == "SCHEDULED"
        assert task["store_id"] == world["store_id"]
        world["task_id"] = task["id"]
        return world

    def test_another_stores_crew_may_not_start_the_task(self, api):
        """
        The task's store is reached through the schedule that authorised it.

        "When `X-User-Role` is `StoreOps`, `X-User-ID` is the `id` of the acting `Store`;
        ownership checks on any resource that references a `Store` compare the resource's
        store-bearing field to `X-User-ID` — specifically a tag batch's
        `destination_store_id` and a count task's `store_id`."

        Design: Corner/rbac/store_ops_start_of_another_stores_count_task_returns_forbidden
        """
        world = self._task_at_the_first_store(api)

        validate_error(
            api.start_count_task(
                world["task_id"], make_store_ops_headers(world["other_store"]["id"])
            ),
            ERR_IDENTITY_SCOPE_VIOLATION,
            403,
        )
        assert fx.read_task(api, world["task_id"])["status"] == "SCHEDULED"

        started = validate_success(
            api.start_count_task(
                world["task_id"], make_store_ops_headers(world["store_id"])
            )
        )
        assert started["status"] == "IN_PROGRESS"
        assert started["in_scope_position_count"] == 1

    def test_lines_and_submit_are_scoped_to_the_tasks_store(self, api):
        """
        Every StoreOps verb on the task reads the same store-bearing field.

        "When `X-User-Role` is `StoreOps`, `X-User-ID` is the `id` of the acting `Store`;
        ownership checks on any resource that references a `Store` compare the resource's
        store-bearing field to `X-User-ID` — specifically a tag batch's
        `destination_store_id` and a count task's `store_id`."

        Design: Corner/rbac/store_ops_start_of_another_stores_count_task_returns_forbidden
        """
        world = self._task_at_the_first_store(api)
        owner = make_store_ops_headers(world["store_id"])
        rival = make_store_ops_headers(world["other_store"]["id"])
        validate_success(api.start_count_task(world["task_id"], owner))

        validate_error(
            api.create_count_line(
                world["task_id"], f.count_line_payload(world["item_id"], 100), rival
            ),
            ERR_IDENTITY_SCOPE_VIOLATION,
            403,
        )
        validate_error(
            api.submit_count_task(world["task_id"], rival),
            ERR_IDENTITY_SCOPE_VIOLATION,
            403,
        )

        validate_success(
            api.create_count_line(
                world["task_id"], f.count_line_payload(world["item_id"], 100), owner
            ),
            201,
        )
        submitted = validate_success(api.submit_count_task(world["task_id"], owner))
        assert submitted["status"] == "COUNTED"
        assert_pct(submitted["coverage_pct"], 100.00)

    def test_the_opaque_roles_need_no_scoping_identifier(self, api):
        """
        An operator identifier is never compared to a store.

        "When `X-User-Role` is `SystemAdmin`, `InventoryAnalyst`, `InventorySupervisor`
        or `ShrinkController`, `X-User-ID` is an opaque operator identifier not tied to
        any persisted entity. The server records it where a workflow step demands
        attribution — as `requested_by_user_id` and `approved_by_user_id` on an
        adjustment, and as `proposed_by_user_id` and `approved_by_user_id` on a variance
        investigation — but it never compares such a value to any entity's `id`."

        Design: Corner/rbac/store_ops_start_of_another_stores_count_task_returns_forbidden
        """
        world = self._task_at_the_first_store(api)

        started = validate_success(api.start_count_task(world["task_id"], ANALYST))
        assert started["status"] == "IN_PROGRESS"

        validate_success(
            api.create_count_line(
                world["task_id"], f.count_line_payload(world["item_id"], 100), ANALYST
            ),
            201,
        )
        submitted = validate_success(
            api.submit_count_task(world["task_id"], SUPERVISOR)
        )
        assert submitted["status"] == "COUNTED"


class TestRoleMembershipIsCheckedBeforePathResolution:
    def test_an_unauthorised_caller_cannot_use_404_as_an_existence_oracle(self, api):
        """
        A fictional identifier returns the same 403 a real one would.

        "1. Authentication of the two headers (`ERR_UNAUTHENTICATED`).
        2. Role authorization for the endpoint (`ERR_ROLE_NOT_PERMITTED`).
        3. Identity scope for the three entity-backed roles
        (`ERR_IDENTITY_SCOPE_VIOLATION`).
        4. Existence of every path identifier, left to right (the 404 family)."

        Design: Corner/rbac/role_membership_is_checked_before_path_resolution_returns_forbidden
        """
        validate_error(
            api.final_close_shrink_period(NON_EXISTENT_UUID, SUPERVISOR),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            api.final_close_shrink_period(NON_EXISTENT_UUID, headers_without_role()),
            ERR_UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.final_close_shrink_period(NON_EXISTENT_UUID, CONTROLLER),
            ERR_SHRINK_PERIOD_NOT_FOUND,
            404,
        )

    def test_an_unknown_scoping_identity_is_a_scope_violation_not_a_not_found(self, api):
        """
        Identity scope is settled one rung above path resolution.

        "1. Authentication of the two headers (`ERR_UNAUTHENTICATED`).
        2. Role authorization for the endpoint (`ERR_ROLE_NOT_PERMITTED`).
        3. Identity scope for the three entity-backed roles
        (`ERR_IDENTITY_SCOPE_VIOLATION`).
        4. Existence of every path identifier, left to right (the 404 family)."

        Design: Corner/rbac/role_membership_is_checked_before_path_resolution_returns_forbidden
        """
        world = fx.apparel_reference_world(api)
        schedule = fx.create_schedule(api, world["store_id"], world["category_id"])
        task = fx.create_task(api, schedule["id"])

        validate_error(
            api.start_count_task(
                task["id"], make_store_ops_headers(NON_EXISTENT_UUID)
            ),
            ERR_IDENTITY_SCOPE_VIOLATION,
            403,
        )
        assert fx.read_task(api, task["id"])["status"] == "SCHEDULED"
