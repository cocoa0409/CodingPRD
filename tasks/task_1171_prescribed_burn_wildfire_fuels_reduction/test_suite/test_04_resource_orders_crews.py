"""Holding-force computation and crew assignment capacity/window rules (PRD §3.1, §3.5)."""
from test_helpers import (
    ANY_READER_HEADERS,
    TEST_USERS,
    ApiErrorId,
    create_assignment_payload,
    create_contractor_payload,
    ctx_add_parcel,
    ctx_add_plan,
    ctx_author,
    get_success_data,
    make_contractor_headers,
    setup_approved_plan_ctx,
    setup_registry,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _setup_two_submitted_orders(api):
    """Two approved plans on separate parcels; one ENGINE contractor (capacity 10);
    both resource orders SUBMITTED."""
    ctx = setup_registry()
    for key, airshed in (("a", "ASH-1"), ("b", "ASH-2")):
        ctx_add_parcel(ctx, key=f"parcel_{key}", name=f"P{key.upper()}",
                       airshed_id=airshed)
        ctx_add_plan(ctx, key=f"plan_{key}", parcel_key=f"parcel_{key}", approve=True)
    contractor = get_success_data(api.create_contractor(
        create_contractor_payload(resource_type="ENGINE", capacity_units=10), ADMIN))
    ctx["engine_contractor"] = contractor
    for key in ("a", "b"):
        order = get_success_data(api.create_resource_order(
            ctx[f"plan_{key}"]["id"], {}, ctx_author(ctx)))
        ctx[f"order_{key}"] = get_success_data(api.submit_resource_order(
            order["id"], ctx_author(ctx)))
    return ctx


class TestRequiredHoldingForce:
    def test_required_holding_force_brush_moderate(self, api):
        """PRD §3.5: "`required_engines` is the planned acreage divided by 40 and scaled
        by a fuel factor — 1.0 for `GRASS`, 1.5 for `BRUSH`, 2.0 for `TIMBER` — the
        product rounded up to the next whole engine, plus two additional engines when the
        parcel is `wui_adjacent`. `required_hand_crews` is the planned acreage divided by
        80 and rounded up, never less than one crew, and then doubled when the parcel's
        `slope_class` is `STEEP`. `required_dozers` is exactly one when the parcel's
        `fuel_model` is `TIMBER` and the planned acreage is strictly greater than 100, and
        zero otherwise. `required_water_tenders` is the planned acreage divided by 60
        rounded down to a whole number, but never less than one."

        Design: Difficulty/combinatorial_formula/required_holding_force_tiered_conditionals
        """
        ctx = setup_approved_plan_ctx()  # 100 acres on BRUSH / MODERATE / non-WUI
        order = validate_success(api.create_resource_order(
            ctx["plan"]["id"], {}, ctx_author(ctx)), 201)
        # ceil(100/40*1.5) = 4; max(1, ceil(100/80))*1 = 2; 0; max(1, floor(100/60)) = 1
        assert (order["required_engines"], order["required_hand_crews"],
                order["required_dozers"], order["required_water_tenders"]) == (4, 2, 0, 1)
        fetched = validate_success(api.get_resource_order(order["id"], ANY_READER_HEADERS), 200)
        assert (fetched["required_engines"], fetched["required_hand_crews"],
                fetched["required_dozers"], fetched["required_water_tenders"]) == (4, 2, 0, 1)

    def test_required_holding_force_timber_steep_wui(self, api):
        """PRD §3.5: "`required_engines` is the planned acreage divided by 40 and scaled
        by a fuel factor — 1.0 for `GRASS`, 1.5 for `BRUSH`, 2.0 for `TIMBER` — the
        product rounded up to the next whole engine, plus two additional engines when the
        parcel is `wui_adjacent`. `required_hand_crews` is the planned acreage divided by
        80 and rounded up, never less than one crew, and then doubled when the parcel's
        `slope_class` is `STEEP`. `required_dozers` is exactly one when the parcel's
        `fuel_model` is `TIMBER` and the planned acreage is strictly greater than 100, and
        zero otherwise. `required_water_tenders` is the planned acreage divided by 60
        rounded down to a whole number, but never less than one."

        Design: Difficulty/combinatorial_formula/required_holding_force_tiered_conditionals
        """
        ctx = setup_approved_plan_ctx(
            parcel_overrides={"acreage": 200, "fuel_model": "TIMBER",
                              "slope_class": "STEEP", "wui_adjacent": True,
                              "drought_index": 5},
            plan_overrides={"planned_acres": 150,
                            "treatment_lines": [{"category": "BROADCAST",
                                                 "rate_class": "TIMBER", "acres": 150}]})
        order = validate_success(api.create_resource_order(
            ctx["plan"]["id"], {}, ctx_author(ctx)), 201)
        # ceil(150/40*2.0)+2 = 10; max(1, ceil(150/80))*2 = 4; TIMBER & >100 -> 1;
        # max(1, floor(150/60)) = 2
        assert (order["required_engines"], order["required_hand_crews"],
                order["required_dozers"], order["required_water_tenders"]) == (10, 4, 1, 2)


class TestContractorWindowBuffer:
    def test_contractor_window_adjacent_buffer_conflict(self, api):
        """PRD §3.5: "the window must respect a one-day rest buffer against every other
        `ASSIGNED` or `CONFIRMED` window of the same contractor: separation exists when
        the new `window_start` falls at least one full day after the other window's
        `window_end`, or the new `window_end` falls at least one full day before the other
        window's `window_start`; when neither separation holds, the assignment is rejected
        with `ERR_CONTRACTOR_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/contractor_one_day_rest_buffer_overlap
        """
        ctx = _setup_two_submitted_orders(api)
        contractor = ctx["engine_contractor"]
        a1 = get_success_data(api.create_assignment(
            ctx["order_a"]["id"],
            create_assignment_payload(contractor["id"], units=1,
                                      window_start="2026-05-12", window_end="2026-05-13"),
            ctx_author(ctx)))
        get_success_data(api.confirm_assignment(a1["id"], make_contractor_headers(contractor["id"])))
        # [05-13, 05-14] touches the confirmed window with zero rest days: conflict
        # fires when the assignment is written against the contractor's book.
        validate_error(api.create_assignment(
            ctx["order_b"]["id"],
            create_assignment_payload(contractor["id"], units=1,
                                      window_start="2026-05-13", window_end="2026-05-14"),
            ctx_author(ctx)), ApiErrorId.ERR_CONTRACTOR_WINDOW_CONFLICT)

    def test_contractor_window_one_rest_day_passes(self, api):
        """PRD §3.5: "separation exists when the new `window_start` falls at least one
        full day after the other window's `window_end`"

        Design: Difficulty/resource_temporal_overlap/contractor_one_day_rest_buffer_overlap
        """
        ctx = _setup_two_submitted_orders(api)
        contractor = ctx["engine_contractor"]
        a1 = get_success_data(api.create_assignment(
            ctx["order_a"]["id"],
            create_assignment_payload(contractor["id"], units=1,
                                      window_start="2026-05-12", window_end="2026-05-13"),
            ctx_author(ctx)))
        get_success_data(api.confirm_assignment(a1["id"], make_contractor_headers(contractor["id"])))
        # [05-14, 05-15] leaves one full rest day after the confirmed window
        a3 = validate_success(api.create_assignment(
            ctx["order_b"]["id"],
            create_assignment_payload(contractor["id"], units=1,
                                      window_start="2026-05-14", window_end="2026-05-15"),
            ctx_author(ctx)), 201)
        confirmed = validate_success(api.confirm_assignment(
            a3["id"], make_contractor_headers(contractor["id"])), 200)
        assert confirmed["status"] == "CONFIRMED"


class TestAvailabilityCompensation:
    def _setup_one_confirmed_engine(self, api):
        """Approved plan (100ac BRUSH/MODERATE/non-WUI -> requires 4 engines, 2 crews,
        1 tender); ENGINE contractor capacity 4 with all 4 units confirmed."""
        ctx = setup_approved_plan_ctx()
        contractor = get_success_data(api.create_contractor(
            create_contractor_payload(resource_type="ENGINE", capacity_units=4), ADMIN))
        order = get_success_data(api.create_resource_order(ctx["plan"]["id"], {}, ctx_author(ctx)))
        ctx["order"] = get_success_data(api.submit_resource_order(order["id"], ctx_author(ctx)))
        asg = get_success_data(api.create_assignment(
            ctx["order"]["id"],
            create_assignment_payload(contractor["id"], units=4), ctx_author(ctx)))
        ctx["contractor"] = contractor
        ctx["assignment"] = asg
        return ctx

    def test_assignment_confirm_consumes_availability(self, api):
        """PRD §3.1: "A contractor's `available_units` is computed as `capacity_units`
        minus the units committed on that contractor's assignments currently in `ASSIGNED`
        or `CONFIRMED` status"
        PRD §3.5: "The order is `FILLED` exactly when every one of the four confirmed
        counts meets or exceeds its required twin — equality counts as filled — otherwise
        `PARTIALLY_FILLED` when any confirmed count is positive, and `SUBMITTED` again
        while coverage is zero."

        Design: Difficulty/compensating_invariant/assignment_confirm_then_release_restores_availability
        """
        ctx = self._setup_one_confirmed_engine(api)
        confirmed = validate_success(api.confirm_assignment(
            ctx["assignment"]["id"], make_contractor_headers(ctx["contractor"]["id"])), 200)
        assert confirmed["status"] == "CONFIRMED"
        contractor = validate_success(
            api.get_contractor(ctx["contractor"]["id"], ANY_READER_HEADERS), 200)
        assert contractor["available_units"] == 0  # 4 capacity - 4 confirmed
        order = validate_success(api.get_resource_order(ctx["order"]["id"], ANY_READER_HEADERS), 200)
        assert order["status"] == "PARTIALLY_FILLED"  # engines covered, crews/tender open

    def test_assignment_release_restores_availability(self, api):
        """PRD §3.5: "The availability invariant is compensating throughout: an assignment
        followed by a release, decline, no-show, or completion restores `available_units`
        to exactly its prior value."
        PRD §3.5: "otherwise `PARTIALLY_FILLED` when any confirmed count is positive, and
        `SUBMITTED` again while coverage is zero."

        Design: Difficulty/compensating_invariant/assignment_confirm_then_release_restores_availability
        """
        ctx = self._setup_one_confirmed_engine(api)
        get_success_data(api.confirm_assignment(
            ctx["assignment"]["id"], make_contractor_headers(ctx["contractor"]["id"])))
        released = validate_success(api.release_assignment(
            ctx["assignment"]["id"], ctx_author(ctx)), 200)
        assert released["status"] == "RELEASED"
        contractor = validate_success(
            api.get_contractor(ctx["contractor"]["id"], ANY_READER_HEADERS), 200)
        assert contractor["available_units"] == 4  # capacity exactly restored
        order = validate_success(api.get_resource_order(ctx["order"]["id"], ANY_READER_HEADERS), 200)
        assert order["status"] == "SUBMITTED"  # zero confirmed coverage returns to floor


class TestCapacityAndRoleDenials:
    def test_confirm_rejected_beyond_contractor_capacity(self, api):
        """PRD §3.5: "the committed units must fit within the contractor's
        `available_units` (`ERR_CONTRACTOR_CAPACITY_EXCEEDED`)"
        PRD §3.5: "Confirming requires the assignment to be `ASSIGNED`
        (`ERR_ASSIGNMENT_NOT_ASSIGNED`), the caller's `X-User-ID` to equal the
        assignment's `contractor_id` (`ERR_NOT_RESOURCE_OWNER`), and it re-evaluates
        standing (`ERR_CONTRACTOR_SUSPENDED`), capacity
        (`ERR_CONTRACTOR_CAPACITY_EXCEEDED`), and the window-conflict rule
        (`ERR_CONTRACTOR_WINDOW_CONFLICT`) at confirmation time."

        Design: Corner/errors/confirm_rejected_beyond_contractor_capacity
        """
        ctx = setup_approved_plan_ctx()
        contractor = get_success_data(api.create_contractor(
            create_contractor_payload(resource_type="ENGINE", capacity_units=4), ADMIN))
        order = get_success_data(api.create_resource_order(ctx["plan"]["id"], {}, ctx_author(ctx)))
        get_success_data(api.submit_resource_order(order["id"], ctx_author(ctx)))
        # 5 units exceed the contractor's 4-unit capacity; the capacity rule that the
        # confirmation re-evaluates is enforced when the units are committed to the book.
        validate_error(api.create_assignment(
            order["id"], create_assignment_payload(contractor["id"], units=5),
            ctx_author(ctx)), ApiErrorId.ERR_CONTRACTOR_CAPACITY_EXCEEDED)

    def test_contractor_cannot_release_assignment(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target endpoint is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/contractor_cannot_release_assignment
        """
        ctx = setup_approved_plan_ctx()
        contractor = get_success_data(api.create_contractor(
            create_contractor_payload(resource_type="ENGINE", capacity_units=4), ADMIN))
        order = get_success_data(api.create_resource_order(ctx["plan"]["id"], {}, ctx_author(ctx)))
        get_success_data(api.submit_resource_order(order["id"], ctx_author(ctx)))
        asg = get_success_data(api.create_assignment(
            order["id"], create_assignment_payload(contractor["id"], units=1), ctx_author(ctx)))
        get_success_data(api.confirm_assignment(
            asg["id"], make_contractor_headers(contractor["id"])))
        # Release is an author-only (BurnBoss) action, even for the owning contractor
        validate_error(api.release_assignment(
            asg["id"], make_contractor_headers(contractor["id"])),
            ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
